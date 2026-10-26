// Package rewards builds bounded, reproducible mining manifests. Publication and
// claims remain onchain operations; producing a manifest never mints tokens.
package rewards

import (
	"bytes"
	"encoding/json"
	"fmt"
	"math/big"
	"sort"

	"fuse/engine/internal/contracts"
	"fuse/engine/internal/engine"
	"github.com/ethereum/go-ethereum/common"
	"github.com/ethereum/go-ethereum/crypto"
)

type Policy struct {
	Version                            string
	ExposureRule                       string `json:",omitempty"`
	ActivityRate                       string `json:",omitempty"`
	SurvivedWeightBPS, FailedWeightBPS uint64
	MaxStakeUSDC                       int64
	StreakBonusBPS                     [8]uint64
	MaxBonusBPS                        uint64
}
type Allocation struct {
	Index   uint64         `json:"index"`
	Account common.Address `json:"account"`
	Amount  string         `json:"amount"`
	Leaf    common.Hash    `json:"leaf"`
	Proof   []common.Hash  `json:"proof"`
}
type StageScore struct {
	Stage            string `json:"stage"`
	Account          string `json:"account"`
	OutcomeSequence  uint64 `json:"outcome_sequence"`
	Stake            int64  `json:"stake_usdc_units"`
	DurationMS       int64  `json:"at_risk_duration_ms"`
	Payout           int64  `json:"committed_payout_usdc_units"`
	DifficultyPolicy string `json:"difficulty_policy"`
	Outcome          string `json:"outcome"`
	Score            string `json:"score"`
}
type Manifest struct {
	TotalScore      string       `json:"total_score,omitempty"`
	ActivityBudget  string       `json:"activity_budget,omitempty"`
	RequestedBudget string       `json:"requested_budget,omitempty"`
	PolicyHash      string       `json:"policy_hash,omitempty"`
	Policy          *Policy      `json:"policy,omitempty"`
	Stages          []StageScore `json:"stages,omitempty"`
	Epoch           uint64       `json:"epoch"`
	From, To        uint64
	PolicyVersion   string
	JournalHash     string
	Budget          string
	Allocated       string
	Root            common.Hash
	Allocations     []Allocation
}

// Build scores only first final outcomes committed in a contiguous journal
// range ending at a finalized checkpoint. Voids and order submissions score zero.
func Build(events []engine.Event, from, to uint64, epoch uint64, budget *big.Int, chain *big.Int, distributor common.Address, policy Policy) (Manifest, error) {
	return build(events, from, to, epoch, budget, chain, distributor, policy, false)
}

