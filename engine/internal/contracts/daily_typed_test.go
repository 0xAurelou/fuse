package contracts

import (
	"encoding/binary"
	"math/big"
	"testing"

	"github.com/ethereum/go-ethereum/common"
	"github.com/ethereum/go-ethereum/crypto"
)

func TestDailyBatchHashIncludesDynamicOffsetLengthAndOrderedFullOutcomes(t *testing.T) {
	rows := []DailyOutcome{{common.HexToHash("0x1234"), 2, 1_000_123, common.HexToHash("0xabcd"), 1200}, {common.HexToHash("0x5678"), 3, 1_000_001, common.HexToHash("0xef01"), 1201}}
	// Independent word construction, not the tuple[] ABI encoder under test.
	raw := make([]byte, 64+160*len(rows))
	raw[31] = 32
	raw[63] = byte(len(rows))
	for i, o := range rows {
		at := 64 + 160*i
		copy(raw[at:at+32], o.Id[:])
		raw[at+63] = o.Outcome
		binary.BigEndian.PutUint64(raw[at+88:at+96], o.CanonicalTime)
		copy(raw[at+96:at+128], o.EvidenceHash[:])
		binary.BigEndian.PutUint64(raw[at+152:at+160], o.Deadline)
	}
	got, err := DailyBatchHash(rows)
	if err != nil || got != crypto.Keccak256Hash(raw) {
		t.Fatal("daily dynamic-array encoding mismatch", err)
	}
	rows[0], rows[1] = rows[1], rows[0]
	changed, err := DailyBatchHash(rows)
	if err != nil || changed == got {
		t.Fatal("batch order not bound")
	}
	rows[0].EvidenceHash = common.Hash{}
	if _, err = DailyBatchHash(rows); err == nil {
		t.Fatal("accepted missing oracle evidence")
	}
}

func TestDailyDigestBindsDomainGenerationJournalAndMillisecondTime(t *testing.T) {
	rows := []DailyOutcome{{common.HexToHash("0x1"), 4, 1_000_123, common.HexToHash("0x2"), 1200}}
	address := common.HexToAddress("0x1234")
	journal := common.HexToHash("0xabcd")
	base, err := DailyBatchDigest(big.NewInt(31337), address, rows, journal, 1200, big.NewInt(7))
	if err != nil {
		t.Fatal(err)
	}
	for _, variant := range []struct {
		chain      int64
		address    common.Address
		journal    common.Hash
		generation int64
	}{{999, address, journal, 7}, {31337, common.HexToAddress("0x5678"), journal, 7}, {31337, address, common.HexToHash("0xef01"), 7}, {31337, address, journal, 8}} {
		got, err := DailyBatchDigest(big.NewInt(variant.chain), variant.address, rows, variant.journal, 1200, big.NewInt(variant.generation))
		if err != nil || got == base {
			t.Fatal("daily signature context not bound", err)
		}
	}
	rows[0].CanonicalTime++
	got, err := DailyBatchDigest(big.NewInt(31337), address, rows, journal, 1200, big.NewInt(7))
	if err != nil || got == base {
		t.Fatal("lost subsecond outcome precision")
	}
}
