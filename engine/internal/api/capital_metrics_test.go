package api

import (
	"context"
	"encoding/json"
	"fmt"
	"strings"
	"testing"

	"fuse/engine/internal/engine"
)

func TestCapitalMetricsRequireAdminAndDistinguishLegacyAttribution(t *testing.T) {
	s, token, _ := setup(t)
	for _, auth := range []string{"", token} {
		if got := request(s, "GET", "/metrics", auth, ""); got.Code != 401 {
			t.Fatal("capital metrics exposed without operator credentials", got.Code)
		}
	}
	got := request(s, "GET", "/metrics", s.AdminToken, "")
	if got.Code != 200 || !strings.Contains(got.Body.String(), "fuse_capital_limits_enabled 0\n") || strings.Contains(got.Body.String(), "fuse_market_exposure_usdc_units{") {
		t.Fatal("legacy attribution misrepresented", got.Body.String())
	}
}

func TestCapitalMetricsKeepUnpaidMarketWinsUntilConfirmedSettlement(t *testing.T) {
	s, _, wallet := setup(t)
	now, serial := int64(1_000_000), 0
	s.Now = func() int64 { return now }
	do := func(command engine.Command) engine.Event {
		t.Helper()
		serial++
		command.Key, command.At = fmt.Sprintf("metrics/%d", serial), now
		event, err := s.Q.Execute(context.Background(), command)
		if err != nil {
			t.Fatal(err)
		}
		return event
	}
	p := s.Q.Snapshot().Policy
	p.Version += "-capital-metrics"
	p.Capital = &engine.CapitalLimits{Rule: engine.FundedCapital, MaxBetLiability: 25_000_000,
		MaxMarketExposure: map[string]int64{"BTC": 100_000_000, "ETH": 100_000_000, "HYPE": 100_000_000}}
	raw, _ := json.Marshal(p)
	do(engine.Command{Kind: "policy_update", Raw: raw})
	do(engine.Command{Kind: "lp_fund", Amount: 1_000_000_000})
	do(engine.Command{Kind: "deposit", Actor: wallet, ID: "cash", Amount: 100_000_000})
	do(engine.Command{Kind: "ack_deposit", ID: "cash"})
	price := func() {
		for _, source := range []string{"a", "b"} {
			do(engine.Command{Kind: "oracle", Source: source, Raw: json.RawMessage(`{"channel":"activeAssetCtx","data":{"coin":"BTC","ctx":{"oraclePx":"100000"}}}`)})
		}
	}
	price()
	event := do(engine.Command{Kind: "quote", Actor: wallet, Amount: 10_000_000, Multiplier: 2})
	var quote engine.Quote
	json.Unmarshal(event.Result, &quote)
	do(engine.Command{Kind: "enter", Actor: wallet, ID: quote.ID})
	check := func(unfunded int64) {
		t.Helper()
		got := request(s, "GET", "/metrics", s.AdminToken, "")
		if got.Code != 200 {
			t.Fatal(got.Code, got.Body.String())
		}
		for _, line := range []string{
			"fuse_capital_limits_enabled 1\n",
			"fuse_market_exposure_usdc_units{asset=\"BTC\"} 10000000\n",
			fmt.Sprintf("fuse_market_unfunded_wins_usdc_units{asset=\"BTC\"} %d\n", unfunded),
			"fuse_market_exposure_usdc_units{asset=\"ETH\"} 0\n",
			"fuse_market_exposure_limit_usdc_units{asset=\"BTC\"} 100000000\n",
			"fuse_lp_admission_headroom_usdc_units 890000000\n",
		} {
			if !strings.Contains(got.Body.String(), line) {
				t.Fatal("missing or wrong metric", line, got.Body.String())
			}
		}
	}
	check(0)
	for range 6 {
		now += 5000
		price()
	}
	check(10_000_000)
	do(engine.Command{Kind: "paper_settle"})
	got := request(s, "GET", "/metrics", s.AdminToken, "")
	if !strings.Contains(got.Body.String(), "fuse_market_exposure_usdc_units{asset=\"BTC\"} 0\n") || !strings.Contains(got.Body.String(), "fuse_lp_available_usdc_units 990000000\n") {
		t.Fatal("settled market debt remained or cash was not paid", got.Body.String())
	}
}
