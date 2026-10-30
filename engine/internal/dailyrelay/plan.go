package dailyrelay

import (
	"context"
	"encoding/json"
	"fmt"
	"math/big"
	"sort"

	"fuse/engine/internal/contracts"
	"github.com/ethereum/go-ethereum/common"
	"github.com/ethereum/go-ethereum/crypto"
)

type Action struct {
	Kind          string                   `json:"kind"` // batch, queue_void, complete_void, await_close, await_time, reconcile
	Tickets       []common.Hash            `json:"tickets"`
	Outcomes      []contracts.DailyOutcome `json:"outcomes,omitempty"`
	Deadline      uint64                   `json:"deadline,omitempty"`
	Digest        common.Hash              `json:"digest,omitempty"`
	OnchainDigest common.Hash              `json:"onchain_digest,omitempty"`
}
type Plan struct {
	ChainID     uint64         `json:"chain_id"`
	Custody     common.Address `json:"custody"`
	Block       uint64         `json:"verified_block"`
	BlockHash   common.Hash    `json:"verified_block_hash"`
	Generation  string         `json:"signature_version"`
	JournalHash common.Hash    `json:"journal_hash"`
	Deadline    uint64         `json:"deadline"`
	Actions     []Action       `json:"actions"`
	source      *Journal
	bindings    []Binding
	seal        common.Hash
}

func (p Plan) hash() common.Hash { raw, _ := json.Marshal(p); return crypto.Keccak256Hash(raw) }
func equalAction(a, b Action) bool {
	x, _ := json.Marshal(a)
	y, _ := json.Marshal(b)
	return string(x) == string(y)
}

