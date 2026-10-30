# Fixed 5% protocol income, dynamic LP and FUSE funding

29 October 2026. This amends the funded-rewards proposal in response to the user's requirement: **the protocol percentage stays at 5%; the LP/FUSE split changes with economic conditions**. It is a proposed economic rule tested offline, not an implemented contract change.

**Updated edge:** the subsequent [7–10% house-edge sensitivity](HOUSE_EDGE_SENSITIVITY.md) replaces the earlier 4% assumption for current design discussion, retaining the allocation mechanism and adding 72 evaluations. The baseline comparison below records the earlier 4% study.

**Current accounting rule:** the user selected [weekly net realized profit with losses carried forward](WEEKLY_REALIZED_PROFIT_SHARE.md). The 5% rate applies at weekly close; the remaining profit is allocated dynamically at that close. The experiments below crystallized profit per settlement batch and remain historical comparisons, not weekly results. Quoted house edge never substitutes for actual profit.

## The allocation rule

Apply the percentage to **new distributable realized profit**, after prior losses have been recovered and the protected LP capital floor has been restored. Deposits, gross losing stakes, already consumed profits, reserve backing and customer balances are not the fee base.

1. Protocol operations receives **5% of distributable profit**, floor-rounded in USDC units.
2. The remaining **95%** is shared dynamically between retained LP equity and FUSE reserve funding.
3. FUSE receives enough to replenish its funded standard-reward allowance toward a target runway, limited by available profit and LP capital headroom.
4. LPs retain the remainder. If the LP needs capital, or FUSE already has its target allowance, more remains with LPs.

For $1,000 of distributable profit, operations receives $50. The other $950 can be $950 LP / $0 backing, $350 LP / $600 backing, or another split derived from actual needs. These are examples, not hardcoded percentage tiers.

“Fixed 5%” means a fixed fee rate. If distributable profit is zero, operator income is zero. If the protocol also provides LP capital, that ownership earns the same proportional LP return as other LP capital; it is separate from the operator fee.

## Concrete first candidate

Retain the existing research protection of **2× required capital**, and aim to retain **3× required capital** before sending new profits to the FUSE reserve. Required capital must reflect real accepted liabilities and be independently checked; these multiples are provisional research parameters, not proofs of solvency.

Use **60 days of standard-reward allowance** as the provisional FUSE target. Estimate the daily need from the preceding 30 days of completed, accepted trading, using the standard 2% loss reward and one-ninth win reward. The welcome promotion has its own prefunded allowance and does not drive the recurring target.

Thirty days gave more profit retention to LPs in the tested paths. Sixty days improved reward availability after a winner cluster. Neither target dominates every scenario, and neither is calibrated to measured user demand.

The simplified integer rule is:

```text
new_profit      = equity above the unrecovered historical high-water mark
distributable   = min(new_profit, max(0, equity - 2 × required_capital))
protocol        = floor(5% × distributable)

allowance_gap   = max(0, target_allowance - available_standard_allowance)
backing_needed = ceil(allowance_gap / reward_credit_fraction)
capital_room   = max(0, equity - protocol - 3 × required_capital)

FUSE_backing    = min(distributable - protocol, backing_needed, capital_room)
LP_retained     = new_profit - protocol - FUSE_backing
```

The reward-credit fraction remains the tested 90% of newly funded reserve USDC. It controls how much of a reserve transfer becomes permission to quote additional rewards, rather than fixing the LP/FUSE profit split. Token inventory is still reserved separately before an offer is accepted.

The algorithm counts each reserve transfer once. Credit from today's transfers becomes usable for new reward offers the next day; pending credits are included when calculating whether another transfer is needed. Previously accepted rewards are honored. When future quote capacity runs out, the ticket must disclose the absence of a reward before a new bet is accepted.

Retained capitalization profits raise the high-water mark and cannot be retrospectively charged after conditions improve. Operator income and FUSE funding paid before a later drawdown are not clawed back by this model. Funds already in the FUSE reserve remain segregated from underwriting capital.

## Stress comparison

