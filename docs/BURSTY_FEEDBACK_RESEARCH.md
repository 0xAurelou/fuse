# Isolated bursty feedback — 28 October 2026

Follow-up: the [bursty residual-quantile comparison](BURSTY_RESIDUAL_RESEARCH.md) adds miss magnitude and chronological forecast priors without refitting these models. The four-hour gap prior recovers retained pass counts on later normalized panels with lower loss, but June stays 8/22 and canonical raw cases remain weaker. Capture remains on hold.

Separating bursty calibration errors from active/sparse errors corrects the previously observed transfer direction and improves the earlier-fold objective. The frozen gap quantile with bursty-only feedback wins selection at **20.094**, versus retained **20.812** and shared gap feedback **24.993**. However, June later survival stays **8/22 = 36.36%** in both modes, and cross-period passes remain below the retained benchmark. The selection winner is saved for research; no successor is promoted or frozen and no capture starts.

## What changes

The previous [gap quantile experiment](GAP_QUANTILE_RESEARCH.md) fitted the timing/gap models and evaluated a correction learned from a non-frozen parent blended with a bursty shape child. Its June correction usually narrowed bursty quotes despite their low observed survival.

This experiment freezes those numerical models, their training prefixes, feature cache, minimum-width probability forecasts, underlying retained-reference forecasts, engines and frozen admission masks. It changes only how the added correction layer transfers matured errors. The original five variants remain exact controls, and six variants add the following three methods to each of the timing and gap models:

| Method | Correction and learning |
| --- | --- |
| Bursty-only | One controller learns from all supported clean bursty references; active/sparse errors cannot update it. |
| Separate shapes | Independent cooling, balanced and fresh bursty controllers; no transfer between shapes or from other activity states. |
| Shrunk bursty | One bursty controller whose prediction and gradient weights are (n/(n+12)), using matured support and a neutral zero-correction prior. |

All use the existing discounted AdaGrad quantile-loss update, learning rate, one-hour age/gradient limits, maturity delay, integer width bounds, anti-windup and correction bounds. Labels become usable at expiry plus thirty seconds. Refused clean references still teach their controller. Unsupported market context retains the previous quote. There is no mandatory quote warmup.

**Isolation applies to the added correction layer.** The retained-reference pricing algorithm and frozen fitted quantile models still carry their original cross-state information. This experiment does not claim end-to-end independence from active/sparse market behavior.

The shared control now logs the parent and child contributions separately. Instrumentation reconstructs its original predictions exactly. No inputs are downloaded, fitted models are not retrained, and native panels without market context keep their prior fallback.

## Chronological selection

The original six/nine/twelve-date prefixes, subsequent three/three/two normalized scoring dates, full-reference loss guard, phase/availability costs and **95% pooled / 90% populated-case bursty retention** constraints remain fixed. Raw evaluation outcomes do not select a variant. All eleven variants preserve admission and satisfy retention.

| Variant | Earlier score |
| --- | ---: |
| Gap + bursty-only | **20.094** |
| Timing + bursty-only | 20.204 |
| Retained benchmark | 20.812 |
| Gap + separate shapes | 22.041 |
| Timing + separate shapes | 22.971 |
| Gap + shrunk bursty | 24.201 |
| Timing + shrunk bursty | 24.386 |
| Timing + shared feedback | 24.431 |
| Gap static | 24.946 |
| Gap + shared feedback | 24.993 |
| Timing static | 25.132 |

Lower is better. The winning improvement versus retained is **0.718, about 3.45%**. Its fold scores are **16.863 / 17.701 / 25.718**, versus retained **20.736 / 21.387 / 20.313**: two improve and the latest worsens. The small earlier selection universe still contains only two distinct sufficiently populated bursty cases. Repeated inspected periods and overlapping panels are developmental evidence, not independent holdouts.

## Transfer direction and June pricing

The following values use the exact June 2025 06:00–14:00 later phase, with twenty-two paths. The multiplier is relative to the frozen gap static forecast.

