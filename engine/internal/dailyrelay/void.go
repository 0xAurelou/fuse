package dailyrelay

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"math/big"

	"fuse/engine/internal/contracts"
	"fuse/engine/internal/engine"
	"github.com/ethereum/go-ethereum/common"
	"github.com/ethereum/go-ethereum/core/types"
	"github.com/ethereum/go-ethereum/crypto"
)

// A queue proof records an obligation, never a payment. A completion proof
// records the original owner's available custody credit, not an external USDC
// withdrawal. Both include the exact successful call and canonical receipt.
type VoidProof struct {
	Kind             string                   `json:"kind"` // queue_void, complete_void
	ChainID          uint64                   `json:"chain_id"`
	Custody          common.Address           `json:"custody"`
	Ticket           common.Hash              `json:"ticket"`
	Account          common.Address           `json:"account"`
	StakeUSDC        string                   `json:"stake_usdc_units"`
	CreditUSDC       string                   `json:"custody_credit_usdc_units"`
	CanonicalMS      uint64                   `json:"canonical_ms"`
	Transaction      common.Hash              `json:"transaction"`
	Block            uint64                   `json:"block"`
	BlockHash        common.Hash              `json:"block_hash"`
	TransactionIndex uint                     `json:"transaction_index"`
	BindingHash      common.Hash              `json:"binding_hash"`
	QueueTransaction common.Hash              `json:"queue_transaction,omitempty"`
	Native           engine.SettlementOutcome `json:"native"`
	Authorization    Authorized               `json:"authorization"`
	verified         common.Hash
}

func (p VoidProof) identityHash() common.Hash {
	raw, _ := json.Marshal(p)
	return crypto.Keccak256Hash(raw)
}
func (p VoidProof) validProof() bool {
	return p.verified != (common.Hash{}) && p.verified == p.identityHash()
}
func sameVoidDecision(a, b engine.SettlementOutcome) bool {
	// Later journal/oracle receipts do not change an already final decision.
	a.JournalHash = ""
	a.OracleCommitment = ""
	b.JournalHash = ""
	b.OracleCommitment = ""
	return a == b
}

func (r *Reader) voidSource(ctx context.Context, s Snapshot, j *Journal, b Binding) (engine.SettlementOutcome, error) {
	if j == nil {
		return engine.SettlementOutcome{}, fmt.Errorf("void needs replayed source")
	}
	current, err := r.bind(ctx, s, j, b.StageID, b.TicketID, b.TxHash, b.Generation)
	if err != nil {
		return engine.SettlementOutcome{}, err
	}
	if current.identityHash() != b.identityHash() {
		return engine.SettlementOutcome{}, fmt.Errorf("void acceptance binding changed")
	}
	n, err := j.Outcome(b.StageID)
	if err != nil {
		return n, err
	}
	if n.Outcome != 4 || n.CanonicalMS <= 0 || n.Payout != n.Stake || n.LPPnL != 0 || n.CanonicalMS > int64(s.Time)*1000 || n.ObservedMS > int64(s.Time)*1000 {
		return n, fmt.Errorf("source is not an observed final void")
	}
	return n, nil
}

// receiptCall independently checks the actual transaction input. Unlike a cash
// batch, FinalVoidQueued has no digest marker, so its event alone cannot bind
// an asserted evidence hash or signed payload to the successful call.
func (r *Reader) receiptCall(ctx context.Context, s Snapshot, hash common.Hash, data []byte) (*types.Receipt, error) {
	var receipt *types.Receipt
	if err := r.rpc.ReadRPC(ctx, "eth_getTransactionReceipt", []any{hash}, &receipt); err != nil {
		return nil, err
	}
	if receipt == nil || receipt.TxHash != hash || receipt.Status != 1 || receipt.BlockNumber == nil || !receipt.BlockNumber.IsUint64() || receipt.BlockHash == (common.Hash{}) {
		return nil, fmt.Errorf("void receipt failed or unavailable")
	}
	n := receipt.BlockNumber.Uint64()
	if n > s.Number {
		return nil, contracts.ErrAwaitFinality
	}
	h, err := r.header(ctx, n)
	if err != nil {
		return nil, err
	}
	if h.Hash != receipt.BlockHash {
		return nil, contracts.ErrFinalityReorg
	}
	var tx *types.Transaction
	if err = r.rpc.ReadRPC(ctx, "eth_getTransactionByHash", []any{hash}, &tx); err != nil {
		return nil, err
	}
	if tx == nil || tx.Hash() != hash || !tx.Protected() || tx.ChainId().Cmp(new(big.Int).SetUint64(r.manifest.ChainID)) != 0 || tx.To() == nil || *tx.To() != r.manifest.Modules["DailyBetCustody"].Address || tx.Value().Sign() != 0 || !bytes.Equal(tx.Data(), data) {
		return nil, fmt.Errorf("void transaction calldata/domain mismatch")
	}
	return receipt, nil
}

