# Bursty residual quantiles and chronological priors — 28 October 2026

The subsequent [automated parameter search](BURSTY_OPTIMIZER_RESEARCH.md) replaces manual parameter enumeration with a bounded Bayesian optimizer. Its 32-trial pilot improves earlier selection but has mixed later performance; the retained benchmark and capture hold remain in place.

The new correction uses the magnitude of past width errors, rather than only survivor/miss labels. A four-hour residual distribution with a chronological prior recovers **7/11 restart and 6/11 continuous passes on later normalized bursty cases**, matching the retained benchmark while lowering restart pricing loss **80.650 → 77.896 ppm**. June later survival nevertheless remains **8/22 = 36.36%** in both modes, and canonical raw passes remain weaker. The previous binary bursty correction still wins earlier selection. The retained benchmark stays in place; no successor is promoted or frozen and no capture starts.

## Controlled experiment

The [preceding bursty-feedback experiment](BURSTY_FEEDBACK_RESEARCH.md) removed inappropriate transfer from active/sparse errors. Its pooled bursty correction widened June quotes in the right direction but gained no survivors. This experiment keeps those eleven candidates as exact controls and adds four residual methods to each frozen timing/gap model, for **nineteen variants**:

| New method | Memory / decay half-life | Prior | Maximum multiplier update per bursty entry |
| --- | --- | --- | ---: |
| One-hour neutral | 1h / 15min | Twelve observations at factor one | 5% |
| Four-hour neutral | 4h / 1h | Twelve observations at factor one | 5% |
| Four-hour chronological prior | 4h / 1h | Earlier forecast residual distribution, mass twelve | 5% |
| Four-hour prior, faster update | 4h / 1h | Same chronological prior | 20% |

The numerical timing/gap fits, feature cache, retained-reference forecasts, engines, target, integer width bounds, frozen prices, admission masks and selection objective remain fixed. No data are downloaded. Only the residual correction changes.

For a supported bursty entry, let (q_i) be its frozen, uncorrected static forecast and (R_i) the minimum integer width surviving its full thirty-second oracle path. Once the outcome matures, the correction learns

\[
r_i=R_i/q_i.
\]

At the next bursty entry it takes the weighted 48th percentile of matured ratios and prior residuals, then multiplies the current static forecast by that factor. Recency weights decay by clock time. The multiplier stays between 0.25 and four, with the declared update bound. The denominator remains the original entry forecast, preventing previous corrections from contaminating the residual definition.

The prior's clipped 48th percentile is available at cold start. When memory is empty, the multiplier resets to that prior factor. Corrections advance only on supported bursty entries. Active/sparse outcomes never update the online residual pool; the pool contains at most 120 clean bursty references. Outcomes become usable at expiry plus thirty seconds. Refused references still learn. Missing market context falls back to the retained quote, and no quote warmup is imposed.

## Chronological calibration of the prior

The prior is not fitted to in-sample residuals. Each allowed monthly training date is forecast with the latest available frozen model whose training dates all precede it. Existing prefix and outer fits are reused; no regression model is refitted.

| Scoring dates | Frozen predictor's training prefix |
| --- | --- |
| November–December 2024 | No earlier fitted predictor; no residual calibration records |
| January–April 2025 | November–December 2024 fit |
| May 2025 | First six dates, through April |
| June 2025 | First seven dates, through May |
| July 2025 | First eight dates, through June |
| August–October 2025 | First nine dates, through July |
| November–December 2025 | First twelve dates, through October |

Every candidate prior then uses only its own allowed training dates and labels matured before its cutoff. Raw rows replace matching training dates where available, without duplicating dates. Calendar periods receive equal weight. A bursty child requires eighty references and three dates; otherwise the non-frozen parent is used, or a neutral prior when no earlier forecasts exist. Raw diagnostic case scores never enter selection; matching raw observations on allowed earlier training dates can train later priors. These remain developmental, repeatedly inspected data.

The archive contains **51,766 earlier-model forecast residual records** across both timing/gap models, on twelve training dates. Each final bursty prior has **757 references across twelve dates**, excluding the 131 November/December bursty training paths without an earlier forecast model. June 2025 uses **474 bursty references across January–May**. January 2025 has no earlier forecast residuals and correctly falls back to neutral.

