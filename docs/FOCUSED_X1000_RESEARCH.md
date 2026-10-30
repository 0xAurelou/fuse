# Focused X1000 iteration: HYPE price steps and frozen ETH validation

This iteration leaves X100 and the ETH formula unchanged. It diagnoses the five remaining September HYPE X1000 wins, tests one strictly pre-entry width cap, and freezes the ETH global-calibration candidate before its first replay on the finalized native capture prefix. Neither model is promoted to live pricing.

## Main findings

HYPE cap: trader survival changes from 0.169% (5 / 2,964) to 0.067% (2 / 2,964); accepted-quote availability stays 12.490%. The target is 0.095%. Every admission/refusal decision and daily availability count is unchanged. The smaller positive-width barriers remove tiny-movement winners; they cannot remove flat-path winners.

ETH frozen native-prefix replay: 0 / 288 (0.000%), with 64.000% availability among clean paths with fresh books. This is an out-of-time replay of data that already existed before the declaration, not pre-event recorded predictions or complete-day prospective validation. Sparse wins and partial capture coverage limit interpretation.

## What the five HYPE wins show

Two winning paths have zero oracle movement. Three have a maximum excursion of exactly 500 native price units, or 0.0005 HYPE. Every one of the five had six to nine price changes in the preceding thirty seconds and an idle age below two seconds. An already-flat entry veto does not explain these future transitions.

| Entry UTC | Future excursion units | Changes in prior 30s | Pre-entry idle ms | Observed step GCD | Original price delta | Capped price delta | Wins after cap |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 2026-09-02T17:16:00+00:00 | 0 | 9 | 454 | 100 | 384 | 100 | Yes |
| 2026-09-03T15:01:30+00:00 | 500 | 9 | 628 | 100 | 854 | 100 | No |
| 2026-09-03T16:15:00+00:00 | 500 | 9 | 1696 | 100 | 990 | 100 | No |
| 2026-09-03T20:09:00+00:00 | 500 | 8 | 478 | 100 | 2096 | 100 | No |
| 2026-09-07T05:20:00+00:00 | 0 | 6 | 446 | 100 | 207 | 100 | Yes |

## Targeted HYPE revision

The base is the audited joint_online_full formula, with all its volatility/activity/liquidity coefficients and delayed feedback parameters unchanged. Estimate the greatest common divisor of positive oracle price changes in the preceding five minutes, using receipts strictly before entry. Require four changes, five minutes of observed history since the last reset and an oracle receipt within eight seconds. Disconnect markers, greater-than-eight-second gaps and UTC day boundaries reset estimation. No future excursion or future validity enters the estimate.

Where supported and representable, cap native integer ppb width at `floor(((observed_step + 1) × 10^9 − 1) / entry_price_units)`. This is the largest width whose actual integer price delta is at most one observed step. Touching loses. Existing narrower quotes stay narrower, unsupported estimates retain the original width, and no zero-width offer is forced. Every offered/refused and unresolved entry remains identical to the baseline.

The first step-estimator audit found that equal-millisecond oracle updates were being sorted by price while merging reset markers. Version 2 preserves their original receipt order and gives only reset markers priority at an equal timestamp. The earlier failed implementation is retained; no model, threshold or cap parameter was changed. The new equal-timestamp regression case is covered by tests.

The observed GCD is a feature of earlier receipts, not a guaranteed exchange tick rule or a promise about future oracle precision. This cap was motivated by the five inspected wins, declared before its own replay, and remains outcome-informed development. It narrows the product: preserving quote counts does not mean preserving quoted widths.

| Group | Baseline wins / quotes (rate) | Capped wins / quotes (rate) | Availability before / after | Mean width ppm before / after |
| --- | ---: | ---: | ---: | ---: |
| overall | 5 / 2,964 (0.169%) | 2 / 2,964 (0.067%) | 12.490% / 12.490% | 11.597 / 1.196 |
| weekday | 5 / 2,727 (0.183%) | 2 / 2,727 (0.073%) | 14.417% / 14.417% | 11.972 / 1.201 |
| weekend | 0 / 237 (0.000%) | 0 / 237 (0.000%) | 4.921% / 4.921% | 7.289 / 1.141 |

