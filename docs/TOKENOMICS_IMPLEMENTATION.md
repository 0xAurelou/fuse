# Tokenomics implementation and research

The supplied specification is retained in [TOKENOMICS_SPECIFICATION.txt](TOKENOMICS_SPECIFICATION.txt). Its candidates are implemented as explicit local research policies, not approved launch economics. Public HyperEVM execution remains disabled.

## Findings from the supplied run

Run `20261025-223015` reconciled 121 local checkpoints and exact PostgreSQL replay, but LP capital fell from 250,000 to 191,988.030816 USDC. Of 432 resolved stages, 427 survived, 3 breached and 2 voided. No eligible LP profit existed, so reserve funding/redemption correctly skipped. All 1B outstanding FUSE still counted in backing. A successful technical E2E did not establish sustainable pricing or token value.

The earlier widths were deliberately varied, untrained experiment inputs. The deterministic paper fixture has one account and 23 commands; the repository provides no historical Papertrade TVL, conversion, demand elasticity or FUSE secondary-market order book. Those inputs are not invented by the simulator.

## Specification mapping

| Specification | Implementation and validation |
|---|---|
| USDC game and separate FUSE rewards | Real custody/LP settlement and token reward claims; no FUSE derivative payout. |
| Fixed 1B genesis; 600M/400M escrows | Fixed mint, no later mint path, treasury remains constrained by an explicit immutable release manifest. Both escrows count in the backing denominator. |
| Finalized at-risk mining; 1.0/0.2; no streak | V2 linear stake-time scores with no per-wallet cap or extra streak bonus. First final outcomes are deduplicated across reward epochs; voids/rejections score zero. |
| Reproducible reward manifests | Policy/hash, stage IDs, outcome sequences, stake, at-risk duration, committed payout, difficulty-policy version, total score, requested/activity/used budget, allocations and proofs are committed and retained. |
| Utilization and emission decay | Explicit research activity rate caps low-volume rewards. Current time slots decay independently of publication; missed slots expire, cannot catch up, and cannot be reused. An immutable finite horizon is mandatory. Lifetime allocation stays within 600M. |
| Solvency-gated reserve funding | Historical profit-HWM recovery, single-use consumed profit, integer SR ramp and a 2× capital floor. Actual USDC reaches the segregated reserve through dual-authorized transfers. Zero allocation can pause new funding. |
| Activation | Transfers remain timelocked. Redemption epochs cannot open until transfers are enabled; governance activation is distinct from opening a funded epoch. |
| Fixed epoch backing and burns | Scheduled future epochs snapshot at actual permissionless start/first valid request. All requests use that snapshot; new funding is for later snapshots. Cumulative per-account rounding, outstanding claims and one-time payments are enforced. |
| Last-supply residual | Final outstanding supply cannot be burned. No residual sweep or new beneficiary is invented. |
| Cohorts, liquidity and farmer equilibrium | Research simulator tracks organic/early miners/late miners/buyers, emissions, burns, USDC PnL, escrow dilution and paid intrinsic redemption. Baseline has no secondary bids; liquidity variants are explicitly synthetic and externally funded. No imagined listing-price mark-to-market. |
| Strategic/failure stresses | Deliberate-loss farming, correlation, no demand, farming collapse, oracle interruption, drawdown and delayed/expired emissions are exercised. Existing pause, reorg, signature rotation, refund and recovery tests remain in place. |
| Disclosures | `GET /v1/tokenomics` reports confirmed supply/escrow/circulation, activation, cumulative emissions, LP capital/exposure/HWM, reserve allowance, free backing, unpaid claims, epoch terms, concentration and retained penalties. Backing is an exact rational, and unknown market bids are null. |

Reward-score truth and accepted exposure remain operator-attested. Signatures and Merkle proofs constrain execution; they do not independently prove the market path or economic fairness.

## Reproduce the experiments

```sh
python3 scripts/analyze_papertrade.py
python3 scripts/calibrate_pricing.py
./scripts/local-live-e2e.sh --traders 300 --seed 20261026 \
  --config .local/pricing-calibration/policy.json \
  --calibration .local/pricing-calibration/calibration.json \
  --capture-seconds 600 --cohort-size 100 \
  --cohort-interval-seconds 180 --control-every 2
# The runner freezes before deployment and automatically evaluates afterward.
# Recheck that exact experiment without refitting:
python3 scripts/validate_pricing.py --experiment /absolute/path/to/run/experiment.json \
  --run /absolute/path/to/run/evidence
python3 scripts/simulate_tokenomics.py
./scripts/local-hyperevm-e2e.sh
```

