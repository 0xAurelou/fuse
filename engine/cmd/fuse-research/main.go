// fuse-research is an offline bridge to the production trading reducer. It has
// no RPC, signing, HTTP or deployment path. External LP projections are explicit
// harness inputs, NOT confirmed transactions or ordinary engine journal events.
package main

import (
	"bufio"
	"encoding/json"
	"fmt"
	"os"

	"fuse/engine/internal/engine"
)

type request struct {
	Kind      string          `json:"kind"`
	Policy    engine.Policy   `json:"policy"`
	Command   engine.Command  `json:"command"`
	Cash      int64           `json:"cash"`
	Fee       int64           `json:"fee"`
	Exit      int64           `json:"exit"`
	Path      string          `json:"path"`
	FinalPath string          `json:"final_path"`
	StageID   string          `json:"stage_id,omitempty"`
	Corridors []corridorInput `json:"corridors,omitempty"`
}

type corridorInput struct {
	Price int64 `json:"price"`
	Width int64 `json:"width_ppb"`
}

// An offline arithmetic cross-check of the exact MulDiv used by native quotes.
// It creates no oracle, pricing approval, financial state or accepted bet.
func quantizeCorridors(p engine.Policy, input []corridorInput) (any, error) {
	if p.Mode != "paper" || p.Product != engine.SingleStage {
		return nil, fmt.Errorf("corridor research requires single-stage paper policy")
	}
	if err := p.Validate(); err != nil {
		return nil, err
	}
	if len(input) == 0 || len(input) > 2048 {
		return nil, fmt.Errorf("1..2048 corridor vectors required")
	}
	type row struct {
		Price int64 `json:"price"`
		Width int64 `json:"width_ppb"`
		Delta int64 `json:"delta"`
		Valid bool  `json:"valid"`
	}
	rows := make([]row, 0, len(input))
	for _, v := range input {
		if v.Price <= 0 || v.Price > engine.Limit || v.Width <= 0 || v.Width >= 1_000_000_000 {
			return nil, fmt.Errorf("invalid corridor input")
		}
		delta, err := engine.MulDiv(v.Price, v.Width, 1_000_000_000)
		rows = append(rows, row{v.Price, v.Width, delta, err == nil && delta > 0 && v.Price+delta <= engine.Limit})
	}
	return rows, nil
}

type bridge struct{ state *engine.State }

// pricingGrid exports the actual integer pricing function without constructing
// a trading state. It is an offline research operation, not a quote/accept API.
func pricingGrid(p engine.Policy) (any, error) {
	if p.Mode != "paper" || p.Product != engine.SingleStage {
		return nil, fmt.Errorf("pricing research requires a single-stage paper policy")
	}
	if err := p.Validate(); err != nil {
		return nil, err
	}
	type vector struct {
		Asset         string `json:"asset"`
		Multiplier    int64  `json:"multiplier"`
		VolatilityPPM int64  `json:"volatility_30s_ppm"`
		EdgeBPS       int64  `json:"house_edge_bps"`
		WidthPPB      int64  `json:"width_ppb"`
	}
	rows := []vector{}
	for _, asset := range []string{"BTC", "ETH", "HYPE"} {
		if !p.HasAsset(asset) {
			continue
		}
		model := p.AssetModel(asset)
		if model.DNT == nil {
			return nil, fmt.Errorf("pricing grid requires the Brownian formula in every enabled market")
		}
		for _, multiplier := range p.MultiplierOptions() {
			width, err := model.DNT.WidthPPB(multiplier)
			if err != nil {
				return nil, err
			}
			rows = append(rows, vector{asset, multiplier, model.DNT.VolatilityPPM, model.DNT.HouseEdgeBPS, width})
		}
	}
	return rows, nil
}

