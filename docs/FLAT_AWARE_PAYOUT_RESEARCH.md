# Flat aware ETH and HYPE payout formula iteration

This iteration adds a pre-entry flat-oracle veto and separate asset-specific estimates of flat-path probability. The revised formulas were tested at 100× and 1,000× on September 1–10, 2026 UTC, with the same weekday/weekend comparisons, strict barrier settlement, data exclusions and availability requirements as the previous backtest. Fourteen earlier monthly out-of-sample dates are reported separately. All evidence is historical development.

No revised formula passes all existing development checks. The explicit veto removes the diagnosed already-flat admission failure; accepted-quote availability and payout calibration remain unresolved.

The conservative overlay accepts no 1,000× entries for either asset. This prevents the old unsafe offers in this replay but supplies no estimate of a usable 1,000× win rate. At 100×, ETH becomes substantially more restrictive, while HYPE remains above break-even on weekdays.

The diagnosed failure was specific: all eighteen ETH wins accepted by the previous raw liquidity formula at 1,000× occurred after the oracle had already been unchanged for more than a minute. The old logistic head assigned those entries probabilities below the 0.095 percent target despite zero price changes in both preceding thirty- and sixty-second windows. A positive-width corridor cannot defeat an actually flat future path by narrowing its barriers.

## Formula changes

The previous fitted formula remains an exact control. The veto-only comparison keeps its widths and probability estimates but refuses entries when the last price change was at least thirty seconds ago, there were no price changes in the preceding thirty seconds, or the recorded idle age is only a lower bound. This decision uses pre-entry features; it does not inspect the current outcome or future health.

The activity hurdle replaces the logistic floor estimate with two asset-specific empirical heads: zero-motion probability and probability of surviving the one-ppm minimum width. The hierarchy conditions on preceding thirty-second change count and idle age. The calendar hurdle adds a UTC weekend child. Each child gives dates equal weight, shrinks toward its parent with mass 32 plus a half-event, and falls back to the parent below 200 paths or three earlier dates. The two heads remain nested. These are smoothed development estimates, not confidence bounds.

Positive movement size is fitted separately using exact date-weighted empirical CDFs, with local groups matching the hurdle activity/idle state and optional weekend. The existing slow-volatility anchor, parent shrinkage, empirical quantile and integer-ppm rounding rules remain. For target `q = 0.95 / M` and estimated minimum-width survival `p_min`, the positive-component quantile is `(q − p_min) / (1 − p_min)`. Quotes are refused if the floor exceeds target or fewer than twenty positive-tail training references support that quantile.

Both new hurdle formulas apply the flat veto. At 1,000× they additionally require at least four price changes in the preceding thirty seconds and a last price change less than three seconds before entry. These fixed recovery conditions were declared before this replay. The veto-only ablation does not add this recovery condition.

Each daily origin fits all components from strictly earlier matured matched paths of that asset. Labels enter only when expiry plus thirty seconds is strictly before the origin. Features and context retain the existing daily reset. No probability coefficients, thresholds or model variants were selected from the new replay. Earlier monthly raw outcomes and September outcomes had already been inspected in the broader research program, so chronological fitting does not create an untouched research holdout.

The first replacement hurdle formulas worsened HYPE results. After inspecting that development regression, a fifth conservative overlay was declared and replayed. It retains the previous positive-movement CDF and uses the larger of the previous logistic and new empirical flat-risk estimates. The same flat and recovery vetoes apply. Every offered quote is checked to have been offered previously, with width no larger than the old width. This guarantees a subset of offers and no wider corridor per retained entry; it does not guarantee an improved win-rate ratio or probability calibration. This additional iteration is explicitly outcome-informed development.

## Consecutive weekday and weekend results

The tables use identical clean oracle paths with fresh pre-entry books for every formula. Trader wins are accepted quotes whose complete observed thirty-second paths remained strictly inside the integer barriers; touching either barrier loses. Targets are 0.95 percent at 100× and 0.095 percent at 1,000×. Availability is accepted resolved quotes divided by the common eligible paths.

### ETH

