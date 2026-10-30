package localdev

import (
	"context"
	"encoding/json"
	"fmt"
	"math/big"
	"net/http"
	"net/http/httptest"
	"os"
	"strings"
	"sync/atomic"
	"testing"

	"fuse/engine/internal/contracts"
	"fuse/engine/internal/engine"
	"fuse/engine/internal/storage"
	"github.com/ethereum/go-ethereum/accounts/abi"
	"github.com/ethereum/go-ethereum/common"
	"github.com/ethereum/go-ethereum/common/hexutil"
)

// Exercise the full public disclosure method against ABI-encoded, pinned-block
// RPC observations, including old manifests with no new capability selector.
func TestTokenomicsRedemptionPauseCapabilitiesAndActualWindow(t *testing.T) {
	for _, tc := range []struct {
		name                                                           string
		declared, support, paused, snapshot, active, transfers, funded bool
		now                                                            uint64
		readError, executable, startRequired                           bool
	}{
		{"legacy paused", false, false, true, true, true, true, true, 150, false, false, false},
		{"legacy active", false, false, false, true, true, true, true, 150, false, true, false},
		{"new paused", true, true, true, true, true, true, true, 150, false, true, false},
		{"declared false", true, false, true, true, true, true, true, 150, false, false, false},
		{"lazy start paused", true, true, true, false, true, true, true, 150, false, false, true},
		{"before window", true, true, true, false, true, true, true, 99, false, false, false},
		{"at end", true, true, true, true, true, true, true, 200, false, false, false},
		{"empty reserve", true, true, true, false, true, true, false, 150, false, false, false},
		{"inactive", true, true, true, true, false, true, true, 150, false, false, false},
		{"transfers disabled", true, true, true, true, true, false, true, 150, false, false, false},
		{"capability unavailable", true, true, true, true, true, true, true, 150, true, false, false},
	} {
		t.Run(tc.name, func(t *testing.T) {
			method := func(name string, outputs []string, inputs ...string) map[string]any {
				params := func(types []string) []map[string]string {
					out := []map[string]string{}
					for i, typ := range types {
						out = append(out, map[string]string{"name": fmt.Sprint("p", i), "type": typ})
					}
					return out
				}
				return map[string]any{"type": "function", "name": name, "stateMutability": "view", "inputs": params(inputs), "outputs": params(outputs)}
			}
			methods := map[string][]map[string]any{
				"FUSEToken":         {method("totalSupply", []string{"uint256"}), method("emissionEscrow", []string{"address"}), method("treasuryEscrow", []string{"address"}), method("lpEmissionEscrow", []string{"address"}), method("balanceOf", []string{"uint256"}, "address"), method("transfersEnabled", []string{"bool"})},
				"RewardDistributor": {method("emissionsActive", []string{"bool"})},
				"RedemptionReserve": {method("redemptionsActive", []string{"bool"}), method("latestEpoch", []string{"uint256"}), method("epochs", []string{"uint64", "uint64", "uint64", "uint16", "uint256", "uint256", "uint256", "uint256"}, "uint64")},
			}
			for _, name := range []string{"totalAllocated", "totalClaimed", "nextEpochCap", "emissionStart", "epochDuration", "decayBps"} {
				methods["RewardDistributor"] = append(methods["RewardDistributor"], method(name, []string{"uint256"}))
			}
			if tc.declared {
				methods["RedemptionReserve"] = append(methods["RedemptionReserve"], method("supportsPausedRedemptions", []string{"bool"}))
			}
			abis := map[string]abi.ABI{}
			modules := map[string]contracts.Module{}
			byAddress := map[common.Address]string{}
			for i, name := range []string{"FUSEToken", "RewardDistributor", "RedemptionReserve"} {
				raw, _ := json.Marshal(methods[name])
				compiled, err := abi.JSON(strings.NewReader(string(raw)))
				if err != nil {
					t.Fatal(err)
				}
				abis[name] = compiled
				address := common.BigToAddress(big.NewInt(int64(i + 10)))
				modules[name] = contracts.Module{Address: address}
				byAddress[address] = name
			}
			escrows := map[string]common.Address{"emissionEscrow": common.HexToAddress("0x100"), "treasuryEscrow": common.HexToAddress("0x200"), "lpEmissionEscrow": common.HexToAddress("0x300")}
			supply, _ := new(big.Int).SetString("1000000000000000000000000000", 10)
			reserve := int64(0)
			if tc.funded {
				reserve = 350_000_000
			}
			var capReads atomic.Int32
			server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				var request struct {
					ID     uint64            `json:"id"`
					Method string            `json:"method"`
					Params []json.RawMessage `json:"params"`
				}
				if err := json.NewDecoder(r.Body).Decode(&request); err != nil {
					t.Error(err)
					return
				}
				respond := func(value any) {
					_ = json.NewEncoder(w).Encode(map[string]any{"jsonrpc": "2.0", "id": request.ID, "result": value})
				}
				if request.Method == "eth_getBlockByNumber" {
					if string(request.Params[0]) != `"0x4d"` {
						t.Error("header is not pinned to confirmed block")
					}
					respond(map[string]any{"timestamp": hexutil.EncodeUint64(tc.now)})
					return
				}
				if request.Method != "eth_call" || string(request.Params[1]) != `"0x4d"` {
					t.Error("contract read is not pinned")
				}
				var call struct {
					To   common.Address `json:"to"`
					Data hexutil.Bytes  `json:"data"`
				}
				if err := json.Unmarshal(request.Params[0], &call); err != nil {
					t.Error(err)
					return
				}
				compiled := abis[byAddress[call.To]]
				m, err := compiled.MethodById(call.Data[:4])
				if err != nil {
					t.Error(err)
					return
				}
				var values []any
				switch m.Name {
				case "totalSupply":
					values = []any{supply}
				case "emissionEscrow", "treasuryEscrow", "lpEmissionEscrow":
					values = []any{escrows[m.Name]}
				case "balanceOf":
					values = []any{big.NewInt(0)}
				case "transfersEnabled":
					values = []any{tc.transfers}
				case "emissionsActive":
					values = []any{true}
				case "redemptionsActive":
					values = []any{tc.active}
				case "supportsPausedRedemptions":
					capReads.Add(1)
					if tc.readError {
						_ = json.NewEncoder(w).Encode(map[string]any{"jsonrpc": "2.0", "id": request.ID, "error": map[string]any{"code": -32000, "message": "unavailable capability"}})
						return
					}
					values = []any{tc.support}
				case "latestEpoch":
					values = []any{big.NewInt(1)}
				case "epochs":
					snapshot := new(big.Int)
					if tc.snapshot {
						snapshot.Set(supply)
					}
					values = []any{uint64(1), uint64(100), uint64(200), uint16(0), snapshot, big.NewInt(reserve), big.NewInt(0), big.NewInt(0)}
				default:
					values = []any{big.NewInt(0)}
				}
				encoded, err := m.Outputs.Pack(values...)
				if err != nil {
					t.Error(err)
					return
				}
				respond(hexutil.Encode(encoded))
			}))
			defer server.Close()
			ctx := context.Background()
			raw, err := os.ReadFile("../../config/local.json")
			if err != nil {
				t.Fatal(err)
			}
			var policy engine.Policy
			if err = json.Unmarshal(raw, &policy); err != nil {
				t.Fatal(err)
			}
			q, err := engine.Open(ctx, policy, &storage.Memory{})
			if err != nil {
				t.Fatal(err)
			}
			bind, _ := json.Marshal(map[string]any{"Deployment": "test", "BlockHash": "parent", "Cursor": uint64(76)})
			if _, err = q.Execute(ctx, engine.Command{Kind: "local_bind", Key: "bind", At: 1_000_000, Raw: bind}); err != nil {
				t.Fatal(err)
			}
			effects := []engine.LocalEffect{{Module: "AccessController", Event: "TradingPauseChanged", Value: fmt.Sprint(tc.paused)}}
			if reserve > 0 {
				effects = append(effects, engine.LocalEffect{Module: "LPVault", Event: "LPDeposited", Amount: reserve}, engine.LocalEffect{Module: "LPVault", Event: "ReserveFunded", Amount: reserve, Value: "1000000000"})
			}
			block, _ := json.Marshal(engine.LocalBlock{Number: 77, Parent: "parent", Hash: "confirmed", Effects: effects})
			if _, err = q.Execute(ctx, engine.Command{Kind: "local_block", Key: "block", At: 1_000_001, Raw: block}); err != nil {
				t.Fatal(err)
			}
			rpc := &RPC{RPCReader: &contracts.RPCReader{URL: server.URL, Client: server.Client()}, client: server.Client()}
			c := &Controller{Q: q, Env: &Environment{Deployment: Deployment{Manifest: contracts.Manifest{Modules: modules}}, ABIs: abis, RPC: rpc}}
			view, err := c.TokenomicsView(ctx)
			if tc.readError {
				if err == nil {
					t.Fatal("failed capability read advertised availability")
				}
				return
			}
			if err != nil {
				t.Fatal(err)
			}
			epoch := view["redemption_epoch"].(map[string]any)
			if epoch["executable"] != tc.executable || epoch["start_required"] != tc.startRequired {
				t.Fatal(epoch)
			}
			if (view["current_executable_net_backing_ratio"] != nil) != tc.executable {
				t.Fatal("unavailable snapshot reported as executable")
			}
			if tc.declared && capReads.Load() != 1 || !tc.declared && capReads.Load() != 0 {
				t.Fatal("legacy capability discovery changed", capReads.Load())
			}
		})
	}
}
