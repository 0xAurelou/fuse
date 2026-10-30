package capture

import (
	"context"
	"encoding/json"
	"fuse/engine/internal/oracle"
	"github.com/gorilla/websocket"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"
)

func TestCollectorRetainsBothSourcesAndVerifiesAfterRestart(t *testing.T) {
	upgrader := websocket.Upgrader{}
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, req *http.Request) {
		conn, err := upgrader.Upgrade(w, req, nil)
		if err != nil {
			return
		}
		defer conn.Close()
		if _, _, err = conn.ReadMessage(); err != nil {
			return
		}
		if err = conn.WriteMessage(websocket.TextMessage, price); err != nil {
			return
		}
		for {
			if _, _, err = conn.ReadMessage(); err != nil {
				return
			}
		}
	}))
	defer server.Close()
	dir := t.TempDir()
	r, p := openTest(t, dir)
	// Recreate with the actual test endpoint pinned before the first receipt.
	r.Close()
	dir = t.TempDir()
	endpoint := "ws" + strings.TrimPrefix(server.URL, "http")
	r, err := Open(dir, endpoint, p, time.Hour)
	if err != nil {
		t.Fatal(err)
	}
	r.now = func() time.Time { return time.UnixMilli(r.manifest.FrozenAt + 1) }
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	var mu sync.Mutex
	seen := map[string]bool{}
	var appendErr error
	oracle.Collector{URL: endpoint, Log: slog.Default(), Submit: func(_ context.Context, source string, raw json.RawMessage) error {
		err := r.Append(source, raw)
		mu.Lock()
		defer mu.Unlock()
		if err != nil {
			appendErr = err
			cancel()
			return err
		}
		seen[source] = true
		if len(seen) == 2 {
			cancel()
		}
		return nil
	}}.Run(ctx)
	if appendErr != nil || len(seen) != 2 {
		t.Fatalf("collector evidence: %v %v", seen, appendErr)
	}
	head := r.Head()
	r.Close()
	_, verified, err := Verify(dir)
	if err != nil || verified.Hash != head.Hash || verified.Sequence != 2 {
		t.Fatalf("offline verification: %v", err)
	}
}

func TestWallDeadlineStopsBothSilentSocketsAfterSimulatedResume(t *testing.T) {
	upgrader := websocket.Upgrader{}
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, req *http.Request) {
		conn, err := upgrader.Upgrade(w, req, nil)
		if err != nil {
			return
		}
		defer conn.Close()
		if _, _, err = conn.ReadMessage(); err != nil {
			return
		}
		if err = conn.WriteMessage(websocket.TextMessage, price); err != nil {
			return
		}
		// Keep both sockets connected but stop delivering market messages.
		for {
			if _, _, err = conn.ReadMessage(); err != nil {
				return
			}
		}
	}))
	defer server.Close()
	initial, p := openTest(t, t.TempDir())
	initial.Close()
	dir := t.TempDir()
	endpoint := "ws" + strings.TrimPrefix(server.URL, "http")
	r, err := Open(dir, endpoint, p, 8*time.Hour)
	if err != nil {
		t.Fatal(err)
	}
	defer r.Close()
	var clock atomic.Int64
	clock.Store(r.manifest.FrozenAt + 1)
	r.now = func() time.Time { return time.UnixMilli(clock.Load()) }
	checks := make(chan time.Time)
	ctx, cancel := withWallDeadline(context.Background(), r.Deadline(), r.now, checks)
	defer cancel(nil)
	seen := make(chan string, 2)
	done := make(chan struct{})
	go func() {
		defer close(done)
		oracle.Collector{URL: endpoint, Log: slog.Default(), Submit: func(_ context.Context, source string, raw json.RawMessage) error {
			err := r.Append(source, raw)
			if err == nil {
				seen <- source
			}
			return err
		}}.Run(ctx)
	}()
	for i := 0; i < 2; i++ {
		select {
		case <-seen:
		case <-time.After(5 * time.Second):
			t.Fatal("fixture did not connect both receivers")
		}
	}
	head := r.Head()
	clock.Store(r.Deadline().Add(16 * time.Hour).UnixMilli())
	checks <- time.UnixMilli(r.manifest.FrozenAt + 1000)
	select {
	case <-done:
	case <-time.After(time.Second):
		t.Fatal("silent sockets survived wall deadline cancellation")
	}
	awaitCancellation(t, ctx, context.DeadlineExceeded)
	r.Close()
	m, verified, err := Verify(dir)
	if err != nil || verified.Hash != head.Hash || verified.Sequence != 2 || m.DurationMS != (8*time.Hour).Milliseconds() {
		t.Fatalf("simulated resume changed evidence or horizon: %v", err)
	}
}
