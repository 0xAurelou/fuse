# USDC-backed FUSE: nine-times loss reward stress test

Run date: 29 October 2026. Research only; no contract, deployment, live configuration or funds were changed.

The proposed rule gives a losing stage nine times the reward weight of a winning stage. FUSE remains a fixed-supply token redeemable against a segregated USDC reserve when redemption is enabled, with no ownership claim on LP capital.

The rule shifts rewards toward losses as intended. It does not itself increase LP profit. Initially empty backing provides little executable consolation, while sufficiently valuable existing backing can make subsidized play or deliberate losses profitable. A fixed outcome ratio alone cannot control that subsidy across the protocol's lifetime.

## Scope and reproduction

```sh
python3 -m unittest discover -s scripts -p test_loss_reward_stress.py
python3 scripts/stress_loss_rewards.py --seeds 8
```

The run contains **1,344 paired policy/budget/redemption trajectories**, **10,800 single-epoch adversarial cases**, and retrospective reward reweighting of two recorded local runs. Thirteen focused tests pass. Integer conservation checks pass for every simulated path. These checks establish modeled accounting, not voluntary demand or launch readiness.

Artifacts:

- `.local/loss-reward-stress/20261029/experiment.json`: assumptions and source SHA-256 hashes.
- `.local/loss-reward-stress/20261029/results.json`: every scenario, seed, policy, attack case and historical reweighting result.
- `.local/loss-reward-stress/20261029/report.md`: complete generated tables and limitations.

The simulator is `scripts/stress_loss_rewards.py`. It reuses `scripts/contract_lp_model.py` for the existing share-mode LP high-water mark, fee accrual, capitalization ramp and reserve funding rules. It projects authorized economic operations offline; it does not execute contracts, verify signatures or simulate oracle prices.

## Assumptions

Each synthetic trajectory covers 180 days, eight independent seeds, 300 wallets initially funded with $1,000 each, and up to 300 one-stage $50 bets daily. Payout is 2x total stake, with baseline survival probability 48%, giving a 4% expected underwriting edge before rewards. These probabilities and participation are assumptions, not calibrated forecasts. Players stop placing full-size bets when their cash is insufficient. No new deposits or redeemed-cash recycling are assumed.

LP capital starts at $250,000 unless otherwise specified. Share economics are assumed activated from the start, without subsequent deposits, exits or LP mining. The reserve receives permitted fees immediately after each of six settled batches daily. Allocation is at most 35% of eligible new profits, subject to historical loss recovery, the capitalization ramp and the 2C floor. Accrued fees are excluded from usable LP equity. Admission conservatively preserves the signed next-batch capital requirement even after worst-case accepted payouts. No separate drawdown pause/recovery controller is enabled in these stresses.

All 1B genesis tokens count in backing: 600M trader emissions, 50M inactive LP emissions and 350M locked treasury. Rewards transfer existing tokens. Redemption burns tokens using a fixed supply/backing snapshot and a 10% penalty. Pending claims are deducted from subsequent available backing. Daily requests are claimed after their window; end-of-horizon requests are claimed after the final window. There are no secondary buyers, imagined listing prices or FUSE price appreciation assumptions.

Current scores use win 10,000 / loss 2,000. Proposed scores use win 1,000 / loss 9,000. Neutral scores use 10,000 / 10,000. Each score also includes actual stake and time exposed, with no streak bonus. The activity rate is the current research setting of 100 FUSE per USDC exposed for a full 30 seconds at weight 1.0.

The hypothetical daily emission cap starts at 10M FUSE, decays 3.4% daily and expires after 180 days, always within the 600M trader escrow. This is a research schedule, not the accelerated local deployment schedule or an approved production curve. A separate control holds the current policy's activity budget constant so that only recipient allocation changes.

The common-draw stress uses an 80% probability of selecting a batch-wide outcome draw. That mixture parameter is not a measured 80% pairwise outcome correlation. Forced losses at 1 ms, 15 seconds and 29,999 ms are adversarial bounds; they are not evidence that traders can force an oracle outcome at a chosen time. Positive initial reserves assume prior historical funding kept separate from initial LP capital.

## What changes on matched trading paths

Medians across eight seeds, with end-of-horizon redemption:

| Scenario | LP final equity | Maximum LP drawdown | New USDC backing | Proposed aggregate trader redemption |
|---|---:|---:|---:|---:|
| Baseline | $319,735 | 1.0% | $38,115 | $1,713.82 |
| No trading | $250,000 | 0.0% | $0 | $0 |
| Trading stops after day 30 | $261,972.50 | 0.7% | $6,825 | $78.60 |
| Ten-day winner cluster | $197,825 | 57.5% | $6,825 | $294.67 |
| Negative edge: 55% survive at 2x | $165 | 99.9% | $0 median | $0 median |

LP equity, accepted trades and reserve funding are identical across reward policies for each paired trading path. The reward split cannot fix bad pricing or winner clustering. Physical payout funding remained intact because new admissions were rejected when capital was insufficient; this does not establish acceptable LP drawdown.

Under the direct score change, baseline median emissions fall from 80.44M to 49.72M FUSE and aggregate redemption falls from $2,757.28 to $1,713.82. This decrease is caused by changing absolute weights inside the activity cap, not an inherent consequence of a 9:1 ratio. Holding the existing activity budget constant preserves aggregate emission and redemption to bounded recipient-rounding differences, while shifting who earns the tokens.

