package contracts

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"sync/atomic"
	"time"

	"github.com/ethereum/go-ethereum/common"
	"github.com/ethereum/go-ethereum/common/hexutil"
)

var ErrRPCUnavailable = errors.New("RPC temporarily unavailable")

// RPCReader exposes only read operations. It cannot sign or broadcast transactions.
type RPCReader struct {
	URL    string
	Client *http.Client
	id     atomic.Uint64
}

func (r *RPCReader) call(ctx context.Context, method string, params any, out any) error {
	id := r.id.Add(1)
	b, err := json.Marshal(map[string]any{"jsonrpc": "2.0", "id": id, "method": method, "params": params})
	if err != nil {
		return err
	}
	req, err := http.NewRequestWithContext(ctx, "POST", r.URL, bytes.NewReader(b))
	if err != nil {
		return err
	}
	req.Header.Set("Content-Type", "application/json")
	client := r.Client
	if client == nil {
		client = &http.Client{Timeout: 10 * time.Second}
	}
	resp, err := client.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	if resp.StatusCode != 200 {
		if resp.StatusCode == 429 || resp.StatusCode >= 500 {
			return fmt.Errorf("%w: HTTP status %d", ErrRPCUnavailable, resp.StatusCode)
		}
		return fmt.Errorf("RPC HTTP status %d", resp.StatusCode)
	}
	raw, err := io.ReadAll(io.LimitReader(resp.Body, 16<<20))
	if err != nil {
		return err
	}
	var envelope struct {
		ID     uint64          `json:"id"`
		Result json.RawMessage `json:"result"`
		Error  *struct {
			Code    int    `json:"code"`
			Message string `json:"message"`
		} `json:"error"`
	}
	if err = json.Unmarshal(raw, &envelope); err != nil {
		return err
	}
	if envelope.ID != id {
		return fmt.Errorf("RPC response ID mismatch")
	}
	if envelope.Error != nil {
		return fmt.Errorf("RPC %s error %d: %s", method, envelope.Error.Code, envelope.Error.Message)
	}
	// A missing transaction receipt is a normal pending state. Keep it distinct
	// from transport/RPC failure so recovery never mistakes an outage for absence.
	if len(envelope.Result) == 0 || (string(envelope.Result) == "null" && method != "eth_getTransactionReceipt") {
		return fmt.Errorf("RPC result unavailable")
	}
	return json.Unmarshal(envelope.Result, out)
}
func (r *RPCReader) ChainID(ctx context.Context) (uint64, error) {
	var v hexutil.Uint64
	err := r.call(ctx, "eth_chainId", []any{}, &v)
	return uint64(v), err
}
func (r *RPCReader) Head(ctx context.Context) (uint64, error) {
	var v hexutil.Uint64
	err := r.call(ctx, "eth_blockNumber", []any{}, &v)
	return uint64(v), err
}
func (r *RPCReader) Header(ctx context.Context, n uint64) (Header, error) {
	var v struct {
		Number hexutil.Uint64 `json:"number"`
		Hash   common.Hash    `json:"hash"`
		Parent common.Hash    `json:"parentHash"`
	}
	err := r.call(ctx, "eth_getBlockByNumber", []any{hexutil.EncodeUint64(n), false}, &v)
	return Header{uint64(v.Number), v.Hash, v.Parent}, err
}
func (r *RPCReader) Logs(ctx context.Context, n uint64, addresses []common.Address) ([]Log, error) {
	var raw []struct {
		Address   common.Address `json:"address"`
		Block     hexutil.Uint64 `json:"blockNumber"`
		BlockHash common.Hash    `json:"blockHash"`
		TxHash    common.Hash    `json:"transactionHash"`
		Index     hexutil.Uint64 `json:"logIndex"`
		Topics    []common.Hash  `json:"topics"`
		Data      hexutil.Bytes  `json:"data"`
		Removed   bool           `json:"removed"`
	}
	err := r.call(ctx, "eth_getLogs", []any{map[string]any{"fromBlock": hexutil.EncodeUint64(n), "toBlock": hexutil.EncodeUint64(n), "address": addresses}}, &raw)
	if err != nil {
		return nil, err
	}
	out := make([]Log, len(raw))
	for i, l := range raw {
		out[i] = Log{l.Address, uint64(l.Block), l.BlockHash, l.TxHash, uint64(l.Index), l.Topics, l.Data, l.Removed}
	}
	return out, nil
}
func (r *RPCReader) Code(ctx context.Context, address common.Address) ([]byte, error) {
	var code hexutil.Bytes
	err := r.call(ctx, "eth_getCode", []any{address, "latest"}, &code)
	return []byte(code), err
}

// ReadRPC exposes standard read calls for adapters. State-changing RPC belongs
// in an explicitly guarded deployment adapter, never in the paper server.
func (r *RPCReader) ReadRPC(ctx context.Context, method string, params any, out any) error {
	switch method {
	case "eth_call", "eth_chainId", "eth_blockNumber", "eth_getTransactionReceipt", "eth_getTransactionByHash", "eth_getTransactionCount", "eth_getLogs", "eth_gasPrice", "eth_estimateGas", "eth_getBlockByNumber", "eth_getCode", "web3_clientVersion":
		return r.call(ctx, method, params, out)
	default:
		return fmt.Errorf("not a read RPC: %s", method)
	}
}