| Payout | Formula | Weekday wins / quotes and rate | Weekday availability | Weekend wins / quotes and rate | Weekend availability | Weekday LP gross per stake | Weekend LP gross per stake |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 100× | Previous fitted formula | 64 / 10,002 (0.64%) | 52.86% | 27 / 714 (3.78%) | 14.84% | 36.01% | -278.15% |
| 100× | Previous formula plus flat veto | 58 / 9,977 (0.58%) | 52.72% | 9 / 651 (1.38%) | 13.53% | 41.87% | -38.25% |
| 100× | Activity hurdle | 64 / 9,155 (0.70%) | 48.38% | 38 / 1,383 (2.75%) | 28.75% | 30.09% | -174.77% |
| 100× | Calendar activity hurdle | 58 / 8,387 (0.69%) | 44.32% | 27 / 1,039 (2.60%) | 21.60% | 30.85% | -159.87% |
| 100× | Conservative flat risk overlay | 13 / 5,712 (0.23%) | 30.19% | 1 / 325 (0.31%) | 6.76% | 77.24% | 69.23% |
| 1,000× | Previous fitted formula | 4 / 51 (7.84%) | 0.27% | 14 / 55 (25.45%) | 1.14% | -7743.14% | -25354.55% |
| 1,000× | Previous formula plus flat veto | 0 / 31 (0.00%) | 0.16% | 0 / 0 (—) | 0.00% | 100.00% | — |
| 1,000× | Activity hurdle | 0 / 0 (—) | 0.00% | 0 / 0 (—) | 0.00% | — | — |
| 1,000× | Calendar activity hurdle | 0 / 0 (—) | 0.00% | 0 / 0 (—) | 0.00% | — | — |
| 1,000× | Conservative flat risk overlay | 0 / 0 (—) | 0.00% | 0 / 0 (—) | 0.00% | — | — |

### HYPE

| Payout | Formula | Weekday wins / quotes and rate | Weekday availability | Weekend wins / quotes and rate | Weekend availability | Weekday LP gross per stake | Weekend LP gross per stake |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 100× | Previous fitted formula | 213 / 12,407 (1.72%) | 65.59% | 20 / 2,129 (0.94%) | 44.21% | -71.68% | 6.06% |
| 100× | Previous formula plus flat veto | 213 / 12,407 (1.72%) | 65.59% | 20 / 2,129 (0.94%) | 44.21% | -71.68% | 6.06% |
| 100× | Activity hurdle | 433 / 14,427 (3.00%) | 76.27% | 128 / 3,407 (3.76%) | 70.74% | -200.13% | -275.70% |
| 100× | Calendar activity hurdle | 417 / 13,797 (3.02%) | 72.94% | 150 / 2,798 (5.36%) | 58.10% | -202.24% | -436.10% |
| 100× | Conservative flat risk overlay | 203 / 11,281 (1.80%) | 59.64% | 16 / 1,751 (0.91%) | 36.36% | -79.95% | 8.62% |
| 1,000× | Previous fitted formula | 0 / 17 (0.00%) | 0.09% | 0 / 0 (—) | 0.00% | 100.00% | — |
| 1,000× | Previous formula plus flat veto | 0 / 17 (0.00%) | 0.09% | 0 / 0 (—) | 0.00% | 100.00% | — |
| 1,000× | Activity hurdle | 0 / 0 (—) | 0.00% | 0 / 0 (—) | 0.00% | — | — |
| 1,000× | Calendar activity hurdle | 0 / 0 (—) | 0.00% | 0 / 0 (—) | 0.00% | — | — |
| 1,000× | Conservative flat risk overlay | 0 / 0 (—) | 0.00% | 0 / 0 (—) | 0.00% | — | — |

## Flat wins and pooled results

The veto-only comparison isolates entries removed by the explicit pre-entry rule. New hurdle formulas also change conditional probability, movement groups and widths, so their accepted populations differ. Zero wins after refusing every entry would not demonstrate successful pricing.

