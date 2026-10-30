package dailyrelay

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"math/big"
	"strings"

	"github.com/ethereum/go-ethereum/common"
	"github.com/ethereum/go-ethereum/core/types"
	"github.com/ethereum/go-ethereum/crypto"
)

// All signed variants remain in the same durable nonce slot. The original
// Intent and raw bytes never change. The bounded history is an operational
// candidate limit, not calibrated production throughput or fee policy.
const MaxOutboundAttempts = 32

type OutboundAttempt struct {
	ID          common.Hash      `json:"id"`
	Kind        string           `json:"kind"` // replace (fees only) or cancel (zero-value self-transfer).
	Reason      string           `json:"reason"`
	Terms       TransactionTerms `json:"transaction_terms"`
	State       string           `json:"state"` // staged, prepared, abandoned
	Unsigned    []byte           `json:"unsigned_transaction"`
	Raw         []byte           `json:"raw_transaction,omitempty"`
	Transaction common.Hash      `json:"transaction,omitempty"`
}

func (a OutboundAttempt) id(parent common.Hash, index int) common.Hash {
	raw, _ := json.Marshal(struct {
		Parent       common.Hash
		Index        int
		Kind, Reason string
		Terms        TransactionTerms
		Unsigned     []byte
	}{parent, index, a.Kind, a.Reason, a.Terms, a.Unsigned})
	return crypto.Keccak256Hash(raw)
}
func attemptUnsigned(b Outbound, a OutboundAttempt) *types.Transaction {
	to, data := b.Intent.Custody, b.Authorization.Data
	if a.Kind == "cancel" {
		to, data = b.Intent.Payer, nil
	}
	return types.NewTx(&types.DynamicFeeTx{ChainID: new(big.Int).SetUint64(b.Intent.ChainID), Nonce: *b.Nonce, Gas: a.Terms.Gas, GasFeeCap: a.Terms.FeeCap, GasTipCap: a.Terms.TipCap, To: &to, Value: new(big.Int), Data: data})
}
func hasCancellation(b Outbound) bool {
	for _, a := range b.Attempts {
		if a.Kind == "cancel" && a.State == "prepared" {
			return true
		}
	}
	return false
}
func higherFees(a, b TransactionTerms) bool {
	return a.FeeCap.Cmp(b.FeeCap) > 0 && a.TipCap.Cmp(b.TipCap) > 0
}
func checkAttempts(b Outbound) error {
	if len(b.Attempts) > MaxOutboundAttempts {
		return fmt.Errorf("outbound attempt history exceeds bound")
	}
	fees := b.Intent.Terms
	staged := false
	cancelled := false
	for i, a := range b.Attempts {
		if b.Nonce == nil || b.Authorization == nil || !validTerms(a.Terms) || a.ID != a.id(b.ID, i) || strings.TrimSpace(a.Reason) == "" || len(a.Reason) > 512 || (a.Kind != "replace" && a.Kind != "cancel") {
			return fmt.Errorf("invalid outbound attempt identity")
		}
		if (a.Kind == "replace" && (a.Terms.Gas != b.Intent.Terms.Gas || cancelled)) || (a.Kind == "cancel" && a.Terms.Gas != 21000) {
			return fmt.Errorf("replacement changed payload/gas or bypassed armed cancellation")
		}
		if !higherFees(a.Terms, fees) {
			return fmt.Errorf("replacement fees must exceed every earlier retained fee cap and tip")
		}
		if a.State == "abandoned" {
			if len(a.Raw) != 0 || a.Transaction != (common.Hash{}) {
				return fmt.Errorf("signed attempt cannot be abandoned")
			}
			continue
		}
		if staged {
			return fmt.Errorf("unresolved unsigned attempt must be resumed or explicitly abandoned")
		}
		unsigned := attemptUnsigned(b, a)
		encoded, err := unsigned.MarshalBinary()
		if err != nil {
			return err
		}
		if !bytes.Equal(encoded, a.Unsigned) {
			return fmt.Errorf("attempt unsigned payload changed")
		}
		if a.State == "staged" {
			if len(a.Raw) != 0 || a.Transaction != (common.Hash{}) {
				return fmt.Errorf("staged attempt already has signed fields")
			}
			staged = true
		} else if a.State == "prepared" {
			var tx types.Transaction
			if err := tx.UnmarshalBinary(a.Raw); err != nil {
				return err
			}
			signer := types.LatestSignerForChainID(unsigned.ChainId())
			from, err := types.Sender(signer, &tx)
			if err != nil {
				return err
			}
			canonical, err := tx.MarshalBinary()
			if err != nil {
				return err
			}
			if tx.Type() != types.DynamicFeeTxType || !tx.Protected() || tx.ChainId().Cmp(unsigned.ChainId()) != 0 || signer.Hash(&tx) != signer.Hash(unsigned) || from != b.Intent.Payer || tx.Hash() != a.Transaction || !bytes.Equal(canonical, a.Raw) {
				return fmt.Errorf("signed attempt fields/sender changed")
			}
			if a.Kind == "cancel" {
				cancelled = true
			}
		} else {
			return fmt.Errorf("unknown outbound attempt state")
		}
		fees = a.Terms
	}
	return nil
}

