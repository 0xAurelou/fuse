package engine

import (
	"fmt"
	"math/big"
	"strings"
)

// Exposure counts debt once: earned cashouts + pending withdrawals + each active
// maximum payout less its physically custody-funded stake. Unsettled losses are
// never underwriting capital. Reserve backing never enters this computation.
func (s State) Exposure() (total int64, byAccount map[string]int64, active int) {
	byAccount = map[string]int64{}
	for id, a := range s.Accounts {
		byAccount[id] = a.Unfunded + a.EarnedUnfunded + a.WithdrawalUnfunded
	}
	for _, p := range s.Stages {
		if p.Status == "active" || p.Status == "pending" {
			byAccount[p.Terms.Account] += p.Terms.Payout - p.Funded
			active++
		}
	}
	for _, v := range byAccount {
		total += v
	}
	return
}
func (s State) Debt() (n int64) {
	for _, a := range s.Accounts {
		n += a.Unfunded + a.EarnedUnfunded + a.WithdrawalUnfunded
	}
	for _, p := range s.Stages {
		if p.Status == "active" || p.Status == "pending" {
			n += p.Debt
		}
	}
	return
}
func (s State) PendingDeposits() (n int64) {
	for _, d := range s.Deposits {
		if d.Status == "pending" {
			n += d.Amount
		}
	}
	return
}
func (s State) FundedLiability() (n int64) {
	for _, a := range s.Accounts {
		n += a.Available + a.EarnedFunded + a.WithdrawalFunded
	}
	for _, p := range s.Stages {
		if p.Status == "active" || p.Status == "pending" {
			n += p.Funded
		}
	}
	return
}
func (s State) Check() error {
	if err := s.checkRecoveryState(); err != nil {
		return err
	}
	if err := s.checkCapital(); err != nil {
		return err
	}
	if s.Custody < 0 || s.Custody > Limit || s.LP < 0 || s.LP > Limit || s.Reserve < 0 || s.Reserve > Limit || s.LossClearing < 0 || s.LossClearing > Limit {
		return fmt.Errorf("asset bound violated")
	}
	for _, a := range s.Accounts {
		for _, n := range []int64{a.Available, a.Unfunded, a.EarnedFunded, a.EarnedUnfunded, a.WithdrawalFunded, a.WithdrawalUnfunded, a.Withdrawn} {
			if n < 0 || n > Limit {
				return fmt.Errorf("customer balance bound violated")
			}
		}
	}
	for _, p := range s.Stages {
		if p.Funded < 0 || p.Debt < 0 || p.Funded+p.Debt != p.Terms.Stake {
			return fmt.Errorf("stake funding invariant violated")
		}
	}
	if s.Custody != s.PendingDeposits()+s.FundedLiability()+s.LossClearing {
		return fmt.Errorf("custody reconciliation mismatch")
	}
	exposure, _, _ := s.Exposure()
	if s.LPAvailable() < exposure {
		return fmt.Errorf("unfunded accepted LP obligation")
	}
	if s.Local != nil {
		if s.Local.LPFeeAccrued < 0 || s.Local.LPExitReserved < 0 || s.LPAvailable() < 0 {
			return fmt.Errorf("unfunded LP reserved liabilities")
		}
		outstanding := int64(0)
		for _, r := range s.Local.Redemptions {
			if r.Accrued < r.Paid || r.Paid < 0 {
				return fmt.Errorf("redemption liability invariant")
			}
			outstanding += r.Accrued - r.Paid
		}
		if outstanding > s.Reserve {
			return fmt.Errorf("unfunded redemption liability")
		}
		supply, ok := new(big.Int).SetString(s.Local.TokenSupply, 10)
		if !ok {
			return fmt.Errorf("invalid token supply")
		}
		totalTokens := new(big.Int)
		for _, v := range s.Local.TokenBalances {
			n, ok := new(big.Int).SetString(v, 10)
			if !ok || n.Sign() < 0 {
				return fmt.Errorf("invalid token balance")
			}
			totalTokens.Add(totalTokens, n)
		}
		if totalTokens.Cmp(supply) != 0 {
			return fmt.Errorf("token supply reconciliation mismatch")
		}
	}
	var total int64
	for _, v := range s.balances() {
		total += v
	}
	if total != 0 {
		return fmt.Errorf("unbalanced ledger: %d", total)
	}
	return nil
}
func (s State) capacity() error {
	if err := s.CheckRecovery(0); err != nil {
		return err
	}
	if s.Paused {
		return reject("trading paused")
	}
	total, by, n := s.Exposure()
	if total+s.Policy.LPBuffer > s.LPAvailable() || total > s.Policy.MaxExposure || n > s.Policy.MaxActive {
		return reject("LP capacity insufficient")
	}
	for _, v := range by {
		if v > s.Policy.MaxAccountExposure {
			return reject("account exposure limit")
		}
	}
	return s.capitalCapacity()
}

