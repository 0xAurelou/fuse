// fuse-capture records real-time market receipts. It has no chain execution path.
package main

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"log/slog"
	"os"
	"os/signal"
	"syscall"
	"time"

	"fuse/engine/internal/capture"
	"fuse/engine/internal/engine"
	"fuse/engine/internal/oracle"
)

func main() {
	if err := run(); err != nil {
		slog.Error("capture stopped", "error", err)
		os.Exit(1)
	}
}
func run() error {
	config := flag.String("config", "config/paper.json", "policy frozen before first receipt")
	output := flag.String("output", "", "dedicated persistent evidence directory (required)")
	endpoint := flag.String("oracle", "wss://api.hyperliquid.xyz/ws", "shared upstream for both connections")
	duration := flag.Duration("duration", 24*time.Hour, "wall-time capture duration, up to 7 days; no early success stopping")
	verify := flag.Bool("verify", false, "verify retained capture offline and exit")
	flag.Parse()
	if *verify {
		m, h, err := capture.Verify(*output)
		if err != nil {
			return err
		}
		return json.NewEncoder(os.Stdout).Encode(map[string]any{"manifest": m, "head": h})
	}
	if *output == "" || *duration <= 0 || *duration > 7*24*time.Hour {
		return fmt.Errorf("output required; duration must be (0,168h]")
	}
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
	var extra any
	if err = decoder.Decode(&extra); err != io.EOF {
		return fmt.Errorf("trailing policy JSON")
	}
	r, err := capture.Open(*output, *endpoint, p, *duration)
	if err != nil {
		return err
	}
	defer r.Close()
	parent, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	ctx, cancel := capture.WithWallDeadline(parent, r.Deadline())
	defer cancel(nil)
	failures := make(chan error, 1)
	slog.Info("prospective capture started", "directory", *output, "duration", *duration, "resuming_sequence", r.Head().Sequence, "upstream_independent", false)
	oracle.Collector{URL: *endpoint, Log: slog.Default(), Submit: func(_ context.Context, source string, raw json.RawMessage) error {
		if !time.Now().Before(r.Deadline()) {
			cancel(context.DeadlineExceeded)
			return nil
		}
		err := r.Append(source, raw)
		if errors.Is(err, capture.ErrDeadlineElapsed) {
			cancel(context.DeadlineExceeded)
			return nil
		}
		if err != nil {
			select {
			case failures <- err:
			default:
			}
			cancel(err)
		}
		return err
	}}.Run(ctx)
	select {
	case err := <-failures:
		return err
	default:
	}
	head := r.Head()
	if head.Sequence == 0 {
		return fmt.Errorf("no receipts collected")
	}
	return json.NewEncoder(os.Stdout).Encode(map[string]any{"sequence": head.Sequence, "receipt_hash": head.Hash, "last_at_ms": head.At, "duration_elapsed": errors.Is(context.Cause(ctx), context.DeadlineExceeded), "production_approved": false})
}
