// Package engine implements a deterministic, single-writer trading reducer. Signing keys live outside this package.
package engine

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"math/big"
	"slices"
	"sort"
)

const Limit int64 = 1_000_000_000_000_000 // Aggregate USDC/price safety envelope, below int64.
const Scale int64 = 1_000_000_000
const SingleStage = "single-stage-v1"
const MinMultiplier int64 = 2
const MaxMultiplier int64 = 10_000
const legacyMaxMultiplier int64 = 100

// PayoutOptions is the discrete selection offered by current desks.
func PayoutOptions() []int64 { return []int64{2, 5, 10, 25, 50, 100, 250, 1000, 10000} }

// MultiplierOptions preserves the frozen selection rules of pre-preset journals.
func (p Policy) MultiplierOptions() []int64 {
	if len(p.Multipliers) > 0 {
		return slices.Clone(p.Multipliers)
	}
	values := make([]int64, legacyMaxMultiplier-MinMultiplier+1)
	for i := range values {
		values[i] = MinMultiplier + int64(i)
	}
	return values
}

var ErrRejected = errors.New("command rejected")

func reject(s string) error { return fmt.Errorf("%w: %s", ErrRejected, s) }

// All time fields are Unix milliseconds; all USDC fields are atomic units.
// Paper policies must be explicit. No real-money policy is inferred from this configuration.
type Policy struct {
	Multipliers        []int64          `json:"multipliers,omitempty"`
	Markets            map[string]Model `json:"markets,omitempty"`
	Product            string           `json:"product,omitempty"`
	Recovery           *RecoveryPolicy  `json:"recovery,omitempty"`
	Capital            *CapitalLimits   `json:"capital,omitempty"`
	Version            string           `json:"version"`
	Mode               string           `json:"mode"`
	Schedule           string           `json:"schedule"`
	Admission          string           `json:"admission"`
	GapRule            string           `json:"gap_rule"`
	DurationMS         int64            `json:"duration_ms"`
	QuoteTTLMS         int64            `json:"quote_ttl_ms"`
	MaxGapMS           int64            `json:"max_gap_ms"`
	DisagreementMS     int64            `json:"disagreement_ms"`
	VoidDelayMS        int64            `json:"void_delay_ms"`
	MinStake           int64            `json:"min_stake"`
	MaxStake           int64            `json:"max_stake"`
	LPBuffer           int64            `json:"lp_buffer"`
	MaxExposure        int64            `json:"max_exposure"`
	MaxAccountExposure int64            `json:"max_account_exposure"`
	MaxActive          int              `json:"max_active"`
	PayoutTable        [9]int64         `json:"payout_table,omitzero"`
	Model              Model            `json:"model"`
}
type Model struct {
	DNT                 *DNTModel       `json:"dnt,omitempty"`
	MultiplierWidthsPPM map[int64]int64 `json:"multiplier_widths_ppm,omitempty"`
	// Explicit PPB tables support a validated subset of current presets. The
	// omitted field preserves historical policy and journal encodings.
	MultiplierWidthsPPB map[int64]int64 `json:"multiplier_widths_ppb,omitempty"`
	Version             string          `json:"version"`
	Dataset             string          `json:"dataset"`
	TrainingWindow      string          `json:"training_window"`
	OutOfSampleError    string          `json:"out_of_sample_error"`
	ValidUntil          int64           `json:"valid_until"`
	BaseWidthBPS        int64           `json:"base_width_bps"`
	BaseWidthPPM        int64           `json:"base_width_ppm,omitempty"`
	MaxWidthBPS         int64           `json:"max_width_bps"`
	ControlWidthBPS     int64           `json:"control_width_bps"`
	MaxDriftBPS         int64           `json:"max_drift_bps"`
	VolatilityFactor    int64           `json:"volatility_factor"`
}

