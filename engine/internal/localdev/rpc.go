// Package localdev integrates the real FUSE contracts with a loopback Anvil chain.
// Its well-known development keys cannot be used with any other chain or client.
package localdev

import (
	"bytes"
	"context"
	"crypto/ecdsa"
	"encoding/json"
	"fmt"
	"io"
	"math/big"
	"net"
	"net/http"
	"net/url"
	"strconv"
	"strings"
	"sync/atomic"
	"time"

	"fuse/engine/internal/contracts"
	"github.com/ethereum/go-ethereum/common"
	"github.com/ethereum/go-ethereum/common/hexutil"
	"github.com/ethereum/go-ethereum/core/types"
	"github.com/ethereum/go-ethereum/crypto"
)

const ChainID uint64 = 31337
const (
	Governance       = 1
	SettlementSigner = 2
	RiskSigner       = 3
	WithdrawalSigner = 4
	Alice            = 5
	Bob              = 6
	MaxLocalTraders  = 300
)

func DevKey(index int) (*ecdsa.PrivateKey, error) {
	if index < 1 || index >= Alice+MaxLocalTraders {
		return nil, fmt.Errorf("unknown development wallet")
	}
	return crypto.HexToECDSA(fmt.Sprintf("%064x", index))
}
func Wallet(index int) common.Address {
	k, err := DevKey(index)
	if err != nil {
		return common.Address{}
	}
	return crypto.PubkeyToAddress(k.PublicKey)
}

type RPC struct {
	*contracts.RPCReader
	client *http.Client
	id     atomic.Uint64
}

