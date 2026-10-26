package engine

import (
	"encoding/json"
	"errors"
	"math/big"
	"strings"
)

// ParsePrice accepts exact decimal strings with at most 6 fractional places.
// Exponents, signs, floats, excess precision and alternate price fields are rejected.
func ParsePrice(v string) (int64, error) {
	parts := strings.Split(v, ".")
	if len(parts) > 2 || parts[0] == "" {
		return 0, errors.New("invalid decimal price")
	}
	frac := ""
	if len(parts) == 2 {
		frac = parts[1]
		if frac == "" || len(frac) > 6 {
			return 0, errors.New("invalid price precision")
		}
	}
	for _, r := range parts[0] + frac {
		if r < '0' || r > '9' {
			return 0, errors.New("invalid decimal price")
		}
	}
	n, ok := new(big.Int).SetString(parts[0]+frac+strings.Repeat("0", 6-len(frac)), 10)
	if !ok || !n.IsInt64() || n.Sign() <= 0 || n.Int64() > Limit {
		return 0, errors.New("price out of range")
	}
	return n.Int64(), nil
}
func ParseOracle(raw json.RawMessage) (int64, error) {
	asset, price, err := ParseAssetOracle(raw)
	if err != nil {
		return 0, err
	}
	if asset != "BTC" {
		return 0, errors.New("expected BTC activeAssetCtx")
	}
	return price, nil
}
func ParseAssetOracle(raw json.RawMessage) (string, int64, error) {
	var msg struct {
		Channel string `json:"channel"`
		Data    struct {
			Coin string `json:"coin"`
			Ctx  struct {
				OraclePx string `json:"oraclePx"`
			} `json:"ctx"`
		} `json:"data"`
	}
	if err := json.Unmarshal(raw, &msg); err != nil {
		return "", 0, err
	}
	if msg.Channel != "activeAssetCtx" || !SupportedAsset(msg.Data.Coin) {
		return "", 0, errors.New("expected enabled perp activeAssetCtx")
	}
	price, err := ParsePrice(msg.Data.Ctx.OraclePx)
	return msg.Data.Coin, price, err
}
func (s State) Healthy(at int64) bool { return s.HealthyAsset("BTC", at) }
func (s State) gap(at int64) bool     { return s.gapAsset("BTC", at) }
func (s State) HealthyAsset(asset string, at int64) bool {
	oracle := s.AssetOracle(asset)
	a, b := oracle.Sources["a"], oracle.Sources["b"]
	return a.At > 0 && b.At > 0 && at >= a.At && at >= b.At && at-a.At <= s.Policy.MaxGapMS && at-b.At <= s.Policy.MaxGapMS && a.Price == b.Price && oracle.Price == a.Price
}
func (s State) gapAsset(asset string, at int64) bool {
	oracle := s.AssetOracle(asset)
	a, b := oracle.Sources["a"], oracle.Sources["b"]
	return a.At == 0 || b.At == 0 || at-a.At > s.Policy.MaxGapMS || at-b.At > s.Policy.MaxGapMS || (oracle.MismatchSince > 0 && at-oracle.MismatchSince >= s.Policy.DisagreementMS)
}
func (s *State) observe(c Command) error {
	if c.Source != "a" && c.Source != "b" {
		return reject("unknown oracle receiver")
	}
	asset, price, err := ParseAssetOracle(c.Raw)
	if err != nil {
		return reject(err.Error())
	}
	if !s.Policy.HasAsset(asset) {
		return reject("market not enabled")
	}
	oracle := s.oraclePointer(asset)
	// Raw bytes remain in Command; the linked oracle hash commits every receiver message.
	oracle.JournalHash = Hash(struct {
		Previous string
		Command  Command
	}{oracle.JournalHash, c})
	oracle.Sources[c.Source] = Feed{price, c.At, Hash(c.Raw)}
	a, b := oracle.Sources["a"], oracle.Sources["b"]
	if a.Price != b.Price {
		if oracle.MismatchSince == 0 {
			oracle.MismatchSince = c.At
		}
		return nil
	}
	oracle.MismatchSince = 0
	if c.At-a.At > s.Policy.MaxGapMS || c.At-b.At > s.Policy.MaxGapMS {
		return nil
	}
	if price != oracle.Price {
		if oracle.Price > 0 {
			delta := price - oracle.Price
			if delta < 0 {
				delta = -delta
			}
			r, err := MulDiv(delta, 10_000, oracle.Price)
			if err != nil {
				return reject("oracle return exceeds arithmetic envelope")
			}
			oracle.ReturnsBPS = append(oracle.ReturnsBPS, r)
			if len(oracle.ReturnsBPS) > 32 {
				oracle.ReturnsBPS = oracle.ReturnsBPS[1:]
			}
		}
		oracle.Price = price
		oracle.Sequence++
	}
	oracle.At = c.At
	for _, id := range keys(s.Stages) {
		p := s.Stages[id]
		if AssetName(p.Terms.Asset) == asset && (p.Status == "active" || p.Status == "pending") && c.At >= p.Start && c.At < p.Expiry && (price <= p.Terms.Lower || price >= p.Terms.Upper) {
			s.resolve(p, "exploded", c.At)
			p.BreachSequence = oracle.Sequence
		}
	}
	return nil
}
func (s *State) advance(at int64) {
	for _, id := range keys(s.Stages) {
		p := s.Stages[id]
		if p.Status != "active" && p.Status != "pending" {
			continue
		}
		if s.gapAsset(p.Terms.Asset, at) {
			p.Status = "pending"
		}
		if at >= p.Expiry {
			if !s.HealthyAsset(p.Terms.Asset, at) {
				p.Status = "pending"
			}
			if p.Status == "active" && s.HealthyAsset(p.Terms.Asset, at) {
				s.resolve(p, "survived", at)
			} else if at >= p.Expiry+s.Policy.VoidDelayMS {
				s.resolve(p, "voided", at)
			}
		}
	}
}
func (s *State) resolve(p *Stage, status string, at int64) {
	a := s.account(p.Terms.Account)
	p.Status = status
	p.Resolved = at
	switch status {
	case "survived":
		s.recordRisk(-(p.Terms.Payout - p.Terms.Stake), at)
		if p.Terms.Product == SingleStage {
			a.Available += p.Funded
			a.Unfunded += p.Terms.Payout - p.Funded
			a.setHead(p.Terms.Asset, "")
		} else {
			a.EarnedFunded = p.Funded
			a.EarnedUnfunded = p.Terms.Payout - p.Funded
		}
	case "exploded":
		s.recordRisk(p.Terms.Stake, at)
		s.LossClearing += p.Funded
		a.setHead(p.Terms.Asset, "")
	case "voided":
		a.Available += p.Funded
		a.Unfunded += p.Debt
		a.setHead(p.Terms.Asset, "")
	}
}
