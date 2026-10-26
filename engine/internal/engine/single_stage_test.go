package engine_test

import (
	"context"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"testing"

	"fuse/engine/internal/engine"
)

func singleFixture(t *testing.T) *fixture {
	t.Helper()
	return fixturePolicy(t, "../../config/paper.json")
}

func (f *fixture) selectQuote(amount, multiplier int64) engine.Quote {
	f.t.Helper()
	e := f.do(engine.Command{Kind: "quote", Actor: "alice", Amount: amount, Multiplier: multiplier})
	var q engine.Quote
	if err := json.Unmarshal(e.Result, &q); err != nil {
		f.t.Fatal(err)
	}
	return q
}

func TestEverySingleStageMultiplierHasExactPayoutAndNarrowerCorridor(t *testing.T) {
	f := singleFixture(t)
	f.do(engine.Command{Kind: "lp_fund", Amount: 10_000_000_000})
	width := engine.Limit
	for _, m := range engine.PayoutOptions() {
		q := f.selectQuote(1_000_000, m)
		if q.Multiplier != m || q.Product != engine.SingleStage || q.Payout != 1_000_000*m || q.Previous != "" || q.Index != 1 || q.DurationMS != 30_000 {
			t.Fatalf("incorrect single-stage terms: %+v", q)
		}
		if q.Upper-q.Price >= width || q.Price-q.Lower != q.Upper-q.Price {
			t.Fatal("corridor did not strictly narrow", m, q)
		}
		width = q.Upper - q.Price
	}
}

func TestSingleStageRejectsInvalidSelectionAndRolloverAtomically(t *testing.T) {
	f := singleFixture(t)
	for _, m := range []int64{0, 1, -2, 3, 24, 26, 99, 101, 249, 251, 999, 1001, 9999, 10001, engine.Limit} {
		rejectRisk(t, f, engine.Command{Kind: "quote", Actor: "alice", Amount: 1_000_000, Multiplier: m}, "integer multiplier")
	}
	rejectRisk(t, f, engine.Command{Kind: "quote", Actor: "alice", Amount: 1_000_000, Multiplier: 2, Previous: "stage-1"}, "no previous stage")
	q := f.selectQuote(1_000_000, 100)
	rejectRisk(t, f, engine.Command{Kind: "enter", Actor: "alice", ID: q.ID, Multiplier: 2}, "cannot be overridden")
	p := f.enter(q)
	rejectRisk(t, f, engine.Command{Kind: "quote", Actor: "alice", Amount: 1_000_000, Multiplier: 2}, "unfinished run")
	f.survive(p)
	rejectRisk(t, f, engine.Command{Kind: "cashout", Actor: "alice", ID: p.ID}, "no survived stage")
	rejectRisk(t, f, engine.Command{Kind: "quote", Actor: "alice", Amount: 1_000_000, Multiplier: 2, Previous: p.ID}, "no previous stage")
}

func TestSingleStage100xAutomaticCreditReentrySettlementWithdrawalAndReplay(t *testing.T) {
	f := singleFixture(t)
	p := f.enter(f.selectQuote(1_000_000, 100))
	f.survive(p)
	s := f.q.Snapshot()
	a := s.Accounts["alice"]
	if a.Available != 100_000_000 || a.Unfunded != 99_000_000 || a.RunHead != "" || a.EarnedFunded+a.EarnedUnfunded != 0 {
		t.Fatal("100x win was not automatically credited with funding separated", a)
	}
	// Re-entry with a mixture of physical funds and unpaid winnings is a new
	// independent trade. Debt must be replaced, never counted as physical cash.
	p = f.enter(f.selectQuote(199_000_000, 2))
	if p.Funded != 100_000_000 || p.Debt != 99_000_000 || p.Terms.Payout != 398_000_000 {
		t.Fatal(p)
	}
	exposure, _, _ := f.q.Snapshot().Exposure()
	if exposure != 298_000_000 {
		t.Fatal("unpaid winnings counted twice", exposure)
	}
	f.survive(p)
	f.do(engine.Command{Kind: "withdraw", Actor: "alice", Amount: 398_000_000})
	s = f.q.Snapshot()
	w := s.Accounts["alice"].Withdrawal
	rejectRisk(t, f, engine.Command{Kind: "paper_pay", ID: w}, "not funded")
	f.do(engine.Command{Kind: "paper_settle"})
	f.do(engine.Command{Kind: "paper_pay", ID: w})
	s = f.q.Snapshot()
	if s.LP != 702_000_000 || s.Custody != 0 || s.Debt() != 0 || s.Accounts["alice"].Withdrawn != 398_000_000 {
		t.Fatal("settlement accounting mismatch", s)
	}
	replayed, err := engine.Open(context.Background(), f.policy, f.store)
	if err != nil || engine.Hash(replayed.Snapshot()) != engine.Hash(s) {
		t.Fatal("single-stage replay diverged", err)
	}
}

