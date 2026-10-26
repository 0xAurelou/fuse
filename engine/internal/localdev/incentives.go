package localdev

import (
	"context"
	"encoding/json"
	"fmt"
	"math/big"
	"strings"

	"fuse/engine/internal/contracts"
	"fuse/engine/internal/engine"
	"fuse/engine/internal/rewards"
	"github.com/ethereum/go-ethereum/common"
)

func (c *Controller) PublishRewards(ctx context.Context, id string, budget *big.Int) (engine.LocalOperation, error) {
	var op engine.LocalOperation
	err := c.Q.Exclusive(func(w *engine.Writer) error {
		if err := c.sync(ctx, w); err != nil {
			return err
		}
		s := w.Snapshot()
		if old := s.Local.Operations[id]; old != nil {
			if old.Kind != "rewards" {
				return fmt.Errorf("operation ID reused")
			}
			var oldReward engine.LocalReward
			if err := json.Unmarshal(old.Data, &oldReward); err != nil {
				return err
			}
			requested := oldReward.RequestedBudget
			if requested == "" {
				requested = oldReward.Budget
			}
			if budget == nil || requested != budget.String() {
				return fmt.Errorf("reward request changed")
			}
			op = *old
			return nil
		}
		if _, ok := c.Env.ABIs["RewardDistributor"].Methods["emissionEnd"]; !ok {
			return fmt.Errorf("v2 mining publication requires a new tokenomics deployment")
		}
		if budget == nil || budget.Sign() <= 0 || budget.BitLen() > 256 {
			return fmt.Errorf("positive FUSE budget required")
		}
		cap, err := c.Env.Uint(ctx, "RewardDistributor", "nextEpochCap", 0)
		if err != nil {
			return err
		}
		allocated, err := c.Env.Uint(ctx, "RewardDistributor", "totalAllocated", 0)
		if err != nil {
			return err
		}
		limit, err := c.Env.Uint(ctx, "FUSEToken", "EMISSION_ALLOCATION", 0)
		if err != nil {
			return err
		}
		requestedBudget := budget.String()
		budget = new(big.Int).Set(budget)
		remaining := new(big.Int).Sub(limit, allocated)
		if budget.Cmp(cap) > 0 {
			budget.Set(cap)
		}
		if budget.Cmp(remaining) > 0 {
			budget.Set(remaining)
		}
		if budget.Sign() <= 0 {
			return fmt.Errorf("no current emission capacity")
		}
		epoch := uint64(len(s.Local.Rewards) + 1)
		from := uint64(1)
		if epoch > 1 {
			from = s.Local.Rewards[fmt.Sprint(epoch-1)].To + 1
		}
		policy := rewards.Policy{Version: "local-mining-v2", ExposureRule: "linear-stake-time-v2", ActivityRate: "100000000000000000000", SurvivedWeightBPS: 10000, FailedWeightBPS: 2000, MaxStakeUSDC: s.Policy.MaxStake}
		manifest, err := rewards.BuildForCheckpoint(w.Events(), s, from, epoch, budget, new(big.Int).SetUint64(ChainID), c.Env.Address("RewardDistributor"), policy)
		if err != nil {
			return err
		}
		manifestRaw, _ := json.Marshal(manifest)
		record := engine.LocalReward{RequestedBudget: requestedBudget, Manifest: manifestRaw, Epoch: epoch, From: from, To: manifest.To, Root: manifest.Root.Hex(), ManifestHash: "0x" + engine.Hash(manifest), Budget: manifest.Budget, Allocations: []engine.LocalAllocation{}}
		for _, a := range manifest.Allocations {
			proof := []string{}
			for _, h := range a.Proof {
				proof = append(proof, h.Hex())
			}
			record.Allocations = append(record.Allocations, engine.LocalAllocation{Index: a.Index, Account: strings.ToLower(a.Account.Hex()), Amount: a.Amount, Proof: proof})
		}
		op, err = c.submit(ctx, w, id, "rewards", "RewardDistributor", "publishEpoch", record, epoch, manifest.Root, mustBig(manifest.Budget), common.HexToHash(record.ManifestHash))
		return err
	})
	return op, err
}

type reserveTuple struct {
	Epoch                                               uint64
	CheckpointRoot                                      [32]byte
	AmountUSDC, MinLPCapitalUSDC, RealizedProfitHWMUSDC *big.Int
	AuthorizationId                                     [32]byte
	Deadline                                            *big.Int
}

