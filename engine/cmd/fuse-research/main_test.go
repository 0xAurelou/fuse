package main

import (
	"encoding/json"
	"os"
	"testing"

	"fuse/engine/internal/engine"
)

func policy(t *testing.T) engine.Policy {
	t.Helper()
	raw, err := os.ReadFile("../../config/paper.json")
	if err != nil {
		t.Fatal(err)
	}
	var p engine.Policy
	if err := json.Unmarshal(raw, &p); err != nil {
		t.Fatal(err)
	}
	return p
}

func TestReadOnlyCorridorQuantizationUsesNativeRoundingAndLimits(t *testing.T) {
	b := &bridge{}
	p := policy(t)
	if _, err := b.execute(request{Kind: "init", Policy: p}); err != nil {
		t.Fatal(err)
	}
	before := b.state.Digest()
	input := []corridorInput{{100_000_000, 1}, {100_000_000, 10}, {3_000_000_000, 333}, {engine.Limit, 1}}
	got, err := b.execute(request{Kind: "quantize_corridors", Policy: p, Corridors: input})
	if err != nil {
		t.Fatal(err)
	}
	raw, _ := json.Marshal(got)
	var rows []struct {
		Delta int64 `json:"delta"`
		Valid bool  `json:"valid"`
	}
	if err = json.Unmarshal(raw, &rows); err != nil {
		t.Fatal(err)
	}
	if len(rows) != 4 || rows[0].Valid || rows[0].Delta != 0 || !rows[1].Valid || rows[1].Delta != 1 || rows[2].Delta != 999 || rows[3].Valid {
		t.Fatal("native quantization/bounds mismatch", string(raw))
	}
	if b.state.Digest() != before {
		t.Fatal("arithmetic export changed trading state")
	}
	p.Mode = "local"
	if _, err = b.execute(request{Kind: "quantize_corridors", Policy: p, Corridors: input}); err == nil {
		t.Fatal("local mode accepted")
	}
}

func TestReadOnlyPricingGridCoversReleaseEdgesAndEveryAssetPayout(t *testing.T) {
	b := &bridge{}
	p := policy(t)
	if _, err := b.execute(request{Kind: "init", Policy: p}); err != nil {
		t.Fatal(err)
	}
	before := b.state.Digest()
	for _, edge := range []int64{500, 700, 850, 1000} {
		variant := policy(t)
		variant.Model.DNT.HouseEdgeBPS = edge
		for asset, model := range variant.Markets {
			model.DNT.HouseEdgeBPS = edge
			variant.Markets[asset] = model
		}
		got, err := b.execute(request{Kind: "pricing_grid", Policy: variant})
		if err != nil {
			t.Fatal(err)
		}
		raw, _ := json.Marshal(got)
		var vectors []struct {
			Asset string `json:"asset"`
			M     int64  `json:"multiplier"`
			Edge  int64  `json:"house_edge_bps"`
			Width int64  `json:"width_ppb"`
		}
		if err := json.Unmarshal(raw, &vectors); err != nil || len(vectors) != 27 {
			t.Fatalf("incomplete pricing grid: %s (%v)", raw, err)
		}
		seen := map[string]map[int64]bool{}
		for _, v := range vectors {
			want, err := variant.AssetModel(v.Asset).DNT.WidthPPB(v.M)
			if err != nil || v.Edge != edge || v.Width != want || v.Width <= 0 {
				t.Fatalf("incorrect exported native vector: %+v", v)
			}
			if seen[v.Asset] == nil {
				seen[v.Asset] = map[int64]bool{}
			}
			if seen[v.Asset][v.M] {
				t.Fatal("duplicate payout")
			}
			seen[v.Asset][v.M] = true
		}
		if b.state.Digest() != before {
			t.Fatal("pricing export mutated trading state")
		}
	}
	p.Mode = "local"
	if _, err := b.execute(request{Kind: "pricing_grid", Policy: p}); err == nil {
		t.Fatal("accepted local policy")
	}
}

