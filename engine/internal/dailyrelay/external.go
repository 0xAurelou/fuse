package dailyrelay

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"math/big"
	"strings"

	"fuse/engine/internal/contracts"
	"github.com/ethereum/go-ethereum/common"
	"github.com/ethereum/go-ethereum/common/hexutil"
	"github.com/ethereum/go-ethereum/core/types"
	"github.com/ethereum/go-ethereum/crypto"
)

// Observation is evidence, never authority to send this transaction. Its raw
// signature, recovered sender, nonce, canonical block membership and receipt
// are reverified after loading. No arbitrary nonce reset is supported.
type TransactionObservation struct {
	Transaction common.Hash    `json:"transaction"`
	Sender      common.Address `json:"sender"`
	Nonce       uint64         `json:"nonce"`
	Raw         []byte         `json:"raw_transaction"`
	Receipt     *types.Receipt `json:"receipt"`
}
type NonceRecovery struct {
	Reason      string                 `json:"reason"`
	Class       string                 `json:"class"` // matching or unrelated (including reverted execution).
	Observation TransactionObservation `json:"observation"`
}
type ExternalExecution struct {
	Reason      string                 `json:"reason"`
	Kind        string                 `json:"kind"`
	Observation TransactionObservation `json:"observation"`
	Settlement  *SettlementProof       `json:"settlement_proof,omitempty"`
	Void        *VoidProof             `json:"void_proof,omitempty"`
}

func validRecoveryReason(s string) bool { return strings.TrimSpace(s) != "" && len(s) <= 512 }

func checkRecoverableParent(b Outbound) error {
	if len(b.Raw) > 0 {
		return checkRaw(b)
	}
	if b.Nonce == nil || b.Authorization == nil || !validTerms(b.Intent.Terms) || len(b.Attempts) != 0 || b.Transaction != (common.Hash{}) {
		return fmt.Errorf("persisted nonce/authorization required for recovery")
	}
	encoded, err := unsignedTransaction(b).MarshalBinary()
	if err != nil {
		return err
	}
	if !bytes.Equal(encoded, b.Unsigned) {
		return fmt.Errorf("reserved unsigned parent payload changed")
	}
	return nil
}

func (r *Reader) ObserveTransaction(ctx context.Context, hash common.Hash) (TransactionObservation, error) {
	var p TransactionObservation
	if hash == (common.Hash{}) {
		return p, fmt.Errorf("transaction hash required")
	}
	s, err := r.Snapshot(ctx)
	if err != nil {
		return p, err
	}
	var receipt *types.Receipt
	if err = r.rpc.ReadRPC(ctx, "eth_getTransactionReceipt", []any{hash}, &receipt); err != nil {
		return p, err
	}
	if receipt == nil || receipt.TxHash != hash || receipt.BlockNumber == nil || !receipt.BlockNumber.IsUint64() || receipt.BlockHash == (common.Hash{}) || receipt.Status > 1 {
		return p, fmt.Errorf("confirmed transaction receipt unavailable or invalid")
	}
	n := receipt.BlockNumber.Uint64()
	if n > s.Number {
		return p, contracts.ErrAwaitFinality
	}
	var block struct {
		Number       hexutil.Uint64
		Hash         common.Hash
		Transactions []common.Hash
	}
	if err = r.rpc.ReadRPC(ctx, "eth_getBlockByNumber", []any{hexutil.EncodeUint64(n), false}, &block); err != nil {
		return p, err
	}
	if uint64(block.Number) != n || block.Hash != receipt.BlockHash || uint64(receipt.TransactionIndex) >= uint64(len(block.Transactions)) || block.Transactions[receipt.TransactionIndex] != hash {
		return p, fmt.Errorf("transaction receipt is not in its asserted canonical block/index")
	}
	var tx *types.Transaction
	if err = r.rpc.ReadRPC(ctx, "eth_getTransactionByHash", []any{hash}, &tx); err != nil {
		return p, err
	}
	if tx == nil || tx.Hash() != hash || !tx.Protected() || tx.ChainId().Cmp(new(big.Int).SetUint64(r.manifest.ChainID)) != 0 {
		return p, fmt.Errorf("transaction raw signature/domain/hash mismatch")
	}
	from, err := types.Sender(types.LatestSignerForChainID(tx.ChainId()), tx)
	if err != nil {
		return p, err
	}
	raw, err := tx.MarshalBinary()
	if err != nil {
		return p, err
	}
	for _, l := range receipt.Logs {
		if l == nil || l.Removed || l.BlockNumber != n || l.BlockHash != receipt.BlockHash || l.TxHash != hash || l.TxIndex != receipt.TransactionIndex {
			return p, fmt.Errorf("transaction receipt log identity invalid")
		}
	}
	if receipt.Status == 0 && len(receipt.Logs) != 0 {
		return p, fmt.Errorf("reverted transaction has committed logs")
	}
	if err = r.stable(ctx, Snapshot{Number: n, Hash: block.Hash}); err != nil {
		return p, err
	}
	if err = r.stable(ctx, s); err != nil {
		return p, err
	}
	return TransactionObservation{Transaction: hash, Sender: from, Nonce: tx.Nonce(), Raw: raw, Receipt: receipt}, nil
}
func (r *Reader) verifyObservation(ctx context.Context, p TransactionObservation) error {
	fresh, err := r.ObserveTransaction(ctx, p.Transaction)
	if err != nil {
		return err
	}
	a, _ := json.Marshal(p)
	b, _ := json.Marshal(fresh)
	if !bytes.Equal(a, b) {
		return fmt.Errorf("stored transaction observation changed")
	}
	return nil
}

