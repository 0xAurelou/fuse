package contracts

import (
	"context"
	"errors"
	"math/big"
	"strings"
	"testing"

	"github.com/ethereum/go-ethereum/accounts/abi"
	"github.com/ethereum/go-ethereum/common"
)

type fakeChain struct {
	head    uint64
	headers map[uint64]Header
	logs    []Log
}

func (f fakeChain) ChainID(context.Context) (uint64, error)                       { return 998, nil }
func (f fakeChain) Head(context.Context) (uint64, error)                          { return f.head, nil }
func (f fakeChain) Header(_ context.Context, n uint64) (Header, error)            { return f.headers[n], nil }
func (f fakeChain) Logs(context.Context, uint64, []common.Address) ([]Log, error) { return f.logs, nil }
func TestIndexerConfirmationsDuplicateAndFinalizedReorg(t *testing.T) {
	compiled, err := abi.JSON(strings.NewReader(`[{"type":"event","name":"DepositCredited","inputs":[{"name":"id","type":"uint256","indexed":true},{"name":"epoch","type":"uint64","indexed":true}]}]`))
	if err != nil {
		t.Fatal(err)
	}
	address := common.HexToAddress("0x100")
	h1, h2 := common.HexToHash("0x01"), common.HexToHash("0x02")
	l := Log{Address: address, Block: 2, BlockHash: h2, TxHash: common.HexToHash("0x03"), Topics: []common.Hash{compiled.Events["DepositCredited"].ID, common.BigToHash(big.NewInt(1)), common.BigToHash(big.NewInt(7))}}
	chain := fakeChain{head: 4, headers: map[uint64]Header{1: {1, h1, common.Hash{}}, 2: {2, h2, h1}}, logs: []Log{l, l}}
	i := Indexer{Manifest: Manifest{ChainID: 998, Confirmations: 2, Modules: map[string]Module{"CustomerCustodyVault": {Address: address}}}, ABIs: map[string]abi.ABI{"CustomerCustodyVault": compiled}, Reader: chain}
	block, err := i.Next(context.Background(), Cursor{1, h1})
	if err != nil || len(block.Events) != 1 || block.Events[0].Event != "DepositCredited" {
		t.Fatal(block, err)
	}
	if _, err = i.Next(context.Background(), Cursor{2, h2}); !errors.Is(err, ErrAwaitFinality) {
		t.Fatal(err)
	}
	chain.headers[1] = Header{1, common.HexToHash("0xff"), common.Hash{}}
	if _, err = i.Next(context.Background(), Cursor{1, h1}); !errors.Is(err, ErrFinalityReorg) {
		t.Fatal("reorg did not halt", err)
	}
}
