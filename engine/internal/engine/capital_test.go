package engine_test

import (
	"context"
	"encoding/json"
	"fmt"
	"sort"
	"strings"
	"sync"
	"testing"

	"fuse/engine/internal/engine"
)

const usd int64 = 1_000_000

func capitalPolicy(f *fixture) engine.Policy {
	p := f.q.Snapshot().Policy
	p.Version += "-capital"
	p.MaxExposure, p.MaxAccountExposure = 200*usd, 200*usd
	p.Capital = &engine.CapitalLimits{Rule: engine.FundedCapital, MaxBetLiability: 100 * usd,
		MaxMarketExposure: map[string]int64{"BTC": 50 * usd, "ETH": 70 * usd, "HYPE": 90 * usd}}
	return p
}

func (f *fixture) updateCapital(p engine.Policy) {
	f.t.Helper()
	raw, err := json.Marshal(p)
	if err != nil {
		f.t.Fatal(err)
	}
	f.do(engine.Command{Kind: "policy_update", Raw: raw})
}

func capitalFixture(t *testing.T) *fixture {
	f := multiFixture(t)
	f.updateCapital(capitalPolicy(f))
	return f
}

func assertMarketCapital(t *testing.T, s engine.State, want map[string]int64) {
	t.Helper()
	var sum int64
	for _, asset := range s.Policy.Assets() {
		n, err := s.MarketExposure(asset)
		if err != nil || n != want[asset] {
			t.Fatalf("%s exposure: %d, want %d (%v)", asset, n, want[asset], err)
		}
		sum += n
	}
	global, _, _ := s.Exposure()
	if sum != global || s.Check() != nil {
		t.Fatal("market/global capital does not reconcile", sum, global, s.Check())
	}
}

func (f *fixture) surviveMarkets(expiry int64) {
	f.t.Helper()
	for f.now < expiry {
		f.now += 5000
		if f.now > expiry {
			f.now = expiry
		}
		f.price("100000")
		f.assetPrice("ETH", "3000")
		f.assetPrice("HYPE", "40")
	}
	f.do(engine.Command{Kind: "tick"})
}

func TestCapitalEveryPresetAndMarketReservesWinUntilActualFunding(t *testing.T) {
	for _, asset := range []string{"BTC", "ETH", "HYPE"} {
		for _, multiplier := range engine.PayoutOptions() {
			t.Run(fmt.Sprintf("%s-%d", asset, multiplier), func(t *testing.T) {
				f := multiFixture(t)
				f.do(engine.Command{Kind: "lp_fund", Amount: 249_000 * usd})
				p := f.q.Snapshot().Policy
				liability := (multiplier - 1) * usd
				p.Version += "-capital"
				p.Capital = &engine.CapitalLimits{Rule: engine.FundedCapital, MaxBetLiability: liability,
					MaxMarketExposure: map[string]int64{"BTC": 100_000 * usd, "ETH": 100_000 * usd, "HYPE": 100_000 * usd}}
				f.updateCapital(p)
				rejectRisk(t, f, engine.Command{Kind: "quote", Actor: "alice", Asset: asset, Amount: usd + 1, Multiplier: multiplier}, "per-bet liability")
				stage := f.enter(f.assetQuote(asset, usd, multiplier))
				assertMarketCapital(t, f.q.Snapshot(), map[string]int64{asset: liability})
				f.surviveMarkets(stage.Expiry)
				s := f.q.Snapshot()
				if s.Stages[stage.ID].Status != "survived" || s.Debt() != liability {
					t.Fatal("maximum win was not recognized before withdrawal")
				}
				assertMarketCapital(t, s, map[string]int64{asset: liability})
				f.do(engine.Command{Kind: "paper_settle"})
				assertMarketCapital(t, f.q.Snapshot(), nil)
				if f.q.Snapshot().LP != 250_000*usd-liability {
					t.Fatal("LP funding did not pay the exact liability")
				}
			})
		}
	}
}

