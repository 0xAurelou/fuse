package localdev

import (
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

func TestLocalExecutionGuards(t *testing.T) {
	for _, endpoint := range []string{"https://127.0.0.1:8545", "http://localhost:8545", "http://api.hyperliquid.xyz:8545", "http://192.168.1.10:8545", "http://127.0.0.1:8545?upstream=public"} {
		if _, err := Connect(context.Background(), endpoint); err == nil {
			t.Fatal("unsafe endpoint accepted", endpoint)
		}
	}
	for _, chain := range []string{"0x3e7", "0x3e6"} {
		t.Run(chain, func(t *testing.T) {
			server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				var query struct {
					ID     uint64 `json:"id"`
					Method string `json:"method"`
				}
				_ = json.NewDecoder(r.Body).Decode(&query)
				value := chain
				if query.Method == "web3_clientVersion" {
					value = "anvil/v1.5.1"
				}
				fmt.Fprintf(w, `{"jsonrpc":"2.0","id":%d,"result":%q}`, query.ID, value)
			}))
			defer server.Close()
			if _, err := Connect(context.Background(), server.URL); err == nil {
				t.Fatal("public chain accepted")
			}
		})
	}
	redirect := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { http.Redirect(w, r, "http://127.0.0.1:1", 307) }))
	defer redirect.Close()
	if _, err := Connect(context.Background(), redirect.URL); err == nil || !strings.Contains(err.Error(), "redirect") {
		t.Fatal("RPC redirect not refused", err)
	}
}
