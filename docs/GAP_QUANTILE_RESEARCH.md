# Oracle–mark gaps and adaptive quantile tracking — 28 October 2026

Follow-up: the [isolated bursty-feedback comparison](BURSTY_FEEDBACK_RESEARCH.md) freezes these fits and removes active/sparse correction transfer. The pooled bursty variant improves earlier selection and recovers some phase calibration, but June later survival remains 8/22 and broader passes remain below retained. No successor or capture is approved.

The proposed experiment is implemented and replayed. A matched comparison tests the retained benchmark, a timing-only conditional quantile, the same model with oracle–mark gaps, and an adaptive version of each quantile model. **The retained benchmark still wins earlier selection, 20.812 versus 24.431–25.132.** January 2025 startup survival falls, but June later survival stays **8/22 = 36.36%** in both modes. Lower aggregate pricing loss does not translate into stable case calibration. No successor is frozen or promoted and no capture starts.

## Inputs and controlled comparison

All inputs come from saved data. The raw `activeAssetCtx` messages contain `oraclePx`, `markPx` and `midPx`; the existing normalized derivative-ticker files contain their corresponding index and mark fields. Across twelve raw sample dates, **458,628 shared timestamps have zero oracle mismatches and zero mark mismatches**. Compressed-response hashes and gzip CRCs remain verified. No downloads, credentials or paid endpoints are needed.

Mark price is the primary market input because it is available in both source formats. Mid-price gaps are retained as diagnostics on raw data and do not enter this experiment's model. Market prices never replace the oracle in path labels, entry prices or barrier checks.

The new feature allowlist adds five values to the existing eleven timing/volatility features:

1. Signed mark/oracle gap.
2. Absolute mark/oracle gap.
3. Change in that gap over thirty seconds.
4. Signed mark-price movement over thirty seconds.
5. Absolute mark-price movement over thirty seconds.

Each is expressed in ppm, divided by the pre-entry slow-volatility scale with a one-ppm floor, and transformed with `asinh`. Standardization and clipping parameters come only from earlier training data. Current and lagged receipts must each be fresh within eight seconds and strictly precede their respective entry/lookback endpoints. Neither receipt may precede the session's retained feature-history boundary. A receipt arriving exactly at entry is excluded.

The raw training universe remains the eight full raw days already saved, replacing matching dates within the original fourteen-date training universe. Remaining training dates use normalized context. Each date counts once. The final timing and gap models both fit **31,262 clean non-frozen reference paths, including 888 bursty paths**. June 2025 models both fit **18,713 / 605**; January 2025 models both fit **5,379 / 131**. Matched training support isolates the effect of the five new features.

Missing or stale market context falls back to the retained quote. The two native paired-capture panels have no attached historical market context and remain unchanged; this experiment establishes no transfer of the new features to native capture. The evaluated prediction archive has 7,388 eligible bursty records across both frozen policies and overlapping panels; **7,334 have usable context** and 54 fall back. These are repeated records, not independent paths. All 427 original raw restart bursty paths have usable context.

## Mathematical model

Let (R_t) be the smallest integer ppm halfwidth surviving the entire subsequent thirty-second oracle path. The conditional target is the 48th percentile of (R_t), subject to integer width bounds and its probability mass at the minimum width.

The model first estimates

\[
\hat p_0(x)=P(R_t\leq1\mid x),\qquad
\tau_+(x)=\operatorname{clip}\left(\frac{0.48-\hat p_0(x)}{1-\hat p_0(x)},0.02,0.98\right).
\]

A ridge-regularized logistic model estimates the minimum-width probability. A regularized iteratively reweighted quantile fit estimates the conditional log ratio of required width to retained benchmark width on positive-movement paths, using the adjusted quantile level. The predictor also includes the retained width relative to slow volatility. This log transform preserves quantile ordering; the numerical fit is regularized and approximate, not an exact finite-sample calibration guarantee.

If predicted minimum-width survival already reaches 48%, the static forecast is one ppm. Otherwise the positive-movement forecast determines the width. The exact integer barrier rule and 50,000-ppm maximum remain fixed. Quantile training and all reference labels use the original oracle paths.

The adaptive versions add a delayed correction to log width. For a matured reference, the quantile-loss subgradient is

\[
g_t=\mathbb{1}\{R_t\leq w_t\}-0.48.
\]