func build(events []engine.Event, from, to uint64, epoch uint64, budget *big.Int, chain *big.Int, distributor common.Address, policy Policy, externalFinality bool) (Manifest, error) {
	out := Manifest{Epoch: epoch, From: from, To: to, PolicyVersion: policy.Version, Allocations: []Allocation{}}
	if from == 0 || to < from || epoch == 0 || budget == nil || budget.Sign() <= 0 || budget.BitLen() > 256 || chain == nil || chain.Sign() <= 0 || chain.BitLen() > 256 || distributor == (common.Address{}) || policy.Version == "" || policy.MaxStakeUSDC <= 0 || policy.SurvivedWeightBPS == 0 || policy.SurvivedWeightBPS > 10_000 || policy.FailedWeightBPS > 10_000 || policy.MaxBonusBPS > 10_000 {
		return out, fmt.Errorf("invalid reward policy/budget")
	}
	for _, b := range policy.StreakBonusBPS {
		if b > policy.MaxBonusBPS {
			return out, fmt.Errorf("unbounded streak bonus")
		}
	}
	scores := map[string]*big.Int{}
	seen := map[string]bool{}
	expected := from
	finalized := externalFinality
	for _, e := range events {
		if e.Sequence > to {
			continue
		}
		if e.Sequence < from {
			// A later funding notice can mention an already-finalized stage. Seed
			// deduplication from the whole preceding journal, not just this epoch.
			for _, raw := range e.Notices {
				var notice struct {
					Stages []engine.Stage `json:"stages"`
				}
				if err := json.Unmarshal(raw, &notice); err != nil {
					return out, err
				}
				for _, p := range notice.Stages {
					if p.Status == "survived" || p.Status == "exploded" {
						seen[p.ID] = true
					}
				}
			}
			continue
		}
		if e.Sequence != expected {
			return out, fmt.Errorf("noncontiguous journal")
		}
		expected++
		if e.Sequence == to {
			var checkpoint engine.Epoch
			if e.Command.Kind == "paper_settle" && json.Unmarshal(e.Result, &checkpoint) == nil && checkpoint.Status == "paper-confirmed" {
				finalized = true
			}
			out.JournalHash = e.Hash
		}
		// Outcome notices are durable sequencer projections. The caller must verify
		// full journal replay before using them as scoring evidence.
		for account, raw := range e.Notices {
			var notice struct {
				Stages []engine.Stage `json:"stages"`
			}
			if err := json.Unmarshal(raw, &notice); err != nil {
				return out, err
			}
			for _, p := range notice.Stages {
				if seen[p.ID] || (p.Status != "survived" && p.Status != "exploded") {
					continue
				}
				seen[p.ID] = true
				if !common.IsHexAddress(account) || p.Terms.Account != account || p.Terms.Index < 1 || p.Terms.Index > 8 || p.Resolved < p.Start {
					return out, fmt.Errorf("invalid rewarded stage")
				}
				stake := p.Terms.Stake
				if policy.ExposureRule != "linear-stake-time-v2" && stake > policy.MaxStakeUSDC {
					stake = policy.MaxStakeUSDC
				}
				duration := p.Resolved - p.Start
				if duration > p.Terms.DurationMS {
					duration = p.Terms.DurationMS
				}
				weight := policy.FailedWeightBPS
				if p.Status == "survived" {
					weight = policy.SurvivedWeightBPS
				}
				score := big.NewInt(stake)
				score.Mul(score, big.NewInt(duration))
				score.Mul(score, new(big.Int).SetUint64(weight))
				score.Mul(score, new(big.Int).SetUint64(10_000+policy.StreakBonusBPS[p.Terms.Index-1]))
				if scores[account] == nil {
					scores[account] = new(big.Int)
				}
				scores[account].Add(scores[account], score)
				if policy.ExposureRule == "linear-stake-time-v2" {
					out.Stages = append(out.Stages, StageScore{p.ID, account, e.Sequence, p.Terms.Stake, duration, p.Terms.Payout, p.Terms.PolicyVersion, p.Status, score.String()})
				}
			}
		}
	}
	if expected != to+1 || !finalized {
		return out, fmt.Errorf("range must end at a verified finalized checkpoint")
	}
	total := new(big.Int)
	accounts := []string{}
	for a, s := range scores {
		if s.Sign() > 0 {
			total.Add(total, s)
			accounts = append(accounts, a)
		}
	}
	sort.Strings(accounts)
	if total.Sign() == 0 {
		return out, fmt.Errorf("no eligible completed risk")
	}
	if policy.ExposureRule == "linear-stake-time-v2" {
		rate, ok := new(big.Int).SetString(policy.ActivityRate, 10)
		if !ok || rate.Sign() <= 0 || rate.BitLen() > 256 || policy.MaxBonusBPS != 0 {
			return out, fmt.Errorf("explicit linear activity budget and no streak bonus required")
		}
		for _, b := range policy.StreakBonusBPS {
			if b != 0 {
				return out, fmt.Errorf("V0 streak bonus disabled")
			}
		}
		eligible := new(big.Int).Mul(total, rate)
		// Score denominator is one USDC exposed for 30s with survival weight 1.0.
		eligible.Quo(eligible, big.NewInt(3_000_000_000_000_000_000))
		out.RequestedBudget = budget.String()
		out.ActivityBudget = eligible.String()
		out.TotalScore = total.String()
		out.PolicyHash = engine.Hash(policy)
		out.Policy = &policy
		budget = new(big.Int).Set(budget)
		if budget.Cmp(eligible) > 0 {
			budget.Set(eligible)
		}
		if budget.Sign() == 0 {
			return out, fmt.Errorf("activity budget rounds to zero")
		}
		sort.Slice(out.Stages, func(i, j int) bool {
			if out.Stages[i].OutcomeSequence != out.Stages[j].OutcomeSequence {
				return out.Stages[i].OutcomeSequence < out.Stages[j].OutcomeSequence
			}
			return out.Stages[i].Stage < out.Stages[j].Stage
		})
	} else if policy.ExposureRule != "" {
		return out, fmt.Errorf("unsupported exposure rule")
	}
	allocated := new(big.Int)
	for _, account := range accounts {
		amount := new(big.Int).Mul(budget, scores[account])
		amount.Quo(amount, total)
		if amount.Sign() == 0 {
			continue
		}
		index := uint64(len(out.Allocations))
		leaf, err := contracts.RewardLeaf(chain, distributor, epoch, new(big.Int).SetUint64(index), common.HexToAddress(account), amount)
		if err != nil {
			return out, err
		}
		out.Allocations = append(out.Allocations, Allocation{Index: index, Account: common.HexToAddress(account), Amount: amount.String(), Leaf: leaf})
		allocated.Add(allocated, amount)
	}
	if len(out.Allocations) == 0 {
		return out, fmt.Errorf("budget rounds all allocations to zero")
	}
	leaves := make([]common.Hash, len(out.Allocations))
	for i, a := range out.Allocations {
		leaves[i] = a.Leaf
	}
	root, proofs := Tree(leaves)
	out.Root = root
	for i := range out.Allocations {
		out.Allocations[i].Proof = proofs[i]
	}
	out.Budget = budget.String()
	out.Allocated = allocated.String()
	return out, nil
}