func TestCapitalSimultaneousWinsFillGlobalLimitThenPayDuringPause(t *testing.T) {
	f := multiFixture(t)
	f.do(engine.Command{Kind: "lp_fund", Amount: 249_000 * usd})
	p := f.q.Snapshot().Policy
	p.Version += "-capital-stress"
	p.LPBuffer = 25_000 * usd
	p.MaxExposure, p.MaxAccountExposure = 200_000*usd, 200_000*usd
	p.Capital = &engine.CapitalLimits{Rule: engine.FundedCapital, MaxBetLiability: 25_000 * usd,
		MaxMarketExposure: map[string]int64{"BTC": 100_000 * usd, "ETH": 100_000 * usd, "HYPE": 100_000 * usd}}
	f.updateCapital(p)
	expected := map[string]int64{}
	accepted, perBetRejected, globalRejected := 0, 0, 0
	for round := 0; round < 4; round++ {
		expiry := f.now + 30_000
		for _, asset := range p.Assets() {
			for _, multiplier := range engine.PayoutOptions() {
				actor := fmt.Sprintf("stress-%d-%s-%d", round, asset, multiplier)
				f.do(engine.Command{Kind: "deposit", Actor: actor, ID: actor, Amount: 1000 * usd})
				f.do(engine.Command{Kind: "ack_deposit", ID: actor})
				before := engine.Hash(f.q.Snapshot())
				e, err := f.q.Execute(context.Background(), f.cmd(engine.Command{Kind: "quote", Actor: actor, Asset: asset, Amount: 50 * usd, Multiplier: multiplier}))
				if err != nil {
					if engine.Hash(f.q.Snapshot()) != before {
						t.Fatal("rejected stress quote mutated state")
					}
					if strings.Contains(err.Error(), "per-bet liability") {
						perBetRejected++
					} else if strings.Contains(err.Error(), "LP capacity") {
						globalRejected++
					} else {
						t.Fatal(err)
					}
					continue
				}
				var quote engine.Quote
				if err := json.Unmarshal(e.Result, &quote); err != nil {
					t.Fatal(err)
				}
				f.do(engine.Command{Kind: "enter", Actor: actor, ID: quote.ID})
				expected[asset] += (multiplier - 1) * 50 * usd
				accepted++
				assertMarketCapital(t, f.q.Snapshot(), expected)
			}
		}
		// Keep all three paths unchanged, forcing every accepted maximum payout.
		// Earlier winning debt is deliberately left unsettled across later batches.
		f.surviveMarkets(expiry)
		assertMarketCapital(t, f.q.Snapshot(), expected)
	}
	if accepted != 73 || perBetRejected != 24 || globalRejected != 11 {
		t.Fatal("unexpected stress admissions", accepted, perBetRejected, globalRejected)
	}
	s := f.q.Snapshot()
	if s.Debt() != 199_800*usd || s.LP != 250_000*usd {
		t.Fatal("unpaid wins disappeared or were counted as settled")
	}
	actor := "fill-exact-global-cap"
	f.do(engine.Command{Kind: "deposit", Actor: actor, ID: actor, Amount: 1000 * usd})
	f.do(engine.Command{Kind: "ack_deposit", ID: actor})
	e := f.do(engine.Command{Kind: "quote", Actor: actor, Amount: 200 * usd, Multiplier: 2})
	var quote engine.Quote
	json.Unmarshal(e.Result, &quote)
	f.do(engine.Command{Kind: "enter", Actor: actor, ID: quote.ID})
	expected["BTC"] += 200 * usd
	assertMarketCapital(t, f.q.Snapshot(), expected)
	f.do(engine.Command{Kind: "deposit", Actor: "over-cap", ID: "over-cap", Amount: 10 * usd})
	f.do(engine.Command{Kind: "ack_deposit", ID: "over-cap"})
	rejectRisk(t, f, engine.Command{Kind: "quote", Actor: "over-cap", Amount: usd, Multiplier: 2}, "LP capacity")
	f.surviveMarkets(f.now + 30_000)
	f.do(engine.Command{Kind: "pause"})
	f.do(engine.Command{Kind: "paper_settle"})
	assertMarketCapital(t, f.q.Snapshot(), nil)
	if f.q.Snapshot().LP != 50_000*usd || !f.q.Snapshot().Paused {
		t.Fatal("maximum wins did not settle through pause")
	}
	// Request every customer's complete funded balance, including unused stakes
	// of rejected bettors. A single checkpoint funds all pending withdrawals.
	var withdrawals []string
	var customerCash int64
	balances := f.q.Snapshot().Accounts
	accounts := make([]string, 0, len(balances))
	for account := range balances {
		accounts = append(accounts, account)
	}
	sort.Strings(accounts)
	for _, account := range accounts {
		balance := balances[account]
		if balance.Available == 0 {
			continue
		}
		customerCash += balance.Available
		e := f.do(engine.Command{Kind: "withdraw", Actor: account, Amount: balance.Available})
		var withdrawal engine.Withdrawal
		json.Unmarshal(e.Result, &withdrawal)
		withdrawals = append(withdrawals, withdrawal.ID)
	}
	f.do(engine.Command{Kind: "paper_settle"})
	for _, id := range withdrawals {
		f.do(engine.Command{Kind: "paper_pay", ID: id})
	}
	s = f.q.Snapshot()
	if s.Custody != 0 || s.Debt() != 0 || s.LP != 50_000*usd || s.Reserve != 0 {
		t.Fatal("post-payment assets did not reconcile")
	}
	replayed, err := engine.Open(context.Background(), f.policy, f.store)
	if err != nil || engine.Hash(replayed.Snapshot()) != engine.Hash(s) {
		t.Fatal("full stress/payment history does not replay", err)
	}
	t.Logf("synthetic native stress: 108 grid attempts, 74 accepted including exact-cap fill, 24 per-bet and 11 grid global rejections; maximum winning debt=$200000; terminal LP=$50000; customer cash paid=%d USDC units; no market calibration", customerCash)
}