func (r *Reader) nonceClass(b Outbound, p TransactionObservation) (string, error) {
	if b.Nonce == nil || b.Authorization == nil || p.Sender != b.Intent.Payer || p.Nonce != *b.Nonce || p.Receipt == nil || p.Receipt.BlockNumber == nil || !p.Receipt.BlockNumber.IsUint64() || p.Receipt.Status > 1 || p.Receipt.BlockNumber.Uint64() < b.Authorization.VerifiedBlock {
		return "", fmt.Errorf("transaction does not consume this reserved payer nonce")
	}
	var tx types.Transaction
	if err := tx.UnmarshalBinary(p.Raw); err != nil {
		return "", err
	}
	if p.Receipt.Status == 0 {
		if len(p.Receipt.Logs) != 0 {
			return "", fmt.Errorf("reverted nonce transaction has committed effects")
		}
		return "unrelated", nil
	}
	if tx.To() != nil && *tx.To() == b.Intent.Custody && tx.Value().Sign() == 0 && bytes.Equal(tx.Data(), b.Authorization.Data) {
		return "matching", nil
	}
	if err := r.nonfinancialObservation(p); err != nil {
		return "", err
	}
	return "unrelated", nil
}
func (r *Reader) nonfinancialObservation(p TransactionObservation) error {
	if p.Receipt.Status == 0 {
		return nil
	}
	var tx types.Transaction
	if err := tx.UnmarshalBinary(p.Raw); err != nil {
		return err
	}
	for _, m := range r.manifest.Modules {
		if tx.To() != nil && *tx.To() == m.Address {
			return fmt.Errorf("unknown successful protocol call needs semantic reconciliation")
		}
	}
	for _, l := range p.Receipt.Logs {
		if l.Address == r.manifest.Modules["USDC"].Address {
			if len(l.Topics) != 3 || len(l.Data) != 32 || (l.Topics[0] != crypto.Keccak256Hash([]byte("Transfer(address,address,uint256)")) && l.Topics[0] != crypto.Keccak256Hash([]byte("Approval(address,address,uint256)"))) {
				return fmt.Errorf("unclassified USDC receipt event")
			}
		}
		for name, m := range r.manifest.Modules {
			if name != "USDC" && l.Address == m.Address {
				return fmt.Errorf("unclassified protocol receipt effects")
			}
			if l.Address == r.manifest.Modules["USDC"].Address {
				for _, topic := range l.Topics[1:] {
					if common.BytesToAddress(topic.Bytes()) == m.Address {
						return fmt.Errorf("unclassified movement/approval involving protocol funds")
					}
				}
			}
		}
	}
	return nil
}

// AdoptNonce requires a specific confirmed, signed transaction consuming exactly
// the reserved nonce. Matching calls still need full semantic payment proof;
// unrelated transactions release processing only, never accepted obligations.
func (o *Outbox) AdoptNonce(ctx context.Context, r *Reader, id, hash common.Hash, reason string) (Outbound, error) {
	o.mu.Lock()
	defer o.mu.Unlock()
	l, err := o.guard(ctx, r)
	if err != nil {
		return Outbound{}, err
	}
	b, err := o.get(ctx, id)
	if err != nil {
		return b, err
	}
	if !validRecoveryReason(reason) {
		return b, fmt.Errorf("active nonce and explicit recovery reason required")
	}
	if err = checkRecoverableParent(b); err != nil {
		return b, err
	}
	if err = checkAttempts(b); err != nil {
		return b, err
	}
	if b.NonceRecovery != nil {
		if b.NonceRecovery.Observation.Transaction != hash || b.NonceRecovery.Reason != reason {
			return b, fmt.Errorf("nonce recovery evidence cannot be replaced")
		}
		return o.observe(ctx, r, id)
	}
	if l.active != id.Hex() {
		return b, fmt.Errorf("active nonce required for new recovery evidence")
	}
	if hash == b.Transaction {
		return b, fmt.Errorf("known transaction: use normal observation")
	}
	for _, a := range b.Attempts {
		if a.Transaction == hash {
			return b, fmt.Errorf("known attempt: use normal observation")
		}
	}
	known, _, err := r.outboundReceipt(ctx, b)
	if err != nil {
		return b, err
	}
	if known != nil {
		return b, fmt.Errorf("a known nonce transaction already has a receipt")
	}
	p, err := r.ObserveTransaction(ctx, hash)
	if err != nil {
		return b, err
	}
	class, err := r.nonceClass(b, p)
	if err != nil {
		return b, err
	}
	b.NonceRecovery = &NonceRecovery{Reason: reason, Class: class, Observation: p}
	if err = o.save(ctx, b); err != nil {
		return b, err
	}
	return o.observe(ctx, r, id)
}