2,934 clean accepted quotes receive a narrower barrier. Flat wins after the cap: 2. Target-expected evaluated wins remain 2.816, below the unchanged twenty-event reference. A point estimate closer to 0.095% is not rare-event calibration evidence.

| UTC date | Quotes before / after | Wins before / after | Quote availability |
| --- | ---: | ---: | ---: |
| 2026-09-01 | 636 / 636 | 0 / 0 | 26.478% |
| 2026-09-02 | 69 / 69 | 1 / 1 | 2.902% |
| 2026-09-03 | 392 / 392 | 3 / 0 | 16.313% |
| 2026-09-04 | 230 / 230 | 0 / 0 | 9.816% |
| 2026-09-05 | 4 / 4 | 0 / 0 | 0.168% |
| 2026-09-06 | 233 / 233 | 0 / 0 | 9.581% |
| 2026-09-07 | 547 / 547 | 1 / 1 | 23.070% |
| 2026-09-08 | 119 / 119 | 0 / 0 | 5.099% |
| 2026-09-09 | 207 / 207 | 0 / 0 | 8.723% |
| 2026-09-10 | 527 / 527 | 0 / 0 | 22.804% |

## Frozen ETH candidate and fresh-prefix boundary

Freeze the joint_global recipe selected from the September development comparisons. Fit one as-of origin at 2026-10-28 using only the audited older/monthly and September inputs: the last ten observed admissible training dates are September 1–10. Calendar/global calibration uses only earlier out-of-sample references from those audited historical packets. No native capture data enters fitting or calibration. Coefficients, calibration budgets and source closure are frozen before native outcome scoring. The candidate is not retuned after viewing this prefix.

The original model was frozen at 2026-10-29 09:21:24 UTC. The finalized index prefix contains 103 segments and 408,112 hash-linked receipts. The pricing timeline spans 2026-10-28 17:54:37 UTC through 2026-10-29 09:16:07 UTC. Evaluation ends at 2026-10-29 09:16:00 UTC; the active open segment and incomplete final corridor are excluded. Complete UTC days: 0. Fresh HYPE outcomes are not built.

The initial reader rejected two timestamp backsteps, of 14 and 28 milliseconds, among unrelated WebSocket receipts. The parser amendment verifies every original record and uses only ETH oracle/book and reset-control receipts to advance the pricing timeline. Those required receipts are strictly ordered. No required ETH price message is sorted or discarded; a regression in that stream still fails validation. The amended packet reuses byte-identical model parameters and the exact original capture prefix. Both versions are retained.

Connection/host gaps and resets censor oracle outcomes and subsequent feature warmup. Missing or stale books refuse quotes. Data gaps are never interpolated or treated as zero-motion winners. Native source timestamps are floored to milliseconds to match the historical feature/entry interface; this is a single-receiver oracle-path replay, not canonical paired-receiver settlement.

| UTC day | Grid entries | Clean oracle paths with history | Clean paths with fresh books | ETH accepted quotes | ETH wins | Availability on matched paths |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 2026-10-28 | 731 | 417 | 354 | 244 | 0 | 68.927% |
| 2026-10-29 | 1,112 | 112 | 96 | 44 | 0 | 45.833% |

Across the full capture grid, 529 / 1,843 entries (28.703%) have clean oracle paths and sufficient history; 450 have fresh books. Resolved quotes divided by the entire grid are 15.627%. This separate coverage measure keeps outages visible instead of reporting only availability conditional on healthy feeds.

Frozen ETH evaluated quotes: 288; observed wins: 0; target-expected wins: 0.274. This prefix cannot establish a 0.095% tail. It contains no complete-day or fresh weekend comparison; the original collector continues unchanged and its later holdout has not been inspected.

## Verification and next evaluation boundary

