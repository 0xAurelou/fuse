# Consecutive ETH and HYPE oracle and liquidity test

September 1–10, 2026 UTC provides ten consecutive dates of native Hyperliquid oracle updates and visible books. The study tests whether measured liquidity improves prediction of zero oracle movement over thirty seconds after accounting for oracle activity and UTC calendar. The evidence covers two weekend dates, September 5 and 6, and is historical development.

ETH: adding the fixed liquidity features improves mean daily prediction loss by +0.26%; its descriptive day-bootstrap interval includes zero. HYPE: adding the fixed liquidity features improves mean daily prediction loss by +0.44%; its descriptive day-bootstrap interval is above zero.

## Data and coverage

The authorized Tardis free trial supplied all 1,440 requested ten-minute slices: 139.75 MB compressed and 1.093 GB decoded. The key remained local. No purchase, upgrade or billing change was made. These dates are earlier than the separate September 30–October 27 book archive; they supply the matched high-frequency oracle data needed for this immediate test.

[Tardis raw Hyperliquid documentation](https://docs.tardis.dev/historical-data-details/hyperliquid) describes `activeAssetCtx` and native 20-level `l2Book`. The study uses actual `ctx.oraclePx`, with original receipt timestamps and disconnect markers. Mark prices, trades and candle prices never substitute for the oracle. [Trial terms](https://docs.tardis.dev/faq/billing-and-subscriptions) specify the first ten dates of the preceding UTC month.

| Asset | Oracle messages | Native book messages | Grid paths | Clean oracle paths | With usable prior book | Match rate among clean |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| ETH | 845,628 | 160,908 | 28,800 | 27,121 | 23,734 | 87.51% |
| HYPE | 845,534 | 160,883 | 28,800 | 27,121 | 23,731 | 87.50% |

Oracle cadence is approximately one update per second. Missing data is not a flat win: original eight-second oracle freshness and disconnect censorship apply to outcomes and history. Each entry uses the latest native book received strictly before entry, at most five seconds old by receipt and exchange timestamp, with at most two seconds of exchange-clock forward tolerance. Books at entry equality or later are excluded. Depth is visible top-five and top-twenty bid/ask USD notional, rather than whole-market or executable depth.

| Asset | Median oracle gap across dates in ms | Largest oracle gap in seconds | Gaps over eight seconds | Oracle disconnect markers |
| --- | --- | ---: | ---: | ---: |
| ETH | 1014–1018 | 127.669 | 3 | 154 |
| HYPE | 1015–1018 | 127.881 | 4 | 154 |

## Chronological comparison

Each asset starts with twenty matched first-of-month dates from January 2025 through August 2026. All ten trial dates are evaluated once. At each UTC daily origin, coefficients, normalization and depth terciles use only earlier labels whose expiry plus thirty seconds is strictly before the origin. Subsequent days add earlier trial data. Context resets daily. This preserves both weekend days for evaluation.

Four fixed logistic models use the identical complete-case cohort: activity, activity plus calendar, activity plus liquidity, and activity plus calendar plus liquidity. Ridge is fixed at 0.003, training mass is equal per date and standardized features are clipped to ±5. No feature or model was selected from trial results. The primary score is the equal-day mean paired zero-motion log-loss improvement of calendar plus liquidity over calendar. Positive improvement favors liquidity. The interval resamples scored dates 2,000 times with a fixed seed and is descriptive.

| Asset | Mean daily baseline loss | Mean daily loss with liquidity | Paired improvement | Relative improvement | Day bootstrap 95% interval | Improved dates |
| --- | ---: | ---: | ---: | ---: | --- | ---: |
| ETH | 0.073695 | 0.073506 | +0.000189 | +0.26% | [-0.000050, +0.000428] | 8 / 10 |
| HYPE | 0.087984 | 0.087594 | +0.000390 | +0.44% | [+0.000087, +0.000727] | 7 / 10 |

| Asset | Model | Pooled zero-motion log loss | Pooled Brier score | Observed zero-motion rate | Mean forecast |
| --- | --- | ---: | ---: | ---: | ---: |
| ETH | activity | 0.074396 | 0.015740 | 1.6011% | 2.5692% |
| ETH | calendar | 0.073928 | 0.015763 | 1.6011% | 2.5167% |
| ETH | activity_liquidity | 0.074309 | 0.015697 | 1.6011% | 2.5094% |
| ETH | calendar_liquidity | 0.073736 | 0.015706 | 1.6011% | 2.4411% |
| HYPE | activity | 0.088151 | 0.020514 | 2.1912% | 1.8673% |
| HYPE | calendar | 0.088114 | 0.020508 | 2.1912% | 1.8373% |
| HYPE | activity_liquidity | 0.087770 | 0.020521 | 2.1912% | 1.9820% |
| HYPE | calendar_liquidity | 0.087724 | 0.020524 | 2.1912% | 1.9599% |

The gains are small. HYPE has a positive descriptive interval for the primary log-loss improvement, while its pooled Brier score is slightly worse with liquidity. ETH’s interval includes zero. These results support further testing of the asset-specific fits rather than adopting a common weekend adjustment.

## Weekend and depth diagnostics

Zero-motion rates below pool matched paths. Liquidity averages give each included date equal weight. Low, middle and high depth groups use only earlier-training terciles of minimum top-five side notional. These are associations and do not identify liquidity as the cause of corridor wins.

| Asset | Group | Dates | Matched paths | Zero-motion paths | Zero-motion rate | Calendar forecast | With liquidity forecast | Equal-day spread in bps | Equal-day minimum top-five side in USD |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| ETH | weekday | 8 | 18,923 | 152 | 0.8033% | 1.5909% | 1.5428% | 0.4197 | 605,714 |
| ETH | weekend | 2 | 4,811 | 228 | 4.7391% | 6.1583% | 5.9743% | 0.4075 | 587,200 |
| ETH | low | 10 | 7,966 | 100 | 1.2553% | 2.1226% | 1.9534% | 0.4269 | 258,039 |
| ETH | middle | 10 | 11,420 | 207 | 1.8126% | 2.6800% | 2.6074% | 0.4113 | 626,126 |
| ETH | high | 10 | 4,348 | 73 | 1.6789% | 2.8097% | 2.8979% | 0.4167 | 1,190,588 |
| HYPE | weekday | 8 | 18,915 | 328 | 1.7341% | 1.4895% | 1.5924% | 0.2193 | 14,015 |
| HYPE | weekend | 2 | 4,816 | 192 | 3.9867% | 3.2033% | 3.4033% | 0.1811 | 13,070 |
| HYPE | low | 10 | 6,604 | 139 | 2.1048% | 1.8522% | 2.0281% | 0.2103 | 3,602 |
| HYPE | middle | 10 | 7,709 | 152 | 1.9717% | 1.7909% | 1.9092% | 0.2148 | 8,819 |
| HYPE | high | 10 | 9,418 | 229 | 2.4315% | 1.8647% | 1.9537% | 0.2101 | 25,024 |

Both assets have higher weekend zero-motion rates in these consecutive matched paths, and both also have zero-motion weekday paths. Weekend spreads are tighter and minimum visible top-five depth is only modestly lower. The low-depth strata do not have the highest flat-path rates. This combination does not support a universal thin-weekend-liquidity explanation.

Only two weekend dates are present. Adjacent dates can share a regime, and earlier monthly oracle outcomes, including September 1, were already inspected in this research program. Chronological fitting does not make the whole research process an untouched holdout. The specified feature additions can show predictive association; they cannot establish that weekend liquidity causes wins or that liquidity has no effect.

Zero movement is the survival floor for any positive-width corridor under the original oracle settlement rule. The one-ppm floor metrics are retained as a secondary outcome in the packet. This experiment does not fit payout widths, test quoted 100× or 1,000× returns, or validate a live pricing change. The ongoing fresh collector and live formulas remain unchanged.

## Artifacts and verification

Research packet: `/Volumes/dev/fuse/.local/adaptive-corridor/20261029-consecutive-trial-liquidity-v2`. Raw history: `/Volumes/dev/fuse/.local/market-history/tardis-ETH-HYPE-consecutive-trial-v1`. The packet retains its protocol and source snapshot, all 57,600 grid rows including exclusions, date-level coverage, eighty fitted origin models, paired forecasts, scores and a replay audit. Raw hashes and exact requests are bound to the frozen download declaration.

The audit passed: 57,600 grid rows reconstructed from 1,440 raw slices; 80 models refitted from earlier matured labels; 189,860 predictions manually replayed. Paired metrics, training-only depth thresholds and all retained coverage were reconciled. Nine focused downloader/reader/model tests cover access bounds, gzip integrity, strict entry joins, stale/disconnected exclusions, future-price invariance and midnight label maturity.

The initial implementation declaration remains in the sibling `20261029-consecutive-trial-liquidity-v1` packet. Its validator stopped at the second daily origin because the last two previous-day paths had not matured. Version 2 filters those candidates before validation and explicitly binds the earlier declaration; it preserves the original model and feature choices.

```sh
PYTHONPATH=scripts python3 -B -m unittest scripts.test_tardis_liquidity_trial scripts.test_trial_liquidity
python3 -B scripts/research_trial_liquidity.py --declare --parent /Volumes/dev/fuse/.local/adaptive-corridor/20261028-ETH-HYPE-raw-fits-v2 --monthly /Volumes/dev/fuse/.local/adaptive-corridor/20261029-historical-liquidity-effect-v1 --raw /Volumes/dev/fuse/.local/market-history/tardis-ETH-HYPE-consecutive-trial-v1 --output .local/adaptive-corridor/NEW-TRIAL-REPLAY
OPENBLAS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 python3 -B scripts/research_trial_liquidity.py --output .local/adaptive-corridor/NEW-TRIAL-REPLAY
OPENBLAS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 python3 -B scripts/research_trial_liquidity.py --audit --output .local/adaptive-corridor/NEW-TRIAL-REPLAY
```

Research SHA-256: `3619688c3e84bb6f169e6990e0a63978baf27edece15ef9d0fff539d020492d9`. Audit SHA-256: `0a3af733a29dd87d9a89de0408ab0c887dfe7b9017aad097ebc768d631db8cd5`.