Thus too many survivors decrease subsequent width and too few increase it. A discounted AdaGrad step scales the adjustment using accumulated squared gradients, with initial learning rate 0.2 and a one-hour half-life. The correction blends a shared non-frozen parent with a bursty cooling/balanced/fresh child, using matured child support and twelve prior observations. Log corrections are bounded to factors between one quarter and four. Anti-windup blocks adjustments that push farther past the allowed width/correction limits. Stale controller state resets after an hour without support.

Labels become usable **at expiry plus thirty seconds**. All clean references, including paused references, can teach the controller. For non-bursty paths it learns from the hypothetical quantile forecast while the actual quote retains benchmark pricing. Restart clears private controller state; continuous replay does not clear it at scoring boundaries. The floor-risk model remains fixed within each replay; adaptive tracking corrects prices, not its probability estimate.

This is a bounded, delayed quantile-tracking experiment inspired by online calibration. It does not implement the full conformal PID procedure or inherit a guarantee of exact coverage in every regime or eight-hour interval. The [quantile tracking/control paper](https://arxiv.org/abs/2307.16895) provides the relevant mathematical background.

## Chronological selection

Five variants were fixed before model fitting. The original six/nine/twelve-date prefixes, subsequent three/three/two normalized scoring dates, engines, loss guard, phase costs, availability costs and 95% pooled / 90% populated-case bursty retention limits remain unchanged. Raw evaluation outcomes never select a variant.

| Variant | Earlier score | Fold scores |
| --- | ---: | --- |
| Retained benchmark | **20.812** | 20.736 / 21.387 / 20.313 |
| Timing + adaptive | 24.431 | 26.460 / 19.980 / 26.854 |
| Gap quantile | 24.946 | 22.949 / 18.972 / 32.919 |
| Gap + adaptive | 24.993 | 29.470 / 18.972 / 26.538 |
| Timing quantile | 25.132 | 23.504 / 18.972 / 32.919 |

Lower is better. All retention constraints pass because admission is fixed. The retained benchmark reconstructs exactly. No new variant wins across the earlier folds. The timing/gap ablation measures a small feature effect within this model family; it does not establish that market information is generally unnecessary. These are repeatedly inspected developmental periods, not untouched independent holdouts.

## Focused January and June results

Each table entry is startup survival / later survival. Startup contains twelve paths; later groups contain 39 for January 2025, 22 for June 2025 and thirteen for January 2026. Phase membership is fixed before outcomes and refusal decisions.

| Variant | Jan 2025 restart | Jan 2025 continuous | June restart | June continuous | Jan 2026 restart / continuous |
| --- | ---: | ---: | ---: | ---: | ---: |
| Retained | 83.33% / 33.33% | 75.00% / 38.46% | 41.67% / 36.36% | 41.67% / 36.36% | 75.00% / 46.15% |
| Timing quantile | 75.00% / 41.03% | 66.67% / 43.59% | 41.67% / 36.36% | 41.67% / 36.36% | 75.00% / 46.15% |
| Timing + adaptive | 66.67% / 33.33% | 66.67% / 38.46% | 41.67% / 36.36% | 33.33% / 36.36% | 75.00% / 53.85% |
| Gap quantile | 66.67% / 38.46% | 66.67% / 43.59% | 41.67% / 36.36% | 41.67% / 36.36% | 75.00% / 46.15% |
| Gap + adaptive | 66.67% / 33.33% | 66.67% / 38.46% | 41.67% / 36.36% | 33.33% / 36.36% | 75.00% / 53.85% |

January 2025 startup moves closer to target, but remains outside the reference band. Its static continuous later phase reaches 17/39 = 43.59%; adaptive tracking removes that improvement. June later survival never changes from eight survivors. The gap adaptive later loss is **72.131 / 71.353 ppm**, versus retained **71.622 / 71.184 ppm**. The timing static version slightly lowers later loss to **71.384 / 71.042 ppm**, without gaining another survivor.

Focused diagnostics show that June's gap adaptive correction averages **0.877× static width in restart mode and 0.929× continuously**. It narrows nineteen/eighteen of the twenty-two later quotes despite this bursty group's low observed survival. Conversely January 2026 restart receives roughly **1.292× static width at startup and 1.276× later**, retaining nine startup survivors and raising later survivors to seven. The shared/context transfer is therefore still poorly aligned with the focused bursty calibration errors. This motivates inspecting transfer and subgroup calibration before tuning toward the same June labels.

![Matched quantile phase comparison](../.local/adaptive-corridor/20261028-gap-quantile-v2/gap-quantile-comparison.png)

The [January finite-subset bound](CALIBRATED_BURSTY_RESEARCH.md) remains unchanged: eight startup paths survive minimum width, and retaining 90% of the twenty-five-path case permits only two refusals. Even optimal refusal and minimum pricing leave 6/10 = 60% startup survival. No parameter fit can force that observed subset into 43–53% while preserving those constraints. This is a statement about the observed subset, not its population probability.

## Risk accuracy and cross-period stability

For January 2026 restart startup, timing predicts **9.46%** mean minimum-width survival; adding gaps lowers it to **8.85%**, against observed 8/12 = 66.67%. Brier score worsens **0.5374 → 0.5458**, and log loss worsens **1.6491 → 1.6925**. On the original raw restart set's 427 bursty paths, timing/gap means are **9.51% / 9.50%** against observed 18.74%; Brier scores are **0.15482 / 0.15507**. These tested gap features do not improve the floor-risk prediction. Static and adaptive variants have the same risk forecast by design.

The following pass counts require at least twenty offered paths and survival within 43–53%. Canonical and shifted raw panels overlap and are not independent confirmations.

| Variant | Original raw restart / continuous | Canonical raw restart / continuous | Later normalized restart / continuous |
| --- | ---: | ---: | ---: |
| Retained | 4/8 / 2/5 | 5/5 / 4/5 | 7/11 / 6/11 |
| Timing quantile | 3/8 / 0/5 | 2/5 / 2/5 | 3/11 / 2/11 |
| Timing + adaptive | 4/8 / 3/5 | 1/5 / 1/5 | 4/11 / 4/11 |
| Gap quantile | 3/8 / 0/5 | 2/5 / 2/5 | 3/11 / 2/11 |
| Gap + adaptive | 3/8 / 2/5 | 1/5 / 1/5 | 4/11 / 4/11 |

Gap adaptive lowers later normalized restart full-reference loss **80.650 → 76.714 ppm**, about 4.9%, but reduces passes **7/11 → 4/11**. Canonical raw restart loss improves **65.462 → 63.499 ppm**, with passes falling **5/5 → 1/5**. Original raw restart loss worsens **48.336 → 48.446 ppm**. A lower aggregate quantile loss is insufficient to choose this formula for stable per-period calibration.

All bursty quote availability remains **100% of the retained benchmark**. Original raw overall eligible-path availability stays **8,314/9,291 = 89.48%** under previous-floor frozen admission and **8,192/9,291 = 88.17%** under warmup/floor30. Frozen, sparse and active prices and admission remain unchanged. These historical availability measures do not establish native capture uptime.

## Reproduction and verification

```sh
OPENBLAS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 OMP_NUM_THREADS=1 \
  python3 -B scripts/research_gap_quantile.py \
  --previous .local/adaptive-corridor/20261028-expanded-bursty-v1 \
  --output .local/adaptive-corridor/20261028-gap-quantile-v2
OPENBLAS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 OMP_NUM_THREADS=1 \
  python3 -B scripts/audit_gap_quantile.py \
  --output .local/adaptive-corridor/20261028-gap-quantile-v2
OPENBLAS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 OMP_NUM_THREADS=1 \
  python3 -B -m unittest discover -s scripts -p 'test_*.py'
```

Use a new output directory for another run. The v1 attempt stopped before selection because native training rows had no normalized context lookup. The declared fallback was corrected and regression-tested; v1 retains an invalidation record and supplies no results. All results here come from v2.

The archive preserves **8,320 case/group rows, 2,080 phase rows and 470 paired common/both-offered comparisons across 104 intervals in 74 sessions**, source snapshots, numerical fits, feature provenance, risk scores, focused diagnostics and the rendered figure. All **1,664 benchmark case/group rows**, earlier benchmark fold scores and **7,430 retained per-entry records** reconstruct exactly. Raw/context/input hashes were reverified, and 279,080 feature records were checked for strict entry/restart boundaries. Actual January/June fits remain unchanged within 1e-10 after mutating own and future labels.

The local suite passes **254 tests**, with three existing optional skips and no failures. Nine new tests cover entry/future receipt isolation, stale/missing/native context, matched training support, outcome-free feature construction, delayed learning, refused references, state resets, fixed non-bursty decisions, controller direction and anti-windup. NumPy remains 1.26.1; remote CI was not run. The figure was visually checked.

The retained formula stays in place. The 48% target and 43–53% band remain legacy research conventions rather than payout-product validation. Native continuity/deadline defects remain separate unresolved work. Capture stays on hold.
