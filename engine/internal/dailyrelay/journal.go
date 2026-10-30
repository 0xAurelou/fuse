// Package dailyrelay binds replayed shared-engine decisions to confirmed daily
// custody tickets. It supplies no default keys or public-network broadcaster.
package dailyrelay

import (
	"fmt"
	"math/big"

	"fuse/engine/internal/contracts"
	"fuse/engine/internal/engine"
	"github.com/ethereum/go-ethereum/common"
)

// Journal can only be created by complete deterministic replay. Callers cannot
// provide a forged stage snapshot directly to the signing path.
type Journal struct{ state engine.State }

func Replay(policy engine.Policy, events []engine.Event) (*Journal, error) {
	if policy.Product != engine.SingleStage {
		return nil, fmt.Errorf("daily relay requires the single-stage engine")
	}
	s, err := engine.NewState(policy)
	if err != nil {
		return nil, err
	}
	seen := map[string]bool{}
	for _, e := range events {
		if seen[e.Command.Key] {
			return nil, fmt.Errorf("duplicate replay command")
		}
		seen[e.Command.Key] = true
		next, got, err := engine.Apply(s, e.Command)
		if err != nil || engine.Hash(got) != engine.Hash(e) {
			return nil, fmt.Errorf("daily source replay diverges at %d: %v", e.Sequence, err)
		}
		s = next
	}
	if len(events) == 0 || s.Check() != nil {
		return nil, fmt.Errorf("empty or unreconciled daily source journal")
	}
	return &Journal{state: s}, nil
}

func (j *Journal) Stage(id string) (engine.Stage, error) {
	if j == nil {
		return engine.Stage{}, fmt.Errorf("missing verified journal")
	}
	p := j.state.Stages[id]
	if p == nil || p.Terms.Product != engine.SingleStage || p.Terms.DurationMS != 30_000 || p.Funded != p.Terms.Stake || p.Debt != 0 || p.Terms.MaxLPLiability != p.Terms.Payout-p.Terms.Stake {
		return engine.Stage{}, fmt.Errorf("stage is not accepted custody-funded single-stage risk")
	}
	return *p, nil // Stage and Quote contain only scalar values.
}

func (j *Journal) Outcome(id string) (engine.SettlementOutcome, error) {
	if j == nil {
		return engine.SettlementOutcome{}, fmt.Errorf("missing verified journal")
	}
	return j.state.SettlementOutcome(id)
}

// QuoteForStage rounds the start up and the exclusive TTL down to a last
// admissible whole second, never extending the native quote's validity.
// Start/expiry and outcome time are not rounded and must match the chain event.
func QuoteForStage(p engine.Stage, ticket common.Hash) (contracts.DailyQuote, error) {
	q := p.Terms
	if ticket == (common.Hash{}) || !common.IsHexAddress(q.Account) || common.HexToAddress(q.Account) == (common.Address{}) || q.Product != engine.SingleStage || q.DurationMS != 30_000 || q.Issued < 0 || q.ValidUntil <= q.Issued || q.Stake <= 0 || q.Payout <= q.Stake || q.Multiplier < 2 || q.Payout/q.Stake != q.Multiplier || q.Payout%q.Stake != 0 || q.Lower <= 0 || q.Lower >= q.Price || q.Price >= q.Upper {
		return contracts.DailyQuote{}, fmt.Errorf("native terms cannot form a daily custody quote")
	}
	asset := uint8(0)
	switch engine.AssetName(q.Asset) {
	case "BTC":
	case "ETH":
		asset = 1
	case "HYPE":
		asset = 2
	default:
		return contracts.DailyQuote{}, fmt.Errorf("unsupported daily asset")
	}
	first, last := uint64((q.Issued+999)/1000), uint64((q.ValidUntil-1)/1000)
	if last < first || last-first > 5 {
		return contracts.DailyQuote{}, fmt.Errorf("native quote has no supported whole-second validity window")
	}
	return contracts.DailyQuote{Id: ticket, Account: common.HexToAddress(q.Account), Asset: asset, Stake: big.NewInt(q.Stake), Multiplier: big.NewInt(q.Multiplier), Lower: big.NewInt(q.Lower), ReferencePrice: big.NewInt(q.Price), Upper: big.NewInt(q.Upper), QuotedAt: first, ValidUntil: last, PricingHash: common.HexToHash(engine.Hash(q))}, nil
}
