# Active-state and conditional-tail ETH/HYPE corridor revision

This development revision restores positive native-width X1000 quotes and recalibrates survival on the paths that a budget would actually offer. Separate asset fits, the explicit pre-entry flat-oracle veto, strict barrier settlement and common availability denominators are retained. The daily replay covers September 1–10, 2026 UTC; fourteen earlier monthly dates are reported separately. These are repeatedly inspected historical outcomes, not a fresh holdout.

The primary declared candidate is `conditional_recent`. The full-history conditional version is an ablation, not an outcome-selected replacement. No policy passes all existing availability, calibration and evidence screens. The live engine and ongoing fresh collector were not changed.

The recent primary revision misses the HYPE objective: weekday X100 survival is 1.875% versus the previous overlay’s 1.799%, while availability falls from 59.640% to 32.429%. It should not replace the previous rule. X1000 quotes return, but HYPE still has an excessive observed win rate, and one weekend date has no HYPE X1000 quotes. The first marginal-calibration attempt offers more X1000 quotes but is also overpriced.

## Formula and causal calibration

The previous empirical hurdle was too restrictive for X1000. The new models fit only states eligible to quote: a healthy five-minute feature history, a fresh strictly prior book, known idle age below thirty seconds, and at least one price change in the preceding thirty seconds. The blanket X1000 four-change/three-second recovery rule is replaced by learned risk. The flat veto remains. Models for ETH and HYPE are fitted independently; neither reuses BTC coefficients.

Two date-weighted logistic heads estimate zero-motion and one-ppm survival from calendar/activity features and six measured liquidity inputs. A separate ridge regression fits the logarithm of positive required width, normalized by preceding five-minute volatility, with a Gaussian residual. Positive-tail fits require 200 paths across five earlier dates. This lognormal tail is an extrapolation assumption; it does not manufacture twenty empirical rare-tail observations. The empirical comparator retains that original support gate.

For width `w > 0`, the native model estimates `F(w) = p0 + (1 − p0) Φ((log(w / slow_vol_ppb) − μ) / σ)`. At budget `b`, invert the positive component at `(b − p0) / (1 − p0)`, round width downward to integer ppb and retain the 50,000-ppm maximum. Refuse if a strictly positive representable barrier already exceeds budget. Settlement uses the actual integer price delta; touching loses. Native ppb precision allows positive corridors below the old one-ppm floor.

The first calibration attempt inverted the marginal CDF of scores over all admissible paths. It restored many X1000 quotes but worsened HYPE weekday pricing. Its denominator included states that the resulting budget would refuse. The correction estimates historical wins divided by historical offers at each candidate budget, with native minimum/maximum width and quantization included. Refused paths remain available to teach future budgets, but do not dilute the conditional survival estimate.

The two conditional variants examine 81 fixed budgets: `(0.95 / M) × 2^(k/8)` for integer `k = −48 … 32`. Dates have equal mass. The historical conditional rate is shrunk toward the candidate budget with identity prior mass 32. Choose the largest budget whose estimate does not exceed `0.95 / M`, requiring 200 offered references across three dates. These are fit-support conditions, not rare-event confidence. If the matching weekday/weekend calibration is unsupported, use global history; if that is unsupported, retain the raw model budget and record identity fallback. A failed calibration does not silently count as a supported estimate.

The recent variant uses the last three observed matching calendar dates at X100 and the last ten at X1000; the full-history variant retains all earlier reference dates. These are observed dates, so the early fallback can still include nonconsecutive monthly history. The shorter X100 window is intended to track regime changes; the longer X1000 window retains more sparse-tail observations. All thresholds and variants were frozen before their replay.

Daily model fits use only strictly earlier matched paths whose expiry plus thirty seconds precedes the origin. Calibration uses earlier out-of-sample forecasts and all matured admissible outcomes, including previously refused quotes; no current-date labels enter. Calibration is frozen at UTC midnight. Missing or disconnected paths are censored, not treated as flat wins.

