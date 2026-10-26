package contracts

import (
	"context"
	"encoding/json"
	"math/big"
	"os"
	"testing"

	"github.com/ethereum/go-ethereum/common"
)

func TestSolidityEncodingVectors(t *testing.T) {
	raw, err := os.ReadFile("../../testdata/encoding-vectors.json")
	if err != nil {
		t.Fatal(err)
	}
	var v map[string]json.RawMessage
	if err = json.Unmarshal(raw, &v); err != nil {
		t.Fatal(err)
	}
	str := func(k string) string { var s string; _ = json.Unmarshal(v[k], &s); return s }
	check := func(k string, got common.Hash, err error) {
		t.Helper()
		if err != nil || got.Hex() != str(k) {
			t.Fatalf("%s: got %s want %s error %v", k, got, str(k), err)
		}
	}
	chain, generation := big.NewInt(998), big.NewInt(9)
	contract := common.HexToAddress(str("contract"))
	a, b := common.HexToAddress(str("account")), common.HexToAddress(str("recipient"))
	h := func(i int64) common.Hash { return common.BigToHash(big.NewInt(i)) }
	w := Withdrawal{a, b, big.NewInt(123456789), 7, 1800000000, h(4), h(5)}
	got, err := w.Digest(chain, contract, generation)
	check("withdrawal", got, err)
	dep, err := DepositBatchHash([]*big.Int{big.NewInt(1), big.NewInt(2), big.NewInt(300)})
	check("deposit_batch", dep, err)
	empty, err := DepositBatchHash(nil)
	check("empty_deposit_batch", empty, err)
	s := Settlement{7, h(1), h(2), h(3), h(4), 100, 200, 1700000000, big.NewInt(-123), big.NewInt(456), big.NewInt(789), big.NewInt(1000), big.NewInt(50), dep, big.NewInt(1800000000)}
	got, err = s.Digest(chain, contract, generation)
	check("settlement", got, err)
	r := ReserveAuthorization{7, h(2), big.NewInt(123), big.NewInt(1000), big.NewInt(50), h(4), big.NewInt(1800000000)}
	got, err = r.Digest(chain, contract, generation)
	check("reserve", got, err)
	capacity := LPCapacity{7, h(2), big.NewInt(123456789), big.NewInt(3), big.NewInt(1800000000)}
	got, err = capacity.Digest(chain, contract, generation)
	check("lp_capacity", got, err)
	utilization := LPUtilization{7, big.NewInt(123456789), h(3), big.NewInt(1800000000)}
	got, err = utilization.Digest(chain, contract, generation)
	check("lp_utilization", got, err)
	leaf, err := RewardLeaf(chain, contract, 7, big.NewInt(3), a, big.NewInt(123456789))
	check("reward_leaf", leaf, err)
	original, _ := w.Digest(chain, contract, generation)
	wrong, _ := w.Digest(big.NewInt(999), contract, generation)
	if wrong == original {
		t.Fatal("chain domain collision")
	}
	if _, err = CheckedSign(context.Background(), nil, "withdrawal", got, got); err == nil {
		t.Fatal("signed without infrastructure")
	}
}
