package contracts

import (
	"context"
	"errors"
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
