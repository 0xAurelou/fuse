package localdev

import (
	"context"
	"encoding/json"
	"fmt"
	"math/big"
	"strings"

	"fuse/engine/internal/contracts"
	"fuse/engine/internal/engine"
	"github.com/ethereum/go-ethereum/common"
	"github.com/ethereum/go-ethereum/common/hexutil"
	"github.com/ethereum/go-ethereum/crypto"
)

// Tuple field names mirror the compiled ABI, including acronym casing.
type settlementTuple struct {
	Epoch                                                                                                                      uint64
	PriorRoot, NewRoot, JournalHash, OracleJournalHash                                                                         [32]byte
	FromSequence, ToSequence, AsOfTimestamp                                                                                    uint64
	NetTraderPnLUSDC, CustomerLiabilityUSDC, ReportedMaxOpenExposureUSDC, ReportedRequiredLPCapitalUSDC, RealizedProfitHWMUSDC *big.Int
	DepositBatchHash                                                                                                           [32]byte
	Deadline                                                                                                                   *big.Int
}

func settlementABI(s contracts.Settlement) settlementTuple {
	return settlementTuple{s.Epoch, s.PriorRoot, s.NewRoot, s.JournalHash, s.OracleJournalHash, s.From, s.To, s.AsOf, s.NetPnL, s.CustomerLiability, s.MaxExposure, s.RequiredLP, s.ProfitHWM, s.DepositBatchHash, s.Deadline}
}
func checkedDigest(out []any, local common.Hash) error {
	if len(out) != 1 {
		return fmt.Errorf("invalid contract digest response")
	}
	remote, ok := out[0].([32]byte)
	if !ok || common.Hash(remote) != local {
		return fmt.Errorf("local/contract EIP-712 digest mismatch")
	}
	return nil
}
func (c *Controller) Settle(ctx context.Context, id string) (engine.LocalOperation, error) {
	var op engine.LocalOperation
	err := c.Q.Exclusive(func(w *engine.Writer) error { var err error; op, err = c.settle(ctx, w, id); return err })
	return op, err
}
func (c *Controller) settle(ctx context.Context, w *engine.Writer, id string) (engine.LocalOperation, error) {
	return c.settleMode(ctx, w, id, false)
}
func (c *Controller) settleMode(ctx context.Context, w *engine.Writer, id string, liquidity bool) (engine.LocalOperation, error) {
	if err := c.sync(ctx, w); err != nil {
		return engine.LocalOperation{}, err
	}
	state := w.Snapshot()
	if old := state.Local.Operations[id]; old != nil {
		var previous engine.LocalSettlement
		if err := json.Unmarshal(old.Data, &previous); err != nil {
			return *old, err
		}
		if old.Kind != "settlement" || previous.LiquidityWindow != liquidity {
			return *old, fmt.Errorf("operation ID reused")
		}
		return *old, nil
	}
	plan, err := engine.PlanLocalSettlement(state)
	if err != nil {
		return engine.LocalOperation{}, err
	}
	if liquidity && plan.Epoch.Exposure != 0 {
		return engine.LocalOperation{}, fmt.Errorf("settle all accepted exposure before opening LP liquidity")
	}
	if plan.Epoch.OracleHash == "" {
		return engine.LocalOperation{}, fmt.Errorf("oracle evidence required before a checkpoint")
	}
	ids := []*big.Int{}
	for _, id := range plan.Deposits {
		n, ok := new(big.Int).SetString(id, 10)
		if !ok {
			return engine.LocalOperation{}, fmt.Errorf("invalid deposit ID")
		}
		ids = append(ids, n)
	}
	batchHash, err := contracts.DepositBatchHash(ids)
	if err != nil {
		return engine.LocalOperation{}, err
	}
	now, err := c.Env.RPC.Timestamp(ctx)
	if err != nil {
		return engine.LocalOperation{}, err
	}
	generation, err := c.Env.Uint(ctx, "AccessController", "signatureVersion", 0)
	if err != nil {
		return engine.LocalOperation{}, err
	}
	profit := state.LPProfit - plan.Epoch.NetTraderPnL
	hwm := max(state.ProfitHWM, profit)
	p := plan.Epoch
	report := contracts.Settlement{Epoch: p.Number, PriorRoot: common.HexToHash(p.PriorRoot), NewRoot: common.HexToHash(p.Root), JournalHash: common.HexToHash(p.JournalHash), OracleJournalHash: common.HexToHash(p.OracleHash), From: p.From, To: p.To, AsOf: now, NetPnL: big.NewInt(p.NetTraderPnL), CustomerLiability: big.NewInt(p.Liability), MaxExposure: big.NewInt(p.Exposure), RequiredLP: big.NewInt(p.RequiredLP), ProfitHWM: big.NewInt(hwm), DepositBatchHash: batchHash, Deadline: new(big.Int).SetUint64(now + 3600)}
	digest, err := report.Digest(new(big.Int).SetUint64(ChainID), c.Env.Address("SettlementController"), generation)
	if err != nil {
		return engine.LocalOperation{}, err
	}
	remote, err := c.Env.Read(ctx, "SettlementController", "hashSettlement", 0, settlementABI(report))
	if err != nil {
		return engine.LocalOperation{}, err
	}
	if err = checkedDigest(remote, digest); err != nil {
		return engine.LocalOperation{}, err
	}
	settlementSig, err := sign(SettlementSigner, digest)
	if err != nil {
		return engine.LocalOperation{}, err
	}
	riskSig, err := sign(RiskSigner, digest)
	if err != nil {
		return engine.LocalOperation{}, err
	}
	plan.LiquidityWindow = liquidity
	plan.Report, _ = json.Marshal(report)
	plan.Digest = digest.Hex()
	method := "settle"
	if liquidity {
		method = "settleAndPause"
	}
	return c.submit(ctx, w, id, "settlement", "SettlementController", method, plan, settlementABI(report), ids, settlementSig, riskSig)
}

