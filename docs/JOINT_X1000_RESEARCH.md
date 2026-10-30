# Joint volatility, oracle activity and liquidity: X1000 revision

This revision fits native thirty-second X1000 corridor risk from the combined state of volatility, oracle price-change activity and measured book liquidity. ETH and HYPE are fitted separately. The target trader survival is 0.095%. The replay scores September 1–10, 2026 UTC, with weekday/weekend comparisons, and fourteen earlier monthly out-of-sample dates. All outcomes belong to repeatedly inspected historical development.

The first declared primary is `joint_local`; `joint_global` and `joint_raw` are fixed ablations. After inspecting that replay, a separate delayed-feedback revision was declared with `joint_online_full` primary and a flat-only ablation. Both packets preserve their declarations. The report does not silently select a different asset-specific winner from later results. Live pricing and the ongoing fresh collector remain unchanged.

## Consecutive results

Availability divides resolved accepted quotes by the same clean oracle paths with fresh strictly prior books. Missing books are retained in the secondary all-clean denominator. A zero-win quote set is reported as observed zero, not as a proven risk-free price.

The delayed-feedback primary moves both assets closer to the target, with an availability cost. The following pooled comparison uses the original native calibrated model as the baseline; it is not a fresh validation sample.

| Asset | Previous rate / availability | Delayed-feedback rate / availability | Wins / quotes after feedback |
| --- | ---: | ---: | ---: |
| ETH | 0.409% / 20.608% | 0.084% / 15.080% | 3 / 3,579 |
| HYPE | 0.465% / 13.607% | 0.169% / 12.490% | 5 / 2,964 |

The ETH global-calibration ablation offers a stronger availability tradeoff in this development sample: 0.084% survival at 20.051% availability. This does not retrospectively change the declared primary. HYPE delayed-feedback survival remains 1.78 times target. No tested rule meets all existing evidence and availability screens.

### ETH

| Formula | Weekday wins / quotes (rate) | Weekday availability | Weekend wins / quotes (rate) | Weekend availability |
| --- | ---: | ---: | ---: | ---: |
| Previous native calibration | 17 / 4,441 (0.383%) | 23.469% | 3 / 450 (0.667%) | 9.354% |
| Previous mild volatility gate | 17 / 4,366 (0.389%) | 23.072% | 3 / 443 (0.677%) | 9.208% |
| Previous conditional calibration | 1 / 923 (0.108%) | 4.878% | 0 / 153 (0.000%) | 3.180% |
| Joint model, raw budget | 0 / 1,383 (0.000%) | 7.309% | 0 / 26 (0.000%) | 0.540% |
| Joint model, global calibration | 4 / 4,521 (0.088%) | 23.892% | 0 / 238 (0.000%) | 4.947% |
| Joint model, local risk calibration (declared primary) | 11 / 5,416 (0.203%) | 28.621% | 0 / 305 (0.000%) | 6.340% |
| Joint model, delayed flat feedback | 2 / 3,552 (0.056%) | 18.771% | 0 / 27 (0.000%) | 0.561% |
| Joint model, delayed flat and tail feedback (second declared primary) | 3 / 3,552 (0.084%) | 18.771% | 0 / 27 (0.000%) | 0.561% |

### HYPE

| Formula | Weekday wins / quotes (rate) | Weekday availability | Weekend wins / quotes (rate) | Weekend availability |
| --- | ---: | ---: | ---: | ---: |
| Previous native calibration | 15 / 3,031 (0.495%) | 16.024% | 0 / 198 (0.000%) | 4.111% |
| Previous mild volatility gate | 11 / 2,710 (0.406%) | 14.327% | 0 / 196 (0.000%) | 4.070% |
| Previous conditional calibration | 7 / 1,111 (0.630%) | 5.874% | 0 / 60 (0.000%) | 1.246% |
| Joint model, raw budget | 3 / 1,629 (0.184%) | 8.612% | 0 / 105 (0.000%) | 2.180% |
| Joint model, global calibration | 15 / 2,651 (0.566%) | 14.015% | 0 / 105 (0.000%) | 2.180% |
| Joint model, local risk calibration (declared primary) | 10 / 1,651 (0.606%) | 8.729% | 0 / 253 (0.000%) | 5.253% |
| Joint model, delayed flat feedback | 5 / 2,727 (0.183%) | 14.417% | 0 / 237 (0.000%) | 4.921% |
| Joint model, delayed flat and tail feedback (second declared primary) | 5 / 2,727 (0.183%) | 14.417% | 0 / 237 (0.000%) | 4.921% |

