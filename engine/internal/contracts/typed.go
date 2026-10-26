// Package contracts contains exact, keyless encodings for the compiled FUSE contracts.
package contracts

import (
	"context"
	"fmt"
	"math/big"

	"github.com/ethereum/go-ethereum/accounts/abi"
	"github.com/ethereum/go-ethereum/common"
	"github.com/ethereum/go-ethereum/crypto"
)

type Domain struct {
	ChainID  *big.Int
	Contract common.Address
	Name     string
}
type Field struct {
	Name  string
	Type  string
	Value any
}

// Signer must be implemented by controlled signing infrastructure. This package
// deliberately supplies no private-key, default signer or transaction sender.
type Signer interface {
	SignDigest(context.Context, string, common.Hash) ([]byte, error)
}
type DigestVerifier interface {
	HashOnchain(context.Context, string, any) (common.Hash, error)
}

func pack(fields []Field) ([]byte, error) {
	args := abi.Arguments{}
	values := []any{}
	for _, f := range fields {
		if f.Type == "uint256" || f.Type == "int256" {
			v, ok := f.Value.(*big.Int)
			if !ok || v == nil {
				return nil, fmt.Errorf("missing integer %s", f.Name)
			}
			if f.Type == "uint256" && (v.Sign() < 0 || v.BitLen() > 256) {
				return nil, fmt.Errorf("uint256 overflow %s", f.Name)
			}
			if f.Type == "int256" {
				bound := new(big.Int).Lsh(big.NewInt(1), 255)
				if v.Cmp(new(big.Int).Neg(bound)) < 0 || v.Cmp(new(big.Int).Sub(new(big.Int).Lsh(big.NewInt(1), 255), big.NewInt(1))) > 0 {
					return nil, fmt.Errorf("int256 overflow %s", f.Name)
				}
			}
		}
		if f.Type == "uint256[]" {
			for _, v := range f.Value.([]*big.Int) {
				if v == nil || v.Sign() < 0 || v.BitLen() > 256 {
					return nil, fmt.Errorf("invalid deposit integer")
				}
			}
		}
		t, err := abi.NewType(f.Type, "", nil)
		if err != nil {
			return nil, err
		}
		args = append(args, abi.Argument{Name: f.Name, Type: t})
		values = append(values, f.Value)
	}
	return args.Pack(values...)
}
func TypedDigest(d Domain, name string, fields []Field, signatureVersion *big.Int) (common.Hash, error) {
	if d.ChainID == nil || d.ChainID.Sign() <= 0 || d.ChainID.BitLen() > 256 || d.Contract == (common.Address{}) || signatureVersion == nil || signatureVersion.Sign() <= 0 || signatureVersion.BitLen() > 256 {
		return common.Hash{}, fmt.Errorf("invalid signing domain/generation")
	}
	fields = append(append([]Field{}, fields...), Field{"signatureVersion", "uint256", signatureVersion})
	schema := name + "("
	for i, f := range fields {
		if i > 0 {
			schema += ","
		}
		schema += f.Type + " " + f.Name
	}
	schema += ")"
	structFields := append([]Field{{"typeHash", "bytes32", crypto.Keccak256Hash([]byte(schema))}}, fields...)
	encoded, err := pack(structFields)
	if err != nil {
		return common.Hash{}, err
	}
	structHash := crypto.Keccak256Hash(encoded)
	encoded, err = pack([]Field{{"typeHash", "bytes32", crypto.Keccak256Hash([]byte("EIP712Domain(string name,string version,uint256 chainId,address verifyingContract)"))}, {"name", "bytes32", crypto.Keccak256Hash([]byte(d.Name))}, {"version", "bytes32", crypto.Keccak256Hash([]byte("1"))}, {"chainId", "uint256", d.ChainID}, {"verifyingContract", "address", d.Contract}})
	if err != nil {
		return common.Hash{}, err
	}
	domainHash := crypto.Keccak256Hash(encoded)
	return crypto.Keccak256Hash([]byte{0x19, 0x01}, domainHash[:], structHash[:]), nil
}

type Withdrawal struct {
	Account, Recipient       common.Address
	Cumulative               *big.Int
	StateVersion, ValidUntil uint64
	ID, AccountStateHash     common.Hash
}

func (w Withdrawal) Digest(chain *big.Int, gateway common.Address, generation *big.Int) (common.Hash, error) {
	return TypedDigest(Domain{chain, gateway, "FUSE WithdrawalGateway"}, "WithdrawalAuthorization", []Field{{"account", "address", w.Account}, {"recipient", "address", w.Recipient}, {"cumulativeAmountUSDC", "uint256", w.Cumulative}, {"stateVersion", "uint64", w.StateVersion}, {"validUntil", "uint64", w.ValidUntil}, {"authorizationId", "bytes32", w.ID}, {"accountStateHash", "bytes32", w.AccountStateHash}}, generation)
}

type Settlement struct {
	Epoch                                                         uint64
	PriorRoot, NewRoot, JournalHash, OracleJournalHash            common.Hash
	From, To, AsOf                                                uint64
	NetPnL, CustomerLiability, MaxExposure, RequiredLP, ProfitHWM *big.Int
	DepositBatchHash                                              common.Hash
	Deadline                                                      *big.Int
}

