package engine

import "fmt"

// FundedCapital is the release candidate's physically funded single-stage rule.
// Existing policies omit Capital and preserve their historical commitments.
const FundedCapital = "funded-single-stage-capital-v1"

type CapitalLimits struct {
	Rule              string           `json:"rule"`
	MaxBetLiability   int64            `json:"max_bet_liability"`
	MaxMarketExposure map[string]int64 `json:"max_market_exposure"`
}

type CapitalState struct {
	// Debt keeps its originating market while it moves from an available user
	// entitlement into a withdrawal. Only confirmed settlement clears it.
	UnfundedByMarket map[string]int64 `json:"unfunded_by_market"`
	// Outcome watermark, not settlement-command time: planning and confirmed
	// funding must commit the same financial projection even in a later block.
	FundedThroughSequence uint64 `json:"funded_through_sequence"`
}

func (c CapitalLimits) validate(p Policy) error {
	if c.Rule != FundedCapital || p.Product != SingleStage || c.MaxBetLiability <= 0 || c.MaxBetLiability > p.MaxExposure || len(c.MaxMarketExposure) != len(p.Assets()) {
		return fmt.Errorf("invalid funded capital policy")
	}
	for _, asset := range p.Assets() {
		if limit := c.MaxMarketExposure[asset]; limit <= 0 || limit > p.MaxExposure {
			return fmt.Errorf("funded capital policy needs a bounded limit for every enabled market")
		}
	}
	return nil
}

// MarketExposure returns simultaneous maximum open/pending obligations plus
// recognized unpaid winnings from that market. It requires the opt-in capital
// rule because older journals did not retain the market of fungible debt.
func (s State) MarketExposure(asset string) (int64, error) {
	if s.Capital == nil || s.Policy.Capital == nil {
		return 0, fmt.Errorf("market debt attribution unavailable for legacy policy")
	}
	asset = AssetName(asset)
	if !s.Policy.HasAsset(asset) {
		return 0, fmt.Errorf("market not enabled")
	}
	n := s.Capital.UnfundedByMarket[asset]
	for _, stage := range s.Stages {
		if AssetName(stage.Terms.Asset) == asset && (stage.Status == "active" || stage.Status == "pending") {
			n += stage.Terms.Payout - stage.Funded
		}
	}
	return n, nil
}

func (s State) checkCapital() error {
	if (s.Capital == nil) != (s.Policy.Capital == nil) {
		return fmt.Errorf("capital policy/state mismatch")
	}
	if s.Capital == nil {
		return nil
	}
	if s.Capital.UnfundedByMarket == nil {
		return fmt.Errorf("market winning debt state unavailable")
	}
	if s.Capital.FundedThroughSequence > s.Sequence {
		return fmt.Errorf("market funding watermark exceeds journal sequence")
	}
	var debt int64
	for asset, amount := range s.Capital.UnfundedByMarket {
		if !s.Policy.HasAsset(asset) || asset != AssetName(asset) || amount <= 0 || amount > Limit-debt {
			return fmt.Errorf("invalid market winning debt")
		}
		debt += amount
	}
	if debt != s.Debt() {
		return fmt.Errorf("market winning debt reconciliation mismatch")
	}
	expected := map[string]int64{}
	for _, stage := range s.Stages {
		if (stage.Status == "active" || stage.Status == "pending") && (stage.Terms.Product != SingleStage || stage.Debt != 0 || stage.Funded != stage.Terms.Stake) {
			return fmt.Errorf("capital policy requires custody-funded single-stage stakes")
		}
		if stage.ResolvedSequence > s.Sequence || ((stage.Status == "active" || stage.Status == "pending") && stage.ResolvedSequence != 0) {
			return fmt.Errorf("invalid market outcome sequence")
		}
		if stage.Status == "survived" && stage.ResolvedSequence > s.Capital.FundedThroughSequence {
			asset := AssetName(stage.Terms.Asset)
			if !s.Policy.HasAsset(asset) {
				return fmt.Errorf("unfunded winner has a disabled market")
			}
			expected[asset] += stage.Terms.Payout - stage.Funded
		}
	}
	for _, asset := range s.Policy.Assets() {
		if expected[asset] != s.Capital.UnfundedByMarket[asset] {
			return fmt.Errorf("market winning debt provenance mismatch")
		}
	}
	return nil
}

// Called both when quoting and again inside atomic acceptance, before inserting
// the new stage. Quotes never reserve scarce capacity.
func (s State) capitalAdmission(asset string, stake, funded, liability int64) error {
	if s.Policy.Capital == nil {
		return nil
	}
	if funded != stake {
		return reject("capital policy requires custody-funded stake")
	}
	if liability > s.Policy.Capital.MaxBetLiability {
		return reject("per-bet liability limit")
	}
	exposure, err := s.MarketExposure(asset)
	if err != nil {
		return err
	}
	if exposure+liability > s.Policy.Capital.MaxMarketExposure[AssetName(asset)] {
		return reject("market exposure limit")
	}
	return nil
}

func (s State) capitalCapacity() error {
	if s.Policy.Capital == nil {
		return nil
	}
	for _, asset := range s.Policy.Assets() {
		exposure, err := s.MarketExposure(asset)
		if err != nil {
			return err
		}
		if exposure > s.Policy.Capital.MaxMarketExposure[asset] {
			return reject("market exposure limit")
		}
	}
	return nil
}