| Asset | Payout | Formula | Wins / quotes and rate | Flat-oracle wins | Availability | Worst date availability | Target expected wins | Passes existing screens |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| ETH | 100× | Previous fitted formula | 91 / 10,716 (0.85%) | 35 | 45.15% | 8.54% | 101.80 | No |
| ETH | 100× | Previous formula plus flat veto | 67 / 10,628 (0.63%) | 16 | 44.78% | 6.28% | 100.97 | No |
| ETH | 100× | Activity hurdle | 102 / 10,538 (0.97%) | 46 | 44.40% | 27.66% | 100.11 | No |
| ETH | 100× | Calendar activity hurdle | 85 / 9,426 (0.90%) | 33 | 39.72% | 0.00% | 89.55 | No |
| ETH | 100× | Conservative flat risk overlay | 14 / 6,037 (0.23%) | 5 | 25.44% | 0.00% | 57.35 | No |
| ETH | 1,000× | Previous fitted formula | 18 / 106 (16.98%) | 18 | 0.45% | 0.00% | 0.10 | No |
| ETH | 1,000× | Previous formula plus flat veto | 0 / 31 (0.00%) | 0 | 0.13% | 0.00% | 0.03 | No |
| ETH | 1,000× | Activity hurdle | 0 / 0 (—) | 0 | 0.00% | 0.00% | 0.00 | No |
| ETH | 1,000× | Calendar activity hurdle | 0 / 0 (—) | 0 | 0.00% | 0.00% | 0.00 | No |
| ETH | 1,000× | Conservative flat risk overlay | 0 / 0 (—) | 0 | 0.00% | 0.00% | 0.00 | No |
| HYPE | 100× | Previous fitted formula | 233 / 14,536 (1.60%) | 59 | 61.25% | 22.53% | 138.09 | No |
| HYPE | 100× | Previous formula plus flat veto | 233 / 14,536 (1.60%) | 59 | 61.25% | 22.53% | 138.09 | No |
| HYPE | 100× | Activity hurdle | 561 / 17,834 (3.15%) | 171 | 75.15% | 55.70% | 169.42 | No |
| HYPE | 100× | Calendar activity hurdle | 567 / 16,595 (3.42%) | 162 | 69.93% | 51.20% | 157.65 | No |
| HYPE | 100× | Conservative flat risk overlay | 219 / 13,032 (1.68%) | 55 | 54.92% | 21.85% | 123.80 | No |
| HYPE | 1,000× | Previous fitted formula | 0 / 17 (0.00%) | 0 | 0.07% | 0.00% | 0.02 | No |
| HYPE | 1,000× | Previous formula plus flat veto | 0 / 17 (0.00%) | 0 | 0.07% | 0.00% | 0.02 | No |
| HYPE | 1,000× | Activity hurdle | 0 / 0 (—) | 0 | 0.00% | 0.00% | 0.00 | No |
| HYPE | 1,000× | Calendar activity hurdle | 0 / 0 (—) | 0 | 0.00% | 0.00% | 0.00 | No |
| HYPE | 1,000× | Conservative flat risk overlay | 0 / 0 (—) | 0 | 0.00% | 0.00% | 0.00 | No |

## Earlier monthly comparisons

July 2025 through August 2026 supplies fourteen earlier out-of-sample dates per asset. The first six months are fit warmup; every subsequent month is scored using only its preceding dates. These comparisons do not select a variant. First-of-month sampling is not consecutive recording, and early 1,000× origins can lack positive-tail training support. Empty quote dates remain failures under the unchanged screens.