func (p Policy) Validate() error {
	ppb := len(p.Model.MultiplierWidthsPPB) > 0
	if ppb && (p.Product != SingleStage || len(p.Multipliers) == 0) {
		return errors.New("PPB pricing requires an explicit single-stage preset menu")
	}
	if ppb {
		previous := int64(0)
		for _, multiplier := range p.Multipliers {
			if multiplier <= previous || !slices.Contains(PayoutOptions(), multiplier) {
				return errors.New("PPB pricing presets must be unique, increasing supported payouts")
			}
			previous = multiplier
		}
	}
	if p.Multipliers != nil && (p.Product != SingleStage || (!ppb && !slices.Equal(p.Multipliers, PayoutOptions()))) {
		return errors.New("single-stage multipliers must be 2, 5, 10, 25, 50, 100, 250, 1000 and 10000")
	}
	for asset, model := range p.Markets {
		if p.Product != SingleStage || !SupportedAsset(asset) || asset == "BTC" {
			return errors.New("unsupported additional market")
		}
		if ppb != (len(model.MultiplierWidthsPPB) > 0) {
			return errors.New("PPB pricing requires the explicit table format in every enabled market")
		}
		copy := p
		copy.Markets = nil
		copy.Capital = nil // Validate the aggregate capital policy on the outer policy only.
		copy.Model = model
		if err := copy.Validate(); err != nil {
			return fmt.Errorf("%s model: %w", asset, err)
		}
	}
	if p.Product != "" && p.Product != SingleStage {
		return errors.New("unsupported product")
	}
	if p.Recovery != nil {
		if err := p.Recovery.Validate(); err != nil {
			return err
		}
	}
	if p.Mode != "paper" && p.Mode != "local" {
		return errors.New("only paper and local Anvil modes are supported; public-chain execution is disabled")
	}
	if p.Version == "" || p.Schedule != "independent" || p.Admission != "paired-local-receipt-v1" || p.GapRule != "pending-then-refund-v1" || p.DurationMS != 30_000 {
		return errors.New("unsupported or missing protocol policy")
	}
	if p.QuoteTTLMS <= 0 || p.QuoteTTLMS > 30_000 || p.MaxGapMS <= 0 || p.MaxGapMS > 30_000 || p.DisagreementMS <= 0 || p.DisagreementMS > p.MaxGapMS || p.VoidDelayMS < 0 || p.VoidDelayMS > 3_600_000 {
		return errors.New("invalid timing policy")
	}
	if p.MinStake <= 0 || p.MaxStake < p.MinStake || p.MaxStake > Limit/100 || p.LPBuffer < 0 || p.LPBuffer > Limit || p.MaxExposure <= 0 || p.MaxExposure > Limit || p.MaxAccountExposure <= 0 || p.MaxAccountExposure > p.MaxExposure || p.MaxActive <= 0 || p.MaxActive > 10_000 {
		return errors.New("invalid risk policy")
	}
	if p.Capital != nil {
		if err := p.Capital.validate(p); err != nil {
			return err
		}
	}
	if p.Product == "" && (p.PayoutTable[0] != Scale || p.PayoutTable[8] != 100*Scale) {
		return errors.New("payout table must start at 1x and end at 100x")
	}
	for i := 1; p.Product == "" && i < 9; i++ {
		if p.PayoutTable[i] <= p.PayoutTable[i-1] || p.PayoutTable[i] > 100*Scale {
			return errors.New("non-increasing payout table")
		}
	}
	m := p.Model
	if len(m.MultiplierWidthsPPB) > 0 && (m.DNT != nil || len(m.MultiplierWidthsPPM) > 0) {
		return errors.New("select exactly one pricing formula or width table")
	}
	widthValid := m.validWidth()
	if p.Product == SingleStage {
		widthValid = m.MaxWidthBPS > 0 && m.MaxWidthBPS < 10_000
		if m.DNT != nil {
			if len(m.MultiplierWidthsPPM) != 0 {
				return errors.New("select formula or historical width table, not both")
			}
			width, err := m.DNT.WidthPPB(MinMultiplier)
			if err != nil || width <= 0 || width > m.MaxWidthBPS*100_000 {
				return errors.New("invalid or out-of-bounds Brownian pricing")
			}
		} else if ppb {
			if len(m.MultiplierWidthsPPB) != len(p.Multipliers) {
				return errors.New("PPB pricing requires exactly the configured payouts")
			}
			previous := int64(1_000_000_000)
			for _, multiplier := range p.Multipliers {
				width := m.MultiplierWidthsPPB[multiplier]
				if width <= 0 || width >= previous || width > m.MaxWidthBPS*100_000 {
					return errors.New("PPB corridors must be positive, bounded and strictly narrower at higher payouts")
				}
				previous = width
			}
		} else {
			if len(m.MultiplierWidthsPPM) != len(p.MultiplierOptions()) {
				return errors.New("single-stage pricing requires every configured multiplier")
			}
			previous := int64(1_000_000)
			for _, multiplier := range p.MultiplierOptions() {
				width := m.MultiplierWidthsPPM[multiplier]
				if width <= 0 || width >= previous || width > m.MaxWidthBPS*100 {
					return errors.New("multiplier corridors must be positive, bounded and strictly narrower at higher payouts")
				}
				previous = width
			}
		}
	}
	if m.Version == "" || m.Dataset == "" || m.TrainingWindow == "" || m.OutOfSampleError == "" || m.ValidUntil <= 0 || !widthValid || m.MaxDriftBPS < 0 || m.MaxDriftBPS >= 10_000 || m.VolatilityFactor < 0 || m.VolatilityFactor > 100 {
		return errors.New("invalid/unavailable pricing policy")
	}
	return nil
}