func TestCapitalConcurrentQuotesCannotOverbookOneMarketAndReplay(t *testing.T) {
	f := capitalFixture(t)
	p := f.q.Snapshot().Policy
	p.Version += "-race"
	p.Capital.MaxMarketExposure["BTC"] = 40 * usd
	f.updateCapital(p)
	commands := make([]engine.Command, 3)
	for i := range commands {
		actor := fmt.Sprintf("race-%d", i)
		f.do(engine.Command{Kind: "deposit", Actor: actor, ID: actor, Amount: 100 * usd})
		f.do(engine.Command{Kind: "ack_deposit", ID: actor})
		e := f.do(engine.Command{Kind: "quote", Actor: actor, Asset: "BTC", Amount: 20 * usd, Multiplier: 2})
		var quote engine.Quote
		if err := json.Unmarshal(e.Result, &quote); err != nil {
			t.Fatal(err)
		}
		commands[i] = f.cmd(engine.Command{Kind: "enter", Actor: actor, ID: quote.ID})
	}
	var wg sync.WaitGroup
	errors := make(chan error, len(commands))
	for _, command := range commands {
		wg.Add(1)
		go func(c engine.Command) {
			defer wg.Done()
			_, err := f.q.Execute(context.Background(), c)
			errors <- err
		}(command)
	}
	wg.Wait()
	close(errors)
	accepted, rejected := 0, 0
	for err := range errors {
		if err == nil {
			accepted++
		} else if strings.Contains(err.Error(), "market exposure limit") {
			rejected++
		} else {
			t.Fatal(err)
		}
	}
	if accepted != 2 || rejected != 1 {
		t.Fatal("market cap overbooked", accepted, rejected)
	}
	assertMarketCapital(t, f.q.Snapshot(), map[string]int64{"BTC": 40 * usd})
	replayed, err := engine.Open(context.Background(), f.policy, f.store)
	if err != nil || engine.Hash(replayed.Snapshot()) != engine.Hash(f.q.Snapshot()) {
		t.Fatal("capital history does not replay", err)
	}
}

func TestCapitalUnpaidWinsKeepOriginThroughWithdrawalPauseAndTighterLimits(t *testing.T) {
	f := capitalFixture(t)
	f.enter(f.assetQuote("BTC", 20*usd, 2))
	eth := f.enter(f.assetQuote("ETH", 20*usd, 2))
	f.surviveMarkets(eth.Expiry)
	assertMarketCapital(t, f.q.Snapshot(), map[string]int64{"BTC": 20 * usd, "ETH": 20 * usd})
	f.do(engine.Command{Kind: "withdraw", Actor: "alice", Amount: 120 * usd})
	assertMarketCapital(t, f.q.Snapshot(), map[string]int64{"BTC": 20 * usd, "ETH": 20 * usd})
	rejectRisk(t, f, engine.Command{Kind: "quote", Actor: "alice", Asset: "HYPE", Amount: usd, Multiplier: 2}, "custody-funded stake")
	s := f.q.Snapshot()
	if s.Accounts["alice"].WithdrawalUnfunded != 20*usd || s.Accounts["alice"].Unfunded != 20*usd {
		t.Fatal("withdrawal test did not move part of the winning debt")
	}
	p := s.Policy
	p.Version += "-remove"
	delete(p.Markets, "ETH")
	delete(p.Capital.MaxMarketExposure, "ETH")
	raw, _ := json.Marshal(p)
	rejectRisk(t, f, engine.Command{Kind: "policy_update", Raw: raw}, "unpaid winnings")
	p = f.q.Snapshot().Policy
	p.Version += "-tight"
	p.Capital.MaxMarketExposure["ETH"] = 10 * usd
	f.updateCapital(p)
	f.do(engine.Command{Kind: "pause"})
	rejectRisk(t, f, engine.Command{Kind: "resume"}, "market exposure limit")
	w := f.q.Snapshot().Accounts["alice"].Withdrawal
	f.do(engine.Command{Kind: "paper_settle"})
	f.do(engine.Command{Kind: "paper_pay", ID: w})
	assertMarketCapital(t, f.q.Snapshot(), nil)
	if !f.q.Snapshot().Paused || f.q.Snapshot().Accounts["alice"].Withdrawn != 120*usd {
		t.Fatal("tighter limits or pause prevented existing payment")
	}
	f.do(engine.Command{Kind: "resume"})
	replayed, err := engine.Open(context.Background(), f.policy, f.store)
	if err != nil || engine.Hash(replayed.Snapshot()) != engine.Hash(f.q.Snapshot()) {
		t.Fatal("winning-debt/withdrawal history does not replay", err)
	}
}

