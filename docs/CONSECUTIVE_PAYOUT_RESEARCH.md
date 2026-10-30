# Consecutive ETH and HYPE 100x and 1000x corridor backtests

These backtests quote and settle actual thirty-second corridors on September 1–10, 2026 UTC oracle paths. They compare trader survival, quote availability and equal-stake LP gross arithmetic on eight weekday dates and two weekend dates, September 5 and 6. Each asset has 28,800 fixed grid entries; unresolved paths remain excluded from outcome arithmetic. This is historical development on already inspected data.

No tested variant passes all existing necessary development screens at either payout. The native formula and fitted research models remain separate comparisons; no live formula was changed.

The shipped fixed-volatility control has trader win rates of 85.72%–98.01%, far above either payout target. Its corridors are too wide for these observed oracle paths under the shipped volatility assumptions.

At 100×, the fixed fitted calendar-plus-liquidity model gives ETH weekday survival of 0.64% with 52.86% availability, versus weekend survival of 3.78% with 14.84% availability. The target is 0.95%.

At 100×, the fixed fitted calendar-plus-liquidity model gives HYPE weekday survival of 1.72% with 65.59% availability, versus weekend survival of 0.94% with 44.21% availability. The target is 0.95%.

## Quote and settlement rules

The shipped-formula control uses `brownian-first-mode-v1`, a five percent target edge and the shipped thirty-second volatility assumptions: ETH 1,500 ppm and HYPE 3,000 ppm. Its Q12 logarithm, integer square root and downward ppb quantization match all ninety retained native pricing reference vectors. It is an assumption-based formula control, rather than a fitted probability guarantee.

The research corridors reuse the previous audited daily earlier-only risk coefficients, separately for each asset. Their positive movement CDF is refitted at each daily origin from the same matched earlier paths: twenty first-of-month dates from January 2025 through August 2026, followed by matured preceding trial dates. Calibrated controls use only earlier out-of-sample monthly raw forecasts and matured prior trial forecasts. Current-date outcomes never enter coefficients, movement widths or calibration. The last two previous-day windows are withheld when their expiry plus thirty seconds has not passed the origin.

The primary fixed comparison is calendar plus oracle activity versus the same model plus measured liquidity, both raw. Activity-only and prior-32 calibrated variants are retained as fixed controls, together with the one-ppm minimum-width diagnostic. All ten variants are saved; none is selected from the payout results. Research CDF quotes use the existing slow-volatility anchor, activity groups, one-ppm minimum, 50,000-ppm maximum, risk gate at the target and at least twenty positive-tail training references. Unsupported quotes are refused.

All variants share the five-minute pre-entry research-history requirement. A trader wins only if every observed oracle price stays strictly inside both integer barriers for the full thirty seconds. Touching a barrier loses. The shipped control retains ppb widths; empirical research widths retain their existing integer ppm quantization. Original freshness and disconnect exclusions apply. Pre-entry offers and subsequently unresolved offers are retained separately, so a future outage cannot become an admission feature.

This is an oracle-path formula replay. It does not reproduce dual-receiver canonical admission, order acceptance latency, account limits, aggregate underwriting capacity or a native engine journal.

| Total payout | Target trader win rate at five percent edge | Zero-cost LP break-even trader win rate |
| --- | ---: | ---: |
| 100× | 0.950% | 1.000% |
| 1,000× | 0.095% | 0.100% |

A total payout includes the returned stake. For N accepted resolved one-unit stakes and W trader wins, LP gross is `N − M × W`; gross per stake is `1 − M × W / N`. A negative percentage can exceed a one-stake loss because one winner receives many stakes. This arithmetic excludes costs, funding, hedging, capital limits and loss correlation. Zero quotes produce no estimated win rate or return.

## Weekday and weekend comparison

The primary table uses the same clean oracle paths with fresh pre-entry books for every variant. “Kept” is accepted resolved quotes divided by those eligible paths. A strategy can reduce wins by quoting fewer times, so counts and availability accompany every win rate.

### ETH

23,734 matched clean paths, versus 27,121 clean oracle paths before requiring a book.

