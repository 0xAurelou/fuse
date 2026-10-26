package engine

import "testing"

func TestRecoveryLPFlowsAndFeeFundingCannotResetLimits(t *testing.T) {
	s := lpState(t)
	s.Policy.Recovery = &RecoveryPolicy{Version: "test", DailyLoss: 100_000_000, RollingLoss: 200_000_000, RollingMS: 7 * riskDayMS, PauseDrawdown: 50_000_000, HardDrawdown: 100_000_000, ResumeDrawdown: 10_000_000, CooldownMS: 1000, ProbeLoss: 1_000_000}
	s.Recovery = &RecoveryState{Mode: "open", Losses: []RiskLoss{}}
	s.At = 1000
	s.recordRisk(-20_000_000, s.At)
	for _, e := range []LocalEffect{
		{Module: "LPVault", Event: "LPExitReserved", Amount: 200_000_000},
		{Module: "LPVault", Event: "LPExitPaid", Amount: 200_000_000},
	} {
		if err := s.localEffect(e); err != nil {
			t.Fatal(err)
		}
	}
	if s.Recovery.PnL != -20_000_000 || len(s.Recovery.Losses) != 1 {
		t.Fatal("LP exit reset economic loss")
	}
	if err := s.localEffect(LocalEffect{Module: "LPVault", Event: "ReserveFeeAccrued", Amount: 100_000_000, Value: "100000000"}); err != nil {
		t.Fatal(err)
	}
	afterFee := Hash(s.Recovery)
	if err := s.localEffect(LocalEffect{Module: "LPVault", Event: "ReserveFunded", Amount: 100_000_000, Value: "285714286"}); err != nil {
		t.Fatal(err)
	}
	if Hash(s.Recovery) != afterFee || s.Recovery.PnL != -120_000_000 || len(s.Recovery.Losses) != 2 {
		t.Fatal("fee funding erased or double charged economic loss")
	}
	if s.Recovery.Mode != "paused" {
		t.Fatal("fee exhaustion did not pause")
	}
	// Accepted obligations are checked for funding, not retroactively rejected
	// because an external fee consumed a prospective budget.
	if err := s.Check(); err != nil {
		t.Fatal(err)
	}
}
func TestRecoveryRollingBoundaryAndHardFloor(t *testing.T) {
	s := lpState(t)
	s.Policy.Recovery = &RecoveryPolicy{Version: "test", DailyLoss: 20, RollingLoss: 40, RollingMS: 7 * riskDayMS, PauseDrawdown: 20, HardDrawdown: 40, ResumeDrawdown: 5, CooldownMS: 1000, ProbeLoss: 2}
	s.At = 1000
	s.Recovery = &RecoveryState{Mode: "open", PnL: -19, Peak: 0, Losses: []RiskLoss{{At: 1000, Amount: 19}}}
	if err := s.CheckRecovery(2); err == nil {
		t.Fatal("gross loss budget ignored")
	}
	s.At += riskDayMS
	s.advanceRecovery(s.At)
	if err := s.CheckRecovery(20); err != nil {
		t.Fatal("exactly expired 24h loss retained", err)
	}
	s.Recovery.Losses = nil
	s.Recovery.PnL = -39
	if err := s.CheckRecovery(2); err == nil {
		t.Fatal("hard floor ignored")
	}
	if err := s.CheckRecovery(1); err != nil {
		t.Fatal("exact floor rejected", err)
	}
}

func TestRecoveryLargeProfitDoesNotExhaustAccountingEnvelope(t *testing.T) {
	s := lpState(t)
	s.Policy.Recovery = &RecoveryPolicy{RollingMS: 7 * riskDayMS, PauseDrawdown: 1000, HardDrawdown: 2000, CooldownMS: 1000}
	s.Recovery = &RecoveryState{Mode: "open", PnL: Limit / 2, Peak: Limit / 2, Losses: []RiskLoss{{At: 1000, Amount: 5}}}
	s.At = 1000
	s.recordRisk(100, 1000)
	if s.Recovery.Peak-s.Recovery.PnL != 0 || len(s.Recovery.Losses) != 1 {
		t.Fatal("origin shift changed risk")
	}
	s.recordRisk(-10, 1000)
	if s.Recovery.Peak-s.Recovery.PnL != 10 || len(s.Recovery.Losses) != 2 {
		t.Fatal("origin shift lost drawdown or gross losses")
	}
}