// ReconcileVoidQueue verifies a new source prefix and its exact signed queue
// call. Financial source authority is checked before signing; the successful
// immutable contract call proves the role authorization during later recovery.
func (r *Reader) ReconcileVoidQueue(ctx context.Context, j *Journal, b Binding, a Authorized, hash common.Hash) (VoidProof, error) {
	s, err := r.Snapshot(ctx)
	if err != nil {
		return VoidProof{}, err
	}
	n, err := r.voidSource(ctx, s, j, b)
	if err != nil {
		return VoidProof{}, err
	}
	if a.JournalHash != common.HexToHash(j.state.JournalHash) {
		return VoidProof{}, fmt.Errorf("queue source prefix changed")
	}
	p := VoidProof{Kind: "queue_void", ChainID: b.ChainID, Custody: b.Custody, Ticket: b.TicketID, Account: common.HexToAddress(n.Account), StakeUSDC: fmt.Sprint(n.Stake), CreditUSDC: "0", CanonicalMS: uint64(n.CanonicalMS), Transaction: hash, BindingHash: b.identityHash(), Native: n, Authorization: a}
	return r.verifyVoidQueue(ctx, s, j, b, p)
}

// VerifyVoidQueue revalidates a restored proof against the actual signed call,
// original immutable ticket and current replay's same final decision. It can
// run without a live financial writer and after the refund has completed.
func (r *Reader) VerifyVoidQueue(ctx context.Context, j *Journal, b Binding, p VoidProof) (VoidProof, error) {
	s, err := r.Snapshot(ctx)
	if err != nil {
		return VoidProof{}, err
	}
	return r.verifyVoidQueue(ctx, s, j, b, p)
}
func (r *Reader) verifyVoidQueue(ctx context.Context, s Snapshot, j *Journal, b Binding, p VoidProof) (VoidProof, error) {
	n, err := r.voidSource(ctx, s, j, b)
	if err != nil {
		return VoidProof{}, err
	}
	a := p.Authorization
	if p.Kind != "queue_void" || p.ChainID != r.manifest.ChainID || p.Custody != r.manifest.Modules["DailyBetCustody"].Address || p.Ticket != b.TicketID || p.BindingHash != b.identityHash() || p.Account != common.HexToAddress(n.Account) || p.StakeUSDC != fmt.Sprint(n.Stake) || p.CreditUSDC != "0" || p.CanonicalMS != uint64(n.CanonicalMS) || p.QueueTransaction != (common.Hash{}) || !sameVoidDecision(p.Native, n) || a.ChainID != p.ChainID || a.Custody != p.Custody || a.JournalHash != common.HexToHash(p.Native.JournalHash) || a.Action.Kind != "queue_void" || len(a.Action.Tickets) != 1 || a.Action.Tickets[0] != p.Ticket || len(a.Action.Outcomes) != 1 || p.Transaction == (common.Hash{}) {
		return VoidProof{}, fmt.Errorf("queued void identity/source changed")
	}
	gen, ok := new(big.Int).SetString(a.Generation, 10)
	if !ok || gen.Sign() <= 0 || gen.String() != a.Generation || gen.Cmp(s.Generation) > 0 {
		return VoidProof{}, fmt.Errorf("invalid queued void generation")
	}
	if err = r.stable(ctx, Snapshot{Number: a.VerifiedBlock, Hash: a.VerifiedHash}); err != nil {
		return VoidProof{}, err
	}
	o := a.Action.Outcomes[0]
	raw, _ := json.Marshal(struct {
		Binding Binding
		Outcome any
	}{b, p.Native})
	if o.Id != p.Ticket || o.Outcome != 4 || o.CanonicalTime != p.CanonicalMS || o.Deadline != a.Action.Deadline || o.EvidenceHash != crypto.Keccak256Hash(raw) {
		return VoidProof{}, fmt.Errorf("queued void evidence changed")
	}
	digest, err := o.Digest(new(big.Int).SetUint64(p.ChainID), p.Custody, gen)
	if err != nil {
		return VoidProof{}, err
	}
	if digest != a.Action.Digest || digest != a.Action.OnchainDigest {
		return VoidProof{}, fmt.Errorf("queued void digest changed")
	}
	data, err := r.abis["DailyBetCustody"].Pack("resolve", o, a.SettlementSignature, a.RiskSignature)
	if err != nil {
		return VoidProof{}, err
	}
	if !bytes.Equal(data, a.Data) {
		return VoidProof{}, fmt.Errorf("queued void authorization calldata changed")
	}
	receipt, err := r.receiptCall(ctx, s, p.Transaction, data)
	if err != nil {
		return VoidProof{}, err
	}
	actualGeneration, err := r.generationAt(ctx, receipt)
	if err != nil {
		return VoidProof{}, err
	}
	if actualGeneration.Cmp(gen) != 0 {
		return VoidProof{}, fmt.Errorf("queued void asserted a different historical signer generation")
	}
	if err = checkVoidReceipt(r, receipt, p.Ticket, p.CanonicalMS, false); err != nil {
		return VoidProof{}, err
	}
	t, bv, err := r.views(ctx, s, p.Ticket)
	if err != nil {
		return VoidProof{}, err
	}
	if t.FinalVoidAt != p.CanonicalMS || bv.FinalVoidAt != p.CanonicalMS || (bv.Status != 1 && bv.Status != 4) {
		return VoidProof{}, fmt.Errorf("stored queued void differs from obligation")
	}
	if p.Block != 0 && (p.Block != receipt.BlockNumber.Uint64() || p.BlockHash != receipt.BlockHash || p.TransactionIndex != receipt.TransactionIndex) {
		return VoidProof{}, contracts.ErrFinalityReorg
	}
	p.Block = receipt.BlockNumber.Uint64()
	p.BlockHash = receipt.BlockHash
	p.TransactionIndex = receipt.TransactionIndex
	if err = r.stable(ctx, s); err != nil {
		return VoidProof{}, err
	}
	p.verified = p.identityHash()
	return p, nil
}

