package engine_test

import (
	"context"
	"errors"
	"testing"

	"fuse/engine/internal/engine"
	"fuse/engine/internal/storage"
)

type testFinancialFence struct {
	*storage.Memory
	sequence uint64
	head     string
	err      error
	calls    int
}

func (s *testFinancialFence) AssertHead(_ context.Context, sequence uint64, head string) error {
	s.calls++
	if sequence != s.sequence || head != s.head {
		return errors.New("wrong authoritative head")
	}
	return s.err
}

func TestFinancialSourceRequiresCanonicalPrefixAndLiveDurableHead(t *testing.T) {
	f := newFixture(t)
	e := f.q.Events(0, 1)[0]
	ctx := context.Background()
	if err := f.q.VerifyFinancialSource(ctx, e.Sequence, e.Hash, e.StateHash); err == nil {
		t.Fatal("memory replay became signing authority")
	}
	head := f.q.Snapshot()
	store := &testFinancialFence{Memory: f.store, sequence: head.Sequence, head: head.JournalHash}
	q, err := engine.Open(ctx, f.policy, store)
	if err != nil {
		t.Fatal(err)
	}
	if err = q.VerifyFinancialSource(ctx, e.Sequence, e.Hash, e.StateHash); err != nil {
		t.Fatal("canonical older prefix failed against current durable head:", err)
	}
	for _, changed := range []struct {
		sequence       uint64
		journal, state string
	}{
		{0, e.Hash, e.StateHash}, {head.Sequence + 1, e.Hash, e.StateHash},
		{e.Sequence, "forged", e.StateHash}, {e.Sequence, e.Hash, "forged"},
	} {
		calls := store.calls
		if q.VerifyFinancialSource(ctx, changed.sequence, changed.journal, changed.state) == nil || store.calls != calls {
			t.Fatal("noncanonical replay reached durable signing fence")
		}
	}
	store.err = errors.New("leadership lost")
	if q.VerifyFinancialSource(ctx, e.Sequence, e.Hash, e.StateHash) == nil {
		t.Fatal("lost leadership retained signing authority")
	}
	store.err = nil
	store.Fail = true
	if _, err = q.Execute(ctx, engine.Command{Kind: "lp_fund", Key: "fail-fence", At: f.now, Amount: 1}); err == nil {
		t.Fatal("injected commit failure passed")
	}
	if q.VerifyFinancialSource(ctx, e.Sequence, e.Hash, e.StateHash) == nil {
		t.Fatal("failed sequencer retained signing authority")
	}
}
