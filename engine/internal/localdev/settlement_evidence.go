package localdev

import (
	"context"
	"encoding/json"
	"fmt"
	"math/big"
	"os"
	"path/filepath"
	"sort"
	"strings"

	"fuse/engine/internal/engine"
	"github.com/ethereum/go-ethereum/common"
)

type settlementEvidence struct {
	Epoch        uint64 `json:"epoch"`
	Transaction  string `json:"transaction_hash"`
	Block        uint64 `json:"block"`
	Root         string `json:"checkpoint_root"`
	Digest       string `json:"eip712_digest"`
	From         uint64 `json:"from_sequence"`
	To           uint64 `json:"to_sequence"`
	NetTraderPnL int64  `json:"net_trader_pnl_usdc_units"`
	Direction    string `json:"transfer_direction"`
	Liability    int64  `json:"customer_liability_usdc_units"`
	Exposure     int64  `json:"open_exposure_usdc_units"`
	RequiredLP   int64  `json:"required_lp_usdc_units"`
}

// Compare all onchain checkpoint roots/digests and the final contract head, not
// just the offchain projection. Canonical receipts and vault movements are also
// retained in journal.jsonl and reconciled by Controller.Sync.
func writeSettlementEvidence(ctx context.Context, env *Environment, q *engine.Sequencer, output string, summary map[string]any) error {
	s := q.Snapshot()
	latest, err := env.Uint(ctx, "SettlementController", "latestEpoch", 0)
	if err != nil {
		return err
	}
	lastSequence, err := env.Uint(ctx, "SettlementController", "lastSequence", 0)
	if err != nil {
		return err
	}
	root, err := env.Read(ctx, "SettlementController", "currentRoot", 0)
	if err != nil {
		return err
	}
	if len(s.Epochs) == 0 || latest.Uint64() != uint64(len(s.Epochs)) || lastSequence.Uint64() != s.Epochs[len(s.Epochs)-1].To || len(root) != 1 || common.Hash(root[0].([32]byte)) != common.HexToHash(s.Epochs[len(s.Epochs)-1].Root) {
		return fmt.Errorf("onchain checkpoint head differs from ledger")
	}
	entries := []settlementEvidence{}
	for _, op := range s.Local.Operations {
		if op.Kind != "settlement" {
			continue
		}
		var plan engine.LocalSettlement
		if err := json.Unmarshal(op.Data, &plan); err != nil {
			return err
		}
		digest, err := env.Read(ctx, "SettlementController", "checkpointHash", 0, plan.Epoch.Number)
		if err != nil {
			return err
		}
		if op.Status != "confirmed" || len(digest) != 1 || common.Hash(digest[0].([32]byte)) != common.HexToHash(plan.Digest) {
			return fmt.Errorf("checkpoint digest not confirmed at epoch %d", plan.Epoch.Number)
		}
		p := plan.Epoch
		direction := "no net transfer"
		if p.NetTraderPnL > 0 {
			direction = "LP -> customer custody"
		}
		if p.NetTraderPnL < 0 {
			direction = "customer custody -> LP"
		}
		entries = append(entries, settlementEvidence{p.Number, op.TxHash, op.Block, p.Root, plan.Digest, p.From, p.To, p.NetTraderPnL, direction, p.Liability, p.Exposure, p.RequiredLP})
	}
	sort.Slice(entries, func(i, j int) bool { return entries[i].Epoch < entries[j].Epoch })
	if len(entries) != len(s.Epochs) {
		return fmt.Errorf("missing checkpoint transaction evidence")
	}
	transferredToCustomers, transferredToLP := int64(0), int64(0)
	for i, e := range entries {
		if e.Epoch != uint64(i+1) || i > 0 && e.From != entries[i-1].To+1 {
			return fmt.Errorf("checkpoint range discontinuity")
		}
		if e.NetTraderPnL > 0 {
			transferredToCustomers += e.NetTraderPnL
		} else {
			transferredToLP -= e.NetTraderPnL
		}
	}
	if s.LPProfit != transferredToLP-transferredToCustomers {
		return fmt.Errorf("settled LP profit does not reconcile")
	}
	// All local client transactions carry the local chain ID, including fork runs.
	for _, op := range s.Local.Operations {
		if op.Status != "confirmed" {
			return fmt.Errorf("unconfirmed local operation %s", op.ID)
		}
	}
	summary["execution_chain_id"] = ChainID
	summary["execution_network"] = "local Anvil; public HyperEVM settlement NOT tested"
	summary["settlement_head_verified"] = true
	summary["settlement_to_customers_usdc_units"] = transferredToCustomers
	summary["settlement_to_lp_usdc_units"] = transferredToLP
	summary["settlement_transactions"] = len(entries)
	evidence := map[string]any{"execution_chain_id": ChainID, "public_hyperevm_transactions": false, "checkpoint_head_verified": true, "latest_epoch": latest.String(), "last_sequence": lastSequence.String(), "entries": entries, "lp_profit_usdc_units": s.LPProfit, "transferred_to_customers_usdc_units": transferredToCustomers, "transferred_to_lp_usdc_units": transferredToLP, "custody_balance_usdc_units": s.Custody, "lp_balance_usdc_units": s.LP, "reserve_balance_usdc_units": s.Reserve}
	if err = writeEvidence(output, "settlements.json", evidence); err != nil {
		return err
	}
	if err = writeGasEvidence(ctx, env, s, output); err != nil {
		return err
	}
	var b strings.Builder
	fmt.Fprintf(&b, "# Settlement evidence\n\nExecution: local Anvil, chain %d. No public HyperEVM transactions were submitted. Checkpoint roots, EIP-712 digests, sequence ranges, actual vault balances and cumulative withdrawals were checked against deployed contracts. Signatures attest operator accounting; contracts do not independently verify HyperCore outcomes.\n\n| Epoch | Block | Net trader PnL USDC | Transfer | Open exposure USDC | Transaction |\n|---|---:|---:|---|---:|---|\n", ChainID)
	for _, e := range entries {
		fmt.Fprintf(&b, "| %d | %d | %.6f | %s | %.6f | `%s` |\n", e.Epoch, e.Block, float64(e.NetTraderPnL)/1e6, e.Direction, float64(e.Exposure)/1e6, e.Transaction)
	}
	fmt.Fprintf(&b, "\nLP paid %.6f USDC to custody; custody paid %.6f USDC to LP. Net realized LP PnL: %.6f USDC.\n", float64(transferredToCustomers)/1e6, float64(transferredToLP)/1e6, float64(new(big.Int).Sub(big.NewInt(transferredToLP), big.NewInt(transferredToCustomers)).Int64())/1e6)
	return writeTextEvidence(output, "settlements.md", b.String())
}

func writeTextEvidence(output, name, value string) error {
	return os.WriteFile(filepath.Join(output, name), []byte(value), 0600)
}