The study re-simulates admission and LP cash under each rule. It does not replay accepted trades against an unchanged LP balance. There are **132 synthetic policy/scenario evaluations**: 11 scenarios, four seeds, and three rules (fixed 35% backing with 5% operations, dynamic 30-day runway, dynamic 60-day runway). All modeled cash, inventory, accepted-quote and capital-floor checks pass. Ten focused allocation tests pass, including 10,000 randomized allocation checks; 31 earlier reward tests also pass.

The starting assumptions remain $250k LP capital, $125k segregated USDC backing, a $10k welcome allowance and $10k standard continuity allowance within that backing. Baseline is 300 funded wallets, up to 300 $50 one-stage 2x bets/day, 48% survival, and 180 days. No new customer funding, reward recycling, price fitting, secondary buyers or retention improvement is assumed.

Medians across four baseline seeds:

| Rule | Operator income | LP final equity | New FUSE backing | User rewards paid | Reward coverage |
|---|---:|---:|---:|---:|---:|
| Fixed 5% protocol / 35% backing / 60% LP | $5,180 | $312,160 | $36,260 | $33,254.61 | 100% |
| Dynamic, 30-day target | $5,180 | $325,510.62 | $22,735.75 | $33,254.61 | 100% |
| Dynamic, 60-day target | $5,180 | $321,190.56 | $27,103.96 | $33,254.61 | 100% |

These are separate medians; arithmetic between median columns does not reconstruct a single path. The fixed 5% rate is checked at every individual checkpoint against distributable profit, not inferred from the table.

The 60-day dynamic rule retains more LP equity than the fixed split while paying the same baseline rewards in these paths. It also preserves baseline/higher-volume reward coverage. This is a conditional simulation result, not evidence of higher actual LP returns or demand.

The trade-offs remain material:

- In the ten-day winner-cluster case, future reward coverage is 59.9% under the fixed split, 41.6% with a 30-day dynamic target, and 54.2% with a 60-day dynamic target. The prefunded allowances honor accepted offers; they cannot guarantee unlimited new rewards through a loss-recovery period.
- With a weaker 2% underwriting edge, dynamic 60-day funding produces 100% median reward coverage, compared with 98.0% under the fixed split, while leaving less profit in LP equity. Changing the split changes who bears the trade-off.
- No trading produces no operator income and no new reserve funding. Negative underwriting edge still depletes LP capital and interrupts future reward offers.
- The fixed operator fee does not pay infrastructure or staffing by itself; actual costs and funded volume determine whether operator revenue is adequate.

## Implementation boundary

Current `LPVault` still has its existing maximum 35% reserve allocation and no separate 5% operator revenue transfer. Implementing this amendment would require a new reviewed allocation rule, operator recipient/claim accounting, fee recovery and capital gates, reserve authorization integration, and accepted-reward reservations. No contracts, live policies or USDC balances were changed by this study.

The new model assumes successful, immediately authorized economic transfers and a fixed LP share cohort with no deposits or exits. Capital flows, LP equity dilution, public withdrawal queues, delayed fee claims, oracle truth, hedge/Sybil resistance and voluntary user/LP demand need further verification. The 60-day choice is a provisional target rather than an optimized launch constant.

## Reproduce

```sh
python3 -m unittest discover -s scripts -p test_dynamic_profit_allocation.py
python3 -m unittest discover -s scripts -p 'test_loss_reward*.py'
python3 scripts/dynamic_profit_allocation.py --seeds 4
```

- `scripts/dynamic_profit_allocation.py`: fixed operator percentage, dynamic allocation and re-simulated trading.
- `scripts/test_dynamic_profit_allocation.py`: deterministic and randomized allocation checks.
- `.local/dynamic-profit-allocation/20261029/experiment.json`: assumptions and source hashes.
- `.local/dynamic-profit-allocation/20261029/results.json`: every case and first-seed daily allocation records.
- `.local/dynamic-profit-allocation/20261029/report.md`: generated tables for all scenarios.

The [funded rewards proposal](FUSE_FUNDED_REWARDS_PROPOSAL.md) supplies the player offer. Its earlier fixed-35% figures remain historical comparisons; the allocation amendment above supersedes that fixed split as the current design candidate.