## Consecutive weekday and weekend results

Trader survival targets are 0.950% at X100 and 0.095% at X1000. Availability is resolved accepted quotes divided by the same clean oracle paths with fresh pre-entry books. Eight weekday dates and two weekend dates are included. Empty quote sets have no estimated win rate.

### ETH

| Payout | Formula | Weekday wins / quotes (rate) | Weekday availability | Weekend wins / quotes (rate) | Weekend availability |
| --- | --- | ---: | ---: | ---: | ---: |
| X100 | Previous conservative overlay | 13 / 5,712 (0.228%) | 30.185% | 1 / 325 (0.308%) | 6.755% |
| X100 | Active-state empirical control | 58 / 9,312 (0.623%) | 49.210% | 11 / 1,198 (0.918%) | 24.901% |
| X100 | Native parametric, raw budget | 130 / 9,544 (1.362%) | 50.436% | 27 / 1,243 (2.172%) | 25.837% |
| X100 | Marginal CDF calibration | 244 / 12,114 (2.014%) | 64.017% | 39 / 1,554 (2.510%) | 32.301% |
| X100 | Offer-conditional, full history | 102 / 8,776 (1.162%) | 46.377% | 7 / 760 (0.921%) | 15.797% |
| X100 | Offer-conditional, recent history | 131 / 9,811 (1.335%) | 51.847% | 5 / 721 (0.693%) | 14.986% |
| X1000 | Previous conservative overlay | 0 / 0 (—) | 0.000% | 0 / 0 (—) | 0.000% |
| X1000 | Active-state empirical control | 0 / 218 (0.000%) | 1.152% | 0 / 5 (0.000%) | 0.104% |
| X1000 | Native parametric, raw budget | 0 / 481 (0.000%) | 2.542% | 0 / 26 (0.000%) | 0.540% |
| X1000 | Marginal CDF calibration | 17 / 4,441 (0.383%) | 23.469% | 3 / 450 (0.667%) | 9.354% |
| X1000 | Offer-conditional, full history | 3 / 1,575 (0.190%) | 8.323% | 0 / 153 (0.000%) | 3.180% |
| X1000 | Offer-conditional, recent history | 1 / 923 (0.108%) | 4.878% | 0 / 153 (0.000%) | 3.180% |

### HYPE

| Payout | Formula | Weekday wins / quotes (rate) | Weekday availability | Weekend wins / quotes (rate) | Weekend availability |
| --- | --- | ---: | ---: | ---: | ---: |
| X100 | Previous conservative overlay | 203 / 11,281 (1.799%) | 59.640% | 16 / 1,751 (0.914%) | 36.358% |
| X100 | Active-state empirical control | 239 / 12,845 (1.861%) | 67.909% | 30 / 2,207 (1.359%) | 45.826% |
| X100 | Native parametric, raw budget | 376 / 12,995 (2.893%) | 68.702% | 54 / 2,248 (2.402%) | 46.678% |
| X100 | Marginal CDF calibration | 309 / 11,686 (2.644%) | 61.782% | 64 / 2,302 (2.780%) | 47.799% |
| X100 | Offer-conditional, full history | 237 / 10,238 (2.315%) | 54.126% | 56 / 2,014 (2.781%) | 41.819% |
| X100 | Offer-conditional, recent history | 115 / 6,134 (1.875%) | 32.429% | 55 / 1,861 (2.955%) | 38.642% |
| X1000 | Previous conservative overlay | 0 / 0 (—) | 0.000% | 0 / 0 (—) | 0.000% |
| X1000 | Active-state empirical control | 0 / 314 (0.000%) | 1.660% | 0 / 5 (0.000%) | 0.104% |
| X1000 | Native parametric, raw budget | 2 / 960 (0.208%) | 5.075% | 0 / 25 (0.000%) | 0.519% |
| X1000 | Marginal CDF calibration | 15 / 3,031 (0.495%) | 16.024% | 0 / 198 (0.000%) | 4.111% |
| X1000 | Offer-conditional, full history | 8 / 1,263 (0.633%) | 6.677% | 0 / 60 (0.000%) | 1.246% |
| X1000 | Offer-conditional, recent history | 7 / 1,111 (0.630%) | 5.874% | 0 / 60 (0.000%) | 1.246% |