// Tree matches OpenZeppelin StandardMerkleTree: sorted leaves, a complete binary
// heap, sorted sibling pairs, and double-hashed ABI leaves supplied by the caller.
func Tree(leaves []common.Hash) (common.Hash, [][]common.Hash) {
	if len(leaves) == 0 {
		return common.Hash{}, nil
	}
	type indexed struct {
		hash  common.Hash
		index int
	}
	sorted := make([]indexed, len(leaves))
	for i, h := range leaves {
		sorted[i] = indexed{h, i}
	}
	sort.Slice(sorted, func(i, j int) bool { return bytes.Compare(sorted[i].hash[:], sorted[j].hash[:]) < 0 })
	tree := make([]common.Hash, 2*len(leaves)-1)
	indices := make([]int, len(leaves))
	for i, l := range sorted {
		j := len(tree) - 1 - i
		tree[j] = l.hash
		indices[l.index] = j
	}
	for i := len(tree) - 1 - len(leaves); i >= 0; i-- {
		tree[i] = pair(tree[2*i+1], tree[2*i+2])
	}
	proofs := make([][]common.Hash, len(leaves))
	for i, idx := range indices {
		proofs[i] = []common.Hash{}
		for idx > 0 {
			sibling := idx - 1
			if idx%2 == 1 {
				sibling = idx + 1
			}
			proofs[i] = append(proofs[i], tree[sibling])
			idx = (idx - 1) / 2
		}
	}
	return tree[0], proofs
}
func pair(a, b common.Hash) common.Hash {
	if bytes.Compare(a[:], b[:]) > 0 {
		a, b = b, a
	}
	return crypto.Keccak256Hash(a[:], b[:])
}
func Verify(leaf common.Hash, proof []common.Hash, root common.Hash) bool {
	for _, sibling := range proof {
		leaf = pair(leaf, sibling)
	}
	return leaf == root
}