## Pricing versus availability

| Asset | Formula | Pooled wins / quotes (rate) | Total availability | Availability versus previous native | Absolute target error | Worst date availability | Target expected wins |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| ETH | Previous native calibration | 20 / 4,891 (0.409%) | 20.608% | 100.000% | 0.314 pp | 1.121% | 4.646 |
| ETH | Previous mild volatility gate | 20 / 4,809 (0.416%) | 20.262% | 98.323% | 0.321 pp | 1.121% | 4.569 |
| ETH | Previous conditional calibration | 1 / 1,076 (0.093%) | 4.534% | 22.000% | 0.002 pp | 0.042% | 1.022 |
| ETH | Joint model, raw budget | 0 / 1,409 (0.000%) | 5.937% | 28.808% | 0.095 pp | 0.293% | 1.339 |
| ETH | Joint model, global calibration | 4 / 4,759 (0.084%) | 20.051% | 97.301% | 0.011 pp | 2.386% | 4.521 |
| ETH | Joint model, local risk calibration (declared primary) | 11 / 5,721 (0.192%) | 24.105% | 116.970% | 0.097 pp | 3.600% | 5.435 |
| ETH | Joint model, delayed flat feedback | 2 / 3,579 (0.056%) | 15.080% | 73.175% | 0.039 pp | 0.460% | 3.400 |
| ETH | Joint model, delayed flat and tail feedback (second declared primary) | 3 / 3,579 (0.084%) | 15.080% | 73.175% | 0.011 pp | 0.460% | 3.400 |
| HYPE | Previous native calibration | 15 / 3,229 (0.465%) | 13.607% | 100.000% | 0.370 pp | 0.545% | 3.068 |
| HYPE | Previous mild volatility gate | 11 / 2,906 (0.379%) | 12.246% | 89.997% | 0.284 pp | 0.545% | 2.761 |
| HYPE | Previous conditional calibration | 7 / 1,171 (0.598%) | 4.934% | 36.265% | 0.503 pp | 0.000% | 1.112 |
| HYPE | Joint model, raw budget | 3 / 1,734 (0.173%) | 7.307% | 53.701% | 0.078 pp | 1.007% | 1.647 |
| HYPE | Joint model, global calibration | 15 / 2,756 (0.544%) | 11.614% | 85.352% | 0.449 pp | 1.007% | 2.618 |
| HYPE | Joint model, local risk calibration (declared primary) | 10 / 1,904 (0.525%) | 8.023% | 58.966% | 0.430 pp | 0.337% | 1.809 |
| HYPE | Joint model, delayed flat feedback | 5 / 2,964 (0.169%) | 12.490% | 91.793% | 0.074 pp | 0.168% | 2.816 |
| HYPE | Joint model, delayed flat and tail feedback (second declared primary) | 5 / 2,964 (0.169%) | 12.490% | 91.793% | 0.074 pp | 0.168% | 2.816 |

Availability versus previous native is a retention ratio: 100% means the same total quote availability. Target error is the absolute difference in probability, shown in percentage points. Neither is statistical confidence. No entry is forced open to meet an availability objective.

## Formula changes

The prior model already included individual volatility/activity/liquidity inputs. The new feature map adds three idle-age hinges, two oracle-change-count hinges and nine joint interactions. These include recent volatility by activity, activity by spread and minimum-side top-five depth, idle by those liquidity measures, and idle by absolute book imbalance. Calendar and fresh market/oracle context remain available. Feature construction reads only pre-entry observations; current survival and future data validity are excluded.

The zero-motion logistic head uses ridge 0.0003. Its fitted probability ranks each entry into four groups, with quartile boundaries computed solely from date-weighted earlier training predictions. This rank combines the three signal families; it does not require closing an entire volatility quartile. The same fitted feature map conditions the positive-movement tail.

The old single lognormal positive tail is replaced by a log-logistic tail. Fit a ridge-0.01 location model to positive log required native width divided by preceding five-minute volatility. Set logistic residual scale to the weighted residual standard deviation times sqrt(3)/pi, with minimum 0.08. For native width `w > 0`, the modeled survival is `p0 + (1 − p0) × sigmoid((log(w / slow_vol_ppb) − μ) / s)`. This is a parametric tail assumption, not twenty empirical rare-tail observations.

