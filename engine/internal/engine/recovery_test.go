package engine_test

import (
	"context"
	"encoding/json"
	"fuse/engine/internal/engine"
	"fuse/engine/internal/storage"
	"strings"
	"testing"
)

func recoveryFixture(t *testing.T) *fixture {
	p := newFixture(t).policy
	p.Recovery = &engine.RecoveryPolicy{Version: "research-fixed-usdc-v1", DailyLoss: 20_000_000, RollingLoss: 40_000_000, RollingMS: 7 * 86_400_000, PauseDrawdown: 15_000_000, HardDrawdown: 40_000_000, ResumeDrawdown: 5_000_000, CooldownMS: 1000, ProbeLoss: 2_000_000}
	store := &storage.Memory{}
	q, err := engine.Open(context.Background(), p, store)
	if err != nil {
		t.Fatal(err)
	}
	f := &fixture{t: t, q: q, store: store, now: 1_000_000, policy: p}
	f.do(engine.Command{Kind: "lp_fund", Amount: 1_000_000_000})
	f.price("100000")
	f.do(engine.Command{Kind: "deposit", Actor: "alice", ID: "d", Amount: 100_000_000})
	f.do(engine.Command{Kind: "ack_deposit", ID: "d"})
	return f
}
func rejectRisk(t *testing.T, f *fixture, c engine.Command, reason string) {
	t.Helper()
	before := engine.Hash(f.q.Snapshot())
	_, err := f.q.Execute(context.Background(), f.cmd(c))
	if err == nil || !strings.Contains(err.Error(), reason) {
		t.Fatalf("wanted %s, got %v", reason, err)
	}
	if engine.Hash(f.q.Snapshot()) != before {
		t.Fatal("rejection changed committed state")
	}
}
func TestRecoveryAtomicReservationAndReplay(t *testing.T) {
	f := recoveryFixture(t)
	f.enter(f.quote(""))
	quotes := []engine.Quote{}
	for _, a := range []string{"bob", "carol"} {
		f.do(engine.Command{Kind: "deposit", Actor: a, ID: a, Amount: 100_000_000})
		f.do(engine.Command{Kind: "ack_deposit", ID: a})
		e := f.do(engine.Command{Kind: "quote", Actor: a, Amount: 10_000_000})
		var q engine.Quote
		json.Unmarshal(e.Result, &q)
		quotes = append(quotes, q)
	}
	f.do(engine.Command{Kind: "enter", Actor: "carol", ID: quotes[1].ID})
	rejectRisk(t, f, engine.Command{Kind: "enter", Actor: "bob", ID: quotes[0].ID}, "rolling 24h")
	got, err := engine.Open(context.Background(), f.policy, f.store)
	if err != nil || engine.Hash(got.Snapshot()) != engine.Hash(f.q.Snapshot()) {
		t.Fatalf("replay: %v", err)
	}
}
func TestRecoveryPauseKeepsClaimsPayableAndCapitalCannotReset(t *testing.T) {
	f := recoveryFixture(t)
	for i := 0; i < 2; i++ {
		p := f.enter(f.quote(""))
		f.survive(p)
		f.do(engine.Command{Kind: "cashout", Actor: "alice", ID: p.ID})
	}
	if f.q.Snapshot().Recovery.Mode != "paused" {
		t.Fatal("drawdown did not pause")
	}
	f.do(engine.Command{Kind: "lp_fund", Amount: 100_000_000})
	f.do(engine.Command{Kind: "deposit", Actor: "alice", ID: "extra", Amount: 10_000_000})
	f.do(engine.Command{Kind: "ack_deposit", ID: "extra"})
	rejectRisk(t, f, engine.Command{Kind: "resume"}, "cooldown")
	rejectRisk(t, f, engine.Command{Kind: "quote", Actor: "alice", Amount: 1_000_000}, "cooldown")
	e := f.do(engine.Command{Kind: "withdraw", Actor: "alice", Amount: 10_000_000})
	var w engine.Withdrawal
	json.Unmarshal(e.Result, &w)
	f.do(engine.Command{Kind: "paper_settle"})
	f.do(engine.Command{Kind: "paper_pay", ID: w.ID})
	r := f.q.Snapshot().Recovery
	if r.Mode != "paused" || len(r.Losses) != 2 {
		t.Fatalf("limits reset: %+v", r)
	}
	f.now = 86_400_001
	f.do(engine.Command{Kind: "tick"})
	f.price("100000")
	if f.q.Snapshot().Recovery.Mode != "probe" {
		t.Fatal("cooldown did not enter probe")
	}
	rejectRisk(t, f, engine.Command{Kind: "quote", Actor: "alice", Amount: 10_000_000}, "rolling 24h")
	f.now += 86_400_000
	f.do(engine.Command{Kind: "tick"})
	f.price("100000")
	rejectRisk(t, f, engine.Command{Kind: "quote", Actor: "alice", Amount: 10_000_000}, "probe budget")
	e = f.do(engine.Command{Kind: "quote", Actor: "alice", Amount: 1_000_000})
	var q engine.Quote
	json.Unmarshal(e.Result, &q)
	p := f.enter(q)
	f.survive(p)
	if f.q.Snapshot().Recovery.Mode != "paused" {
		t.Fatal("losing probe did not restart cooldown")
	}
	replay, err := engine.Open(context.Background(), f.policy, f.store)
	if err != nil || engine.Hash(replay.Snapshot()) != engine.Hash(f.q.Snapshot()) {
		t.Fatalf("recovery replay: %v", err)
	}
}
func TestRecoveryPolicyCannotBeRemovedOrReset(t *testing.T) {
	f := recoveryFixture(t)
	for _, remove := range []bool{true, false} {
		p := f.q.Snapshot().Policy
		p.Version = "changed"
		if remove {
			p.Recovery = nil
		} else {
			p.Recovery.DailyLoss++
		}
		raw, _ := json.Marshal(p)
		rejectRisk(t, f, engine.Command{Kind: "policy_update", Raw: raw}, "immutable")
	}
	f.store.Fail = true
	before := engine.Hash(f.q.Snapshot())
	_, err := f.q.Execute(context.Background(), f.cmd(engine.Command{Kind: "tick"}))
	if err == nil || engine.Hash(f.q.Snapshot()) != before || f.q.Ready() {
		t.Fatal("storage failure committed or did not fence")
	}
}
func TestRecoveryValidation(t *testing.T) {
	f := recoveryFixture(t)
	for _, mutate := range []func(*engine.RecoveryPolicy){
		func(p *engine.RecoveryPolicy) { p.DailyLoss = 0 }, func(p *engine.RecoveryPolicy) { p.RollingMS = 1 },
		func(p *engine.RecoveryPolicy) { p.ResumeDrawdown = p.PauseDrawdown }, func(p *engine.RecoveryPolicy) { p.ProbeLoss = p.DailyLoss + 1 },
	} {
		p := *f.policy.Recovery
		mutate(&p)
		if p.Validate() == nil {
			t.Fatalf("invalid policy accepted: %+v", p)
		}
	}
}