## Primary revision versus the previous overlay

| Asset / payout | Weekday rate, before → after | Weekday availability, before → after | Weekend rate, before → after | Weekend availability, before → after |
| --- | ---: | ---: | ---: | ---: |
| ETH X100 | 0.228% → 1.335% | 30.185% → 51.847% | 0.308% → 0.693% | 6.755% → 14.986% |
| ETH X1000 | — → 0.108% | 0.000% → 4.878% | — → 0.000% | 0.000% → 3.180% |
| HYPE X100 | 1.799% → 1.875% | 59.640% → 32.429% | 0.914% → 2.955% | 36.358% → 38.642% |
| HYPE X1000 | — → 0.630% | 0.000% → 5.874% | — → 0.000% | 0.000% → 1.246% |

## Primary revision: daily X1000 offers

| UTC date | ETH quotes | ETH availability | HYPE quotes | HYPE availability |
| --- | ---: | ---: | ---: | ---: |
| 2026-09-01 | 5 | 0.208% | 606 | 25.229% |
| 2026-09-02 | 1 | 0.042% | 141 | 5.929% |
| 2026-09-03 | 3 | 0.125% | 80 | 3.329% |
| 2026-09-04 | 180 | 7.676% | 102 | 4.353% |
| 2026-09-05 | 27 | 1.130% | 0 | 0.000% |
| 2026-09-06 | 126 | 5.202% | 60 | 2.467% |
| 2026-09-07 | 294 | 12.389% | 25 | 1.054% |
| 2026-09-08 | 59 | 2.527% | 36 | 1.542% |
| 2026-09-09 | 71 | 2.982% | 44 | 1.854% |
| 2026-09-10 | 310 | 13.426% | 77 | 3.332% |

## Primary revision: pooled support and economics

| Asset / payout | Wins / quotes (rate) | Flat-path wins | Availability | Worst date availability | Target expected wins | LP gross per stake | Screen failures |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| ETH X100 | 136 / 10,532 (1.291%) | 12 | 44.375% | 7.158% | 100.054 | -29.130% | insufficient_quote_availability, survival_outside_reference_band, negative_zero_cost_gross |
| ETH X1000 | 1 / 1,076 (0.093%) | 0 | 4.534% | 0.042% | 1.022 | 7.063% | insufficient_quote_availability, insufficient_rare_event_evidence |
| HYPE X100 | 170 / 7,995 (2.126%) | 30 | 33.690% | 7.339% | 75.953 | -112.633% | insufficient_quote_availability, survival_outside_reference_band, negative_zero_cost_gross |
| HYPE X1000 | 7 / 1,171 (0.598%) | 1 | 4.934% | 0.000% | 1.112 | -497.780% | empty_quote_set, insufficient_quote_availability, survival_outside_reference_band, negative_zero_cost_gross, insufficient_rare_event_evidence |

LP gross assumes one stake per resolved accepted quote and total payout including returned stake: `(quotes − M × wins) / quotes`. It excludes fees, hedging, funding, latency, capital requirements and correlated losses. A positive sample gross is not established net profitability.

The unchanged necessary screens require nonempty quotes on every date, 85% availability on every date, pooled survival within 75–125% of target, nonnegative zero-cost gross, and twenty target-expected evaluated wins. X1000 needs at least 21,053 accepted quotes for that final reference; parametric extrapolation does not waive it. A zero-win weekend with few quotes is not evidence of accurately priced X1000 risk.