Invert the positive component at `(budget − p0) / (1 − p0)`, round width downward to integer ppb, and retain the 50,000-ppm maximum. The model refuses an entry when predicted flat risk or minimum-representable-width risk exceeds its budget. Corridors have a strictly positive integer price delta; touching either barrier loses. The flat-oracle veto, five-minute history and strictly prior book freshness remain required. A stale book or unknown idle-age lower bound cannot create a quote.

Each daily origin fits from the last ten observed earlier admissible dates of that asset, with equal date mass. At least 200 total paths and 200 positive paths across five earlier dates are required. These are observed sample dates, not necessarily consecutive calendar days: early warmup includes monthly history. Training labels enter only if expiry plus thirty seconds is strictly before the daily origin.

## Joint calibration and controls

All clean admissible out-of-sample outcomes enter future calibration, including previously refused paths. Native quantization is included in each reference’s admission and win threshold. At each origin, only earlier-date references with expiry plus thirty seconds strictly before UTC midnight are permitted. There is no within-day outcome update.

Evaluate 81 predeclared model budgets: `0.00095 × 2^(k/8)` for integer k from −48 through 32. Estimate wins divided by offers at each budget, date-balanced over the last ten matching observed reference dates, with identity prior mass 32. Require at least 200 offered references across three dates. Choose the highest passing budget whose smoothed conditional estimate is at most 0.00095. This is sparse-reference model calibration, not a confidence bound; 200 references and prior mass 32 do not establish a 0.095% tail.

`joint_raw` uses the raw target budget. `joint_global` tries the entry’s weekday/weekend reference group, then global, then recorded raw-identity fallback. `joint_local` first tries weekday/weekend plus risk-rank group, then that risk group across calendars, then the calendar group, global, and identity. Supported local groups can preserve useful states that a single hard volatility cutoff would remove. They can also overfit sparse tail references; the ablations expose that tradeoff.

This iteration changes interactions, fit recency, tail shape and calibration together. Its comparisons cannot attribute an improvement solely to liquidity or establish why weekends differ. The three new ablations isolate calibration within the same new fitted model, not every bundled modeling choice.

## Daily primary and global-calibration quotes

| UTC date | ETH primary quotes / wins | ETH global quotes / wins | HYPE primary quotes / wins | HYPE global quotes / wins |
| --- | ---: | ---: | ---: | ---: |
| 2026-09-01 | 192 / 0 | 180 / 0 | 1,192 / 8 | 1,294 / 8 |
| 2026-09-02 | 870 / 1 | 870 / 1 | 225 / 1 | 398 / 5 |
| 2026-09-03 | 724 / 3 | 796 / 1 | 91 / 1 | 200 / 2 |
| 2026-09-04 | 637 / 0 | 552 / 0 | 91 / 0 | 218 / 0 |
| 2026-09-05 | 86 / 0 | 57 / 0 | 28 / 0 | 24 / 0 |
| 2026-09-06 | 219 / 0 | 181 / 0 | 225 / 0 | 81 / 0 |
| 2026-09-07 | 716 / 1 | 563 / 1 | 14 / 0 | 117 / 0 |
| 2026-09-08 | 875 / 2 | 519 / 0 | 15 / 0 | 126 / 0 |
| 2026-09-09 | 816 / 4 | 616 / 1 | 8 / 0 | 141 / 0 |
| 2026-09-10 | 586 / 0 | 425 / 0 | 15 / 0 | 157 / 0 |

## Screens and flat-path exposure

| Asset | Formula | Flat-path wins | Gross LP per stake | Identity-fallback offers | Screen failures |
| --- | --- | ---: | ---: | ---: | --- |
| ETH | Joint model, raw budget | 0 | 100.000% | 1,409 | insufficient_quote_availability, survival_outside_reference_band, insufficient_rare_event_evidence |
| ETH | Joint model, global calibration | 1 | 15.949% | 0 | insufficient_quote_availability, insufficient_rare_event_evidence |
| ETH | Joint model, local risk calibration (declared primary) | 3 | -92.274% | 0 | insufficient_quote_availability, survival_outside_reference_band, negative_zero_cost_gross, insufficient_rare_event_evidence |
| HYPE | Joint model, raw budget | 1 | -73.010% | 1,734 | insufficient_quote_availability, survival_outside_reference_band, negative_zero_cost_gross, insufficient_rare_event_evidence |
| HYPE | Joint model, global calibration | 2 | -444.267% | 0 | insufficient_quote_availability, survival_outside_reference_band, negative_zero_cost_gross, insufficient_rare_event_evidence |
| HYPE | Joint model, local risk calibration (declared primary) | 2 | -425.210% | 0 | insufficient_quote_availability, survival_outside_reference_band, negative_zero_cost_gross, insufficient_rare_event_evidence |