| Payout | Model | Weekday wins / quotes and rate | Weekday kept | Weekend wins / quotes and rate | Weekend kept | Weekday LP gross per stake | Weekend LP gross per stake |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 100× | Shipped formula | 17,213 / 18,923 (90.96%) | 100.00% | 4,672 / 4,811 (97.11%) | 100.00% | -8996.34% | -9611.08% |
| 100× | Fitted calendar | 62 / 9,780 (0.63%) | 51.68% | 27 / 672 (4.02%) | 13.97% | 36.61% | -301.79% |
| 100× | Fitted calendar plus liquidity | 64 / 10,002 (0.64%) | 52.86% | 27 / 714 (3.78%) | 14.84% | 36.01% | -278.15% |
| 1,000× | Shipped formula | 16,221 / 18,923 (85.72%) | 100.00% | 4,577 / 4,811 (95.14%) | 100.00% | -85621.08% | -95036.15% |
| 1,000× | Fitted calendar | 4 / 31 (12.90%) | 0.16% | 14 / 55 (25.45%) | 1.14% | -12803.23% | -25354.55% |
| 1,000× | Fitted calendar plus liquidity | 4 / 51 (7.84%) | 0.27% | 14 / 55 (25.45%) | 1.14% | -7743.14% | -25354.55% |

### HYPE

23,731 matched clean paths, versus 27,121 clean oracle paths before requiring a book.

| Payout | Model | Weekday wins / quotes and rate | Weekday kept | Weekend wins / quotes and rate | Weekend kept | Weekday LP gross per stake | Weekend LP gross per stake |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 100× | Shipped formula | 18,245 / 18,915 (96.46%) | 100.00% | 4,720 / 4,816 (98.01%) | 100.00% | -9545.78% | -9700.66% |
| 100× | Fitted calendar | 228 / 12,836 (1.78%) | 67.86% | 30 / 2,275 (1.32%) | 47.24% | -77.63% | -31.87% |
| 100× | Fitted calendar plus liquidity | 213 / 12,407 (1.72%) | 65.59% | 20 / 2,129 (0.94%) | 44.21% | -71.68% | 6.06% |
| 1,000× | Shipped formula | 17,754 / 18,915 (93.86%) | 100.00% | 4,629 / 4,816 (96.12%) | 100.00% | -93762.01% | -96017.11% |
| 1,000× | Fitted calendar | 0 / 11 (0.00%) | 0.06% | 0 / 0 (—) | 0.00% | 100.00% | — |
| 1,000× | Fitted calendar plus liquidity | 0 / 17 (0.00%) | 0.09% | 0 / 0 (—) | 0.00% | 100.00% | — |

## All fixed variants

The following pooled matched-path results include every fixed variant and payout. The one-ppm row is an always-open lower-bound diagnostic and cannot qualify as a calibrated payout rule. “Worst day kept” includes empty quote dates. Full daily and weekday/weekend breakdowns for every row are retained in each asset research JSON.