The HYPE audit independently reconstructs the raw pre-entry step estimates with indexed historical slices and replays 28,800 capped decisions. It verifies baseline reproduction, unchanged daily availability, non-increasing widths and a subset of baseline wins. The ETH audit refits the candidate from historical inputs only, reconstructs every finalized raw receipt, independently checks strict book joins and replays 1,843 frozen decisions. Fifty-eight regression tests pass across the existing research stack and the new frozen-prefix/parser/step-cap cases.

ETH remains frozen after this replay. HYPE is a focused development candidate; its next validation must use uninspected data with this rule fixed. Neither the five motivating wins nor the same September replay becomes a new holdout. The unchanged original daily availability, target band, gross arithmetic and twenty-target-expected-event screens still apply; no successful operating regime is certified.

ETH packet: `/Volumes/dev/fuse/.local/adaptive-corridor/20261029-frozen-ETH-x1000-v2`. Candidate SHA-256: `3d6721935f29af9af91b433e6962c1a9b0b7cbb643abf0b2c6c50d129486a8e6`. Research SHA-256: `d6086e842281278c4ef032807a1ab479363c11b2992620104c07dbc011dcdb71`. Audit SHA-256: `5b51a3bddcfd71aa7efbaa8b2ec997e736f281bda6ee781b9ed7eb72c0cc1e88`. Original freeze: `/Volumes/dev/fuse/.local/adaptive-corridor/20261029-frozen-ETH-x1000-v1`.

HYPE packet: `/Volumes/dev/fuse/.local/adaptive-corridor/20261029-HYPE-step-cap-v2`. Research SHA-256: `acaafdc75cc285263b276dd477a949d1757241c34ad547075647d672ccc151d6`. Audit SHA-256: `a65eff708fb1cf1ffd43d8a82f5f49b1180c41bbdbd1f05193e9b15af56fd80b`. Prior combined-model comparisons: [JOINT_X1000_RESEARCH.md](/Volumes/dev/fuse/docs/JOINT_X1000_RESEARCH.md).

```sh
PYTHONPATH=scripts OPENBLAS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 OMP_NUM_THREADS=1 python3 -B -m unittest scripts.test_historical_liquidity scripts.test_trial_liquidity scripts.test_trial_payout scripts.test_flat_aware_payout scripts.test_flat_risk_overlay scripts.test_active_tail_payout scripts.test_conditional_tail_payout scripts.test_volatility_open_gate scripts.test_joint_x1000 scripts.test_online_joint_x1000 scripts.test_frozen_eth_x1000 scripts.test_frozen_eth_x1000_v2 scripts.test_oracle_step_cap
python3 -B scripts/research_hype_step_cap_v2.py --declare --parent .local/adaptive-corridor/20261029-online-joint-x1000-v1 --amends .local/adaptive-corridor/20261029-HYPE-step-cap-v1 --output .local/adaptive-corridor/NEW-HYPE-STEP-CAP
OPENBLAS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 OMP_NUM_THREADS=1 python3 -B scripts/research_hype_step_cap_v2.py --output .local/adaptive-corridor/NEW-HYPE-STEP-CAP
OPENBLAS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 OMP_NUM_THREADS=1 python3 -B scripts/research_hype_step_cap_v2.py --audit --output .local/adaptive-corridor/NEW-HYPE-STEP-CAP
# The retained v1 candidate supplies the byte-identical model for this parser amendment.
python3 -B scripts/freeze_eth_x1000_v2.py --declare --frozen-parent .local/adaptive-corridor/20261029-frozen-ETH-x1000-v1 --output .local/adaptive-corridor/NEW-ETH-PREFIX
OPENBLAS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 OMP_NUM_THREADS=1 python3 -B scripts/freeze_eth_x1000_v2.py --output .local/adaptive-corridor/NEW-ETH-PREFIX
OPENBLAS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 OMP_NUM_THREADS=1 python3 -B scripts/freeze_eth_x1000_v2.py --audit --output .local/adaptive-corridor/NEW-ETH-PREFIX
python3 -B scripts/report_focused_x1000.py --eth .local/adaptive-corridor/NEW-ETH-PREFIX --hype .local/adaptive-corridor/NEW-HYPE-STEP-CAP --output docs/FOCUSED_X1000_RESEARCH.md
```
