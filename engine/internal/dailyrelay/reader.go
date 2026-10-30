package dailyrelay

import (
	"context"
	"encoding/json"
	"fmt"
	"math/big"
	"os"
	"strings"

	"fuse/engine/internal/contracts"
	"fuse/engine/internal/engine"
	"github.com/ethereum/go-ethereum/accounts/abi"
	"github.com/ethereum/go-ethereum/common"
	"github.com/ethereum/go-ethereum/common/hexutil"
	"github.com/ethereum/go-ethereum/core/types"
	"github.com/ethereum/go-ethereum/crypto"
)

type RPC interface {
	ReadRPC(context.Context, string, any, any) error
}
type ModulePin struct {
	contracts.Module
	RuntimeHash common.Hash `json:"runtime_hash"`
}
type Manifest struct {
	ChainID       uint64               `json:"chain_id"`
	Confirmations uint64               `json:"confirmations"`
	Anchor        contracts.Cursor     `json:"anchor"`
	Modules       map[string]ModulePin `json:"modules"`
}
type Reader struct {
	manifest  Manifest
	abis      map[string]abi.ABI
	rpc       RPC
	canonical *engine.Sequencer
}
type Snapshot struct {
	Number, Time, Day uint64
	Hash              common.Hash
	Generation        *big.Int
	LimitsHash        common.Hash
}
type blockHeader struct {
	Number    hexutil.Uint64
	Hash      common.Hash
	Timestamp hexutil.Uint64
}
type ticketView struct {
	Account           common.Address
	Stake, Multiplier *big.Int
	TermsHash         [32]byte
	Resolved          bool
	FinalVoidAt       uint64
}
type betView struct {
	Start, Expiry     uint64
	Asset, Status     uint8
	FinalVoidAt       uint64
	Stake, Liability  *big.Int
	Lots, Allocations []*big.Int
}

var required = map[string]map[string]string{
	"AccessController":  {"signatureVersion()": "uint256", "verify(bytes32,bytes32,bytes)": ""},
	"DailyBetCustody":   {"access()": "address", "lpVault()": "address", "usdc()": "address", "tickets(bytes32)": "address,uint256,uint256,bytes32,bool,uint64", "hashBatch((bytes32,uint8,uint64,bytes32,uint64)[],bytes32,uint64)": "bytes32", "hashOutcome((bytes32,uint8,uint64,bytes32,uint64))": "bytes32", "hashQuote((bytes32,address,uint8,uint256,uint256,uint256,uint256,uint256,uint64,uint64,bytes32))": "bytes32"},
	"DailyLPVault":      {"access()": "address", "custody()": "address", "usdc()": "address", "reserve()": "address", "limitsHash()": "bytes32", "currentDay()": "uint64", "bet(bytes32)": "(uint64,uint64,uint8,uint8,uint64,uint256,uint256,uint256[],uint256[])"},
	"USDC":              {"balanceOf(address)": "uint256"},
	"RedemptionReserve": {"lpVault()": "address", "usdc()": "address"},
}