func TestResearchIsPaperOnlyAndRejectsUnfundedProjectionAtomically(t *testing.T) {
	b := &bridge{}
	p := policy(t)
	p.Mode = "local"
	if _, err := b.execute(request{Kind: "init", Policy: p}); err == nil {
		t.Fatal("allowed local execution")
	}
	p.Mode = "paper"
	if _, err := b.execute(request{Kind: "init", Policy: p}); err != nil {
		t.Fatal(err)
	}
	if _, err := b.execute(request{Kind: "sync_lp", Cash: 100, Fee: 20, Exit: 30}); err != nil {
		t.Fatal(err)
	}
	before := b.state.Digest()
	for _, r := range []request{
		{Kind: "sync_lp", Cash: 10, Fee: 20},
		{Kind: "sync_lp", Cash: 100, Fee: 60, Exit: 41},
		{Kind: "sync_lp", Cash: -1},
		{Kind: "command", Command: engine.Command{Key: "forbidden", Kind: "local_bind", At: 1}},
	} {
		if _, err := b.execute(r); err == nil {
			t.Fatalf("accepted %+v", r)
		}
		if b.state.Digest() != before {
			t.Fatal("rejection mutated state")
		}
	}
}

func TestSourceVerifierRecomputesHashes(t *testing.T) {
	p := policy(t)
	s, err := engine.NewState(p)
	if err != nil {
		t.Fatal(err)
	}
	_, event, err := engine.Apply(s, engine.Command{Key: "one", Kind: "lp_fund", Amount: 1000, At: 1})
	if err != nil {
		t.Fatal(err)
	}
	f, err := os.CreateTemp(t.TempDir(), "source")
	if err != nil {
		t.Fatal(err)
	}
	write := func() {
		raw, _ := json.Marshal(event)
		if err := os.WriteFile(f.Name(), raw, 0600); err != nil {
			t.Fatal(err)
		}
	}
	f.Close()
	write()
	if _, err := verify(f.Name(), p, ""); err != nil {
		t.Fatal(err)
	}
	event.Command.Amount++
	write()
	if _, err := verify(f.Name(), p, ""); err == nil {
		t.Fatal("accepted tampered source event")
	}
}

func TestResearchExportsExistingJournalOutcomeWithoutMutatingState(t *testing.T) {
	b := &bridge{}
	if _, err := b.execute(request{Kind: "init", Policy: policy(t)}); err != nil {
		t.Fatal(err)
	}
	commands := []engine.Command{
		{Kind: "lp_fund", Amount: 1_000_000_000},
		{Kind: "deposit", Actor: "alice", ID: "deposit", Amount: 100_000_000},
		{Kind: "ack_deposit", ID: "deposit"},
		{Kind: "oracle", Source: "a", Raw: json.RawMessage(`{"channel":"activeAssetCtx","data":{"coin":"BTC","ctx":{"oraclePx":"100000"}}}`)},
		{Kind: "oracle", Source: "b", Raw: json.RawMessage(`{"channel":"activeAssetCtx","data":{"coin":"BTC","ctx":{"oraclePx":"100000"}}}`)},
		{Kind: "quote", Actor: "alice", Asset: "BTC", Amount: 1_000_000, Multiplier: 2},
	}
	for i, c := range commands {
		c.Key = string(rune('a' + i))
		c.At = 1_000_000
		if _, err := b.execute(request{Kind: "command", Command: c}); err != nil {
			t.Fatal(err)
		}
	}
	var quoteID string
	for id := range b.state.Quotes {
		quoteID = id
	}
	if _, err := b.execute(request{Kind: "command", Command: engine.Command{
		Kind: "enter", Key: "enter", Actor: "alice", ID: quoteID, At: 1_000_000}}); err != nil {
		t.Fatal(err)
	}
	if _, err := b.execute(request{Kind: "command", Command: engine.Command{
		Kind: "tick", Key: "void", At: 1_045_123}}); err != nil {
		t.Fatal(err)
	}
	var stageID string
	for id := range b.state.Stages {
		stageID = id
	}
	before := b.state.Digest()
	got, err := b.execute(request{Kind: "settlement_outcome", StageID: stageID})
	if err != nil {
		t.Fatal(err)
	}
	out, ok := got.(engine.SettlementOutcome)
	if !ok || out.Outcome != 4 || out.CanonicalMS != 1_045_123 || out.LPPnL != 0 {
		t.Fatalf("%+v", got)
	}
	if b.state.Digest() != before {
		t.Fatal("export mutated state")
	}
	if _, err := b.execute(request{Kind: "settlement_outcome", StageID: "missing"}); err == nil {
		t.Fatal("exported missing outcome")
	}
}