| Asset | Payout | Formula | Wins / quotes and rate | Availability | Worst date availability | LP gross per stake |
| --- | --- | --- | ---: | ---: | ---: | ---: |
| ETH | 100× | Previous fitted formula | 184 / 19,833 (0.93%) | 51.70% | 2.78% | 7.23% |
| ETH | 100× | Previous formula plus flat veto | 130 / 19,696 (0.66%) | 51.35% | 2.78% | 34.00% |
| ETH | 100× | Activity hurdle | 240 / 16,487 (1.46%) | 42.98% | 0.00% | -45.57% |
| ETH | 100× | Calendar activity hurdle | 233 / 12,453 (1.87%) | 32.46% | 0.00% | -87.10% |
| ETH | 100× | Conservative flat risk overlay | 57 / 9,241 (0.62%) | 24.09% | 0.00% | 38.32% |
| ETH | 1,000× | Previous fitted formula | 50 / 204 (24.51%) | 0.53% | 0.00% | -24409.80% |
| ETH | 1,000× | Previous formula plus flat veto | 0 / 72 (0.00%) | 0.19% | 0.00% | 100.00% |
| ETH | 1,000× | Activity hurdle | 0 / 0 (—) | 0.00% | 0.00% | — |
| ETH | 1,000× | Calendar activity hurdle | 0 / 0 (—) | 0.00% | 0.00% | — |
| ETH | 1,000× | Conservative flat risk overlay | 0 / 0 (—) | 0.00% | 0.00% | — |
| HYPE | 100× | Previous fitted formula | 143 / 34,551 (0.41%) | 90.11% | 46.95% | 58.61% |
| HYPE | 100× | Previous formula plus flat veto | 143 / 34,551 (0.41%) | 90.11% | 46.95% | 58.61% |
| HYPE | 100× | Activity hurdle | 208 / 34,754 (0.60%) | 90.64% | 65.37% | 40.15% |
| HYPE | 100× | Calendar activity hurdle | 206 / 34,042 (0.61%) | 88.78% | 65.37% | 39.49% |
| HYPE | 100× | Conservative flat risk overlay | 124 / 32,742 (0.38%) | 85.39% | 45.29% | 62.13% |
| HYPE | 1,000× | Previous fitted formula | 0 / 163 (0.00%) | 0.43% | 0.00% | 100.00% |
| HYPE | 1,000× | Previous formula plus flat veto | 0 / 163 (0.00%) | 0.43% | 0.00% | 100.00% |
| HYPE | 1,000× | Activity hurdle | 0 / 0 (—) | 0.00% | 0.00% | — |
| HYPE | 1,000× | Calendar activity hurdle | 0 / 0 (—) | 0.00% | 0.00% | — |
| HYPE | 1,000× | Conservative flat risk overlay | 0 / 0 (—) | 0.00% | 0.00% | — |

## Availability without a book requirement

The secondary cohort includes all clean oracle paths. Missing books stay in the availability denominator, and every formula here refuses them because each requires measured liquidity inputs or the same common book requirement. No unavailable entry is silently treated as a flat win. Full daily and calendar results are retained for both cohorts.

| Asset | Payout | Formula | Weekday availability on all clean paths | Weekend availability on all clean paths |
| --- | --- | --- | ---: | ---: |
| ETH | 100× | Previous fitted formula | 46.26% | 12.98% |
| ETH | 100× | Previous formula plus flat veto | 46.15% | 11.83% |
| ETH | 100× | Activity hurdle | 42.35% | 25.14% |
| ETH | 100× | Calendar activity hurdle | 38.79% | 18.89% |
| ETH | 100× | Conservative flat risk overlay | 26.42% | 5.91% |
| ETH | 1,000× | Previous fitted formula | 0.24% | 1.00% |
| ETH | 1,000× | Previous formula plus flat veto | 0.14% | 0.00% |
| ETH | 1,000× | Activity hurdle | 0.00% | 0.00% |
| ETH | 1,000× | Calendar activity hurdle | 0.00% | 0.00% |
| ETH | 1,000× | Conservative flat risk overlay | 0.00% | 0.00% |
| HYPE | 100× | Previous fitted formula | 57.38% | 38.71% |
| HYPE | 100× | Previous formula plus flat veto | 57.38% | 38.71% |
| HYPE | 100× | Activity hurdle | 66.73% | 61.95% |
| HYPE | 100× | Calendar activity hurdle | 63.81% | 50.87% |
| HYPE | 100× | Conservative flat risk overlay | 52.18% | 31.84% |
| HYPE | 1,000× | Previous fitted formula | 0.08% | 0.00% |
| HYPE | 1,000× | Previous formula plus flat veto | 0.08% | 0.00% |
| HYPE | 1,000× | Activity hurdle | 0.00% | 0.00% |
| HYPE | 1,000× | Calendar activity hurdle | 0.00% | 0.00% |
| HYPE | 1,000× | Conservative flat risk overlay | 0.00% | 0.00% |

## Interpretation and verification