Calibration uses paired real HyperCore oracle receipts, exact barrier-touch arithmetic and complete 30-second non-overlapping windows. Gapped windows and cross-run overlap are excluded. Splits are chronological 60/20/20, and only training selects widths. Targets 40–54% are compared. A minimum gate of 200 training, 100 validation and 100 test windows is reported; current repository data fails it. Fractional widths use integer ppm (1 ppm = 0.01 bps), preserving all previous journal encodings when omitted.

The first frozen candidate used 20/7/7 windows and selected 1.17 bps for the 48% hypothesis. Held-out survival was 4/7, with a broad 95% interval. In the independent later run, the frozen width survived 1/2 independent windows, while the timing-varied trader profiles survived 6/131 stages. These correlated trader stages cannot be treated as independent calibration samples. No 48% production model is established.

The extended E2E supports 300 wallets sharing the original aggregate risk scale, spaced entry cohorts and continued oracle capture after early game completion. Exact-width controls are separate from varied-width stress profiles. Each predeclared experiment pins the candidate, training sources and run parameters before deployment. The prospective gate uses 48% ±5 percentage points and at least 400 eligible nonoverlapping windows; it reports contract/accounting health separately from target evidence, without approving production. Oracle gaps and material disagreements invalidate windows. All cohort outcomes, claims, reserve transfers, actual backing and settlement evidence remain reviewable in the run directory. Longer observation and measured voluntary demand are still required by the tokenomics acceptance condition.

The revised 100-user run `20261025-230950` passed actual settlements, reward claims, reserve funding, burns/redemption, conservation and exact replay. Gross realized LP profit was 13,958.243328 USDC; 4,885.385164 USDC funded the reserve. LP ended at 259,072.858164 USDC; reserve assets after redemption were 4,885.380817 USDC. This single short outcome is not a projected return.

The extended run `20261026-002626` passed with 300 wallets in three cohorts, 150 exact-width controls, 288 distinct initial stakes, five widths, five strategies and targets across all eight stages. It finalized 522 stages (187 survived, 332 breached, three voided), 339 onchain checkpoints, 299 customer withdrawals and 299 eligible reward claims. All 7,037 journal events replayed exactly; custody and open exposure ended at zero. Journal reconstruction found a minimum LP balance of 244,950.443716 USDC and peak open exposure of 8,606.272448 USDC. Trading, finalization and replay took about 22 minutes, including ten minutes of live capture, plus deployment/setup time; this is not a production throughput benchmark.

Final LP equity was 265,314.691656 USDC, with realized profit of 15,314.691656 USDC. Reserve funding correctly stayed zero: the earlier realized-profit high-water mark was 15,496.327584 USDC. The positive-profit result therefore exercised the recovery guard, while the separate deterministic/fork E2E exercised positive reserve funding, burns and redemption payouts.

The unchanged 1.17 bps candidate survived nine of 20 eligible nonoverlapping forward windows (45%; descriptive Wilson interval 25.8–65.8%). This fails the 400-window minimum sample gate. Control ladder entries also showed a concerning stage difference: stage 1 survived 81/193 valid entries, stage 2 only 1/71, and stage 3 1/1. These are correlated entries sharing BTC paths, not independent trial counts. The unconditional estimate cannot validate conditional ladder survival; stage-conditioned calibration and forward validation remain required. Continue local integration and data collection, without promoting the pricing candidate or claiming economic acceptance.

Two earlier 300-user attempts remain retained: `20261025-234546` exposed queue-time expiry during entry, and `20261025-235912` stopped after 257 withdrawals on a local RPC timeout that had been misclassified as a permanent halt. Fixes separate queue delay from first-request retry time, sort stage IDs once per event, reuse unchanged current width policies, batch every account's confirmed withdrawal read, avoid idle empty-block mining, and fence new admission during transient RPC outages until successful reconciliation. Malformed evidence, confirmed reorgs and accounting mismatches still fail closed. A real-contract E2E injects the transport outage before testing the permanent reorg halt. The final HyperEVM testnet fork run `20261026-002631` passed at source block 67861935; signed execution stayed on local chain 31337.

The economic sweep covers all requested parameter values through a baseline, one-factor sweeps and 160 seeded joint combinations. It includes stage-conditioned survival shapes, correlation and unmeasured demand-response coefficients. It reports a conditional organic-demand frontier, not a universal optimum. The 70% allocation experiment is explicitly outside the contract's 50% ceiling. Every simulated USDC movement and FUSE supply change is conserved with integer accounting.

## Faster parameter fitting and convex optimization

The scalar corridor calibrator now solves two precisely defined problems without an external solver. For a path with entry price `P` and maximum absolute movement `D`, both in integer price units, the smallest surviving integer ppm width is `ceil((D + 1) * 1,000,000 / P)`. This preserves the engine's rounded barrier and touch-is-loss rule. Sorting these thresholds gives every attainable empirical survival count. Searching that frontier globally minimizes distance from the target, with narrower widths breaking ties, in O(n log n) preprocessing rather than scanning every ppm value. Legal maximum widths are enforced, and the report states when the exact target is unattainable because of sample size, repeated thresholds or bounds.