func TestSingleStageTouchVoidAndAcceptedTermsSurvivePolicyChange(t *testing.T) {
	for _, outcome := range []string{"lower", "upper", "void", "win"} {
		t.Run(outcome, func(t *testing.T) {
			f := singleFixture(t)
			p := f.enter(f.selectQuote(1_000_000, 100))
			policy := f.q.Snapshot().Policy
			policy.Version += "-updated"
			policy.Model.Version += "-updated"
			policy.Model.DNT.VolatilityPPM *= 2
			raw, _ := json.Marshal(policy)
			f.do(engine.Command{Kind: "policy_update", Raw: raw})
			if outcome == "win" {
				f.survive(p)
			} else if outcome == "void" {
				f.now = p.Expiry + policy.VoidDelayMS
				f.do(engine.Command{Kind: "tick"})
			} else {
				barrier := p.Terms.Lower
				if outcome == "upper" {
					barrier = p.Terms.Upper
				}
				f.now++
				f.price(fmt.Sprintf("%d.%06d", barrier/1_000_000, barrier%1_000_000))
			}
			s := f.q.Snapshot()
			got := s.Stages[p.ID]
			want, balance := "exploded", int64(99_000_000)
			if outcome == "void" {
				want, balance = "voided", 100_000_000
			}
			if outcome == "win" {
				want, balance = "survived", 199_000_000
			}
			if got.Status != want || s.Balance("alice").EconomicBalance != balance || engine.Hash(got.Terms) != engine.Hash(p.Terms) || s.Accounts["alice"].RunHead != "" {
				t.Fatal(got, s.Balance("alice"))
			}
		})
	}
}

func TestSingleStageReservesFull100xLiabilityAndRechecksCapacity(t *testing.T) {
	f := singleFixture(t)
	rejectRisk(t, f, engine.Command{Kind: "quote", Actor: "alice", Amount: 100_000_000, Multiplier: 100}, "LP capacity")
	q := f.selectQuote(5_000_000, 100)
	if q.MaxLPLiability != 495_000_000 {
		t.Fatal(q)
	}
	f.do(engine.Command{Kind: "deposit", Actor: "bob", ID: "bob", Amount: 10_000_000})
	f.do(engine.Command{Kind: "ack_deposit", ID: "bob"})
	e := f.do(engine.Command{Kind: "quote", Actor: "bob", Amount: 5_000_000, Multiplier: 100})
	var bob engine.Quote
	json.Unmarshal(e.Result, &bob)
	f.do(engine.Command{Kind: "enter", Actor: "bob", ID: bob.ID})
	rejectRisk(t, f, engine.Command{Kind: "enter", Actor: "alice", ID: q.ID}, "LP capacity")
}

func TestSingleStagePolicyRejectsMissingAndNonmonotonePricing(t *testing.T) {
	for _, change := range []func(*engine.Policy){
		func(p *engine.Policy) { p.Model.DNT = nil },
		func(p *engine.Policy) { p.Model.DNT.VolatilityPPM = 0 },
		func(p *engine.Policy) { p.Model.MultiplierWidthsPPM = map[int64]int64{100: 1} },
		func(p *engine.Policy) { p.Product = "unknown" },
		func(p *engine.Policy) { p.Multipliers = []int64{2, 3, 10000} },
	} {
		p := singleFixture(t).q.Snapshot().Policy
		change(&p)
		if p.Validate() == nil {
			t.Fatal("invalid single-stage policy accepted")
		}
	}
}

func TestHighPayoutCreditLiabilityAndReplay(t *testing.T) {
	for _, multiplier := range []int64{250, 1000, 10000} {
		t.Run(fmt.Sprint(multiplier), func(t *testing.T) {
			f := singleFixture(t)
			f.do(engine.Command{Kind: "lp_fund", Amount: 10_000_000_000})
			q := f.selectQuote(1_000_000, multiplier)
			if q.MaxLPLiability != (multiplier-1)*1_000_000 || q.TargetSurvivalPPB != 950_000_000/multiplier {
				t.Fatal("incorrect high-payout liability or model target", q)
			}
			p := f.enter(q)
			f.survive(p)
			s := f.q.Snapshot()
			if s.Stages[p.ID].Status != "survived" || s.Balance("alice").EconomicBalance != 100_000_000+(multiplier-1)*1_000_000 {
				t.Fatal("high-payout win was not credited", s.Balance("alice"))
			}
			replayed, err := engine.Open(context.Background(), f.policy, f.store)
			if err != nil || engine.Hash(replayed.Snapshot()) != engine.Hash(s) {
				t.Fatal("high-payout replay diverged", err)
			}
		})
	}
	f := singleFixture(t)
	rejectRisk(t, f, engine.Command{Kind: "quote", Actor: "alice", Amount: 1_000_000, Multiplier: 10000}, "LP capacity")
	f.do(engine.Command{Kind: "lp_fund", Amount: 100_000_000_000})
	rejectRisk(t, f, engine.Command{Kind: "quote", Actor: "alice", Amount: 10_000_000, Multiplier: 10000}, "account exposure limit")
}

func TestPresetPolicyUpdatePreservesHistoricalSelectionsAndReplay(t *testing.T) {
	policy := singleFixture(t).policy
	policy.Multipliers = nil
	policy.Version = "historical-single-stage"
	raw, _ := json.Marshal(policy)
	path := filepath.Join(t.TempDir(), "legacy.json")
	if err := os.WriteFile(path, raw, 0600); err != nil {
		t.Fatal(err)
	}
	f := fixturePolicy(t, path)
	p := f.enter(f.selectQuote(1_000_000, 42))
	policy.Multipliers = engine.PayoutOptions()
	policy.Version = "preset-single-stage"
	raw, _ = json.Marshal(policy)
	f.do(engine.Command{Kind: "policy_update", Raw: raw})
	f.survive(p)
	if f.q.Snapshot().Stages[p.ID].Terms.Multiplier != 42 {
		t.Fatal("policy update changed accepted historical terms")
	}
	rejectRisk(t, f, engine.Command{Kind: "quote", Actor: "alice", Amount: 1_000_000, Multiplier: 42}, "integer multiplier")
	f.selectQuote(1_000_000, 250)
	replayed, err := engine.Open(context.Background(), f.policy, f.store)
	if err != nil || engine.Hash(replayed.Snapshot()) != engine.Hash(f.q.Snapshot()) {
		t.Fatal("historical/preset policy replay diverged", err)
	}
}
