# ETH/HYPE payout walk-forward research — 29 October 2026

No tested pricing variant meets all necessary development screens. The larger chronological replay still does not establish deployable 100× or 1,000× pricing.

## What changed

The evaluation now expands through time. After six warmup dates, every later sampled date is scored once per asset/payout/variant. Every origin refits both risk coefficients and movement distributions from all strictly earlier, matured paths of that asset. The old train/validation/test labels do not control these fits. No previous final coefficients, selected risk family, payout widths or future-selected policy are reused.

This is a broader evaluation of an already inspected development archive. It is not new market data or a new holdout. [Tardis raw API documentation](https://docs.tardis.dev/api/http-api-reference) makes first-of-month histories available without an API key; the archive therefore consists of sampled full days separated by monthly gaps. No continuous history, paid access or unattended capture was added.

| Asset | Warmup dates | Scored dates | Scored UTC range | Unique grid entries | Clean paths | Weekend / weekday dates |
| --- | ---: | ---: | --- | ---: | ---: | ---: |
| ETH | 6 | 18 | 2025-05-01–2026-10-01 | 51,840 | 50,244 | 5 / 13 |
| HYPE | 6 | 16 | 2025-07-01–2026-10-01 | 46,080 | 44,600 | 4 / 12 |

The paired fixed models use oracle timing/activity features, with or without UTC weekend/hour features, at ridge 0.003. Each is evaluated raw and with prior-32 score-bin calibration. Calibration receives all clean earlier walk-forward forecasts, including refused paths. It never receives own-date forecasts or fitted in-sample forecasts. Supported bins still require at least 200 paths across three earlier dates; otherwise raw probabilities remain. Coefficients and calibration are frozen for the entire scored date.

Positive movement widths use the exact date-weighted empirical CDF of required width divided by slow volatility, grouped by pre-entry activity state and shrunk toward the global positive CDF. Local groups require 200 positive paths across three dates; otherwise the parent is used. The requested positive quantile is `(0.95/M − predicted_floor)/(1 − predicted_floor)`. Quotes require forecast floor at most target and at least twenty global count-times-positive-quantile training references. Neither this support rule nor the 85% daily availability reference is relaxed.

The one-ppm open corridor is a lower-bound diagnostic only. Its win rate is the unavoidable floor for this research width bound, not a calibrated payout model. Zero movement is the separate floor applying to every valid positive corridor.

## Chronological quote results

Targets are 0.95% at 100× and 0.095% at 1,000×. The zero-cost break-even rates are 1% and 0.1%. “Kept” is measured among paths with a healthy resolved label and available entry history; quote admission itself cannot see that future health label. Pre-entry and resolved counts are retained separately. Each row is a fixed comparison, not a selected winner.

| Asset | Payout | Fixed variant | Kept | Worst date kept | Wins / kept | Win rate | Target-expected wins |
| --- | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| ETH | 100× | timing_raw_cdf | 48.78% | 2.49% | 215 / 24,509 | 0.8772% | 232.84 |
| ETH | 100× | timing_cal32_cdf | 51.06% | 2.78% | 274 / 25,657 | 1.0679% | 243.74 |
| ETH | 100× | calendar_raw_cdf | 49.42% | 2.96% | 221 / 24,829 | 0.8901% | 235.88 |
| ETH | 100× | calendar_cal32_cdf | 51.68% | 3.36% | 283 / 25,967 | 1.0898% | 246.69 |
| ETH | 1,000× | timing_raw_cdf | 0.33% | 0.00% | 52 / 165 | 31.5152% | 0.16 |
| ETH | 1,000× | timing_cal32_cdf | 4.55% | 0.00% | 53 / 2,285 | 2.3195% | 2.17 |
| ETH | 1,000× | calendar_raw_cdf | 0.34% | 0.00% | 52 / 170 | 30.5882% | 0.16 |
| ETH | 1,000× | calendar_cal32_cdf | 4.95% | 0.00% | 53 / 2,487 | 2.1311% | 2.36 |
| HYPE | 100× | timing_raw_cdf | 89.81% | 43.52% | 227 / 40,055 | 0.5667% | 380.52 |
| HYPE | 100× | timing_cal32_cdf | 91.08% | 46.48% | 300 / 40,623 | 0.7385% | 385.92 |
| HYPE | 100× | calendar_raw_cdf | 90.06% | 45.72% | 227 / 40,168 | 0.5651% | 381.60 |
| HYPE | 100× | calendar_cal32_cdf | 90.96% | 48.90% | 300 / 40,569 | 0.7395% | 385.41 |
| HYPE | 1,000× | timing_raw_cdf | 0.15% | 0.00% | 0 / 65 | 0.0000% | 0.06 |
| HYPE | 1,000× | timing_cal32_cdf | 37.15% | 0.00% | 12 / 16,569 | 0.0724% | 15.74 |
| HYPE | 1,000× | calendar_raw_cdf | 0.32% | 0.00% | 0 / 142 | 0.0000% | 0.13 |
| HYPE | 1,000× | calendar_cal32_cdf | 36.80% | 0.00% | 13 / 16,412 | 0.0792% | 15.59 |

For the fixed calibrated timing comparison at 1,000×, ETH retains 4.55% of clean paths but has 53 wins in 2,285 quotes (2.3195% versus the 0.095% target). HYPE retains 37.15%, with 12 wins in 16,569 quotes (0.0724%). HYPE’s pooled rate is near the target reference band, but sparse availability, empty dates and only 15.74 target-expected wins still fail the screens. These rows do not select the timing family or establish future performance.

The same necessary descriptive screens now apply to every fixed walk-forward variant: nonempty quotes on every scheduled date, at least 85% availability on every date, pooled survival within 75–125% of target, nonnegative zero-cost equal-stake gross arithmetic, and at least twenty target-expected wins. These screens do not establish confidence, conditional calibration, joint liability coverage, or net LP returns. Failures and all daily summaries are retained in each asset’s research packet.

Early 1,000× origins can have too few positive training paths even if predicted floor were zero. Those dates are retained as real refusals in the scheduled evaluation. Later data cannot retroactively make an earlier quote sufficiently supported. The twenty-reference training-tail screen and twenty target-expected evaluated wins are separate requirements.

## Does a weekend term help?

The table scores minimum-width probability on all clean reference paths, including paths a pricing rule refused. Lower log loss is better. Paired calendar comparisons share the same origins and ridge; no calendar variant is selected from the observed results.

| Asset | Risk forecast | All-path floor log loss | Weekday floor log loss | Weekend floor log loss |
| --- | --- | ---: | ---: | ---: |
| ETH | timing_raw_cdf | 0.113884 | 0.096941 | 0.157889 |
| ETH | timing_cal32_cdf | 0.121852 | 0.105059 | 0.165470 |
| ETH | calendar_raw_cdf | 0.114268 | 0.097287 | 0.158376 |
| ETH | calendar_cal32_cdf | 0.121808 | 0.104842 | 0.165874 |
| HYPE | timing_raw_cdf | 0.021353 | 0.025021 | 0.010310 |
| HYPE | timing_cal32_cdf | 0.022122 | 0.025998 | 0.010457 |
| HYPE | calendar_raw_cdf | 0.021309 | 0.024890 | 0.010534 |
| HYPE | calendar_cal32_cdf | 0.022023 | 0.026065 | 0.009858 |

| Asset | Calendar group | Clean paths | Zero-motion wins | Minimum-width wins | Minimum-width survival |
| --- | --- | ---: | ---: | ---: | ---: |
| ETH | weekday | 36,277 | 1212 | 1212 | 3.3410% |
| ETH | weekend | 13,967 | 593 | 593 | 4.2457% |
| HYPE | weekday | 33,477 | 168 | 168 | 0.5018% |
| HYPE | weekend | 11,123 | 19 | 19 | 0.1708% |

In the fixed calibrated timing 1,000× comparison, ETH has 43 weekend wins and 10 weekday wins. HYPE has 5 weekend wins and 7 weekday wins. The weekend-only explanation does not fit either complete cohort; quote counts, rates and daily clustering must accompany win counts.

Weekend is a timestamp feature, not a measured liquidity state. This study has no spread, depth, trade volume or execution-cost measurements. Monthly sampling and a handful of weekend dates cannot establish that liquidity caused a win cluster or that a calendar coefficient will transfer to future weekends.

## Oracle floor and evidence budget

For N paths and Z unavoidable flat winners, retaining K quotes leaves at least `max(0, Z − (N − K))` winners, even with perfect hindsight about which paths to reject. A target win probability q therefore requires `K ≤ floor((N − Z)/(1 − q))`, capped at N. The code uses exact integer arithmetic. This is an optimistic historical ceiling, never an achievable pre-entry policy or probability guarantee. Daily ceilings are retained as well.

| Asset | Payout | All clean paths | Universal zero-motion floor | Most quotes possible at target, even with hindsight | All-quotes target-expected wins |
| --- | ---: | ---: | ---: | ---: | ---: |
| ETH | 100× | 50,244 | 3.5925% | 48,903 | 477.32 |
| ETH | 1,000× | 50,244 | 3.5925% | 48,485 | 47.73 |
| HYPE | 100× | 44,600 | 0.4193% | 44,600 | 423.70 |
| HYPE | 1,000× | 44,600 | 0.4193% | 44,455 | 42.37 |

Twenty target-expected wins require at least 2,106 offered paths at 100× or 21,053 at 1,000×. These are count references, not sample-size calculations for independent confidence intervals. `evidence-budget.json` records additional offered paths and clean-entry equivalents at each observed availability. Those projections assume unchanged retention and full 2,880-entry days; they cannot substitute for newly observed data, independent market episodes or prospective evaluation. A policy with zero availability has no finite estimate under that assumption.

The next data-dependent decision requires consecutive, newly observed weekday and weekend sessions, followed by a frozen-policy evaluation. A liquidity hypothesis also requires synchronized depth/spread/volume observations. This iteration establishes the chronological replay and evidence accounting needed for that test; the current archive cannot answer the liquidity-causality question.

## Verification and reproduction

Archive: `.local/adaptive-corridor/20261029-payout-walkforward-v1`. The audit checks 34 fitted origins and independently replays 979,200 saved decisions. It refits every saved risk coefficient from earlier labels, reconstructs calibration populations and monotone maps, verifies every positive CDF point/date weight, checks unique scoring entries and reconciles pooled/daily/calendar metrics and screens.

Seven focused tests cover own/future-label exclusion, duplicate/maturity rejection, pre-entry admission, exhaustive floor-bound arithmetic, empty-quote handling and end-to-end export/audit/tamper rejection. The full Python suite ran 403 tests with 3 skips; all others passed. No live pricing or running capture was changed.

```sh
python3 -B scripts/research_payout_walkforward.py --declare --parent .local/adaptive-corridor/20261028-ETH-HYPE-raw-fits-v2 --output .local/adaptive-corridor/NEW-WALKFORWARD
OPENBLAS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 python3 -B scripts/research_payout_walkforward.py --output .local/adaptive-corridor/NEW-WALKFORWARD
OPENBLAS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 python3 -B scripts/audit_payout_walkforward.py --research .local/adaptive-corridor/NEW-WALKFORWARD
python3 -B -m unittest discover -s scripts -p test_payout_walkforward.py
```