// NewReader accepts only explicit pinned artifacts/runtime code and a chain
// anchor. No deployment lookup, environment default or mutable ABI is inferred.
func NewReader(path string, rpc RPC) (*Reader, error) {
	raw, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	var m Manifest
	if err = json.Unmarshal(raw, &m); err != nil {
		return nil, err
	}
	if rpc == nil || m.ChainID == 0 || m.Confirmations == 0 || m.Anchor.Hash == (common.Hash{}) {
		return nil, fmt.Errorf("daily chain/finality/anchor required")
	}
	r := &Reader{manifest: m, abis: map[string]abi.ABI{}, rpc: rpc}
	seen := map[common.Address]bool{}
	for name, methods := range required {
		pin, ok := m.Modules[name]
		if !ok || pin.Address == (common.Address{}) || pin.RuntimeHash == (common.Hash{}) || pin.Version == "" || seen[pin.Address] {
			return nil, fmt.Errorf("invalid daily module %s", name)
		}
		seen[pin.Address] = true
		artifact, _, err := contracts.PinnedArtifact(path, pin.Module)
		if err != nil {
			return nil, err
		}
		var a struct{ ABI json.RawMessage }
		if err = json.Unmarshal(artifact, &a); err != nil {
			return nil, err
		}
		parsed, err := abi.JSON(strings.NewReader(string(a.ABI)))
		if err != nil {
			return nil, err
		}
		for sig, outputs := range methods {
			method, ok := parsed.Methods[strings.Split(sig, "(")[0]]
			if !ok || method.Sig != sig {
				return nil, fmt.Errorf("daily ABI mismatch %s.%s", name, sig)
			}
			got := []string{}
			for _, out := range method.Outputs {
				got = append(got, out.Type.String())
			}
			if strings.Join(got, ",") != outputs {
				return nil, fmt.Errorf("daily ABI output mismatch %s.%s", name, sig)
			}
		}
		events := map[string]struct {
			sig     string
			indexed []bool
		}{}
		if name == "AccessController" {
			events["SignerRotated"] = struct {
				sig     string
				indexed []bool
			}{"SignerRotated(bytes32,address,uint256)", []bool{true, true, false}}
		}
		if name == "DailyBetCustody" {
			events["TicketResolved"] = struct {
				sig     string
				indexed []bool
			}{"TicketResolved(bytes32,uint8,uint64,bytes32)", []bool{true, false, false, false}}
			events["TicketAccepted"] = struct {
				sig     string
				indexed []bool
			}{"TicketAccepted(bytes32,address,bytes32,uint64,uint64)", []bool{true, true, false, false, false}}
			events["BatchSettled"] = struct {
				sig     string
				indexed []bool
			}{"BatchSettled(bytes32,bytes32,int256,uint256)", []bool{true, true, false, false}}
		}
		if name == "DailyLPVault" {
			events["FinalVoidQueued"] = struct {
				sig     string
				indexed []bool
			}{"FinalVoidQueued(bytes32,uint64)", []bool{true, false}}
			events["OutcomeRecorded"] = struct {
				sig     string
				indexed []bool
			}{"OutcomeRecorded(bytes32,uint8,uint64,int256)", []bool{true, false, false, false}}
		}
		for eventName, want := range events {
			e, ok := parsed.Events[eventName]
			if !ok || e.Anonymous || e.Sig != want.sig || len(e.Inputs) != len(want.indexed) {
				return nil, fmt.Errorf("daily event ABI mismatch %s.%s", name, eventName)
			}
			for i, indexed := range want.indexed {
				if e.Inputs[i].Indexed != indexed {
					return nil, fmt.Errorf("daily event index mismatch %s.%s", name, eventName)
				}
			}
		}
		r.abis[name] = parsed
	}
	return r, nil
}

// NewSigningReader additionally requires the operator's live canonical
// sequencer. Replay supplied by a caller is never itself signing authority.
func NewSigningReader(path string, rpc RPC, canonical *engine.Sequencer) (*Reader, error) {
	if canonical == nil {
		return nil, fmt.Errorf("canonical financial source required")
	}
	r, err := NewReader(path, rpc)
	if err != nil {
		return nil, err
	}
	r.canonical = canonical
	return r, nil
}

func (r *Reader) sourceFence(ctx context.Context, j *Journal) error {
	if r.canonical == nil || j == nil {
		return fmt.Errorf("read-only replay cannot authorize financial outcomes")
	}
	return r.canonical.VerifyFinancialSource(ctx, j.state.Sequence, j.state.JournalHash, j.state.Digest())
}