// AdoptExternalExecution records a semantically verified call by another sender
// without pretending that it consumed this payer's nonce. Financial proof and
// the external association commit together; the original lane/claims remain
// held until a recorded nonce transaction, cancellation or recovery consumes it.
func (o *Outbox) AdoptExternalExecution(ctx context.Context, r *Reader, j *Journal, id, hash common.Hash, reason string) (Outbound, error) {
	o.mu.Lock()
	defer o.mu.Unlock()
	l, err := o.guard(ctx, r)
	if err != nil {
		return Outbound{}, err
	}
	b, err := o.get(ctx, id)
	if err != nil {
		return b, err
	}
	if b.Nonce == nil || b.Authorization == nil || !validRecoveryReason(reason) {
		return b, fmt.Errorf("active prepared intent and explicit recovery reason required")
	}
	if err = checkRecoverableParent(b); err != nil {
		return b, err
	}
	if err = checkAttempts(b); err != nil {
		return b, err
	}
	if b.ExternalExecution != nil {
		if b.ExternalExecution.Observation.Transaction != hash || b.ExternalExecution.Reason != reason {
			return b, fmt.Errorf("external execution evidence cannot be replaced")
		}
		if err = o.verifyExternal(ctx, r, b); err != nil {
			return b, err
		}
		return b, nil
	}
	if l.active != id.Hex() {
		return b, fmt.Errorf("active intent required for new external execution evidence")
	}
	known, _, err := r.outboundReceipt(ctx, b)
	if err != nil {
		return b, err
	}
	if known != nil && known.Status == 1 {
		return b, fmt.Errorf("known successful execution must be reconciled first")
	}
	p, err := r.ObserveTransaction(ctx, hash)
	if err != nil {
		return b, err
	}
	if p.Sender == o.payer && p.Nonce == *b.Nonce {
		return b, fmt.Errorf("this consumes the reserved nonce; use AdoptNonce")
	}
	var tx types.Transaction
	if err = tx.UnmarshalBinary(p.Raw); err != nil {
		return b, err
	}
	if p.Receipt.Status != 1 || tx.To() == nil || *tx.To() != b.Intent.Custody || tx.Value().Sign() != 0 || !bytes.Equal(tx.Data(), b.Authorization.Data) {
		return b, fmt.Errorf("external call is not the exact planned financial authorization")
	}
	e := &ExternalExecution{Reason: reason, Kind: b.Intent.Action.Kind, Observation: p}
	switch e.Kind {
	case "batch":
		proof, err := r.ReconcileBatch(ctx, j, b.Intent.Bindings, *b.Authorization, hash)
		if err != nil {
			return b, err
		}
		e.Settlement = &proof
	case "queue_void":
		if len(b.Intent.Bindings) != 1 {
			return b, fmt.Errorf("one queued void binding required")
		}
		proof, err := r.ReconcileVoidQueue(ctx, j, b.Intent.Bindings[0], *b.Authorization, hash)
		if err != nil {
			return b, err
		}
		e.Void = &proof
	case "complete_void":
		if len(b.Intent.Bindings) != 1 || b.Intent.Queue == nil {
			return b, fmt.Errorf("original queued proof required")
		}
		proof, err := r.ReconcileVoidCompletion(ctx, j, b.Intent.Bindings[0], *b.Intent.Queue, *b.Authorization, hash)
		if err != nil {
			return b, err
		}
		e.Void = &proof
	default:
		return b, fmt.Errorf("unsupported external execution kind")
	}
	b.ExternalExecution = e
	b.State = "external_executed"
	encoded, err := json.Marshal(b)
	if err != nil {
		return b, err
	}
	dbtx, err := o.conn.Begin(ctx)
	if err != nil {
		return b, err
	}
	defer dbtx.Rollback(context.Background()) //nolint:errcheck
	if e.Settlement != nil {
		if err = commitSettlement(ctx, dbtx, *e.Settlement); err != nil {
			return b, err
		}
	} else {
		if err = commitVoid(ctx, dbtx, *e.Void); err != nil {
			return b, err
		}
	}
	res, err := dbtx.Exec(ctx, `UPDATE fuse_daily_outbound SET record_encoded=$4 WHERE chain_id=$1 AND payer=$2 AND id=$3 AND EXISTS(SELECT 1 FROM fuse_daily_outbound_lanes WHERE chain_id=$1 AND payer=$2 AND active_id=$3)`, fmt.Sprint(o.chain), o.payer.Hex(), id.Hex(), encoded)
	if err != nil {
		return b, err
	}
	if res.RowsAffected() != 1 {
		return b, ErrOutboundBusy
	}
	return b, dbtx.Commit(ctx)
}

