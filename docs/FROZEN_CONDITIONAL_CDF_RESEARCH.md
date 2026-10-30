# Conditional frozen-oracle distribution — 28 October 2026

A context-conditioned model now estimates both the chance of surviving minimum
width and the positive-movement width distribution. It improves the causal
estimate of August's minimum-width probability, but does **not** produce better
cross-period quote calibration. The retained open benchmark wins earlier
selection. Tested probability gates still violate quote-availability screens,
and September frozen pricing remains weak. No candidate is promoted or frozen
for an eight-hour capture.

The full run took **45.70 seconds**. Models, sources, selection, per-entry
predictions and diagnostics are retained in
`.local/adaptive-corridor/20261028-frozen-cdf-v1/`.

## Model and causal rules

The preceding temporal study found that one frozen-state prior could not
represent both high-floor January/August and low-floor September conditions.
This experiment replaces only frozen pricing and admission. Every non-frozen
width remains the retained benchmark's width and its quotes stay open.

The thirteen allowed inputs describe previous oracle activity, idle duration,
change counts, empty bins, variance concentration, slow volatility, fast/slow
volatility shape, directional strength/efficiency, an idle/cooling interaction,
whether idle age is only a lower bound, and signed prior drift. There are no
outcome, current validity, date or future-price predictors. Market/oracle gaps
are **not** inputs to this experiment.

Let `R` be the smallest integer ppm width surviving the exact subsequent oracle
path. A ridge logistic regression estimates `p0 = P(R <= 1 | pre-entry context)`.
Ten regularized quantile regressions fit positive-movement
`log(R / max(1, prior slow volatility))` at levels
0.01/0.05/0.10/0.20/0.35/0.50/0.65/0.80/0.95/0.99. At prediction, sorting the
positive log-width forecasts prevents quantile crossing. For desired CDF level
`q`, the positive component is queried at `(q - p0)/(1 - p0)`. If `p0 >= q`, the
forecast is the absolute one-ppm minimum. Otherwise interpolation yields an
integer width between 2 and 50,000 ppm, with exact touch-is-loss scoring.

Training uses all clean earlier frozen reference paths, including refused
paths. Two weightings compare equal calendar-date mass with equal path mass.
Each has static/open, online/open, static/gate53, online/gate53 and
online/gate65 methods, plus the retained open control: eleven variants.

The online method starts with the fitted model and CDF level 0.48. After a clean
frozen label matures, its floor logit intercept receives
`0.1 * (observed_floor - predicted_floor)`, bounded to ±3. The desired CDF level
receives `0.03 * (0.48 - shadow_survived)`, bounded to 0.02–0.98. Outward updates
at absolute width bounds are blocked. Updates use the probabilities and width
saved at quote time. The state resets after four hours without mature support;
it is a bounded accumulator, not a four-hour sliding sample pool. Restart state
is private and continuous eight-hour scoring boundaries do not reset it.

Labels enter at **expiry plus thirty seconds**. Probability gates refuse only
from the pre-entry forecast, never the current outcome. Refused clean paths
still update both declared accumulators. Gate decisions do not select learning.
These fitted/interpolated distributions and bounded updates have no guaranteed
finite-period or conditional calibration.

## Earlier chronological selection

The original later folds remain: prefixes of fourteen, seventeen and twenty
sample dates score January–March, April–June and July–August 2026. The final
twenty-two-date fit ends before September. September/October raw and normalized
panels remain later diagnostics, but are now already inspected development data.

The full-state score, loss guard and provisional 85% overall / 50% populated
frozen availability screens remain. The phase charge now measures frozen
first-twelve/later groups rather than the unchanged bursty phases, so scores
are not directly comparable with the preceding study. Quotes cannot disappear
from denominators by being refused.

| Variant | Earlier score | Availability screens |
| --- | ---: | --- |
| Retained open | **13.389** | Pass |
| Path-weighted, online open | 13.892 | Pass |
| Path-weighted, static open | 15.553 | Pass |
| Period-weighted, online open | 16.003 | Pass |
| Period-weighted, static open | 17.650 | Pass |
| Path-weighted, online gate65 | 18.965 | Fail |
| Path-weighted, static gate53 | 20.044 | Fail |
| Path-weighted, online gate53 | 40.174 | Fail |

All remaining period-weighted gates also fail availability. Model coefficients,
selection and full update rules are pinned and hashed before later replay.
Neither the later-best method nor a newly inspected feature can change this
archived ranking.

## Floor prediction improves; offered calibration does not

