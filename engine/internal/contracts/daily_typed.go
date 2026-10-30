package contracts

import (
	"fmt"
	"math/big"

	"github.com/ethereum/go-ethereum/accounts/abi"
	"github.com/ethereum/go-ethereum/common"
	"github.com/ethereum/go-ethereum/crypto"
)

// DailyQuote uses seconds for freshness, integer prices and six-decimal USDC.
// PricingHash commits the complete original native quote, not a new price model.
type DailyQuote struct {
	Id                                              [32]byte
	Account                                         common.Address
	Asset                                           uint8
	Stake, Multiplier, Lower, ReferencePrice, Upper *big.Int
	QuotedAt, ValidUntil                            uint64
	PricingHash                                     [32]byte
}

func (q DailyQuote) Digest(chain *big.Int, custody common.Address, limits common.Hash, generation *big.Int) (common.Hash, error) {
	return TypedDigest(Domain{chain, custody, "FUSE DailyBetCustody"}, "Quote", []Field{
		{"id", "bytes32", q.Id}, {"account", "address", q.Account}, {"asset", "uint8", q.Asset},
		{"stake", "uint256", q.Stake}, {"multiplier", "uint256", q.Multiplier},
		{"lower", "uint256", q.Lower}, {"referencePrice", "uint256", q.ReferencePrice}, {"upper", "uint256", q.Upper},
		{"quotedAt", "uint64", q.QuotedAt}, {"validUntil", "uint64", q.ValidUntil},
		{"pricingHash", "bytes32", q.PricingHash}, {"limitsHash", "bytes32", limits},
	}, generation)
}

// DailyOutcome's canonical time is milliseconds; its signature deadline is seconds.
// Field spelling matches the compiled ABI (Id, rather than ID).
type DailyOutcome struct {
	Id            [32]byte
	Outcome       uint8
	CanonicalTime uint64
	EvidenceHash  [32]byte
	Deadline      uint64
}

func (o DailyOutcome) Digest(chain *big.Int, custody common.Address, generation *big.Int) (common.Hash, error) {
	if err := o.Validate(); err != nil {
		return common.Hash{}, err
	}
	return TypedDigest(Domain{chain, custody, "FUSE DailyBetCustody"}, "Outcome", []Field{
		{"id", "bytes32", o.Id}, {"outcome", "uint8", o.Outcome}, {"canonicalTime", "uint64", o.CanonicalTime},
		{"evidenceHash", "bytes32", o.EvidenceHash}, {"deadline", "uint64", o.Deadline},
	}, generation)
}

func (o DailyOutcome) Validate() error {
	if o.Id == ([32]byte{}) || o.Outcome < 2 || o.Outcome > 4 || o.CanonicalTime == 0 || o.EvidenceHash == ([32]byte{}) || o.Deadline == 0 {
		return fmt.Errorf("invalid daily outcome")
	}
	return nil
}

// DailyBatchHash reproduces keccak256(abi.encode(Outcome[])), including the ABI
// dynamic-array offset. It is not the EIP-712 hash of an array of structs.
func DailyBatchHash(outcomes []DailyOutcome) (common.Hash, error) {
	if len(outcomes) == 0 || len(outcomes) > 16 {
		return common.Hash{}, fmt.Errorf("daily batch needs 1..16 outcomes")
	}
	for _, o := range outcomes {
		if err := o.Validate(); err != nil {
			return common.Hash{}, err
		}
	}
	t, err := abi.NewType("tuple[]", "", []abi.ArgumentMarshaling{
		{Name: "id", Type: "bytes32"}, {Name: "outcome", Type: "uint8"}, {Name: "canonicalTime", Type: "uint64"},
		{Name: "evidenceHash", Type: "bytes32"}, {Name: "deadline", Type: "uint64"},
	})
	if err != nil {
		return common.Hash{}, err
	}
	encoded, err := (abi.Arguments{{Type: t}}).Pack(outcomes)
	if err != nil {
		return common.Hash{}, err
	}
	return crypto.Keccak256Hash(encoded), nil
}

func DailyBatchDigest(chain *big.Int, custody common.Address, outcomes []DailyOutcome, journal common.Hash, deadline uint64, generation *big.Int) (common.Hash, error) {
	if journal == (common.Hash{}) || deadline == 0 {
		return common.Hash{}, fmt.Errorf("missing daily journal/deadline")
	}
	h, err := DailyBatchHash(outcomes)
	if err != nil {
		return common.Hash{}, err
	}
	return TypedDigest(Domain{chain, custody, "FUSE DailyBetCustody"}, "SettlementBatch", []Field{
		{"outcomesHash", "bytes32", h}, {"journalHash", "bytes32", journal}, {"deadline", "uint64", deadline},
	}, generation)
}
