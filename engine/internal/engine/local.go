package engine

import (
	"encoding/json"
	"fmt"
	"math/big"
	"strings"
)

type LocalOperation struct {
	ID     string          `json:"id"`
	Kind   string          `json:"kind"`
	TxHash string          `json:"tx_hash"`
	RawTx  string          `json:"raw_tx"`
	Status string          `json:"status"`
	Data   json.RawMessage `json:"data"`
	Block  uint64          `json:"block,omitempty"`
}
type LocalTicket struct {
	ObservedChainTime uint64 `json:"observed_chain_time"`
	Withdrawal        string `json:"withdrawal"`
	Account           string `json:"account"`
	Recipient         string `json:"recipient"`
	Cumulative        int64  `json:"cumulative"`
	Epoch             uint64 `json:"epoch"`
	ValidUntil        uint64 `json:"valid_until"`
	ID                string `json:"id"`
	AccountStateHash  string `json:"account_state_hash"`
	Generation        string `json:"generation"`
	Signature         string `json:"signature"`
	Digest            string `json:"digest"`
}
type LocalAllocation struct {
	Index   uint64   `json:"index"`
	Account string   `json:"account"`
	Amount  string   `json:"amount"`
	Proof   []string `json:"proof"`
	Claimed bool     `json:"claimed"`
}
type LocalReward struct {
	RequestedBudget string            `json:"requested_budget,omitempty"`
	Manifest        json.RawMessage   `json:"manifest,omitempty"`
	Epoch           uint64            `json:"epoch"`
	From            uint64            `json:"from"`
	To              uint64            `json:"to"`
	Root            string            `json:"root"`
	ManifestHash    string            `json:"manifest_hash"`
	Budget          string            `json:"budget"`
	Allocations     []LocalAllocation `json:"allocations"`
	Published       bool              `json:"published"`
}
type LocalRedemption struct {
	Epoch   uint64 `json:"epoch"`
	Account string `json:"account"`
	Burned  string `json:"burned"`
	Accrued int64  `json:"accrued"`
	Paid    int64  `json:"paid"`
}
type LocalState struct {
	LPFeeAccrued   int64                       `json:"lp_fee_accrued,omitempty"`
	LPExitReserved int64                       `json:"lp_exit_reserved,omitempty"`
	TicketHistory  map[string]LocalTicket      `json:"ticket_history"`
	ClockOffsetMS  int64                       `json:"clock_offset_ms"`
	Deployment     string                      `json:"deployment"`
	Cursor         uint64                      `json:"cursor"`
	BlockHash      string                      `json:"block_hash"`
	Pending        string                      `json:"pending,omitempty"`
	Halted         string                      `json:"halted,omitempty"`
	Operations     map[string]*LocalOperation  `json:"operations"`
	Tickets        map[string]LocalTicket      `json:"tickets"`
	Rewards        map[string]*LocalReward     `json:"rewards"`
	Redemptions    map[string]*LocalRedemption `json:"redemptions"`
	TokenBalances  map[string]string           `json:"token_balances"`
	TokenSupply    string                      `json:"token_supply"`
	Generation     string                      `json:"generation"`
	ChainEvents    uint64                      `json:"chain_events"`
}
type LocalEffect struct {
	Module    string `json:"module"`
	Event     string `json:"event"`
	TxHash    string `json:"tx_hash"`
	ID        string `json:"id,omitempty"`
	Account   string `json:"account,omitempty"`
	Recipient string `json:"recipient,omitempty"`
	Amount    int64  `json:"amount,omitempty"`
	Epoch     uint64 `json:"epoch,omitempty"`
	Index     uint64 `json:"index,omitempty"`
	Root      string `json:"root,omitempty"`
	Digest    string `json:"digest,omitempty"`
	Value     string `json:"value,omitempty"`
}
type LocalBlock struct {
	Evidence    json.RawMessage `json:"evidence,omitempty"`
	Number      uint64          `json:"number"`
	Hash        string          `json:"hash"`
	Parent      string          `json:"parent"`
	Effects     []LocalEffect   `json:"effects"`
	Transaction string          `json:"transaction,omitempty"`
	Success     *bool           `json:"success,omitempty"`
}
type LocalSettlement struct {
	LiquidityWindow bool            `json:"liquidity_window,omitempty"`
	Epoch           Epoch           `json:"epoch"`
	Deposits        []string        `json:"deposits"`
	Report          json.RawMessage `json:"report"`
	Digest          string          `json:"digest"`
}