func (s Settlement) Digest(chain *big.Int, controller common.Address, generation *big.Int) (common.Hash, error) {
	return TypedDigest(Domain{chain, controller, "FUSE SettlementController"}, "EpochSettlement", []Field{{"epoch", "uint64", s.Epoch}, {"priorRoot", "bytes32", s.PriorRoot}, {"newRoot", "bytes32", s.NewRoot}, {"journalHash", "bytes32", s.JournalHash}, {"oracleJournalHash", "bytes32", s.OracleJournalHash}, {"fromSequence", "uint64", s.From}, {"toSequence", "uint64", s.To}, {"asOfTimestamp", "uint64", s.AsOf}, {"netTraderPnLUSDC", "int256", s.NetPnL}, {"customerLiabilityUSDC", "uint256", s.CustomerLiability}, {"reportedMaxOpenExposureUSDC", "uint256", s.MaxExposure}, {"reportedRequiredLPCapitalUSDC", "uint256", s.RequiredLP}, {"realizedProfitHWMUSDC", "uint256", s.ProfitHWM}, {"depositBatchHash", "bytes32", s.DepositBatchHash}, {"deadline", "uint256", s.Deadline}}, generation)
}

type ReserveAuthorization struct {
	Epoch                    uint64
	Root                     common.Hash
	Amount, MinLP, ProfitHWM *big.Int
	ID                       common.Hash
	Deadline                 *big.Int
}

func (r ReserveAuthorization) Digest(chain *big.Int, vault common.Address, generation *big.Int) (common.Hash, error) {
	return TypedDigest(Domain{chain, vault, "FUSE LPVault"}, "ReserveAuthorization", []Field{{"epoch", "uint64", r.Epoch}, {"checkpointRoot", "bytes32", r.Root}, {"amountUSDC", "uint256", r.Amount}, {"minLPCapitalUSDC", "uint256", r.MinLP}, {"realizedProfitHWMUSDC", "uint256", r.ProfitHWM}, {"authorizationId", "bytes32", r.ID}, {"deadline", "uint256", r.Deadline}}, generation)
}
func DepositBatchHash(ids []*big.Int) (common.Hash, error) {
	if ids == nil {
		ids = []*big.Int{}
	}
	encoded, err := pack([]Field{{"depositIds", "uint256[]", ids}})
	if err != nil {
		return common.Hash{}, err
	}
	return crypto.Keccak256Hash(encoded), nil
}
func RewardLeaf(chain *big.Int, distributor common.Address, epoch uint64, index *big.Int, account common.Address, amount *big.Int) (common.Hash, error) {
	encoded, err := pack([]Field{{"chainId", "uint256", chain}, {"distributor", "address", distributor}, {"epoch", "uint64", epoch}, {"index", "uint256", index}, {"recipient", "address", account}, {"amount", "uint256", amount}})
	if err != nil {
		return common.Hash{}, err
	}
	return crypto.Keccak256Hash(crypto.Keccak256(encoded)), nil
}

// CheckedSign requires an independently obtained contract digest before invoking
// the external signer; a mismatched ABI/domain cannot silently receive a signature.
func CheckedSign(ctx context.Context, signer Signer, role string, local, onchain common.Hash) ([]byte, error) {
	if signer == nil || local == (common.Hash{}) || local != onchain {
		return nil, fmt.Errorf("signing refused: contract digest mismatch or unavailable signer")
	}
	return signer.SignDigest(ctx, role, local)
}

// LPCapacity binds admission demand to a confirmed settlement and a short validity window.
type LPCapacity struct {
	Epoch                           uint64
	Root                            common.Hash
	EligibleDemand, Nonce, Deadline *big.Int
}

func (r LPCapacity) Digest(chain *big.Int, vault common.Address, generation *big.Int) (common.Hash, error) {
	return TypedDigest(Domain{chain, vault, "FUSE LPShareVault"}, "CapacityAuthorization", []Field{
		{"epoch", "uint64", r.Epoch}, {"checkpointRoot", "bytes32", r.Root},
		{"eligibleDemandUSDC", "uint256", r.EligibleDemand}, {"nonce", "uint256", r.Nonce}, {"deadline", "uint256", r.Deadline},
	}, generation)
}

// LPUtilization reports real accepted underwriting liability-time; capital-time is onchain.
type LPUtilization struct {
	Epoch            uint64
	LiabilitySeconds *big.Int
	JournalHash      common.Hash
	Deadline         *big.Int
}

func (r LPUtilization) Digest(chain *big.Int, distributor common.Address, generation *big.Int) (common.Hash, error) {
	return TypedDigest(Domain{chain, distributor, "FUSE LPIncentives"}, "LPUtilizationReport", []Field{
		{"epoch", "uint64", r.Epoch}, {"liabilitySeconds", "uint256", r.LiabilitySeconds},
		{"journalHash", "bytes32", r.JournalHash}, {"deadline", "uint256", r.Deadline},
	}, generation)
}
