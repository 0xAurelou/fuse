package engine_test

import (
	"fuse/engine/internal/engine"
	"math/big"
	"testing"
)

func FuzzMulDivBounds(f *testing.F) {
	f.Add(int64(1_000_000), int64(1_778_279_410), int64(1_000_000_000))
	f.Add(int64(engine.Limit), int64(engine.Limit), int64(1))
	f.Fuzz(func(t *testing.T, a, b, d int64) {
		got, err := engine.MulDiv(a, b, d)
		if a < 0 || b < 0 || d <= 0 {
			if err == nil {
				t.Fatal("invalid arithmetic accepted")
			}
			return
		}
		expected := new(big.Int).Mul(big.NewInt(a), big.NewInt(b))
		expected.Quo(expected, big.NewInt(d))
		if !expected.IsInt64() || expected.Cmp(big.NewInt(engine.Limit)) > 0 {
			if err == nil {
				t.Fatal("overflow accepted")
			}
			return
		}
		if err != nil || got != expected.Int64() {
			t.Fatal(got, expected, err)
		}
	})
}
