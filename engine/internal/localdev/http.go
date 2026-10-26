package localdev

import (
	"crypto/subtle"
	"encoding/json"
	"fmt"
	"io"
	"math/big"
	"net/http"
	"sort"
	"strings"

	"fuse/engine/internal/api"
	"fuse/engine/internal/engine"
)

func response(w http.ResponseWriter, status int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.Header().Set("Cache-Control", "no-store")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(v)
}
func problem(w http.ResponseWriter, err error) {
	response(w, 409, map[string]string{"error": err.Error()})
}
func decode(w http.ResponseWriter, r *http.Request, v any) error {
	r.Body = http.MaxBytesReader(w, r.Body, 1<<20)
	d := json.NewDecoder(r.Body)
	d.DisallowUnknownFields()
	if err := d.Decode(v); err != nil {
		return err
	}
	var extra any
	if err := d.Decode(&extra); err != io.EOF {
		return fmt.Errorf("one JSON object required")
	}
	return nil
}
func (c *Controller) Handler(base *api.Server) http.Handler {
	base.Now = c.Now
	mux := http.NewServeMux()
	ordinary := base.Handler()
	mux.Handle("/", http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if c.unavailable.Load() && ((r.Method == "POST" && (r.URL.Path == "/v1/quotes" || r.URL.Path == "/v1/stages")) || r.URL.Path == "/healthz") {
			response(w, 503, map[string]string{"error": "local chain reconciliation unavailable; retry after successful sync"})
			return
		}
		ordinary.ServeHTTP(w, r)
	}))
	mux.HandleFunc("GET /v1/tokenomics", func(w http.ResponseWriter, r *http.Request) {
		view, err := c.TokenomicsView(r.Context())
		if err != nil {
			problem(w, err)
			return
		}
		response(w, 200, view)
	})
	mux.HandleFunc("GET /{$}", func(w http.ResponseWriter, r *http.Request) {
		response(w, 200, map[string]any{"service": "FUSE local contract backend", "chain_id": ChainID, "mode": "local", "health": "/healthz", "deployment": "/local/deployment", "oracle": "/v1/oracle"})
	})
	operator := func(w http.ResponseWriter, r *http.Request) bool {
		got := r.Header.Get("Authorization")
		want := "Bearer " + base.AdminToken
		if len(base.AdminToken) < 32 || subtle.ConstantTimeCompare([]byte(got), []byte(want)) != 1 {
			response(w, 401, map[string]string{"error": "local operator token required"})
			return false
		}
		return true
	}
	key := func(r *http.Request) (string, error) {
		v := r.Header.Get("Idempotency-Key")
		if v == "" || len(v) > 100 {
			return "", fmt.Errorf("Idempotency-Key required, max 100 bytes")
		}
		return "local/" + v, nil
	}
	mux.HandleFunc("GET /local/deployment", func(w http.ResponseWriter, r *http.Request) {
		response(w, 200, map[string]any{"chain_id": ChainID, "contracts": c.Env.Deployment.Modules, "usdc": c.Env.Address("USDC"), "alice": Wallet(Alice), "bob": Wallet(Bob), "oracle": "deterministic local fixture"})
	})
	mux.HandleFunc("GET /local/state", func(w http.ResponseWriter, r *http.Request) {
		if !operator(w, r) {
			return
		}
		s := c.Q.Snapshot()
		response(w, 200, map[string]any{"local": s.Local, "custody": s.Custody, "lp": s.LP, "reserve": s.Reserve, "lp_profit": s.LPProfit, "epochs": s.Epochs, "sequence": s.Sequence})
	})
	mux.HandleFunc("POST /local/sync", func(w http.ResponseWriter, r *http.Request) {
		if !operator(w, r) {
			return
		}
		if err := c.Sync(r.Context()); err != nil {
			problem(w, err)
			return
		}
		response(w, 200, map[string]bool{"reconciled": true})
	})
	mux.HandleFunc("POST /local/checkpoints", func(w http.ResponseWriter, r *http.Request) {
		if !operator(w, r) {
			return
		}
		id, err := key(r)
		if err != nil {
			problem(w, err)
			return
		}
		op, err := c.Settle(r.Context(), id)
		if err != nil {
			problem(w, err)
			return
		}
		response(w, 200, op)
	})
	mux.HandleFunc("POST /local/lp/liquidity-window", func(w http.ResponseWriter, r *http.Request) {
		if !operator(w, r) {
			return
		}
		id, err := key(r)
		if err != nil {
			problem(w, err)
			return
		}
		op, err := c.OpenLPLiquidityWindow(r.Context(), id)
		if err != nil {
			problem(w, err)
			return
		}
		response(w, 200, op)
	})
	mux.HandleFunc("POST /local/lp/capacity", func(w http.ResponseWriter, r *http.Request) {
		if !operator(w, r) {
			return
		}
		id, err := key(r)
		if err != nil {
			problem(w, err)
			return
		}
		var input struct {
			Demand int64 `json:"eligible_demand_usdc_units"`
		}
		if err = decode(w, r, &input); err != nil {
			problem(w, err)
			return
		}
		op, err := c.PublishLPCapacity(r.Context(), id, input.Demand)
		if err != nil {
			problem(w, err)
			return
		}
		response(w, 200, op)
	})
	mux.HandleFunc("POST /local/oracle", func(w http.ResponseWriter, r *http.Request) {
		if !operator(w, r) {
			return
		}
		var input struct {
			Asset string `json:"asset"`
			Price string `json:"price"`
		}
		if err := decode(w, r, &input); err != nil {
			problem(w, err)
			return
		}
		if err := c.ObserveAssetPrice(r.Context(), input.Asset, input.Price); err != nil {
			problem(w, err)
			return
		}
		response(w, 200, map[string]string{"asset": engine.AssetName(input.Asset), "oraclePx": input.Price})
	})
	mux.HandleFunc("POST /local/advance", func(w http.ResponseWriter, r *http.Request) {
		if !operator(w, r) {
			return
		}
		var input struct {
			Seconds uint64 `json:"seconds"`
			Price   string `json:"price"`
		}
		if err := decode(w, r, &input); err != nil {
			problem(w, err)
			return
		}
		if err := c.Advance(r.Context(), input.Seconds, input.Price); err != nil {
			problem(w, err)
			return
		}
		response(w, 200, map[string]int64{"now": c.Now()})
	})
	mux.HandleFunc("POST /v1/withdrawals/{id}/authorization", func(w http.ResponseWriter, r *http.Request) {
		account, ok := base.Auth.Session(r, "withdraw")
		if !ok {
			response(w, 401, map[string]string{"error": "scoped session required"})
			return
		}
		ticket, err := c.Ticket(r.Context(), account, r.PathValue("id"))
		if err != nil {
			problem(w, err)
			return
		}
		response(w, 200, ticket)
	})

	mux.HandleFunc("GET /v1/withdrawals/{id}/authorization", func(w http.ResponseWriter, r *http.Request) {
		account, ok := base.Auth.Session(r, "read")
		if !ok {
			response(w, 401, map[string]string{"error": "scoped session required"})
			return
		}
		ticket, found := c.Q.Snapshot().Local.Tickets[r.PathValue("id")]
		if !found || ticket.Account != account {
			response(w, 404, map[string]string{"error": "authorization not found"})
			return
		}
		response(w, 200, ticket)
	})
	mux.HandleFunc("POST /local/rewards", func(w http.ResponseWriter, r *http.Request) {
		if !operator(w, r) {
			return
		}
		id, err := key(r)
		if err != nil {
			problem(w, err)
			return
		}
		var input struct {
			Budget string `json:"budget"`
		}
		if err = decode(w, r, &input); err != nil {
			problem(w, err)
			return
		}
		budget, ok := new(big.Int).SetString(input.Budget, 10)
		if !ok {
			problem(w, fmt.Errorf("invalid FUSE base units"))
			return
		}
		op, err := c.PublishRewards(r.Context(), id, budget)
		if err != nil {
			problem(w, err)
			return
		}
		response(w, 200, op)
	})
	mux.HandleFunc("GET /v1/rewards", func(w http.ResponseWriter, r *http.Request) {
		account, ok := base.Auth.Session(r, "read")
		if !ok {
			response(w, 401, map[string]string{"error": "session required"})
			return
		}
		out := []engine.LocalReward{}
		for _, reward := range c.Q.Snapshot().Local.Rewards {
			copy := *reward
			copy.Allocations = []engine.LocalAllocation{}
			for _, a := range reward.Allocations {
				if a.Account == account {
					copy.Allocations = append(copy.Allocations, a)
				}
			}
			if len(copy.Allocations) > 0 {
				out = append(out, copy)
			}
		}
		sort.Slice(out, func(i, j int) bool { return out[i].Epoch < out[j].Epoch })
		response(w, 200, out)
	})
	mux.HandleFunc("POST /local/reserve", func(w http.ResponseWriter, r *http.Request) {
		if !operator(w, r) {
			return
		}
		id, err := key(r)
		if err != nil {
			problem(w, err)
			return
		}
		var input struct {
			Amount int64 `json:"amount"`
		}
		if err = decode(w, r, &input); err != nil {
			problem(w, err)
			return
		}
		op, err := c.FundReserve(r.Context(), id, input.Amount)
		if err != nil {
			problem(w, err)
			return
		}
		response(w, 200, op)
	})
	mux.HandleFunc("POST /local/redemptions", func(w http.ResponseWriter, r *http.Request) {
		if !operator(w, r) {
			return
		}
		id, err := key(r)
		if err != nil {
			problem(w, err)
			return
		}
		var input struct {
			Duration uint64 `json:"duration"`
			Penalty  uint16 `json:"penalty_bps"`
		}
		if err = decode(w, r, &input); err != nil {
			problem(w, err)
			return
		}
		op, err := c.OpenRedemption(r.Context(), id, input.Duration, input.Penalty)
		if err != nil {
			problem(w, err)
			return
		}
		response(w, 200, op)
	})
	mux.HandleFunc("GET /v1/redemptions", func(w http.ResponseWriter, r *http.Request) {
		account, ok := base.Auth.Session(r, "read")
		if !ok {
			response(w, 401, map[string]string{"error": "session required"})
			return
		}
		out := []engine.LocalRedemption{}
		for _, redemption := range c.Q.Snapshot().Local.Redemptions {
			if redemption.Account == account {
				out = append(out, *redemption)
			}
		}
		sort.Slice(out, func(i, j int) bool { return out[i].Epoch < out[j].Epoch })
		response(w, 200, out)
	})
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if strings.HasPrefix(r.URL.Path, "/local/") {
			w.Header().Set("Cache-Control", "no-store")
		}
		mux.ServeHTTP(w, r)
	})
}
