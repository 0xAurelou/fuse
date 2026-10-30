// Generate conspicuously synthetic native-format fixtures without a network.
// The frozen fuse-capture binary must independently verify the generated chain.
package main

import (
	"bufio"
	"encoding/json"
	"flag"
	"fmt"
	"os"
	"path/filepath"

	"fuse/engine/internal/capture"
	"fuse/engine/internal/engine"
)

func must(err error) {
	if err != nil {
		panic(err)
	}
}

func create(path string, value any) {
	f, err := os.OpenFile(path, os.O_CREATE|os.O_EXCL|os.O_WRONLY, 0600)
	must(err)
	must(json.NewEncoder(f).Encode(value))
	must(f.Close())
}

func main() {
	directory := flag.String("directory", "", "new synthetic fixture directory containing frozen-policy.json")
	start := flag.Int64("start-ms", 0, "explicit synthetic clock, not a prospective freeze")
	gap := flag.Int64("gap-ms", 0, "omit both sources starting two hours into fixture")
	delta := flag.Int64("policy-gap-delta", 0, "deliberate manifest-only policy corruption")
	flag.Parse()
	if *directory == "" || *start <= 0 || *gap < 0 || *gap >= 6*3600000 {
		panic("invalid synthetic fixture options")
	}
	raw, err := os.ReadFile(filepath.Join(*directory, "frozen-policy.json"))
	must(err)
	var policy engine.Policy
	must(json.Unmarshal(raw, &policy))
	policy.MaxGapMS += *delta
	must(policy.Validate())
	manifest := capture.Manifest{DurationMS: 8 * 3600000, Version: 1, FrozenAt: *start,
		Policy: policy, PolicyHash: engine.Hash(policy), Endpoint: "synthetic://offline/BTC"}
	if *start+manifest.DurationMS >= policy.Model.ValidUntil {
		panic("synthetic policy expires within fixture")
	}
	create(filepath.Join(*directory, "manifest.json"), manifest)
	f, err := os.OpenFile(filepath.Join(*directory, "receipts.jsonl"), os.O_CREATE|os.O_EXCL|os.O_WRONLY, 0600)
	must(err)
	w := bufio.NewWriter(f)
	head := engine.Hash(manifest)
	var sequence uint64
	for offset := int64(1000); offset < manifest.DurationMS; offset += 4000 {
		if offset >= 2*3600000 && offset < 2*3600000+*gap {
			continue
		}
		// Repeated flat/range/pump/dump schedules are software fixtures only.
		block := (offset / 900000) % 4
		phase := (offset % 900000) / 4000
		price := int64(100000)
		switch block {
		case 1:
			price += (phase%20 - 10) * 3
		case 2:
			price += phase * 3
		case 3:
			price -= phase * 3
		}
		frame := json.RawMessage(fmt.Sprintf(`{"channel":"activeAssetCtx","data":{"coin":"BTC","ctx":{"oraclePx":"%d","markPx":"%d","midPx":"%d"}}}`, price, price+2, price+1))
		_, err := engine.ParseOracle(frame)
		must(err)
		for _, source := range []string{"a", "b"} {
			sequence++
			receipt := capture.Receipt{Sequence: sequence, Previous: head, At: *start + offset, Source: source, Raw: frame}
			receipt.Hash = engine.Hash(receipt)
			must(json.NewEncoder(w).Encode(receipt))
			head = receipt.Hash
		}
	}
	must(w.Flush())
	must(f.Sync())
	must(f.Close())
	create(filepath.Join(*directory, "SYNTHETIC_GENERATION.json"), map[string]any{
		"synthetic_only": true, "network_used": false, "prospective_evidence": false,
		"sequence": sequence, "head_hash": head, "start_ms": *start, "duration_ms": manifest.DurationMS,
		"gap_ms": *gap, "manifest_only_policy_delta_ms": *delta,
	})
}