func (o *Outbox) verifyExternal(ctx context.Context, r *Reader, b Outbound) error {
	e := b.ExternalExecution
	if e == nil {
		return nil
	}
	if !validRecoveryReason(e.Reason) || e.Kind != b.Intent.Action.Kind {
		return fmt.Errorf("external execution metadata changed")
	}
	if err := r.verifyObservation(ctx, e.Observation); err != nil {
		return err
	}
	if (e.Settlement == nil) == (e.Void == nil) {
		return fmt.Errorf("one external semantic proof required")
	}
	var expected []byte
	var hash common.Hash
	table := "fuse_daily_settlements"
	if e.Settlement != nil {
		expected, _ = json.Marshal(e.Settlement)
		hash = e.Settlement.Transaction
	} else {
		expected, _ = json.Marshal(e.Void)
		hash = e.Void.Transaction
		table = "fuse_daily_void_proofs"
	}
	if hash != e.Observation.Transaction {
		return fmt.Errorf("external proof transaction changed")
	}
	var actual []byte
	// Table names are fixed constants above, never caller input.
	err := o.conn.QueryRow(ctx, `SELECT proof_encoded FROM `+table+` WHERE chain_id=$1 AND custody=$2 AND tx_hash=$3`, fmt.Sprint(o.chain), b.Intent.Custody.Hex(), hash.Hex()).Scan(&actual)
	if err != nil {
		return err
	}
	if !bytes.Equal(actual, expected) {
		return fmt.Errorf("external execution association lost its committed semantic proof")
	}
	return nil
}

// FindNonce scans an explicit bounded confirmed range. Absence never releases
// anything. Larger gaps can be examined in separate windows with saved cursors.
const MaxRecoveryBlocks = 128

func (r *Reader) FindNonce(ctx context.Context, payer common.Address, nonce, from, to uint64) (*TransactionObservation, error) {
	if payer == (common.Address{}) || to < from || to-from >= MaxRecoveryBlocks {
		return nil, fmt.Errorf("explicit recovery range must contain 1..128 blocks")
	}
	s, err := r.Snapshot(ctx)
	if err != nil {
		return nil, err
	}
	if to > s.Number {
		return nil, contracts.ErrAwaitFinality
	}
	var found *TransactionObservation
	var prior common.Hash
	for n := from; ; n++ {
		var b struct {
			Number           hexutil.Uint64
			Hash, ParentHash common.Hash
			Transactions     []*types.Transaction
		}
		if err = r.rpc.ReadRPC(ctx, "eth_getBlockByNumber", []any{hexutil.EncodeUint64(n), true}, &b); err != nil {
			return nil, err
		}
		if uint64(b.Number) != n || b.Hash == (common.Hash{}) || (n > from && b.ParentHash != prior) {
			return nil, contracts.ErrFinalityReorg
		}
		for _, tx := range b.Transactions {
			if tx == nil {
				return nil, fmt.Errorf("recovery block contains missing transaction")
			}
			if tx.Nonce() != nonce {
				continue
			}
			sender, err := types.Sender(types.LatestSignerForChainID(new(big.Int).SetUint64(r.manifest.ChainID)), tx)
			if err != nil {
				return nil, err
			}
			if sender != payer {
				continue
			}
			if found != nil {
				return nil, ErrNonceConflict
			}
			p, err := r.ObserveTransaction(ctx, tx.Hash())
			if err != nil {
				return nil, err
			}
			if p.Receipt.BlockHash != b.Hash {
				return nil, contracts.ErrFinalityReorg
			}
			found = &p
		}
		if err = r.stable(ctx, Snapshot{Number: n, Hash: b.Hash}); err != nil {
			return nil, err
		}
		prior = b.Hash
		if n == to {
			break
		}
	}
	if err = r.stable(ctx, s); err != nil {
		return nil, err
	}
	return found, nil
}
