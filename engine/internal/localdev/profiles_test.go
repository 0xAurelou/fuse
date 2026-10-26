package localdev

import (
	"encoding/json"
	"os"
	"testing"
	"time"

	"fuse/engine/internal/engine"
)

func TestHundredProfilesStayFundableAndDiverse(t *testing.T) {
	raw, err := os.ReadFile("../../testdata/legacy-ladder-policy.json")
	if err != nil {
		t.Fatal(err)
	}
	var p engine.Policy
	if err = json.Unmarshal(raw, &p); err != nil {
		t.Fatal(err)
	}
	profiles, err := traderProfiles(100, 20261025, p)
	if err != nil {
		t.Fatal(err)
	}
	accounts, stakes, widths, targets, strategies := map[string]bool{}, map[int64]bool{}, map[int64]bool{}, map[int]bool{}, map[string]bool{}
	worstProfit := int64(0)
	for _, profile := range profiles {
		if accounts[profile.Account] || profile.Account == "0x0000000000000000000000000000000000000000" {
			t.Fatal("wallet collision")
		}
		accounts[profile.Account] = true
		if profile.Stake < p.MinStake || profile.Stake > p.MaxStake || profile.Deposit < profile.Stake*int64(profile.MaxRuns) || profile.Deposit > 1_000_000_000 {
			t.Fatalf("unfundable profile %+v", profile)
		}
		payout, err := engine.MulDiv(profile.Stake, p.PayoutTable[profile.Target], engine.Scale)
		if err != nil {
			t.Fatal(err)
		}
		profit := (payout - profile.Stake) * int64(profile.MaxRuns)
		if profit > p.MaxAccountExposure {
			t.Fatal("scenario exceeds account risk budget")
		}
		worstProfit += profit
		stakes[profile.Stake] = true
		widths[profile.Width] = true
		targets[profile.Target] = true
		strategies[profile.Strategy] = true
	}
	if worstProfit+p.LPBuffer > 250_000_000_000 {
		t.Fatal("all-win scenario could exhaust the initial LP", worstProfit)
	}
	if len(stakes) < 75 || len(widths) != 12 || len(targets) != 8 || len(strategies) != 5 {
		t.Fatal("insufficient profile diversity", len(stakes), len(widths), len(targets), len(strategies))
	}
	other, err := traderProfiles(100, 20261025, p)
	if err != nil || engine.Hash(profiles) != engine.Hash(other) {
		t.Fatal("seed not reproducible", err)
	}
	changed, err := traderProfiles(100, 20261026, p)
	if err != nil || engine.Hash(profiles) == engine.Hash(changed) {
		t.Fatal("seed does not change scenarios", err)
	}
	if _, err = DevKey(Alice + 99); err != nil {
		t.Fatal(err)
	}
	if _, err = DevKey(Alice + MaxLocalTraders); err == nil {
		t.Fatal("wallet range unbounded")
	}
	t.Logf("100 wallets, %d stake sizes, %d widths, %d targets, %d strategies; worst-case total profit %.6f USDC", len(stakes), len(widths), len(targets), len(strategies), float64(worstProfit)/1e6)
}

func TestThreeCohortsPreserveRiskAndFrozenControl(t *testing.T) {
	raw, err := os.ReadFile("../../testdata/legacy-ladder-policy.json")
	if err != nil {
		t.Fatal(err)
	}
	var p engine.Policy
	if err = json.Unmarshal(raw, &p); err != nil {
		t.Fatal(err)
	}
	p.Model.BaseWidthPPM = 117
	o := SimulationOptions{CohortSize: 100, CohortInterval: 180 * time.Second, CaptureDuration: 600 * time.Second, ControlEvery: 2}
	profiles, err := o.profiles(300, 20261026, p)
	if err != nil {
		t.Fatal(err)
	}
	var liability int64
	controls, cohorts, accounts := 0, map[int]int{}, map[string]bool{}
	strategies := map[string]bool{}
	for i, trader := range profiles {
		if accounts[trader.Account] {
			t.Fatal("duplicate wallet")
		}
		accounts[trader.Account] = true
		cohorts[trader.Cohort]++
		if trader.EntryDelayMS < int64(i/100)*180000 || trader.EntryDelayMS >= int64(i/100)*180000+15000 {
			t.Fatal("cohort entry outside schedule")
		}
		if trader.PricingGroup == "frozen-width-control" {
			controls++
			strategies[trader.Strategy] = true
			if trader.WidthPPM != 117 || trader.Width != 0 {
				t.Fatal("control width drift")
			}
		}
		payout, err := engine.MulDiv(trader.Stake, p.PayoutTable[trader.Target], engine.Scale)
		if err != nil {
			t.Fatal(err)
		}
		liability += (payout - trader.Stake) * int64(trader.MaxRuns)
		if trader.Deposit > 1000000000 || trader.Deposit < trader.Stake*int64(trader.MaxRuns) {
			t.Fatal("unfundable wallet")
		}
	}
	if controls != 150 || len(strategies) != 5 || len(cohorts) != 3 || cohorts[3] != 100 || liability+p.LPBuffer > p.MaxExposure {
		t.Fatal("population/risk mismatch", controls, cohorts, liability)
	}
	if _, err = DevKey(Alice + 299); err != nil {
		t.Fatal(err)
	}
	o.ControlEvery = 1
	if _, err = o.profiles(300, 1, p); err == nil {
		t.Fatal("invalid control frequency accepted")
	}
	t.Logf("300 wallets; 150 exact-width controls; all-win liability %.6f USDC", float64(liability)/1e6)
}

func TestSingleStageProfilesChooseMultipliersAndStayFullyFundable(t *testing.T) {
	raw, err := os.ReadFile("../../config/local.json")
	if err != nil {
		t.Fatal(err)
	}
	var p engine.Policy
	if err := json.Unmarshal(raw, &p); err != nil {
		t.Fatal(err)
	}
	profiles, err := traderProfiles(100, 20261026, p)
	if err != nil {
		t.Fatal(err)
	}
	multipliers := map[int64]bool{}
	liability := int64(0)
	for _, trader := range profiles {
		if trader.Target != 1 || trader.Multiplier < 2 || trader.Multiplier > 100 || trader.WidthPPB == 0 {
			t.Fatal(trader)
		}
		multipliers[trader.Multiplier] = true
		profit := trader.Stake * (trader.Multiplier - 1) * int64(trader.MaxRuns)
		if profit > p.MaxAccountExposure || trader.Deposit < trader.Stake*int64(trader.MaxRuns) {
			t.Fatal("unfundable single-stage profile", trader)
		}
		liability += profit
	}
	if len(multipliers) != 6 || liability+p.LPBuffer > 250_000_000_000 {
		t.Fatal("unsafe or incomplete multiplier scenarios", multipliers, liability)
	}
}
