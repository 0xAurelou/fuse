package engine

import "fmt"

const riskDayMS int64 = 86_400_000

// RecoveryPolicy uses fixed USDC atomic-unit budgets, deliberately independent
// of deposits, exits and UTC day boundaries. These are research rules requiring
// explicit approval; they do not silently inherit the simulator's NAV policy.
type RecoveryPolicy struct {
	Version        string `json:"version"`
	DailyLoss      int64  `json:"daily_loss"`
	RollingLoss    int64  `json:"rolling_loss"`
	RollingMS      int64  `json:"rolling_ms"`
	PauseDrawdown  int64  `json:"pause_drawdown"`
	HardDrawdown   int64  `json:"hard_drawdown"`
	ResumeDrawdown int64  `json:"resume_drawdown"`
	CooldownMS     int64  `json:"cooldown_ms"`
	ProbeLoss      int64  `json:"probe_loss"`
}

func (p RecoveryPolicy) Validate() error {
	if p.Version == "" || p.RollingMS < riskDayMS || p.RollingMS > 90*riskDayMS || p.CooldownMS <= 0 || p.CooldownMS > 90*riskDayMS {
		return fmt.Errorf("invalid recovery version or timing")
	}
	for _, v := range []int64{p.DailyLoss, p.RollingLoss, p.PauseDrawdown, p.HardDrawdown, p.ResumeDrawdown, p.ProbeLoss} {
		if v < 0 || v > Limit {
			return fmt.Errorf("invalid recovery amount")
		}
	}
	if p.DailyLoss == 0 || p.RollingLoss < p.DailyLoss || p.ResumeDrawdown >= p.PauseDrawdown || p.PauseDrawdown > p.HardDrawdown || p.ProbeLoss == 0 || p.ProbeLoss > p.DailyLoss {
		return fmt.Errorf("invalid recovery budget ordering")
	}
	return nil
}

type RiskLoss struct {
	At     int64 `json:"at"`
	Amount int64 `json:"amount"`
}
type RecoveryState struct {
	Mode     string     `json:"mode"`
	ReopenAt int64      `json:"reopen_at"`
	PnL      int64      `json:"pnl"`
	Peak     int64      `json:"peak"`
	Losses   []RiskLoss `json:"losses"`
}

// PendingRisk excludes previously realized ladder gains: each open stage can
// lose its incremental payout minus stake. Prior gains already consumed budget.
func (s State) PendingRisk() (n int64) {
	for _, p := range s.Stages {
		if p.Status == "active" || p.Status == "pending" {
			n += p.Terms.Payout - p.Terms.Stake
		}
	}
	return
}
func (s *State) advanceRecovery(at int64) {
	p, r := s.Policy.Recovery, s.Recovery
	if p == nil || r == nil {
		return
	}
	i := 0
	for i < len(r.Losses) && r.Losses[i].At <= at-p.RollingMS {
		i++
	}
	r.Losses = append([]RiskLoss{}, r.Losses[i:]...)
	drawdown := r.Peak - r.PnL
	if r.Mode == "open" && drawdown >= p.PauseDrawdown {
		r.Mode = "paused"
		r.ReopenAt = at + p.CooldownMS
	} else if r.Mode != "open" && at >= r.ReopenAt {
		if drawdown <= p.ResumeDrawdown {
			r.Mode = "open"
		} else if r.Mode == "paused" {
			r.Mode = "probe"
		}
	}
}
func (s *State) recordRisk(pnl, at int64) {
	r := s.Recovery
	if r == nil {
		return
	}
	r.PnL += pnl
	if r.PnL > r.Peak {
		r.Peak = r.PnL
	}
	// Only the difference drives risk. Shift the common origin after large
	// profits so cumulative turnover cannot exhaust the balance safety envelope.
	if r.Peak > Limit/2 {
		r.PnL -= r.Peak
		r.Peak = 0
	}
	if pnl < 0 {
		r.Losses = append(r.Losses, RiskLoss{at, -pnl})
		if r.Mode == "probe" {
			r.Mode = "paused"
			r.ReopenAt = at + s.Policy.Recovery.CooldownMS
		}
	}
	s.advanceRecovery(at)
}

// CheckRecovery independently recomputes all open incremental exposure from
// accepted terms. It gates admission only, never funding or paying old claims.
func (s State) CheckRecovery(extra int64) error {
	p, r := s.Policy.Recovery, s.Recovery
	if p == nil {
		if r != nil {
			return reject("orphan recovery state")
		}
		return nil
	}
	if r == nil {
		return reject("missing recovery state")
	}
	if r.Mode == "paused" {
		return reject("recovery cooldown")
	}
	var day, rolling int64
	for _, loss := range r.Losses {
		if loss.At > s.At-p.RollingMS {
			rolling += loss.Amount
		}
		if loss.At > s.At-riskDayMS {
			day += loss.Amount
		}
	}
	reserved := s.PendingRisk() + extra
	if extra < 0 || reserved < 0 || reserved > p.DailyLoss-day {
		return reject("rolling 24h loss budget")
	}
	if reserved > p.RollingLoss-rolling {
		return reject("rolling multi-day loss budget")
	}
	if reserved > p.HardDrawdown-(r.Peak-r.PnL) {
		return reject("hard drawdown budget")
	}
	if r.Mode == "probe" && reserved > p.ProbeLoss-day {
		return reject("recovery probe budget")
	}
	return nil
}
func (s State) checkRecoveryState() error {
	p, r := s.Policy.Recovery, s.Recovery
	if p == nil && r == nil {
		return nil
	}
	if p == nil || r == nil || (r.Mode != "open" && r.Mode != "paused" && r.Mode != "probe") || r.Peak < 0 || r.Peak > Limit || r.Peak < r.PnL {
		return fmt.Errorf("invalid recovery state")
	}
	var last int64
	for _, loss := range r.Losses {
		if loss.At < last || loss.At > s.At || loss.Amount <= 0 || loss.Amount > Limit {
			return fmt.Errorf("invalid recovery loss history")
		}
		last = loss.At
	}
	return nil
}
