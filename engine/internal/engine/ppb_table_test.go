package engine_test

import (
	"context"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"fuse/engine/internal/engine"
)

func ppbPolicy(t *testing.T, menu []int64, widths []int64) engine.Policy {
	t.Helper()
	raw, err := os.ReadFile("../../config/paper.json")
	if err != nil {
		t.Fatal(err)
	}
	var p engine.Policy
	if err := json.Unmarshal(raw, &p); err != nil {
		t.Fatal(err)
	}
	p.Markets = nil
	p.Version = "ppb-table-test-v1"
	p.Multipliers = menu
	p.Model.Version = p.Version
	p.Model.DNT = nil
	p.Model.MultiplierWidthsPPB = map[int64]int64{}
	for i, m := range menu {
		p.Model.MultiplierWidthsPPB[m] = widths[i]
	}
	return p
}

func ppbFixture(t *testing.T, p engine.Policy) *fixture {
	t.Helper()
	raw, err := json.Marshal(p)
	if err != nil {
		t.Fatal(err)
	}
	path := filepath.Join(t.TempDir(), "policy.json")
	if err := os.WriteFile(path, raw, 0600); err != nil {
		t.Fatal(err)
	}
	return fixturePolicy(t, path)
}

func TestPPBTableQuotesExactOnePPMAndFractionalWidthsWithoutUnusedPayouts(t *testing.T) {
	for _, width := range []int64{1, 123, 999, 1000, 1234, 8000} {
		t.Run(fmt.Sprint(width), func(t *testing.T) {
			f := ppbFixture(t, ppbPolicy(t, []int64{2}, []int64{width}))
			q := f.selectQuote(1_000_000, 2)
			delta := q.Price * width / 1_000_000_000
			if q.WidthPPB != width || q.PricingRule != engine.FixedWidthPPB || q.Lower != q.Price-delta || q.Upper != q.Price+delta || q.TargetSurvivalPPB != 0 || q.HouseEdgeBPS != 0 {
				t.Fatal("exact PPB terms or unknown calibration metadata changed", q)
			}
			rejectRisk(t, f, engine.Command{Kind: "quote", Actor: "alice", Amount: 1_000_000, Multiplier: 5}, "integer multiplier")
			f.enter(q)
		})
	}
}

func TestPPBTableSupportsAllPresetsAtSubPPMResolution(t *testing.T) {
	menu := engine.PayoutOptions()
	widths := []int64{1000, 900, 800, 700, 600, 500, 400, 200, 1}
	f := ppbFixture(t, ppbPolicy(t, menu, widths))
	f.do(engine.Command{Kind: "lp_fund", Amount: 20_000_000_000})
	for i, multiplier := range menu {
		q := f.selectQuote(1_000_000, multiplier)
		if q.WidthPPB != widths[i] || q.Payout != multiplier*1_000_000 || q.MaxLPLiability != (multiplier-1)*1_000_000 {
			t.Fatal("payout or reservation changed", q)
		}
	}
}

func TestPPBTableValidationRejectsAmbiguousOrUnboundedMenus(t *testing.T) {
	for name, change := range map[string]func(*engine.Policy){
		"missing":   func(p *engine.Policy) { p.Multipliers = []int64{2, 5} },
		"extra":     func(p *engine.Policy) { p.Model.MultiplierWidthsPPB[5] = 1 },
		"duplicate": func(p *engine.Policy) { p.Multipliers = []int64{2, 2} },
		"unknown": func(p *engine.Policy) {
			p.Multipliers = []int64{3}
			p.Model.MultiplierWidthsPPB = map[int64]int64{3: 1000}
		},
		"nil menu":   func(p *engine.Policy) { p.Multipliers = nil },
		"empty menu": func(p *engine.Policy) { p.Multipliers = []int64{} },
		"unsorted":   func(p *engine.Policy) { p.Multipliers = []int64{5, 2}; p.Model.MultiplierWidthsPPB[5] = 1001 },
		"equal":      func(p *engine.Policy) { p.Multipliers = []int64{2, 5}; p.Model.MultiplierWidthsPPB[5] = 1000 },
		"wider":      func(p *engine.Policy) { p.Multipliers = []int64{2, 5}; p.Model.MultiplierWidthsPPB[5] = 1001 },
		"zero":       func(p *engine.Policy) { p.Model.MultiplierWidthsPPB[2] = 0 },
		"negative":   func(p *engine.Policy) { p.Model.MultiplierWidthsPPB[2] = -1 },
		"cap":        func(p *engine.Policy) { p.Model.MultiplierWidthsPPB[2] = p.Model.MaxWidthBPS*100_000 + 1 },
		"brownian": func(p *engine.Policy) {
			p.Model.DNT = &engine.DNTModel{Rule: engine.BrownianFirstMode, VolatilityPPM: 1000, HouseEdgeBPS: 500}
		},
		"ppm":            func(p *engine.Policy) { p.Model.MultiplierWidthsPPM = map[int64]int64{2: 1} },
		"legacy product": func(p *engine.Policy) { p.Product = "" },
		"mixed market": func(p *engine.Policy) {
			other := p.Model
			other.MultiplierWidthsPPB = nil
			other.DNT = &engine.DNTModel{Rule: engine.BrownianFirstMode, VolatilityPPM: 1000, HouseEdgeBPS: 500}
			p.Markets = map[string]engine.Model{"ETH": other}
		},
	} {
		t.Run(name, func(t *testing.T) {
			p := ppbPolicy(t, []int64{2}, []int64{1000})
			change(&p)
			if p.Validate() == nil {
				t.Fatal("invalid PPB pricing accepted", p)
			}
		})
	}
}