func verify(path string, p engine.Policy, finalPath string) (any, error) {
	s, err := engine.NewState(p)
	if err != nil {
		return nil, err
	}
	f, err := os.Open(path)
	if err != nil {
		return nil, err
	}
	defer f.Close()
	scan := bufio.NewScanner(f)
	scan.Buffer(make([]byte, 65536), 64<<20)
	seen := map[string]bool{}
	for scan.Scan() {
		var expected engine.Event
		if err := json.Unmarshal(scan.Bytes(), &expected); err != nil {
			return nil, err
		}
		if seen[expected.Command.Key] {
			return nil, fmt.Errorf("duplicate journal key")
		}
		seen[expected.Command.Key] = true
		next, got, err := engine.Apply(s, expected.Command)
		if err != nil {
			return nil, err
		}
		if engine.Hash(got) != engine.Hash(expected) {
			return nil, fmt.Errorf("source replay divergence at %d", expected.Sequence)
		}
		s = next
		if s.Sequence%1000 == 0 {
			fmt.Fprintf(os.Stderr, "Source replay: %d commands verified\n", s.Sequence)
		}
	}
	if err := scan.Err(); err != nil {
		return nil, err
	}
	if finalPath != "" {
		raw, err := os.ReadFile(finalPath)
		if err != nil {
			return nil, err
		}
		var retained engine.State
		if err := json.Unmarshal(raw, &retained); err != nil {
			return nil, err
		}
		if engine.Hash(s) != engine.Hash(retained) {
			return nil, fmt.Errorf("source final state differs from verified replay")
		}
	}
	return map[string]any{"sequence": s.Sequence, "state_hash": s.Digest(), "journal_hash": s.JournalHash}, nil
}

func (b *bridge) execute(r request) (any, error) {
	if r.Kind == "quantize_corridors" {
		return quantizeCorridors(r.Policy, r.Corridors)
	}
	if r.Kind == "pricing_grid" {
		return pricingGrid(r.Policy)
	}
	if r.Kind == "verify" {
		return verify(r.Path, r.Policy, r.FinalPath)
	}
	if r.Kind == "init" {
		if r.Policy.Mode != "paper" {
			return nil, fmt.Errorf("research requires paper policy")
		}
		s, err := engine.NewState(r.Policy)
		if err != nil {
			return nil, err
		}
		// Only the already-tested reservation accounting is used from LocalState.
		// This harness cannot submit local_* commands or bind a deployment.
		s.Local = &engine.LocalState{TokenSupply: "0", TokenBalances: map[string]string{}}
		b.state = &s
		return b.view(nil), nil
	}
	if b.state == nil {
		return nil, fmt.Errorf("initialize first")
	}
	switch r.Kind {
	case "settlement_outcome":
		return b.state.SettlementOutcome(r.StageID)
	case "sync_lp":
		if r.Cash < 0 || r.Cash > engine.Limit || r.Fee < 0 || r.Exit < 0 || r.Fee > r.Cash || r.Exit > r.Cash-r.Fee {
			return nil, fmt.Errorf("invalid projected LP balances")
		}
		s := *b.state
		local := *s.Local
		s.Local = &local
		s.LP, s.Local.LPFeeAccrued, s.Local.LPExitReserved = r.Cash, r.Fee, r.Exit
		if err := s.Check(); err != nil {
			return nil, err
		}
		b.state = &s
		return b.view(nil), nil
	case "command":
		next, e, err := engine.Apply(*b.state, r.Command)
		if err != nil {
			return nil, err
		}
		b.state = &next
		return b.view(&e), nil
	case "snapshot":
		return b.state, nil
	default:
		return nil, fmt.Errorf("unknown research operation")
	}
}

func (b *bridge) view(e *engine.Event) any {
	s := b.state
	exposure, _, active := s.Exposure()
	v := map[string]any{"sequence": s.Sequence, "at": s.At, "lp": s.LP, "lp_profit": s.LPProfit, "exposure": exposure, "active": active, "debt": s.Debt(), "state_hash": s.Digest()}
	if e != nil {
		v["result"] = e.Result
		v["notices"] = e.Notices
	}
	return v
}

func main() {
	b := &bridge{}
	scan := bufio.NewScanner(os.Stdin)
	scan.Buffer(make([]byte, 65536), 64<<20)
	encoder := json.NewEncoder(os.Stdout)
	for scan.Scan() {
		var r request
		var value any
		err := json.Unmarshal(scan.Bytes(), &r)
		if err == nil {
			value, err = b.execute(r)
		}
		out := map[string]any{"ok": err == nil, "value": value}
		if err != nil {
			out["error"] = err.Error()
		}
		if err := encoder.Encode(out); err != nil {
			fmt.Fprintln(os.Stderr, err)
			os.Exit(1)
		}
	}
	if err := scan.Err(); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}
