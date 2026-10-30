package dailyrelay

import (
	"context"
	"encoding/json"
	"testing"

	"github.com/ethereum/go-ethereum/common"
)

func TestProofProvenanceCannotBeRecreatedByJSONOrChangedMetadata(t *testing.T) {
	b := Binding{ChainID: 31337, Custody: common.HexToAddress("0x1234"), StageID: "stage-1", StageCommitment: common.HexToHash("0x1"), TicketID: common.HexToHash("0x2"), Generation: "7", LimitsHash: common.HexToHash("0x3"), TermsHash: common.HexToHash("0x4"), TxHash: common.HexToHash("0x5"), Block: 1, BlockHash: common.HexToHash("0x6"), StartMS: 1_000_000, ExpiryMS: 1_030_000}
	b.verified = b.identityHash()
	if !b.validProof() {
		t.Fatal("valid reader proof rejected")
	}
	raw, _ := json.Marshal(b)
	var restored Binding
	if err := json.Unmarshal(raw, &restored); err != nil {
		t.Fatal(err)
	}
	if restored.validProof() {
		t.Fatal("serialized binding bypassed mandatory chain revalidation")
	}
	store := &BindingStore{} // No DB handle: invalid proof must be rejected before I/O.
	if err := store.Put(context.Background(), restored); err == nil {
		t.Fatal("persisted unverified binding")
	}
	b.StartMS++
	if b.validProof() {
		t.Fatal("changed acceptance kept proof provenance")
	}
	if err := store.Put(context.Background(), b); err == nil {
		t.Fatal("persisted changed binding")
	}
	p := SettlementProof{ChainID: 31337, Custody: common.HexToAddress("0x1234"), Transaction: common.HexToHash("0x7"), Block: 10, BlockHash: common.HexToHash("0x8"), Digest: common.HexToHash("0x9"), JournalHash: common.HexToHash("0xa"), Tickets: []common.Hash{common.HexToHash("0x2")}, LPNetUSDC: "2000000"}
	p.verified = p.identityHash()
	raw, _ = json.Marshal(p)
	var decoded SettlementProof
	if err := json.Unmarshal(raw, &decoded); err != nil {
		t.Fatal(err)
	}
	if decoded.validProof() {
		t.Fatal("serialized receipt bypassed mandatory event/transfer verification")
	}
	if err := store.CommitSettlement(context.Background(), decoded); err == nil {
		t.Fatal("committed an unverified payment record")
	}
	p.Tickets[0] = common.HexToHash("0xb")
	if p.validProof() {
		t.Fatal("changed paid ticket kept receipt provenance")
	}
	if err := store.CommitSettlement(context.Background(), p); err == nil {
		t.Fatal("committed altered paid-ticket metadata")
	}
	v := VoidProof{Kind: "queue_void", ChainID: 31337, Ticket: common.HexToHash("0x2"), Account: common.HexToAddress("0x1234"), CreditUSDC: "0"}
	v.verified = v.identityHash()
	if !v.validProof() {
		t.Fatal("fresh void proof rejected")
	}
	raw, _ = json.Marshal(v)
	var restoredVoid VoidProof
	if err := json.Unmarshal(raw, &restoredVoid); err != nil {
		t.Fatal(err)
	}
	if restoredVoid.validProof() || store.CommitVoid(context.Background(), restoredVoid) == nil {
		t.Fatal("serialized queue bypassed receipt verification")
	}
	v.CreditUSDC = "10000000"
	if v.validProof() || store.CommitVoid(context.Background(), v) == nil {
		t.Fatal("queue changed into a paid refund")
	}
}
