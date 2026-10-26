package localdev

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"math/big"
	"os"
	"path/filepath"
	"strings"

	"fuse/engine/internal/contracts"
	"github.com/ethereum/go-ethereum/accounts/abi"
	"github.com/ethereum/go-ethereum/common"
	"github.com/ethereum/go-ethereum/common/hexutil"
	"github.com/ethereum/go-ethereum/crypto"
)

type Deployment struct {
	contracts.Manifest
	USDC        contracts.Module `json:"usdc"`
	Genesis     common.Hash      `json:"genesis"`
	AnchorBlock uint64           `json:"anchor_block,omitempty"`
	StartBlock  uint64           `json:"start_block"`
}
type artifact struct {
	ABI      abi.ABI
	Bytecode []byte
	Module   contracts.Module
}

func readArtifact(path string) (artifact, error) {
	b, err := os.ReadFile(path)
	if err != nil {
		return artifact{}, err
	}
	var v struct {
		ABI      json.RawMessage `json:"abi"`
		Bytecode struct {
			Object string `json:"object"`
		} `json:"bytecode"`
	}
	if err = json.Unmarshal(b, &v); err != nil {
		return artifact{}, err
	}
	parsed, err := abi.JSON(strings.NewReader(string(v.ABI)))
	if err != nil {
		return artifact{}, err
	}
	bin, err := hexutil.Decode(v.Bytecode.Object)
	if err != nil {
		return artifact{}, err
	}
	h := sha256.Sum256(b)
	abs, err := filepath.Abs(path)
	if err != nil {
		return artifact{}, err
	}
	return artifact{parsed, bin, contracts.Module{Version: "fuse-local-tokenomics-v2", Artifact: abs, SHA256: hex.EncodeToString(h[:])}}, nil
}

type Environment struct {
	Deployment Deployment
	ABIs       map[string]abi.ABI
	RPC        *RPC
}

func Load(ctx context.Context, path, endpoint string) (*Environment, error) {
	m, abis, err := contracts.LoadManifest(path)
	if err != nil {
		return nil, err
	}
	if m.ChainID != ChainID {
		return nil, fmt.Errorf("local manifest must use chain 31337")
	}
	raw, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	var d Deployment
	if err = json.Unmarshal(raw, &d); err != nil {
		return nil, err
	}
	_, usdcArtifact, err := contracts.PinnedArtifact(path, d.USDC)
	if err != nil {
		return nil, err
	}
	a, err := readArtifact(usdcArtifact)
	if err != nil {
		return nil, err
	}
	if a.Module.SHA256 != d.USDC.SHA256 || d.USDC.Address == (common.Address{}) {
		return nil, fmt.Errorf("invalid local USDC pin")
	}
	abis["USDC"] = a.ABI
	rpc, err := Connect(ctx, endpoint)
	if err != nil {
		return nil, err
	}
	genesis, err := rpc.Header(ctx, d.AnchorBlock)
	if err != nil {
		return nil, err
	}
	if genesis.Hash != d.Genesis {
		return nil, fmt.Errorf("Anvil chain anchor differs from deployment; use a fresh local database")
	}
	e := &Environment{d, abis, rpc}
	for _, name := range append(append([]string{}, contracts.RequiredModules...), "USDC") {
		code, err := rpc.Code(ctx, e.Address(name))
		if err != nil {
			return nil, err
		}
		if len(code) == 0 {
			return nil, fmt.Errorf("no deployed %s", name)
		}
	}
	return e, nil
}
func (e *Environment) Address(name string) common.Address {
	if name == "USDC" {
		return e.Deployment.USDC.Address
	}
	return e.Deployment.Modules[name].Address
}
func (e *Environment) Data(module, method string, args ...any) ([]byte, error) {
	compiled, ok := e.ABIs[module]
	if !ok {
		return nil, fmt.Errorf("unknown module %s", module)
	}
	return compiled.Pack(method, args...)
}
func (e *Environment) Read(ctx context.Context, module, method string, block uint64, args ...any) ([]any, error) {
	data, err := e.Data(module, method, args...)
	if err != nil {
		return nil, err
	}
	raw, err := e.RPC.Call(ctx, e.Address(module), data, block)
	if err != nil {
		return nil, fmt.Errorf("%s.%s: %w", module, method, err)
	}
	return e.ABIs[module].Unpack(method, raw)
}
func (e *Environment) Uint(ctx context.Context, module, method string, block uint64, args ...any) (*big.Int, error) {
	out, err := e.Read(ctx, module, method, block, args...)
	if err != nil {
		return nil, err
	}
	switch n := out[0].(type) {
	case *big.Int:
		return n, nil
	case uint64:
		return new(big.Int).SetUint64(n), nil
	case uint16:
		return new(big.Int).SetUint64(uint64(n)), nil
	case uint8:
		return new(big.Int).SetUint64(uint64(n)), nil
	}
	return nil, fmt.Errorf("unexpected %s.%s numeric result", module, method)
}
func (e *Environment) Direct(ctx context.Context, wallet int, module, method string, args ...any) error {
	data, err := e.Data(module, method, args...)
	if err != nil {
		return err
	}
	to := e.Address(module)
	_, err = e.RPC.Send(ctx, wallet, &to, data)
	return err
}
func DeployTo(ctx context.Context, rpc *RPC, artifacts, out string) (Deployment, error) {
	return DeployWithOptions(ctx, rpc, artifacts, out, 1_000_000_000_000, 2)
}

