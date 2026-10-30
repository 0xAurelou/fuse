package api

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"sort"
	"strconv"
	"strings"
	"time"

	"fuse/engine/internal/engine"
	"github.com/gorilla/websocket"
)

type Server struct {
	PaperDesk  bool
	Now        func() int64
	Q          *engine.Sequencer
	Auth       *Auth
	AdminToken string
	Origin     string
}

func (s *Server) now() int64 {
	if s.Now != nil {
		return s.Now()
	}
	return time.Now().UnixMilli()
}

// Assign receipt time at serialization, after preceding oracle/chain commits.
// Sampling before taking the writer lock races other ingress under load.
func (s *Server) execute(ctx context.Context, c engine.Command) (event engine.Event, err error) {
	err = s.Q.Exclusive(func(w *engine.Writer) error {
		c.At = max(s.now(), w.At())
		var e error
		event, e = w.Execute(ctx, c)
		return e
	})
	return
}

func (s *Server) Handler() http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("GET /healthz", func(w http.ResponseWriter, r *http.Request) {
		state := s.Q.Snapshot()
		ready := s.Q.Ready() && (state.Local == nil || state.Local.Halted == "")
		status := 200
		if !ready {
			status = 503
		}
		write(w, status, map[string]any{"ready": ready, "mode": state.Policy.Mode})
	})
	mux.HandleFunc("GET /v1/oracle", func(w http.ResponseWriter, r *http.Request) {
		state := s.Q.Snapshot()
		now := s.now()
		asset := engine.AssetName(r.URL.Query().Get("asset"))
		if !state.Policy.HasAsset(asset) {
			fail(w, 400, fmt.Errorf("market not enabled"))
			return
		}
		policy := state.Policy
		policy.Model = policy.AssetModel(asset)
		write(w, 200, map[string]any{"asset": asset, "oracle": state.AssetOracle(asset), "healthy": state.HealthyAsset(asset, now), "policy": policy, "server_time": now, "multiplier_min": engine.MinMultiplier, "multiplier_max": policy.MultiplierOptions()[len(policy.MultiplierOptions())-1], "multipliers": policy.MultiplierOptions()})
	})
	mux.HandleFunc("GET /v1/markets", func(w http.ResponseWriter, r *http.Request) {
		state := s.Q.Snapshot()
		now := s.now()
		markets := []any{}
		for _, asset := range state.Policy.Assets() {
			policy := state.Policy
			policy.Model = policy.AssetModel(asset)
			markets = append(markets, map[string]any{"asset": asset, "oracle": state.AssetOracle(asset), "healthy": state.HealthyAsset(asset, now), "policy": policy, "server_time": now, "multipliers": policy.MultiplierOptions()})
		}
		write(w, 200, map[string]any{"markets": markets, "server_time": now, "paper_desk": s.PaperDesk && state.Policy.Mode == "paper"})
	})
	mux.HandleFunc("POST /v1/paper/session", s.paperSession)
	mux.HandleFunc("POST /v1/paper/entries", s.paperEntry)
	mux.HandleFunc("POST /v1/auth/challenge", s.challenge)
	mux.HandleFunc("POST /v1/auth/verify", s.verify)
	mux.HandleFunc("DELETE /v1/session", func(w http.ResponseWriter, r *http.Request) {
		s.Auth.Revoke(r)
		write(w, 200, map[string]bool{"revoked": true})
	})
	mux.HandleFunc("GET /v1/account", s.account)
	mux.HandleFunc("GET /v1/stages", s.stages)
	mux.HandleFunc("GET /v1/withdrawals", s.withdrawals)
	mux.HandleFunc("POST /v1/quotes", s.command("quote", "quote"))
	mux.HandleFunc("POST /v1/stages", s.command("enter", "trade"))
	mux.HandleFunc("POST /v1/cashout", s.command("cashout", "trade"))
	mux.HandleFunc("POST /v1/withdrawals", s.command("withdraw", "withdraw"))
	mux.HandleFunc("GET /v1/events", s.events)
	mux.HandleFunc("GET /v1/ws", s.ws)
	mux.HandleFunc("GET /metrics", s.metrics)
	mux.HandleFunc("GET /admin/journal", s.journal)
	mux.HandleFunc("POST /admin/commands", s.admin)
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Cache-Control", "no-store")
		w.Header().Set("X-Content-Type-Options", "nosniff")
		mux.ServeHTTP(w, r)
	})
}
func write(w http.ResponseWriter, status int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(v)
}
func fail(w http.ResponseWriter, status int, err error) {
	write(w, status, map[string]string{"error": err.Error()})
}
func body(w http.ResponseWriter, r *http.Request, v any) error {
	r.Body = http.MaxBytesReader(w, r.Body, 1<<20)
	d := json.NewDecoder(r.Body)
	d.DisallowUnknownFields()
	if err := d.Decode(v); err != nil {
		return err
	}
	var extra any
	if err := d.Decode(&extra); err != io.EOF {
		return fmt.Errorf("expected one JSON object")
	}
	return nil
}
func (s *Server) authenticated(w http.ResponseWriter, r *http.Request, scope string) (string, bool) {
	account, ok := s.Auth.Session(r, scope)
	if !ok {
		fail(w, 401, fmt.Errorf("valid scoped session required"))
	}
	return account, ok
}
func (s *Server) challenge(w http.ResponseWriter, r *http.Request) {
	var b struct {
		Account string `json:"account"`
	}
	if err := body(w, r, &b); err != nil {
		fail(w, 400, err)
		return
	}
	id, message, err := s.Auth.Challenge(b.Account)
	if err != nil {
		fail(w, 400, err)
		return
	}
	write(w, 200, map[string]string{"id": id, "message": message})
}
func (s *Server) verify(w http.ResponseWriter, r *http.Request) {
	var b struct {
		ID        string `json:"id"`
		Signature string `json:"signature"`
	}
	if err := body(w, r, &b); err != nil {
		fail(w, 400, err)
		return
	}
	token, err := s.Auth.Verify(b.ID, b.Signature)
	if err != nil {
		fail(w, 401, err)
		return
	}
	write(w, 200, map[string]string{"token": token, "expires_in": "1800"})
}
func (s *Server) account(w http.ResponseWriter, r *http.Request) {
	id, ok := s.authenticated(w, r, "read")
	if !ok {
		return
	}
	state := s.Q.Snapshot()
	write(w, 200, map[string]any{"account": state.Balance(id), "sequence": state.Sequence, "state_hash": state.Digest()})
}
func (s *Server) stages(w http.ResponseWriter, r *http.Request) {
	id, ok := s.authenticated(w, r, "read")
	if !ok {
		return
	}
	state := s.Q.Snapshot()
	out := []engine.Stage{}
	for _, p := range state.Stages {
		if p.Terms.Account == id {
			out = append(out, *p)
		}
	}
	sort.Slice(out, func(i, j int) bool { return out[i].AcceptedSequence < out[j].AcceptedSequence })
	write(w, 200, out)
}
func (s *Server) withdrawals(w http.ResponseWriter, r *http.Request) {
	id, ok := s.authenticated(w, r, "read")
	if !ok {
		return
	}
	state := s.Q.Snapshot()
	out := []engine.Withdrawal{}
	for _, p := range state.Withdrawals {
		if p.Account == id {
			out = append(out, *p)
		}
	}
	sort.Slice(out, func(i, j int) bool { return out[i].Cumulative < out[j].Cumulative })
	write(w, 200, out)
}
func (s *Server) command(kind, scope string) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		id, ok := s.authenticated(w, r, scope)
		if !ok {
			return
		}
		var b struct {
			Asset      string `json:"asset"`
			Multiplier int64  `json:"multiplier"`
			ID         string `json:"id"`
			Previous   string `json:"previous"`
			Amount     int64  `json:"amount"`
		}
		if err := body(w, r, &b); err != nil {
			fail(w, 400, err)
			return
		}
		key := r.Header.Get("Idempotency-Key")
		if key == "" || len(key) > 100 {
			fail(w, 400, fmt.Errorf("Idempotency-Key required (max 100 bytes)"))
			return
		}
		c := engine.Command{Key: id + "/" + key, Kind: kind, Actor: id, ID: b.ID, Previous: b.Previous, Amount: b.Amount, Multiplier: b.Multiplier, Asset: b.Asset}
		e, err := s.execute(r.Context(), c)
		if err != nil {
			status := 503
			if errors.Is(err, engine.ErrRejected) {
				status = 409
			}
			fail(w, status, err)
			return
		}
		write(w, 200, map[string]any{"sequence": e.Sequence, "state_version": e.Sequence, "journal_hash": e.Hash, "result": e.Result})
	}
}