| Feedback | Restart mean multiplier | Restart below / above static | Continuous mean multiplier | Continuous below / above static |
| --- | ---: | ---: | ---: | ---: |
| Shared | 0.877× | 19 / 3 | 0.929× | 18 / 4 |
| Bursty-only | **1.054×** | 1 / 14 | **1.067×** | 1 / 18 |
| Separate shapes | 0.999× | 8 / 7 | 0.985× | 10 / 7 |
| Shrunk bursty | 1.024× | 0 / 17 | 1.009× | 0 / 13 |

Counts need not sum to twenty-two because some quotes equal their static forecast. In restart mode the shared parent's mean log contribution is **−0.1371**, while the child's is nearly zero, **−0.0000565**. Removing that parent contribution changes the average direction to widening. The pooled bursty controller sees up to seventeen matured references; the separate shape/shared child sees at most six, illustrating the support cost of finer partitioning.

This direction change does **not** add a survivor. Every new variant still yields eight later survivors in both modes. Gap bursty-only later full-reference loss is **72.313 / 71.945 ppm**, versus retained **71.622 / 71.184 ppm** and shared gap **72.131 / 71.353 ppm**. Correcting the transfer mechanism is insufficient to repair the conditional price distribution.

The saved hindsight spacing diagnostic examines how far misses lie outside their current quotes. Its future-aware ratios are diagnostic only and never determine entry prices, hyperparameters or selection. They show that modest widening can leave the finite survival count unchanged; the exact integer transition thresholds are retained in `focused-diagnostics.json`. Choosing a June-specific multiplier from those future movements would not constitute a predictive solution.

## January startup and later phases

Entries below show startup / later survival. Startup has twelve paths; later phases have thirty-nine for January 2025 and thirteen for January 2026. No phase is re-ranked after outcomes or admission.

| Variant | January 2025 restart | January 2025 continuous | January 2026 restart | January 2026 continuous |
| --- | ---: | ---: | ---: | ---: |
| Retained | 83.33% / 33.33% | 75.00% / 38.46% | 75.00% / 46.15% | 75.00% / 46.15% |
| Shared gap | 66.67% / 33.33% | 66.67% / 38.46% | 75.00% / 53.85% | 75.00% / 53.85% |
| Bursty-only gap | 66.67% / 35.90% | 66.67% / 43.59% | 75.00% / **46.15%** | 75.00% / **46.15%** |
| Separate-shape gap | 66.67% / 33.33% | 66.67% / 41.03% | 75.00% / 53.85% | 75.00% / 53.85% |
| Shrunk gap | 66.67% / 38.46% | 66.67% / 41.03% | 75.00% / 46.15% | 75.00% / 46.15% |

Bursty-only gap feedback restores January 2026 later survival to the reference band and improves January 2025 continuous later survival, compared with shared feedback. Startup remains unresolved. Timing bursty-only produces January 2025 startup **66.67% restart / 75.00% continuous**, revealing additional restart sensitivity; finer shape splitting does not consistently improve it.

June startup stays **5/12 = 41.67%** in both modes for every isolated method, restoring the survivor lost by shared feedback in continuous mode. Later stays 8/22.

The [finite January 2026 startup constraint](CALIBRATED_BURSTY_RESEARCH.md) is unchanged: eight minimum-width survivors among twelve startup paths, and at most two refusals while retaining 90% of the twenty-five-path case. Even optimal refusal and minimum-width pricing leave 6/10 = 60% startup survival. This describes that finite observed subset; it is not a population probability estimate or a reason to tune prices toward an impossible subset target.

![Shared and isolated feedback comparison](../.local/adaptive-corridor/20261028-bursty-feedback-v1/gap-quantile-comparison.png)

## Stability and availability across periods

Passes require at least twenty offered paths and survival within 43–53%. Small cells remain descriptive. Canonical and shifted panels overlap, and repeated continuous/restart paths are not independent samples.