func (s *State) local(c Command) (any, error) {
	switch c.Kind {
	case "local_bind":
		if s.Local != nil {
			return nil, reject("deployment already bound")
		}
		var binding struct {
			Deployment, BlockHash string
			Cursor                uint64
		}
		if err := json.Unmarshal(c.Raw, &binding); err != nil {
			return nil, err
		}
		if binding.Deployment == "" || binding.BlockHash == "" {
			return nil, reject("missing deployment binding")
		}
		s.Local = &LocalState{Deployment: binding.Deployment, Cursor: binding.Cursor, BlockHash: binding.BlockHash, Operations: map[string]*LocalOperation{}, Tickets: map[string]LocalTicket{}, TicketHistory: map[string]LocalTicket{}, Rewards: map[string]*LocalReward{}, Redemptions: map[string]*LocalRedemption{}, TokenBalances: map[string]string{}, TokenSupply: "0", Generation: "1"}
		return s.Local, nil
	case "local_clock":
		if c.Amount < s.Local.ClockOffsetMS || c.Amount-s.Local.ClockOffsetMS > 3_600_000 {
			return nil, reject("invalid local clock advance")
		}
		s.Local.ClockOffsetMS = c.Amount
		return nil, nil
	case "local_halt":
		s.Paused = true
		s.Local.Halted = c.ID
		return nil, nil
	case "local_prepare":
		if s.Local.Halted != "" || s.Local.Pending != "" {
			return nil, reject("local coordinator halted or busy")
		}
		var op LocalOperation
		if err := json.Unmarshal(c.Raw, &op); err != nil {
			return nil, err
		}
		if op.ID == "" || op.TxHash == "" || op.RawTx == "" || s.Local.Operations[op.ID] != nil {
			return nil, reject("invalid or duplicate transaction operation")
		}
		op.Status = "prepared"
		s.Local.Operations[op.ID] = &op
		s.Local.Pending = op.ID
		return op, nil
	case "local_ticket":
		var ticket LocalTicket
		if err := json.Unmarshal(c.Raw, &ticket); err != nil {
			return nil, err
		}
		w := s.Withdrawals[ticket.Withdrawal]
		if w == nil || w.Status != "funded" || ticket.Account != w.Account || ticket.Recipient != w.Account || ticket.Cumulative != w.Cumulative || ticket.Epoch != w.Epoch || ticket.Generation != s.Local.Generation || ticket.ID == "" || ticket.Signature == "" {
			return nil, reject("ticket does not match funded locked entitlement")
		}
		for _, old := range s.Local.TicketHistory {
			if old.ID == ticket.ID {
				return nil, reject("authorization ID already issued")
			}
		}
		if old, exists := s.Local.Tickets[ticket.Withdrawal]; exists && old.Generation == ticket.Generation && old.ValidUntil >= ticket.ObservedChainTime {
			return nil, reject("previous authorization may still execute")
		}
		s.Local.Tickets[ticket.Withdrawal] = ticket
		s.Local.TicketHistory[ticket.ID] = ticket
		return ticket, nil
	case "local_block":
		var block LocalBlock
		if err := json.Unmarshal(c.Raw, &block); err != nil {
			return nil, err
		}
		if block.Number != s.Local.Cursor+1 || !strings.EqualFold(block.Parent, s.Local.BlockHash) || block.Hash == "" {
			return nil, reject("noncanonical local block")
		}
		for _, effect := range block.Effects {
			if err := s.localEffect(effect); err != nil {
				return nil, fmt.Errorf("%s.%s: %w", effect.Module, effect.Event, err)
			}
			s.Local.ChainEvents++
		}
		if block.Transaction != "" {
			op := s.Local.Operations[s.Local.Pending]
			if op == nil || !strings.EqualFold(op.TxHash, block.Transaction) || block.Success == nil {
				return nil, reject("unexpected local receipt")
			}
			op.Block = block.Number
			op.Status = "confirmed"
			if !*block.Success {
				op.Status = "reverted"
			}
			s.Local.Pending = ""
		}
		s.Local.Cursor = block.Number
		s.Local.BlockHash = block.Hash
		return block, nil
	default:
		return nil, reject("unknown local command")
	}
}
func (s *State) localEffect(e LocalEffect) error {
	switch e.Module + "." + e.Event {
	case "LPVault.ReserveFeeAccrued":
		total, err := checkedAmount(e.Value)
		if err != nil || e.Amount < 0 || total < s.Local.LPFeeAccrued || total-s.Local.LPFeeAccrued != e.Amount {
			return reject("invalid LP fee accrual")
		}
		s.Local.LPFeeAccrued = total
		// Charge the accrual event even when the same block also funds the fee.
		s.recordRisk(-e.Amount, s.At)
		return nil
	case "LPVault.LPExitReserved":
		if e.Amount < 0 || e.Amount > s.LPAvailable() {
			return reject("invalid LP exit reservation")
		}
		s.Local.LPExitReserved += e.Amount
		return nil
	case "LPVault.LPExitPaid":
		if e.Amount < 0 || e.Amount > s.Local.LPExitReserved {
			return reject("invalid LP exit claim")
		}
		s.Local.LPExitReserved -= e.Amount
		s.LP -= e.Amount
		return nil
	case "LPVault.LPDeposited":
		_, err := s.execute(Command{Kind: "lp_fund", Amount: e.Amount})
		return err
	case "CustomerCustodyVault.Deposited":
		_, err := s.execute(Command{Kind: "deposit", Actor: e.Account, ID: e.ID, Amount: e.Amount})
		return err
	case "CustomerCustodyVault.DepositCredited":
		_, err := s.execute(Command{Kind: "ack_deposit", ID: e.ID})
		return err
	case "CustomerCustodyVault.DepositRefunded":
		_, err := s.execute(Command{Kind: "refund_deposit", ID: e.ID})
		return err
	case "SettlementController.CheckpointFinalized":
		op := s.localOp(e.TxHash, "settlement")
		if op == nil {
			return reject("checkpoint has no durable settlement manifest")
		}
		var plan LocalSettlement
		if err := json.Unmarshal(op.Data, &plan); err != nil {
			return err
		}
		p := plan.Epoch
		prior := ""
		from := uint64(1)
		if len(s.Epochs) > 0 {
			last := s.Epochs[len(s.Epochs)-1]
			prior = last.Root
			from = last.To + 1
		}
		if p.Number != uint64(len(s.Epochs)+1) || p.Number != e.Epoch || p.PriorRoot != prior || p.From != from || p.To < p.From || !sameHash(p.Root, e.Root) || !strings.EqualFold(plan.Digest, e.Digest) || p.NetTraderPnL != e.Amount || p.NetTraderPnL != s.Debt()-s.LossClearing {
			return reject("checkpoint commitment or PnL mismatch")
		}
		if err := s.fundSettlement(); err != nil {
			return err
		}
		exposure, _, _ := s.Exposure()
		if p.Liability != s.FundedLiability() || p.Exposure != exposure || s.LPAvailable() < p.RequiredLP {
			return reject("checkpoint liability/capital mismatch")
		}
		p.Status = "onchain-confirmed"
		s.Epochs = append(s.Epochs, p)
		for _, w := range s.Withdrawals {
			if w.Status == "pending" {
				w.Status = "funded"
				w.Epoch = p.Number
				w.StateHash = Hash(s.Balance(w.Account))
			}
		}
		return nil
	case "WithdrawalGateway.Withdrawn":
		var ticket *LocalTicket
		for _, t := range s.Local.TicketHistory {
			if strings.EqualFold(t.ID, e.ID) {
				copy := t
				ticket = &copy
				break
			}
		}
		if ticket == nil || ticket.Account != e.Account || ticket.Recipient != e.Recipient {
			return reject("unknown or redirected withdrawal")
		}
		w := s.Withdrawals[ticket.Withdrawal]
		if w == nil || w.Amount != e.Amount {
			return reject("withdrawal amount mismatch")
		}
		_, err := s.execute(Command{Kind: "paper_pay", ID: w.ID})
		return err
	case "AccessController.SignerRotated":
		s.Local.Generation = e.Value
		return nil
	case "AccessController.TradingPauseChanged":
		s.Paused = e.Value == "true"
		return nil
	case "FUSEToken.Transfer":
		amount, ok := new(big.Int).SetString(e.Value, 10)
		if !ok || amount.Sign() < 0 {
			return reject("invalid FUSE transfer")
		}
		zero := "0x0000000000000000000000000000000000000000"
		if e.Account != zero {
			if err := tokenAdd(s.Local.TokenBalances, e.Account, new(big.Int).Neg(amount)); err != nil {
				return err
			}
		} else {
			if err := tokenSupply(s.Local, amount); err != nil {
				return err
			}
		}
		if e.Recipient != zero {
			return tokenAdd(s.Local.TokenBalances, e.Recipient, amount)
		}
		return tokenSupply(s.Local, new(big.Int).Neg(amount))
	case "RewardDistributor.EpochPublished":
		op := s.localOp(e.TxHash, "rewards")
		if op == nil {
			return reject("reward publication has no durable manifest")
		}
		var reward LocalReward
		if err := json.Unmarshal(op.Data, &reward); err != nil {
			return err
		}
		if reward.Epoch != e.Epoch || !strings.EqualFold(reward.Root, e.Root) || reward.Budget != e.Value || (len(reward.Manifest) > 0 && !strings.EqualFold(reward.ManifestHash, e.Digest)) {
			return reject("reward commitment mismatch")
		}
		if len(s.Local.Rewards)+1 != int(reward.Epoch) {
			return reject("reward epochs out of order")
		}
		reward.Published = true
		s.Local.Rewards[fmt.Sprint(reward.Epoch)] = &reward
		return nil
	case "RewardDistributor.RewardClaimed":
		reward := s.Local.Rewards[fmt.Sprint(e.Epoch)]
		if reward == nil {
			return reject("unknown reward epoch")
		}
		for i := range reward.Allocations {
			a := &reward.Allocations[i]
			if a.Index == e.Index {
				if a.Account != e.Account || a.Amount != e.Value || a.Claimed {
					return reject("reward claim mismatch")
				}
				a.Claimed = true
				return nil
			}
		}
		return reject("unknown allocation")
	case "LPVault.ReserveFunded":
		if e.Amount <= 0 || e.Amount > s.LP {
			return reject("invalid reserve funding")
		}
		s.LP -= e.Amount
		if s.Local.LPFeeAccrued != 0 {
			if e.Amount > s.Local.LPFeeAccrued {
				return reject("reserve funding exceeds accrued LP fee")
			}
			s.Local.LPFeeAccrued -= e.Amount
		}
		s.Reserve += e.Amount
		n, ok := new(big.Int).SetString(e.Value, 10)
		if !ok || !n.IsInt64() {
			return reject("invalid consumed profit mark")
		}
		s.ConsumedProfit = n.Int64()
		return nil
	case "RedemptionReserve.RedemptionRequested":
		key := fmt.Sprintf("%d/%s", e.Epoch, e.Account)
		r := s.Local.Redemptions[key]
		if r == nil {
			r = &LocalRedemption{Epoch: e.Epoch, Account: e.Account, Burned: "0"}
			s.Local.Redemptions[key] = r
		}
		burn, ok := new(big.Int).SetString(e.Value, 10)
		if !ok || burn.Sign() <= 0 || e.Amount < 0 {
			return reject("invalid redemption request")
		}
		old, _ := new(big.Int).SetString(r.Burned, 10)
		r.Burned = old.Add(old, burn).String()
		r.Accrued += e.Amount
		return nil
	case "RedemptionReserve.RedemptionClaimed":
		key := fmt.Sprintf("%d/%s", e.Epoch, e.Account)
		r := s.Local.Redemptions[key]
		if r == nil || e.Amount <= 0 || r.Accrued-r.Paid != e.Amount || s.Reserve < e.Amount {
			return reject("redemption payment mismatch")
		}
		r.Paid += e.Amount
		s.Reserve -= e.Amount
		return nil
	}
	return nil // Non-financial configuration and duplicate transfer-notification events.
}
func (s *State) localOp(hash, kind string) *LocalOperation {
	for _, op := range s.Local.Operations {
		if strings.EqualFold(op.TxHash, hash) && op.Kind == kind {
			return op
		}
	}
	return nil
}
func tokenAdd(balances map[string]string, account string, delta *big.Int) error {
	current := new(big.Int)
	if v := balances[account]; v != "" {
		if _, ok := current.SetString(v, 10); !ok {
			return reject("invalid token balance")
		}
	}
	current.Add(current, delta)
	if current.Sign() < 0 || current.BitLen() > 256 {
		return reject("token balance out of range")
	}
	balances[account] = current.String()
	return nil
}
func tokenSupply(local *LocalState, delta *big.Int) error {
	n, ok := new(big.Int).SetString(local.TokenSupply, 10)
	if !ok {
		return reject("invalid token supply")
	}
	n.Add(n, delta)
	if n.Sign() < 0 || n.BitLen() > 256 {
		return reject("token supply out of range")
	}
	local.TokenSupply = n.String()
	return nil
}

