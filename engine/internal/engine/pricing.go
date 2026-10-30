package engine

import (
	"fmt"
	"math/big"
)

const BrownianFirstMode = "brownian-first-mode-v1"
const FixedWidthPPB = "fixed-width-ppb-v1"
const pricingQ int64 = 1_000_000_000_000
const pricingPi int64 = 3_141_592_653_590
const pricingLn2 int64 = 693_147_180_560

// DNTModel assumes driftless arithmetic Brownian relative returns. VolatilityPPM
// is the standard deviation over the complete 30-second stage, NOT annualized.
// This is a research model; its assumptions are not empirical oracle calibration.
type DNTModel struct {
	Rule          string `json:"rule"`
	VolatilityPPM int64  `json:"volatility_30s_ppm"`
	HouseEdgeBPS  int64  `json:"house_edge_bps"`
}

func (m DNTModel) Validate() error {
	if m.Rule != BrownianFirstMode || m.VolatilityPPM < 1 || m.VolatilityPPM > 100_000 || m.HouseEdgeBPS < 0 || m.HouseEdgeBPS > 5000 {
		return fmt.Errorf("invalid Brownian pricing assumptions")
	}
	return nil
}

// WidthPPB inverts the first eigenfunction of Brownian survival in (-a,a):
// a = pi*sigma30 / sqrt(8*ln(4*M/(pi*(1-h)))).
// Exact survival is an alternating series; for M>=2 and h>=0, its absolute
// difference from the target is <0.000095 before integer rounding. See
// docs/BARRIER_PRICING.md. Money and barriers use integer arithmetic only.
func (m DNTModel) WidthPPB(multiplier int64) (int64, error) {
	if err := m.Validate(); err != nil {
		return 0, err
	}
	if multiplier < MinMultiplier || multiplier > MaxMultiplier {
		return 0, fmt.Errorf("invalid payout multiplier")
	}
	retainedPi, _ := MulDiv(pricingPi, 10_000-m.HouseEdgeBPS, 10_000)
	// This dimensionless Q12 ratio can exceed the money/price Limit at high
	// payouts. Its validated maximum (M=10000, edge=50%) still fits int64.
	ratioQ := new(big.Int).Mul(big.NewInt(4*multiplier*pricingQ), big.NewInt(pricingQ))
	ratioQ.Quo(ratioQ, big.NewInt(retainedPi))
	ratio := ratioQ.Int64()
	logarithm := pricingLog(ratio)
	denominator := new(big.Int).Mul(big.NewInt(8*logarithm), big.NewInt(pricingQ))
	denominator.Sqrt(denominator)
	return MulDiv(m.VolatilityPPM*1000, pricingPi, denominator.Int64())
}

// log(x) in Q12: range reduction to [1,2) and the positive atanh series.
// Its argument is bounded by DNTModel.Validate and M in [2,10000].
func pricingLog(x int64) int64 {
	powers := int64(0)
	for x >= 2*pricingQ {
		x /= 2
		powers++
	}
	z, _ := MulDiv(x-pricingQ, pricingQ, x+pricingQ)
	z2, _ := MulDiv(z, z, pricingQ)
	term, sum := z, z
	for n := int64(3); n <= 63; n += 2 {
		term, _ = MulDiv(term, z2, pricingQ)
		sum += term / n
	}
	return 2*sum + powers*pricingLn2
}
