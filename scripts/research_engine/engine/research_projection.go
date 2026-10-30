package engine

import "fmt"

// ResearchSyncLP is compiled only in a separately generated offline engine copy.
// It is not added to the production module, transaction API or capture binary.
// Cash/exits are explicit successful-operation projections, never confirmations.
// Fee accrual reuses the actual local-effect handler so recovery is charged once.
func ResearchSyncLP(before State, cash, fee, exit int64) (State, error) {
	if before.Policy.Mode != "paper" || before.Local == nil || before.Local.Deployment != "" {
		return before, fmt.Errorf("projection requires an unbound paper research state")
	}
	if cash < 0 || cash > Limit || fee < before.Local.LPFeeAccrued || exit < 0 || fee > cash || exit > cash-fee {
		return before, fmt.Errorf("invalid projected balances or decreasing accrued fee")
	}
	delta := fee - before.Local.LPFeeAccrued
	if delta > 0 && before.At <= 0 {
		return before, fmt.Errorf("fee accrual requires a prior sequenced time")
	}
	s := clone(before)
	s.LP, s.Local.LPExitReserved = cash, exit
	if delta > 0 {
		if err := s.localEffect(LocalEffect{Module: "LPVault", Event: "ReserveFeeAccrued", Amount: delta, Value: fmt.Sprint(fee)}); err != nil {
			return before, err
		}
	}
	// New fees can exhaust recovery budgets while accepted claims remain funded.
	// Do not retroactively run admission checks against already accepted stages.
	if err := s.Check(); err != nil {
		return before, err
	}
	return s, nil
}