The prior 48th-percentile factors are:

| Cutoff | Timing | Gap |
| --- | ---: | ---: |
| January 2025 | 1.000× | 1.000× |
| June 2025 | 1.052× | 1.055× |
| July 2025 | 1.072× | 1.066× |
| Final fourteen-date fit | 1.140× | 1.132× |

Residuals from earlier models may still transfer imperfectly to a later fitted model or a new market regime. Chronological construction prevents use of future labels; it does not guarantee conditional calibration under that shift.

## Selection and activation

The original chronological folds, full-reference loss guard, phase and availability costs, and **95% pooled / 90% populated-case bursty retention** requirements are unchanged. All variants retain admission and pass those constraints.

| Candidate | Earlier score |
| --- | ---: |
| Previous gap binary bursty | **20.094** |
| Previous timing binary bursty | 20.204 |
| Gap four-hour prior, fast | 20.237 |
| Gap four-hour prior | 20.350 |
| Retained benchmark | 20.812 |
| Timing four-hour prior, fast | 21.575 |
| Timing four-hour prior | 23.925 |
| Gap neutral, either memory | 24.946 |
| Timing neutral, either memory | 25.132 |

Lower is better. The best new method does not beat the preceding selection winner. All eleven old candidates' scores and fold scores reconstruct exactly. Repeated selection still has only two distinct sufficiently populated bursty cases; the earlier mean alone is insufficient to promote a successor.

Both neutral-prior methods remain **exactly static on the evaluated predictions**. The twelve-observation point mass at one holds their weighted quantile at one. Extending memory increases evidence but does not move that quantile in this configuration. This is an inactive correction, not evidence that longer history or miss magnitude is unnecessary. Learned distributional priors do move forecasts.

## June and January phases

June 2025 06:00–14:00 later-phase gap corrections show the following behavior:

| Correction | Restart mean multiplier | Continuous mean multiplier | Restart / continuous survivors |
| --- | ---: | ---: | ---: |
| Previous binary bursty | 1.054× | 1.067× | 8/22 / 8/22 |
| Neutral residual, either memory | 1.000× | 1.000× | 8/22 / 8/22 |
| Four-hour chronological prior | **1.139×** | **1.100×** | 8/22 / 8/22 |
| Four-hour prior, fast | 1.153× | 1.104× | 8/22 / 8/22 |

The longer pool's later recency mass averages **7.32 restart / 7.65 continuous**, versus 3.25 for one hour; maximum mass is 14.04 / 14.76. The learned prior removes the neutral point-mass blockade. Faster updating follows the requested factor more closely, but still does not add a later survivor.

Timing four-hour prior lowers later loss **71.622 → 69.953 ppm restart** and **71.184 → 70.049 ppm continuous**. Gap four-hour prior yields **70.644 / 70.693 ppm**. Faster gap updating worsens those losses to **70.995 / 71.129 ppm**. Correcting larger misses improves some distances to required width without changing the finite survival count.

June startup remains **5/12 = 41.67%** for the slow prior methods in both modes. Fast gap updating reaches **6/12 = 50% continuously**, while restart remains 5/12. This twelve-path, mode-specific gain is descriptive and does not repair later drift.

January 2025 gap startup remains **8/12 = 66.67%**. Its later phase is **15/39 = 38.46% restart / 17/39 = 43.59% continuous**. Timing variants yield **9/12 restart / 8/12 continuous** at startup and **16/39 / 17/39** later. January 2026 remains **9/12 = 75% startup and 6/13 = 46.15% later**, in both modes, for all new methods.

The [finite January startup limit](CALIBRATED_BURSTY_RESEARCH.md) remains: minimum-width pricing and the maximum two refusals permitted by 90% case retention still leave at least 6/10 = 60% survival on that observed startup subset. The new residual model cannot eliminate that constraint. It is a finite-subset bound, not a population probability claim.

![Residual quantile phase comparison](../.local/adaptive-corridor/20261028-bursty-residual-v1/gap-quantile-comparison.png)

## Cross-period stability

Passes require twenty offered paths and survival in 43–53%. All rows use fixed primary frozen admission. Overlapping canonical/shifted panels and restart/continuous paths are not independent confirmations.

