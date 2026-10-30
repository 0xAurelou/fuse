package localdev

import (
	"context"
	"fmt"
	"math/big"
	"sort"
	"strings"

	"github.com/ethereum/go-ethereum/common"
	"github.com/ethereum/go-ethereum/common/hexutil"
)

// TokenomicsView reports confirmed contract observations and exact rational
// backing values. A secondary-market bid is deliberately absent without a venue.
func (c *Controller) TokenomicsView(ctx context.Context) (map[string]any, error) {
	s := c.Q.Snapshot()
	if s.Local == nil {
		return nil, fmt.Errorf("local deployment required")
	}
	block := s.Local.Cursor
	read := func(module, method string, args ...any) (*big.Int, error) {
		return c.Env.Uint(ctx, module, method, block, args...)
	}
	supply, err := read("FUSEToken", "totalSupply")
	if err != nil {
		return nil, err
	}
	escrow := map[string]string{}
	escrowTotal := new(big.Int)
	excluded := map[string]bool{}
	escrowMethods := []string{"emissionEscrow", "treasuryEscrow"}
	if _, ok := c.Env.ABIs["FUSEToken"].Methods["lpEmissionEscrow"]; ok {
		escrowMethods = append(escrowMethods, "lpEmissionEscrow")
	}
	for _, method := range escrowMethods {
		out, e := c.Env.Read(ctx, "FUSEToken", method, block)
		if e != nil {
			return nil, e
		}
		address := out[0].(common.Address)
		balance, e := read("FUSEToken", "balanceOf", address)
		if e != nil {
			return nil, e
		}
		escrow[method] = balance.String()
		escrowTotal.Add(escrowTotal, balance)
		excluded[strings.ToLower(address.Hex())] = true
	}
	outstanding := int64(0)
	for _, r := range s.Local.Redemptions {
		outstanding += r.Accrued - r.Paid
	}
	free := s.Reserve - outstanding
	if free < 0 {
		return nil, fmt.Errorf("reserve claims exceed assets")
	}
	flags := map[string]bool{}
	for _, item := range []struct{ module, method string }{{"FUSEToken", "transfersEnabled"}, {"RewardDistributor", "emissionsActive"}, {"RedemptionReserve", "redemptionsActive"}} {
		out, e := c.Env.Read(ctx, item.module, item.method, block)
		if e != nil {
			return nil, e
		}
		flags[item.method] = out[0].(bool)
	}
	// Only new, capability-declaring deployments preserve redemption admission
	// through a betting pause. Do not relabel legacy immutable contracts.
	if _, supported := c.Env.ABIs["RedemptionReserve"].Methods["supportsPausedRedemptions"]; supported {
		out, e := c.Env.Read(ctx, "RedemptionReserve", "supportsPausedRedemptions", block)
		if e != nil {
			return nil, e
		}
		flags["redemptionsDuringTradingPause"] = out[0].(bool)
	}
	emission := map[string]string{}
	for _, method := range []string{"totalAllocated", "totalClaimed", "nextEpochCap", "emissionStart", "epochDuration", "decayBps"} {
		v, e := read("RewardDistributor", method)
		if e != nil {
			return nil, e
		}
		emission[method] = v.String()
	}
	if _, ok := c.Env.ABIs["RewardDistributor"].Methods["emissionEnd"]; ok {
		v, e := read("RewardDistributor", "emissionEnd")
		if e != nil {
			return nil, e
		}
		emission["emissionEnd"] = v.String()
	}
	circulating := new(big.Int).Sub(new(big.Int).Set(supply), escrowTotal)
	unlocked := new(big.Int)
	if flags["transfersEnabled"] {
		unlocked.Set(circulating)
	}
	type holder struct {
		Account string `json:"account"`
		Balance string `json:"balance"`
	}
	holders := []holder{}
	for account, value := range s.Local.TokenBalances {
		if excluded[account] {
			continue
		}
		n, ok := new(big.Int).SetString(value, 10)
		if ok && n.Sign() > 0 {
			holders = append(holders, holder{account, value})
		}
	}
	sort.Slice(holders, func(i, j int) bool {
		a, _ := new(big.Int).SetString(holders[i].Balance, 10)
		b, _ := new(big.Int).SetString(holders[j].Balance, 10)
		if a.Cmp(b) == 0 {
			return holders[i].Account < holders[j].Account
		}
		return a.Cmp(b) > 0
	})
	if len(holders) > 10 {
		holders = holders[:10]
	}
	exposure, _, active := s.Exposure()
	required := exposure + s.Policy.LPBuffer
	allowance := any(nil)
	if _, ok := c.Env.ABIs["LPVault"].Methods["reserveAllowance"]; ok {
		out, e := c.Env.Read(ctx, "LPVault", "reserveAllowance", block, big.NewInt(required))
		if e != nil {
			return nil, e
		}
		allowance = map[string]string{"amount_usdc_units": out[0].(*big.Int).String(), "effective_bps": out[1].(*big.Int).String()}
	}
	latest, err := read("RedemptionReserve", "latestEpoch")
	if err != nil {
		return nil, err
	}
	epoch := any(nil)
	retained := new(big.Int)
	epochRecords := map[uint64][]any{}
	for _, record := range s.Local.Redemptions {
		if _, ok := epochRecords[record.Epoch]; !ok {
			values, e := c.Env.Read(ctx, "RedemptionReserve", "epochs", block, record.Epoch)
			if e != nil {
				return nil, e
			}
			epochRecords[record.Epoch] = values
		}
		values := epochRecords[record.Epoch]
		tokens, _ := new(big.Int).SetString(record.Burned, 10)
		gross := new(big.Int).Mul(tokens, values[5].(*big.Int))
		gross.Quo(gross, values[4].(*big.Int))
		retained.Add(retained, new(big.Int).Sub(gross, big.NewInt(record.Accrued)))
	}
	netQuote := any(nil)
	if latest.Sign() > 0 {
		values, e := c.Env.Read(ctx, "RedemptionReserve", "epochs", block, latest.Uint64())
		if e != nil {
			return nil, e
		}
		var header struct {
			Time hexutil.Uint64 `json:"timestamp"`
		}
		if e = c.Env.RPC.ReadRPC(ctx, "eth_getBlockByNumber", []any{hexutil.EncodeUint64(block), false}, &header); e != nil {
			return nil, e
		}
		start, end := values[1].(uint64), values[2].(uint64)
		ready := values[4].(*big.Int).Sign() > 0
		pausePermits := !s.Paused || flags["redemptionsDuringTradingPause"]
		inWindow := uint64(header.Time) >= start && uint64(header.Time) < end
		executable := ready && inWindow && flags["redemptionsActive"] && flags["transfersEnabled"] && pausePermits
		if executable {
			numerator := new(big.Int).Mul(values[5].(*big.Int), big.NewInt(int64(10000-values[3].(uint16))))
			denominator := new(big.Int).Mul(values[4].(*big.Int), big.NewInt(10000))
			netQuote = map[string]string{"usdc_units": numerator.String(), "fuse_units": denominator.String()}
		}
		canStart := !ready && inWindow && flags["redemptionsActive"] && flags["transfersEnabled"] && pausePermits && free > 0 && supply.Sign() > 0
		epoch = map[string]any{"executable": executable, "start_required": canStart, "id": latest.String(), "start": values[1], "end": values[2], "penalty_bps": values[3], "supply_snapshot": values[4].(*big.Int).String(), "reserve_snapshot_usdc_units": values[5].(*big.Int).String(), "snapshot_available": values[4].(*big.Int).Sign() > 0}
	}
	lpParticipation, err := c.lpView(ctx, block)
	if err != nil {
		return nil, err
	}
	_, hasReserve := c.Env.ABIs["LPVault"].Methods["reserveAllowance"]
	_, hasHorizon := c.Env.ABIs["RewardDistributor"].Methods["emissionEnd"]
	return map[string]any{"lp_participation": lpParticipation, "tokenomics_controls_v2": hasReserve && hasHorizon, "usdc_decimals": 6, "fuse_decimals": 18, "current_executable_net_backing_ratio": netQuote, "sequence": s.Sequence, "confirmed_block": block, "confirmed_block_hash": s.Local.BlockHash, "execution_chain_id": ChainID, "supply_fuse_units": supply.String(), "circulating_fuse_units": circulating.String(), "unlocked_fuse_units": unlocked.String(), "locked_escrows": escrow, "activation": flags, "emissions": emission, "lp_equity_usdc_units": s.LPAvailable(), "lp_total_cash_usdc_units": s.LP, "lp_reserved_exit_usdc_units": s.Local.LPExitReserved, "lp_accrued_reserve_fee_usdc_units": s.Local.LPFeeAccrued, "open_exposure_usdc_units": exposure, "active_stages": active, "required_capital_usdc_units": required, "realized_lp_profit_usdc_units": s.LPProfit, "profit_hwm_usdc_units": s.ProfitHWM, "consumed_profit_usdc_units": s.ConsumedProfit, "reserve_transfer_allowance": allowance, "reserve_usdc_units": s.Reserve, "unpaid_redemption_claims_usdc_units": outstanding, "free_reserve_usdc_units": free, "gross_backing_ratio": map[string]string{"usdc_units": fmt.Sprint(free), "fuse_units": supply.String()}, "redemption_epoch": epoch, "penalty_retained_usdc_units": retained.String(), "top_circulating_holders": holders, "secondary_market_bid": nil, "policy_notice": "Local research policies; no guaranteed token price, yield, market bid or production activation"}, nil
}
