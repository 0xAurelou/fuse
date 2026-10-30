package engine

import "testing"

func TestCapitalReservedFeesExitsBackingDepositsAndUnsettledLossesCannotUnderwrite(t *testing.T) {
	s := lpState(t)
	s.Policy.Capital = &CapitalLimits{Rule: FundedCapital, MaxBetLiability: 1000_000_000,
		MaxMarketExposure: map[string]int64{"BTC": 1000_000_000, "ETH": 1000_000_000, "HYPE": 1000_000_000}}
	s.Capital = &CapitalState{UnfundedByMarket: map[string]int64{}}
	s.Local.LPFeeAccrued, s.Local.LPExitReserved = 100_000_000, 200_000_000
	s.Reserve = 125_000_000_000 // Synthetic state only; no external funding claim.
	s.Deposits["pending"] = &Deposit{ID: "pending", Account: "alice", Amount: 250_000_000_000, Status: "pending"}
	s.LossClearing = 20_000_000_000
	s.Custody = 270_001_000_000
	s.account("alice")
	s.Stages["reserved"] = &Stage{ID: "reserved", Status: "active", Funded: 1_000_000,
		Terms: Quote{Asset: "BTC", Account: "alice", Product: SingleStage, Stake: 1_000_000, Payout: 2_000_000}}
	s.Policy.LPBuffer = 700_000_000
	if err := s.Check(); err != nil {
		t.Fatal(err)
	}
	if s.LPAvailable() != 700_000_000 || s.capacity() == nil {
		t.Fatal("segregated backing, pending deposits, losses or reserved fees/exits financed new risk")
	}
	s.Policy.LPBuffer = 699_000_000
	if err := s.capacity(); err != nil {
		t.Fatal("exact physical headroom was rejected", err)
	}
}

func TestCapitalFundingWatermarkMatchesPlanAcrossLaterConfirmationSequence(t *testing.T) {
	s := lpState(t)
	s.Policy.Capital = &CapitalLimits{Rule: FundedCapital, MaxBetLiability: 1000_000_000,
		MaxMarketExposure: map[string]int64{"BTC": 1000_000_000, "ETH": 1000_000_000, "HYPE": 1000_000_000}}
	s.Sequence = 10
	s.Capital = &CapitalState{UnfundedByMarket: map[string]int64{"BTC": 1_000_000}}
	s.Custody = 1_000_000
	s.Accounts["alice"] = &Account{Available: 1_000_000, Unfunded: 1_000_000}
	s.Stages["winner"] = &Stage{ID: "winner", AcceptedSequence: 2, ResolvedSequence: 4,
		Status: "survived", Funded: 1_000_000,
		Terms: Quote{Asset: "BTC", Account: "alice", Product: SingleStage, Stake: 1_000_000, Payout: 2_000_000}}
	if err := s.Check(); err != nil {
		t.Fatal(err)
	}
	plan, err := PlanLocalSettlement(s)
	if err != nil {
		t.Fatal(err)
	}
	preview := clone(s)
	if err := preview.fundSettlement(); err != nil || plan.Epoch.Root != preview.Digest() {
		t.Fatal("planned financial state does not include the exact capital projection", err)
	}
	s.Sequence = 20 // Confirmation can follow other local journal observations.
	if err := s.fundSettlement(); err != nil {
		t.Fatal(err)
	}
	if s.Capital.FundedThroughSequence != 4 || Hash(s.Capital) != Hash(preview.Capital) {
		t.Fatal("confirmation timing changed the funded outcome set")
	}
}
