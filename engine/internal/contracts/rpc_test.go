package contracts

import (
	"context"
	"encoding/json"
	"errors"
	"github.com/ethereum/go-ethereum/core/types"
	"net/http"
	"net/http/httptest"
	"testing"
)

func TestReadRPCSeparatesAvailabilityFromInvalidRequests(t *testing.T) {
	for _, status := range []int{400, 429, 500, 503} {
		t.Run(http.StatusText(status), func(t *testing.T) {
			server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { w.WriteHeader(status) }))
			defer server.Close()
			reader := &RPCReader{URL: server.URL, Client: server.Client()}
			_, err := reader.Head(context.Background())
			if err == nil || errors.Is(err, ErrRPCUnavailable) != (status == 429 || status >= 500) {
				t.Fatal("wrong RPC availability classification", status, err)
			}
		})
	}
}

func TestReceiptNullIsPendingButOtherNullReadsFail(t *testing.T) {
	s := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		var request struct {
			ID uint64 `json:"id"`
		}
		_ = json.NewDecoder(r.Body).Decode(&request)
		_ = json.NewEncoder(w).Encode(map[string]any{"jsonrpc": "2.0", "id": request.ID, "result": nil})
	}))
	defer s.Close()
	r := &RPCReader{URL: s.URL, Client: s.Client()}
	var receipt *types.Receipt
	if err := r.ReadRPC(context.Background(), "eth_getTransactionReceipt", []any{}, &receipt); err != nil || receipt != nil {
		t.Fatal("absent receipt was not pending", err)
	}
	if _, err := r.Head(context.Background()); err == nil {
		t.Fatal("missing block number accepted")
	}
}
