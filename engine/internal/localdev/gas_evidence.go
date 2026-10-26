package localdev

import (
	"context"
	"fmt"
	"math/big"
	"sort"

	"fuse/engine/internal/engine"
	"github.com/ethereum/go-ethereum/common"
	"github.com/ethereum/go-ethereum/core/types"
)

type gasReceiptEvidence struct {
	Operation            string `json:"operation"`
	Kind                 string `json:"kind"`
	Transaction          string `json:"transaction_hash"`
	Block                uint64 `json:"block"`
	BlockHash            string `json:"block_hash"`
	GasUsed              uint64 `json:"gas_used"`
	EffectiveGasPriceWei string `json:"effective_gas_price_wei"`
	FeeWei               string `json:"execution_fee_wei"`
}

func projectGasReceipt(op *engine.LocalOperation, r *types.Receipt, canonical common.Hash) (gasReceiptEvidence, error) {
	if op == nil || canonical == (common.Hash{}) || op.Status != "confirmed" || r == nil || r.Status != types.ReceiptStatusSuccessful ||
		r.BlockNumber == nil || !r.BlockNumber.IsUint64() || r.BlockNumber.Uint64() != op.Block ||
		r.TxHash != common.HexToHash(op.TxHash) || r.BlockHash != canonical ||
		r.GasUsed == 0 || r.EffectiveGasPrice == nil || r.EffectiveGasPrice.Sign() < 0 {
		return gasReceiptEvidence{}, fmt.Errorf("unverified gas receipt for %s", op.ID)
	}
	fee := new(big.Int).Mul(new(big.Int).SetUint64(r.GasUsed), r.EffectiveGasPrice)
	return gasReceiptEvidence{op.ID, op.Kind, op.TxHash, op.Block, r.BlockHash.Hex(), r.GasUsed, r.EffectiveGasPrice.String(), fee.String()}, nil
}

// Native execution fees for coordinator-managed operations only. Wallet direct
// transactions, deployment and infrastructure are deliberately outside coverage.
// No native/USD quote or public-network cost is inferred from local Anvil gas.
func writeGasEvidence(ctx context.Context, env *Environment, s engine.State, output string) error {
	ids := make([]string, 0, len(s.Local.Operations))
	for id := range s.Local.Operations {
		ids = append(ids, id)
	}
	sort.Strings(ids)
	rows := make([]gasReceiptEvidence, 0, len(ids))
	total := new(big.Int)
	seen := map[string]bool{}
	for _, id := range ids {
		op := s.Local.Operations[id]
		if seen[op.TxHash] {
			return fmt.Errorf("duplicate operation transaction in gas evidence")
		}
		seen[op.TxHash] = true
		r, err := env.RPC.Receipt(ctx, common.HexToHash(op.TxHash))
		if err != nil {
			return err
		}
		header, err := env.RPC.Header(ctx, op.Block)
		if err != nil {
			return err
		}
		row, err := projectGasReceipt(op, r, header.Hash)
		if err != nil {
			return err
		}
		rows = append(rows, row)
		n, _ := new(big.Int).SetString(row.FeeWei, 10)
		total.Add(total, n)
	}
	return writeEvidence(output, "gas-receipts.json", map[string]any{
		"execution_chain_id":             ChainID,
		"scope":                          "coordinator operations only; excludes direct wallet/setup/deployment transactions and infrastructure",
		"public_hyperevm_costs_measured": false,
		"native_usd_price_supplied":      false,
		"total_execution_fee_wei":        total.String(),
		"entries":                        rows,
	})
}