// PrepareReplacement keeps the financial authorization, calldata, gas, target,
// value, chain and nonce unchanged. It requests only another payer signature.
// Fees are explicit inputs; the node may require a larger bump than this API's
// strict increase. No fee multiplier or production defaults are inferred.
func (o *Outbox) PrepareReplacement(ctx context.Context, r *Reader, j *Journal, id common.Hash, terms TransactionTerms, reason string, payer TransactionSigner) (Outbound, int, error) {
	o.mu.Lock()
	defer o.mu.Unlock()
	return o.prepareAttempt(ctx, r, j, id, "replace", terms, reason, payer)
}

// PrepareCancellation records a nonce-consuming zero-value self-transfer. It
// needs no financial writer or role signature and never cancels the payout
// obligation or invalidates an already exposed contract authorization.
func (o *Outbox) PrepareCancellation(ctx context.Context, r *Reader, id common.Hash, terms TransactionTerms, reason string, payer TransactionSigner) (Outbound, int, error) {
	o.mu.Lock()
	defer o.mu.Unlock()
	return o.prepareAttempt(ctx, r, nil, id, "cancel", terms, reason, payer)
}
func (o *Outbox) prepareAttempt(ctx context.Context, r *Reader, j *Journal, id common.Hash, kind string, terms TransactionTerms, reason string, payer TransactionSigner) (Outbound, int, error) {
	b, err := o.observe(ctx, r, id)
	if err != nil {
		return b, -1, err
	}
	if b.Receipt != nil || (b.State != "prepared" && b.State != "external_executed") || payer == nil || !validTerms(terms) || strings.TrimSpace(reason) == "" || len(reason) > 512 {
		return b, -1, fmt.Errorf("pending prepared nonce, explicit terms/reason and payer signer required")
	}
	if kind == "replace" {
		if b.ExternalExecution != nil {
			return b, -1, fmt.Errorf("payment is already proven; only nonce cleanup is permitted")
		}
		if hasCancellation(b) {
			return b, -1, fmt.Errorf("cancellation is armed; settlement replacement refused")
		}
		if terms.Gas != b.Intent.Terms.Gas {
			return b, -1, fmt.Errorf("fee replacement cannot change gas or settlement payload")
		}
		if err = r.validateOutboundAuthorization(ctx, j, b); err != nil {
			return b, -1, err
		}
	} else if terms.Gas != 21000 {
		return b, -1, fmt.Errorf("cancellation requires exactly intrinsic self-transfer gas")
	}
	// Deep-copy caller-owned fee integers before recording or invoking a signer.
	terms = TransactionTerms{Gas: terms.Gas, FeeCap: new(big.Int).Set(terms.FeeCap), TipCap: new(big.Int).Set(terms.TipCap)}
	a := OutboundAttempt{Kind: kind, Reason: reason, Terms: terms, State: "staged"}
	unsigned := attemptUnsigned(b, a)
	a.Unsigned, err = unsigned.MarshalBinary()
	if err != nil {
		return b, -1, err
	}
	index := len(b.Attempts)
	if index > 0 && b.Attempts[index-1].State == "staged" {
		index--
		a.ID = a.id(b.ID, index)
		if a.ID != b.Attempts[index].ID {
			return b, index, fmt.Errorf("resume or abandon the recorded unsigned attempt before changing it")
		}
	} else {
		if index >= MaxOutboundAttempts {
			return b, -1, fmt.Errorf("outbound attempt bound reached; operator reconciliation required")
		}
		a.ID = a.id(b.ID, index)
		b.Attempts = append(b.Attempts, a)
		if err = checkAttempts(b); err != nil {
			return b, index, err
		}
		if err = o.save(ctx, b); err != nil {
			return b, index, err
		}
	}
	if l, err := o.guard(ctx, r); err != nil {
		return b, index, err
	} else if l.active != b.ID.Hex() {
		return b, index, ErrOutboundBusy
	}
	signed, err := payer.SignTransaction(ctx, unsigned)
	if err != nil {
		return b, index, err
	}
	if signed == nil {
		return b, index, fmt.Errorf("payer signer returned no replacement transaction")
	}
	a.Raw, err = signed.MarshalBinary()
	if err != nil {
		return b, index, err
	}
	a.Transaction = signed.Hash()
	a.State = "prepared"
	b.Attempts[index] = a
	if err = checkAttempts(b); err != nil {
		return b, index, err
	}
	if kind == "replace" {
		if err = r.validateOutboundAuthorization(ctx, j, b); err != nil {
			return b, index, err
		}
	}
	if _, err = o.guard(ctx, r); err != nil {
		return b, index, err
	}
	if err = o.save(ctx, b); err != nil {
		return b, index, err
	}
	return b, index, nil
}

