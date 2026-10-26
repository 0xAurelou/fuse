package oracle

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"os"
	"strings"
	"testing"
	"time"

	"fuse/engine/internal/engine"
	"fuse/engine/internal/storage"
	"github.com/gorilla/websocket"
)

func TestCollectorPairsThreeMarketsWithoutMixingSources(t *testing.T) {
	raw, err := os.ReadFile("../../config/paper.json")
	if err != nil {
		t.Fatal(err)
	}
	var policy engine.Policy
	if err := json.Unmarshal(raw, &policy); err != nil {
		t.Fatal(err)
	}
	q, err := engine.Open(context.Background(), policy, &storage.Memory{})
	if err != nil {
		t.Fatal(err)
	}
	errors := make(chan error, 8)
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		conn, err := (&websocket.Upgrader{}).Upgrade(w, r, nil)
		if err != nil {
			errors <- err
			return
		}
		defer conn.Close()
		coins := map[string]bool{}
		for i := 0; i < 3; i++ {
			var subscription struct {
				Subscription struct {
					Type string `json:"type"`
					Coin string `json:"coin"`
				} `json:"subscription"`
			}
			if err := conn.ReadJSON(&subscription); err != nil {
				errors <- err
				return
			}
			if subscription.Subscription.Type != "activeAssetCtx" || !engine.SupportedAsset(subscription.Subscription.Coin) || coins[subscription.Subscription.Coin] {
				errors <- fmt.Errorf("bad multi-market subscription")
				return
			}
			coins[subscription.Subscription.Coin] = true
		}
		for asset, price := range map[string]string{"BTC": "100000", "ETH": "3000", "HYPE": "40"} {
			if err := conn.WriteMessage(websocket.TextMessage, []byte(fmt.Sprintf(`{"channel":"activeAssetCtx","data":{"coin":%q,"ctx":{"oraclePx":%q}}}`, asset, price))); err != nil {
				errors <- err
				return
			}
		}
		for {
			if _, _, err := conn.ReadMessage(); err != nil {
				return
			}
		}
	}))
	defer server.Close()
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	done := make(chan struct{})
	go func() {
		defer close(done)
		Collector{Assets: policy.Assets(), URL: "ws" + strings.TrimPrefix(server.URL, "http"), Sequencer: q, Log: slog.New(slog.NewTextHandler(io.Discard, nil))}.Run(ctx)
	}()
	for {
		state := q.Snapshot()
		allHealthy := true
		for _, asset := range policy.Assets() {
			allHealthy = allHealthy && state.HealthyAsset(asset, time.Now().UnixMilli())
		}
		if allHealthy {
			break
		}
		select {
		case err := <-errors:
			t.Fatal(err)
		case <-ctx.Done():
			t.Fatal("three paired markets did not become healthy")
		case <-time.After(10 * time.Millisecond):
		}
	}
	cancel()
	select {
	case <-done:
	case <-time.After(time.Second):
		t.Fatal("collector did not stop")
	}
	state := q.Snapshot()
	if state.Oracle.Price != 100_000_000_000 || state.AssetOracle("ETH").Price != 3_000_000_000 || state.AssetOracle("HYPE").Price != 40_000_000 {
		t.Fatal("oracle prices crossed market boundaries")
	}
}

func TestTwoReceiversPersistRawAndCancel(t *testing.T) {
	raw, err := os.ReadFile("../../config/paper.json")
	if err != nil {
		t.Fatal(err)
	}
	var p engine.Policy
	_ = json.Unmarshal(raw, &p)
	q, err := engine.Open(context.Background(), p, &storage.Memory{})
	if err != nil {
		t.Fatal(err)
	}
	errors := make(chan error, 4)
	up := websocket.Upgrader{}
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		conn, err := up.Upgrade(w, r, nil)
		if err != nil {
			errors <- err
			return
		}
		defer conn.Close()
		var sub struct {
			Method       string                      `json:"method"`
			Subscription struct{ Type, Coin string } `json:"subscription"`
		}
		if err = conn.ReadJSON(&sub); err != nil {
			errors <- err
			return
		}
		if sub.Method != "subscribe" || sub.Subscription.Type != "activeAssetCtx" || sub.Subscription.Coin != "BTC" {
			errors <- io.ErrUnexpectedEOF
			return
		}
		if err = conn.WriteMessage(websocket.TextMessage, []byte(`{"channel":"activeAssetCtx","data":{"coin":"BTC","ctx":{"oraclePx":"100000","markPx":"90000"}}}`)); err != nil {
			errors <- err
			return
		}
		for {
			if _, _, err = conn.ReadMessage(); err != nil {
				return
			}
		}
	}))
	defer srv.Close()
	ctx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
	defer cancel()
	done := make(chan struct{})
	go func() {
		defer close(done)
		Collector{URL: "ws" + strings.TrimPrefix(srv.URL, "http"), Sequencer: q, Log: slog.New(slog.NewTextHandler(io.Discard, nil))}.Run(ctx)
	}()
	ticker := time.NewTicker(5 * time.Millisecond)
	defer ticker.Stop()
	for len(q.Snapshot().Oracle.Sources) < 2 {
		select {
		case err := <-errors:
			t.Fatal(err)
		case <-ctx.Done():
			t.Fatal("receivers failed to admit observations")
		case <-ticker.C:
		}
	}
	cancel()
	select {
	case <-done:
	case <-time.After(time.Second):
		t.Fatal("collector leaked on cancellation")
	}
	state := q.Snapshot()
	if state.Oracle.Sequence != 1 || state.Oracle.Price != 100_000_000_000 || len(q.Events(0, 10)) != 2 {
		t.Fatal("redundant feeds duplicated canonical update", state.Oracle)
	}
	for _, e := range q.Events(0, 10) {
		if len(e.Command.Raw) == 0 || e.Command.Source == "" {
			t.Fatal("source evidence not persisted")
		}
	}
}