## Delayed within-day revision

The first HYPE local calibration misses the goal: 0.525% pooled survival at 8.023% availability, with eight of its ten wins on the first trial date. Older low-risk monthly reference groups initially allow wider budgets, then later observations can suppress most quotes. The second revision reuses the frozen joint models, returns to the raw 0.00095 mixture budget, and corrects the component probabilities using only recently matured observations. It does not refit coefficients or use the current path.

Flat correction multiplies raw zero-motion odds by `(1 + recent observed zero paths) / (1 + sum recent raw p0)`, bounded from 0.1 to 10 and enabled after sixty matured references. All healthy admissible outcomes contribute, even when no quote was offered. This can correct overestimated flat risk while retaining the explicit pre-entry flat veto.

The full correction also evaluates the raw positive-component CDF at each observed native required width. Among positive paths, multiply positive-CDF odds by `(1 + scores at or below 0.01) / (1 + 0.01 × positive count)`, bounded from 0.25 to 4 and enabled after one hundred positive references. The fixed one-percent anchor supplies more observations than the X1000 extreme tail. The equivalent log-logistic location shift is `mu_corrected = mu − scale × log(tail_factor)`. Extrapolation from that anchor remains a modeling assumption.

Memory retains the last 480 matured valid admissible references whose expiry is within six hours. References enter only when expiry plus thirty seconds is strictly earlier than entry. State carries across consecutive days and ages out monthly gaps. Raw forecasts at each reference entry remain frozen; feedback does not compare labels with retrospectively corrected probabilities. Invalid/disconnected paths never count as zero wins. The one-event prior prevents a zero probability estimate, but supplies no rare-event confidence guarantee.

The static second-packet control exactly reproduces every parent joint_raw quote. The independent auditor uses offline indexed maturity slices to reconstruct the forward pending/recent queues at every entry. This checks the principal lookahead risk with a different data flow.

| Asset / variant | Wins / quotes (rate) | Availability | Flat-path wins | Offers with active feedback | Screen failures |
| --- | ---: | ---: | ---: | ---: | --- |
| ETH / joint_online_flat | 2 / 3,579 (0.056%) | 15.080% | 1 | 3,578 | insufficient_quote_availability, survival_outside_reference_band, insufficient_rare_event_evidence |
| ETH / joint_online_full | 3 / 3,579 (0.084%) | 15.080% | 1 | 3,578 | insufficient_quote_availability, insufficient_rare_event_evidence |
| HYPE / joint_online_flat | 5 / 2,964 (0.169%) | 12.490% | 2 | 2,954 | insufficient_quote_availability, survival_outside_reference_band, negative_zero_cost_gross, insufficient_rare_event_evidence |
| HYPE / joint_online_full | 5 / 2,964 (0.169%) | 12.490% | 2 | 2,954 | insufficient_quote_availability, survival_outside_reference_band, negative_zero_cost_gross, insufficient_rare_event_evidence |

| UTC date | ETH full feedback quotes / wins | HYPE full feedback quotes / wins |
| --- | ---: | ---: |
| 2026-09-01 | 425 / 0 | 636 / 0 |
| 2026-09-02 | 727 / 2 | 69 / 1 |
| 2026-09-03 | 646 / 1 | 392 / 3 |
| 2026-09-04 | 704 / 0 | 230 / 0 |
| 2026-09-05 | 11 / 0 | 4 / 0 |
| 2026-09-06 | 16 / 0 | 233 / 0 |
| 2026-09-07 | 197 / 0 | 547 / 1 |
| 2026-09-08 | 442 / 0 | 119 / 0 |
| 2026-09-09 | 155 / 0 | 207 / 0 |
| 2026-09-10 | 256 / 0 | 527 / 0 |