About **83.1%** of proposed baseline reward score comes from losing stages. It is not exactly 90% because actual losses generally end earlier than winning stages. Daily redemption pays a median $626.77 under the direct proposal versus $1,713.82 when everyone waits until the end; early burns relinquish participation in later backing growth. Neither behavior is assumed to be an optimal redemption strategy.

In the forced-loss cohort, 60 initially funded farmers collectively lose their entire $60,000 trading bankroll. With initially empty backing, their median eventual redemption is approximately $0.008 for 1 ms losses, $122.49 for 15-second losses and $244.98 for 29,999 ms losses. Under the assumed $10M starting reserve, the late-loss cohort redeems $48,843.36 and remains cash-negative by $11,156.64. This is finite-bankroll behavior under the stated emissions and timing, not evidence about organic retention.

## When losing becomes profitable

The following single-epoch examples assume:

- One $100 loss at 29,999 ms; no attacker FUSE owned before the bet.
- 1B outstanding FUSE; the epoch/activity caps do not constrain this bet.
- Proposed win/loss weights 1,000 / 9,000 and the 100 FUSE activity rate.
- A maximum $35 contribution from the new loss to reserve backing.
- Redemption enabled at the resulting fixed snapshot, with 10% penalty.

| Existing USDC backing | Attacker redemption | Cash result after losing $100 |
|---|---:|---:|
| $0 | $0.0003 | −$99.9997 |
| $1M | $8.1000 | −$91.9000 |
| $10M | $80.9976 | −$19.0024 |
| $100M | $809.9733 | +$709.9733 |

The proposed single-loss break-even point is approximately **$12.35M backing at 1B outstanding tokens**, versus approximately $55.56M under current loss weights. For a nearly full-duration loss, the proposal releases approximately 90 FUSE per dollar lost; after the 10% redemption penalty, the rough break-even condition is:

```text
81 × backing_USDC_per_FUSE >= 1
```

This threshold depends on emission rate, duration, outstanding supply, penalty, competition and remaining epoch capacity. It is not a universal dollar limit. Instant-loss farming remains cash-negative even in the $100M backing examples because the stake*time score is tiny. At a 1 FUSE activity rate, no scanned attacker is cash-profitable; at 100 and 1,000 FUSE rates, profitable bounded cases exist. These counts describe the grid and are not attack probabilities.

If an attacker also owns 90% of LP equity, they recover 90% of the retained $65 as LP equity, reducing their economic cost to $41.50 before redemption. That can make the $10M backing example wealth-positive even though redemption cash alone remains below the $100 loss. The grid reports retained equity separately; it assumes neither an immediate LP exit nor a second claim on the same money.

Ordinary play can also become profitable through subsidies without forcing a loss. For a 2x bet with 48% survival and average failed duration 15 seconds, the proposed uncapped activity rate produces an expected 28.2 FUSE per dollar staked. At a fixed $0.001 USDC backing per FUSE, a $100 wager has approximately −$1.462 expected net cash result including redemption, compared with −$4 without rewards. At $0.01 backing per FUSE, that becomes +$21.38. This calculation holds backing and subsidy rates constant and excludes timing, caps, operating costs and the tiny marginal backing contribution. Such a subsidy can be intentional, but consumes finite existing backing rights.

## Retrospective outcome reweighting

Two previously recorded runs were read without generating new market data or rerunning prices. Voids were excluded, actual stake and capped start-to-resolution durations were retained, and the outcomes were counterfactually scored as one reward epoch with a 10M cap.

| Recorded run | Eligible stages | Losing-stage score: current | Losing-stage score: proposed | Proposed rewards earned by accounts that won overall |
|---|---:|---:|---:|---:|
| 20261026-002626 | 519 | 13.1% | 87.1% | 12.7% |
| 20261026-012628 | 471 | 9.9% | 83.2% | 30.7% |

These short local traces support the direction of redistribution. They do not validate long-run prices, funded organic demand, future profitability or a retention improvement. Account-level net profit sums each completed stage's realized incremental USDC change before token rewards. Rewarding losing stages still rewards some players who win overall; per-wallet net-loss scoring alone would also be vulnerable to splitting activity among wallets.

## Design consequence

A 9:1 loss multiplier is a plausible distribution preference. Its lifetime economic cost needs an independent USDC-value budget that accounts for current backing per outstanding FUSE, remaining token emissions and likely player behavior. Merely flipping weights cannot establish that cost or prevent farming as backing grows.

Before a live policy change, compare bounded subsidy budgets at different maturity levels and test whether actual funded users return after losses. A current-value cap does not promise that the future value of held FUSE stays below an earlier loss: future backing and burns can change redemption value. HYPE conversion, future token bids, gas and operating costs, LP exits and real retention are outside this study.

The follow-up [funded rewards proposal](FUSE_FUNDED_REWARDS_PROPOSAL.md) tests the user's $100k–$150k backing budget, accepted USDC-value quotes, welcome and ongoing rewards, daily zero-penalty redemption, and an explicit continuity allowance. It retains these original stress results and adds a concrete pilot specification.
