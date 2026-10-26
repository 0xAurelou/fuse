package localdev

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"math/big"
	"net"
	"strings"
	"sync/atomic"
	"time"

	"fuse/engine/internal/contracts"
	"fuse/engine/internal/engine"
	"github.com/ethereum/go-ethereum/common"
	"github.com/ethereum/go-ethereum/common/hexutil"
	"github.com/ethereum/go-ethereum/crypto"
)

type Controller struct {
	price        atomic.Value
	Env          *Environment
	Q            *engine.Sequencer
	offset       atomic.Int64
	AfterPrepare func() error
	unavailable  atomic.Bool
	minedHead    common.Hash
}

func NewController(ctx context.Context, e *Environment, q *engine.Sequencer) (*Controller, error) {
	if q.Snapshot().Policy.Mode != "local" {
		return nil, fmt.Errorf("local policy required")
	}
	c := &Controller{Env: e, Q: q}
	c.unavailable.Store(true)
	s := q.Snapshot()
	binding := engine.Hash(e.Deployment)
	if s.Local == nil {
		h, err := e.RPC.Header(ctx, e.Deployment.StartBlock)
		if err != nil {
			return nil, err
		}
		raw, _ := json.Marshal(map[string]any{"Deployment": binding, "Cursor": h.Number, "BlockHash": h.Hash.Hex()})
		if _, err = q.Execute(ctx, engine.Command{Key: "local/bind", Kind: "local_bind", At: time.Now().UnixMilli(), Raw: raw}); err != nil {
			return nil, err
		}
	} else if s.Local.Deployment != binding {
		return nil, fmt.Errorf("database is bound to a different local deployment")
	}
	c.offset.Store(q.Snapshot().Local.ClockOffsetMS)
	price := q.Snapshot().Oracle.Price
	if price > 0 {
		c.price.Store(fmt.Sprintf("%d.%06d", price/1_000_000, price%1_000_000))
	} else {
		c.price.Store("100000")
	}
	return c, nil
}
func (c *Controller) Now() int64 { return time.Now().UnixMilli() + c.offset.Load() }
func (c *Controller) exec(ctx context.Context, w *engine.Writer, kind, key string, raw any) (engine.Event, error) {
	s := w.Snapshot()
	now := c.Now()
	if now < s.At {
		now = s.At
	}
	b, err := json.Marshal(raw)
	if err != nil {
		return engine.Event{}, err
	}
	return w.Execute(ctx, engine.Command{Key: key, Kind: kind, At: now, Raw: b})
}
func (c *Controller) Sync(ctx context.Context) error {
	return c.Q.Exclusive(func(w *engine.Writer) error { return c.sync(ctx, w) })
}
func transientRPC(err error) bool {
	var network net.Error
	return errors.Is(err, contracts.ErrRPCUnavailable) || errors.As(err, &network) || errors.Is(err, io.EOF) || errors.Is(err, io.ErrUnexpectedEOF) || errors.Is(err, context.Canceled) || errors.Is(err, context.DeadlineExceeded)
}

