# Update: 7–10% house edge before FUSE rewards

29 October 2026. The user specified a **7–10% house edge**. This study treats it as the nominal underwriting edge **before FUSE rewards**. It supersedes the earlier 4% assumption for the current design discussion, while preserving the original studies as historical comparisons. The edge is a user-supplied assumption, not an independently measured outcome.

**Current accounting rule:** [weekly net realized profit with losses carried forward](WEEKLY_REALIZED_PROFIT_SHARE.md). House edge sets a quote's expected economics; actual settled results determine profit. The protocol's fixed 5% rate applies to distributable new realized profit at weekly close. The simulation below paid per batch and is retained as a historical timing comparison.

## Expected economics

For a 2x total payout, survival probability is `(1 − house_edge) / 2`. The standard reward is 2% of losing stake in current USDC redemption value, and one ninth of that percentage on winning stake. With immediate redemption at the quoted value:

| Per $10,000 of turnover | 7% edge | 8.5% edge | 10% edge |
|---|---:|---:|---:|
| Expected gross underwriting profit | $700 | $850 | $1,000 |
| Expected standard FUSE reward value | $117.33 | $118.67 | $120.00 |
| Combined margin after standard rewards | $582.67 | $731.33 | $880.00 |

The combined expected margin after standard rewards is **5.8267–8.8000% of turnover**, before operator income and operating costs. This expectation does not determine an operator payment. Actual settled profit, carried losses, capital protection, the weekly accounting boundary and integer rounding determine that payment. LP and FUSE allocations remain dynamic.

More edge makes standard rewards easier to fund. It does not establish profitable realized pricing, adequate operator income after actual costs, or customer demand. A target edge built into a quote requires the survival probabilities to be calibrated. Future appreciation of held FUSE is not included in the immediate-redemption calculation.

## The welcome offer depends on payout choice

At 2x, the 10% loss-value welcome offer and one-ninth win offer leave a positive house margin throughout the specified range:

| Nominal edge | House margin after welcome rewards at 2x |
|---|---:|
| 7% | 1.1333% |
| 8.5% | 2.5667% |
| 10% | 4.0000% |

The earlier 4%-edge statement that the 2x welcome bet is positive EV for the player no longer applies under these updated inputs. It remains relevant for some higher-multiplier welcome bets:

| Nominal edge | 5x welcome player EV | 10x welcome player EV | 100x welcome player EV |
|---|---:|---:|---:|
| 7% | +1.3467% | +2.1733% | +2.9173% |
| 8.5% | −0.1267% | +0.6867% | +1.4187% |
| 10% | −1.6000% | −0.8000% | −0.0800% |

These values are percentages of stake, before costs, and assume correctly calibrated, executable payouts. The $25 welcome wallet cap, $10k global quoted-value allowance, finite token inventory and adversarial testing remain necessary. Wallet caps alone are not Sybil resistance. The 2% standard reward remains below the nominal 7–10% edge across all tested payout multipliers.

## Re-simulated allocation

**72 policy/scenario evaluations** cover three edges, three scenarios, four seeds and two allocation rules. There are **54 exact expected-value sensitivities** across nine payout choices and standard/welcome rewards. All modeled conservation and accepted-quote checks passed. Six new focused tests pass, alongside the preceding 41 allocation/reward tests.

The dynamic case retains fixed 5% protocol income, the 60-day standard-reward target, $250k separate LP capital, $125k segregated backing and the existing funded quote budgets. Simulation payouts are 2x; the multi-payout table above is an analytic sensitivity, not a multi-payout market-path simulation.

Baseline medians across four seeds and 180 days:

| Assumed edge | Accepted bets | Gross trading profit | Operator income | New FUSE backing | Rewards paid | Reward coverage |
|---|---:|---:|---:|---:|---:|---:|
| 7% | 45,546 | $172,175 | $8,608.75 | $24,515.92 | $32,023.50 | 100% |
| 8.5% | 43,549 | $192,050 | $9,622.50 | $22,829.07 | $31,190.33 | 100% |
| 10% | 42,200 | $210,575 | $10,528.75 | $21,524.26 | $30,585.39 | 100% |

All four baseline and higher-volume seeds retain 100% reward-offer coverage under the dynamic 60-day rule at each edge. Winner-cluster median coverage is 57.1%, 67.2% and 76.9% respectively: stronger mean margin does not eliminate temporal losses or guarantee unlimited future offers.

The baseline has 300 wallets initially funded with $1,000 each, up to 300 $50 bets daily, no new funding and no reinvestment of reward proceeds. Higher volume uses 1,000 funded wallets and up to 1,000 bets/day. Higher edge consumes those finite trading bankrolls faster, reducing accepted bets mechanically. That is not observed retention or evidence that customers tolerate the higher cost. Existing underlying price, correlation and custody risks remain outside this expected-value assumption.

## Configuration and reproduction

The checked-in `engine/config/local.json`, `paper.json` and `paper-recovery.json` still specify `house_edge_bps: 500` for the listed DNT models. Those are repository defaults and may differ from the intended deployment. This study neither changes those settings nor claims that a 7–10% realized edge has been established. Any live configuration update is a separate implementation task.

```sh
python3 -m unittest discover -s scripts -p test_house_edge_stress.py
python3 scripts/stress_house_edge.py --seeds 4
```

- `scripts/stress_house_edge.py`: reproducible edge sensitivity using the dynamic allocator.
- `scripts/test_house_edge_stress.py`: exact probability, reward and operator-share checks.
- `.local/house-edge-stress/20261029/experiment.json`: user assumption and source hashes.
- `.local/house-edge-stress/20261029/results.json`: all scenarios, controls and expected values.
- `.local/house-edge-stress/20261029/report.md`: generated full tables.

The [dynamic allocation proposal](DYNAMIC_PROFIT_ALLOCATION.md) remains the allocation mechanism. The [funded reward offer](FUSE_FUNDED_REWARDS_PROPOSAL.md) remains the player-facing candidate. The updated edge makes their modeled funding more comfortable; actual retention and realized underwriting performance remain to be measured.