// AbandonUnsignedAttempt only retires a staged signature request. It releases
// neither nonce nor tickets and cannot remove any signed hash from observation.
func (o *Outbox) AbandonUnsignedAttempt(ctx context.Context, r *Reader, id common.Hash, index int) error {
	o.mu.Lock()
	defer o.mu.Unlock()
	if _, err := o.guard(ctx, r); err != nil {
		return err
	}
	b, err := o.get(ctx, id)
	if err != nil {
		return err
	}
	if index < 0 || index != len(b.Attempts)-1 || b.Attempts[index].State != "staged" || len(b.Attempts[index].Raw) != 0 {
		return fmt.Errorf("only the last unsigned staged attempt can be abandoned")
	}
	b.Attempts[index].State = "abandoned"
	return o.save(ctx, b)
}
func (o *Outbox) DeliverAttempt(ctx context.Context, r *Reader, j *Journal, id common.Hash, index int, sender RawBroadcaster) (Outbound, error) {
	o.mu.Lock()
	defer o.mu.Unlock()
	if index < 0 {
		return Outbound{}, fmt.Errorf("nonnegative replacement attempt index required")
	}
	return o.deliver(ctx, r, j, id, index, sender)
}

// Query every retained signed hash. Any failed RPC read or contradictory pair
// of receipts halts reconciliation; selecting only the latest hash is unsafe
// because an older settlement can win the race against a cancellation.
func (r *Reader) outboundReceipt(ctx context.Context, b Outbound) (*types.Receipt, int, error) {
	hashes := []common.Hash{}
	indices := []int{}
	seen := map[common.Hash]bool{}
	if len(b.Raw) > 0 {
		hashes = append(hashes, b.Transaction)
		indices = append(indices, -1)
		seen[b.Transaction] = true
	}
	for i, a := range b.Attempts {
		if a.State == "prepared" {
			if seen[a.Transaction] {
				return nil, -1, fmt.Errorf("duplicate attempt transaction hash")
			}
			seen[a.Transaction] = true
			hashes = append(hashes, a.Transaction)
			indices = append(indices, i)
		}
	}
	if b.NonceRecovery != nil {
		hash := b.NonceRecovery.Observation.Transaction
		if seen[hash] {
			return nil, -1, fmt.Errorf("nonce recovery duplicates a known signed transaction")
		}
		hashes = append(hashes, hash)
		indices = append(indices, -2)
	}
	var winner *types.Receipt
	index := -1
	for i, hash := range hashes {
		var receipt *types.Receipt
		if err := r.rpc.ReadRPC(ctx, "eth_getTransactionReceipt", []any{hash}, &receipt); err != nil {
			return nil, -1, err
		}
		if receipt == nil {
			continue
		}
		if receipt.TxHash != hash {
			return nil, -1, fmt.Errorf("attempt receipt hash changed")
		}
		if winner != nil {
			return nil, -1, ErrNonceConflict
		}
		winner = receipt
		index = indices[i]
	}
	return winner, index, nil
}
