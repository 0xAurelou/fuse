package rewards

import (
	"bytes"
	"encoding/json"
	"fmt"
	"fuse/engine/internal/engine"
	"math/big"
	"os"
	"testing"

	"fuse/engine/internal/contracts"
	"github.com/ethereum/go-ethereum/common"
)

func TestTreeAndDomainSeparation(t *testing.T) {
	for _, count := range []int{1, 2, 3, 5, 8, 19} {
		leaves := []common.Hash{}
		for i := 0; i < count; i++ {
			leaf, err := contracts.RewardLeaf(big.NewInt(998), common.HexToAddress("0x100"), 1, big.NewInt(int64(i)), common.HexToAddress("0x200"), big.NewInt(int64(i+1)))
			if err != nil {
				t.Fatal(err)
			}
			leaves = append(leaves, leaf)
		}
		root, proofs := Tree(leaves)
		for i, l := range leaves {
			if !Verify(l, proofs[i], root) {
				t.Fatalf("bad proof %d/%d", i, count)
			}
			wrong, _ := contracts.RewardLeaf(big.NewInt(999), common.HexToAddress("0x100"), 1, big.NewInt(int64(i)), common.HexToAddress("0x200"), big.NewInt(int64(i+1)))
			if Verify(wrong, proofs[i], root) {
				t.Fatal("cross-chain reward replay")
			}
		}
	}
}
func TestEmissionAndReserveLimits(t *testing.T) {
	cap2, err2 := EmissionCap(big.NewInt(1000), 1000, 2)
	if err2 != nil || cap2.Int64() != 900 {
		t.Fatal(cap2, err2)
	}
	cap, err := EmissionCap(big.NewInt(1000), 5000, 3)
	if err != nil || cap.Int64() != 250 {
		t.Fatal(cap, err)
	}
	amount, consumed, err := ReserveContribution(1000, 0, 1000, 900, 3500)
	if err != nil || amount != 100 || consumed != 286 {
		t.Fatal(amount, consumed, err)
	}
	amount, _, err = ReserveContribution(200, 286, 1000, 0, 3500)
	if err != nil || amount != 0 {
		t.Fatal("losses not recovered")
	}
	if _, _, err = ReserveContribution(1000, 0, 1000, 0, 5001); err == nil {
		t.Fatal("unsafe reserve allocation")
	}
}

func TestManifestFromReplayedCompletedRisk(t *testing.T) {
	raw, err := os.ReadFile("../../config/paper.json")
	if err != nil {
		t.Fatal(err)
	}
	var policy engine.Policy
	if err = json.Unmarshal(raw, &policy); err != nil {
		t.Fatal(err)
	}
	state, err := engine.NewState(policy)
	if err != nil {
		t.Fatal(err)
	}
	commands, err := os.ReadFile("../../testdata/paper-commands.jsonl")
	if err != nil {
		t.Fatal(err)
	}
	events := []engine.Event{}
	for _, line := range bytes.Split(bytes.TrimSpace(commands), []byte("\n")) {
		var c engine.Command
		if err = json.Unmarshal(line, &c); err != nil {
			t.Fatal(err)
		}
		next, event, err := engine.Apply(state, c)
		if err != nil {
			t.Fatal(err)
		}
		state = next
		events = append(events, event)
	}
	mining := Policy{Version: "test-v1", SurvivedWeightBPS: 10_000, FailedWeightBPS: 2000, MaxStakeUSDC: 1_000_000_000}
	manifest, err := Build(events, 1, 22, 1, big.NewInt(1000), big.NewInt(998), common.HexToAddress("0x100"), mining)
	if err != nil {
		t.Fatal(err)
	}
	if manifest.Allocated != "1000" || len(manifest.Allocations) != 1 || !Verify(manifest.Allocations[0].Leaf, manifest.Allocations[0].Proof, manifest.Root) {
		t.Fatal(manifest)
	}
	repeated, err := Build(events, 1, 22, 1, big.NewInt(1000), big.NewInt(998), common.HexToAddress("0x100"), mining)
	if err != nil || engine.Hash(repeated) != engine.Hash(manifest) {
		t.Fatal("nondeterministic reward manifest", err)
	}
	if _, err = Build(events, 1, 6, 1, big.NewInt(1000), big.NewInt(998), common.HexToAddress("0x100"), mining); err == nil {
		t.Fatal("unfinalized order activity rewarded")
	}
	mining.StreakBonusBPS[0] = 1
	if _, err = Build(events, 1, 22, 1, big.NewInt(1000), big.NewInt(998), common.HexToAddress("0x100"), mining); err == nil {
		t.Fatal("unbounded streak policy rewarded")
	}
}

