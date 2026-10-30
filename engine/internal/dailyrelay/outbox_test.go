package dailyrelay

import (
	"math/big"
	"testing"

	"github.com/ethereum/go-ethereum/common"
	"github.com/ethereum/go-ethereum/core/types"
	"github.com/ethereum/go-ethereum/crypto"
)

func TestOutboundRawTransactionBindsEveryPayerAuthorizedField(t *testing.T) {
	key, err := crypto.HexToECDSA("0000000000000000000000000000000000000000000000000000000000000007")
	if err != nil {
		t.Fatal(err)
	}
	nonce := uint64(17)
	b := Outbound{Intent: OutboundIntent{ChainID: 31337, Payer: crypto.PubkeyToAddress(key.PublicKey), Custody: common.HexToAddress("0x1234"), Terms: TransactionTerms{Gas: 1_000_000, FeeCap: big.NewInt(3_000_000_000), TipCap: big.NewInt(1_000_000_000)}}, Nonce: &nonce, Authorization: &Authorized{Data: []byte{1, 2, 3, 4}}}
	signer := types.LatestSignerForChainID(big.NewInt(31337))
	unsigned := unsignedTransaction(b)
	b.Unsigned, err = unsigned.MarshalBinary()
	if err != nil {
		t.Fatal(err)
	}
	signed, err := types.SignTx(unsigned, signer, key)
	if err != nil {
		t.Fatal(err)
	}
	b.Raw, err = signed.MarshalBinary()
	if err != nil {
		t.Fatal(err)
	}
	b.Transaction = signed.Hash()
	if err = checkRaw(b); err != nil {
		t.Fatal(err)
	}
	for name, change := range map[string]func(*Outbound){
		"nonce":            func(x *Outbound) { n := *x.Nonce + 1; x.Nonce = &n },
		"chain":            func(x *Outbound) { x.Intent.ChainID++ },
		"payer":            func(x *Outbound) { x.Intent.Payer = common.HexToAddress("0xabcd") },
		"target":           func(x *Outbound) { x.Intent.Custody = common.HexToAddress("0xabcd") },
		"gas":              func(x *Outbound) { x.Intent.Terms.Gas++ },
		"fee cap":          func(x *Outbound) { x.Intent.Terms.FeeCap = new(big.Int).Add(x.Intent.Terms.FeeCap, big.NewInt(1)) },
		"tip cap":          func(x *Outbound) { x.Intent.Terms.TipCap = new(big.Int).Add(x.Intent.Terms.TipCap, big.NewInt(1)) },
		"calldata":         func(x *Outbound) { x.Authorization = &Authorized{Data: []byte{4, 3, 2, 1}} },
		"unsigned bytes":   func(x *Outbound) { x.Unsigned = []byte{1} },
		"transaction hash": func(x *Outbound) { x.Transaction = common.HexToHash("0x1234") },
		"raw bytes":        func(x *Outbound) { x.Raw = []byte{1} },
	} {
		t.Run(name, func(t *testing.T) {
			changed := b
			change(&changed)
			if checkRaw(changed) == nil {
				t.Fatal("changed payer transaction passed")
			}
		})
	}
	to := b.Intent.Custody
	// Even a valid payer signature cannot add value or an access list that was
	// not part of the reserved unsigned transaction.
	for _, tx := range []*types.Transaction{
		types.NewTx(&types.DynamicFeeTx{ChainID: big.NewInt(31337), Nonce: nonce, Gas: b.Intent.Terms.Gas, GasFeeCap: b.Intent.Terms.FeeCap, GasTipCap: b.Intent.Terms.TipCap, To: &to, Value: big.NewInt(1), Data: b.Authorization.Data}),
		types.NewTx(&types.DynamicFeeTx{ChainID: big.NewInt(31337), Nonce: nonce, Gas: b.Intent.Terms.Gas, GasFeeCap: b.Intent.Terms.FeeCap, GasTipCap: b.Intent.Terms.TipCap, To: &to, Value: new(big.Int), Data: b.Authorization.Data, AccessList: types.AccessList{{Address: to}}}),
	} {
		signed, err := types.SignTx(tx, signer, key)
		if err != nil {
			t.Fatal(err)
		}
		changed := b
		changed.Raw, _ = signed.MarshalBinary()
		changed.Transaction = signed.Hash()
		if checkRaw(changed) == nil {
			t.Fatal("signed transaction added unreserved fields")
		}
	}
}