| Candidate | Original raw restart / continuous passes | Canonical raw restart / continuous | Later normalized restart / continuous |
| --- | ---: | ---: | ---: |
| Retained | 4/8 / 2/5 | 5/5 / 4/5 | 7/11 / 6/11 |
| Previous gap binary bursty | 4/8 / 0/5 | 2/5 / 3/5 | 6/11 / 5/11 |
| Gap neutral, either memory | 3/8 / 0/5 | 2/5 / 2/5 | 3/11 / 2/11 |
| Gap four-hour prior | **4/8 / 2/5** | 2/5 / 3/5 | **7/11 / 6/11** |
| Gap four-hour prior, fast | 4/8 / 1/5 | 3/5 / 3/5 | 7/11 / 5/11 |
| Timing neutral, either memory | 3/8 / 0/5 | 2/5 / 2/5 | 3/11 / 2/11 |
| Timing four-hour prior | 4/8 / 2/5 | 3/5 / 3/5 | 7/11 / 4/11 |
| Timing four-hour prior, fast | 4/8 / 1/5 | 3/5 / 4/5 | 7/11 / 5/11 |

Gap four-hour prior matches retained's aggregate pass counts on original raw and later normalized panels, though counts do not imply identical passing cases. Its later normalized restart loss falls **80.650 → 77.896 ppm**, about 3.4%, and continuous loss **79.898 → 77.592 ppm**. Original raw restart loss worsens slightly **48.336 → 48.540 ppm**; canonical restart loss improves **65.462 → 63.578 ppm**, but passes fall 5/5 → 2/5.

The three populated canonical restart misses are **11/27 = 40.74%, 10/25 = 40%, and 17/40 = 42.5%**. Each needs one additional survivor to enter the reference band. This illustrates the coarseness of small-cell pass/fail screens; these observations were not used to choose a special multiplier. The eighteen-path canonical January 08:00 cell remains descriptive.

Quote availability is unchanged: all existing bursty quotes remain offered, original raw eligible-path availability stays **8,314/9,291 = 89.48%** under previous-floor frozen admission and **8,192/9,291 = 88.17%** under warmup/floor30. Frozen, active and sparse prices and all admission decisions remain fixed. These historical availability measures do not establish native capture uptime.

The new learned-prior correction is a useful development result, but does not yet support replacing the retained benchmark. The remaining evidence concerns conditional calibration and transfer between periods, rather than simply increasing the update step.

## Reproduction and verification

```sh
OPENBLAS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 OMP_NUM_THREADS=1 \
  python3 -B scripts/research_bursty_residual.py \
  --previous .local/adaptive-corridor/20261028-bursty-feedback-v1 \
  --output .local/adaptive-corridor/20261028-bursty-residual-v1
OPENBLAS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 OMP_NUM_THREADS=1 \
  python3 -B scripts/audit_bursty_residual.py \
  --output .local/adaptive-corridor/20261028-bursty-residual-v1
OPENBLAS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 OMP_NUM_THREADS=1 \
  python3 -B -m unittest discover -s scripts -p 'test_*.py'
```

Use a fresh output directory. The archive retains **31,616 case/group rows, 7,904 phase rows and 1,786 common/both-offered comparisons across 104 intervals in 74 sessions**, all chronological forecast bindings and residual records, priors, component diagnostics, sources and a visually checked figure.

All **18,304 previous case/group rows, eleven earlier candidate scores and 81,730 preceding per-entry records reconstruct exactly**. All frozen timing/gap and prefix fits are unchanged. The audit recomputes all 51,766 chronological residual records and their predictor bindings exactly, verifies source/input hashes and 279,080 cached feature records, and confirms that own/future residual mutations leave January/June priors unchanged. Actual-data counterfactuals verify online cross-state isolation given fixed references and correct label maturity. All quote/grid denominators and non-bursty prices remain fixed.

The local suite passes **268 tests**, with three existing optional skips and no failures. Seven new tests cover future-date exclusion, self-fitted forecast rejection, maturity and duplicate guards, predictor eligibility, different response to equally classified small/large misses, refused-reference learning, cross-state isolation, missing context, restart resets and longer-memory behavior. NumPy remains 1.26.1; remote CI was not run.

The 48% target and 43–53% band remain research conventions rather than payout-product validation. Native continuity/deadline defects remain separate unresolved work. Capture stays on hold.