// Fractional research widths use one ppm = 0.01 bps. Omitted zero fields keep
// legacy policy encodings and journal replay unchanged.
func (m Model) validWidth() bool {
	if m.MaxWidthBPS <= 0 || m.MaxWidthBPS >= 10000 {
		return false
	}
	if m.BaseWidthPPM > 0 {
		return m.BaseWidthBPS == 0 && m.ControlWidthBPS == 0 && m.VolatilityFactor == 0 && m.BaseWidthPPM <= m.MaxWidthBPS*100
	}
	return m.BaseWidthPPM == 0 && m.BaseWidthBPS > 0 && m.BaseWidthBPS <= m.MaxWidthBPS && m.ControlWidthBPS > 0
}
func MulDiv(a, b, d int64) (int64, error) {
	if a < 0 || b < 0 || d <= 0 {
		return 0, errors.New("invalid unsigned arithmetic")
	}
	v := new(big.Int).Mul(big.NewInt(a), big.NewInt(b))
	v.Quo(v, big.NewInt(d))
	if !v.IsInt64() || v.Int64() > Limit {
		return 0, errors.New("arithmetic limit exceeded")
	}
	return v.Int64(), nil
}
func Hash(v any) string {
	b, err := json.Marshal(v)
	if err != nil {
		panic(err)
	}
	h := sha256.Sum256(b)
	return hex.EncodeToString(h[:])
}
func clone[T any](v T) T {
	b, _ := json.Marshal(v)
	var out T
	if err := json.Unmarshal(b, &out); err != nil {
		panic(err)
	}
	return out
}
func keys[T any](m map[string]T) []string {
	out := make([]string, 0, len(m))
	for k := range m {
		out = append(out, k)
	}
	sort.Strings(out)
	return out
}