// Plan revalidates every persisted binding at one confirmed block. Resolved
// storage flags request receipt reconciliation; they never prove a payment.
func (r *Reader) Plan(ctx context.Context, j *Journal, bindings []Binding, deadline uint64) (*Plan, error) {
	if len(bindings) == 0 || len(bindings) > 1024 || j == nil {
		return nil, fmt.Errorf("daily plan needs verified journal and 1..1024 bindings")
	}
	s, err := r.Snapshot(ctx)
	if err != nil {
		return nil, err
	}
	if deadline <= s.Time || deadline-s.Time > 600 {
		return nil, fmt.Errorf("daily authorization deadline must be within ten minutes")
	}
	journal := common.HexToHash(j.state.JournalHash)
	p := &Plan{ChainID: r.manifest.ChainID, Custody: r.manifest.Modules["DailyBetCustody"].Address, Block: s.Number, BlockHash: s.Hash, Generation: s.Generation.String(), JournalHash: journal, Deadline: deadline, source: j, bindings: append([]Binding{}, bindings...)}
	sorted := append([]Binding{}, bindings...)
	sort.Slice(sorted, func(i, k int) bool { return sorted[i].StageID < sorted[k].StageID })
	seenTickets := map[common.Hash]bool{}
	seenStages := map[string]bool{}
	batch := []contracts.DailyOutcome{}
	flush := func() error {
		if len(batch) == 0 {
			return nil
		}
		local, err := contracts.DailyBatchDigest(new(big.Int).SetUint64(p.ChainID), p.Custody, batch, journal, deadline, s.Generation)
		if err != nil {
			return err
		}
		remote, err := r.one(ctx, s, "DailyBetCustody", "hashBatch", batch, journal, deadline)
		if err != nil {
			return err
		}
		if remote.([32]byte) != local {
			return fmt.Errorf("daily batch contract digest mismatch")
		}
		ids := make([]common.Hash, len(batch))
		for i, o := range batch {
			ids[i] = o.Id
		}
		p.Actions = append(p.Actions, Action{Kind: "batch", Tickets: ids, Outcomes: append([]contracts.DailyOutcome{}, batch...), Deadline: deadline, Digest: local, OnchainDigest: remote.([32]byte)})
		batch = nil
		return nil
	}
	for _, b := range sorted {
		if seenTickets[b.TicketID] || seenStages[b.StageID] {
			return nil, fmt.Errorf("duplicate daily ticket/stage in plan")
		}
		seenTickets[b.TicketID] = true
		seenStages[b.StageID] = true
		current, err := r.bind(ctx, s, j, b.StageID, b.TicketID, b.TxHash, b.Generation)
		if err != nil {
			return nil, err
		}
		if current.identityHash() != b.identityHash() {
			return nil, fmt.Errorf("persisted daily acceptance binding changed")
		}
		native, err := j.Outcome(b.StageID)
		if err != nil {
			return nil, err
		}
		t, bv, err := r.views(ctx, s, b.TicketID)
		if err != nil {
			return nil, err
		}
		if t.Resolved {
			if bv.Status != native.Outcome {
				return nil, fmt.Errorf("onchain/native final outcome conflict")
			}
			if err = flush(); err != nil {
				return nil, err
			}
			p.Actions = append(p.Actions, Action{Kind: "reconcile", Tickets: []common.Hash{b.TicketID}})
			continue
		}
		canonical := uint64(native.CanonicalMS)
		if native.CanonicalMS > int64(s.Time)*1000 || native.ObservedMS > int64(s.Time)*1000 {
			if err = flush(); err != nil {
				return nil, err
			}
			p.Actions = append(p.Actions, Action{Kind: "await_time", Tickets: []common.Hash{b.TicketID}})
			continue
		}
		if native.CanonicalMS <= 0 || canonical/86_400_000 < s.Day {
			return nil, fmt.Errorf("native outcome contradicts a closed daily period")
		}
		if t.FinalVoidAt != 0 {
			if native.Outcome != 4 || t.FinalVoidAt != canonical {
				return nil, fmt.Errorf("queued/native void conflict")
			}
			if err = flush(); err != nil {
				return nil, err
			}
			kind := "await_close"
			if canonical/86_400_000 == s.Day {
				kind = "complete_void"
			}
			p.Actions = append(p.Actions, Action{Kind: kind, Tickets: []common.Hash{b.TicketID}})
			continue
		}
		evidenceRaw, _ := json.Marshal(struct {
			Binding Binding
			Outcome any
		}{b, native})
		o := contracts.DailyOutcome{Id: b.TicketID, Outcome: native.Outcome, CanonicalTime: canonical, EvidenceHash: crypto.Keccak256Hash(evidenceRaw), Deadline: deadline}
		if canonical/86_400_000 > s.Day {
			if err = flush(); err != nil {
				return nil, err
			}
			if native.Outcome != 4 {
				p.Actions = append(p.Actions, Action{Kind: "await_close", Tickets: []common.Hash{b.TicketID}})
				continue
			}
			local, err := o.Digest(new(big.Int).SetUint64(p.ChainID), p.Custody, s.Generation)
			if err != nil {
				return nil, err
			}
			remote, err := r.one(ctx, s, "DailyBetCustody", "hashOutcome", o)
			if err != nil {
				return nil, err
			}
			if remote.([32]byte) != local {
				return nil, fmt.Errorf("daily void contract digest mismatch")
			}
			p.Actions = append(p.Actions, Action{Kind: "queue_void", Tickets: []common.Hash{b.TicketID}, Outcomes: []contracts.DailyOutcome{o}, Deadline: deadline, Digest: local, OnchainDigest: remote.([32]byte)})
			continue
		}
		batch = append(batch, o)
		if len(batch) == 16 {
			if err = flush(); err != nil {
				return nil, err
			}
		}
	}
	if err = flush(); err != nil {
		return nil, err
	}
	if err = r.stable(ctx, s); err != nil {
		return nil, err
	}
	p.seal = p.hash()
	return p, nil
}

type Authorized struct {
	ChainID                            uint64         `json:"chain_id"`
	Custody                            common.Address `json:"custody"`
	Generation                         string         `json:"signature_version"`
	JournalHash                        common.Hash    `json:"journal_hash"`
	Action                             Action         `json:"action"`
	VerifiedBlock                      uint64         `json:"verified_block"`
	VerifiedHash                       common.Hash    `json:"verified_block_hash"`
	SettlementSignature, RiskSignature []byte
	Data                               []byte `json:"calldata"`
}