func Connect(ctx context.Context, endpoint string) (*RPC, error) {
	u, err := url.Parse(endpoint)
	if err != nil || u.Scheme != "http" || u.User != nil || u.RawQuery != "" || u.Fragment != "" {
		return nil, fmt.Errorf("local integration requires an http loopback RPC")
	}
	ip := net.ParseIP(u.Hostname())
	if ip == nil || !ip.IsLoopback() {
		return nil, fmt.Errorf("RPC must use a literal loopback IP address")
	}
	// No proxies, redirects or DNS resolution may turn the loopback guard into a
	// public-network signing capability.
	client := &http.Client{Timeout: 60 * time.Second, Transport: &http.Transport{Proxy: nil}, CheckRedirect: func(*http.Request, []*http.Request) error { return fmt.Errorf("RPC redirects refused") }}
	r := &RPC{RPCReader: &contracts.RPCReader{URL: endpoint, Client: client}, client: client}
	if err = r.guard(ctx); err != nil {
		return nil, err
	}
	return r, nil
}
func (r *RPC) guard(ctx context.Context) error {
	chain, err := r.ChainID(ctx)
	if err != nil {
		return err
	}
	var version string
	if err = r.ReadRPC(ctx, "web3_clientVersion", []any{}, &version); err != nil {
		return err
	}
	if chain != ChainID || !strings.HasPrefix(strings.ToLower(version), "anvil/") {
		return fmt.Errorf("local execution requires Anvil with chain ID 31337")
	}
	return nil
}
func (r *RPC) write(ctx context.Context, method string, params any, out any) error {
	if err := r.guard(ctx); err != nil {
		return err
	}
	allowed := map[string]bool{"eth_sendRawTransaction": true, "anvil_setBalance": true, "anvil_mine": true, "evm_increaseTime": true, "anvil_setAutomine": true, "evm_snapshot": true, "evm_revert": true}
	if !allowed[method] {
		return fmt.Errorf("unsupported local RPC mutation")
	}
	id := r.id.Add(1)
	raw, _ := json.Marshal(map[string]any{"jsonrpc": "2.0", "id": id, "method": method, "params": params})
	req, err := http.NewRequestWithContext(ctx, "POST", r.URL, bytes.NewReader(raw))
	if err != nil {
		return err
	}
	req.Header.Set("Content-Type", "application/json")
	resp, err := r.client.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	if resp.StatusCode != 200 {
		return fmt.Errorf("RPC HTTP %d", resp.StatusCode)
	}
	var result struct {
		Result json.RawMessage `json:"result"`
		Error  *struct {
			Message string `json:"message"`
		} `json:"error"`
	}
	b, err := io.ReadAll(io.LimitReader(resp.Body, 16<<20))
	if err != nil {
		return err
	}
	if err = json.Unmarshal(b, &result); err != nil {
		return err
	}
	if result.Error != nil {
		return fmt.Errorf("%s: %s", method, result.Error.Message)
	}
	if out != nil {
		return json.Unmarshal(result.Result, out)
	}
	return nil
}
func (r *RPC) Mine(ctx context.Context, blocks uint64) error {
	return r.write(ctx, "anvil_mine", []any{hexutil.EncodeUint64(blocks)}, nil)
}
func (r *RPC) Advance(ctx context.Context, seconds uint64) error {
	if seconds > 3600 {
		return fmt.Errorf("local time advance capped at one hour")
	}
	if err := r.write(ctx, "evm_increaseTime", []any{seconds}, nil); err != nil {
		return err
	}
	return r.Mine(ctx, 1)
}
func (r *RPC) FundGas(ctx context.Context, address common.Address) error {
	return r.write(ctx, "anvil_setBalance", []any{address, hexutil.EncodeBig(new(big.Int).Mul(big.NewInt(1000), big.NewInt(1e18)))}, nil)
}
func (r *RPC) Call(ctx context.Context, to common.Address, data []byte, block uint64) ([]byte, error) {
	var out hexutil.Bytes
	tag := "latest"
	if block != 0 {
		tag = hexutil.EncodeUint64(block)
	}
	err := r.ReadRPC(ctx, "eth_call", []any{map[string]any{"to": to, "data": hexutil.Encode(data)}, tag}, &out)
	return []byte(out), err
}
func (r *RPC) Prepare(ctx context.Context, wallet int, to *common.Address, data []byte) (*types.Transaction, []byte, error) {
	if err := r.guard(ctx); err != nil {
		return nil, nil, err
	}
	key, err := DevKey(wallet)
	if err != nil {
		return nil, nil, err
	}
	sender := crypto.PubkeyToAddress(key.PublicKey)
	var nonce hexutil.Uint64
	var gasPrice hexutil.Big
	if err = r.ReadRPC(ctx, "eth_getTransactionCount", []any{sender, "pending"}, &nonce); err != nil {
		return nil, nil, err
	}
	if err = r.ReadRPC(ctx, "eth_gasPrice", []any{}, &gasPrice); err != nil {
		return nil, nil, err
	}
	msg := map[string]any{"from": sender, "data": hexutil.Encode(data)}
	if to != nil {
		msg["to"] = to
	}
	var gas hexutil.Uint64
	if err = r.ReadRPC(ctx, "eth_estimateGas", []any{msg}, &gas); err != nil {
		return nil, nil, err
	}
	tx := types.NewTx(&types.LegacyTx{Nonce: uint64(nonce), To: to, Value: new(big.Int), Gas: uint64(gas) + uint64(gas)/4 + 10000, GasPrice: (*big.Int)(&gasPrice), Data: data})
	tx, err = types.SignTx(tx, types.LatestSignerForChainID(new(big.Int).SetUint64(ChainID)), key)
	if err != nil {
		return nil, nil, err
	}
	raw, err := tx.MarshalBinary()
	return tx, raw, err
}
func (r *RPC) Broadcast(ctx context.Context, raw []byte) (common.Hash, error) {
	var tx types.Transaction
	if err := tx.UnmarshalBinary(raw); err != nil {
		return common.Hash{}, err
	}
	if tx.ChainId().Uint64() != ChainID {
		return common.Hash{}, fmt.Errorf("signed transaction chain mismatch")
	}
	var hash common.Hash
	err := r.write(ctx, "eth_sendRawTransaction", []any{hexutil.Encode(raw)}, &hash)
	if err == nil && hash != tx.Hash() {
		return common.Hash{}, fmt.Errorf("RPC returned unexpected transaction hash")
	}
	return tx.Hash(), err
}
func (r *RPC) Receipt(ctx context.Context, hash common.Hash) (*types.Receipt, error) {
	var receipt *types.Receipt
	err := r.ReadRPC(ctx, "eth_getTransactionReceipt", []any{hash}, &receipt)
	return receipt, err
}
func (r *RPC) Wait(ctx context.Context, hash common.Hash) (*types.Receipt, error) {
	ticker := time.NewTicker(50 * time.Millisecond)
	defer ticker.Stop()
	for {
		receipt, err := r.Receipt(ctx, hash)
		if err == nil && receipt != nil {
			return receipt, nil
		}
		select {
		case <-ctx.Done():
			return nil, ctx.Err()
		case <-ticker.C:
		}
	}
}
func (r *RPC) Send(ctx context.Context, wallet int, to *common.Address, data []byte) (*types.Receipt, error) {
	tx, raw, err := r.Prepare(ctx, wallet, to, data)
	if err != nil {
		return nil, err
	}
	if _, err = r.Broadcast(ctx, raw); err != nil {
		return nil, err
	}
	receipt, err := r.Wait(ctx, tx.Hash())
	if err != nil {
		return nil, err
	}
	if receipt.Status != 1 {
		return nil, fmt.Errorf("local transaction reverted: %s", tx.Hash())
	}
	return receipt, nil
}
func (r *RPC) Timestamp(ctx context.Context) (uint64, error) {
	head, err := r.Head(ctx)
	if err != nil {
		return 0, err
	}
	var block struct {
		Timestamp string `json:"timestamp"`
	}
	if err = r.ReadRPC(ctx, "eth_getBlockByNumber", []any{hexutil.EncodeUint64(head), false}, &block); err != nil {
		return 0, err
	}
	return strconv.ParseUint(strings.TrimPrefix(block.Timestamp, "0x"), 16, 64)
}
