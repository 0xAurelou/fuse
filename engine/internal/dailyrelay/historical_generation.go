package dailyrelay

import (
	"context"
	"fmt"
	"math/big"
	"sort"

	"github.com/ethereum/go-ethereum/common/hexutil"
	"github.com/ethereum/go-ethereum/core/types"
)

// A queue receipt has no typed-digest event. Derive its actual generation from
// the historical end-of-block value and every SignerRotated event after this
// direct custody transaction, rather than accepting asserted digest metadata.
func (r *Reader) generationAt(ctx context.Context, receipt *types.Receipt) (*big.Int, error) {
	s := Snapshot{Number: receipt.BlockNumber.Uint64(), Hash: receipt.BlockHash}
	if s.Number == 0 {
		return nil, fmt.Errorf("queue cannot originate in genesis")
	}
	priorHeader, err := r.header(ctx, s.Number-1)
	if err != nil {
		return nil, err
	}
	priorValue, err := r.one(ctx, Snapshot{Number: s.Number - 1, Hash: priorHeader.Hash}, "AccessController", "signatureVersion")
	if err != nil {
		return nil, err
	}
	v, err := r.one(ctx, s, "AccessController", "signatureVersion")
	if err != nil {
		return nil, err
	}
	end := v.(*big.Int)
	event := r.abis["AccessController"].Events["SignerRotated"]
	var logs []types.Log
	if err = r.rpc.ReadRPC(ctx, "eth_getLogs", []any{map[string]any{"fromBlock": hexutil.EncodeUint64(s.Number), "toBlock": hexutil.EncodeUint64(s.Number), "address": r.manifest.Modules["AccessController"].Address, "topics": []any{event.ID}}}, &logs); err != nil {
		return nil, err
	}
	for _, l := range logs {
		if l.Address != r.manifest.Modules["AccessController"].Address {
			return nil, fmt.Errorf("historical signer event address changed")
		}
	}
	result, err := generationFromRotations(priorValue.(*big.Int), end, receipt, logs, event.ID, event.Inputs.NonIndexed().Unpack)
	if err != nil {
		return nil, err
	}
	if err = r.stable(ctx, s); err != nil {
		return nil, err
	}
	if err = r.stable(ctx, Snapshot{Number: s.Number - 1, Hash: priorHeader.Hash}); err != nil {
		return nil, err
	}
	return result, nil
}

func generationFromRotations(prior, end *big.Int, receipt *types.Receipt, logs []types.Log, eventID [32]byte, unpack func([]byte) ([]any, error)) (*big.Int, error) {
	if prior == nil || prior.Sign() <= 0 || end == nil || end.Sign() <= 0 || receipt == nil || receipt.BlockNumber == nil {
		return nil, fmt.Errorf("historical signer generation unavailable")
	}
	sort.Slice(logs, func(i, j int) bool { return logs[i].Index < logs[j].Index })
	start := new(big.Int).Sub(end, big.NewInt(int64(len(logs))))
	if start.Sign() <= 0 || start.Cmp(prior) != 0 {
		return nil, fmt.Errorf("historical signer generation/events conflict")
	}
	result := new(big.Int).Set(start)
	for i, l := range logs {
		if l.Removed || l.BlockHash != receipt.BlockHash || l.BlockNumber != receipt.BlockNumber.Uint64() || len(l.Topics) != 3 || l.Topics[0] != eventID || l.TxIndex == receipt.TransactionIndex || (i > 0 && (l.Index == logs[i-1].Index || l.TxIndex < logs[i-1].TxIndex)) {
			return nil, fmt.Errorf("historical signer rotation identity/order conflict")
		}
		fields, err := unpack(l.Data)
		if err != nil {
			return nil, err
		}
		if len(fields) != 1 {
			return nil, fmt.Errorf("historical signer rotation ABI conflict")
		}
		version, ok := fields[0].(*big.Int)
		want := new(big.Int).Add(start, big.NewInt(int64(i+1)))
		if !ok || version.Cmp(want) != 0 {
			return nil, fmt.Errorf("historical signer rotation sequence conflict")
		}
		if l.TxIndex < receipt.TransactionIndex {
			result.Set(version)
		}
	}
	return result, nil
}