func (r *Reader) header(ctx context.Context, n uint64) (blockHeader, error) {
	var h blockHeader
	err := r.rpc.ReadRPC(ctx, "eth_getBlockByNumber", []any{hexutil.EncodeUint64(n), false}, &h)
	if err == nil && (uint64(h.Number) != n || h.Hash == (common.Hash{})) {
		err = fmt.Errorf("invalid daily block header")
	}
	return h, err
}
func (r *Reader) read(ctx context.Context, s Snapshot, module, method string, args ...any) ([]any, error) {
	a := r.abis[module]
	data, err := a.Pack(method, args...)
	if err != nil {
		return nil, err
	}
	var raw hexutil.Bytes
	err = r.rpc.ReadRPC(ctx, "eth_call", []any{map[string]any{"to": r.manifest.Modules[module].Address, "data": hexutil.Encode(data)}, hexutil.EncodeUint64(s.Number)}, &raw)
	if err != nil {
		return nil, err
	}
	return a.Unpack(method, raw)
}
func (r *Reader) one(ctx context.Context, s Snapshot, module, method string, args ...any) (any, error) {
	v, err := r.read(ctx, s, module, method, args...)
	if err != nil {
		return nil, err
	}
	if len(v) != 1 {
		return nil, fmt.Errorf("invalid daily scalar %s.%s", module, method)
	}
	return v[0], nil
}
func (r *Reader) stable(ctx context.Context, s Snapshot) error {
	h, err := r.header(ctx, s.Number)
	if err != nil {
		return err
	}
	if h.Hash != s.Hash {
		return contracts.ErrFinalityReorg
	}
	return nil
}

func (r *Reader) Snapshot(ctx context.Context) (Snapshot, error) {
	var chain, head hexutil.Uint64
	if err := r.rpc.ReadRPC(ctx, "eth_chainId", []any{}, &chain); err != nil {
		return Snapshot{}, err
	}
	if uint64(chain) != r.manifest.ChainID {
		return Snapshot{}, fmt.Errorf("daily chain mismatch")
	}
	if err := r.rpc.ReadRPC(ctx, "eth_blockNumber", []any{}, &head); err != nil {
		return Snapshot{}, err
	}
	if uint64(head) < r.manifest.Confirmations {
		return Snapshot{}, contracts.ErrAwaitFinality
	}
	n := uint64(head) - r.manifest.Confirmations
	if n < r.manifest.Anchor.Number {
		return Snapshot{}, contracts.ErrAwaitFinality
	}
	anchor, err := r.header(ctx, r.manifest.Anchor.Number)
	if err != nil {
		return Snapshot{}, err
	}
	if anchor.Hash != r.manifest.Anchor.Hash {
		return Snapshot{}, contracts.ErrFinalityReorg
	}
	h, err := r.header(ctx, n)
	if err != nil {
		return Snapshot{}, err
	}
	s := Snapshot{Number: n, Time: uint64(h.Timestamp), Hash: h.Hash}
	if s.Time > uint64(^uint64(0)>>1)/1000 {
		return Snapshot{}, fmt.Errorf("daily chain timestamp exceeds native clock")
	}
	for name, pin := range r.manifest.Modules {
		if _, ok := r.abis[name]; !ok {
			continue
		}
		var code hexutil.Bytes
		if err = r.rpc.ReadRPC(ctx, "eth_getCode", []any{pin.Address, hexutil.EncodeUint64(n)}, &code); err != nil {
			return Snapshot{}, err
		}
		if len(code) == 0 || crypto.Keccak256Hash(code) != pin.RuntimeHash {
			return Snapshot{}, fmt.Errorf("daily runtime mismatch %s", name)
		}
	}
	for _, w := range [][3]string{{"DailyBetCustody", "access", "AccessController"}, {"DailyBetCustody", "lpVault", "DailyLPVault"}, {"DailyBetCustody", "usdc", "USDC"}, {"DailyLPVault", "access", "AccessController"}, {"DailyLPVault", "custody", "DailyBetCustody"}, {"DailyLPVault", "usdc", "USDC"}, {"DailyLPVault", "reserve", "RedemptionReserve"}, {"RedemptionReserve", "lpVault", "DailyLPVault"}, {"RedemptionReserve", "usdc", "USDC"}} {
		v, err := r.one(ctx, s, w[0], w[1])
		if err != nil {
			return Snapshot{}, err
		}
		if v != r.manifest.Modules[w[2]].Address {
			return Snapshot{}, fmt.Errorf("daily wiring mismatch %s.%s", w[0], w[1])
		}
	}
	v, err := r.one(ctx, s, "AccessController", "signatureVersion")
	if err != nil {
		return Snapshot{}, err
	}
	s.Generation = v.(*big.Int)
	if s.Generation.Sign() <= 0 {
		return Snapshot{}, fmt.Errorf("invalid daily signer generation")
	}
	v, err = r.one(ctx, s, "DailyLPVault", "currentDay")
	if err != nil {
		return Snapshot{}, err
	}
	s.Day = v.(uint64)
	if s.Day > s.Time/86400 {
		return Snapshot{}, fmt.Errorf("daily accounting period is ahead of confirmed chain time")
	}
	v, err = r.one(ctx, s, "DailyLPVault", "limitsHash")
	if err != nil {
		return Snapshot{}, err
	}
	s.LimitsHash = v.([32]byte)
	if err = r.stable(ctx, s); err != nil {
		return Snapshot{}, err
	}
	return s, nil
}

