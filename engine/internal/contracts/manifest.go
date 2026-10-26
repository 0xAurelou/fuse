package contracts

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"strings"

	"github.com/ethereum/go-ethereum/accounts/abi"
	"github.com/ethereum/go-ethereum/common"
)

type Module struct {
	Address  common.Address `json:"address"`
	Version  string         `json:"version"`
	Artifact string         `json:"artifact"`
	SHA256   string         `json:"sha256"`
}
type Manifest struct {
	ChainID       uint64            `json:"chain_id"`
	Confirmations uint64            `json:"confirmations"`
	Modules       map[string]Module `json:"modules"`
}

var RequiredModules = []string{"AccessController", "CustomerCustodyVault", "LPVault", "SettlementController", "WithdrawalGateway", "FUSEToken", "RewardDistributor", "RedemptionReserve"}

// LoadManifest verifies compiled artifact bytes, addresses and event/function
// shapes. Runtime chain ID, code, wiring and signer generation need independent
// RPC verification before any deployment adapter can be activated.
func LoadManifest(path string) (Manifest, map[string]abi.ABI, error) {
	var m Manifest
	raw, err := os.ReadFile(path)
	if err != nil {
		return m, nil, err
	}
	if err = json.Unmarshal(raw, &m); err != nil {
		return m, nil, err
	}
	if (m.ChainID != 998 && m.ChainID != 999 && m.ChainID != 31337) || m.Confirmations == 0 {
		return m, nil, fmt.Errorf("unsupported chain or missing finality policy")
	}
	out := map[string]abi.ABI{}
	seen := map[common.Address]bool{}
	requiredEvents := map[string]string{"CustomerCustodyVault": "DepositCredited", "LPVault": "NetTraderWinsFunded", "SettlementController": "CheckpointFinalized", "WithdrawalGateway": "Withdrawn", "FUSEToken": "Transfer", "RewardDistributor": "EpochPublished", "RedemptionReserve": "RedemptionRequested", "AccessController": "SignerRotated"}
	modules := append([]string{}, RequiredModules...)
	for name, event := range map[string]string{"LPShareVault": "RedeemRequest", "LPIncentiveDistributor": "LPRewardsPublished"} {
		if _, exists := m.Modules[name]; exists {
			modules = append(modules, name)
			requiredEvents[name] = event
		}
	}
	for _, name := range modules {
		mod, ok := m.Modules[name]
		if !ok || mod.Address == (common.Address{}) || seen[mod.Address] || mod.Version == "" {
			return m, nil, fmt.Errorf("invalid module %s", name)
		}
		seen[mod.Address] = true
		b, _, err := PinnedArtifact(path, mod)
		if err != nil {
			return m, nil, fmt.Errorf("%s: %w", name, err)
		}
		var obj struct {
			ABI json.RawMessage `json:"abi"`
		}
		if err = json.Unmarshal(b, &obj); err != nil {
			return m, nil, err
		}
		parsed, err := abi.JSON(strings.NewReader(string(obj.ABI)))
		if err != nil {
			return m, nil, err
		}
		if _, ok := parsed.Events[requiredEvents[name]]; !ok {
			return m, nil, fmt.Errorf("missing event %s.%s", name, requiredEvents[name])
		}
		out[name] = parsed
	}
	return m, out, nil
}

// PinnedArtifact allows an exact-hash local cache to preserve older deployments
// whose original artifact path pointed into a mutable build directory. The
// manifest and its deployment binding are unchanged; no digest check is relaxed.
func PinnedArtifact(manifestPath string, mod Module) ([]byte, string, error) {
	original := mod.Artifact
	if !filepath.IsAbs(original) {
		original = filepath.Join(filepath.Dir(manifestPath), original)
	}
	for _, candidate := range []string{original, filepath.Join(filepath.Dir(manifestPath), "artifacts", filepath.Base(mod.Artifact))} {
		raw, err := os.ReadFile(candidate)
		if err != nil {
			continue
		}
		h := sha256.Sum256(raw)
		if hex.EncodeToString(h[:]) == mod.SHA256 {
			return raw, candidate, nil
		}
	}
	return nil, "", fmt.Errorf("artifact pin mismatch or unavailable: %s", mod.Artifact)
}