The comparison solver minimizes the convex scalar pinball loss `sum(q*max(T-w,0) + (1-q)*max(w-T,0))`, with `q=0.48` and integer survival thresholds `T`. A quantile order statistic is an exact global minimizer of its continuous relaxation and provides an integer optimum under integer bounds. It needs no iterative LP package. Quantile-loss optimality and closest empirical survival are distinct objectives: tied thresholds can make the convex optimum jump over the requested survival fraction. Both candidates and the attainable frontier are included in `calibration.json`; the generated policy retains the nearest-survival objective. Model identifiers include the method, bounds, target and source manifest.

Calibration and prospective validation now share the same paired-entry, expiry-health, gap and disagreement eligibility checks. A research refit can be generated separately from a frozen candidate:

```sh
python3 scripts/calibrate_pricing.py --output .local/pricing-optimization/new-research
```

In the retained `fast-scalar-research` experiment, the chronological split had 33/11/12 windows. Both scalar objectives selected 0.78 bps: training survival 48.5%, validation 18.2%, test 33.3%, with an unpassed sample gate. A search-only benchmark over 100 repetitions measured median 1,827.875 microseconds for the prior grid and 38.4585 microseconds for the exact frontier, about 47.5x faster. These timings exclude source parsing, live capture, settlement and replay. The original 1.17 bps candidate's policy/calibration hashes and its 9/20 prospective result were verified unchanged. Faster fitting does not shorten the need for new market evidence or approve the new width.