type WithdrawalTuple struct {
	Account, Recipient                common.Address
	CumulativeAmountUSDC              *big.Int
	StateVersion, ValidUntil          uint64
	AuthorizationId, AccountStateHash [32]byte
}

func TicketABI(t engine.LocalTicket) WithdrawalTuple {
	return WithdrawalTuple{common.HexToAddress(t.Account), common.HexToAddress(t.Recipient), big.NewInt(t.Cumulative), t.Epoch, t.ValidUntil, common.HexToHash(t.ID), common.HexToHash(t.AccountStateHash)}
}
func (c *Controller) Ticket(ctx context.Context, account, id string) (engine.LocalTicket, error) {
	var ticket engine.LocalTicket
	err := c.Q.Exclusive(func(w *engine.Writer) error {
		if err := c.sync(ctx, w); err != nil {
			return err
		}
		s := w.Snapshot()
		claim := s.Withdrawals[id]
		if claim == nil || claim.Account != account {
			return fmt.Errorf("withdrawal not found")
		}
		if claim.Status == "pending" {
			if _, err := c.settle(ctx, w, "funding/"+id); err != nil {
				return err
			}
			s = w.Snapshot()
			claim = s.Withdrawals[id]
		}
		if claim.Status != "funded" {
			return fmt.Errorf("withdrawal is not funded and locked")
		}
		generation, err := c.Env.Uint(ctx, "AccessController", "signatureVersion", 0)
		if err != nil {
			return err
		}
		now, err := c.Env.RPC.Timestamp(ctx)
		if err != nil {
			return err
		}
		if old, ok := s.Local.Tickets[id]; ok && old.Generation == generation.String() && old.ValidUntil >= now {
			ticket = old
			return nil
		}
		if s.Custody-s.PendingDeposits() < claim.Amount || s.Accounts[account].WithdrawalFunded != claim.Amount {
			return fmt.Errorf("funding not reconciled")
		}
		ticket = engine.LocalTicket{Withdrawal: id, Account: account, Recipient: account, Cumulative: claim.Cumulative, Epoch: claim.Epoch, ValidUntil: now + 600, AccountStateHash: claim.StateHash, Generation: generation.String(), ObservedChainTime: now}
		ticket.ID = crypto.Keccak256Hash([]byte(fmt.Sprintf("%s/%s/%s/%d", s.Local.Deployment, id, generation, ticket.ValidUntil))).Hex()
		authorization := contracts.Withdrawal{Account: common.HexToAddress(account), Recipient: common.HexToAddress(account), Cumulative: big.NewInt(ticket.Cumulative), StateVersion: ticket.Epoch, ValidUntil: ticket.ValidUntil, ID: common.HexToHash(ticket.ID), AccountStateHash: common.HexToHash(ticket.AccountStateHash)}
		digest, err := authorization.Digest(new(big.Int).SetUint64(ChainID), c.Env.Address("WithdrawalGateway"), generation)
		if err != nil {
			return err
		}
		remote, err := c.Env.Read(ctx, "WithdrawalGateway", "hashWithdrawal", 0, TicketABI(ticket))
		if err != nil {
			return err
		}
		if err = checkedDigest(remote, digest); err != nil {
			return err
		}
		signature, err := sign(WithdrawalSigner, digest)
		if err != nil {
			return err
		}
		ticket.Signature = hexutil.Encode(signature)
		ticket.Digest = digest.Hex()
		raw, _ := json.Marshal(ticket)
		_, err = w.Execute(ctx, engine.Command{Key: "local/ticket/" + strings.ToLower(ticket.ID), Kind: "local_ticket", Actor: account, At: max(c.Now(), w.Snapshot().At), Raw: raw})
		return err
	})
	return ticket, err
}
func (e *Environment) ClaimWithdrawal(ctx context.Context, wallet int, ticket engine.LocalTicket) error {
	sig, err := hexutil.Decode(ticket.Signature)
	if err != nil {
		return err
	}
	return e.Direct(ctx, wallet, "WithdrawalGateway", "claim", TicketABI(ticket), sig, []byte{})
}