type eventView struct {
	Sequence     uint64          `json:"sequence"`
	StateVersion uint64          `json:"state_version"`
	Type         string          `json:"type"`
	Payload      json.RawMessage `json:"payload"`
}
type batch struct {
	Cursor uint64      `json:"cursor"`
	Events []eventView `json:"events"`
}

func (s *Server) catchup(id string, after uint64) batch {
	out := batch{Cursor: after, Events: []eventView{}}
	for _, e := range s.Q.Events(after, 500) {
		out.Cursor = e.Sequence
		if v, ok := e.Notices[id]; ok {
			out.Events = append(out.Events, eventView{e.Sequence, e.Sequence, e.Command.Kind, v})
		}
	}
	return out
}
func cursor(r *http.Request) (uint64, error) {
	v := r.URL.Query().Get("after")
	if v == "" {
		return 0, nil
	}
	return strconv.ParseUint(v, 10, 64)
}
func (s *Server) events(w http.ResponseWriter, r *http.Request) {
	id, ok := s.authenticated(w, r, "read")
	if !ok {
		return
	}
	after, err := cursor(r)
	if err != nil || after > s.Q.Snapshot().Sequence {
		fail(w, 400, fmt.Errorf("invalid cursor"))
		return
	}
	write(w, 200, s.catchup(id, after))
}
func (s *Server) ws(w http.ResponseWriter, r *http.Request) {
	id, ok := s.authenticated(w, r, "read")
	if !ok {
		return
	}
	after, err := cursor(r)
	if err != nil || after > s.Q.Snapshot().Sequence {
		fail(w, 400, fmt.Errorf("invalid cursor"))
		return
	}
	up := websocket.Upgrader{CheckOrigin: func(r *http.Request) bool { return r.Header.Get("Origin") == "" || r.Header.Get("Origin") == s.Origin }}
	conn, err := up.Upgrade(w, r, nil)
	if err != nil {
		return
	}
	defer conn.Close()
	conn.SetReadLimit(1024)
	done := make(chan struct{})
	go func() {
		defer close(done)
		for {
			if _, _, err := conn.ReadMessage(); err != nil {
				return
			}
		}
	}()
	ticker := time.NewTicker(200 * time.Millisecond)
	defer ticker.Stop()
	for {
		if _, valid := s.Auth.Session(r, "read"); !valid {
			return
		}
		b := s.catchup(id, after)
		_ = conn.SetWriteDeadline(time.Now().Add(5 * time.Second))
		if err = conn.WriteJSON(b); err != nil {
			return
		}
		after = b.Cursor
		select {
		case <-r.Context().Done():
			return
		case <-done:
			return
		case <-ticker.C:
		}
	}
}
func (s *Server) isAdmin(w http.ResponseWriter, r *http.Request) bool {
	if !equalSecret(s.AdminToken, strings.TrimPrefix(r.Header.Get("Authorization"), "Bearer ")) {
		fail(w, 401, fmt.Errorf("paper operator token required"))
		return false
	}
	return true
}
func (s *Server) admin(w http.ResponseWriter, r *http.Request) {
	if !s.isAdmin(w, r) {
		return
	}
	var c engine.Command
	if err := body(w, r, &c); err != nil {
		fail(w, 400, err)
		return
	}
	allowed := map[string]bool{"policy_update": true, "oracle": true, "tick": true, "pause": true, "resume": true, "lp_fund": true, "deposit": true, "ack_deposit": true, "refund_deposit": true, "paper_settle": true, "paper_pay": true}
	if !allowed[c.Kind] || !strings.HasPrefix(c.Key, "admin/") {
		fail(w, 400, fmt.Errorf("unsupported paper command or key must start admin/"))
		return
	}
	if c.Actor != "" {
		actor, err := address(c.Actor)
		if err != nil {
			fail(w, 400, err)
			return
		}
		c.Actor = actor
	}
	e, err := s.execute(r.Context(), c)
	if err != nil {
		status := 503
		if errors.Is(err, engine.ErrRejected) {
			status = 409
		}
		fail(w, status, err)
		return
	}
	write(w, 200, e)
}
func (s *Server) journal(w http.ResponseWriter, r *http.Request) {
	if !s.isAdmin(w, r) {
		return
	}
	after, err := cursor(r)
	if err != nil {
		fail(w, 400, err)
		return
	}
	write(w, 200, s.Q.Events(after, 1000))
}
func (s *Server) metrics(w http.ResponseWriter, r *http.Request) {
	if !s.isAdmin(w, r) {
		return
	}
	state := s.Q.Snapshot()
	exposure, _, active := state.Exposure()
	var capital strings.Builder
	enabled := 0
	if state.Policy.Capital != nil {
		enabled = 1
		fmt.Fprintf(&capital, "fuse_max_bet_liability_usdc_units %d\n", state.Policy.Capital.MaxBetLiability)
		for _, asset := range state.Policy.Assets() {
			amount, err := state.MarketExposure(asset)
			if err != nil {
				fail(w, 503, err)
				return
			}
			fmt.Fprintf(&capital, "fuse_market_exposure_usdc_units{asset=%q} %d\nfuse_market_unfunded_wins_usdc_units{asset=%q} %d\nfuse_market_exposure_limit_usdc_units{asset=%q} %d\n",
				asset, amount, asset, state.Capital.UnfundedByMarket[asset], asset, state.Policy.Capital.MaxMarketExposure[asset])
		}
	}
	fmt.Fprintf(&capital, "fuse_capital_limits_enabled %d\nfuse_lp_available_usdc_units %d\nfuse_lp_admission_headroom_usdc_units %d\nfuse_global_exposure_limit_usdc_units %d\nfuse_account_exposure_limit_usdc_units %d\nfuse_lp_admission_buffer_usdc_units %d\n",
		enabled, state.LPAvailable(), state.LPAvailable()-exposure-state.Policy.LPBuffer, state.Policy.MaxExposure, state.Policy.MaxAccountExposure, state.Policy.LPBuffer)
	pending := 0
	for _, p := range state.Stages {
		if p.Status == "pending" {
			pending++
		}
	}
	w.Header().Set("Content-Type", "text/plain; version=0.0.4")
	fmt.Fprintf(w, "fuse_sequence %d\nfuse_lp_assets_usdc %d\nfuse_lp_reserved_usdc %d\nfuse_unfunded_claims_usdc %d\nfuse_active_stages %d\nfuse_pending_stages %d\nfuse_oracle_age_milliseconds %d\nfuse_reserve_usdc %d\n", state.Sequence, state.LP, exposure, state.Debt(), active, pending, s.now()-state.Oracle.At, state.Reserve)
	fmt.Fprint(w, capital.String())
	if r := state.Recovery; r != nil {
		for _, mode := range []string{"open", "paused", "probe"} {
			value := 0
			if r.Mode == mode {
				value = 1
			}
			fmt.Fprintf(w, "fuse_recovery_mode{mode=%q} %d\n", mode, value)
		}
		fmt.Fprintf(w, "fuse_recovery_drawdown_usdc %d\nfuse_recovery_pending_usdc %d\nfuse_recovery_reopen_at_milliseconds %d\n", r.Peak-r.PnL, state.PendingRisk(), r.ReopenAt)
	}
}
