package contracts

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"sort"

	"github.com/ethereum/go-ethereum/accounts/abi"
	"github.com/ethereum/go-ethereum/common"
)

var ErrAwaitFinality = errors.New("awaiting chain confirmations")
var ErrFinalityReorg = errors.New("finalized chain cursor reorganized; halt financial projection and reconcile")

type Header struct {
	Number       uint64
	Hash, Parent common.Hash
}
type Log struct {
	Address           common.Address
	Block             uint64
	BlockHash, TxHash common.Hash
	Index             uint64
	Topics            []common.Hash
	Data              []byte
	Removed           bool
}
type ChainReader interface {
	ChainID(context.Context) (uint64, error)
	Head(context.Context) (uint64, error)
	Header(context.Context, uint64) (Header, error)
	Logs(context.Context, uint64, []common.Address) ([]Log, error)
}
type Cursor struct {
	Number uint64      `json:"number"`
	Hash   common.Hash `json:"hash"`
}
type DecodedLog struct {
	ID, Module, Event string
	Raw               Log
	Fields            map[string]any
}
type Block struct {
	Header Header
	Events []DecodedLog
}

// Indexer is read-only and produces confirmed blocks for a transactional consumer.
// Persist block projections AND Cursor together. A finalized reorg is a hard halt,
// never an automatic reversal of deposits backing previously accepted trades.
type Indexer struct {
	Manifest Manifest
	ABIs     map[string]abi.ABI
	Reader   ChainReader
}

func (i Indexer) Next(ctx context.Context, c Cursor) (Block, error) {
	chain, err := i.Reader.ChainID(ctx)
	if err != nil {
		return Block{}, err
	}
	if chain != i.Manifest.ChainID || i.Manifest.Confirmations == 0 {
		return Block{}, fmt.Errorf("chain/finality mismatch")
	}
	if c.Hash != (common.Hash{}) {
		head, err := i.Reader.Header(ctx, c.Number)
		if err != nil {
			return Block{}, err
		}
		if head.Hash != c.Hash {
			return Block{}, ErrFinalityReorg
		}
	}
	head, err := i.Reader.Head(ctx)
	if err != nil {
		return Block{}, err
	}
	if head < i.Manifest.Confirmations || c.Number >= head-i.Manifest.Confirmations {
		return Block{}, ErrAwaitFinality
	}
	h, err := i.Reader.Header(ctx, c.Number+1)
	if err != nil {
		return Block{}, err
	}
	if h.Number != c.Number+1 || h.Hash == (common.Hash{}) || (c.Hash != (common.Hash{}) && h.Parent != c.Hash) {
		return Block{}, ErrFinalityReorg
	}
	addresses := []common.Address{}
	names := map[common.Address]string{}
	for name, m := range i.Manifest.Modules {
		addresses = append(addresses, m.Address)
		names[m.Address] = name
	}
	sort.Slice(addresses, func(a, b int) bool { return addresses[a].Hex() < addresses[b].Hex() })
	logs, err := i.Reader.Logs(ctx, h.Number, addresses)
	if err != nil {
		return Block{}, err
	}
	sort.Slice(logs, func(a, b int) bool { return logs[a].Index < logs[b].Index })
	out := Block{Header: h, Events: []DecodedLog{}}
	seen := map[string]string{}
	indices := map[uint64]string{}
	for _, l := range logs {
		if l.Block != h.Number || l.BlockHash != h.Hash || l.Removed {
			return Block{}, ErrFinalityReorg
		}
		name, ok := names[l.Address]
		if !ok || len(l.Topics) == 0 {
			return Block{}, fmt.Errorf("unexpected contract log")
		}
		compiled, ok := i.ABIs[name]
		if !ok {
			return Block{}, fmt.Errorf("ABI unavailable for %s", name)
		}
		event, err := compiled.EventByID(l.Topics[0])
		if err != nil {
			return Block{}, err
		}
		fields := map[string]any{}
		if err = event.Inputs.NonIndexed().UnpackIntoMap(fields, l.Data); err != nil {
			return Block{}, err
		}
		indexed := abi.Arguments{}
		for _, arg := range event.Inputs {
			if arg.Indexed {
				indexed = append(indexed, arg)
			}
		}
		if err = abi.ParseTopicsIntoMap(fields, indexed, l.Topics[1:]); err != nil {
			return Block{}, err
		}
		id := fmt.Sprintf("%d/%s/%s/%d", chain, l.Address.Hex(), l.TxHash.Hex(), l.Index)
		raw, _ := json.Marshal(l)
		fingerprint := string(raw)
		if old, ok := indices[l.Index]; ok && old != fingerprint {
			return Block{}, fmt.Errorf("conflicting block log index")
		}
		indices[l.Index] = fingerprint
		if old, exists := seen[id]; exists {
			if old != fingerprint {
				return Block{}, fmt.Errorf("conflicting duplicate chain log")
			}
			continue
		}
		seen[id] = fingerprint
		out.Events = append(out.Events, DecodedLog{id, name, event.Name, l, fields})
	}
	// Refetch after logs: an in-flight reorg must not produce a mixed block.
	check, err := i.Reader.Header(ctx, h.Number)
	if err != nil {
		return Block{}, err
	}
	if check.Hash != h.Hash {
		return Block{}, ErrFinalityReorg
	}
	return out, nil
}
