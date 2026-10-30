# Historical ETH/HYPE liquidity-effect test — 29 October 2026

Historical spread and visible-depth data is available and was downloaded and tested immediately. Fresh consecutive recording can continue alongside it; a historical first pass does not require waiting for the fresh horizon.

ETH: adding the fixed liquidity features has an uncertain paired prediction effect in these historical development samples.
HYPE: adding the fixed liquidity features has an uncertain paired prediction effect in these historical development samples.

## Sources and sample

The study downloads every native `l2Book` slice for ETH and HYPE on the first UTC day of each month from January 2025 through October 2026. These 22 full sample days per asset match the existing raw-oracle archive. The 3,168 ten-minute gzip payloads are retained with request URLs, hashes, metadata and an immutable source snapshot. No API key, paid subscription or AWS billing credentials were used.

[Tardis Hyperliquid documentation](https://docs.tardis.dev/historical-data-details/hyperliquid) confirms raw native 20-level book history, asset coverage, BBO history and the switch to a separate fast five-level channel. The raw 20-level channel is used throughout. Normalized `book_snapshot_25` must not be interpreted as 25 actual levels: the provider documents that its newer normalized snapshots are built from the five-level fast stream.

The [Tardis raw API](https://docs.tardis.dev/api/http-api-reference) makes first-of-month histories available without authentication. Continuous dates beyond those free samples require another access route. [Hyperliquid also publishes historical L2 snapshots](https://hyperliquid.gitbook.io/hyperliquid-docs/historical-data) in its requester-pays S3 archive, with variable completeness and transfer charges. That paid route was not activated here.

| Asset | Matched source dates | Clean oracle paths | Paths with usable prior book | Match rate | Evaluated dates | Evaluated matched paths | Weekend / weekday evaluation dates |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| ETH | 22 | 61,689 | 60,242 | 97.65% | 16 | 43,152 | 4 / 12 |
| HYPE | 22 | 61,690 | 60,224 | 97.62% | 16 | 43,134 | 4 / 12 |

Each thirty-second entry joins the latest book received strictly before entry. Both receipt age and exchange timestamp must meet the frozen five-second freshness rule, with at most two seconds of forward exchange-clock tolerance. Disconnect markers clear book state conservatively before the next recorded message. Initial missing history, stale books, fewer than five visible levels and invalid books remain explicitly unavailable. No gap is interpolated and no book after entry is used. Raw order and entry-equality boundaries are tested.

Depth features are USD notional in the top five and twenty visible bid/ask levels, plus top-five imbalance. Spread is derived from the native book. The complete-case cohort is identical for all four models; book availability is not filled with zero. Full 1/5-bps band coverage is retained separately, and incomplete band depth is never presented as complete. These quantities measure one venue’s visible liquidity. They are not total market depth or execution costs.

## Paired chronological prediction

Each asset warms up on January–June 2025. July 2025–October 2026 are scored once per matched entry, with coefficients and standardization refitted only on earlier matured matched paths. Every fixed model uses ridge 0.003, equal training mass per date and standardized features clipped to ±5. The four comparisons are oracle activity, activity plus calendar, activity plus liquidity, and activity plus calendar plus liquidity. No model or feature combination is selected from the results.

The primary label is zero oracle movement over the next thirty seconds, because that was the main driver of the earlier high-payout wins. The one-ppm minimum-width label is secondary. This is an experiment about the flat-path mechanism; it does not fit payout widths, claim a calibrated 100×/1,000× quote or establish net LP returns.

The primary score is the equal-date average paired log-loss improvement when adding liquidity to the calendar/activity baseline. Positive improvement favors the added liquidity features. The descriptive interval resamples whole scored days 2,000 times with a frozen seed. It preserves within-day dependence but does not establish causal effects or independence across monthly market episodes.

| Asset | Mean daily baseline log loss | Mean daily with liquidity | Paired improvement | Relative improvement | Day-block 95% interval | Improved dates |
| --- | ---: | ---: | ---: | ---: | --- | ---: |
| ETH | 0.119222 | 0.119650 | -0.000427 | -0.36% | [-0.002665, +0.000920] | 10 / 16 |
| HYPE | 0.020978 | 0.021029 | -0.000050 | -0.24% | [-0.000137, +0.000021] | 7 / 16 |

| Asset | Fixed model | Pooled log loss | Pooled Brier score | Observed zero-motion rate | Mean forecast |
| --- | --- | ---: | ---: | ---: | ---: |
| ETH | activity | 0.117882 | 0.030646 | 3.7843% | 3.9535% |
| ETH | calendar | 0.118304 | 0.030686 | 3.7843% | 3.7886% |
| ETH | activity_liquidity | 0.118158 | 0.030519 | 3.7843% | 3.6796% |
| ETH | calendar_liquidity | 0.118642 | 0.030584 | 3.7843% | 3.5186% |
| HYPE | activity | 0.020814 | 0.004002 | 0.4080% | 0.5852% |
| HYPE | calendar | 0.020762 | 0.003980 | 0.4080% | 0.5632% |
| HYPE | activity_liquidity | 0.020846 | 0.003990 | 0.4080% | 0.5758% |
| HYPE | calendar_liquidity | 0.020816 | 0.003976 | 0.4080% | 0.5628% |

## Depth and calendar diagnostics

Low/middle/high depth groups use prior-training-only terciles of the minimum top-five side notional, separately for each asset and scoring origin. They are descriptive states, not recommended trading thresholds. The following observed rates can reflect volatility, oracle activity, market regime, timestamp and selection effects. Baseline versus augmented forecasts are included to show why a raw thin/deep rate difference alone is insufficient evidence.

| Asset | Group | Matched paths | Zero-motion rate | Calendar/activity forecast | With-liquidity forecast | Mean spread, bps | Mean minimum top-five side, USD |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| ETH | low | 13,151 | 2.2964% | 2.7571% | 2.4425% | 0.4125 | 198,829 |
| ETH | middle | 14,535 | 4.2862% | 3.9950% | 3.7067% | 0.4002 | 612,235 |
| ETH | high | 15,466 | 4.5778% | 4.4716% | 4.2570% | 0.4514 | 1,360,522 |
| ETH | weekday | 32,366 | 3.4975% | 3.6909% | 3.5251% | 0.4102 | 777,681 |
| ETH | weekend | 10,786 | 4.6449% | 4.0816% | 3.4993% | 0.4585 | 684,689 |
| HYPE | low | 8,534 | 0.3515% | 0.5471% | 0.5523% | 0.4951 | 3,231 |
| HYPE | middle | 12,268 | 0.4157% | 0.5752% | 0.5718% | 0.6007 | 7,435 |
| HYPE | high | 22,332 | 0.4254% | 0.5627% | 0.5619% | 0.6568 | 22,410 |
| HYPE | weekday | 32,363 | 0.4851% | 0.6370% | 0.6407% | 0.5367 | 14,968 |
| HYPE | weekend | 10,771 | 0.1764% | 0.3414% | 0.3290% | 0.8257 | 12,517 |

In these fixed cohorts, the low-depth group has a lower raw zero-motion rate than the high-depth group in both assets. Weekend spreads are wider and visible top-five depth is lower on average for both assets, while the weekend zero-motion rate rises for ETH and falls for HYPE. These descriptive patterns do not support a single thin-weekend-liquidity rule across both assets. They also do not prove that liquidity has no effect: the specified linear/logistic feature additions, visible depth bound, sample dates and oracle process limit the test.

These are sampled first-of-month days, not consecutive weeks. Their oracle outcomes overlap an already inspected development research program. The coefficient fits are chronological, but this is not a pristine holdout of the entire research process. Only four evaluated weekend dates per asset are available. Neither the calendar comparison nor the depth strata identify liquidity as the cause of a weekend win cluster. The fresh consecutive collection remains useful for evaluating transfer and within-week variation.

## Artifacts and verification

Research packet: `.local/adaptive-corridor/20261029-historical-liquidity-effect-v1`. Raw books: `/Volumes/dev/fuse/.local/market-history/tardis-hyperliquid-ETH-HYPE-books-monthly-v1`. Original oracle fits and the fresh ETH/HYPE recorder were not changed.

`protocol.json` freezes sources and the test before joining or fitting. `joined.jsonl.gz` retains all fixed-grid book matches/reasons and book provenance. `coverage.json` retains date/asset attrition. Each asset retains all origin models, predictions, paired daily scores, depth/calendar strata and research metadata.

The audit reconstructs all 126,720 grid joins from 3,168 hashed raw book payloads, refits every saved model from strictly earlier labels, replays 345,144 forecasts and reconciles paired metrics and day-block intervals. Six focused tests cover timestamp equality, freshness, feed identity, disconnect censorship, future-label exclusion, paired model populations and complete fit/export/audit coverage. The full Python suite ran 436 tests, with 10 skips and all others passing.

```sh
python3 -B scripts/fetch_historical_liquidity.py --directory .local/market-history/NEW-BOOKS --metadata .local/market-history/tardis-hyperliquid-ETH-HYPE-monthly-raw-v1/exchange-metadata.json
python3 -B scripts/fetch_historical_liquidity.py --directory .local/market-history/NEW-BOOKS --fetch
python3 -B scripts/research_historical_liquidity.py --declare --parent .local/adaptive-corridor/20261028-ETH-HYPE-raw-fits-v2 --books .local/market-history/NEW-BOOKS --output .local/adaptive-corridor/NEW-LIQUIDITY
OPENBLAS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 python3 -B scripts/research_historical_liquidity.py --output .local/adaptive-corridor/NEW-LIQUIDITY
OPENBLAS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 python3 -B scripts/audit_historical_liquidity.py --research .local/adaptive-corridor/NEW-LIQUIDITY
python3 -B -m unittest discover -s scripts -p test_historical_liquidity.py
```
