package engine_test

import (
	"context"
	"encoding/json"
	"fmt"
	"testing"

	"fuse/engine/internal/engine"
)

func (f *fixture) assetPrice(asset, price string) {
	f.t.Helper()
	for _, source := range []string{"a", "b"} {
		f.do(engine.Command{Kind: "oracle", Source: source, Raw: json.RawMessage(fmt.Sprintf(`{"channel":"activeAssetCtx","data":{"coin":%q,"ctx":{"oraclePx":%q}}}`, asset, price))})
	}
}
func (f *fixture) assetQuote(asset string, stake, multiplier int64) engine.Quote {
	f.t.Helper()
	event := f.do(engine.Command{Kind: "quote", Actor: "alice", Asset: asset, Amount: stake, Multiplier: multiplier})
	var quote engine.Quote
	if err := json.Unmarshal(event.Result, &quote); err != nil {
		f.t.Fatal(err)
	}
	return quote
}
func multiFixture(t *testing.T) *fixture {
	f := singleFixture(t)
	f.assetPrice("ETH", "3000")
	f.assetPrice("HYPE", "40")
	return f
}

func TestThreeIndependentMarketsReserveSettleAndReplay(t *testing.T) {
	f := multiFixture(t)
	btc := f.assetQuote("BTC", 10_000_000, 2)
	hype := f.assetQuote("HYPE", 10_000_000, 25)
	eth := f.assetQuote("ETH", 10_000_000, 10)
	if len(f.q.Snapshot().Quotes) != 3 {
		t.Fatal("one market quote deleted another")
	}
	if btc.Asset != "BTC" || hype.Asset != "HYPE" || eth.Asset != "ETH" || eth.VolatilityPPM != 1500 || hype.VolatilityPPM != 3000 {
		t.Fatal("incorrect per-market quote terms")
	}
	b, h, e := f.enter(btc), f.enter(hype), f.enter(eth)
	s := f.q.Snapshot()
	exposure, by, active := s.Exposure()
	if active != 3 || exposure != 340_000_000 || by["alice"] != exposure || s.Accounts["alice"].Available != 70_000_000 {
		t.Fatal("shared funding/exposure mismatch", exposure, by, active)
	}
	f.now++
	f.assetPrice("BTC", "101000")
	s = f.q.Snapshot()
	if s.Stages[b.ID].Status != "exploded" || s.Stages[h.ID].Status != "active" || s.Stages[e.ID].Status != "active" {
		t.Fatal("BTC observation affected a different market")
	}
	f.assetPrice("HYPE", "42")
	for f.now+5000 < e.Expiry {
		f.now += 5000
		f.assetPrice("ETH", "3000")
	}
	f.now = e.Expiry
	f.assetPrice("ETH", "3000")
	s = f.q.Snapshot()
	if s.Stages[e.ID].Status != "survived" || s.Stages[h.ID].Status != "exploded" || s.Balance("alice").EconomicBalance != 170_000_000 {
		t.Fatal("independent market outcomes incorrect", s.Balance("alice"))
	}
	if s.Accounts["alice"].RunHead != "" || len(s.Accounts["alice"].StageHeads) != 0 {
		t.Fatal("resolved market locks were not released")
	}
	f.do(engine.Command{Kind: "paper_settle"})
	s = f.q.Snapshot()
	if s.LP != 930_000_000 || s.Custody != 170_000_000 || s.Epochs[0].OracleHash == s.Oracle.JournalHash {
		t.Fatal("multi-market settlement did not reconcile or commit all feeds")
	}
	replayed, err := engine.Open(context.Background(), f.policy, f.store)
	if err != nil || engine.Hash(replayed.Snapshot()) != engine.Hash(s) {
		t.Fatal("multi-market replay divergence", err)
	}
}

func TestParallelMarketAcceptanceCannotSpendOneBalanceTwice(t *testing.T) {
	f := multiFixture(t)
	btc := f.assetQuote("BTC", 50_000_000, 2)
	eth := f.assetQuote("ETH", 50_000_000, 2)
	hype := f.assetQuote("HYPE", 50_000_000, 2)
	f.enter(btc)
	f.enter(eth)
	rejectRisk(t, f, engine.Command{Kind: "enter", Actor: "alice", ID: hype.ID}, "insufficient funds")
	rejectRisk(t, f, engine.Command{Kind: "quote", Actor: "alice", Asset: "ETH", Amount: 1_000_000, Multiplier: 2}, "unfinished run")
}

func TestParallelMarketsShareTheAccountRiskBudget(t *testing.T) {
	f := multiFixture(t)
	f.do(engine.Command{Kind: "deposit", Actor: "alice", ID: "extra", Amount: 200_000_000})
	f.do(engine.Command{Kind: "ack_deposit", ID: "extra"})
	policy := f.q.Snapshot().Policy
	policy.Version += "-cap"
	policy.MaxAccountExposure = 100_000_000
	raw, _ := json.Marshal(policy)
	f.do(engine.Command{Kind: "policy_update", Raw: raw})
	btc := f.assetQuote("BTC", 50_000_000, 2)
	eth := f.assetQuote("ETH", 50_000_000, 2)
	hype := f.assetQuote("HYPE", 50_000_000, 2)
	f.enter(btc)
	f.enter(eth)
	rejectRisk(t, f, engine.Command{Kind: "enter", Actor: "alice", ID: hype.ID}, "account exposure limit")
}

func TestOracleFreshnessAndOutagesAreMarketSpecific(t *testing.T) {
	f := multiFixture(t)
	quote := f.assetQuote("ETH", 10_000_000, 2)
	f.assetPrice("BTC", "101000") // A BTC sequence change must not invalidate ETH.
	eth := f.enter(quote)
	btc := f.enter(f.assetQuote("BTC", 10_000_000, 2))
	for f.now+5000 < eth.Expiry {
		f.now += 5000
		f.assetPrice("ETH", "3000")
	}
	f.now = eth.Expiry
	f.assetPrice("ETH", "3000")
	s := f.q.Snapshot()
	if s.Stages[eth.ID].Status != "survived" || s.Stages[btc.ID].Status != "pending" {
		t.Fatal("BTC outage crossed market boundaries")
	}
	f.now += s.Policy.VoidDelayMS
	f.do(engine.Command{Kind: "tick"})
	if f.q.Snapshot().Stages[btc.ID].Status != "voided" {
		t.Fatal("stale BTC stage not refunded")
	}
}

func TestMarketPricingVersionsAndOpenMarketRemovalAreEnforced(t *testing.T) {
	f := multiFixture(t)
	f.enter(f.assetQuote("ETH", 1_000_000, 2))
	policy := f.q.Snapshot().Policy
	policy.Version += "-retuned"
	model := policy.Markets["ETH"]
	model.DNT.VolatilityPPM++
	policy.Markets["ETH"] = model
	raw, _ := json.Marshal(policy)
	rejectRisk(t, f, engine.Command{Kind: "policy_update", Raw: raw}, "new model version")
	policy = f.q.Snapshot().Policy
	policy.Version += "-removed"
	delete(policy.Markets, "ETH")
	raw, _ = json.Marshal(policy)
	rejectRisk(t, f, engine.Command{Kind: "policy_update", Raw: raw}, "cannot disable")
	rejectRisk(t, f, engine.Command{Kind: "quote", Actor: "alice", Asset: "SOL", Amount: 1_000_000, Multiplier: 2}, "market not enabled")
}
