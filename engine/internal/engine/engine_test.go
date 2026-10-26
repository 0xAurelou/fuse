package engine_test

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"sync"
	"testing"

	"fuse/engine/internal/engine"
	"fuse/engine/internal/storage"
)

type fixture struct {
	t      *testing.T
	q      *engine.Sequencer
	store  *storage.Memory
	now    int64
	n      int
	policy engine.Policy
}

func newFixture(t *testing.T) *fixture {
	t.Helper()
	return fixturePolicy(t, "../../testdata/legacy-ladder-policy.json")
}

func fixturePolicy(t *testing.T, path string) *fixture {
	t.Helper()
	raw, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	var p engine.Policy
	if err = json.Unmarshal(raw, &p); err != nil {
		t.Fatal(err)
	}
	store := &storage.Memory{}
	q, err := engine.Open(context.Background(), p, store)
	if err != nil {
		t.Fatal(err)
	}
	f := &fixture{t: t, q: q, store: store, now: 1_000_000, policy: p}
	f.do(engine.Command{Kind: "lp_fund", Amount: 1_000_000_000})
	f.price("100000")
	f.do(engine.Command{Kind: "deposit", Actor: "alice", ID: "deposit-1", Amount: 100_000_000})
	f.do(engine.Command{Kind: "ack_deposit", ID: "deposit-1"})
	return f
}
func (f *fixture) cmd(c engine.Command) engine.Command {
	f.n++
	if c.Key == "" {
		c.Key = fmt.Sprint("test/", f.n)
	}
	if c.At == 0 {
		c.At = f.now
	}
	return c
}
func (f *fixture) do(c engine.Command) engine.Event {
	f.t.Helper()
	e, err := f.q.Execute(context.Background(), f.cmd(c))
	if err != nil {
		f.t.Fatalf("%s: %v", c.Kind, err)
	}
	return e
}
func (f *fixture) price(p string) {
	f.t.Helper()
	for _, src := range []string{"a", "b"} {
		f.do(engine.Command{Kind: "oracle", Source: src, Raw: json.RawMessage(fmt.Sprintf(`{"channel":"activeAssetCtx","data":{"coin":"BTC","ctx":{"oraclePx":%q,"markPx":"1"}}}`, p))})
	}
}
func (f *fixture) quote(previous string) engine.Quote {
	f.t.Helper()
	e := f.do(engine.Command{Kind: "quote", Actor: "alice", Amount: 10_000_000, Previous: previous})
	var q engine.Quote
	_ = json.Unmarshal(e.Result, &q)
	return q
}
func (f *fixture) enter(q engine.Quote) engine.Stage {
	f.t.Helper()
	e := f.do(engine.Command{Kind: "enter", Actor: "alice", ID: q.ID})
	var p engine.Stage
	_ = json.Unmarshal(e.Result, &p)
	return p
}
func (f *fixture) survive(p engine.Stage) {
	f.t.Helper()
	for f.now+5000 < p.Expiry {
		f.now += 5000
		f.price("100000")
	}
	f.now = p.Expiry
	f.price("100000")
	f.do(engine.Command{Kind: "tick"})
}
func TestEightStagesExact100AndReplay(t *testing.T) {
	f := newFixture(t)
	f.do(engine.Command{Kind: "lp_fund", Amount: 1_000_000_000})
	var previous string
	for i := 1; i <= 8; i++ {
		q := f.quote(previous)
		p := f.enter(q)
		f.survive(p)
		if got := f.q.Snapshot().Stages[p.ID].Status; got != "survived" {
			t.Fatal(got)
		}
		previous = p.ID
	}
	f.do(engine.Command{Kind: "cashout", Actor: "alice", ID: previous})
	s := f.q.Snapshot()
	if s.Accounts["alice"].Available+s.Accounts["alice"].Unfunded != 1_090_000_000 {
		t.Fatal(s.Accounts["alice"])
	}
	q, err := engine.Open(context.Background(), f.policy, f.store)
	if err != nil {
		t.Fatal(err)
	}
	if engine.Hash(q.Snapshot()) != engine.Hash(s) {
		t.Fatal("replay differs")
	}
	for _, e := range q.Events(0, 1000) {
		sums := map[string]int64{}
		for _, p := range e.Postings {
			sums[p.Asset] += p.Delta
		}
		for _, v := range sums {
			if v != 0 {
				t.Fatal("unbalanced posting")
			}
		}
	}
}
func TestTouchAndPostExpiry(t *testing.T) {
	for _, side := range []string{"lower", "upper"} {
		t.Run(side, func(t *testing.T) {
			f := newFixture(t)
			p := f.enter(f.quote(""))
			barrier := p.Terms.Lower
			if side == "upper" {
				barrier = p.Terms.Upper
			}
			f.now++
			f.price(fmt.Sprintf("%d.%06d", barrier/1_000_000, barrier%1_000_000))
			s := f.q.Snapshot()
			if s.Stages[p.ID].Status != "exploded" || s.Accounts["alice"].Available != 90_000_000 {
				t.Fatal(s.Stages[p.ID])
			}
			f.do(engine.Command{Kind: "paper_settle"})
			if f.q.Snapshot().LP != 1_010_000_000 {
				t.Fatal("lost stake not settled")
			}
		})
	}
	f := newFixture(t)
	p := f.enter(f.quote(""))
	f.survive(p)
	f.now++
	f.price("1")
	if f.q.Snapshot().Stages[p.ID].Status != "survived" {
		t.Fatal("post-expiry breach")
	}
}
func TestGapIsPendingThenRefundAndDuplicateDoesNotHeal(t *testing.T) {
	f := newFixture(t)
	p := f.enter(f.quote(""))
	f.now += f.policy.MaxGapMS + 1
	f.do(engine.Command{Kind: "tick"})
	if f.q.Snapshot().Stages[p.ID].Status != "pending" {
		t.Fatal("gap survived")
	}
	f.price("100000")
	f.now = p.Expiry + f.policy.VoidDelayMS
	f.do(engine.Command{Kind: "tick"})
	s := f.q.Snapshot()
	if s.Stages[p.ID].Status != "voided" || s.Accounts["alice"].Available != 100_000_000 {
		t.Fatal(s.Stages[p.ID])
	}
}
func TestRolloverDebtReplacementAndRejectionPreservesWin(t *testing.T) {
	f := newFixture(t)
	p := f.enter(f.quote(""))
	f.survive(p)
	before := f.q.Snapshot()
	q := f.quote(p.ID)
	next := f.enter(q)
	s := f.q.Snapshot()
	exposure, _, _ := s.Exposure()
	if exposure != next.Terms.Payout-10_000_000 || s.Accounts["alice"].EarnedUnfunded != 0 || s.Debt() != before.Debt() {
		t.Fatalf("double counted rollover: exposure=%d debt=%d", exposure, s.Debt())
	}
	f.now++
	f.price("1")
	if f.q.Snapshot().Debt() != 0 {
		t.Fatal("lost rollover debt retained")
	}
	f = newFixture(t)
	p = f.enter(f.quote(""))
	f.survive(p)
	f.do(engine.Command{Kind: "pause"})
	before = f.q.Snapshot()
	_, err := f.q.Execute(context.Background(), f.cmd(engine.Command{Kind: "quote", Actor: "alice", Previous: p.ID}))
	if err == nil || engine.Hash(before) != engine.Hash(f.q.Snapshot()) {
		t.Fatal("rejected rollover altered earned claim")
	}
	f.do(engine.Command{Kind: "cashout", Actor: "alice", ID: p.ID})
}
func TestAtomicRetriesAndConcurrentEntry(t *testing.T) {
	f := newFixture(t)
	q := f.quote("")
	c := f.cmd(engine.Command{Key: "same", Kind: "enter", Actor: "alice", ID: q.ID})
	var wg sync.WaitGroup
	out := make(chan engine.Event, 20)
	for i := 0; i < 20; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			e, err := f.q.Execute(context.Background(), c)
			if err != nil {
				t.Error(err)
			}
			out <- e
		}()
	}
	wg.Wait()
	close(out)
	var seq uint64
	for e := range out {
		if seq == 0 {
			seq = e.Sequence
		}
		if seq != e.Sequence {
			t.Fatal("duplicated acceptance")
		}
	}
	if f.q.Snapshot().Accounts["alice"].Available != 90_000_000 {
		t.Fatal("duplicate debit")
	}
	c.ID = "other"
	if _, err := f.q.Execute(context.Background(), c); err == nil {
		t.Fatal("idempotency conflict accepted")
	}
}
func TestDepositsRefundAndWithdrawalFunding(t *testing.T) {
	f := newFixture(t)
	f.do(engine.Command{Kind: "deposit", Actor: "bob", ID: "refundable", Amount: 1_000_000})
	if f.q.Snapshot().Accounts["bob"].Available != 0 {
		t.Fatal("pending deposit credited")
	}
	f.do(engine.Command{Kind: "refund_deposit", ID: "refundable"})
	if _, err := f.q.Execute(context.Background(), f.cmd(engine.Command{Kind: "ack_deposit", ID: "refundable"})); err == nil {
		t.Fatal("refund credited")
	}
	p := f.enter(f.quote(""))
	f.survive(p)
	f.do(engine.Command{Kind: "cashout", Actor: "alice", ID: p.ID})
	e := f.do(engine.Command{Kind: "withdraw", Actor: "alice", Amount: 107_000_000})
	var w engine.Withdrawal
	_ = json.Unmarshal(e.Result, &w)
	if _, err := f.q.Execute(context.Background(), f.cmd(engine.Command{Kind: "paper_pay", ID: w.ID})); err == nil {
		t.Fatal("unfunded payment")
	}
	if _, err := f.q.Execute(context.Background(), f.cmd(engine.Command{Kind: "withdraw", Actor: "alice", Amount: 1})); err == nil {
		t.Fatal("overlapping claim")
	}
	f.do(engine.Command{Kind: "paper_settle"})
	f.do(engine.Command{Kind: "paper_pay", ID: w.ID})
	if _, err := f.q.Execute(context.Background(), f.cmd(engine.Command{Kind: "paper_pay", ID: w.ID})); err == nil {
		t.Fatal("double withdrawal")
	}
	if err := f.q.Snapshot().Check(); err != nil {
		t.Fatal(err)
	}
}
func TestStorageFailureFencesWithoutAcknowledgment(t *testing.T) {
	f := newFixture(t)
	before := engine.Hash(f.q.Snapshot())
	f.store.Fail = true
	if _, err := f.q.Execute(context.Background(), f.cmd(engine.Command{Kind: "pause"})); err == nil {
		t.Fatal("failed commit acknowledged")
	}
	if f.q.Ready() || engine.Hash(f.q.Snapshot()) != before {
		t.Fatal("state changed on failed commit")
	}
	f.store.Fail = false
	if _, err := f.q.Execute(context.Background(), f.cmd(engine.Command{Kind: "tick"})); err == nil {
		t.Fatal("uncertain writer resumed")
	}
	if _, err := engine.Open(context.Background(), f.policy, f.store); err != nil {
		t.Fatal(err)
	}
}
func TestPricePrecisionAndUnsafeConfig(t *testing.T) {
	for _, v := range []string{"1e5", "-1", "NaN", "1.0000001", "0", "1000000000000000000000", ".1"} {
		if _, err := engine.ParsePrice(v); err == nil {
			t.Fatal(v)
		}
	}
	f := newFixture(t)
	p := f.policy
	p.Mode = "production"
	if _, err := engine.NewState(p); err == nil {
		t.Fatal("unsafe configuration")
	}
	_, err := f.q.Execute(context.Background(), f.cmd(engine.Command{Kind: "enter", Actor: "alice", ID: "absent"}))
	if !errors.Is(err, engine.ErrRejected) {
		t.Fatal(err)
	}
}

func TestFractionalResearchWidthHasExactTouchBoundary(t *testing.T) {
	f := newFixture(t)
	p := f.policy
	p.Version = "fractional-v2"
	p.Model.Version = "fractional-model"
	p.Model.BaseWidthBPS = 0
	p.Model.ControlWidthBPS = 0
	p.Model.BaseWidthPPM = 5
	p.Model.VolatilityFactor = 0
	raw, _ := json.Marshal(p)
	f.do(engine.Command{Kind: "policy_update", Raw: raw})
	quote := f.quote("")
	if quote.Upper != 100000500000 || quote.Lower != 99999500000 {
		t.Fatal(quote)
	}
	stage := f.enter(quote)
	f.now++
	f.price("100000.5")
	if f.q.Snapshot().Stages[stage.ID].Status != "exploded" {
		t.Fatal("fractional boundary touch survived")
	}
	p.Model.BaseWidthBPS = 1
	if p.Validate() == nil {
		t.Fatal("ambiguous bps/ppm units accepted")
	}
}
