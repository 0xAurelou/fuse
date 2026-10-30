package dailyrelay

import (
	"context"
	"encoding/json"
	"errors"
	"math/big"
	"testing"

	"github.com/ethereum/go-ethereum/common"
	"github.com/ethereum/go-ethereum/core/types"
	"github.com/ethereum/go-ethereum/crypto"
)

func replacementFixture(t *testing.T, kind string) Outbound {
	t.Helper()
	key, err := crypto.HexToECDSA("0000000000000000000000000000000000000000000000000000000000000007")
	if err != nil {
		t.Fatal(err)
	}
	nonce := uint64(19)
	b := Outbound{Intent: OutboundIntent{ChainID: 31337, Payer: crypto.PubkeyToAddress(key.PublicKey), Custody: common.HexToAddress("0x1234"), Terms: TransactionTerms{Gas: 1_000_000, FeeCap: big.NewInt(3_000_000_000), TipCap: big.NewInt(1_000_000_000)}}, Nonce: &nonce, Authorization: &Authorized{Data: []byte{1, 2, 3, 4}}}
	b.ID = b.Intent.id()
	unsigned := unsignedTransaction(b)
	b.Unsigned, _ = unsigned.MarshalBinary()
	tx, err := types.SignTx(unsigned, types.LatestSignerForChainID(big.NewInt(31337)), key)
	if err != nil {
		t.Fatal(err)
	}
	b.Raw, _ = tx.MarshalBinary()
	b.Transaction = tx.Hash()
	gas := b.Intent.Terms.Gas
	if kind == "cancel" {
		gas = 21000
	}
	a := OutboundAttempt{Kind: kind, Reason: "Explicit test operator decision", State: "prepared", Terms: TransactionTerms{Gas: gas, FeeCap: big.NewInt(6_000_000_000), TipCap: big.NewInt(2_000_000_000)}}
	unsigned = attemptUnsigned(b, a)
	a.Unsigned, _ = unsigned.MarshalBinary()
	a.ID = a.id(b.ID, 0)
	tx, err = types.SignTx(unsigned, types.LatestSignerForChainID(big.NewInt(31337)), key)
	if err != nil {
		t.Fatal(err)
	}
	a.Raw, _ = tx.MarshalBinary()
	a.Transaction = tx.Hash()
	b.Attempts = []OutboundAttempt{a}
	if err = checkRaw(b); err != nil {
		t.Fatal(err)
	}
	if err = checkAttempts(b); err != nil {
		t.Fatal(err)
	}
	return b
}

func TestReplacementHistoryBindsNoncePayloadFeesAndCannotDiscardSignedHashes(t *testing.T) {
	for _, kind := range []string{"replace", "cancel"} {
		t.Run(kind, func(t *testing.T) {
			b := replacementFixture(t, kind)
			if !hasCancellation(b) && kind == "cancel" {
				t.Fatal("signed cancellation not armed")
			}
			var tx types.Transaction
			if err := tx.UnmarshalBinary(b.Attempts[0].Raw); err != nil {
				t.Fatal(err)
			}
			if tx.Nonce() != *b.Nonce || tx.Value().Sign() != 0 {
				t.Fatal("replacement changed nonce or value")
			}
			if kind == "cancel" && (*tx.To() != b.Intent.Payer || len(tx.Data()) != 0 || tx.Gas() != 21000) {
				t.Fatal("cancellation is not a zero-value intrinsic-gas self-transfer")
			}
			for name, change := range map[string]func(*Outbound){
				"changed nonce":            func(x *Outbound) { n := *x.Nonce + 1; x.Nonce = &n },
				"changed fee terms":        func(x *Outbound) { x.Attempts[0].Terms.FeeCap.Add(x.Attempts[0].Terms.FeeCap, big.NewInt(1)) },
				"changed decision reason":  func(x *Outbound) { x.Attempts[0].Reason = "another decision" },
				"changed unsigned bytes":   func(x *Outbound) { x.Attempts[0].Unsigned = []byte{1} },
				"changed raw bytes":        func(x *Outbound) { x.Attempts[0].Raw = []byte{1} },
				"changed hash":             func(x *Outbound) { x.Attempts[0].Transaction = common.HexToHash("0x99") },
				"signed attempt abandoned": func(x *Outbound) { x.Attempts[0].State = "abandoned" },
				"signed attempt staged":    func(x *Outbound) { x.Attempts[0].State = "staged" },
				"history bound":            func(x *Outbound) { x.Attempts = make([]OutboundAttempt, MaxOutboundAttempts+1) },
			} {
				t.Run(name, func(t *testing.T) {
					raw, _ := json.Marshal(b)
					var changed Outbound
					if err := json.Unmarshal(raw, &changed); err != nil {
						t.Fatal(err)
					}
					change(&changed)
					if checkAttempts(changed) == nil {
						t.Fatal("changed replacement history accepted")
					}
				})
			}
		})
	}
	if higherFees(TransactionTerms{FeeCap: big.NewInt(6), TipCap: big.NewInt(1)}, TransactionTerms{FeeCap: big.NewInt(3), TipCap: big.NewInt(1)}) {
		t.Fatal("unchanged tip accepted as a fee bump")
	}
}

type receiptFamilyRPC struct {
	receipts map[common.Hash]*types.Receipt
	fail     common.Hash
	reads    int
}

func (r *receiptFamilyRPC) ReadRPC(_ context.Context, method string, params any, out any) error {
	if method != "eth_getTransactionReceipt" {
		return errors.New("unexpected family RPC")
	}
	hash := params.([]any)[0].(common.Hash)
	r.reads++
	if hash == r.fail {
		return errors.New("injected receipt outage")
	}
	raw, _ := json.Marshal(r.receipts[hash])
	return json.Unmarshal(raw, out)
}
func TestReplacementObservationChecksEveryHashAndRecognizesOriginalWinner(t *testing.T) {
	b := replacementFixture(t, "cancel")
	receipt := func(hash common.Hash) *types.Receipt {
		return &types.Receipt{TxHash: hash, Status: 1, BlockNumber: big.NewInt(10), BlockHash: common.HexToHash("0x111"), Logs: []*types.Log{}}
	}
	rpc := &receiptFamilyRPC{receipts: map[common.Hash]*types.Receipt{b.Transaction: receipt(b.Transaction)}}
	r := &Reader{rpc: rpc}
	p, index, err := r.outboundReceipt(context.Background(), b)
	if err != nil || p == nil || index != -1 || rpc.reads != 2 {
		t.Fatal("latest cancellation hid original receipt", err)
	}
	rpc.receipts = map[common.Hash]*types.Receipt{b.Attempts[0].Transaction: receipt(b.Attempts[0].Transaction)}
	p, index, err = r.outboundReceipt(context.Background(), b)
	if err != nil || p == nil || index != 0 {
		t.Fatal("replacement receipt not selected", err)
	}
	rpc.receipts[b.Transaction] = receipt(b.Transaction)
	if _, _, err = r.outboundReceipt(context.Background(), b); !errors.Is(err, ErrNonceConflict) {
		t.Fatal("contradictory same-nonce receipts accepted", err)
	}
	delete(rpc.receipts, b.Transaction)
	rpc.fail = b.Transaction
	if _, _, err = r.outboundReceipt(context.Background(), b); err == nil {
		t.Fatal("original receipt RPC outage ignored because replacement had a receipt")
	}
}
