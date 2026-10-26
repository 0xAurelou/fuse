package localdev

import (
	"context"
	"encoding/json"
	"fmt"
	"math/big"

	"fuse/engine/internal/contracts"
	"fuse/engine/internal/engine"
	"github.com/ethereum/go-ethereum/common"
)

// OpenLPLiquidityWindow serializes acceptance, reconciliation, signatures and the
// atomic settle-and-pause transaction under the same writer lock as trading.
func (c *Controller) OpenLPLiquidityWindow(ctx context.Context, id string) (engine.LocalOperation, error) {
	var op engine.LocalOperation
	err := c.Q.Exclusive(func(w *engine.Writer) error { var err error; op, err = c.settleMode(ctx, w, id, true); return err })
	return op, err
}

type capacityTuple struct {
	Epoch                               uint64
	CheckpointRoot                      [32]byte
	EligibleDemandUSDC, Nonce, Deadline *big.Int
}

func (c *Controller) PublishLPCapacity(ctx context.Context, id string, demand int64) (engine.LocalOperation, error) {
	if demand < 0 || demand > engine.Limit {
		return engine.LocalOperation{}, fmt.Errorf("invalid demand cap")
	}
	var op engine.LocalOperation
	err := c.Q.Exclusive(func(w *engine.Writer) error {
		if err := c.sync(ctx, w); err != nil {
			return err
		}
		if old := w.Snapshot().Local.Operations[id]; old != nil {
			var previous contracts.LPCapacity
			if err := json.Unmarshal(old.Data, &previous); err != nil {
				return err
			}
			if old.Kind != "lp_capacity" || previous.EligibleDemand == nil || previous.EligibleDemand.Cmp(big.NewInt(demand)) != 0 {
				return fmt.Errorf("operation ID reused")
			}
			op = *old
			return nil
		}
		epoch, err := c.Env.Uint(ctx, "SettlementController", "latestEpoch", 0)
		if err != nil {
			return err
		}
		root, err := c.Env.Read(ctx, "SettlementController", "currentRoot", 0)
		if err != nil {
			return err
		}
		nonce, err := c.Env.Uint(ctx, "LPShareVault", "capacityNonce", 0)
		if err != nil {
			return err
		}
		generation, err := c.Env.Uint(ctx, "AccessController", "signatureVersion", 0)
		if err != nil {
			return err
		}
		now, err := c.Env.RPC.Timestamp(ctx)
		if err != nil {
			return err
		}
		// 30 minutes leaves room for block inclusion within the contract's one-hour bound.
		r := contracts.LPCapacity{Epoch: epoch.Uint64(), Root: common.Hash(root[0].([32]byte)), EligibleDemand: big.NewInt(demand), Nonce: new(big.Int).Add(nonce, big.NewInt(1)), Deadline: new(big.Int).SetUint64(now + 1800)}
		tuple := capacityTuple{r.Epoch, r.Root, r.EligibleDemand, r.Nonce, r.Deadline}
		digest, err := r.Digest(new(big.Int).SetUint64(ChainID), c.Env.Address("LPShareVault"), generation)
		if err != nil {
			return err
		}
		remote, err := c.Env.Read(ctx, "LPShareVault", "hashCapacity", 0, tuple)
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
		op, err = c.submit(ctx, w, id, "lp_capacity", "LPShareVault", "publishCapacity", r, tuple, ss, rs)
		return err
	})
	return op, err
}

func (c *Controller) lpView(ctx context.Context, block uint64) (map[string]any, error) {
	if _, ok := c.Env.Deployment.Modules["LPShareVault"]; !ok {
		return nil, nil
	}
	result := map[string]any{"shares": c.Env.Address("LPShareVault"), "incentives": c.Env.Address("LPIncentiveDistributor"), "share_transfers_enabled": false}
	for _, v := range []struct{ module, method string }{
		{"LPShareVault", "phase"}, {"LPShareVault", "totalSupply"}, {"LPShareVault", "totalAssets"},
		{"LPShareVault", "depositCap"}, {"LPShareVault", "queueHead"}, {"LPShareVault", "nextRequestId"},
		{"LPVault", "peakNAVRay"}, {"LPVault", "maxDrawdownBps"}, {"LPVault", "openExposureUSDC"},
		{"LPVault", "reservedExitUSDC"}, {"LPVault", "reserveFeeAccruedUSDC"},
		{"LPIncentiveDistributor", "start"}, {"LPIncentiveDistributor", "end"}, {"LPIncentiveDistributor", "totalClaimed"},
	} {
		value, err := c.Env.Uint(ctx, v.module, v.method, block)
		if err != nil {
			return nil, err
		}
		result[v.method] = value.String()
	}
	return result, nil
}