func TestCapitalCannotEnableWithoutReconciliationOrDisableAfterActivation(t *testing.T) {
	for _, kind := range []string{"open", "win", "loss"} {
		t.Run(kind, func(t *testing.T) {
			f := multiFixture(t)
			stage := f.enter(f.assetQuote("BTC", usd, 2))
			if kind == "win" {
				f.surviveMarkets(stage.Expiry)
			} else if kind == "loss" {
				f.price("1")
			}
			p := capitalPolicy(f)
			raw, _ := json.Marshal(p)
			rejectRisk(t, f, engine.Command{Kind: "policy_update", Raw: raw}, "reconciled zero exposure")
			if kind == "open" {
				f.now = stage.Expiry + f.policy.VoidDelayMS
				f.do(engine.Command{Kind: "tick"})
			}
			f.do(engine.Command{Kind: "paper_settle"})
			f.updateCapital(p)
			p = f.q.Snapshot().Policy
			p.Version += "-disabled"
			p.Capital = nil
			raw, _ = json.Marshal(p)
			rejectRisk(t, f, engine.Command{Kind: "policy_update", Raw: raw}, "cannot be disabled")
		})
	}
}

func TestCapitalPolicyAndDebtInvariantsRejectMissingOrFalseAttribution(t *testing.T) {
	base := capitalPolicy(multiFixture(t))
	for _, change := range []func(*engine.Policy){
		func(p *engine.Policy) { p.Capital.Rule = "unknown" },
		func(p *engine.Policy) { p.Capital.MaxBetLiability = 0 },
		func(p *engine.Policy) { p.Capital.MaxBetLiability = p.MaxExposure + 1 },
		func(p *engine.Policy) { delete(p.Capital.MaxMarketExposure, "ETH") },
		func(p *engine.Policy) { p.Capital.MaxMarketExposure["SOL"] = usd },
		func(p *engine.Policy) { p.Capital.MaxMarketExposure["ETH"] = -1 },
		func(p *engine.Policy) { p.Capital.MaxMarketExposure["HYPE"] = p.MaxExposure + 1 },
	} {
		raw, _ := json.Marshal(base)
		var p engine.Policy
		json.Unmarshal(raw, &p)
		change(&p)
		if p.Validate() == nil {
			t.Fatal("invalid capital policy accepted", p.Capital)
		}
	}
	f := capitalFixture(t)
	stage := f.enter(f.assetQuote("BTC", usd, 2))
	for _, mutate := range []func(*engine.State){
		func(s *engine.State) { s.Capital = nil },
		func(s *engine.State) { s.Capital.UnfundedByMarket = nil },
		func(s *engine.State) { s.Capital.UnfundedByMarket["SOL"] = usd },
		func(s *engine.State) { s.Capital.UnfundedByMarket["BTC"] = usd },
		func(s *engine.State) {
			s.Stages[stage.ID].Funded--
			s.Stages[stage.ID].Debt++
			s.Capital.UnfundedByMarket["BTC"] = 1
		},
	} {
		s := f.q.Snapshot()
		mutate(&s)
		if s.Check() == nil {
			t.Fatal("false attribution/funding accepted")
		}
	}
	s, err := engine.NewState(base)
	if err != nil {
		t.Fatal(err)
	}
	before := engine.Hash(s)
	base.Capital.MaxMarketExposure["BTC"]++
	if engine.Hash(s) != before {
		t.Fatal("capital configuration aliases caller-owned input")
	}
	if _, err := s.MarketExposure("SOL"); err == nil {
		t.Fatal("unknown market advertised as zero exposure")
	}
	f.surviveMarkets(stage.Expiry)
	s = f.q.Snapshot()
	delete(s.Capital.UnfundedByMarket, "BTC")
	s.Capital.UnfundedByMarket["ETH"] = usd // Correct aggregate debt, wrong origin.
	if err := s.Check(); err == nil || !strings.Contains(err.Error(), "provenance") {
		t.Fatal("aggregate equality concealed a market attribution error", err)
	}
}