For context-dependent widths, the next model is regularized linear quantile regression using only features observable at entry, such as trailing volatility, elapsed time since an oracle price change, BBO/oracle displacement and stage. A linear predictor with pinball loss and suitable convex constraints is a convex subproblem; see the [QuantileRegressor documentation](https://scikit-learn.org/stable/modules/generated/sklearn.linear_model.QuantileRegressor.html). This conditional model is not implemented or validated by the scalar solver. It requires chronological evaluation and enough distinct entry episodes to investigate the observed second-stage failure concentration. Jointly selecting the entire ladder and tokenomics parameters remains path dependent: changing a stage width changes who reaches later stages, while LP high-water marks, admission limits, emissions and redemption actions create discrete branches. A global convex guarantee for that full simulator is not claimed.

## External LP participation amendment

The supplied proposal is retained verbatim in [LP_INCENTIVES_PROPOSAL.txt](LP_INCENTIVES_PROPOSAL.txt). `scripts/simulate_lp_incentives.py` adds a separate, integer-ledger research model before any change to contract ownership, settlement or the frozen pricing candidate. The proposed allocation is **600M trader mining + 50M LP bootstrapping + 350M locked treasury = 1B FUSE**. LP tokens come out of the existing 400M allocation; no new supply is minted. Different LP budgets in sensitivity cases leave the corresponding remainder locked.

The model implements settled USDC equity shares, loss participation, contribution-adjusted per-share high-water marks, solvency-gated asynchronous withdrawal requests, demand-capped deposits and a finite 60/90-day reward schedule. The baseline uses 90 days of decaying LP emissions, 30-day vesting and a two-day minimum withdrawal delay. Requests retain their shares and exposure to losses until fulfillment at current reconciled NAV. A strict FIFO queue preserves the two-times-capital floor and does not fulfill while exposure is open or reconciliation is stale. Forty-eight hours is a minimum wait, not a payment guarantee. Protocol-owned and pending-exit shares do not mine LP FUSE.

The baseline starts with the existing **250k USDC protocol LP**, 100 synthetic potential LPs with 50k USDC each, and 300 funded trader wallets with 1k USDC each. It attempts 300 games/day in six batches. A separate 5M seed case reproduces the proposal's starting assumption. Continuing-demand cases explicitly inject **150k USDC/day of external trader funding** and attempt 3,000 games/day in twelve batches. This is an assumption about new customer cash, not revenue created by the protocol. Baseline trader wallets cannot spend or lose money they do not have. Unfunded attempts are rejected; simultaneous reuse of a wallet is rejected. After losses, finite demand can disappear.

Default trade limits retain the local policy's 100k USDC aggregate incremental exposure, 10k per active account, 1k initial stake maximum and 100 USDC buffer. Risk-cap alternatives are separately labeled. Outcomes are synthetic correlated Bernoulli paths, with unchanged latent draws kept independent of LP behavioral randomness. They do not run the frozen oracle pricing model or infer fair widths from historical data.

LP entry and withdrawal decisions depend on recent share returns, drawdown, utilization and a disclosed subjective bootstrap-interest response. These response rules are not empirical demand estimates and assign no USD listing price to FUSE. The default phase assumptions are protocol-only days 0–13, a capped whitelist from day 14, and public eligibility from day 45; active-demand stresses deliberately open days 1/7 to exercise deposit and withdrawal paths. These phases are simulation inputs, not launch dates or contract permissions.

Deposit capacity is limited to the smaller of 20M USDC and the trailing seven-day requested peak liability divided by the target utilization, with requested risk bounded by the scenario's admission cap. Capital already above that cap is not forced out. The reward utilization gate uses **actual admitted incremental liability × actual time at risk / equity × time**, rather than requested demand or a peak TVL snapshot. LP rewards also scale by each external provider's active time-weighted capital; protocol capital remains in the denominator. Unused schedule slots expire and cannot catch up. Unvested and unreleased FUSE remain in the reserve backing denominator. The only modeled FUSE cash proceeds come from actual simulated reserve redemption, after vesting and transfer activation, with the common epoch snapshot and penalty.

The proposed LP-first waterfall crystallizes at each settled batch. It first recovers the prior per-share high-water mark, then applies the capitalization ramp and two-times-required-capital floor, transferring at most 35% of eligible profit. Profits retained to restore capitalization raise the LP's high-water mark and cannot be charged retroactively later. A new deposit or withdrawal at fair NAV does not reset the loss-recovery mark. The tested 5M capital / 200k profit example leaves **130k in share NAV and funds 70k to the reserve**. This is a proposed per-share fee rule; its crystallization and accounting differ from the existing gross cumulative-profit/consumed-profit contract policy.

Reproduce the complete matrix, including retained live-run counterfactuals:

```sh
cd /Volumes/dev/fuse
python3 scripts/simulate_lp_incentives.py
python3 -m unittest discover -s scripts -p 'test_*.py' -v
```

For a short standalone smoke simulation without local run data:

```sh
python3 scripts/simulate_lp_incentives.py --quick --days 45 \
  --skip-retained-runs --output .local/lp-incentives-research/smoke
```

The full matrix uses 180 days, baseline and named stresses, one-factor sweeps, 24 seeded joint parameter combinations and 16 additional seed trajectories. It covers seed capital, survival, correlation, reserve share, 0/10M/50M LP budgets, 60/90-day bootstrap, emission half-life, vesting, 2/4/7-day exit waits, dynamic caps, utilization targets, LP response strength, trader funding and exposure limits. These are bounded research cases, not exhaustive optimization or a measured equilibrium. Named stresses cover no demand, no organic demand, deliberately losing farmers, correlated winners, drawdown, a withdrawal run, oracle gaps/outages, demand collapse, incentive expiry and stage-dependent survival.

Outputs under `.local/lp-incentives-research/` include `experiment.json` with the input matrix and source hashes, `report.md`, and `results.json` with each trajectory, cash PnL, share NAV, drawdown, capital flows, claims, utilization, vesting and remaining supply. The `*-events.jsonl` files record deposits, requests, payments, rewards and settled batches for the baseline and active stresses. Every simulated day checks exact USDC and FUSE conservation, share ownership, queued-share bounds and funded payouts. Tests additionally exercise NAV rounding, deposit caps, fee-free loss recovery, vesting, emission expiry and stale/open-exposure exit blocking. Terminal pending withdrawals and unvested rewards remain explicit obligations rather than being silently discarded.

Completed retained live runs are also read without modification. Their canonical settlement event fields are replayed through the proposed fee waterfall, with original reserve outflows excluded and journal hashes retained. These are **counterfactual settlement-level accounting illustrations**, with no external LP participation or changed trade admission. They are not new contract E2Es and do not validate future capital availability under the changed waterfall. Fee timing can leave reserve funding in a path that later draws down; losses do not claw back earlier reserve transfers.

The proposed asynchronous share lifecycle follows the Pending → Claimable → Claimed concepts in [ERC-7540](https://eips.ethereum.org/EIPS/eip-7540), which extends [ERC-4626](https://eips.ethereum.org/EIPS/eip-4626). The simulator does **not** execute those contract interfaces or establish standard compliance. LP share contracts, request/claim APIs, reward/vesting contracts and the treasury allocation manifest require separate contract/backend/fork verification. The workspace contains LP share contract work that is outside this research comparison. Frozen policies and previous E2E evidence remain unchanged by these simulations.

The retained full run at `.local/lp-incentives-research/full/` contains **87 scenarios × 180 days**, with all daily USDC/FUSE/share checks passing and seven retained settlement paths reconciled. Nineteen trajectories exercised external LP deposits and withdrawal requests. The older fixed-capital tokenomics model was also rerun separately: 214 scenarios passed its conservation checks. These are different model families, not interchangeable samples.

In the new no-demand case, LP rewards, trader emissions and reserve funding all remained zero. In the continuing-funded-demand sensitivity, five external LPs contributed 87,923.596754 USDC in total and earned 4,126.026214820589 FUSE across the bootstrap period; most of the 50M schedule expired unused. That case assumes 27M USDC of external trader funding over 180 days, so its large underwriting returns are not a demand forecast. With the same finite 300k trader bankroll and no inflows, increasing seed LP from 250k to 5M reduced the modeled share return from 78% to 3.9%; both consume the same finite customer loss pool. The deposit cap admits no external LPs in those baseline cases, rather than paying to attract idle TVL.

The active correlated-winner and withdrawal-run stresses produced **more than 99.99% peak-to-trough share drawdown** and left five providers' withdrawal requests pending, with 147 observed days of queue delay. All accepted payouts remained funded, but LP risk capital was almost exhausted. This is an economic failure, not evidence of a viable launch. A two-day queue and a capitalization gate on reserve transfers do not by themselves constrain cumulative losses from successive correlated trades. Daily/drawdown risk budgets and admission pauses need separate design and validation before external LP contract implementation is justified.

Economic results must be read alongside the funding assumptions. Accounting conservation does not establish sustainable demand, acceptable LP drawdown, withdrawal availability, token value or an optimal 50M allocation. Returns exclude unspecified operating costs. LP equity can approach total loss under correlated winners even while all payouts remain funded. A larger seed cannot create trading demand, and extra idle capital dilutes share returns. LP share NAV includes retained realized underwriting PnL; it is not all withdrawable cash. Token redemption proceeds are modeled as withdrawn savings, with no automatic reinvestment into trading or LP deposits.

## Rolling loss budgets, drawdown pauses and recovery

`scripts/lp_risk.py` and `scripts/simulate_lp_risk.py` extend the LP simulation with **admission controls applied before accepting new risk**. Existing positions settle at their accepted payout; a pause never cancels a winner or changes its terms. These controls are research policies and are not installed in the Go engine or Solidity modules by this work. The workspace also contains separate LP share contract work; this comparison does not execute those contracts or establish ERC-7540 compliance.

Reproduce the complete comparison:

```sh
cd /Volumes/dev/fuse
python3 scripts/simulate_lp_risk.py
python3 -m unittest discover -s scripts -p 'test_*.py' -v
```

For a smaller reproduction:

```sh
python3 scripts/simulate_lp_risk.py --quick --days 125 \
  --output .local/lp-risk-research/smoke
```

The default matrix has **168 trajectories: seven policies × eight environments × three matched seeds, each over 180 days**. Environments include finite funded wallets, steady external funding, forced three-day and ten-day winner clusters, repeated clusters at days 30–32/60–62/95–97, an oracle outage followed by a winner cluster, demand/funding collapse after the 90-day incentive period, and an explicit 20% external loss shock. Funding assumptions remain unchanged within each matched environment. The seeded per-trade latent outcome draws are unchanged across policies; admissions, later stages and LP/cash behavior can diverge as a result of the policy. These are counterfactual market paths, not paired realized returns on identical accepted trades.

The policies compare current admission, a 5% trailing-24-hour loss cap, that cap plus a 10% trailing-seven-day cap, a latched pause, a bounded-probe pause, combined controls, and tighter combined controls. Zero-valued caps disable that control. The standard pause triggers at 10% share-NAV drawdown, retains a prospective 20% hard drawdown floor, waits two days and reopens fully only after drawdown recovers to 5%. The tight alternative uses 5%/10%/2%, with 2.5%/5% loss budgets. This is a parameter comparison, not selection or approval of a launch policy.

Loss budgets conservatively consume **gross incremental LP payments to surviving positions**, excluding returned trader principal. Revenue from losing traders does not erase consumed budget, even when the net batch PnL is positive. Whole-batch worst-case incremental exposure is reserved before outcomes are known. Unused reservation is released when the batch settles. A 24-hour window expires individual settled debits after 86,400 seconds; it does not reset at midnight. Multi-day losses remain constrained after a daily allowance refreshes.

Both budget references and spent loss are normalized per share. The reference is the latest recorded settled NAV at or before the rolling window start, or inception NAV when history is shorter. Losses round upward and reference NAV downward at 1e36 fixed-point precision. Fair-NAV deposits/withdrawals scale dollar capacity and spent losses together; they cannot reset the fraction consumed, a pause or the historical NAV peak. A prospective hard floor limits new aggregate exposure so its worst accepted payout preserves the configured peak-to-trough NAV bound. It does not protect against a separately imposed external balance shock; such breaches are counted separately and prevent new underwriting below the floor.

A latched pause has no automatic recovery while trading is stopped. The probe alternative permits trading after the cooldown under a separate **0.25% trailing-24-hour gross-loss cap**, all normal loss limits and the original hard floor. It never resets the peak or past losses. Profitable probes can restore NAV and reopen the vault; persistent losses can consume the remaining headroom and leave it stopped. Fresh reconciliation remains mandatory. No governance reset, bailout or successful recovery is invented.

The report separates funded accepted payouts from economic outcomes: maximum share drawdown, accepted stages relative to current policy, risk rejections, fully reopened and unrecovered pause episodes, completed/pending withdrawal waits, overdue requests and retention after emissions stop. The LP cohort is owners holding at least 1 USDC of NAV at day 89; the same owners are observed at days 119 and 179. Invested capital includes pending shares. Unrequested ownership and remaining cohort equity are separately reported so a trapped or depleted position is not mistaken for voluntary retention. Absent cohorts or horizons have no estimated retention rate. A zero-overdue result with no external LP participation does not establish withdrawal reliability.

Default outputs are under `.local/lp-risk-research/`: `experiment.json` pins every policy, scenario, seed and source hash; `results.json` contains full daily trajectories and matched comparisons; `report.md` summarizes trade-offs. First-seed cluster and incentive-expiry JSONL logs include accepted settlements, reserved capacity, gross LP debits, loss-limit reasons, payouts and risk-mode transitions. Earlier LP reports and frozen pricing candidates are preserved. No public or local contract transactions are submitted by this workflow.

The retained full comparison is at `.local/lp-risk-research/full/`. All **168 trajectories × 180 days** conserved their USDC/FUSE/share ledgers and funded accepted payouts. All prospective underwriting drawdown floors held outside the explicitly external balance-shock environment. The **51 Python tests** passed, and a separate rerun of all 87 uncontrolled trajectories reproduced the earlier financial and outcome metrics exactly.

| Policy | Worst drawdown, ten-day cluster across three seeds | Median steady-market stages vs current |
|---|---:|---:|
| Current | 99.997% | 100.0% |
| 5% trailing-24h gross-loss budget | 39.123% | 11.3% |
| 5% 24h + 10% seven-day budgets | 11.314% | 2.2% |
| Pause + bounded probes | 13.831% | approximately 100% |
| Combined budgets + pause/probes | 10.912% | 2.2% |
| Tight combined | 6.029% | 1.2% |

The 24-hour cap alone did not bound cumulative drawdown across multiple losing days. Latched pauses recovered in none of the three ten-day-cluster paths; probe and combined policies reopened in all three within the modeled horizon. Recovery can take months, not merely the two-day cooldown. The combined policy avoided overdue exits in these paths but rejected most normal activity. In the first-seed incentive/demand-expiry case, its bootstrap-end cohort fell from 43 invested owners at day 89 to zero with at least 1 USDC invested at day 179. LP retention is therefore not established by preventing insolvency. The pause/probe alternative warrants further study as a different risk/throughput trade-off; no settings are promoted to an engine policy by this comparison.

Stage-volume ratios in failed stress cases require care: a protected vault may process several times the stages of a control that lost almost all capital and stopped. Use the steady-market column for the admission cost, alongside terminal modes, recovery time, queue completion, remaining cohort equity and external funding assumptions. External loss shocks still crossed configured floors in some paths and then blocked new underwriting; admission controls do not insure such losses.

## Faster LP NAV recovery research

`scripts/optimize_lp_recovery.py` searches for faster recovery of **the actual pre-cluster NAV peak**, separately from reopening trading at 5% drawdown. The simulation now records exact per-share NAV targets for every forced winner cluster, the first deficit and the first return to that target. Risk pause episodes also record when their original peak is recovered. An LP who withdraws during a drawdown crystallizes that loss: later recovery of remaining shares does not reimburse an exited investor.

The bounded search compares 24 policies: pause thresholds 7.5%/10%, cooldowns 6/24/48 hours, fixed 0.25%/1% trailing-24-hour gross-loss probes, and adaptive probes starting at 0.25% with maximum 1%/2%. Every candidate retains the same **20% prospective drawdown floor and 5% full-reopening threshold**. Earlier reopening thresholds, resetting historical NAV/losses, bailout contributions, higher FUSE prices and changed trader payout terms cannot improve the search score because none is permitted.

Adaptive probes double their budget only after three positive settled probe batches and at least 0.1% net NAV gain since the previous step. Any negative settled NAV change resets the budget to its initial level. The rule uses realized post-settlement/post-reserve NAV, never future observations or knowledge that a cluster has ended. Increasing a cap does not erase consumed rolling losses. The hard floor, freshness gate and complete settlement of previously accepted risk remain mandatory.

Training uses two explicitly declared seeds on steady funding, ten-day winner clusters and repeated clusters. The objective minimizes worst, then median, recovery time. Unfinished deficits receive a full-horizon penalty rather than disappearing from an average. Training constraints require every deficit to recover, no more than 20% drawdown, at least 80% of baseline steady-market stage admissions, zero overdue requests and funded accepted payouts. This is an exhaustive search within the stated finite grid, not convex optimization or a global optimum for tokenomics.

The two best training candidates and the original fixed-probe baseline are frozen in `selection.json` **before** held-out execution. Four separate seeds test the original environments plus thinner underwriting edge, lower trader funding and complete cessation of trading after losses. A source/input manifest and training hash pin the selection. Held-out results do not trigger reselection. The continued-funding scenarios retain their explicit 150k USDC/day customer-funding assumption; there is no new organic-demand evidence.

```sh
cd /Volumes/dev/fuse
python3 scripts/optimize_lp_recovery.py --workers 2
# Smaller end-to-end search/validation, with the same 180-day horizon:
python3 scripts/optimize_lp_recovery.py --quick \
  --output .local/lp-recovery-optimization/smoke
```

Default outputs are `.local/lp-recovery-optimization/experiment.json`, `training.json`, `selection.json`, `held-out.json` and `report.md`, plus first-held-out-seed ten-day-cluster logs. Validation retains full daily ledgers, recovery/censoring, drawdowns, throughput, withdrawal waits, investor PnL and retention. A low-demand or absent-demand case may remain unrecovered. No controller can create counterparty profit or make an external balance shock disappear. This remains simulation-only research, without Go/contract enforcement or production parameter approval.

The retained search at `.local/lp-recovery-optimization/full/` ran **144 training trajectories and 132 held-out trajectories**, all over 180 days. It selected an earlier **7.5% pause, six-hour cooldown and fixed 1% trailing-24-hour probe gross-loss budget**, retaining the 20% prospective underwriting floor and 5% reopening threshold. The 24-hour-cooldown alternative tied in training and produced identical held-out results; these cases do not establish a benefit from six hours specifically. The search preferred these fixed-budget policies to the adaptive candidates within this parameter grid. No candidate was reselected from validation outcomes.

| Held-out ten-day winner cluster seed | Selected policy: actual NAV recovery | Original probe baseline: actual NAV recovery |
|---|---:|---:|
| 20261126 | 55.92 days | 135.17 days |
| 20261127 | 44.17 days | 95.08 days |
| 20261128 | 42.00 days | 138.67 days |
| 20261129 | 52.83 days | Unrecovered at the 180-day horizon |

This improvement used greater recovery exposure: worst ten-day-cluster drawdown rose from **14.15% to 18.18%**. Steady-market admissions remained **97.0–100% of the baseline** across the four held-out seeds, and no overdue requests occurred in those comparisons. All simulated USDC/FUSE/share ledgers conserved and accepted payouts remained funded. The 58 Python tests passed, and nine retained uncontrolled/static-policy trajectories reproduced their earlier financial/outcome metrics exactly.

The boundary cases remain material. In the thinner-edge environment, only **2/4** selected-policy paths recovered within the horizon, with drawdown reaching **19.98%**; the baseline recovered 0/4. With trading stopped after the loss, neither policy recovered any of the four paths. The recovery ratios measure winner-cluster deficit episodes; 0/0 in environments without a winner cluster means no applicable cluster-recovery measurement, not absence of losses. External 20% balance shocks remain outside the prospective underwriting floor's guarantee. Faster recovery of remaining NAV is therefore conditional on continued funded activity and profitable future underwriting; it does not establish customer demand or reimburse exited LPs.

## Validation and remaining decisions

Use Foundry unit/fuzz/invariant tests, Go race tests, the local contract/backend E2E and the pinned HyperEVM testnet fork suite. `scripts/verify_formal.py` checks the existing 23 bounded bytecode properties and seven integer lemmas; it is not a proof of all new economics or arbitrary transaction histories. New expiry, ramp, activation, snapshot and final-supply behavior has dedicated tests.

Immutable existing local deployments retain their artifact pins; new deployments receive the revised contracts. Old journals remain replayable. Restarting a local backend does not upgrade its deployed contracts.

Still unresolved by design: beneficiaries/disposition of the remaining locked treasury (350M after the LP amendment below); an approved final-residual policy (guarded by disabling the final burn); empirical long-regime pricing and demand data; approved activity rate, emission curve, reserve cap, haircut and launch timing; production key/governance review and independent security review. No transactions have been sent to public HyperEVM by these workflows. Local fork execution does not establish public-network inclusion or finality.

## LP contract and backend implementation

The [LP participation implementation](LP_PARTICIPATION.md) now adds real share, exit and incentive contracts plus backend cash-liability reconciliation. This supersedes the earlier research section's pending contract-implementation status. It does not change the frozen experiment inputs or reinterpret past runs as contract tests. Older 600M/400M allocation descriptions above record the pre-amendment design; **new deployments use 600M trader / 50M LP / 350M treasury escrows**, with fixed 1B genesis supply and all escrows in the backing denominator.

`LPShareVault` implements synchronous ERC-4626 deposits and FIFO ERC-7540 redemption requests, nontransferable shares, 48-hour minimum waits, fresh zero-exposure NAV, a 2C fulfillment floor, operators and pull claims. A settlement-created atomic pause window prevents entry/exit against an old checkpoint while new guarantees are being accepted. The deposit cap uses dual-attested eligible demand and a governance hard cap/utilization target. Phase advancement is explicit Protocol → Whitelisted → Public; deployment stays paused in Protocol with no campaign start.

Whitelist advancement permanently enables contribution-adjusted per-share loss recovery and capitalization before a maximum 35% reserve fee. Protected retained profits raise the high-water mark and cannot be retroactively charged. Accrued fees and funded exits are excluded from usable equity and underwriting capacity. Fees move into token backing only with a separate dual-signed reserve authorization. Protocol-only mode preserves legacy gross-profit telemetry and allowance behavior until advancement.

`LPIncentiveDistributor` binds the 50M LP escrow to one 90-day linearly declining campaign, 30-day vesting, actual onchain account capital-time and dual-attested accepted liability-time. Protocol/queued capital cannot mine; zero demand pays zero and unused daily slots expire. The local backend pins both new module artifacts, exposes confirmed LP disclosures and provides serialized liquidity-window and capacity operations. No automatic incentive publication or activation is enabled.

Validation includes dedicated lifecycle/economic tests, randomized external-LP accounting sequences, Solidity/Go signature vectors, a real isolated Anvil/PostgreSQL/backend deposit-to-exit journey, and three additional bounded bytecode checks plus an integer share-dilution lemma. [Formal scope](FORMAL_VERIFICATION.md) remains bounded. The research loss-budget/probe controls are still simulation policies; they have not been promoted into engine admission rules. Accounting correctness does not resolve the simulated correlated-winner drawdowns, withdrawal delays, voluntary demand, production policy choices or independent launch assessment.

## Contract-matched recorded economics replay

The [recorded LP replay](CONTRACT_LP_REPLAY.md) now connects repository oracle traces and trader decisions to the actual Go reducer and an integer model of current LP contract economics. It fixes the research/contract distinction explicitly: this path uses linear 90-day LP budgets, ERC-4626 virtual rounding, accrued reserve-fee liabilities, separate exit fulfillment/payment, deadline-bound publication and epoch-end vesting. Earlier Bernoulli/half-life recovery research remains unchanged and does not become production validation through this addition.

Run `python3 scripts/replay_lp_economics.py` for two chronological 300-wallet captures and nested 300/150/30/0 participation cases, with explicit cost sensitivities, source/binary hashes, funding reconciliation and replayable Go audit logs. Initial 250k LP capital includes an assumed 50k external allocation. No future market prices or organic customers are generated. Day-3 exit payment and day-31 reward claims are a zero-trading mechanical runoff, not a prediction of LP recovery. Current contract states and all 90 daily emission caps are compared against generated model expectations in Foundry. Future local runs retain canonical native execution fees for coordinator operations; direct wallet/setup and infrastructure costs still require separate measurement.

The retained run is `.local/contract-lp-replay/full/report.md`. Both original journals reproduced their complete final states across **14,118 commands**. All eight participation cases preserved selected recorded entries, immutable economic terms and outcomes, with zero mismatches, conserved cash/shares/LP reward escrow, funded exit claims and zero terminal trading exposure. All eight audit hash chains were checked; the first full-participation audit also re-executed all **5,823** records through the Go bridge.

At 300 traders, LP trading profit after accrued reserve fees was **9,954.549577 USDC** in the development recording and **5,487.683195 USDC** in the retrospective holdout, before assumed operating/gas costs. At 30 traders, the holdout instead lost **706.554153 USDC** after fees. Its external LP cohort received **49,858.689150 USDC** against the assumed 50,000 contribution. A small fee earned before subsequent losses remains accrued under the current contract; the model does not invent fee clawbacks. Zero traders produced zero trading profit and LP emissions; allocated operating costs made the economic result negative.

The eight cases share only **41 distinct healthy nonoverlapping 30-second reference windows**, with 18 surviving the frozen 1.17 bps corridor. They do not expand the original pricing evidence or validate multi-day recovery. The maximum full-participation NAV drawdowns were 2.02% and 1.80%, below the synthetic recovery policy's pause trigger. Validation passed 73 Python tests, 87 Foundry tests, Go race/vet checks and the actual Anvil/PostgreSQL/HTTP E2E, including gas receipt export (605 journal events, 82 canonical chain events, nine checkpoints). Public execution remains disabled.