// Authorize re-plans against current confirmed chain state before either role
// signs. Controlled infrastructure supplies Signer; no key is read by this API.
// Persist the intent/calldata before a transaction-sending adapter exposes it.
func (r *Reader) Authorize(ctx context.Context, p *Plan, index int, signer contracts.Signer) (Authorized, error) {
	if p == nil || p.source == nil || p.seal == (common.Hash{}) || p.hash() != p.seal || index < 0 || index >= len(p.Actions) {
		return Authorized{}, fmt.Errorf("daily plan missing or modified")
	}
	a := p.Actions[index]
	if a.Kind != "batch" && a.Kind != "queue_void" && a.Kind != "complete_void" {
		return Authorized{}, fmt.Errorf("daily action is not executable")
	}
	if a.Kind != "complete_void" {
		if err := r.sourceFence(ctx, p.source); err != nil {
			return Authorized{}, err
		}
	}
	if err := r.stable(ctx, Snapshot{Number: p.Block, Hash: p.BlockHash}); err != nil {
		return Authorized{}, err
	}
	deadline := p.Deadline
	if a.Kind == "complete_void" {
		s, err := r.Snapshot(ctx)
		if err != nil {
			return Authorized{}, err
		}
		deadline = s.Time + 300
	}
	fresh, err := r.Plan(ctx, p.source, p.bindings, deadline)
	if err != nil {
		return Authorized{}, err
	}
	if a.Kind != "complete_void" && fresh.Generation != p.Generation {
		return Authorized{}, fmt.Errorf("daily signer generation changed; re-plan")
	}
	match := false
	for _, candidate := range fresh.Actions {
		if equalAction(a, candidate) {
			match = true
			break
		}
	}
	if !match {
		return Authorized{}, fmt.Errorf("daily chain state changed; re-plan")
	}
	result := Authorized{ChainID: p.ChainID, Custody: p.Custody, Generation: p.Generation, JournalHash: p.JournalHash, Action: a, VerifiedBlock: fresh.Block, VerifiedHash: fresh.BlockHash}
	if a.Kind == "complete_void" {
		result.Data, err = r.abis["DailyBetCustody"].Pack("completeVoid", a.Tickets[0])
		return result, err
	}
	for _, role := range []string{"SETTLEMENT_SIGNER", "RISK_SIGNER"} {
		if err = r.sourceFence(ctx, p.source); err != nil {
			return Authorized{}, err
		}
		sig, err := contracts.CheckedSign(ctx, signer, role, a.Digest, a.OnchainDigest)
		if err != nil {
			return Authorized{}, err
		}
		snapshot := Snapshot{Number: fresh.Block, Hash: fresh.BlockHash}
		if _, err = r.read(ctx, snapshot, "AccessController", "verify", crypto.Keccak256Hash([]byte(role)), a.Digest, sig); err != nil {
			return Authorized{}, fmt.Errorf("daily signer returned invalid %s signature: %w", role, err)
		}
		if role == "SETTLEMENT_SIGNER" {
			result.SettlementSignature = sig
		} else {
			result.RiskSignature = sig
		}
	}
	if err = r.sourceFence(ctx, p.source); err != nil {
		return Authorized{}, err
	}
	if a.Kind == "batch" {
		result.Data, err = r.abis["DailyBetCustody"].Pack("settleBatch", a.Outcomes, p.JournalHash, a.Deadline, result.SettlementSignature, result.RiskSignature)
	} else {
		result.Data, err = r.abis["DailyBetCustody"].Pack("resolve", a.Outcomes[0], result.SettlementSignature, result.RiskSignature)
	}
	if err != nil {
		return Authorized{}, err
	}
	if err = r.stable(ctx, Snapshot{Number: fresh.Block, Hash: fresh.BlockHash}); err != nil {
		return Authorized{}, err
	}
	return result, nil
}
