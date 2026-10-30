// This v2 bridge is compiled in a separate offline copy of the engine. It has
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
	Kind      string         `json:"kind"`
	Policy    engine.Policy  `json:"policy"`
	Command   engine.Command `json:"command"`
	Cash      int64          `json:"cash"`
	Fee       int64          `json:"fee"`
	Exit      int64          `json:"exit"`
	Path      string         `json:"path"`
	FinalPath string         `json:"final_path"`
}

type bridge struct{ state *engine.State }

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
	if r.Kind == "capabilities" {
		return map[string]any{"version": "fee-recovery-research-v2", "paper_only": true, "fee_accrual_recovery": true, "fee_reduction": false, "operator_cost_accrual": false}, nil
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
	case "sync_lp":
		s, err := engine.ResearchSyncLP(*b.state, r.Cash, r.Fee, r.Exit)
		if err != nil {
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
	v["recovery"], v["pending_risk"] = s.Recovery, s.PendingRisk()
	v["lp_fee_accrued"], v["lp_exit_reserved"] = s.Local.LPFeeAccrued, s.Local.LPExitReserved
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