// Positive = debit; negative = credit. Reservations use a separate balanced memo
// asset and cannot be mistaken for physical USDC. All deltas are journaled.
func (s State) balances() map[string]int64 {
	b := map[string]int64{"asset/custody": s.Custody, "asset/lp": s.LP, "asset/reserve": s.Reserve, "equity/reserve": -s.Reserve, "equity/lp": -(s.LP - s.Debt()), "clearing/losses": -s.LossClearing}
	if s.Local != nil {
		if s.Local.LPFeeAccrued != 0 {
			b["liability/lp-reserve-fee"] = -s.Local.LPFeeAccrued
			b["equity/lp"] += s.Local.LPFeeAccrued
		}
		if s.Local.LPExitReserved != 0 {
			b["liability/lp-exits"] = -s.Local.LPExitReserved
			b["equity/lp"] += s.Local.LPExitReserved
		}
		for id, r := range s.Local.Redemptions {
			owed := r.Accrued - r.Paid
			b["redemption/"+id] = -owed
			b["equity/reserve"] += owed
		}
	}
	for id, a := range s.Accounts {
		prefix := "customer/" + id + "/"
		b[prefix+"available"] = -a.Available
		b[prefix+"unfunded"] = -a.Unfunded
		b[prefix+"earned_funded"] = -a.EarnedFunded
		b[prefix+"earned_unfunded"] = -a.EarnedUnfunded
		b[prefix+"withdrawal_funded"] = -a.WithdrawalFunded
		b[prefix+"withdrawal_unfunded"] = -a.WithdrawalUnfunded
	}
	for id, p := range s.Stages {
		if p.Status == "active" || p.Status == "pending" {
			b["stake/"+id+"/funded"] = -p.Funded
			b["stake/"+id+"/unfunded"] = -p.Debt
		}
	}
	for id, d := range s.Deposits {
		if d.Status == "pending" {
			b["deposit/"+id] = -d.Amount
		}
	}
	exposure, _, _ := s.Exposure()
	b["memo/reserved"] = exposure
	b["memo/capacity"] = -exposure
	return b
}
func postings(before, after State) []Posting {
	a, b := before.balances(), after.balances()
	for k := range a {
		if _, ok := b[k]; !ok {
			b[k] = 0
		}
	}
	out := []Posting{}
	for _, k := range keys(b) {
		if d := b[k] - a[k]; d != 0 {
			asset := "USDC"
			if strings.HasPrefix(k, "memo/") {
				asset = "USDC_RESERVATION"
			}
			out = append(out, Posting{k, asset, d})
		}
	}
	return out
}

// BalanceView keeps physical funding explicit; EconomicBalance is not a promise
// of an immediately executable onchain withdrawal authorization.
type BalanceView struct {
	FUSEBalance       string   `json:"fuse_balance,omitempty"`
	FUSEUnclaimed     string   `json:"fuse_unclaimed,omitempty"`
	RedemptionAccrued int64    `json:"redemption_accrued,omitempty"`
	RedemptionPaid    int64    `json:"redemption_paid,omitempty"`
	Account           *Account `json:"balances"`
	LockedFunded      int64    `json:"locked_funded"`
	LockedUnfunded    int64    `json:"locked_unfunded"`
	PendingDeposits   int64    `json:"pending_deposits"`
	EconomicBalance   int64    `json:"economic_balance"`
}

func (s State) Balance(id string) BalanceView {
	a := s.Accounts[id]
	if a == nil {
		a = &Account{}
	}
	out := BalanceView{Account: a}
	if s.Local != nil {
		out.FUSEBalance = s.Local.TokenBalances[id]
		if out.FUSEBalance == "" {
			out.FUSEBalance = "0"
		}
		unclaimed := new(big.Int)
		for _, epoch := range s.Local.Rewards {
			if !epoch.Published {
				continue
			}
			for _, allocation := range epoch.Allocations {
				if allocation.Account == id && !allocation.Claimed {
					n, ok := new(big.Int).SetString(allocation.Amount, 10)
					if ok {
						unclaimed.Add(unclaimed, n)
					}
				}
			}
		}
		out.FUSEUnclaimed = unclaimed.String()
		for _, r := range s.Local.Redemptions {
			if r.Account == id {
				out.RedemptionAccrued += r.Accrued - r.Paid
				out.RedemptionPaid += r.Paid
			}
		}
	}
	for _, p := range s.Stages {
		if p.Terms.Account == id && (p.Status == "active" || p.Status == "pending") {
			out.LockedFunded += p.Funded
			out.LockedUnfunded += p.Debt
		}
	}
	for _, d := range s.Deposits {
		if d.Account == id && d.Status == "pending" {
			out.PendingDeposits += d.Amount
		}
	}
	out.EconomicBalance = a.Available + a.Unfunded + a.EarnedFunded + a.EarnedUnfunded + a.WithdrawalFunded + a.WithdrawalUnfunded + out.LockedFunded + out.LockedUnfunded
	return out
}

// LPAvailable excludes capital already owed to LP claimants or the token reserve.
func (s State) LPAvailable() int64 {
	if s.Local == nil {
		return s.LP
	}
	return s.LP - s.Local.LPFeeAccrued - s.Local.LPExitReserved
}