func (c *Controller) sync(ctx context.Context, w *engine.Writer) (resultErr error) {
	defer func() { c.unavailable.Store(resultErr != nil) }()
	s := w.Snapshot()
	if s.Local.Halted != "" {
		return fmt.Errorf("local coordinator halted: %s", s.Local.Halted)
	}
	if s.Local.Pending != "" {
		op := s.Local.Operations[s.Local.Pending]
		receipt, err := c.Env.RPC.Receipt(ctx, common.HexToHash(op.TxHash))
		if err != nil || receipt == nil {
			raw, decodeErr := hexutil.Decode(op.RawTx)
			if decodeErr != nil {
				return decodeErr
			}
			if _, err = c.Env.RPC.Broadcast(ctx, raw); err != nil {
				receipt, readErr := c.Env.RPC.Receipt(ctx, common.HexToHash(op.TxHash))
				if readErr != nil || receipt == nil {
					return err
				}
			}
		}
	}
	head, err := c.Env.RPC.Head(ctx)
	if err != nil {
		return err
	}
	header, err := c.Env.RPC.Header(ctx, head)
	if err != nil {
		return err
	}
	// Idle worker ticks do not need new historical chain states.
	if header.Hash != c.minedHead {
		if err = c.Env.RPC.Mine(ctx, c.Env.Deployment.Confirmations); err != nil {
			return err
		}
		head, err = c.Env.RPC.Head(ctx)
		if err != nil {
			return err
		}
		header, err = c.Env.RPC.Header(ctx, head)
		if err != nil {
			return err
		}
		c.minedHead = header.Hash
	}
	indexer := contracts.Indexer{Manifest: c.Env.Deployment.Manifest, ABIs: c.Env.ABIs, Reader: c.Env.RPC}
	for count := 0; count < 10000; count++ {
		s = w.Snapshot()
		block, err := indexer.Next(ctx, contracts.Cursor{Number: s.Local.Cursor, Hash: common.HexToHash(s.Local.BlockHash)})
		if errors.Is(err, contracts.ErrAwaitFinality) {
			return c.reconcile(ctx, w)
		}
		if err != nil {
			if transientRPC(err) {
				return err
			}
			return c.halt(ctx, w, err)
		}
		evidence, _ := json.Marshal(block.Events)
		projection := engine.LocalBlock{Evidence: evidence, Number: block.Header.Number, Hash: block.Header.Hash.Hex(), Parent: block.Header.Parent.Hex(), Effects: []engine.LocalEffect{}}
		for _, event := range block.Events {
			effect, err := decodeEffect(event)
			if err != nil {
				return c.halt(ctx, w, err)
			}
			projection.Effects = append(projection.Effects, effect)
		}
		if s.Local.Pending != "" {
			op := s.Local.Operations[s.Local.Pending]
			receipt, err := c.Env.RPC.Receipt(ctx, common.HexToHash(op.TxHash))
			if err == nil && receipt != nil && receipt.BlockNumber.Uint64() == block.Header.Number {
				if receipt.BlockHash != block.Header.Hash {
					return c.halt(ctx, w, contracts.ErrFinalityReorg)
				}
				ok := receipt.Status == 1
				projection.Transaction = op.TxHash
				projection.Success = &ok
			}
		}
		if _, err = c.exec(ctx, w, "local_block", fmt.Sprintf("local/block/%d/%s", block.Header.Number, block.Header.Hash.Hex()), projection); err != nil {
			return c.halt(ctx, w, err)
		}
	}
	return fmt.Errorf("local indexer catch-up limit reached")
}
func (c *Controller) halt(ctx context.Context, w *engine.Writer, cause error) error {
	s := w.Snapshot()
	_, err := w.Execute(ctx, engine.Command{Key: fmt.Sprintf("local/halt/%d", s.Sequence+1), Kind: "local_halt", At: max(c.Now(), s.At), ID: cause.Error()})
	if err != nil {
		return fmt.Errorf("%v; halt persistence failed: %w", cause, err)
	}
	return cause
}
func (c *Controller) reconcile(ctx context.Context, w *engine.Writer) error {
	s := w.Snapshot()
	block := s.Local.Cursor
	checks := []struct {
		module, method string
		want           int64
		args           []any
	}{
		{"USDC", "balanceOf", s.Custody, []any{c.Env.Address("CustomerCustodyVault")}},
		{"USDC", "balanceOf", s.LP, []any{c.Env.Address("LPVault")}},
		{"USDC", "balanceOf", s.Reserve, []any{c.Env.Address("RedemptionReserve")}},
		{"LPVault", "accountedBalance", s.LP, nil},
		{"CustomerCustodyVault", "uncreditedBalance", s.PendingDeposits(), nil},
		{"CustomerCustodyVault", "customerLiabilityUSDC", s.FundedLiability() + s.LossClearing, nil},
		{"LPVault", "cumulativeRealizedProfitUSDC", s.LPProfit, nil},
		{"LPVault", "realizedProfitHWMUSDC", s.ProfitHWM, nil},
	}
	if _, ok := c.Env.ABIs["LPVault"].Methods["totalLPAssets"]; ok {
		checks = append(checks, struct {
			module, method string
			want           int64
			args           []any
		}{"LPVault", "totalLPAssets", s.LPAvailable(), nil})
		checks = append(checks, struct {
			module, method string
			want           int64
			args           []any
		}{"LPVault", "reservedExitUSDC", s.Local.LPExitReserved, nil})
		checks = append(checks, struct {
			module, method string
			want           int64
			args           []any
		}{"LPVault", "reserveFeeAccruedUSDC", s.Local.LPFeeAccrued, nil})
	}
	// Before construction of a module, the zero initial projection has no code to
	// reconcile. Deployment.StartBlock binds the initialized chain; initial catchup
	// always reaches a post-deployment confirmed head before this function runs.
	for _, check := range checks {
		got, err := c.Env.Uint(ctx, check.module, check.method, block, check.args...)
		if err != nil {
			return err
		}
		if got.Cmp(big.NewInt(check.want)) != 0 {
			return c.halt(ctx, w, fmt.Errorf("reconciliation %s.%s: chain=%s ledger=%d", check.module, check.method, got, check.want))
		}
	}
	supply, err := c.Env.Uint(ctx, "FUSEToken", "totalSupply", block)
	if err != nil {
		return err
	}
	if supply.String() != s.Local.TokenSupply {
		return c.halt(ctx, w, fmt.Errorf("token supply mismatch"))
	}
	accounts := make([]string, 0, len(s.Accounts))
	args := make([][]any, 0, len(s.Accounts))
	for account := range s.Accounts {
		accounts = append(accounts, account)
		args = append(args, []any{common.HexToAddress(account)})
	}
	paid, err := c.Env.UintBatch(ctx, "WithdrawalGateway", "withdrawnCumulative", block, args)
	if err != nil {
		return err
	}
	for i, account := range accounts {
		if paid[i].Cmp(big.NewInt(s.Accounts[account].Withdrawn)) != 0 {
			return c.halt(ctx, w, fmt.Errorf("withdrawn cumulative mismatch for %s", account))
		}
	}
	return s.Check()
}
func decodeEffect(event contracts.DecodedLog) (engine.LocalEffect, error) {
	e := engine.LocalEffect{Module: event.Module, Event: event.Event, TxHash: strings.ToLower(event.Raw.TxHash.Hex())}
	f := event.Fields
	integer := func(name string) (*big.Int, error) {
		v, ok := f[name]
		if !ok {
			return nil, fmt.Errorf("missing %s", name)
		}
		switch n := v.(type) {
		case *big.Int:
			return n, nil
		case uint64:
			return new(big.Int).SetUint64(n), nil
		case uint16:
			return new(big.Int).SetUint64(uint64(n)), nil
		}
		return nil, fmt.Errorf("invalid numeric %s", name)
	}
	amount := func(name string) error {
		n, err := integer(name)
		if err != nil {
			return err
		}
		if !n.IsInt64() || n.Int64() > engine.Limit || n.Int64() < -engine.Limit {
			return fmt.Errorf("amount outside engine range")
		}
		e.Amount = n.Int64()
		return nil
	}
	epoch := func(name string) error {
		n, err := integer(name)
		if err != nil {
			return err
		}
		if !n.IsUint64() {
			return fmt.Errorf("epoch overflow")
		}
		e.Epoch = n.Uint64()
		return nil
	}
	addr := func(name string) string {
		a, ok := f[name].(common.Address)
		if !ok {
			return ""
		}
		return strings.ToLower(a.Hex())
	}
	hash := func(name string) string {
		switch h := f[name].(type) {
		case [32]byte:
			return common.Hash(h).Hex()
		case common.Hash:
			return h.Hex()
		}
		return ""
	}
	text := func(name string) error {
		n, err := integer(name)
		if err == nil {
			e.Value = n.String()
		}
		return err
	}
	var err error
	switch event.Module + "." + event.Event {
	case "LPVault.LPDeposited", "LPVault.LPExitReserved", "LPVault.LPExitPaid":
		err = amount("amount")
	case "LPVault.ReserveFeeAccrued":
		err = amount("amount")
		if err == nil {
			err = text("totalAccrued")
		}
	case "CustomerCustodyVault.Deposited":
		n, x := integer("id")
		if x != nil {
			return e, x
		}
		e.ID = n.String()
		e.Account = addr("beneficiary")
		err = amount("amount")
	case "CustomerCustodyVault.DepositCredited", "CustomerCustodyVault.DepositRefunded":
		n, x := integer("id")
		if x != nil {
			return e, x
		}
		e.ID = n.String()
	case "SettlementController.CheckpointFinalized":
		if err = epoch("epoch"); err == nil {
			err = amount("netTraderPnLUSDC")
		}
		e.Root = hash("newRoot")
		e.Digest = hash("digest")
	case "WithdrawalGateway.Withdrawn":
		e.Account = addr("account")
		e.Recipient = addr("recipient")
		e.ID = hash("authorizationId")
		err = amount("amount")
	case "AccessController.SignerRotated":
		err = text("signatureVersion")
	case "AccessController.TradingPauseChanged":
		paused, ok := f["paused"].(bool)
		if !ok {
			return e, fmt.Errorf("invalid pause event")
		}
		e.Value = fmt.Sprint(paused)
	case "FUSEToken.Transfer":
		e.Account = addr("from")
		e.Recipient = addr("to")
		err = text("value")
	case "RewardDistributor.EpochPublished":
		err = epoch("epoch")
		if err == nil {
			err = text("budget")
		}
		e.Root = hash("merkleRoot")
		e.Digest = hash("manifestHash")
	case "RewardDistributor.RewardClaimed":
		err = epoch("epoch")
		if err == nil {
			err = text("amount")
		}
		n, x := integer("index")
		if x != nil || !n.IsUint64() {
			return e, fmt.Errorf("invalid allocation index")
		}
		e.Index = n.Uint64()
		e.Account = addr("recipient")
	case "LPVault.ReserveFunded":
		err = amount("amount")
		if err == nil {
			err = text("consumedProfitHWM")
		}
		e.ID = hash("authorizationId")
	case "RedemptionReserve.RedemptionRequested":
		err = epoch("epoch")
		if err == nil {
			err = amount("accruedUSDC")
		}
		if err == nil {
			err = text("burnedFUSE")
		}
		e.Account = addr("account")
	case "RedemptionReserve.RedemptionClaimed":
		err = epoch("epoch")
		if err == nil {
			err = amount("amount")
		}
		e.Account = addr("account")
	}
	return e, err
}
func (c *Controller) submit(ctx context.Context, w *engine.Writer, id, kind, module, method string, payload any, args ...any) (engine.LocalOperation, error) {
	s := w.Snapshot()
	if old := s.Local.Operations[id]; old != nil {
		if old.Kind != kind {
			return engine.LocalOperation{}, fmt.Errorf("operation ID reused")
		}
		return *old, nil
	}
	data, err := c.Env.Data(module, method, args...)
	if err != nil {
		return engine.LocalOperation{}, err
	}
	to := c.Env.Address(module)
	tx, raw, err := c.Env.RPC.Prepare(ctx, Governance, &to, data)
	if err != nil {
		return engine.LocalOperation{}, err
	}
	encoded, err := json.Marshal(payload)
	if err != nil {
		return engine.LocalOperation{}, err
	}
	op := engine.LocalOperation{ID: id, Kind: kind, TxHash: strings.ToLower(tx.Hash().Hex()), RawTx: hexutil.Encode(raw), Data: encoded}
	if _, err = c.exec(ctx, w, "local_prepare", "local/prepare/"+id, op); err != nil {
		return op, err
	}
	if c.AfterPrepare != nil {
		if err = c.AfterPrepare(); err != nil {
			return op, err
		}
	}
	if _, err = c.Env.RPC.Broadcast(ctx, raw); err != nil {
		return op, err
	}
	if err = c.sync(ctx, w); err != nil {
		return op, err
	}
	op = *w.Snapshot().Local.Operations[id]
	if op.Status != "confirmed" {
		return op, fmt.Errorf("local operation %s is %s", id, op.Status)
	}
	return op, nil
}
func sign(wallet int, digest common.Hash) ([]byte, error) {
	key, err := DevKey(wallet)
	if err != nil {
		return nil, err
	}
	signature, err := crypto.Sign(digest[:], key)
	if err == nil {
		signature[64] += 27
	}
	return signature, err
}
