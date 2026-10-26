package localdev

import (
	"context"
	"encoding/json"
	"fmt"
	"math/big"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"fuse/engine/internal/contracts"
	"github.com/ethereum/go-ethereum/accounts/abi"
	"github.com/ethereum/go-ethereum/common"
	"github.com/ethereum/go-ethereum/common/hexutil"
)

func TestPinnedBatchChecksReorderedAndDuplicateIDs(t *testing.T) {
	compiled, err := abi.JSON(strings.NewReader(`[{"type":"function","name":"withdrawnCumulative","stateMutability":"view","inputs":[{"name":"account","type":"address"}],"outputs":[{"type":"uint256"}]}]`))
	if err != nil {
		t.Fatal(err)
	}
	for _, mode := range []string{"reverse", "duplicate", "missing", "unavailable"} {
		t.Run(mode, func(t *testing.T) {
			server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				if mode == "unavailable" {
					w.WriteHeader(503)
					return
				}
				var requests []struct {
					ID     uint64            `json:"id"`
					Method string            `json:"method"`
					Params []json.RawMessage `json:"params"`
				}
				if err := json.NewDecoder(r.Body).Decode(&requests); err != nil {
					t.Error(err)
					return
				}
				responses := []map[string]any{}
				for i, request := range requests {
					if request.Method != "eth_call" || string(request.Params[1]) != `"0x7b"` {
						t.Error("batch changed method/block")
					}
					output, _ := compiled.Methods["withdrawnCumulative"].Outputs.Pack(big.NewInt(int64(100 + i)))
					responses = append(responses, map[string]any{"jsonrpc": "2.0", "id": request.ID, "result": hexutil.Encode(output)})
				}
				switch mode {
				case "reverse":
					responses[0], responses[1] = responses[1], responses[0]
				case "duplicate":
					responses[1]["id"] = responses[0]["id"]
				case "missing":
					responses = responses[:1]
				}
				_ = json.NewEncoder(w).Encode(responses)
			}))
			defer server.Close()
			rpc := &RPC{RPCReader: &contracts.RPCReader{URL: server.URL, Client: server.Client()}, client: server.Client()}
			env := &Environment{RPC: rpc, ABIs: map[string]abi.ABI{"WithdrawalGateway": compiled}, Deployment: Deployment{Manifest: contracts.Manifest{Modules: map[string]contracts.Module{"WithdrawalGateway": {Address: common.HexToAddress("0x123")}}}}}
			result, err := env.UintBatch(context.Background(), "WithdrawalGateway", "withdrawnCumulative", 123, [][]any{{Wallet(Alice)}, {Wallet(Bob)}})
			if mode == "reverse" {
				if err != nil || fmt.Sprint(result) != "[100 101]" {
					t.Fatal(result, err)
				}
			} else if err == nil {
				t.Fatal("invalid batch accepted")
			}
			if mode == "unavailable" && !transientRPC(err) {
				t.Fatal("service outage not retryable", err)
			}
			if (mode == "duplicate" || mode == "missing") && transientRPC(err) {
				t.Fatal("malformed evidence treated as transport outage")
			}
		})
	}
}
