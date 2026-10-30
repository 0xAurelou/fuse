package engine

import "fmt"

// SettlementOutcome exports the existing oracle/reducer decision. It neither
// prices nor resolves a bet a second time, moves money, or signs an attestation.
// Millisecond canonical time is distinct from the reducer's processing time.
type SettlementOutcome struct {
	Rule             string `json:"rule"`
	StageID          string `json:"stage_id"`
	Account          string `json:"account"`
	Asset            string `json:"asset"`
	Outcome          uint8  `json:"outcome"`
	CanonicalMS      int64  `json:"canonical_ms"`
	ObservedMS       int64  `json:"observed_ms"`
	Stake            int64  `json:"stake_usdc_units"`
	Payout           int64  `json:"payout_usdc_units"`
	LPPnL            int64  `json:"lp_pnl_usdc_units"`
	AcceptedSequence uint64 `json:"accepted_sequence"`
	StageCommitment  string `json:"stage_commitment"`
	JournalHash      string `json:"journal_hash"`
	OracleCommitment string `json:"oracle_commitment"`
}

// SettlementOutcome is shared by papertrade evidence and production adapters.
// A production adapter must additionally verify the accepted onchain ticket
// binding, replay the committed journal and obtain both authorized signatures.
// No state fields/encodings change, preserving existing replay commitments.
func (s State) SettlementOutcome(id string) (SettlementOutcome, error) {
	p := s.Stages[id]
	if p == nil || p.Terms.Product != SingleStage || p.Start <= 0 || p.Expiry <= p.Start ||
		p.Expiry-p.Start != 30_000 || p.Terms.Stake <= 0 || p.Terms.Payout <= p.Terms.Stake ||
		p.Funded != p.Terms.Stake || p.Debt != 0 || p.AcceptedSequence == 0 ||
		p.Terms.MaxLPLiability != p.Terms.Payout-p.Terms.Stake || p.Resolved < p.Start ||
		s.JournalHash == "" {
		return SettlementOutcome{}, fmt.Errorf("no exportable custody-funded single-stage outcome")
	}
	canonical, payout, outcome := p.Resolved, int64(0), uint8(0)
	switch p.Status {
	case "survived":
		if p.Resolved < p.Expiry {
			return SettlementOutcome{}, fmt.Errorf("survival before expiry")
		}
		canonical, payout, outcome = p.Expiry, p.Terms.Payout, 2
	case "exploded":
		if p.Resolved >= p.Expiry {
			return SettlementOutcome{}, fmt.Errorf("barrier hit outside accepted interval")
		}
		outcome = 3
	case "voided":
		if p.Resolved < p.Expiry {
			return SettlementOutcome{}, fmt.Errorf("void before expiry")
		}
		payout, outcome = p.Terms.Stake, 4
	default:
		return SettlementOutcome{}, fmt.Errorf("stage has no final outcome")
	}
	commitment := p.AcceptanceCommitment()
	return SettlementOutcome{Rule: "shared-engine-outcome-v1", StageID: p.ID,
		Account: p.Terms.Account, Asset: AssetName(p.Terms.Asset), Outcome: outcome,
		CanonicalMS: canonical, ObservedMS: p.Resolved, Stake: p.Terms.Stake,
		Payout: payout, LPPnL: p.Terms.Stake - payout, AcceptedSequence: p.AcceptedSequence,
		StageCommitment: commitment, JournalHash: s.JournalHash, OracleCommitment: s.OracleCommitment()}, nil
}

// AcceptanceCommitment excludes later outcome/funding fields. Chain bindings
// use the same commitment as the shared outcome exporter.
func (p Stage) AcceptanceCommitment() string {
	return Hash(struct {
		ID               string
		AcceptedSequence uint64
		Terms            Quote
		Start, Expiry    int64
	}{p.ID, p.AcceptedSequence, p.Terms, p.Start, p.Expiry})
}
