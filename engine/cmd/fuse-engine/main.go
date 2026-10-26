package main

import (
	"bufio"
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"log/slog"
	"net"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"fuse/engine/internal/api"
	"fuse/engine/internal/engine"
	"fuse/engine/internal/oracle"
	"fuse/engine/internal/storage"
)

func main() {
	if err := run(); err != nil {
		slog.Error("engine stopped", "error", err)
		os.Exit(1)
	}
}
func run() error {
	config := flag.String("config", "config/paper.json", "explicit paper policy file")
	listen := flag.String("listen", "127.0.0.1:8080", "HTTP bind address")
	memory := flag.Bool("memory", false, "explicitly use ephemeral paper storage")
	paperDesk := flag.Bool("paper-desk", false, "loopback-only virtual accounts, 1000 paper USDC per account, automatic paper settlement; requires -memory")
	wsURL := flag.String("oracle", "", "optional HyperCore WebSocket URL; two receivers are opened")
	replay := flag.String("replay", "", "verify a JSONL journal offline, print final commitments and exit")
	commands := flag.String("commands", "", "run paper commands from JSONL offline and emit a replayable JSONL journal")
	origin := flag.String("origin", "http://127.0.0.1:8080", "wallet challenge domain and permitted browser origin")
	flag.Parse()
	raw, err := os.ReadFile(*config)
	if err != nil {
		return err
	}
	var p engine.Policy
	decoder := json.NewDecoder(bytes.NewReader(raw))
	decoder.DisallowUnknownFields()
	if err = decoder.Decode(&p); err != nil {
		return err
	}
	if err = p.Validate(); err != nil {
		return err
	}
	if *replay != "" {
		return verify(*replay, p)
	}
	if *commands != "" {
		return simulate(*commands, p)
	}
	if p.Mode != "paper" {
		return errors.New("use fuse-local serve for local contract execution")
	}
	if *paperDesk {
		host, _, err := net.SplitHostPort(*listen)
		if err != nil || net.ParseIP(host) == nil || !net.ParseIP(host).IsLoopback() || !*memory {
			return errors.New("paper desk requires explicit loopback IP and ephemeral -memory storage")
		}
		if *wsURL == "" {
			return errors.New("paper desk requires a live oracle URL")
		}
	}
	ctx, cancel := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer cancel()
	var store engine.Store
	if *memory {
		store = &storage.Memory{}
		slog.Warn("ephemeral paper storage; no crash durability")
	} else {
		url := os.Getenv("DATABASE_URL")
		if url == "" {
			return errors.New("DATABASE_URL required, or explicitly pass -memory for paper demos")
		}
		openCtx, stop := context.WithTimeout(ctx, 15*time.Second)
		defer stop()
		store, err = storage.OpenPostgres(openCtx, url)
		if err != nil {
			return err
		}
	}
	defer store.Close(context.Background()) //nolint:errcheck
	q, err := engine.Open(ctx, p, store)
	if err != nil {
		return err
	}
	if *paperDesk {
		if _, err = q.Execute(ctx, engine.Command{Key: "paper/desk/lp", Kind: "lp_fund", Amount: 1_000_000_000_000, At: time.Now().UnixMilli()}); err != nil {
			return err
		}
	}
	token := os.Getenv("FUSE_PAPER_ADMIN_TOKEN")
	if len(token) < 32 {
		return errors.New("FUSE_PAPER_ADMIN_TOKEN must contain at least 32 characters")
	}
	server := &api.Server{Q: q, Auth: api.NewAuth(*origin), AdminToken: token, Origin: *origin, PaperDesk: *paperDesk}
	httpServer := &http.Server{Addr: *listen, Handler: server.Handler(), ReadHeaderTimeout: 5 * time.Second, ReadTimeout: 10 * time.Second, WriteTimeout: 15 * time.Second, IdleTimeout: 60 * time.Second, MaxHeaderBytes: 16 << 10}
	workerDone := make(chan struct{})
	go func() { defer close(workerDone); ticks(ctx, q, *paperDesk) }()
	collectorDone := make(chan struct{})
	if *wsURL != "" {
		go func() {
			defer close(collectorDone)
			oracle.Collector{Assets: p.Assets(), URL: *wsURL, Sequencer: q, Log: slog.Default()}.Run(ctx)
		}()
	} else {
		close(collectorDone)
	}
	errCh := make(chan error, 1)
	go func() {
		slog.Info("paper engine listening", "address", *listen, "sequence", q.Snapshot().Sequence)
		errCh <- httpServer.ListenAndServe()
	}()
	select {
	case <-ctx.Done():
	case err = <-errCh:
		if !errors.Is(err, http.ErrServerClosed) {
			cancel()
		}
	}
	cancel()
	shutdown, stop := context.WithTimeout(context.Background(), 10*time.Second)
	defer stop()
	_ = httpServer.Shutdown(shutdown)
	<-workerDone
	<-collectorDone
	if errors.Is(err, http.ErrServerClosed) {
		return nil
	}
	return err
}

