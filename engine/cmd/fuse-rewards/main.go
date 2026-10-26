// fuse-rewards compiles an offline paper manifest; it never publishes or mints.
package main

import (
	"bufio"
	"encoding/json"
	"flag"
	"fmt"
	"math/big"
	"os"

	"fuse/engine/internal/engine"
	"fuse/engine/internal/rewards"
	"github.com/ethereum/go-ethereum/common"
)

func main() {
	if err := run(); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}
func run() error {
	journal := flag.String("journal", "", "replay-verified JSONL journal")
	config := flag.String("config", "config/paper.json", "engine policy")
	policyPath := flag.String("policy", "", "explicit mining policy JSON")
	from := flag.Uint64("from", 1, "first unallocated event")
	to := flag.Uint64("to", 0, "finalized checkpoint event sequence")
	epoch := flag.Uint64("epoch", 0, "next reward epoch")
	budgetText := flag.String("budget", "", "FUSE base-unit epoch budget")
	capText := flag.String("cap", "", "independently observed emission cap")
	remainingText := flag.String("remaining-allocation", "", "independently observed remaining emission allocation")
	previous := flag.String("previous", "", "previous immutable reward manifest, required after epoch 1")
	chain := flag.Uint64("chain-id", 0, "deployment chain ID")
	distributor := flag.String("distributor", "", "RewardDistributor address")
	flag.Parse()
	positive := func(v string) (*big.Int, error) {
		n, ok := new(big.Int).SetString(v, 10)
		if !ok || n.Sign() <= 0 || n.BitLen() > 256 {
			return nil, fmt.Errorf("positive uint256 required")
		}
		return n, nil
	}
	budget, err := positive(*budgetText)
	if err != nil {
		return err
	}
	cap, err := positive(*capText)
	if err != nil {
		return err
	}
	remaining, err := positive(*remainingText)
	if err != nil {
		return err
	}
	if budget.Cmp(cap) > 0 || budget.Cmp(remaining) > 0 {
		return fmt.Errorf("epoch exceeds emission cap or remaining escrow allocation")
	}
	if *chain != 998 && *chain != 999 && *chain != 31337 {
		return fmt.Errorf("explicit supported chain ID required")
	}
	if !common.IsHexAddress(*distributor) || common.HexToAddress(*distributor) == (common.Address{}) {
		return fmt.Errorf("nonzero distributor required")
	}
	if *epoch == 1 {
		if *from != 1 || *previous != "" {
			return fmt.Errorf("first epoch must start at sequence 1")
		}
	} else {
		if *previous == "" {
			return fmt.Errorf("previous immutable manifest required")
		}
		raw, err := os.ReadFile(*previous)
		if err != nil {
			return err
		}
		var prev rewards.Manifest
		if err = json.Unmarshal(raw, &prev); err != nil {
			return err
		}
		if *epoch != prev.Epoch+1 || *from != prev.To+1 {
			return fmt.Errorf("overlapping or nonsequential reward range")
		}
	}
	raw, err := os.ReadFile(*config)
	if err != nil {
		return err
	}
	var p engine.Policy
	if err = json.Unmarshal(raw, &p); err != nil {
		return err
	}
	state, err := engine.NewState(p)
	if err != nil {
		return err
	}
	raw, err = os.ReadFile(*policyPath)
	if err != nil {
		return err
	}
	var policy rewards.Policy
	if err = json.Unmarshal(raw, &policy); err != nil {
		return err
	}
	file, err := os.Open(*journal)
	if err != nil {
		return err
	}
	defer file.Close()
	scanner := bufio.NewScanner(file)
	scanner.Buffer(make([]byte, 64<<10), 64<<20)
	events := []engine.Event{}
	seen := map[string]bool{}
	for scanner.Scan() {
		var e engine.Event
		if err = json.Unmarshal(scanner.Bytes(), &e); err != nil {
			return err
		}
		if seen[e.Command.Key] {
			return fmt.Errorf("duplicate journal command")
		}
		seen[e.Command.Key] = true
		next, expected, err := engine.Apply(state, e.Command)
		if err != nil {
			return err
		}
		if engine.Hash(e) != engine.Hash(expected) {
			return fmt.Errorf("replay divergence at %d", e.Sequence)
		}
		state = next
		events = append(events, e)
	}
	if err = scanner.Err(); err != nil {
		return err
	}
	manifest, err := rewards.Build(events, *from, *to, *epoch, budget, new(big.Int).SetUint64(*chain), common.HexToAddress(*distributor), policy)
	if err != nil {
		return err
	}
	return json.NewEncoder(os.Stdout).Encode(manifest)
}