## Earlier monthly results

These fourteen first-of-month out-of-sample dates span July 2025–August 2026. The initial six monthly dates are warmup. This is distinct from the consecutive September period, and no candidate is selected from these comparisons.

| Asset / payout | Formula | Wins / quotes (rate) | Availability | Worst date availability |
| --- | --- | ---: | ---: | ---: |
| ETH X100 | Previous conservative overlay | 57 / 9,241 (0.617%) | 24.090% | 0.000% |
| ETH X100 | Active-state empirical control | 133 / 18,426 (0.722%) | 48.034% | 3.035% |
| ETH X100 | Native parametric, raw budget | 222 / 18,979 (1.170%) | 49.476% | 3.396% |
| ETH X100 | Marginal CDF calibration | 322 / 20,812 (1.547%) | 54.254% | 4.155% |
| ETH X100 | Offer-conditional, full history | 226 / 18,741 (1.206%) | 48.856% | 2.962% |
| ETH X100 | Offer-conditional, recent history | 209 / 18,024 (1.160%) | 46.986% | 2.240% |
| ETH X1000 | Previous conservative overlay | 0 / 0 (—) | 0.000% | 0.000% |
| ETH X1000 | Active-state empirical control | 0 / 816 (0.000%) | 2.127% | 0.000% |
| ETH X1000 | Native parametric, raw budget | 1 / 3,946 (0.025%) | 10.287% | 0.000% |
| ETH X1000 | Marginal CDF calibration | 9 / 5,672 (0.159%) | 14.786% | 0.036% |
| ETH X1000 | Offer-conditional, full history | 10 / 6,788 (0.147%) | 17.696% | 0.289% |
| ETH X1000 | Offer-conditional, recent history | 10 / 6,788 (0.147%) | 17.696% | 0.289% |
| HYPE X100 | Previous conservative overlay | 124 / 32,742 (0.379%) | 85.388% | 45.287% |
| HYPE X100 | Active-state empirical control | 174 / 34,991 (0.497%) | 91.253% | 51.282% |
| HYPE X100 | Native parametric, raw budget | 317 / 35,229 (0.900%) | 91.874% | 52.799% |
| HYPE X100 | Marginal CDF calibration | 476 / 36,052 (1.320%) | 94.020% | 65.078% |
| HYPE X100 | Offer-conditional, full history | 451 / 35,861 (1.258%) | 93.522% | 63.669% |
| HYPE X100 | Offer-conditional, recent history | 387 / 35,319 (1.096%) | 92.108% | 60.166% |
| HYPE X1000 | Previous conservative overlay | 0 / 0 (—) | 0.000% | 0.000% |
| HYPE X1000 | Active-state empirical control | 0 / 2,436 (0.000%) | 6.353% | 0.000% |
| HYPE X1000 | Native parametric, raw budget | 6 / 13,382 (0.045%) | 34.899% | 9.155% |
| HYPE X1000 | Marginal CDF calibration | 32 / 18,070 (0.177%) | 47.125% | 12.062% |
| HYPE X1000 | Offer-conditional, full history | 22 / 18,093 (0.122%) | 47.185% | 16.601% |
| HYPE X1000 | Offer-conditional, recent history | 22 / 18,093 (0.122%) | 47.185% | 16.601% |

## Availability with missing books retained

The secondary denominator includes every clean oracle path, including paths without fresh books. Every formula still requires measured liquidity to quote. Full daily, weekday and weekend summaries for both cohorts are retained in the packet.

| Asset / payout | Primary weekday availability | Primary weekend availability |
| --- | ---: | ---: |
| ETH X100 | 45.379% | 13.107% |
| ETH X1000 | 4.269% | 2.781% |
| HYPE X100 | 28.371% | 33.836% |
| HYPE X1000 | 5.139% | 1.091% |

## Verification and remaining limits

