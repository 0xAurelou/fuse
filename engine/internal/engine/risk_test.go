package engine_test

import (
	"context"
	"encoding/json"
	"fmt"
	"testing"

	"fuse/engine/internal/engine"
)

func TestCorrelatedPositionsReserveAdditively(t *testing.T) {
	f := newFixture(t)
	// Each account promises a payout on the same observation path. No statistical
	// independence or simultaneous-outcome discount may reduce their reservation.
	var expected int64
	for i := 0; i < 12; i++ {
		account := fmt.Sprintf("correlated-%d", i)
		id := fmt.Sprintf("deposit-%d", i+2)
		f.do(engine.Command{Kind: "deposit", Actor: account, ID: id, Amount: 100_000_000})
		f.do(engine.Command{Kind: "ack_deposit", ID: id})
		beforeQuote := f.q.Snapshot()
		e, quoteErr := f.q.Execute(context.Background(), f.cmd(engine.Command{Kind: "quote", Actor: account, Amount: 100_000_000}))
		if quoteErr != nil {
			if engine.Hash(beforeQuote) != engine.Hash(f.q.Snapshot()) {
				t.Fatal("quote rejection mutated balances")
			}
			break
		}
		var quote engine.Quote
		_ = json.Unmarshal(e.Result, &quote)
		before := f.q.Snapshot()
		c := f.cmd(engine.Command{Kind: "enter", Actor: account, ID: quote.ID})
		_, err := f.q.Execute(context.Background(), c)
		if err != nil {
			if engine.Hash(f.q.Snapshot()) != engine.Hash(before) {
				t.Fatal("rejected entry mutated funds")
			}
			break
		}
		expected += quote.Payout - quote.Stake
		total, _, _ := f.q.Snapshot().Exposure()
		if total != expected {
			t.Fatalf("correlated exposure %d != %d", total, expected)
		}
	}
	if expected == 0 {
		t.Fatal("no positions accepted")
	}
}
func TestUnpairedExpiryCannotLaterBecomeSurvival(t *testing.T) {
	f := newFixture(t)
	p := f.enter(f.quote(""))
	for f.now+5000 < p.Expiry {
		f.now += 5000
		f.price("100000")
	}
	f.now = p.Expiry - 1
	f.do(engine.Command{Kind: "oracle", Source: "a", Raw: json.RawMessage(`{"channel":"activeAssetCtx","data":{"coin":"BTC","ctx":{"oraclePx":"100001"}}}`)})
	f.now = p.Expiry
	f.do(engine.Command{Kind: "tick"})
	f.price("100000")
	f.do(engine.Command{Kind: "tick"})
	if f.q.Snapshot().Stages[p.ID].Status != "pending" {
		t.Fatal("ambiguous expiry turned into a win")
	}
}
func TestBreachAlreadyEstablishedSurvivesOutage(t *testing.T) {
	f := newFixture(t)
	p := f.enter(f.quote(""))
	f.now++
	f.price("1")
	f.now = p.Expiry + f.policy.VoidDelayMS
	f.do(engine.Command{Kind: "tick"})
	if f.q.Snapshot().Stages[p.ID].Status != "exploded" {
		t.Fatal("valid breach erased")
	}
}

func TestVersionedModelUpdatePreservesAcceptedTerms(t *testing.T) {
	f := newFixture(t)
	p := f.enter(f.quote(""))
	accepted := engine.Hash(p.Terms)
	next := f.policy
	next.Version = "paper-v2"
	next.Model.Version = "paper-range-v2"
	next.Model.BaseWidthBPS = 60
	next.Model.ControlWidthBPS = 60
	raw, _ := json.Marshal(next)
	f.do(engine.Command{Kind: "policy_update", Raw: raw})
	if engine.Hash(f.q.Snapshot().Stages[p.ID].Terms) != accepted {
		t.Fatal("accepted terms mutated")
	}
	timing := next
	timing.Version = "paper-v3"
	timing.MaxGapMS++
	raw, _ = json.Marshal(timing)
	before := f.q.Snapshot()
	if _, err := f.q.Execute(context.Background(), f.cmd(engine.Command{Kind: "policy_update", Raw: raw})); err == nil || engine.Hash(before) != engine.Hash(f.q.Snapshot()) {
		t.Fatal("accepted gap rules changed")
	}
	replayed, err := engine.Open(context.Background(), f.policy, f.store)
	if err != nil || engine.Hash(replayed.Snapshot()) != engine.Hash(f.q.Snapshot()) {
		t.Fatal("policy history does not replay", err)
	}
}