| Asset | Payout | Variant | Wins / quotes and rate | Kept | Worst day kept | Target expected wins | LP gross per stake | Passes screens |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| ETH | 100× | shipped_formula | 21,885 / 23,734 (92.21%) | 100.00% | 100.00% | 225.47 | -9120.95% | No |
| ETH | 100× | minimum_width_floor | 380 / 23,734 (1.60%) | 100.00% | 100.00% | 225.47 | -60.11% | No |
| ETH | 100× | activity_raw_cdf | 76 / 9,637 (0.79%) | 40.60% | 8.92% | 91.55 | 21.14% | No |
| ETH | 100× | activity_cal32_cdf | 104 / 10,507 (0.99%) | 44.27% | 9.67% | 99.82 | 1.02% | No |
| ETH | 100× | calendar_raw_cdf | 89 / 10,452 (0.85%) | 44.04% | 8.08% | 99.29 | 14.85% | No |
| ETH | 100× | calendar_cal32_cdf | 109 / 11,266 (0.97%) | 47.47% | 8.87% | 107.03 | 3.25% | No |
| ETH | 100× | activity_liquidity_raw_cdf | 81 / 9,848 (0.82%) | 41.49% | 9.50% | 93.56 | 17.75% | No |
| ETH | 100× | activity_liquidity_cal32_cdf | 101 / 10,704 (0.94%) | 45.10% | 10.30% | 101.69 | 5.64% | No |
| ETH | 100× | calendar_liquidity_raw_cdf | 91 / 10,716 (0.85%) | 45.15% | 8.54% | 101.80 | 15.08% | No |
| ETH | 100× | calendar_liquidity_cal32_cdf | 126 / 11,525 (1.09%) | 48.56% | 9.46% | 109.49 | -9.33% | No |
| ETH | 1,000× | shipped_formula | 20,798 / 23,734 (87.63%) | 100.00% | 100.00% | 22.55 | -87529.56% | No |
| ETH | 1,000× | minimum_width_floor | 380 / 23,734 (1.60%) | 100.00% | 100.00% | 22.55 | -1501.08% | No |
| ETH | 1,000× | activity_raw_cdf | 18 / 85 (21.18%) | 0.36% | 0.00% | 0.08 | -21076.47% | No |
| ETH | 1,000× | activity_cal32_cdf | 0 / 0 (—) | 0.00% | 0.00% | 0.00 | — | No |
| ETH | 1,000× | calendar_raw_cdf | 18 / 86 (20.93%) | 0.36% | 0.00% | 0.08 | -20830.23% | No |
| ETH | 1,000× | calendar_cal32_cdf | 0 / 0 (—) | 0.00% | 0.00% | 0.00 | — | No |
| ETH | 1,000× | activity_liquidity_raw_cdf | 18 / 97 (18.56%) | 0.41% | 0.00% | 0.09 | -18456.70% | No |
| ETH | 1,000× | activity_liquidity_cal32_cdf | 0 / 0 (—) | 0.00% | 0.00% | 0.00 | — | No |
| ETH | 1,000× | calendar_liquidity_raw_cdf | 18 / 106 (16.98%) | 0.45% | 0.00% | 0.10 | -16881.13% | No |
| ETH | 1,000× | calendar_liquidity_cal32_cdf | 0 / 0 (—) | 0.00% | 0.00% | 0.00 | — | No |
| HYPE | 100× | shipped_formula | 22,965 / 23,731 (96.77%) | 100.00% | 100.00% | 225.44 | -9577.22% | No |
| HYPE | 100× | minimum_width_floor | 520 / 23,731 (2.19%) | 100.00% | 100.00% | 225.44 | -119.12% | No |
| HYPE | 100× | activity_raw_cdf | 248 / 14,967 (1.66%) | 63.07% | 25.46% | 142.19 | -65.70% | No |
| HYPE | 100× | activity_cal32_cdf | 325 / 15,581 (2.09%) | 65.66% | 28.19% | 148.02 | -108.59% | No |
| HYPE | 100× | calendar_raw_cdf | 258 / 15,111 (1.71%) | 63.68% | 25.80% | 143.55 | -70.74% | No |
| HYPE | 100× | calendar_cal32_cdf | 323 / 15,677 (2.06%) | 66.06% | 28.27% | 148.93 | -106.03% | No |
| HYPE | 100× | activity_liquidity_raw_cdf | 229 / 14,361 (1.59%) | 60.52% | 22.11% | 136.43 | -59.46% | No |
| HYPE | 100× | activity_liquidity_cal32_cdf | 299 / 15,019 (1.99%) | 63.29% | 25.04% | 142.68 | -99.08% | No |
| HYPE | 100× | calendar_liquidity_raw_cdf | 233 / 14,536 (1.60%) | 61.25% | 22.53% | 138.09 | -60.29% | No |
| HYPE | 100× | calendar_liquidity_cal32_cdf | 304 / 15,145 (2.01%) | 63.82% | 24.83% | 143.88 | -100.73% | No |
| HYPE | 1,000× | shipped_formula | 22,383 / 23,731 (94.32%) | 100.00% | 100.00% | 22.54 | -94219.67% | No |
| HYPE | 1,000× | minimum_width_floor | 520 / 23,731 (2.19%) | 100.00% | 100.00% | 22.54 | -2091.23% | No |
| HYPE | 1,000× | activity_raw_cdf | 0 / 6 (0.00%) | 0.03% | 0.00% | 0.01 | 100.00% | No |
| HYPE | 1,000× | activity_cal32_cdf | 4 / 1,523 (0.26%) | 6.42% | 0.00% | 1.45 | -162.64% | No |
| HYPE | 1,000× | calendar_raw_cdf | 0 / 11 (0.00%) | 0.05% | 0.00% | 0.01 | 100.00% | No |
| HYPE | 1,000× | calendar_cal32_cdf | 8 / 2,358 (0.34%) | 9.94% | 0.25% | 2.24 | -239.27% | No |
| HYPE | 1,000× | activity_liquidity_raw_cdf | 0 / 12 (0.00%) | 0.05% | 0.00% | 0.01 | 100.00% | No |
| HYPE | 1,000× | activity_liquidity_cal32_cdf | 6 / 1,699 (0.35%) | 7.16% | 0.17% | 1.61 | -253.15% | No |
| HYPE | 1,000× | calendar_liquidity_raw_cdf | 0 / 17 (0.00%) | 0.07% | 0.00% | 0.02 | 100.00% | No |
| HYPE | 1,000× | calendar_liquidity_cal32_cdf | 8 / 2,059 (0.39%) | 8.68% | 0.21% | 1.96 | -288.54% | No |

## Missing book sensitivity

This secondary comparison includes every clean oracle path. Missing books remain in the availability denominator and cause the liquidity variants to refuse quotes. Outcomes are never filled with zero; baseline models can still quote without a book. All variants retain identical earlier matched training cohorts, so this measures entry-book availability rather than a second choice of training data.