The unchanged descriptive screens require a nonempty quote set every date, at least 85% availability every date, pooled survival within 75–125% of target, nonnegative zero-cost gross, and at least twenty target-expected evaluated wins. X1000 needs at least 21,053 accepted quotes to reach that last count reference. Sparse parametric or local calibration support does not waive it. Quotes are measured across all eligible entries; no closed-period denominator adjustment is used.

LP gross assumes one stake per resolved accepted quote and total payout including the returned stake: `(quotes − 1000 × wins) / quotes`. It excludes fees, hedging, funding, latency, capacity and correlated losses. Even near-target sample survival or positive sample gross does not establish future calibration or net profitability.

## Earlier monthly results

These fourteen first-of-month out-of-sample dates span July 2025–August 2026, after six monthly warmup dates. They are reported separately and do not select the primary.

| Asset | Formula | Wins / quotes (rate) | Availability | Worst date availability |
| --- | --- | ---: | ---: | ---: |
| ETH | Previous native calibration | 9 / 5,672 (0.159%) | 14.786% | 0.036% |
| ETH | Previous mild volatility gate | 7 / 5,608 (0.125%) | 14.619% | 0.036% |
| ETH | Previous conditional calibration | 10 / 6,788 (0.147%) | 17.696% | 0.289% |
| ETH | Joint model, raw budget | 1 / 6,328 (0.016%) | 16.496% | 0.361% |
| ETH | Joint model, global calibration | 27 / 12,433 (0.217%) | 32.411% | 1.770% |
| ETH | Joint model, local risk calibration (declared primary) | 28 / 10,955 (0.256%) | 28.558% | 1.048% |
| ETH | Joint model, delayed flat feedback | 1 / 9,453 (0.011%) | 24.643% | 0.036% |
| ETH | Joint model, delayed flat and tail feedback (second declared primary) | 1 / 9,453 (0.011%) | 24.643% | 0.036% |
| HYPE | Previous native calibration | 32 / 18,070 (0.177%) | 47.125% | 12.062% |
| HYPE | Previous mild volatility gate | 19 / 15,424 (0.123%) | 40.224% | 9.960% |
| HYPE | Previous conditional calibration | 22 / 18,093 (0.122%) | 47.185% | 16.601% |
| HYPE | Joint model, raw budget | 8 / 20,566 (0.039%) | 53.634% | 18.057% |
| HYPE | Joint model, global calibration | 40 / 26,750 (0.150%) | 69.761% | 32.109% |
| HYPE | Joint model, local risk calibration (declared primary) | 53 / 27,211 (0.195%) | 70.964% | 32.109% |
| HYPE | Joint model, delayed flat feedback | 13 / 23,407 (0.056%) | 61.043% | 17.848% |
| HYPE | Joint model, delayed flat and tail feedback (second declared primary) | 14 / 23,407 (0.060%) | 61.043% | 17.848% |

## All clean oracle paths

Missing books remain in these secondary denominators and are refused. The complete packet retains every daily and calendar summary for both cohorts.

| Asset | Formula | Weekday availability | Weekend availability |
| --- | --- | ---: | ---: |
| ETH | Joint model, raw budget | 6.397% | 0.473% |
| ETH | Joint model, global calibration | 20.911% | 4.326% |
| ETH | Joint model, local risk calibration (declared primary) | 25.051% | 5.544% |
| ETH | Joint model, delayed flat feedback | 16.429% | 0.491% |
| ETH | Joint model, delayed flat and tail feedback (second declared primary) | 16.429% | 0.491% |
| HYPE | Joint model, raw budget | 7.534% | 1.909% |
| HYPE | Joint model, global calibration | 12.261% | 1.909% |
| HYPE | Joint model, local risk calibration (declared primary) | 7.636% | 4.600% |
| HYPE | Joint model, delayed flat feedback | 12.613% | 4.309% |
| HYPE | Joint model, delayed flat and tail feedback (second declared primary) | 12.613% | 4.309% |

## Verification and evidence limits

The independent audit refitted 48 earlier-only joint models, reconstructed every calendar/risk calibration candidate, replayed 402,915 decisions, and reconciled all daily/calendar/cohort metrics. Source, origin, trace and input hashes match. Forty-nine regression tests pass across the research stack. Seven new tests cover joint feature/outcome isolation, native positive width and touch settlement, stale/flat/missing vetoes, date and asset isolation, last-ten-date fitting, calibration maturity/group fallback, complete export/replay and tamper rejection.