// PlanLocalSettlement commits the exact acknowledged deposit batch, journal range
// and post-funding financial state. No physical funding occurs until chain logs.
func PlanLocalSettlement(s State) (LocalSettlement, error) {
	if s.Local == nil || s.Local.Pending != "" {
		return LocalSettlement{}, reject("local coordinator unavailable")
	}
	preview := clone(s)
	ids := []string{}
	for _, id := range keys(preview.Deposits) {
		if preview.Deposits[id].Status == "pending" {
			if _, err := preview.execute(Command{Kind: "ack_deposit", ID: id}); err != nil {
				return LocalSettlement{}, err
			}
			ids = append(ids, id)
		}
	}
	net := preview.Debt() - preview.LossClearing
	if err := preview.fundSettlement(); err != nil {
		return LocalSettlement{}, err
	}
	exposure, _, _ := preview.Exposure()
	from := uint64(1)
	prior := ""
	if len(s.Epochs) > 0 {
		last := s.Epochs[len(s.Epochs)-1]
		from = last.To + 1
		prior = last.Root
	}
	if s.Sequence < from {
		return LocalSettlement{}, reject("no journal range to settle")
	}
	p := Epoch{Number: uint64(len(s.Epochs) + 1), From: from, To: s.Sequence, PriorRoot: prior, Root: preview.Digest(), JournalHash: s.JournalHash, OracleHash: s.OracleCommitment(), NetTraderPnL: net, Liability: preview.FundedLiability(), Exposure: exposure, RequiredLP: exposure + s.Policy.LPBuffer, Status: "onchain-confirmed"}
	if preview.LPAvailable() < p.RequiredLP {
		return LocalSettlement{}, reject("post-settlement LP buffer insufficient")
	}
	return LocalSettlement{Epoch: p, Deposits: ids}, nil
}

func sameHash(a, b string) bool {
	return strings.EqualFold(strings.TrimPrefix(a, "0x"), strings.TrimPrefix(b, "0x"))
}

// checkedAmount decodes bounded financial event fields without trusting JSON strings.
func checkedAmount(value string) (int64, error) {
	n, ok := new(big.Int).SetString(value, 10)
	if !ok || !n.IsInt64() || n.Sign() < 0 || n.Int64() > Limit {
		return 0, reject("invalid amount")
	}
	return n.Int64(), nil
}