func (r *Reader) ReconcileVoidCompletion(ctx context.Context, j *Journal, b Binding, queued VoidProof, a Authorized, hash common.Hash) (VoidProof, error) {
	s, err := r.Snapshot(ctx)
	if err != nil {
		return VoidProof{}, err
	}
	q, err := r.verifyVoidQueue(ctx, s, j, b, queued)
	if err != nil {
		return VoidProof{}, err
	}
	n, err := r.voidSource(ctx, s, j, b)
	if err != nil {
		return VoidProof{}, err
	}
	if a.ChainID != q.ChainID || a.Custody != q.Custody || a.JournalHash != common.HexToHash(j.state.JournalHash) || a.Action.Kind != "complete_void" || len(a.Action.Tickets) != 1 || a.Action.Tickets[0] != q.Ticket || len(a.Action.Outcomes) != 0 || a.Action.Deadline != 0 || a.Action.Digest != (common.Hash{}) || a.Action.OnchainDigest != (common.Hash{}) || len(a.SettlementSignature) != 0 || len(a.RiskSignature) != 0 {
		return VoidProof{}, fmt.Errorf("void completion authorization changed")
	}
	if err = r.stable(ctx, Snapshot{Number: a.VerifiedBlock, Hash: a.VerifiedHash}); err != nil {
		return VoidProof{}, err
	}
	data, err := r.abis["DailyBetCustody"].Pack("completeVoid", q.Ticket)
	if err != nil {
		return VoidProof{}, err
	}
	if !bytes.Equal(data, a.Data) {
		return VoidProof{}, fmt.Errorf("void completion calldata changed")
	}
	receipt, err := r.receiptCall(ctx, s, hash, data)
	if err != nil {
		return VoidProof{}, err
	}
	if receipt.BlockNumber.Uint64() < q.Block || (receipt.BlockNumber.Uint64() == q.Block && receipt.TransactionIndex <= q.TransactionIndex) {
		return VoidProof{}, fmt.Errorf("completion must follow queued void receipt")
	}
	if err = checkVoidReceipt(r, receipt, q.Ticket, q.CanonicalMS, true); err != nil {
		return VoidProof{}, err
	}
	t, bv, err := r.views(ctx, s, q.Ticket)
	if err != nil {
		return VoidProof{}, err
	}
	if !t.Resolved || bv.Status != 4 || t.FinalVoidAt != q.CanonicalMS {
		return VoidProof{}, fmt.Errorf("void completion storage mismatch")
	}
	p := VoidProof{Kind: "complete_void", ChainID: q.ChainID, Custody: q.Custody, Ticket: q.Ticket, Account: q.Account, StakeUSDC: q.StakeUSDC, CreditUSDC: q.StakeUSDC, CanonicalMS: q.CanonicalMS, Transaction: hash, Block: receipt.BlockNumber.Uint64(), BlockHash: receipt.BlockHash, TransactionIndex: receipt.TransactionIndex, BindingHash: q.BindingHash, QueueTransaction: q.Transaction, Native: n, Authorization: a}
	if err = r.stable(ctx, s); err != nil {
		return VoidProof{}, err
	}
	p.verified = p.identityHash()
	return p, nil
}