func ticks(ctx context.Context, q *engine.Sequencer, paperDesk bool) {
	ticker := time.NewTicker(250 * time.Millisecond)
	defer ticker.Stop()
	for {
		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
			err := q.Exclusive(func(w *engine.Writer) error {
				if _, err := w.Execute(ctx, engine.Command{Key: fmt.Sprintf("clock/%d", time.Now().UnixNano()), Kind: "tick", At: max(time.Now().UnixMilli(), w.At())}); err != nil {
					return err
				}
				if paperDesk {
					state := w.Snapshot()
					if state.Debt() > 0 || state.LossClearing > 0 {
						_, err := w.Execute(ctx, engine.Command{Key: fmt.Sprintf("paper/settle/%d", time.Now().UnixNano()), Kind: "paper_settle", At: max(time.Now().UnixMilli(), w.At())})
						return err
					}
				}
				return nil
			})
			if err != nil && ctx.Err() == nil {
				slog.Error("tick failed", "error", err)
				if !q.Ready() {
					return
				}
			}
		}
	}
}
func eachLine(path string, f func([]byte) error) error {
	file, err := os.Open(path)
	if err != nil {
		return err
	}
	defer file.Close()
	scanner := bufio.NewScanner(file)
	scanner.Buffer(make([]byte, 64<<10), 64<<20)
	line := 0
	for scanner.Scan() {
		line++
		if err = f(scanner.Bytes()); err != nil {
			return fmt.Errorf("line %d: %w", line, err)
		}
	}
	return scanner.Err()
}
func verify(path string, p engine.Policy) error {
	s, err := engine.NewState(p)
	if err != nil {
		return err
	}
	seen := map[string]bool{}
	err = eachLine(path, func(raw []byte) error {
		var e engine.Event
		if err := json.Unmarshal(raw, &e); err != nil {
			return err
		}
		if seen[e.Command.Key] {
			return errors.New("duplicate command key")
		}
		seen[e.Command.Key] = true
		next, got, err := engine.Apply(s, e.Command)
		if err != nil {
			return err
		}
		if engine.Hash(got) != engine.Hash(e) {
			return fmt.Errorf("replay divergence at %d", e.Sequence)
		}
		s = next
		return nil
	})
	if err != nil {
		return err
	}
	return json.NewEncoder(os.Stdout).Encode(map[string]any{"sequence": s.Sequence, "state_hash": s.Digest(), "journal_hash": s.JournalHash, "oracle_hash": s.Oracle.JournalHash})
}
func simulate(path string, p engine.Policy) error {
	q, err := engine.Open(context.Background(), p, &storage.Memory{})
	if err != nil {
		return err
	}
	emitted := map[uint64]bool{}
	return eachLine(path, func(raw []byte) error {
		var c engine.Command
		d := json.NewDecoder(bytes.NewReader(raw))
		d.DisallowUnknownFields()
		if err := d.Decode(&c); err != nil {
			return err
		}
		e, err := q.Execute(context.Background(), c)
		if err != nil {
			return err
		}
		if emitted[e.Sequence] {
			return nil
		}
		emitted[e.Sequence] = true
		return json.NewEncoder(os.Stdout).Encode(e)
	})
}