The active-tail audit refitted 48 earlier-only origin models and independently replayed 805,830 decisions. The conditional-tail audit verified every calibration population, candidate budget and chosen level, then independently replayed 537,220 additional decisions. All origin/source/input hashes, accepted/refused/unresolved traces and daily/cohort metrics reconcile. Thirty-five tests passed across historical liquidity, trial liquidity, payout settlement, flat vetoes, overlay, active tails and conditional calibration, including native touch boundaries, future-outcome invariance, midnight maturity, asset isolation and tamper rejection.

X1000 now supplies actual positive-width quotes, but availability and sparse-tail evidence remain limitations. The target-versus-availability tradeoff is reported without relaxing the existing screen. HYPE weekday results must be read against both the 0.950% target and the prior overlay availability. Only two September weekend dates are available; weekday/weekend differences cannot establish a causal liquidity effect. These outcomes have informed repeated formula changes, so a future frozen evaluation on fresh data remains necessary. No model is promoted to the live engine.

Active packet: `/Volumes/dev/fuse/.local/adaptive-corridor/20261029-active-tail-payout-v1`. Conditional packet: `/Volumes/dev/fuse/.local/adaptive-corridor/20261029-conditional-tail-payout-v1`. Prior overlay: `/Volumes/dev/fuse/.local/adaptive-corridor/20261029-flat-risk-overlay-v1`. Each packet retains a declaration, complete imported local source snapshot, per-origin models or calibration levels, complete decisions and independent audit.

```sh
PYTHONPATH=scripts OPENBLAS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 OMP_NUM_THREADS=1 python3 -B -m unittest scripts.test_historical_liquidity scripts.test_trial_liquidity scripts.test_trial_payout scripts.test_flat_aware_payout scripts.test_flat_risk_overlay scripts.test_active_tail_payout scripts.test_conditional_tail_payout
python3 -B scripts/research_active_tail.py --declare --parent .local/adaptive-corridor/20261029-flat-aware-payout-v1 --comparison .local/adaptive-corridor/20261029-flat-risk-overlay-v1 --output .local/adaptive-corridor/NEW-ACTIVE
OPENBLAS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 OMP_NUM_THREADS=1 python3 -B scripts/research_active_tail.py --output .local/adaptive-corridor/NEW-ACTIVE
OPENBLAS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 OMP_NUM_THREADS=1 python3 -B scripts/research_active_tail.py --audit --output .local/adaptive-corridor/NEW-ACTIVE
python3 -B scripts/research_conditional_tail.py --declare --parent .local/adaptive-corridor/NEW-ACTIVE --output .local/adaptive-corridor/NEW-CONDITIONAL
OPENBLAS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 OMP_NUM_THREADS=1 python3 -B scripts/research_conditional_tail.py --output .local/adaptive-corridor/NEW-CONDITIONAL
OPENBLAS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 OMP_NUM_THREADS=1 python3 -B scripts/research_conditional_tail.py --audit --output .local/adaptive-corridor/NEW-CONDITIONAL
python3 -B scripts/report_active_tail.py --previous .local/adaptive-corridor/20261029-flat-risk-overlay-v1 --active .local/adaptive-corridor/NEW-ACTIVE --conditional .local/adaptive-corridor/NEW-CONDITIONAL --output docs/ACTIVE_TAIL_PAYOUT_RESEARCH.md
```

Active research SHA-256: `b55ace819784c34af338c6c2cc15fea7a8cc08f66d1a989ac0fb3f09f70de773`. Audit SHA-256: `2c2c15d83b6bf139e6395f4323a97769d52f4c41f81d571f8eaaf44ef3ed16bf`.
Conditional research SHA-256: `114da1403518831726e6622ec340538befd61a1d150ce678a683072b5f94241a`. Audit SHA-256: `2084f585d1e08bffd7e032a4a0fbd924cc5c13694f0500ed8b79699ef5f3e036`.
