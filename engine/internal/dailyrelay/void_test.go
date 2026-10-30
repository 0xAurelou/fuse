package dailyrelay

import (
	"math/big"
	"strings"
	"testing"

	"fuse/engine/internal/contracts"
	"fuse/engine/internal/engine"
	"github.com/ethereum/go-ethereum/accounts/abi"
	"github.com/ethereum/go-ethereum/common"
	"github.com/ethereum/go-ethereum/core/types"
	"github.com/ethereum/go-ethereum/crypto"
)

func TestVoidReceiptSeparatesObligationFromCreditAndRejectsPoolMovement(t *testing.T) {
	a, err := abi.JSON(strings.NewReader(`[
{"type":"event","name":"FinalVoidQueued","inputs":[{"name":"id","type":"bytes32","indexed":true},{"name":"canonicalTime","type":"uint64","indexed":false}]},
{"type":"event","name":"OutcomeRecorded","inputs":[{"name":"id","type":"bytes32","indexed":true},{"name":"outcome","type":"uint8","indexed":false},{"name":"canonicalTime","type":"uint64","indexed":false},{"name":"lpPnL","type":"int256","indexed":false}]},
{"type":"event","name":"TicketResolved","inputs":[{"name":"id","type":"bytes32","indexed":true},{"name":"outcome","type":"uint8","indexed":false},{"name":"canonicalTime","type":"uint64","indexed":false},{"name":"evidenceHash","type":"bytes32","indexed":false}]},
{"type":"event","name":"BatchSettled","inputs":[{"name":"digest","type":"bytes32","indexed":true},{"name":"journalHash","type":"bytes32","indexed":true},{"name":"lpNet","type":"int256","indexed":false},{"name":"count","type":"uint256","indexed":false}]}
]`))
	if err != nil {
		t.Fatal(err)
	}
	vault, custody, usdc := common.HexToAddress("0x100"), common.HexToAddress("0x200"), common.HexToAddress("0x300")
	r := &Reader{manifest: Manifest{Modules: map[string]ModulePin{"DailyLPVault": {Module: contracts.Module{Address: vault}}, "DailyBetCustody": {Module: contracts.Module{Address: custody}}, "USDC": {Module: contracts.Module{Address: usdc}}}}, abis: map[string]abi.ABI{"DailyLPVault": a, "DailyBetCustody": a}}
	id, blockHash, txHash := common.HexToHash("0x1"), common.HexToHash("0x2"), common.HexToHash("0x3")
	canonical := uint64(86_400_020_000)
	log := func(address common.Address, name string, args ...any) *types.Log {
		t.Helper()
		event := a.Events[name]
		data, err := event.Inputs.NonIndexed().Pack(args...)
		if err != nil {
			t.Fatal(err)
		}
		return &types.Log{Address: address, Topics: []common.Hash{event.ID, id}, Data: data, BlockHash: blockHash, BlockNumber: 10, TxHash: txHash}
	}
	queue := &types.Receipt{Status: 1, TxHash: txHash, BlockNumber: big.NewInt(10), BlockHash: blockHash, Logs: []*types.Log{log(vault, "FinalVoidQueued", canonical)}}
	refund := &types.Receipt{Status: 1, TxHash: txHash, BlockNumber: big.NewInt(10), BlockHash: blockHash, Logs: []*types.Log{log(vault, "OutcomeRecorded", uint8(4), canonical, big.NewInt(0)), log(custody, "TicketResolved", uint8(4), canonical, [32]byte{})}}
	if err = checkVoidReceipt(r, queue, id, canonical, false); err != nil {
		t.Fatal(err)
	}
	if err = checkVoidReceipt(r, refund, id, canonical, true); err != nil {
		t.Fatal(err)
	}
	if checkVoidReceipt(r, queue, id, canonical, true) == nil || checkVoidReceipt(r, refund, id, canonical, false) == nil {
		t.Fatal("obligation and completed credit became interchangeable")
	}
	for name, change := range map[string]func(*types.Receipt){
		"missing custody credit event": func(p *types.Receipt) { p.Logs = p.Logs[:1] },
		"duplicate outcome":            func(p *types.Receipt) { p.Logs = append(p.Logs, p.Logs[0]) },
		"wrong final day": func(p *types.Receipt) {
			p.Logs[0] = log(vault, "OutcomeRecorded", uint8(4), canonical-86_400_000, big.NewInt(0))
		},
		"invented LP profit": func(p *types.Receipt) { p.Logs[0] = log(vault, "OutcomeRecorded", uint8(4), canonical, big.NewInt(1)) },
		"different ticket":   func(p *types.Receipt) { p.Logs[0].Topics[1] = common.HexToHash("0x4") },
		"removed log":        func(p *types.Receipt) { p.Logs[0].Removed = true },
		"replaced block":     func(p *types.Receipt) { p.Logs[0].BlockHash = common.HexToHash("0x5") },
		"nil log":            func(p *types.Receipt) { p.Logs = append(p.Logs, nil) },
		"physical pool transfer": func(p *types.Receipt) {
			data := make([]byte, 32)
			data[31] = 1
			p.Logs = append(p.Logs, &types.Log{Address: usdc, Topics: []common.Hash{crypto.Keccak256Hash([]byte("Transfer(address,address,uint256)")), common.BytesToHash(custody.Bytes()), common.BytesToHash(vault.Bytes())}, Data: data, BlockNumber: 10, BlockHash: blockHash, TxHash: txHash})
		},
	} {
		t.Run(name, func(t *testing.T) {
			copy := *refund
			copy.Logs = nil
			for _, original := range refund.Logs {
				l := *original
				l.Topics = append([]common.Hash{}, original.Topics...)
				l.Data = append([]byte{}, original.Data...)
				copy.Logs = append(copy.Logs, &l)
			}
			change(&copy)
			if checkVoidReceipt(r, &copy, id, canonical, true) == nil {
				t.Fatal("invalid refund receipt passed")
			}
		})
	}
}

func TestVoidDecisionSurvivesLaterJournalButNotChangedOwnerStakeOrTime(t *testing.T) {
	a := engine.SettlementOutcome{Rule: "shared-engine-outcome-v1", StageID: "stage-1", Account: "alice", Outcome: 4, CanonicalMS: 100000, ObservedMS: 100000, Stake: 10000000, Payout: 10000000, JournalHash: "old", OracleCommitment: "old-oracle"}
	b := a
	b.JournalHash = "new"
	b.OracleCommitment = "new-oracle"
	if !sameVoidDecision(a, b) {
		t.Fatal("later unrelated journal changed a final obligation")
	}
	for _, change := range []func(*engine.SettlementOutcome){func(n *engine.SettlementOutcome) { n.Account = "bob" }, func(n *engine.SettlementOutcome) { n.Stake++ }, func(n *engine.SettlementOutcome) { n.Payout++ }, func(n *engine.SettlementOutcome) { n.CanonicalMS++ }, func(n *engine.SettlementOutcome) { n.ObservedMS++ }, func(n *engine.SettlementOutcome) { n.Outcome = 2 }} {
		changed := b
		change(&changed)
		if sameVoidDecision(a, changed) {
			t.Fatal("changed obligation accepted as original final decision")
		}
	}
}
