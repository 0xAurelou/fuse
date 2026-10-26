package localdev

import (
	"fmt"
	"math/rand"
	"strings"
	"time"

	"fuse/engine/internal/engine"
)

// Profiles are test scenarios, never fitted trading or fair-price models. Stakes
// and risk budgets are integer USDC units and independent of observed outcomes.
func traderProfiles(count int, seed int64, policy engine.Policy) ([]*simulatedTrader, error) {
	if count < 2 || count > MaxLocalTraders {
		return nil, fmt.Errorf("traders must be 2..%d", MaxLocalTraders)
	}
	r := rand.New(rand.NewSource(seed))
	widths := []int64{1, 2, 3, 4, 5, 8, 10, 15, 20, 35, 50, 75}
	result := make([]*simulatedTrader, 0, count)
	for i := 0; i < count; i++ {
		t := &simulatedTrader{Name: fmt.Sprintf("trader-%03d", i+1), Wallet: Alice + i, Account: strings.ToLower(Wallet(Alice + i).Hex()), MaxRuns: 1, Run: 1, Stages: []string{}, Status: "waiting"}
		switch i % 5 {
		case 0:
			t.Strategy = "early-cashout"
			t.Target = 1 + r.Intn(2)
		case 1:
			t.Strategy = "ladder"
			t.Target = 3 + r.Intn(4)
		case 2:
			t.Strategy = "marathon"
			t.Target = 7 + r.Intn(2)
		case 3:
			t.Strategy = "risk-aware"
			t.Target = 2 + r.Intn(5)
			t.CashoutDelayMS = int64(500 + r.Intn(2501))
		case 4:
			t.Strategy = "re-entry"
			t.Target = 1 + r.Intn(3)
			t.MaxRuns = 2 + r.Intn(2)
		}
		t.Width = widths[(i*7+r.Intn(len(widths)))%len(widths)]
		if policy.Model.BaseWidthPPM > 0 {
			t.WidthPPM = max(int64(1), policy.Model.BaseWidthPPM*[]int64{60, 75, 85, 90, 95, 100, 105, 110, 125, 150}[i%10]/100)
			t.Width = 0
		}
		// Cap the largest possible payout profit of a run to a seeded budget. This
		// makes target stage, width and stake independent while respecting account risk.
		profitBudget := int64(25+r.Intn(1476)) * 1_000_000
		// Larger populations share the original 100-wallet risk budget.
		profitBudget = profitBudget * 100 / int64(max(100, count))
		payoutMultiple := policy.PayoutTable[t.Target]
		if policy.Product == engine.SingleStage {
			t.Multiplier = []int64{2, 5, 10, 25, 50, 100}[i%6]
			t.Target = 1
			t.Width, t.WidthPPM = 0, policy.Model.MultiplierWidthsPPM[t.Multiplier]
			if policy.Model.DNT != nil {
				var pricingErr error
				t.WidthPPB, pricingErr = policy.Model.DNT.WidthPPB(t.Multiplier)
				if pricingErr != nil {
					return nil, pricingErr
				}
			}
			t.Strategy = []string{"low-multiplier", "balanced", "high-multiplier", "delayed-entry", "re-entry"}[i%5]
			payoutMultiple = t.Multiplier * engine.Scale
		}
		capStake, err := engine.MulDiv(profitBudget, engine.Scale, payoutMultiple-engine.Scale)
		if err != nil {
			return nil, err
		}
		t.Stake = max(policy.MinStake, min(capStake, int64(100+r.Intn(99901))*10_000/int64(t.MaxRuns), policy.MaxStake))
		t.Deposit = t.Stake * int64(t.MaxRuns)
		idle := min(int64(r.Intn(151))*1_000_000, 1_000_000_000-t.Deposit)
		if idle > 0 {
			t.Deposit += idle
		}
		t.EntryDelayMS = int64((i%10)*1500 + r.Intn(500)) // ten waves with deterministic jitter
		t.ReentryDelayMS = int64(500 + r.Intn(2501))
		result = append(result, t)
	}
	return result, nil
}
func (t *simulatedTrader) scheduleEntry(at time.Time) {
	t.readyAt = at
	// A queued client has not requested a quote yet. Start its admissibility
	// retry timeout at its first attempt, rather than expiring it in the queue.
	t.entryDeadline = time.Time{}
}