func TestRecoveryRolloverChargesIncrementalLossOnce(t *testing.T) {
	f := recoveryFixture(t)
	p := f.enter(f.quote(""))
	f.survive(p)
	before := f.q.Snapshot()
	if before.Recovery.Losses[0].Amount != p.Terms.Payout-p.Terms.Stake || before.PendingRisk() != 0 {
		t.Fatal("incorrect realized stage loss")
	}
	rejectRisk(t, f, engine.Command{Kind: "quote", Actor: "alice", Previous: p.ID}, "rolling 24h")
	f.do(engine.Command{Kind: "paper_settle"})
	if engine.Hash(before.Recovery) != engine.Hash(f.q.Snapshot().Recovery) {
		t.Fatal("funding double-charged risk")
	}
}
func TestRecoveryVoidsReleaseReservationAndProfitsDoNotRefill(t *testing.T) {
	f := recoveryFixture(t)
	p := f.enter(f.quote(""))
	f.now = p.Expiry + f.policy.VoidDelayMS
	f.do(engine.Command{Kind: "tick"})
	if len(f.q.Snapshot().Recovery.Losses) != 0 || f.q.Snapshot().PendingRisk() != 0 {
		t.Fatal("void consumed loss budget")
	}
	f.price("100000")
	p = f.enter(f.quote(""))
	f.survive(p)
	f.do(engine.Command{Kind: "cashout", Actor: "alice", ID: p.ID})
	p = f.enter(f.quote(""))
	f.price("99499")
	if f.q.Snapshot().Stages[p.ID].Status != "exploded" || len(f.q.Snapshot().Recovery.Losses) != 1 {
		t.Fatal("gross loss history changed")
	}
	rejectRisk(t, f, engine.Command{Kind: "quote", Actor: "alice", Amount: 20_000_000}, "rolling 24h")
}

func TestRecoveryConfigurationDoesNotAliasCaller(t *testing.T) {
	f := recoveryFixture(t)
	f.policy.Recovery.DailyLoss = 1
	if f.q.Snapshot().Policy.Recovery.DailyLoss != 20_000_000 {
		t.Fatal("caller changed durable recovery policy outside journal")
	}
}