type Account struct {
	StageHeads         map[string]string `json:"stage_heads,omitempty"`
	Available          int64             `json:"available"`
	Unfunded           int64             `json:"unfunded"`
	EarnedFunded       int64             `json:"earned_funded"`
	EarnedUnfunded     int64             `json:"earned_unfunded"`
	WithdrawalFunded   int64             `json:"withdrawal_funded"`
	WithdrawalUnfunded int64             `json:"withdrawal_unfunded"`
	Withdrawn          int64             `json:"withdrawn"`
	RunHead            string            `json:"run_head,omitempty"`
	Withdrawal         string            `json:"withdrawal,omitempty"`
}
type Feed struct {
	Price   int64  `json:"price"`
	At      int64  `json:"at"`
	RawHash string `json:"raw_hash"`
}
type Oracle struct {
	Sources       map[string]Feed `json:"sources"`
	Price         int64           `json:"price"`
	At            int64           `json:"at"`
	Sequence      uint64          `json:"sequence"`
	MismatchSince int64           `json:"mismatch_since"`
	JournalHash   string          `json:"journal_hash"`
	ReturnsBPS    []int64         `json:"returns_bps"`
}
type Quote struct {
	PricingRule       string `json:"pricing_rule,omitempty"`
	VolatilityPPM     int64  `json:"volatility_30s_ppm,omitempty"`
	HouseEdgeBPS      int64  `json:"house_edge_bps,omitempty"`
	TargetSurvivalPPB int64  `json:"target_survival_ppb,omitempty"`
	WidthPPB          int64  `json:"width_ppb,omitempty"`
	Product           string `json:"product,omitempty"`
	Multiplier        int64  `json:"multiplier,omitempty"`
	ID                string `json:"id"`
	Account           string `json:"account"`
	Asset             string `json:"asset"`
	Previous          string `json:"previous,omitempty"`
	Index             int    `json:"index"`
	Initial           int64  `json:"initial"`
	Stake             int64  `json:"stake"`
	Payout            int64  `json:"payout"`
	Price             int64  `json:"entry_price"`
	Lower             int64  `json:"lower"`
	Upper             int64  `json:"upper"`
	Issued            int64  `json:"issued"`
	ValidUntil        int64  `json:"valid_until"`
	DurationMS        int64  `json:"duration_ms"`
	OracleSequence    uint64 `json:"oracle_sequence"`
	MaxLPLiability    int64  `json:"max_lp_liability"`
	PolicyVersion     string `json:"policy_version"`
	ModelVersion      string `json:"model_version"`
	Admission         string `json:"admission"`
	GapRule           string `json:"gap_rule"`
	Window            string `json:"window"`
}
type Stage struct {
	AcceptedSequence uint64 `json:"accepted_sequence"`
	ResolvedSequence uint64 `json:"resolved_sequence,omitempty"`
	ID               string `json:"id"`
	Terms            Quote  `json:"terms"`
	Start            int64  `json:"start"`
	Expiry           int64  `json:"expiry"`
	Status           string `json:"status"`
	Resolved         int64  `json:"resolved,omitempty"`
	Funded           int64  `json:"funded"`
	Debt             int64  `json:"debt"`
	BreachSequence   uint64 `json:"breach_sequence,omitempty"`
}
type Deposit struct {
	ID      string `json:"id"`
	Account string `json:"account"`
	Amount  int64  `json:"amount"`
	Status  string `json:"status"`
}
type Withdrawal struct {
	ID         string `json:"id"`
	Account    string `json:"account"`
	Recipient  string `json:"recipient"`
	Amount     int64  `json:"amount"`
	Cumulative int64  `json:"cumulative"`
	Status     string `json:"status"`
	Epoch      uint64 `json:"epoch"`
	StateHash  string `json:"state_hash,omitempty"`
}
type Epoch struct {
	Number       uint64 `json:"number"`
	From         uint64 `json:"from"`
	To           uint64 `json:"to"`
	PriorRoot    string `json:"prior_root"`
	Root         string `json:"root"`
	JournalHash  string `json:"journal_hash"`
	OracleHash   string `json:"oracle_hash"`
	NetTraderPnL int64  `json:"net_trader_pnl"`
	Liability    int64  `json:"customer_liability"`
	Exposure     int64  `json:"exposure"`
	RequiredLP   int64  `json:"required_lp"`
	Status       string `json:"status"`
}
type State struct {
	Oracles        map[string]*Oracle     `json:"oracles,omitempty"`
	Recovery       *RecoveryState         `json:"recovery,omitempty"`
	Local          *LocalState            `json:"local,omitempty"`
	Capital        *CapitalState          `json:"capital,omitempty"`
	PolicyHistory  map[string]Policy      `json:"policy_history"`
	Policy         Policy                 `json:"policy"`
	Sequence       uint64                 `json:"sequence"`
	At             int64                  `json:"at"`
	JournalHash    string                 `json:"journal_hash"`
	Accounts       map[string]*Account    `json:"accounts"`
	Quotes         map[string]Quote       `json:"quotes"`
	Stages         map[string]*Stage      `json:"stages"`
	Deposits       map[string]*Deposit    `json:"deposits"`
	Withdrawals    map[string]*Withdrawal `json:"withdrawals"`
	Epochs         []Epoch                `json:"epochs"`
	Oracle         Oracle                 `json:"oracle"`
	Custody        int64                  `json:"custody"`
	LP             int64                  `json:"lp"`
	Reserve        int64                  `json:"reserve"`
	LossClearing   int64                  `json:"loss_clearing"`
	LPProfit       int64                  `json:"lp_profit"`
	ProfitHWM      int64                  `json:"profit_hwm"`
	ConsumedProfit int64                  `json:"consumed_profit"`
	Paused         bool                   `json:"paused"`
}

