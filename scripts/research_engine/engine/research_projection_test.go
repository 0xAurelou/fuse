package engine

import (
	"encoding/json"
	"fmt"
	"os"
	"testing"
)

func researchProjectionFixture(t *testing.T) State {
	t.Helper()
	raw, err := os.ReadFile("../../config/paper-recovery.json")
	if err != nil {
		t.Fatal(err)
	}
	var p Policy
	if err := json.Unmarshal(raw, &p); err != nil {
		t.Fatal(err)
	}
	s, err := NewState(p)
	if err != nil {
		t.Fatal(err)
	}
	s.At, s.LP = 1_000_000, 250_000_000_000
	s.Local = &LocalState{TokenSupply: "0", TokenBalances: map[string]string{}}
	return s
}

func TestResearchProjectionMatchesRealFeeHandlerAndDoesNotReset(t *testing.T) {
	s := researchProjectionFixture(t)
	real := clone(s)
	if err := real.localEffect(LocalEffect{Module: "LPVault", Event: "ReserveFeeAccrued", Amount: 25_000_000, Value: "25000000"}); err != nil {
		t.Fatal(err)
	}
	got, err := ResearchSyncLP(s, s.LP, 25_000_000, 0)
	if err != nil {
		t.Fatal(err)
	}
	if Hash(got.Recovery) != Hash(real.Recovery) || got.Recovery.PnL != -25_000_000 || got.Recovery.Mode != "paused" {
		t.Fatal("projection differs from production fee recovery", got.Recovery, real.Recovery)
	}
	before := Hash(got.Recovery)
	again, err := ResearchSyncLP(got, got.LP+1_000_000, 25_000_000, 100_000_000)
	if err != nil || Hash(again.Recovery) != before {
		t.Fatal("repeated fee or capital flow changed recovery", err)
	}
	if _, err := ResearchSyncLP(again, again.LP, 24_999_999, 0); err == nil {
		t.Fatal("allowed clearing accrued fee")
	}
}

func TestResearchProjectionRejectsAtomicallyAndIsPaperOnly(t *testing.T) {
	s := researchProjectionFixture(t)
	digest := Hash(s)
	for _, args := range [][3]int64{{-1, 0, 0}, {100, 200, 0}, {100, 10, 91}} {
		got, err := ResearchSyncLP(s, args[0], args[1], args[2])
		if err == nil || Hash(got) != digest || Hash(s) != digest {
			t.Fatal("invalid projection mutated state", args)
		}
	}
	local := clone(s)
	local.Policy.Mode = "local"
	if _, err := ResearchSyncLP(local, local.LP, 0, 0); err == nil {
		t.Fatal("accepted local mode")
	}
	bound := clone(s)
	bound.Local.Deployment = "deployment"
	if _, err := ResearchSyncLP(bound, bound.LP, 0, 0); err == nil {
		t.Fatal("accepted bound deployment")
	}
	unclocked := clone(s)
	unclocked.At = 0
	if _, err := ResearchSyncLP(unclocked, unclocked.LP, 1, 0); err == nil {
		t.Fatal("accepted unsequenced fee")
	}
}

func TestResearchProjectionPreservesAcceptedObligationsAfterFeePause(t *testing.T) {
	s := researchProjectionFixture(t)
	serial := 0
	do := func(c Command) any {
		serial++
		c.Key = fmt.Sprint("projection/", serial)
		if c.At == 0 {
			c.At = s.At
		}
		next, e, err := Apply(s, c)
		if err != nil {
			t.Fatal(err)
		}
		s = next
		var result any
		if err := json.Unmarshal(e.Result, &result); err != nil {
			t.Fatal(err)
		}
		return result
	}
	for _, source := range []string{"a", "b"} {
		do(Command{Kind: "oracle", Source: source, Raw: json.RawMessage(`{"channel":"activeAssetCtx","data":{"coin":"BTC","ctx":{"oraclePx":"100000"}}}`)})
	}
	do(Command{Kind: "deposit", Actor: "alice", ID: "fund", Amount: 10_000_000})
	do(Command{Kind: "ack_deposit", ID: "fund"})
	q := do(Command{Kind: "quote", Actor: "alice", Amount: 1_000_000, Multiplier: 2}).(map[string]any)
	stage := do(Command{Kind: "enter", Actor: "alice", ID: q["id"].(string)}).(map[string]any)
	next, err := ResearchSyncLP(s, s.LP, 25_000_000, 0)
	if err != nil {
		t.Fatal(err)
	}
	s = next
	if s.Recovery.Mode != "paused" {
		t.Fatal("fee did not pause")
	}
	for at := s.At + 5000; at <= 1_030_000; at += 5000 {
		do(Command{Kind: "tick", At: at})
		for _, source := range []string{"a", "b"} {
			do(Command{Kind: "oracle", At: at, Source: source, Raw: json.RawMessage(`{"channel":"activeAssetCtx","data":{"coin":"BTC","ctx":{"oraclePx":"100000"}}}`)})
		}
	}
	if s.Stages[stage["id"].(string)].Status != "survived" {
		t.Fatal("fee pause revoked accepted outcome")
	}
	do(Command{Kind: "paper_settle"})
	if s.Debt() != 0 || s.Local.LPFeeAccrued != 25_000_000 || s.Recovery.PnL != -26_000_000 {
		t.Fatal("funding reset recovery or fee")
	}
}