On August's raw 08:00 restart group, static path-weighted mean predicted floor
is **47.45%**, versus **61.79% observed**. Online updating raises the mean forecast
to **60.67%** and improves Brier score **0.2606 → 0.2406**. This is a descriptive
forecast improvement on the same paths, not successful quote calibration.

| Method | August 08:00 frozen quotes / eligible | Offered survival | Offered minimum-width survival |
| --- | ---: | ---: | ---: |
| Retained open | 390/390 | 63.85% | 61.79% |
| Path static, open | 390/390 | 70.26% | 61.79% |
| Path online, open | 390/390 | 69.74% | 61.79% |
| Path static, gate53 | 247/390 | 71.26% | 57.89% |
| Path online, gate53 | 135/390 | 73.33% | 52.59% |
| Path online, gate65 | 228/390 | 69.74% | 56.14% |

This temporal full-day input retains one more eligible frozen entry than the
earlier clipped 389-path panel; all variants here share the same 390 paths.
The gate53 online rule keeps only **34.62%** of this frozen group. Gate65 keeps
more than half, but its offered floor already exceeds the 53% upper reference
bound. No width-only correction can repair that fixed offered subset.

Gate53's 52.59% offered floor is physically compatible with the reference band,
but its positive-width quotes add too many survivors. Accurate average floor
prediction therefore does not establish useful discrimination, positive-CDF
calibration, or calibration after probability-based selection. Its desired CDF
level also adapts from full reference paths, which is not a guarantee for the
subpopulation that remains offered.

The following raw-date table includes January/August selection data and
September/October later diagnostics. None are prospective observations:

| Frozen group, restart mode | Retained open | Path static open | Path online open |
| --- | ---: | ---: | ---: |
| January 2026, 1,004 paths | 56.77% | 62.35% | 61.95% |
| August 2026, 894 paths | 62.08% | 67.67% | 64.77% |
| September 2026, 49 paths | 34.69% | 20.41% | 32.65% |
| October 2026, 49 paths | 48.98% | 38.78% | 40.82% |

The new model does not fix untouched non-frozen/bursty failures, since those
prices remain unchanged. Small frozen phase/regime groups and repeated modes
are descriptive; pooled percentages are not independent probability evidence.

## A separate information lead

A post-experiment inspection checks already retained **pre-entry** mark/oracle
gaps. All 1,004 January and 894 August frozen paths have fresh saved context.
On August's full day, observed minimum-width survival rises from **43.05% in
the smallest-gap quartile** to **70.54% in the largest-gap quartile**. January's
corresponding rates are 52.99% and 64.14%, with lower middle quartiles.

The quartiles use the absolute transformed gap relative to prior slow
volatility. Their boundaries are descriptive equal-count partitions of these
already inspected days, not a new entry gate or validated threshold. They were
excluded from this experiment's fits and selection. The archived
`exploratory-mark-gap.csv` and its note preserve that distinction. The result
supports testing fresh market context in a subsequent matched-support model;
it does not prove that it will transfer or that market prices can replace the
oracle in entry/barrier outcomes.

## Verification and remaining work

The audit refits all eight prefix/weighting models exactly, recomputes selection
and **760,320 prediction records**, and verifies **711,920 retained-control or
non-frozen records** against the preceding archive. Actual seventeen- and
twenty-two-date counterfactuals preserve fits after own/future labels change,
confirm label maturity, and prove that refusing quotes does not select model
updates. Seven new tests cover context separation, monotonic quantiles, exact
floor/cap behavior, future-label isolation, refused-reference learning,
cross-state isolation, restart/stale resets and chronological fitting. The full
suite passes **318 tests with three existing optional skips**. No dependency
was installed; remote CI was not run.

```sh
OPENBLAS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 OMP_NUM_THREADS=1 \
  python3 -B scripts/research_frozen_cdf.py \
  --previous .local/adaptive-corridor/20261028-temporal-pricing-v1 \
  --output /absolute/path/to/new-frozen-cdf-run
OPENBLAS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 OMP_NUM_THREADS=1 \
  python3 -B scripts/audit_frozen_cdf.py \
  --output /absolute/path/to/new-frozen-cdf-run
```

The archive retains 6,336 case/group rows, 6,336 regime/group rows, 1,584 frozen
phase rows, 792 floor-bound rows, 792 risk summaries and 396 paired comparisons.
These span repeated policies/modes and source formats, not that many independent
experiments. The next pricing step is a matched timing-versus-market-context
comparison, with proper treatment of predictions that already exceed the target
at minimum width. A defensible frozen candidate and reliable new eight-hour
pricing capture remain outstanding; payout, costs, strategies and LP economics
remain separate unvalidated requirements.
