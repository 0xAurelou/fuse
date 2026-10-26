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
