// fuse-contracts verifies a reviewed deployment manifest without signing or broadcasting.
package main

import (
	"context"
	"encoding/json"
	"flag"
	"fmt"
	"os"
	"time"

	"fuse/engine/internal/contracts"
)

func main() {
	if err := run(); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}
func run() error {
	path := flag.String("manifest", "", "reviewed deployment manifest")
	rpc := flag.String("rpc", "", "optional read-only RPC chain/code check")
	flag.Parse()
	if *path == "" {
		return fmt.Errorf("-manifest required")
	}
	m, abis, err := contracts.LoadManifest(*path)
	if err != nil {
		return err
	}
	checked := false
	if *rpc != "" {
		ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
		defer cancel()
		reader := &contracts.RPCReader{URL: *rpc}
		chain, err := reader.ChainID(ctx)
		if err != nil {
			return err
		}
		if chain != m.ChainID {
			return fmt.Errorf("RPC chain ID differs from manifest")
		}
		for name, module := range m.Modules {
			code, err := reader.Code(ctx, module.Address)
			if err != nil {
				return err
			}
			if len(code) == 0 {
				return fmt.Errorf("no deployed code at %s", name)
			}
		}
		checked = true
	}
	return json.NewEncoder(os.Stdout).Encode(map[string]any{"chain_id": m.ChainID, "modules": len(abis), "artifact_pins_valid": true, "rpc_chain_and_code_checked": checked, "execution_enabled": false})
}