func TestReserveV2RampRecoveryAndCapitalFloor(t *testing.T) {
	for _, tt := range []struct{ equity, capital, wantBPS int64 }{{1500, 1000, 0}, {2000, 1000, 1166}, {2500, 1000, 2333}, {3000, 1000, 3500}} {
		amount, _, bps, err := ReserveContributionV2(1000, 1000, 0, tt.equity, tt.capital, 3500)
		if err != nil || bps != tt.wantBPS || amount > max(int64(0), tt.equity-2*tt.capital) {
			t.Fatal(tt, amount, bps, err)
		}
	}
	amount, _, _, err := ReserveContributionV2(900, 1000, 1, 100000, 0, 3500)
	if err != nil || amount != 0 {
		t.Fatal("HWM recovery bypass", amount, err)
	}
}

func TestLinearRewardActivityCapAndNoDuplicateEpochScore(t *testing.T) {
	raw, _ := os.ReadFile("../../config/paper.json")
	var p engine.Policy
	_ = json.Unmarshal(raw, &p)
	state, _ := engine.NewState(p)
	commands, _ := os.ReadFile("../../testdata/paper-commands.jsonl")
	events := []engine.Event{}
	for _, line := range bytes.Split(bytes.TrimSpace(commands), []byte("\n")) {
		var c engine.Command
		_ = json.Unmarshal(line, &c)
		next, event, err := engine.Apply(state, c)
		if err != nil {
			t.Fatal(err)
		}
		state = next
		events = append(events, event)
	}
	policy := Policy{Version: "v2", ExposureRule: "linear-stake-time-v2", ActivityRate: "100000000000000000000", SurvivedWeightBPS: 10000, FailedWeightBPS: 2000, MaxStakeUSDC: 1}
	m, err := Build(events, 1, 22, 1, new(big.Int).Mul(big.NewInt(1000000), big.NewInt(1e18)), big.NewInt(998), common.HexToAddress("0x100"), policy)
	if err != nil || m.Budget != "100000000000000000000" || m.TotalScore == "" || len(m.Stages) != 1 {
		t.Fatal(m, err)
	}
	// Repeat a final outcome notice in a later checkpoint. It must never mine twice.
	repeated := events[21]
	repeated.Sequence = 24
	for _, event := range events {
		for _, raw := range event.Notices {
			if bytes.Contains(raw, []byte(`"status":"survived"`)) {
				repeated.Notices = event.Notices
			}
		}
	}
	events = append(events, repeated)
	if _, err = Build(events, 24, 24, 2, big.NewInt(1), big.NewInt(998), common.HexToAddress("0x100"), policy); err == nil {
		t.Fatal("stage rewarded twice")
	}
}

func TestLinearMiningIsWalletSplitNeutralBeforeRounding(t *testing.T) {
	makeEvents := func(split bool) []engine.Event {
		notices := map[string]json.RawMessage{}
		count := 1
		if split {
			count = 2
		}
		for i := 0; i < count; i++ {
			account := fmt.Sprintf("0x%040x", i+1)
			stake := int64(1000000 / int64(count))
			stage := engine.Stage{ID: fmt.Sprint("stage-", i), Start: 1000, Resolved: 31000, Status: "survived", Terms: engine.Quote{Account: account, Index: 1, Stake: stake, Payout: stake * 2, DurationMS: 30000, PolicyVersion: "difficulty-v1"}}
			notices[account], _ = json.Marshal(map[string]any{"stages": []engine.Stage{stage}})
		}
		checkpoint, _ := json.Marshal(engine.Epoch{Status: "paper-confirmed"})
		return []engine.Event{{Sequence: 1, Notices: notices}, {Sequence: 2, Command: engine.Command{Kind: "paper_settle"}, Result: checkpoint}}
	}
	policy := Policy{Version: "v2", ExposureRule: "linear-stake-time-v2", ActivityRate: "100000000000000000000", SurvivedWeightBPS: 10000, FailedWeightBPS: 2000, MaxStakeUSDC: 1}
	budget, _ := new(big.Int).SetString("1000000000000000000000000", 10)
	one, err := Build(makeEvents(false), 1, 2, 1, budget, big.NewInt(998), common.HexToAddress("0x100"), policy)
	if err != nil {
		t.Fatal(err)
	}
	two, err := Build(makeEvents(true), 1, 2, 1, budget, big.NewInt(998), common.HexToAddress("0x100"), policy)
	if err != nil {
		t.Fatal(err)
	}
	if one.TotalScore != two.TotalScore || one.ActivityBudget != two.ActivityBudget || one.Allocated != two.Allocated {
		t.Fatal("wallet splitting changed mining eligibility", one, two)
	}
}
