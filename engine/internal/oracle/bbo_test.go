package oracle

import (
	"context"
	"encoding/json"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync/atomic"
	"testing"
	"time"

	"fuse/engine/internal/engine"
	"github.com/gorilla/websocket"
)

func TestBBOValidationAndPriceIsolation(t *testing.T) {
	valid := `{"channel":"bbo","data":{"coin":"BTC","time":1234,"bbo":[{"px":"100000.1","sz":"0.5","n":2},{"px":"100000.2","sz":"1.2","n":1}]}}`
	b, err := ParseBBO([]byte(valid))
	if err != nil || b.Levels[0].Price != "100000.1" {
		t.Fatal(b, err)
	}
	if _, err = engine.ParseOracle([]byte(valid)); err == nil {
		t.Fatal("BBO accepted as settlement oracle")
	}
	for _, raw := range []string{strings.Replace(valid, "BTC", "ETH", 1), strings.Replace(valid, `"time":1234`, `"time":0`, 1), strings.Replace(valid, "100000.1", "100001.1", 1), strings.Replace(valid, `"0.5"`, `"-1"`, 1), strings.Replace(valid, `"100000.1"`, `100000.1`, 1), strings.Replace(valid, `"bbo":[`, `"bbo":[null,`, 1)} {
		if _, err := ParseBBO([]byte(raw)); err == nil {
			t.Fatal("invalid BBO accepted", raw)
		}
	}
	if _, err := ParseBBO([]byte(`{"channel":"bbo","data":{"coin":"BTC","time":1234,"bbo":[null,null]}}`)); err != nil {
		t.Fatal("unavailable sides should remain valid market evidence", err)
	}
}

func TestCollectorBBOEvidenceNeverSubmittedAsOracle(t *testing.T) {
	var submitted, observed atomic.Int32
	up := websocket.Upgrader{}
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		conn, err := up.Upgrade(w, r, nil)
		if err != nil {
			return
		}
		defer conn.Close()
		var subscription map[string]any
		if conn.ReadJSON(&subscription) != nil {
			return
		}
		_ = conn.WriteMessage(websocket.TextMessage, []byte(`{"channel":"activeAssetCtx","data":{"coin":"BTC","ctx":{"oraclePx":"100000"}}}`))
		for {
			if conn.ReadJSON(&subscription) != nil {
				return
			}
			nested, _ := subscription["subscription"].(map[string]any)
			if nested["type"] == "bbo" {
				_ = conn.WriteMessage(websocket.TextMessage, []byte(`{"channel":"bbo","data":{"coin":"BTC","time":1234,"bbo":[{"px":"99999","sz":"1","n":1},{"px":"100001","sz":"1","n":1}]}}`))
			}
		}
	}))
	defer server.Close()
	ctx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
	defer cancel()
	done := make(chan struct{})
	go func() {
		defer close(done)
		Collector{URL: "ws" + strings.TrimPrefix(server.URL, "http"), Log: slog.New(slog.NewTextHandler(io.Discard, nil)), Observe: func(source, channel string, raw json.RawMessage) {
			if channel == "bbo" {
				observed.Add(1)
			}
		}, Submit: func(ctx context.Context, source string, raw json.RawMessage) error {
			if _, err := engine.ParseOracle(raw); err != nil {
				t.Error(err)
			}
			submitted.Add(1)
			return nil
		}}.Run(ctx)
	}()
	for submitted.Load() != 2 || observed.Load() != 1 {
		select {
		case <-ctx.Done():
			t.Fatal("missing oracle/BBO subscriptions")
		case <-time.After(5 * time.Millisecond):
		}
	}
	cancel()
	select {
	case <-done:
	case <-time.After(time.Second):
		t.Fatal("live collector did not stop")
	}
	if submitted.Load() != 2 {
		t.Fatal("BBO entered oracle submission")
	}
}