func NewState(p Policy) (State, error) {
	if err := p.Validate(); err != nil {
		return State{}, err
	}
	// Pointer-valued optional policies must not alias caller-owned configuration.
	p = clone(p)
	s := State{Policy: p, PolicyHistory: map[string]Policy{p.Version: p}, Accounts: map[string]*Account{}, Quotes: map[string]Quote{}, Stages: map[string]*Stage{}, Deposits: map[string]*Deposit{}, Withdrawals: map[string]*Withdrawal{}, Epochs: []Epoch{}, Oracle: Oracle{Sources: map[string]Feed{}, ReturnsBPS: []int64{}}}
	if p.Recovery != nil {
		s.Recovery = &RecoveryState{Mode: "open", Losses: []RiskLoss{}}
	}
	if p.Capital != nil {
		s.Capital = &CapitalState{UnfundedByMarket: map[string]int64{}}
	}
	return s, nil
}

// Command actor is supplied by the authenticated gateway, never taken from a public request body.
type Command struct {
	Asset      string          `json:"asset,omitempty"`
	Multiplier int64           `json:"multiplier,omitempty"`
	Key        string          `json:"key"`
	Kind       string          `json:"kind"`
	Actor      string          `json:"actor,omitempty"`
	At         int64           `json:"at"`
	ID         string          `json:"id,omitempty"`
	Previous   string          `json:"previous,omitempty"`
	Amount     int64           `json:"amount,omitempty"`
	Source     string          `json:"source,omitempty"`
	Raw        json.RawMessage `json:"raw,omitempty"`
}

func (c Command) Identity() string { c.At = 0; return Hash(c) }

type Posting struct {
	Account string `json:"account"`
	Asset   string `json:"asset"`
	Delta   int64  `json:"delta"`
}
type Event struct {
	Sequence     uint64                     `json:"sequence"`
	PreviousHash string                     `json:"previous_hash"`
	Hash         string                     `json:"hash"`
	StateHash    string                     `json:"state_hash"`
	Command      Command                    `json:"command"`
	Result       json.RawMessage            `json:"result"`
	Postings     []Posting                  `json:"postings"`
	Notices      map[string]json.RawMessage `json:"notices"`
}

func eventHash(e Event) string { e.Hash = ""; return Hash(e) }

// JournalHash is excluded to avoid a cycle between the state and event commitments.
func (s State) Digest() string { s.JournalHash = ""; return Hash(s) }
func (s *State) account(id string) *Account {
	a := s.Accounts[id]
	if a == nil {
		a = &Account{}
		s.Accounts[id] = a
	}
	return a
}