// DeployWithOptions seeds only local faucet USDC; amounts use six decimals.
func DeployWithOptions(ctx context.Context, rpc *RPC, artifacts, out string, initialLP int64, traders int) (Deployment, error) {
	if initialLP <= 0 || initialLP > 10_000_000_000_000 || traders < 2 || traders > MaxLocalTraders {
		return Deployment{}, fmt.Errorf("invalid local LP or trader count")
	}
	d := Deployment{Manifest: contracts.Manifest{ChainID: ChainID, Confirmations: 1, Modules: map[string]contracts.Module{}}}
	head, err := rpc.Head(ctx)
	if err != nil {
		return d, err
	}
	anchor, err := rpc.Header(ctx, head)
	if err != nil {
		return d, err
	}
	d.Genesis = anchor.Hash
	d.AnchorBlock = head
	d.StartBlock = head
	e := &Environment{Deployment: d, ABIs: map[string]abi.ABI{}, RPC: rpc}
	for wallet := 1; wallet < Alice+traders; wallet++ {
		if err = rpc.FundGas(ctx, Wallet(wallet)); err != nil {
			return d, err
		}
	}
	deploy := func(name, source string, args ...any) error {
		a, err := readArtifact(filepath.Join(artifacts, source+".sol", name+".json"))
		if err != nil {
			return err
		}
		constructor, err := a.ABI.Pack("", args...)
		if err != nil {
			return err
		}
		receipt, err := rpc.Send(ctx, Governance, nil, append(a.Bytecode, constructor...))
		if err != nil {
			return fmt.Errorf("deploy %s: %w", name, err)
		}
		// Retain the exact deployed build independently of later forge rebuilds.
		pinned, err := os.ReadFile(a.Module.Artifact)
		if err != nil {
			return err
		}
		cachePath, err := filepath.Abs(filepath.Join(filepath.Dir(out), "artifacts", name+".json"))
		if err != nil {
			return err
		}
		if err = os.MkdirAll(filepath.Dir(cachePath), 0700); err != nil {
			return err
		}
		if err = os.WriteFile(cachePath, pinned, 0600); err != nil {
			return err
		}
		a.Module.Artifact = cachePath
		a.Module.Address = receipt.ContractAddress
		e.ABIs[name] = a.ABI
		if name == "LocalUSDC" {
			e.Deployment.USDC = a.Module
			e.ABIs["USDC"] = a.ABI
		} else {
			e.Deployment.Modules[name] = a.Module
		}
		return nil
	}
	register := func(name, source string, address common.Address) error {
		a, err := readArtifact(filepath.Join(artifacts, source+".sol", name+".json"))
		if err != nil {
			return err
		}
		pinned, err := os.ReadFile(a.Module.Artifact)
		if err != nil {
			return err
		}
		cachePath, err := filepath.Abs(filepath.Join(filepath.Dir(out), "artifacts", name+".json"))
		if err != nil {
			return err
		}
		if err = os.MkdirAll(filepath.Dir(cachePath), 0700); err != nil {
			return err
		}
		if err = os.WriteFile(cachePath, pinned, 0600); err != nil {
			return err
		}
		a.Module.Artifact, a.Module.Address = cachePath, address
		e.ABIs[name] = a.ABI
		e.Deployment.Modules[name] = a.Module
		return nil
	}
	if err = deploy("LocalUSDC", "LocalUSDC"); err != nil {
		return d, err
	}
	if err = deploy("AccessController", "AccessController", Wallet(Governance)); err != nil {
		return d, err
	}
	access, usdc := e.Address("AccessController"), e.Address("USDC")
	if err = deploy("CustomerCustodyVault", "CustomerCustodyVault", access, usdc, big.NewInt(10)); err != nil {
		return d, err
	}
	if err = deploy("LPVault", "LPVault", access, usdc); err != nil {
		return d, err
	}
	if _, ok := e.ABIs["LPVault"].Methods["shareVault"]; ok {
		values, readErr := e.Read(ctx, "LPVault", "shareVault", 0)
		if readErr != nil {
			return d, readErr
		}
		if err = register("LPShareVault", "LPShareVault", values[0].(common.Address)); err != nil {
			return d, err
		}
	}
	if err = deploy("SettlementController", "SettlementController", access, e.Address("CustomerCustodyVault"), e.Address("LPVault")); err != nil {
		return d, err
	}
	if err = deploy("WithdrawalGateway", "WithdrawalGateway", access, e.Address("CustomerCustodyVault"), e.Address("SettlementController")); err != nil {
		return d, err
	}
	if err = deploy("FUSEToken", "FUSEToken", access, big.NewInt(1)); err != nil {
		return d, err
	}
	if err = deploy("RewardDistributor", "RewardDistributor", access, e.Address("FUSEToken")); err != nil {
		return d, err
	}
	if err = deploy("RedemptionReserve", "RedemptionReserve", access, usdc, e.Address("FUSEToken"), e.Address("LPVault")); err != nil {
		return d, err
	}
	if _, ok := e.Deployment.Modules["LPShareVault"]; ok {
		if err = deploy("LPIncentiveDistributor", "LPIncentiveDistributor", access, e.Address("FUSEToken"), e.Address("LPShareVault")); err != nil {
			return d, err
		}
	}
	calls := []struct {
		module, method string
		args           []any
	}{
		{"CustomerCustodyVault", "configure", []any{e.Address("SettlementController"), e.Address("WithdrawalGateway"), e.Address("LPVault")}},
		{"LPVault", "configure", []any{e.Address("CustomerCustodyVault"), e.Address("SettlementController"), e.Address("RedemptionReserve")}},
		{"FUSEToken", "setRedemptionReserve", []any{e.Address("RedemptionReserve")}},
	}
	if _, ok := e.Deployment.Modules["LPShareVault"]; ok {
		if err = e.Direct(ctx, Governance, "LPShareVault", "setIncentives", e.Address("LPIncentiveDistributor")); err != nil {
			return d, err
		}
		if err = e.Direct(ctx, Governance, "AccessController", "grantRole", crypto.Keccak256Hash([]byte("LP_REWARD_PUBLISHER")), Wallet(Governance)); err != nil {
			return d, err
		}
		if err = e.Direct(ctx, Governance, "AccessController", "grantRole", crypto.Keccak256Hash([]byte("GUARDIAN")), e.Address("SettlementController")); err != nil {
			return d, err
		}
	}
	for _, c := range calls {
		if err = e.Direct(ctx, Governance, c.module, c.method, c.args...); err != nil {
			return d, err
		}
	}
	for role, wallet := range map[string]int{"SETTLEMENT_SIGNER": SettlementSigner, "RISK_SIGNER": RiskSigner, "WITHDRAWAL_SIGNER": WithdrawalSigner} {
		if err = e.Direct(ctx, Governance, "AccessController", "setSigner", crypto.Keccak256Hash([]byte(role)), Wallet(wallet)); err != nil {
			return d, err
		}
	}
	for _, role := range []string{"LP_PROVIDER", "EMISSION_PUBLISHER", "REDEMPTION_SCHEDULER", "GUARDIAN"} {
		if err = e.Direct(ctx, Governance, "AccessController", "grantRole", crypto.Keccak256Hash([]byte(role)), Wallet(Governance)); err != nil {
			return d, err
		}
	}
	escrow, err := e.Read(ctx, "FUSEToken", "emissionEscrow", 0)
	if err != nil {
		return d, err
	}
	escrowArtifact, err := readArtifact(filepath.Join(artifacts, "AllocationEscrows.sol", "EmissionEscrow.json"))
	if err != nil {
		return d, err
	}
	data, err := escrowArtifact.ABI.Pack("setDistributor", e.Address("RewardDistributor"))
	if err != nil {
		return d, err
	}
	escrowAddress := escrow[0].(common.Address)
	if _, err = rpc.Send(ctx, Governance, &escrowAddress, data); err != nil {
		return d, err
	}
	if _, ok := e.Deployment.Modules["LPIncentiveDistributor"]; ok {
		lpEscrow, readErr := e.Read(ctx, "FUSEToken", "lpEmissionEscrow", 0)
		if readErr != nil {
			return d, readErr
		}
		lpAddress := lpEscrow[0].(common.Address)
		call, packErr := escrowArtifact.ABI.Pack("setDistributor", e.Address("LPIncentiveDistributor"))
		if packErr != nil {
			return d, packErr
		}
		if _, err = rpc.Send(ctx, Governance, &lpAddress, call); err != nil {
			return d, err
		}
		// LP phases and the 90-day campaign deliberately remain inactive.
	}
	now, err := rpc.Timestamp(ctx)
	if err != nil {
		return d, err
	}
	budget := new(big.Int).Mul(big.NewInt(1_000_000), big.NewInt(1e18))
	if err = e.Direct(ctx, Governance, "RewardDistributor", "configureEmissionSchedule", now+60, uint64(60), budget, uint16(1000)); err != nil {
		return d, err
	}
	if err = e.Direct(ctx, Governance, "RewardDistributor", "configureEmissionHorizon", now+60+180*60); err != nil {
		return d, err
	}
	if err = e.Direct(ctx, Governance, "RewardDistributor", "activateEmissions"); err != nil {
		return d, err
	}
	if err = e.Direct(ctx, Governance, "RedemptionReserve", "activateRedemptions"); err != nil {
		return d, err
	}
	if err = e.Direct(ctx, Governance, "FUSEToken", "scheduleEnableTransfers"); err != nil {
		return d, err
	}
	if err = rpc.Advance(ctx, 65); err != nil {
		return d, err
	}
	if err = e.Direct(ctx, Governance, "FUSEToken", "enableTransfers"); err != nil {
		return d, err
	}
	max := new(big.Int).Sub(new(big.Int).Lsh(big.NewInt(1), 256), big.NewInt(1))
	wallets := []int{Governance}
	for wallet := Alice; wallet < Alice+traders; wallet++ {
		wallets = append(wallets, wallet)
	}
	for _, wallet := range wallets {
		amount := big.NewInt(1_000_000_000)
		if wallet == Governance {
			amount = big.NewInt(initialLP * 2)
		}
		if err = e.Direct(ctx, Governance, "USDC", "mint", Wallet(wallet), amount); err != nil {
			return d, err
		}
		target := e.Address("CustomerCustodyVault")
		if wallet == Governance {
			target = e.Address("LPVault")
		}
		if err = e.Direct(ctx, wallet, "USDC", "approve", target, max); err != nil {
			return d, err
		}
	}
	if _, ok := e.Deployment.Modules["LPShareVault"]; ok && initialLP > 5_000_000_000_000 {
		if err = e.Direct(ctx, Governance, "LPShareVault", "setDepositPolicy", big.NewInt(initialLP), uint16(2000)); err != nil {
			return d, err
		}
	}
	if err = e.Direct(ctx, Governance, "LPVault", "depositLP", big.NewInt(initialLP)); err != nil {
		return d, err
	}
	if err = rpc.Mine(ctx, 1); err != nil {
		return d, err
	}
	d = e.Deployment
	raw, err := json.MarshalIndent(d, "", "  ")
	if err != nil {
		return d, err
	}
	if err = os.MkdirAll(filepath.Dir(out), 0700); err != nil {
		return d, err
	}
	if err = os.WriteFile(out, append(raw, '\n'), 0600); err != nil {
		return d, err
	}
	return d, nil
}
