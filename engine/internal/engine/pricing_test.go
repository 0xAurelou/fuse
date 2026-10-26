package engine_test

import (
	"encoding/json"
	"math"
	"os"
	"testing"

	"fuse/engine/internal/engine"
)

// Independent floating-point reference for the full absorbing-interval series,
// rather than a copy of the fixed-point logarithm used in quote construction.
func brownianSurvival(normalizedWidth float64) float64 {
	sum := 0.0
	for n := 0; n < 20; n++ {
		k := float64(2*n + 1)
		term := math.Exp(-k*k*math.Pi*math.Pi/(8*normalizedWidth*normalizedWidth)) / k
		if n%2 == 0 {
			sum += term
		} else {
			sum -= term
		}
	}
	return 4 * sum / math.Pi
}

func TestBrownianFormulaMatchesReferenceAndBoundedSurvivalTarget(t *testing.T) {
	for _, edge := range []int64{0, 500, 5000} {
		previous := int64(math.MaxInt64)
		for _, multiplier := range engine.PayoutOptions() {
			model := engine.DNTModel{Rule: engine.BrownianFirstMode, VolatilityPPM: 1000, HouseEdgeBPS: edge}
			width, err := model.WidthPPB(multiplier)
			if err != nil || width <= 0 || width >= previous {
				t.Fatal("nonmonotone formula", multiplier, width, err)
			}
			previous = width
			target := (1 - float64(edge)/10000) / float64(multiplier)
			reference := math.Pi * 1_000_000 / math.Sqrt(8*math.Log(4/(math.Pi*target)))
			if math.Abs(float64(width)-math.Floor(reference)) > 1 {
				t.Fatal("integer formula differs from reference", width, reference)
			}
			probability := brownianSurvival(float64(width) / 1_000_000)
			if probability > target+1e-8 || target-probability > .0001 {
				t.Fatal("survival approximation outside bound", multiplier, target, probability)
			}
			doubled := model
			doubled.VolatilityPPM *= 2
			wide, err := doubled.WidthPPB(multiplier)
			if err != nil || wide < 2*width || wide > 2*width+1 {
				t.Fatal("width is not proportional to volatility", wide, width, err)
			}
		}
	}
}

func TestBrownianPricingBoundsAndQuoteAssumptions(t *testing.T) {
	for _, model := range []engine.DNTModel{
		{Rule: "unknown", VolatilityPPM: 1000},
		{Rule: engine.BrownianFirstMode, VolatilityPPM: 0},
		{Rule: engine.BrownianFirstMode, VolatilityPPM: 100001},
		{Rule: engine.BrownianFirstMode, VolatilityPPM: 1000, HouseEdgeBPS: -1},
		{Rule: engine.BrownianFirstMode, VolatilityPPM: 1000, HouseEdgeBPS: 5001},
	} {
		if _, err := model.WidthPPB(2); err == nil {
			t.Fatal("invalid assumptions accepted", model)
		}
	}
	f := singleFixture(t)
	q := f.selectQuote(1_000_000, 100)
	if q.PricingRule != engine.BrownianFirstMode || q.VolatilityPPM != 1000 || q.HouseEdgeBPS != 500 || q.TargetSurvivalPPB != 9_500_000 || q.WidthPPB != 501873 {
		t.Fatal("quote did not commit pricing assumptions", q)
	}
	policy := f.q.Snapshot().Policy
	policy.Model.MaxWidthBPS = 1
	if policy.Validate() == nil {
		t.Fatal("formula width bypassed the maximum corridor")
	}
}

func TestBrownianSharedBrowserVectors(t *testing.T) {
	raw, err := os.ReadFile("../../testdata/brownian-pricing-vectors.json")
	if err != nil {
		t.Fatal(err)
	}
	var vectors []struct {
		Multiplier int64 `json:"multiplier"`
		Volatility int64 `json:"volatility_30s_ppm"`
		Edge       int64 `json:"house_edge_bps"`
		Width      int64 `json:"width_ppb"`
	}
	if err := json.Unmarshal(raw, &vectors); err != nil {
		t.Fatal(err)
	}
	for _, v := range vectors {
		m := engine.DNTModel{Rule: engine.BrownianFirstMode, VolatilityPPM: v.Volatility, HouseEdgeBPS: v.Edge}
		got, err := m.WidthPPB(v.Multiplier)
		if err != nil || got != v.Width {
			t.Fatal("shared vector mismatch", v, got, err)
		}
	}
}