// Binding contains immutable acceptance identity. A fresh snapshot is required
// before every signing attempt; persisting this record does not freeze finality.
type Binding struct {
	ChainID           uint64         `json:"chain_id"`
	Custody           common.Address `json:"custody"`
	StageID           string         `json:"stage_id"`
	StageCommitment   common.Hash    `json:"stage_commitment"`
	TicketID          common.Hash    `json:"ticket_id"`
	Generation        string         `json:"acceptance_signature_version"`
	LimitsHash        common.Hash    `json:"limits_hash"`
	TermsHash         common.Hash    `json:"terms_hash"`
	TxHash            common.Hash    `json:"acceptance_transaction"`
	Block             uint64         `json:"acceptance_block"`
	BlockHash         common.Hash    `json:"acceptance_block_hash"`
	LogIndex          uint           `json:"acceptance_log_index"`
	StartMS, ExpiryMS uint64
	verified          common.Hash
}

func (b Binding) identityHash() common.Hash {
	raw, _ := json.Marshal(b)
	return crypto.Keccak256Hash(raw)
}
func (b Binding) validProof() bool {
	return b.verified != (common.Hash{}) && b.verified == b.identityHash()
}

func (r *Reader) Bind(ctx context.Context, j *Journal, stageID string, ticket, tx common.Hash, generation string) (Binding, error) {
	s, err := r.Snapshot(ctx)
	if err != nil {
		return Binding{}, err
	}
	b, err := r.bind(ctx, s, j, stageID, ticket, tx, generation)
	if err != nil {
		return Binding{}, err
	}
	if err = r.stable(ctx, s); err != nil {
		return Binding{}, err
	}
	return b, nil
}

