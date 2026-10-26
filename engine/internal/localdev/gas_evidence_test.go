package localdev

import (
	"math/big"
	"testing"

	"fuse/engine/internal/engine"
	"github.com/ethereum/go-ethereum/common"
	"github.com/ethereum/go-ethereum/core/types"
)

func TestGasEvidenceUsesCanonicalReceiptAndExactNativeUnits(t *testing.T) {
	hash, block := common.HexToHash("0x123"), common.HexToHash("0x456")
	op := &engine.LocalOperation{ID: "s1", Kind: "settlement", Status: "confirmed", TxHash: hash.Hex(), Block: 7}
	r := &types.Receipt{Status: 1, TxHash: hash, BlockNumber: big.NewInt(7), BlockHash: block, GasUsed: 123456, EffectiveGasPrice: big.NewInt(1000000001)}
	row, err := projectGasReceipt(op, r, block)
	if err != nil {
		t.Fatal(err)
	}
	if row.FeeWei != "123456000123456" || row.GasUsed != 123456 {
		t.Fatalf("wrong fee %+v", row)
	}
	for _, mutate := range []func(*types.Receipt){
		func(r *types.Receipt) { r.Status = 0 },
		func(r *types.Receipt) { r.BlockHash = common.Hash{} },
		func(r *types.Receipt) { r.BlockNumber = big.NewInt(8) },
		func(r *types.Receipt) { r.TxHash = common.Hash{} },
		func(r *types.Receipt) { r.EffectiveGasPrice = nil },
	} {
		bad := *r
		mutate(&bad)
		if _, err := projectGasReceipt(op, &bad, block); err == nil {
			t.Fatal("accepted unverified receipt")
		}
	}
}
