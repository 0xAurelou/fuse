package engine_test

import (
	"context"
	"testing"

	"fuse/engine/internal/engine"
)

func TestSharedSettlementExportUsesExpiryRatherThanLateProcessingTime(t *testing.T) {
	f := multiFixture(t)
	p := f.enter(f.assetQuote("BTC", 1_000_000, 2))
	for f.now+5000 < p.Expiry {
		f.now += 5000
		f.price("100000")
	}
	f.now = p.Expiry + 123
	f.do(engine.Command{Kind: "tick"})
	s := f.q.Snapshot()
	before := s.Digest()
	out, err := s.SettlementOutcome(p.ID)
	if err != nil || out.Outcome != 2 || out.CanonicalMS != p.Expiry || out.ObservedMS != f.now ||
		out.Payout != 2_000_000 || out.LPPnL != -1_000_000 || out.JournalHash != s.JournalHash ||
		out.StageCommitment == "" || out.OracleCommitment != s.OracleCommitment() {
		t.Fatalf("shared survival export: %+v, %v", out, err)
	}
	if s.Digest() != before {
		t.Fatal("read-only export changed replay state")
	}
	f.do(engine.Command{Kind: "paper_settle"})
	if f.q.Snapshot().LP != 1000_000_000+out.LPPnL {
		t.Fatal("paper settlement differs from exported outcome")
	}
	replayed, err := engine.Open(context.Background(), f.policy, f.store)
	if err != nil || replayed.Snapshot().Digest() != f.q.Snapshot().Digest() {
		t.Fatal("replay changed", err)
	}
}

func TestSharedSettlementExportRetainsSubsecondBarrierHitsAcrossMarkets(t *testing.T) {
	for _, asset := range []string{"BTC", "ETH", "HYPE"} {
		t.Run(asset, func(t *testing.T) {
			f := multiFixture(t)
			p := f.enter(f.assetQuote(asset, 1_000_000, 2))
			f.now += 123
			f.assetPrice(asset, "1")
			out, err := f.q.Snapshot().SettlementOutcome(p.ID)
			if err != nil || out.Outcome != 3 || out.CanonicalMS != f.now || out.ObservedMS != f.now ||
				out.LPPnL != 1_000_000 || out.Payout != 0 || out.Asset != asset {
				t.Fatalf("shared barrier export: %+v, %v", out, err)
			}
		})
	}
}

func TestSharedSettlementExportRetainsFinalVoidDeterminationAfterOutage(t *testing.T) {
	f := multiFixture(t)
	p := f.enter(f.assetQuote("BTC", 1_000_000, 2))
	f.now = p.Expiry + f.policy.VoidDelayMS + 123
	f.do(engine.Command{Kind: "tick"})
	out, err := f.q.Snapshot().SettlementOutcome(p.ID)
	if err != nil || out.Outcome != 4 || out.CanonicalMS != f.now || out.Payout != p.Terms.Stake || out.LPPnL != 0 {
		t.Fatalf("shared void export: %+v, %v", out, err)
	}
}

func TestSharedSettlementExportRejectsUnresolvedUnsupportedAndCorruptOutcomes(t *testing.T) {
	f := multiFixture(t)
	p := f.enter(f.assetQuote("BTC", 1_000_000, 2))
	s := f.q.Snapshot()
	for _, id := range []string{p.ID, "unknown"} {
		if _, err := s.SettlementOutcome(id); err == nil {
			t.Fatal("exported unresolved stage")
		}
	}
	for _, mutate := range []func(*engine.Stage){
		func(p *engine.Stage) { p.Status = "survived"; p.Resolved = p.Expiry - 1 },
		func(p *engine.Stage) { p.Status = "exploded"; p.Resolved = p.Expiry },
		func(p *engine.Stage) { p.Status = "voided"; p.Resolved = p.Expiry - 1 },
		func(p *engine.Stage) { p.Status = "voided"; p.Resolved = p.Expiry; p.Funded-- },
		func(p *engine.Stage) { p.Status = "voided"; p.Resolved = p.Expiry; p.Terms.Product = "ladder" },
	} {
		copyState := f.q.Snapshot()
		mutate(copyState.Stages[p.ID])
		if _, err := copyState.SettlementOutcome(p.ID); err == nil {
			t.Fatal("exported invalid outcome")
		}
	}
}
