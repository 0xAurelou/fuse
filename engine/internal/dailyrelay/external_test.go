package dailyrelay

import (
	"math/big"
	"strings"
	"testing"

	"fuse/engine/internal/contracts"
	"github.com/ethereum/go-ethereum/accounts/abi"
	"github.com/ethereum/go-ethereum/common"
	"github.com/ethereum/go-ethereum/core/types"
)

func TestNonceRecoveryRequiresExactSenderNonceAndClassifiesFinancialEffects(t *testing.T) {
	b := replacementFixture(t, "replace")
	r := &Reader{manifest: Manifest{Modules: map[string]ModulePin{"DailyBetCustody": {Module: contracts.Module{Address: b.Intent.Custody}}, "DailyLPVault": {Module: contracts.Module{Address: common.HexToAddress("0x5678")}}, "USDC": {Module: contracts.Module{Address: common.HexToAddress("0x9999")}}}}}
	p := TransactionObservation{Transaction: b.Transaction, Sender: b.Intent.Payer, Nonce: *b.Nonce, Raw: b.Raw, Receipt: &types.Receipt{Status: 1, BlockNumber: big.NewInt(10)}}
	if class, err := r.nonceClass(b, p); err != nil || class != "matching" {
		t.Fatal("exact financial call not recognized", class, err)
	}
	for name, change := range map[string]func(*TransactionObservation){
		"other sender":     func(p *TransactionObservation) { p.Sender = common.HexToAddress("0x4444") },
		"other nonce":      func(p *TransactionObservation) { p.Nonce++ },
		"no receipt block": func(p *TransactionObservation) { p.Receipt = &types.Receipt{Status: 1} },
		"invalid status":   func(p *TransactionObservation) { p.Receipt = &types.Receipt{Status: 2, BlockNumber: big.NewInt(10)} },
		"revert with effects": func(p *TransactionObservation) {
			p.Receipt = &types.Receipt{Status: 0, BlockNumber: big.NewInt(10), Logs: []*types.Log{{}}}
		},
	} {
		t.Run(name, func(t *testing.T) {
			copy := p
			change(&copy)
			if _, err := r.nonceClass(b, copy); err == nil {
				t.Fatal("invalid nonce evidence accepted")
			}
		})
	}
	p.Receipt = &types.Receipt{Status: 0, BlockNumber: big.NewInt(10)}
	if class, err := r.nonceClass(b, p); err != nil || class != "unrelated" {
		t.Fatal("canonical revert consumed nonce as a payment", class, err)
	}
	p.Receipt = &types.Receipt{Status: 1, BlockNumber: big.NewInt(10)}
	changed := b
	changed.Authorization = &Authorized{Data: []byte{9, 9, 9, 9}}
	if _, err := r.nonceClass(changed, p); err == nil {
		t.Fatal("unrecognized successful protocol call classified as unrelated")
	}
}

func TestHistoricalGenerationUsesCompleteOrderedBeforeAndAfterRotations(t *testing.T) {
	a, err := abi.JSON(strings.NewReader(`[{"type":"event","name":"SignerRotated","inputs":[{"name":"role","type":"bytes32","indexed":true},{"name":"authority","type":"address","indexed":true},{"name":"signatureVersion","type":"uint256","indexed":false}]}]`))
	if err != nil {
		t.Fatal(err)
	}
	event := a.Events["SignerRotated"]
	receipt := &types.Receipt{BlockNumber: big.NewInt(10), BlockHash: common.HexToHash("0x111"), TransactionIndex: 1}
	rotation := func(version int64, index uint) *types.Log {
		data, err := event.Inputs.NonIndexed().Pack(big.NewInt(version))
		if err != nil {
			t.Fatal(err)
		}
		return &types.Log{BlockNumber: 10, BlockHash: receipt.BlockHash, TxIndex: index, Index: index + 10, Topics: []common.Hash{event.ID, {}, {}}, Data: data}
	}
	before, after := rotation(6, 0), rotation(7, 2)
	logs := []types.Log{*after, *before}
	got, err := generationFromRotations(big.NewInt(5), big.NewInt(7), receipt, logs, event.ID, event.Inputs.NonIndexed().Unpack)
	if err != nil || got.Int64() != 6 {
		t.Fatal("end-of-block generation incorrectly applied to earlier transaction", got, err)
	}
	for name, change := range map[string]func([]types.Log) []types.Log{
		"missing rotation":          func(l []types.Log) []types.Log { return l[:1] },
		"duplicate index":           func(l []types.Log) []types.Log { l[1].Index = l[0].Index; return l },
		"removed event":             func(l []types.Log) []types.Log { l[0].Removed = true; return l },
		"same transaction rotation": func(l []types.Log) []types.Log { l[0].TxIndex = receipt.TransactionIndex; return l },
		"wrong block":               func(l []types.Log) []types.Log { l[0].BlockHash = common.HexToHash("0x222"); return l },
	} {
		t.Run(name, func(t *testing.T) {
			copy := []types.Log{*before, *after}
			copy = change(copy)
			if _, err := generationFromRotations(big.NewInt(5), big.NewInt(7), receipt, copy, event.ID, event.Inputs.NonIndexed().Unpack); err == nil {
				t.Fatal("incomplete/inconsistent signer history accepted")
			}
		})
	}
}