func (c *Controller) FundReserve(ctx context.Context, id string, amount int64) (engine.LocalOperation, error) {
	var op engine.LocalOperation
	err := c.Q.Exclusive(func(w *engine.Writer) error {
		if err := c.sync(ctx, w); err != nil {
			return err
		}
		s := w.Snapshot()
		if old := s.Local.Operations[id]; old != nil {
			if old.Kind != "reserve" {
				return fmt.Errorf("operation ID reused")
			}
			var oldAmount int64
			_ = json.Unmarshal(old.Data, &oldAmount)
			if oldAmount != amount {
				return fmt.Errorf("reserve request changed")
			}
			op = *old
			return nil
		}
		if _, ok := c.Env.ABIs["LPVault"].Methods["reserveAllowance"]; !ok {
			return fmt.Errorf("v2 reserve funding requires a new tokenomics deployment")
		}
		if len(s.Epochs) == 0 || amount <= 0 {
			return fmt.Errorf("funded checkpoint and positive reserve contribution required")
		}
		exposure, _, _ := s.Exposure()
		required := exposure + s.Policy.LPBuffer
		lastCapital, err := c.Env.Uint(ctx, "LPVault", "requiredCapitalUSDC", 0)
		if err != nil {
			return err
		}
		if !lastCapital.IsInt64() {
			return fmt.Errorf("capital out of range")
		}
		required = max(required, lastCapital.Int64())
		allocation, err := c.Env.Uint(ctx, "LPVault", "reserveAllocationBps", 0)
		if err != nil {
			return err
		}
		available, _, _, err := rewards.ReserveContributionV2(max(s.LPProfit, 0), s.ProfitHWM, s.ConsumedProfit, s.LP, required, allocation.Int64())
		if err != nil {
			return err
		}
		if _, ok := c.Env.ABIs["LPVault"].Methods["shareEconomics"]; ok {
			mode, err := c.Env.Read(ctx, "LPVault", "shareEconomics", 0)
			if err != nil {
				return err
			}
			if mode[0].(bool) {
				// The external-LP waterfall crystallizes fees at settlement. Gross
				// profit and consumed-profit telemetry cannot reconstruct this liability.
				allowance, err := c.Env.Read(ctx, "LPVault", "reserveAllowance", 0, big.NewInt(required))
				if err != nil {
					return err
				}
				accrued := allowance[0].(*big.Int)
				if !accrued.IsInt64() || accrued.Sign() < 0 || accrued.Int64() > s.Local.LPFeeAccrued {
					return fmt.Errorf("accrued LP reserve fee does not reconcile")
				}
				available = accrued.Int64()
			}
		}
		if amount > available {
			return fmt.Errorf("reserve contribution exceeds realized profit or post-transfer solvency")
		}
		epoch := s.Epochs[len(s.Epochs)-1]
		now, err := c.Env.RPC.Timestamp(ctx)
		if err != nil {
			return err
		}
		generation, err := c.Env.Uint(ctx, "AccessController", "signatureVersion", 0)
		if err != nil {
			return err
		}
		authorization := contracts.ReserveAuthorization{Epoch: epoch.Number, Root: common.HexToHash(epoch.Root), Amount: big.NewInt(amount), MinLP: big.NewInt(required), ProfitHWM: big.NewInt(s.ProfitHWM), ID: common.HexToHash(engine.Hash(id)), Deadline: new(big.Int).SetUint64(now + 3600)}
		digest, err := authorization.Digest(new(big.Int).SetUint64(ChainID), c.Env.Address("LPVault"), generation)
		if err != nil {
			return err
		}
		tuple := reserveTuple{authorization.Epoch, authorization.Root, authorization.Amount, authorization.MinLP, authorization.ProfitHWM, authorization.ID, authorization.Deadline}
		remote, err := c.Env.Read(ctx, "LPVault", "hashReserveAuthorization", 0, tuple)
		if err != nil {
			return err
		}
		if err = checkedDigest(remote, digest); err != nil {
			return err
		}
		ss, err := sign(SettlementSigner, digest)
		if err != nil {
			return err
		}
		rs, err := sign(RiskSigner, digest)
		if err != nil {
			return err
		}
		op, err = c.submit(ctx, w, id, "reserve", "LPVault", "fundFUSEReserve", amount, tuple, ss, rs)
		return err
	})
	return op, err
}
func (c *Controller) OpenRedemption(ctx context.Context, id string, duration uint64, penalty uint16) (engine.LocalOperation, error) {
	var op engine.LocalOperation
	err := c.Q.Exclusive(func(w *engine.Writer) error {
		if err := c.sync(ctx, w); err != nil {
			return err
		}
		if old := w.Snapshot().Local.Operations[id]; old != nil {
			if old.Kind != "redemption" {
				return fmt.Errorf("operation ID reused")
			}
			var request []uint64
			_ = json.Unmarshal(old.Data, &request)
			if len(request) != 2 || request[0] != duration || request[1] != uint64(penalty) {
				return fmt.Errorf("redemption request changed")
			}
			op = *old
			return nil
		}
		if duration == 0 || duration > 3600 || penalty > 10000 {
			return fmt.Errorf("invalid local redemption window")
		}
		now, err := c.Env.RPC.Timestamp(ctx)
		if err != nil {
			return err
		}
		op, err = c.submit(ctx, w, id, "redemption", "RedemptionReserve", "openRedemptionEpoch", []uint64{duration, uint64(penalty)}, now+2, now+2+duration, penalty)
		return err
	})
	return op, err
}

func mustBig(s string) *big.Int {
	n, ok := new(big.Int).SetString(s, 10)
	if !ok {
		panic("invalid internal integer")
	}
	return n
}