func (r *Reader) bind(ctx context.Context, s Snapshot, j *Journal, stageID string, ticket, tx common.Hash, generation string) (Binding, error) {
	p, err := j.Stage(stageID)
	if err != nil {
		return Binding{}, err
	}
	q, err := QuoteForStage(p, ticket)
	if err != nil {
		return Binding{}, err
	}
	gen, ok := new(big.Int).SetString(generation, 10)
	if !ok || gen.Sign() <= 0 || gen.BitLen() > 256 || gen.String() != generation || gen.Cmp(s.Generation) > 0 || tx == (common.Hash{}) {
		return Binding{}, fmt.Errorf("invalid acceptance generation/transaction")
	}
	digest, err := q.Digest(new(big.Int).SetUint64(r.manifest.ChainID), r.manifest.Modules["DailyBetCustody"].Address, s.LimitsHash, gen)
	if err != nil {
		return Binding{}, err
	}
	var receipt types.Receipt
	if err = r.rpc.ReadRPC(ctx, "eth_getTransactionReceipt", []any{tx}, &receipt); err != nil {
		return Binding{}, err
	}
	if receipt.TxHash != tx || receipt.Status != 1 || receipt.BlockNumber == nil || !receipt.BlockNumber.IsUint64() || receipt.BlockHash == (common.Hash{}) {
		return Binding{}, fmt.Errorf("invalid daily acceptance receipt")
	}
	n := receipt.BlockNumber.Uint64()
	if n > s.Number {
		return Binding{}, contracts.ErrAwaitFinality
	}
	origin, err := r.header(ctx, n)
	if err != nil {
		return Binding{}, err
	}
	if origin.Hash != receipt.BlockHash {
		return Binding{}, contracts.ErrFinalityReorg
	}
	event := r.abis["DailyBetCustody"].Events["TicketAccepted"]
	var accepted *types.Log
	var start, expiry uint64
	for _, l := range receipt.Logs {
		if l.Address != r.manifest.Modules["DailyBetCustody"].Address || len(l.Topics) == 0 || l.Topics[0] != event.ID {
			continue
		}
		if len(l.Topics) != 3 || l.Topics[1] != ticket {
			continue
		}
		if accepted != nil || l.Removed || l.BlockHash != receipt.BlockHash || l.BlockNumber != n || l.TxHash != tx || l.Topics[2] != common.BytesToHash(q.Account.Bytes()) {
			return Binding{}, fmt.Errorf("invalid/duplicate daily acceptance event")
		}
		values, err := event.Inputs.NonIndexed().Unpack(l.Data)
		if err != nil {
			return Binding{}, err
		}
		if values[0].([32]byte) != digest {
			return Binding{}, fmt.Errorf("native/onchain quote commitment mismatch")
		}
		start, expiry = values[1].(uint64), values[2].(uint64)
		accepted = l
	}
	if accepted == nil || origin.Timestamp > hexutil.Uint64(^uint64(0)/1000) || start != uint64(origin.Timestamp)*1000 || int64(start) != p.Start || int64(expiry) != p.Expiry || expiry-start != 30_000 {
		return Binding{}, fmt.Errorf("native/onchain acceptance time mismatch or event missing")
	}
	t, bv, err := r.views(ctx, s, ticket)
	if err != nil {
		return Binding{}, err
	}
	if t.Account != q.Account || t.TermsHash != digest || t.Stake.Cmp(q.Stake) != 0 || t.Multiplier.Cmp(q.Multiplier) != 0 || bv.Start != start || bv.Expiry != expiry || bv.Asset != q.Asset || bv.Stake.Cmp(q.Stake) != 0 || bv.Liability.Cmp(big.NewInt(p.Terms.Payout-p.Terms.Stake)) != 0 {
		return Binding{}, fmt.Errorf("native/onchain stored ticket mismatch")
	}
	b := Binding{ChainID: r.manifest.ChainID, Custody: r.manifest.Modules["DailyBetCustody"].Address, StageID: stageID, StageCommitment: common.HexToHash(p.AcceptanceCommitment()), TicketID: ticket, Generation: generation, LimitsHash: s.LimitsHash, TermsHash: digest, TxHash: tx, Block: n, BlockHash: receipt.BlockHash, LogIndex: accepted.Index, StartMS: start, ExpiryMS: expiry}
	b.verified = b.identityHash()
	return b, nil
}

func (r *Reader) views(ctx context.Context, s Snapshot, id common.Hash) (ticketView, betView, error) {
	v, err := r.read(ctx, s, "DailyBetCustody", "tickets", id)
	if err != nil {
		return ticketView{}, betView{}, err
	}
	t := ticketView{v[0].(common.Address), v[1].(*big.Int), v[2].(*big.Int), v[3].([32]byte), v[4].(bool), v[5].(uint64)}
	v, err = r.read(ctx, s, "DailyLPVault", "bet", id)
	if err != nil {
		return t, betView{}, err
	}
	// ABI shape was pinned at load; JSON conversion avoids reflection panics.
	raw, err := json.Marshal(v[0])
	if err != nil {
		return t, betView{}, err
	}
	var b betView
	if err = json.Unmarshal(raw, &b); err != nil {
		return t, b, err
	}
	if t.Stake == nil || t.Multiplier == nil || b.Stake == nil || b.Liability == nil || b.Status < 1 || b.Status > 4 || t.Resolved != (b.Status != 1) || t.FinalVoidAt != b.FinalVoidAt {
		return t, b, fmt.Errorf("inconsistent daily custody/vault state")
	}
	return t, b, nil
}
