package dailyrelay

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"math/big"

	"fuse/engine/internal/contracts"
	"github.com/ethereum/go-ethereum/common"
	"github.com/ethereum/go-ethereum/core/types"
	"github.com/ethereum/go-ethereum/crypto"
)

type SettlementProof struct {
	ChainID     uint64         `json:"chain_id"`
	Custody     common.Address `json:"custody"`
	Transaction common.Hash    `json:"transaction"`
	Block       uint64         `json:"block"`
	BlockHash   common.Hash    `json:"block_hash"`
	Digest      common.Hash    `json:"digest"`
	JournalHash common.Hash    `json:"journal_hash"`
	Tickets     []common.Hash  `json:"tickets"`
	LPNetUSDC   string         `json:"lp_net_usdc_units"`
	verified    common.Hash
}

func (p SettlementProof) identityHash() common.Hash {
	raw, _ := json.Marshal(p)
	return crypto.Keccak256Hash(raw)
}
func (p SettlementProof) validProof() bool {
	return p.verified != (common.Hash{}) && p.verified == p.identityHash()
}

// ReconcileBatch requires the exact replay prefix used by the authorization.
// Receipt status or a resolved storage flag alone is insufficient: verify the
// signed batch marker, every original-owner outcome and actual net token move.
func (r *Reader) ReconcileBatch(ctx context.Context, j *Journal, bindings []Binding, a Authorized, tx common.Hash) (SettlementProof, error) {
	if j == nil || a.Action.Kind != "batch" || a.ChainID != r.manifest.ChainID || a.Custody != r.manifest.Modules["DailyBetCustody"].Address || a.JournalHash != common.HexToHash(j.state.JournalHash) || len(bindings) != len(a.Action.Outcomes) || len(bindings) == 0 || tx == (common.Hash{}) {
		return SettlementProof{}, fmt.Errorf("incomplete daily settlement evidence")
	}
	s, err := r.Snapshot(ctx)
	if err != nil {
		return SettlementProof{}, err
	}
	if err = r.stable(ctx, Snapshot{Number: a.VerifiedBlock, Hash: a.VerifiedHash}); err != nil {
		return SettlementProof{}, err
	}
	gen, ok := new(big.Int).SetString(a.Generation, 10)
	if !ok || gen.Sign() <= 0 || gen.Cmp(s.Generation) > 0 || gen.String() != a.Generation {
		return SettlementProof{}, fmt.Errorf("invalid settlement generation")
	}
	digest, err := contracts.DailyBatchDigest(new(big.Int).SetUint64(a.ChainID), a.Custody, a.Action.Outcomes, a.JournalHash, a.Action.Deadline, gen)
	if err != nil {
		return SettlementProof{}, err
	}
	if digest != a.Action.Digest || digest != a.Action.OnchainDigest {
		return SettlementProof{}, fmt.Errorf("daily settlement authorization digest changed")
	}
	expectedData, err := r.abis["DailyBetCustody"].Pack("settleBatch", a.Action.Outcomes, a.JournalHash, a.Action.Deadline, a.SettlementSignature, a.RiskSignature)
	if err != nil {
		return SettlementProof{}, err
	}
	if !bytes.Equal(expectedData, a.Data) {
		return SettlementProof{}, fmt.Errorf("daily authorized calldata changed")
	}
	byID := map[common.Hash]Binding{}
	expectedNet := new(big.Int)
	pnlByID := map[common.Hash]*big.Int{}
	for _, b := range bindings {
		current, err := r.bind(ctx, s, j, b.StageID, b.TicketID, b.TxHash, b.Generation)
		if err != nil {
			return SettlementProof{}, err
		}
		if current.identityHash() != b.identityHash() {
			return SettlementProof{}, fmt.Errorf("daily settlement binding changed")
		}
		if _, exists := byID[b.TicketID]; exists {
			return SettlementProof{}, fmt.Errorf("duplicate daily proof binding")
		}
		byID[b.TicketID] = b
	}
	if len(a.Action.Tickets) != len(a.Action.Outcomes) {
		return SettlementProof{}, fmt.Errorf("daily receipt ticket metadata mismatch")
	}
	for i, o := range a.Action.Outcomes {
		if a.Action.Tickets[i] != common.Hash(o.Id) {
			return SettlementProof{}, fmt.Errorf("daily receipt ticket metadata mismatch")
		}
		b, exists := byID[o.Id]
		if !exists || pnlByID[o.Id] != nil {
			return SettlementProof{}, fmt.Errorf("daily authorization ticket set mismatch")
		}
		native, err := j.Outcome(b.StageID)
		if err != nil {
			return SettlementProof{}, err
		}
		raw, _ := json.Marshal(struct {
			Binding Binding
			Outcome any
		}{b, native})
		if o.Outcome != native.Outcome || o.CanonicalTime != uint64(native.CanonicalMS) || o.EvidenceHash != crypto.Keccak256Hash(raw) || o.Deadline != a.Action.Deadline {
			return SettlementProof{}, fmt.Errorf("daily receipt source outcome mismatch")
		}
		pnl := big.NewInt(native.LPPnL)
		pnlByID[o.Id] = pnl
		expectedNet.Add(expectedNet, pnl)
	}
	var receipt types.Receipt
	if err = r.rpc.ReadRPC(ctx, "eth_getTransactionReceipt", []any{tx}, &receipt); err != nil {
		return SettlementProof{}, err
	}
	if receipt.TxHash != tx || receipt.Status != 1 || receipt.BlockNumber == nil || !receipt.BlockNumber.IsUint64() {
		return SettlementProof{}, fmt.Errorf("daily settlement receipt failed or unavailable")
	}
	n := receipt.BlockNumber.Uint64()
	if n > s.Number {
		return SettlementProof{}, contracts.ErrAwaitFinality
	}
	h, err := r.header(ctx, n)
	if err != nil {
		return SettlementProof{}, err
	}
	if h.Hash != receipt.BlockHash {
		return SettlementProof{}, contracts.ErrFinalityReorg
	}
	batchEvent := r.abis["DailyBetCustody"].Events["BatchSettled"]
	outcomeEvent := r.abis["DailyLPVault"].Events["OutcomeRecorded"]
	if batchEvent.Sig != "BatchSettled(bytes32,bytes32,int256,uint256)" || outcomeEvent.Sig != "OutcomeRecorded(bytes32,uint8,uint64,int256)" {
		return SettlementProof{}, fmt.Errorf("daily reconciliation event ABI mismatch")
	}
	markers, movements := 0, 0
	seen := map[common.Hash]bool{}
	transfer := crypto.Keccak256Hash([]byte("Transfer(address,address,uint256)"))
	vault := r.manifest.Modules["DailyLPVault"].Address
	wantFrom, wantTo := a.Custody, vault
	if expectedNet.Sign() < 0 {
		wantFrom, wantTo = vault, a.Custody
	}
	for _, log := range receipt.Logs {
		if log.Removed || log.TxHash != tx || log.BlockNumber != n || log.BlockHash != receipt.BlockHash || log.TxIndex != receipt.TransactionIndex {
			return SettlementProof{}, fmt.Errorf("invalid daily receipt log identity")
		}
		if len(log.Topics) == 0 {
			continue
		}
		if log.Address == a.Custody && log.Topics[0] == batchEvent.ID {
			if len(log.Topics) != 3 || log.Topics[1] != digest || log.Topics[2] != a.JournalHash {
				return SettlementProof{}, fmt.Errorf("daily batch marker mismatch")
			}
			v, err := batchEvent.Inputs.NonIndexed().Unpack(log.Data)
			if err != nil {
				return SettlementProof{}, err
			}
			if v[0].(*big.Int).Cmp(expectedNet) != 0 || v[1].(*big.Int).Cmp(big.NewInt(int64(len(bindings)))) != 0 {
				return SettlementProof{}, fmt.Errorf("daily batch net/count mismatch")
			}
			markers++
		}
		if log.Address == vault && log.Topics[0] == outcomeEvent.ID {
			if len(log.Topics) != 2 || seen[log.Topics[1]] || pnlByID[log.Topics[1]] == nil {
				return SettlementProof{}, fmt.Errorf("daily original-owner outcome event mismatch")
			}
			id := log.Topics[1]
			v, err := outcomeEvent.Inputs.NonIndexed().Unpack(log.Data)
			if err != nil {
				return SettlementProof{}, err
			}
			native, err := j.Outcome(byID[id].StageID)
			if err != nil {
				return SettlementProof{}, err
			}
			if v[0].(uint8) != native.Outcome || v[1].(uint64) != uint64(native.CanonicalMS) || v[2].(*big.Int).Cmp(pnlByID[id]) != 0 {
				return SettlementProof{}, fmt.Errorf("daily emitted outcome/PnL differs from shared engine")
			}
			seen[id] = true
		}
		if log.Address == r.manifest.Modules["USDC"].Address && log.Topics[0] == transfer {
			if len(log.Topics) != 3 || len(log.Data) != 32 {
				return SettlementProof{}, fmt.Errorf("invalid daily USDC movement")
			}
			from, to := common.BytesToAddress(log.Topics[1].Bytes()), common.BytesToAddress(log.Topics[2].Bytes())
			if from != vault && to != vault && from != a.Custody && to != a.Custody {
				continue
			}
			if expectedNet.Sign() == 0 || from != wantFrom || to != wantTo || new(big.Int).SetBytes(log.Data).Cmp(new(big.Int).Abs(expectedNet)) != 0 {
				return SettlementProof{}, fmt.Errorf("daily physical USDC transfer mismatch")
			}
			movements++
		}
	}
	wantMovements := 1
	if expectedNet.Sign() == 0 {
		wantMovements = 0
	}
	if markers != 1 || len(seen) != len(bindings) || movements != wantMovements {
		return SettlementProof{}, fmt.Errorf("incomplete daily settlement receipt")
	}
	if err = r.stable(ctx, s); err != nil {
		return SettlementProof{}, err
	}
	proof := SettlementProof{ChainID: a.ChainID, Custody: a.Custody, Transaction: tx, Block: n, BlockHash: receipt.BlockHash, Digest: digest, JournalHash: a.JournalHash, Tickets: append([]common.Hash{}, a.Action.Tickets...), LPNetUSDC: expectedNet.String()}
	proof.verified = proof.identityHash()
	return proof, nil
}