func TestCapitalFailedWinningCommitPreservesReservationAndRetryCreditsOnce(t *testing.T) {
	f := capitalFixture(t)
	stage := f.enter(f.assetQuote("BTC", 20*usd, 2))
	for f.now+5000 < stage.Expiry {
		f.now += 5000
		f.price("100000")
	}
	f.now = stage.Expiry - 1
	f.price("100000")
	before := engine.Hash(f.q.Snapshot())
	f.store.Fail = true
	f.now = stage.Expiry
	command := f.cmd(engine.Command{Kind: "tick"})
	if _, err := f.q.Execute(context.Background(), command); err == nil || f.q.Ready() || engine.Hash(f.q.Snapshot()) != before {
		t.Fatal("failed winning commit was acknowledged or changed visible capital")
	}
	assertMarketCapital(t, f.q.Snapshot(), map[string]int64{"BTC": 20 * usd})
	if f.q.Snapshot().Debt() != 0 {
		t.Fatal("uncommitted winning debt leaked into visible state")
	}
	f.store.Fail = false
	replayed, err := engine.Open(context.Background(), f.policy, f.store)
	if err != nil {
		t.Fatal(err)
	}
	f.q = replayed
	f.do(command)
	f.do(command) // Exact retry must return the same committed event.
	f.do(engine.Command{Kind: "tick"})
	assertMarketCapital(t, f.q.Snapshot(), map[string]int64{"BTC": 20 * usd})
	if f.q.Snapshot().Debt() != 20*usd {
		t.Fatal("winning debt missing or credited twice after recovery")
	}
	f.do(engine.Command{Kind: "paper_settle"})
	if f.q.Snapshot().LP != 980*usd {
		t.Fatal("recovered winner funded more than once")
	}
}

func TestCapitalBufferUpdateCannotStrandExistingWinningClaims(t *testing.T) {
	f := capitalFixture(t)
	stage := f.enter(f.assetQuote("BTC", 20*usd, 2))
	f.surviveMarkets(stage.Expiry)
	p := f.q.Snapshot().Policy
	p.Version += "-buffer"
	p.LPBuffer = 980*usd + 1
	raw, _ := json.Marshal(p)
	before := engine.Hash(f.q.Snapshot())
	if _, err := f.q.Execute(context.Background(), f.cmd(engine.Command{Kind: "policy_update", Raw: raw})); err == nil {
		_, settlementErr := f.q.Execute(context.Background(), f.cmd(engine.Command{Kind: "paper_settle"}))
		t.Fatalf("unsafe buffer update accepted; existing winner settlement error: %v", settlementErr)
	} else if !strings.Contains(err.Error(), "buffer increase would strand") || engine.Hash(f.q.Snapshot()) != before {
		t.Fatal("unsafe buffer rejection changed obligations or has wrong cause", err)
	}
	p.LPBuffer = 980 * usd
	f.updateCapital(p)
	f.do(engine.Command{Kind: "pause"})
	f.do(engine.Command{Kind: "paper_settle"})
	event := f.do(engine.Command{Kind: "withdraw", Actor: "alice", Amount: 120 * usd})
	var withdrawal engine.Withdrawal
	json.Unmarshal(event.Result, &withdrawal)
	f.do(engine.Command{Kind: "paper_settle"})
	f.do(engine.Command{Kind: "paper_pay", ID: withdrawal.ID})
	if f.q.Snapshot().LP != 980*usd || f.q.Snapshot().Custody != 0 || !f.q.Snapshot().Paused {
		t.Fatal("safe buffer boundary did not preserve payout during pause")
	}
	f.do(engine.Command{Kind: "resume"})
	f.do(engine.Command{Kind: "deposit", Actor: "fresh", ID: "fresh", Amount: usd})
	f.do(engine.Command{Kind: "ack_deposit", ID: "fresh"})
	rejectRisk(t, f, engine.Command{Kind: "quote", Actor: "fresh", Amount: usd, Multiplier: 2}, "LP capacity")
}