Refusing an already-flat oracle addresses the identified admission failure. It cannot predict every transition from active to flat, establish a rare-event probability from a small sample, or create a valid positive-width quote when estimated unavoidable survival already exceeds the payout target. Wider or narrower corridors do not remove a zero-motion winner.

The existing necessary screens are unchanged: quotes on every date, at least 85 percent availability on every date, pooled survival within 75–125 percent of target, nonnegative zero-cost LP gross and at least twenty target-expected evaluated wins. A 1,000× rule needs at least 21,053 accepted resolved quotes to reach the last count reference. These are descriptive checks, rather than proof of independent-event confidence or deployability. The two September weekend dates and repeatedly inspected outcomes remain material limits.

LP gross assumes one stake unit per accepted resolved quote, total payout including returned stake, and `quotes − M × trader wins`. Gross per stake divides this by quote count. It excludes fees, hedging, funding, latency, underwriting capacity and correlated capital losses. Empty quote sets have no estimated win rate or return. This is an oracle-path formula replay rather than a full production engine or canonical-admission simulation.

The audit passed: 48 earlier-only floor models refitted, all positive CDF points/date weights verified, 1,074,440 decisions independently replayed, and all daily/calendar/cohort summaries reconciled. The previous September baseline was reproduced exactly. Five new focused tests cover the falsely safe frozen-oracle regression, recovery boundaries, asset/date isolation, future-label invariance, date weighting, midnight maturity and complete fit/export/audit/tamper rejection.

Research packet: `/Volumes/dev/fuse/.local/adaptive-corridor/20261029-flat-aware-payout-v1`. Previous payout packet: `/Volumes/dev/fuse/.local/adaptive-corridor/20261029-consecutive-payout-v1`. The new protocol and complete local Python source snapshot were frozen before fitting and replay. Every origin model, refused/unresolved decision and cohort summary is retained. The live formula and ongoing fresh collector were not changed.

```sh
PYTHONPATH=scripts OPENBLAS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 python3 -B -m unittest scripts.test_flat_aware_payout
python3 -B scripts/research_flat_aware_payout.py --declare --previous /Volumes/dev/fuse/.local/adaptive-corridor/20261029-consecutive-payout-v1 --output .local/adaptive-corridor/NEW-FLAT-AWARE-PAYOUT
OPENBLAS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 python3 -B scripts/research_flat_aware_payout.py --output .local/adaptive-corridor/NEW-FLAT-AWARE-PAYOUT
OPENBLAS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 python3 -B scripts/research_flat_aware_payout.py --audit --output .local/adaptive-corridor/NEW-FLAT-AWARE-PAYOUT
```

Research SHA-256: `39c072b1ce72af0b2e11568b5b8779b0ab65ea84020decd6d715820ef15cd757`. Audit SHA-256: `cf813a8bc3f6f74a29fae2050d84b3a566f9f5ef629a3f1bd3c867b8f8ea8057`.


Conservative overlay packet: `/Volumes/dev/fuse/.local/adaptive-corridor/20261029-flat-risk-overlay-v1`. Its separate audit independently replayed 268,610 decisions and verified the subset/width invariant on every offered quote. Three additional tests cover risk non-decrease, width tightening, unchanged missing-book refusal, future-outcome invariance and independent replay across payout and flat states.

```sh
PYTHONPATH=scripts OPENBLAS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 python3 -B -m unittest scripts.test_flat_risk_overlay
python3 -B scripts/research_flat_risk_overlay.py --declare --parent .local/adaptive-corridor/NEW-FLAT-AWARE-PAYOUT --output .local/adaptive-corridor/NEW-FLAT-RISK-OVERLAY
OPENBLAS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 python3 -B scripts/research_flat_risk_overlay.py --output .local/adaptive-corridor/NEW-FLAT-RISK-OVERLAY
OPENBLAS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 python3 -B scripts/research_flat_risk_overlay.py --audit --output .local/adaptive-corridor/NEW-FLAT-RISK-OVERLAY
```

Overlay research SHA-256: `eb0573e03f6336346f9fa6b8aefa41aa79e8179ee22aa7a2b5544268738a4e1d`. Overlay audit SHA-256: `5ce1dcf8f8e08b6889dbb785f91b008d0a577272a34369a42f121e1875cc57fa`.
