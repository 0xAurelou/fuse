package engine

import (
	"strings"
	"testing"
)

func TestResearchExtraPostFeeFundingFailureIsAtomic(t *testing.T) {
	s := researchProjectionFixture(t)
	s.LP = 1_000_000_000
	s.account("alice").Unfunded = 100_000_000
	if err := s.Check(); err != nil {
		t.Fatal("invalid initial claim fixture", err)
	}
	before := Hash(s)
	// The declared balances themselves are valid. The real fee handler runs,
	// charges recovery and pauses; only the subsequent accepted-claim funding
	// invariant fails. None of those intermediate mutations may escape.
	got, err := ResearchSyncLP(s, s.LP, 950_000_000, 0)
	if err == nil || !strings.Contains(err.Error(), "unfunded accepted LP obligation") {
		t.Fatal("wrong rejection", err)
	}
	if Hash(got) != before || Hash(s) != before || s.Recovery.PnL != 0 || s.Recovery.Mode != "open" {
		t.Fatal("rejected projection leaked fee/recovery mutation")
	}
}

func TestResearchExtraNoRecoveryPositiveFeeMatchesCapitalProjection(t *testing.T) {
	s := researchProjectionFixture(t)
	s.Policy.Recovery = nil
	s.Recovery = nil
	before := Hash(s)
	expected := clone(s)
	expected.Local.LPFeeAccrued = 25_000_000
	got, err := ResearchSyncLP(s, s.LP, 25_000_000, 0)
	if err != nil || Hash(got) != Hash(expected) || Hash(s) != before {
		t.Fatal("no-recovery fee compatibility failed", err)
	}
}

func TestResearchExtraFeeCannotEraseProfitPeak(t *testing.T) {
	s := researchProjectionFixture(t)
	s.recordRisk(50_000_000, s.At)
	got, err := ResearchSyncLP(s, s.LP, 25_000_000, 0)
	if err != nil {
		t.Fatal(err)
	}
	if got.Recovery.PnL != 25_000_000 || got.Recovery.Peak != 50_000_000 || got.Recovery.Mode != "paused" {
		t.Fatal("fee failed to preserve profit peak and drawdown", got.Recovery)
	}
}