// EmissionCap applies independent fixed-interval decay; unused caps never carry.
func EmissionCap(initial *big.Int, decayBPS uint64, epoch uint64) (*big.Int, error) {
	if initial == nil || initial.Sign() < 0 || initial.BitLen() > 256 || decayBPS == 0 || decayBPS >= 10_000 || epoch == 0 || epoch > 1_000_000 {
		return nil, fmt.Errorf("invalid emission schedule")
	}
	cap := new(big.Int).Set(initial)
	for i := uint64(1); i < epoch && cap.Sign() > 0; i++ {
		cap.Mul(cap, new(big.Int).SetUint64(10_000-decayBPS))
		cap.Quo(cap, big.NewInt(10_000))
	}
	return cap, nil
}

// ReserveContribution follows LPVault's current-profit/consumed-HWM policy and
// excludes all reserved underwriting capital. allocationBPS is a reviewed input.
func ReserveContribution(profit, consumed, lp, required int64, allocationBPS int64) (amount, consumedIncrement int64, err error) {
	if profit < 0 || consumed < 0 || lp < 0 || required < 0 || allocationBPS <= 0 || allocationBPS > 5000 {
		return 0, 0, fmt.Errorf("invalid reserve policy")
	}
	if profit <= consumed || lp <= required {
		return 0, 0, nil
	}
	amount, err = engine.MulDiv(profit-consumed, allocationBPS, 10_000)
	if err != nil {
		return
	}
	if amount > lp-required {
		amount = lp - required
	}
	v := new(big.Int).Mul(big.NewInt(amount), big.NewInt(10_000))
	v.Add(v, big.NewInt(allocationBPS-1))
	v.Quo(v, big.NewInt(allocationBPS))
	if !v.IsInt64() {
		return 0, 0, fmt.Errorf("reserve overflow")
	}
	return amount, v.Int64(), nil
}

// BuildForCheckpoint accepts the exact journal range supported by a confirmed
// contract checkpoint in the fully replayed local state.
func BuildForCheckpoint(events []engine.Event, state engine.State, from, epoch uint64, budget, chain *big.Int, distributor common.Address, policy Policy) (Manifest, error) {
	if state.Local == nil || len(state.Epochs) == 0 {
		return Manifest{}, fmt.Errorf("no finalized contract checkpoint")
	}
	checkpoint := state.Epochs[len(state.Epochs)-1]
	if checkpoint.Status != "onchain-confirmed" {
		return Manifest{}, fmt.Errorf("checkpoint not confirmed onchain")
	}
	return build(events, from, checkpoint.To, epoch, budget, chain, distributor, policy, true)
}

// ReserveContributionV2 is the tokenomics candidate: recovery to historical HWM,
// an equity/capital allocation ramp, and a post-transfer 2x capital floor.
func ReserveContributionV2(profit, hwm, consumed, equity, capital, capBPS int64) (amount, consumedIncrement, effectiveBPS int64, err error) {
	if profit < 0 || hwm < 0 || consumed < 0 || equity < 0 || equity > engine.Limit || capital < 0 || capital > engine.Limit || capBPS < 0 || capBPS > 5000 {
		err = fmt.Errorf("invalid reserve v2 policy")
		return
	}
	if profit < hwm || profit <= consumed || capital > equity/2 || capBPS == 0 {
		return
	}
	effectiveBPS = capBPS
	if capital > 0 && capital > equity/3 {
		var scaled int64
		scaled, err = engine.MulDiv(capBPS*2, equity-capital, capital)
		if err != nil {
			return
		}
		effectiveBPS = (scaled - capBPS) / 3
	}
	if effectiveBPS == 0 {
		return
	}
	amount, err = engine.MulDiv(profit-consumed, effectiveBPS, 10000)
	if err != nil {
		return
	}
	amount = min(amount, equity-2*capital)
	v := new(big.Int).Mul(big.NewInt(amount), big.NewInt(10000))
	v.Add(v, big.NewInt(effectiveBPS-1))
	v.Quo(v, big.NewInt(effectiveBPS))
	if !v.IsInt64() {
		err = fmt.Errorf("reserve overflow")
		return
	}
	consumedIncrement = v.Int64()
	return
}