| Variant | Original raw restart / continuous passes | Canonical raw restart / continuous | Later normalized restart / continuous |
| --- | ---: | ---: | ---: |
| Retained | 4/8 / 2/5 | 5/5 / 4/5 | 7/11 / 6/11 |
| Shared timing | 4/8 / 3/5 | 1/5 / 1/5 | 4/11 / 4/11 |
| Shared gap | 3/8 / 2/5 | 1/5 / 1/5 | 4/11 / 4/11 |
| Bursty-only timing | 4/8 / 1/5 | 2/5 / 3/5 | 5/11 / 5/11 |
| Bursty-only gap | 4/8 / 0/5 | 2/5 / 3/5 | 6/11 / 5/11 |
| Separate-shape timing | 3/8 / 1/5 | 3/5 / 3/5 | 3/11 / 2/11 |
| Separate-shape gap | 2/8 / 0/5 | 2/5 / 2/5 | 3/11 / 2/11 |
| Shrunk timing | 3/8 / 0/5 | 2/5 / 2/5 | 3/11 / 2/11 |
| Shrunk gap | 3/8 / 0/5 | 2/5 / 2/5 | 4/11 / 3/11 |

The winning bursty-only gap method recovers later normalized passes compared with shared gap, but remains below retained and loses all five populated original raw continuous passes. Full-reference original raw restart loss worsens **48.336 → 48.793 ppm**. Later normalized restart loss improves **80.650 → 77.332 ppm**, yet shared gap's **76.714 ppm** was lower. Improvements in earlier score, aggregate loss and case calibration do not align consistently enough to promote a successor.

All existing bursty quotes remain offered. Original raw overall eligible-path availability is unchanged at **8,314/9,291 = 89.48%** under previous-floor frozen admission and **8,192/9,291 = 88.17%** under warmup/floor30. Grid availability remains **86.83% / 85.55%**. Frozen, active and sparse prices and all admission decisions remain fixed. Historical eligible-path availability does not establish native capture uptime.

## Verification and reproduction

```sh
OPENBLAS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 OMP_NUM_THREADS=1 \
  python3 -B scripts/research_bursty_feedback.py \
  --previous .local/adaptive-corridor/20261028-gap-quantile-v2 \
  --output .local/adaptive-corridor/20261028-bursty-feedback-v1
OPENBLAS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 OMP_NUM_THREADS=1 \
  python3 -B scripts/audit_bursty_feedback.py \
  --output .local/adaptive-corridor/20261028-bursty-feedback-v1
OPENBLAS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 OMP_NUM_THREADS=1 \
  python3 -B -m unittest discover -s scripts -p 'test_*.py'
```

Use a new output directory for another replay. The archive retains **18,304 case/group rows, 4,576 phase rows and 1,034 common/both-offered comparisons across 104 intervals in 74 sessions**, plus models, component logs, source snapshots, focused diagnostics and a visually checked figure.

All **8,320 preceding case/group rows, five preceding candidates' earlier scores and 37,150 per-entry prediction records reconstruct exactly**. Every numerical fit and selection-prefix model is unchanged. Source/input/context hashes and all 279,080 cached feature records were reverified.

Actual January/June correction-layer counterfactuals replace active/sparse outcomes while holding retained forecasts and fitted models fixed. The old shared control changes fifty/thirty-four bursty widths; all isolated methods remain unchanged. Additional actual-data mutations confirm that current/future outcomes cannot affect any candidate's width before label maturity. Quote/grid denominators, paired underlying paths and non-bursty prices remain fixed.

The local suite passes **261 tests**, with three existing optional skips and no failures. Seven new tests cover exact shared-control instrumentation, cross-state/cross-shape label isolation, sparse neutral startup, delayed learning, refused-reference learning, restart behavior, unchanged non-bursty prices and bounded component sums. NumPy remains 1.26.1; remote CI was not run.

This iteration supports removing inappropriate correction-layer transfer as a research direction, while showing it is not sufficient for June's conditional pricing or cross-period stability. The retained benchmark remains in place. The 48% target and 43–53% band remain research conventions rather than payout-product validation; native continuity/deadline defects remain separate unresolved work. Capture stays on hold.
