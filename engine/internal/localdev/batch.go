package localdev

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"math/big"
	"net/http"

	"fuse/engine/internal/contracts"
	"github.com/ethereum/go-ethereum/common/hexutil"
)

// UintBatch retains all per-account checks at one pinned block while avoiding
// hundreds of separate HTTP round trips. IDs are verified even if reordered.
func (e *Environment) UintBatch(ctx context.Context, module, method string, block uint64, arguments [][]any) ([]*big.Int, error) {
	if len(arguments) == 0 {
		return []*big.Int{}, nil
	}
	if len(arguments) > MaxLocalTraders {
		result := make([]*big.Int, 0, len(arguments))
		for start := 0; start < len(arguments); start += MaxLocalTraders {
			part, err := e.UintBatch(ctx, module, method, block, arguments[start:min(start+MaxLocalTraders, len(arguments))])
			if err != nil {
				return nil, err
			}
			result = append(result, part...)
		}
		return result, nil
	}
	tag := "latest"
	if block != 0 {
		tag = hexutil.EncodeUint64(block)
	}
	requests := make([]any, 0, len(arguments))
	indices := map[uint64]int{}
	for index, args := range arguments {
		data, err := e.ABIs[module].Pack(method, args...)
		if err != nil {
			return nil, err
		}
		id := e.RPC.id.Add(1)
		indices[id] = index
		requests = append(requests, map[string]any{"jsonrpc": "2.0", "id": id, "method": "eth_call", "params": []any{map[string]string{"to": e.Address(module).Hex(), "data": hexutil.Encode(data)}, tag}})
	}
	raw, err := json.Marshal(requests)
	if err != nil {
		return nil, err
	}
	req, err := http.NewRequestWithContext(ctx, "POST", e.RPC.URL, bytes.NewReader(raw))
	if err != nil {
		return nil, err
	}
	req.Header.Set("Content-Type", "application/json")
	response, err := e.RPC.client.Do(req)
	if err != nil {
		return nil, err
	}
	defer response.Body.Close()
	if response.StatusCode != 200 {
		if response.StatusCode == 429 || response.StatusCode >= 500 {
			return nil, fmt.Errorf("%w: batch HTTP status %d", contracts.ErrRPCUnavailable, response.StatusCode)
		}
		return nil, fmt.Errorf("RPC batch HTTP status %d", response.StatusCode)
	}
	var envelopes []struct {
		ID     uint64          `json:"id"`
		Result json.RawMessage `json:"result"`
		Error  *struct {
			Code    int    `json:"code"`
			Message string `json:"message"`
		} `json:"error"`
	}
	if err = json.NewDecoder(io.LimitReader(response.Body, 16<<20)).Decode(&envelopes); err != nil {
		return nil, err
	}
	if len(envelopes) != len(arguments) {
		return nil, fmt.Errorf("RPC batch response count mismatch")
	}
	result := make([]*big.Int, len(arguments))
	for _, envelope := range envelopes {
		index, ok := indices[envelope.ID]
		if !ok || result[index] != nil {
			return nil, fmt.Errorf("RPC batch response ID mismatch")
		}
		if envelope.Error != nil {
			return nil, fmt.Errorf("RPC batch %s: %d: %s", method, envelope.Error.Code, envelope.Error.Message)
		}
		var encoded string
		if err = json.Unmarshal(envelope.Result, &encoded); err != nil {
			return nil, err
		}
		data, err := hexutil.Decode(encoded)
		if err != nil {
			return nil, err
		}
		values, err := e.ABIs[module].Unpack(method, data)
		if err != nil {
			return nil, err
		}
		if len(values) != 1 {
			return nil, fmt.Errorf("RPC batch expected single uint output")
		}
		value, ok := values[0].(*big.Int)
		if !ok || value.Sign() < 0 {
			return nil, fmt.Errorf("RPC batch expected uint256")
		}
		result[index] = value
	}
	return result, nil
}