| Asset | Payout | Model | Weekday wins / quotes and rate | Weekday kept | Weekend wins / quotes and rate | Weekend kept |
| --- | --- | --- | ---: | ---: | ---: | ---: |
| ETH | 100× | Shipped formula | 19,670 / 21,620 (90.98%) | 100.00% | 5,342 / 5,501 (97.11%) | 100.00% |
| ETH | 100× | Fitted calendar | 69 / 11,164 (0.62%) | 51.64% | 28 / 776 (3.61%) | 14.11% |
| ETH | 100× | Fitted calendar plus liquidity | 64 / 10,002 (0.64%) | 46.26% | 27 / 714 (3.78%) | 12.98% |
| ETH | 1,000× | Shipped formula | 18,535 / 21,620 (85.73%) | 100.00% | 5,234 / 5,501 (95.15%) | 100.00% |
| ETH | 1,000× | Fitted calendar | 5 / 36 (13.89%) | 0.17% | 14 / 59 (23.73%) | 1.07% |
| ETH | 1,000× | Fitted calendar plus liquidity | 4 / 51 (7.84%) | 0.24% | 14 / 55 (25.45%) | 1.00% |
| HYPE | 100× | Shipped formula | 20,873 / 21,621 (96.54%) | 100.00% | 5,389 / 5,500 (97.98%) | 100.00% |
| HYPE | 100× | Fitted calendar | 271 / 14,669 (1.85%) | 67.85% | 35 / 2,601 (1.35%) | 47.29% |
| HYPE | 100× | Fitted calendar plus liquidity | 213 / 12,407 (1.72%) | 57.38% | 20 / 2,129 (0.94%) | 38.71% |
| HYPE | 1,000× | Shipped formula | 20,312 / 21,621 (93.95%) | 100.00% | 5,289 / 5,500 (96.16%) | 100.00% |
| HYPE | 1,000× | Fitted calendar | 0 / 13 (0.00%) | 0.06% | 0 / 0 (—) | 0.00% |
| HYPE | 1,000× | Fitted calendar plus liquidity | 0 / 17 (0.00%) | 0.08% | 0 / 0 (—) | 0.00% |

## Limits and verification

The existing necessary screens require quotes on every date, at least 85 percent availability on every date, pooled survival within 75–125 percent of target, nonnegative zero-cost LP gross and at least twenty target-expected evaluated wins. These are descriptive checks, not an independent-event confidence test. At 1,000×, twenty target-expected wins require at least 21,053 accepted resolved quotes. Most refused-entry policies cannot supply that budget in ten dates.

Only one Saturday and one Sunday are included. Consecutive days can share market regimes, and these outcomes were already inspected for oracle and liquidity research. Calendar differences cannot identify liquidity as the cause. A small improvement in a probability loss metric does not by itself establish payout calibration, availability or positive LP arithmetic.

The audit passed. It refitted 80 earlier-only risk models, verified every positive CDF point/date weight and calibration population, independently replayed 1,152,000 quote decisions, and reconciled all calendar, daily and cohort summaries. The source oracle packet remains bound to its earlier successful 57,600-row reconstruction audit and the hashes of 1,440 raw slices. Five focused tests cover all ninety native vectors, exact barrier touches, future-outcome independence, tail support, missing-book denominators, midnight maturity, complete export/audit and tamper rejection.

Research packet: `/Volumes/dev/fuse/.local/adaptive-corridor/20261029-consecutive-payout-v1`. Input oracle/liquidity packet: `/Volumes/dev/fuse/.local/adaptive-corridor/20261029-consecutive-trial-liquidity-v2`. Each asset retains every daily origin model and all grid decisions, including refused and unresolved entries. The protocol freezes the full Python source closure and native pricing source/vectors before the payout replay. The live policy and fresh collector were not changed.

```sh
PYTHONPATH=scripts OPENBLAS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 python3 -B -m unittest scripts.test_trial_payout
python3 -B scripts/research_trial_payout.py --declare --liquidity /Volumes/dev/fuse/.local/adaptive-corridor/20261029-consecutive-trial-liquidity-v2 --output .local/adaptive-corridor/NEW-CONSECUTIVE-PAYOUT
OPENBLAS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 python3 -B scripts/research_trial_payout.py --output .local/adaptive-corridor/NEW-CONSECUTIVE-PAYOUT
OPENBLAS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 python3 -B scripts/research_trial_payout.py --audit --output .local/adaptive-corridor/NEW-CONSECUTIVE-PAYOUT
```

Research SHA-256: `f27b9727ce00569d12a288002d7d464391e1b83767a60fd8df5619f9f617526f`. Audit SHA-256: `5d3ded385194d900685a242a0c306af36d97d07fc3b9020c6cda0051510f56e6`.