func TestPPBTableMultiAssetAndLowPriceRounding(t *testing.T) {
	p := ppbPolicy(t, []int64{2}, []int64{1000})
	p.Markets = map[string]engine.Model{"ETH": p.Model, "HYPE": p.Model}
	f := ppbFixture(t, p)
	for _, asset := range []string{"ETH", "HYPE"} {
		for _, source := range []string{"a", "b"} {
			f.do(engine.Command{Kind: "oracle", Source: source, Raw: json.RawMessage(fmt.Sprintf(`{"channel":"activeAssetCtx","data":{"coin":%q,"ctx":{"oraclePx":"0.100000"}}}`, asset))})
		}
		// At this asset price, a 1-ppm half-width rounds to zero price units;
		// the engine must reject rather than silently widen the corridor.
		rejectRisk(t, f, engine.Command{Kind: "quote", Actor: "alice", Amount: 1_000_000, Multiplier: 2, Asset: asset}, "invalid corridor")
		for _, source := range []string{"a", "b"} {
			f.do(engine.Command{Kind: "oracle", Source: source, Raw: json.RawMessage(fmt.Sprintf(`{"channel":"activeAssetCtx","data":{"coin":%q,"ctx":{"oraclePx":"10.000000"}}}`, asset))})
		}
		e := f.do(engine.Command{Kind: "quote", Actor: "alice", Amount: 1_000_000, Multiplier: 2, Asset: asset})
		var q engine.Quote
		if err := json.Unmarshal(e.Result, &q); err != nil || q.Asset != asset || q.Upper-q.Price != 10 {
			t.Fatal("incorrect asset-specific integer barrier", q, err)
		}
	}
}

func TestPPBTableUpdateInvalidatesUnacceptedQuoteButPreservesAcceptedTermsAndReplay(t *testing.T) {
	p := ppbPolicy(t, []int64{2, 5}, []int64{1000, 123})
	f := ppbFixture(t, p)
	old := f.selectQuote(1_000_000, 2)
	stage := f.enter(old)
	f.do(engine.Command{Kind: "deposit", Actor: "bob", ID: "bob", Amount: 1_000_000})
	f.do(engine.Command{Kind: "ack_deposit", ID: "bob"})
	e := f.do(engine.Command{Kind: "quote", Actor: "bob", Amount: 1_000_000, Multiplier: 5})
	var unaccepted engine.Quote
	json.Unmarshal(e.Result, &unaccepted)
	updated := ppbPolicy(t, []int64{2}, []int64{8000})
	updated.Version += "-new"
	updated.Model.Version += "-new"
	raw, _ := json.Marshal(updated)
	f.do(engine.Command{Kind: "policy_update", Raw: raw})
	rejectRisk(t, f, engine.Command{Kind: "enter", Actor: "bob", ID: unaccepted.ID}, "expired, unavailable or stale")
	f.survive(stage)
	s := f.q.Snapshot()
	if engine.Hash(s.Stages[stage.ID].Terms) != engine.Hash(old) || s.Stages[stage.ID].Status != "survived" || s.Debt() != 1_000_000 {
		t.Fatal("accepted terms or winning liability changed", s.Stages[stage.ID], s.Debt())
	}
	f.do(engine.Command{Kind: "withdraw", Actor: "alice", Amount: 101_000_000})
	f.do(engine.Command{Kind: "paper_settle"})
	f.do(engine.Command{Kind: "paper_pay", ID: f.q.Snapshot().Accounts["alice"].Withdrawal})
	replayed, err := engine.Open(context.Background(), f.policy, f.store)
	if err != nil || engine.Hash(replayed.Snapshot()) != engine.Hash(f.q.Snapshot()) {
		t.Fatal("PPB table policy/settlement replay diverged", err)
	}
}

func TestPPBTableTouchAndOracleSequenceStillFailClosed(t *testing.T) {
	for _, side := range []string{"lower", "upper"} {
		t.Run(side, func(t *testing.T) {
			f := ppbFixture(t, ppbPolicy(t, []int64{2}, []int64{1000}))
			q := f.selectQuote(1_000_000, 2)
			stage := f.enter(q)
			barrier := q.Lower
			if side == "upper" {
				barrier = q.Upper
			}
			f.now++
			f.price(fmt.Sprintf("%d.%06d", barrier/1_000_000, barrier%1_000_000))
			if f.q.Snapshot().Stages[stage.ID].Status != "exploded" {
				t.Fatal("exact barrier touch did not lose")
			}
		})
	}
	f := ppbFixture(t, ppbPolicy(t, []int64{2}, []int64{1000}))
	q := f.selectQuote(1_000_000, 2)
	f.now++
	f.price("100001")
	f.price("100000")
	rejectRisk(t, f, engine.Command{Kind: "enter", Actor: "alice", ID: q.ID}, "stale")
}

func TestPPBTableDoesNotAlterLegacyPolicyEncodingOrPermitLegacySubset(t *testing.T) {
	raw, err := os.ReadFile("../../config/paper.json")
	if err != nil {
		t.Fatal(err)
	}
	var p engine.Policy
	json.Unmarshal(raw, &p)
	encoded, _ := json.Marshal(p)
	if strings.Contains(string(encoded), "multiplier_widths_ppb") {
		t.Fatal("absent field changes legacy serialized policies")
	}
	p.Multipliers = []int64{2}
	if p.Validate() == nil {
		t.Fatal("legacy Brownian menu silently changed")
	}
}