func checkVoidReceipt(r *Reader, receipt *types.Receipt, id common.Hash, canonical uint64, completion bool) error {
	vault, custody := r.manifest.Modules["DailyLPVault"].Address, r.manifest.Modules["DailyBetCustody"].Address
	queueEvent := r.abis["DailyLPVault"].Events["FinalVoidQueued"]
	outcomeEvent := r.abis["DailyLPVault"].Events["OutcomeRecorded"]
	resolvedEvent := r.abis["DailyBetCustody"].Events["TicketResolved"]
	batchEvent := r.abis["DailyBetCustody"].Events["BatchSettled"]
	queued, resolved, outcomes := 0, 0, 0
	transfer := crypto.Keccak256Hash([]byte("Transfer(address,address,uint256)"))
	for _, log := range receipt.Logs {
		if log == nil || log.Removed || log.TxHash != receipt.TxHash || log.BlockHash != receipt.BlockHash || log.BlockNumber != receipt.BlockNumber.Uint64() || log.TxIndex != receipt.TransactionIndex {
			return fmt.Errorf("void receipt log identity invalid")
		}
		if len(log.Topics) == 0 {
			continue
		}
		if log.Address == r.manifest.Modules["USDC"].Address && log.Topics[0] == transfer {
			if len(log.Topics) != 3 || len(log.Data) != 32 {
				return fmt.Errorf("malformed void token movement")
			}
			from, to := common.BytesToAddress(log.Topics[1].Bytes()), common.BytesToAddress(log.Topics[2].Bytes())
			if from == vault || to == vault || from == custody || to == custody {
				return fmt.Errorf("void credit must not move pool/custody USDC")
			}
		}
		if log.Address == custody && log.Topics[0] == batchEvent.ID {
			return fmt.Errorf("void receipt contains a cash batch")
		}
		if log.Address == vault && log.Topics[0] == queueEvent.ID {
			if completion || len(log.Topics) != 2 || log.Topics[1] != id {
				return fmt.Errorf("void queue event mismatch")
			}
			v, err := queueEvent.Inputs.NonIndexed().Unpack(log.Data)
			if err != nil {
				return err
			}
			if v[0].(uint64) != canonical {
				return fmt.Errorf("void queue time mismatch")
			}
			queued++
		}
		if log.Address == vault && log.Topics[0] == outcomeEvent.ID {
			if !completion || len(log.Topics) != 2 || log.Topics[1] != id {
				return fmt.Errorf("void outcome event mismatch")
			}
			v, err := outcomeEvent.Inputs.NonIndexed().Unpack(log.Data)
			if err != nil {
				return err
			}
			if v[0].(uint8) != 4 || v[1].(uint64) != canonical || v[2].(*big.Int).Sign() != 0 {
				return fmt.Errorf("void outcome/time/PnL mismatch")
			}
			outcomes++
		}
		if log.Address == custody && log.Topics[0] == resolvedEvent.ID {
			if !completion || len(log.Topics) != 2 || log.Topics[1] != id {
				return fmt.Errorf("void resolved event mismatch")
			}
			v, err := resolvedEvent.Inputs.NonIndexed().Unpack(log.Data)
			if err != nil {
				return err
			}
			if v[0].(uint8) != 4 || v[1].(uint64) != canonical || v[2].([32]byte) != ([32]byte{}) {
				return fmt.Errorf("void resolved fields mismatch")
			}
			resolved++
		}
	}
	if completion {
		if queued != 0 || resolved != 1 || outcomes != 1 {
			return fmt.Errorf("incomplete void refund receipt")
		}
	} else if queued != 1 || resolved != 0 || outcomes != 0 {
		return fmt.Errorf("queue receipt cannot prove a refund")
	}
	return nil
}