September provides eight weekday dates and only two weekend dates. These repeatedly inspected outcomes are development evidence, not a fresh holdout or proof of a safe operating regime. A zero-win weekend or a point estimate near target can be uninformative at the available quote count. The frozen formula must be evaluated on new data before any promotion. Neither live pricing nor the ongoing fresh recorder is modified.

Research packet: `/Volumes/dev/fuse/.local/adaptive-corridor/20261029-joint-x1000-v1`. Research SHA-256: `ec38c161a74e51832bad52577ad5fa26d6deb8dbdfb336b54fef747b5cfa8676`. Audit SHA-256: `15ad17957e10dd8f1de6616eafa7dfd775b9d90afbb3dc89a986e2b9a1cc1558`. Volatility comparison packet: `/Volumes/dev/fuse/.local/adaptive-corridor/20261029-volatility-open-gate-v1`, research SHA-256 `631950e1e40a592d6238e125456879eef802a7f8dbc7c1e2bf12f81f45d49f2d` and audit SHA-256 `bd3d1106cfee59abbf739895c28774d3914ce09a07316443df5715ca8ff851ce`. Complete imported source snapshots, per-origin models/calibration grids and all accepted, refused and unresolved decisions are retained.

```sh
PYTHONPATH=scripts OPENBLAS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 OMP_NUM_THREADS=1 python3 -B -m unittest scripts.test_historical_liquidity scripts.test_trial_liquidity scripts.test_trial_payout scripts.test_flat_aware_payout scripts.test_flat_risk_overlay scripts.test_active_tail_payout scripts.test_conditional_tail_payout scripts.test_volatility_open_gate scripts.test_joint_x1000 scripts.test_online_joint_x1000
python3 -B scripts/research_joint_x1000.py --declare --active .local/adaptive-corridor/20261029-active-tail-payout-v1 --conditional .local/adaptive-corridor/20261029-conditional-tail-payout-v1 --output .local/adaptive-corridor/NEW-JOINT-X1000
OPENBLAS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 OMP_NUM_THREADS=1 python3 -B scripts/research_joint_x1000.py --output .local/adaptive-corridor/NEW-JOINT-X1000
OPENBLAS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 OMP_NUM_THREADS=1 python3 -B scripts/research_joint_x1000.py --audit --output .local/adaptive-corridor/NEW-JOINT-X1000
python3 -B scripts/report_joint_x1000.py --research .local/adaptive-corridor/NEW-JOINT-X1000 --volatility .local/adaptive-corridor/20261029-volatility-open-gate-v1 --output docs/JOINT_X1000_RESEARCH.md
```

Online packet: `/Volumes/dev/fuse/.local/adaptive-corridor/20261029-online-joint-x1000-v1`. Its independent audit replays 402,915 additional decisions, verifies static-parent reproduction and checks every causal feedback state against offline maturity slices. Research SHA-256: `fca31e4641fbf97ae20221680d7da2f13e6a67a4df5d55b7192363878eba08fc`. Audit SHA-256: `dcc21557c3669a287fd6b4f27b202c11bcbefee86886819126a95bc7a889464f`. Four additional tests cover strict maturity, invalid paths, gap expiry, bounded memory, independent state reconstruction, future-label invariance, corrected width direction and complete static/export/audit/tamper rejection.

```sh
python3 -B scripts/research_online_joint_x1000.py --declare --parent .local/adaptive-corridor/NEW-JOINT-X1000 --output .local/adaptive-corridor/NEW-ONLINE-JOINT-X1000
OPENBLAS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 OMP_NUM_THREADS=1 python3 -B scripts/research_online_joint_x1000.py --output .local/adaptive-corridor/NEW-ONLINE-JOINT-X1000
OPENBLAS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 OMP_NUM_THREADS=1 python3 -B scripts/research_online_joint_x1000.py --audit --output .local/adaptive-corridor/NEW-ONLINE-JOINT-X1000
python3 -B scripts/report_joint_x1000.py --research .local/adaptive-corridor/NEW-JOINT-X1000 --online .local/adaptive-corridor/NEW-ONLINE-JOINT-X1000 --volatility .local/adaptive-corridor/20261029-volatility-open-gate-v1 --output docs/JOINT_X1000_RESEARCH.md
```
