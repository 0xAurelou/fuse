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
	if _, err := b.execute(request{Kind: "command", Command: engine.Command{Key: "clock", Kind: "tick", At: 1}}); err != nil {
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

func TestResearchBridgeReportsFeeCapabilityAndPausesRecovery(t *testing.T) {
	b := &bridge{}
	capability, err := b.execute(request{Kind: "capabilities"})
	if err != nil || capability.(map[string]any)["fee_accrual_recovery"] != true {
		t.Fatal("missing recovery fee capability", err)
	}
	raw, err := os.ReadFile("../../config/paper-recovery.json")
	if err != nil {
		t.Fatal(err)
	}
	var p engine.Policy
	if err := json.Unmarshal(raw, &p); err != nil {
		t.Fatal(err)
	}
	if _, err := b.execute(request{Kind: "init", Policy: p}); err != nil {
		t.Fatal(err)
	}
	if _, err := b.execute(request{Kind: "command", Command: engine.Command{Key: "time", Kind: "tick", At: 1000000}}); err != nil {
		t.Fatal(err)
	}
	if _, err := b.execute(request{Kind: "sync_lp", Cash: 250000000000, Fee: 25000000}); err != nil {
		t.Fatal(err)
	}
	if b.state.Recovery.PnL != -25000000 || b.state.Recovery.Mode != "paused" || len(b.state.Recovery.Losses) != 1 {
		t.Fatal("bridge did not charge production recovery handler", b.state.Recovery)
	}
	before := b.state.Digest()
	if _, err := b.execute(request{Kind: "sync_lp", Cash: 250000000000, Fee: 24000000}); err == nil || b.state.Digest() != before {
		t.Fatal("invalid fee reduction mutated bridge")
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
