# Pump calibration and period stability — 27 October 2026

The subsequent [oracle-activity iteration](ADAPTIVE_ACTIVITY_RESEARCH.md) adds
price-change activity features, conditional corrections and explicit research
entry pauses. It further improves pump and flat-period diagnostics while keeping
the difficult day, shadow outcomes and availability loss visible; capture remains
on hold. The earlier iteration below remains as its original research record.

The offline iteration improved pump calibration and transfer to both native
recordings. The leading research rule uses pump-phase scales and a bounded
correction learned from completed earlier reference windows. **A new capture
remains on hold:** one flat-heavy historical day still misses badly, and several
individual pump-period rates remain outside the reference band.

No live pricing policy, accepted corridor or frozen recording changed. No new
capture started. The retained final experiment is
`.local/adaptive-corridor/20261027-stability-v2/`; the first experiment is retained
separately as `20261027-stability-v1/`.

## What was investigated

The earlier blend survived only 38.1% of latest-slice pump windows with slowing
one-minute volatility, versus 51.1% in the validation slice under the same phase
definition. Simply widening all pumping conditions would therefore overshoot
other periods.

Eight small research variants compare the old blend, equal-period calibration,
separate regime scales, separate pump-phase scales, and rolling calibration with
60/120/240 mature-window memories. These are a bounded comparison, not a claim
to have optimized all possible formulas.

The first rolling experiment had a large inactive range from placing its prior
mass at exactly one. It also repeatedly discarded valid earlier calibration
when feature history became unavailable. Its modest improvement is retained.
The final experiment uses smooth shrinkage and age-based expiry of valid earlier
evidence, while continuing to suppress predictions when current feature history
is unavailable. This model revision was informed by development diagnostics;
outer periods and native recordings are not untouched holdouts.

## Leading research rule

```text
shape = max(1, (vol60_ppm + vol300_ppm) / 2)
width_ppm = clamp(ceil(scale[regime_or_pump_phase] * shape * correction), 1, 50000)
```

The historical training fit gives these approximate base scales:

| Pre-entry condition | Scale |
| --- | ---: |
| Range | 0.94154 |
| Mixed | 0.92261 |
| Dump | 0.96689 |
| Pump, slowing volatility | 1.10359 |
| Pump, steady volatility | 0.94631 |
| Pump, accelerating volatility | 0.89463 |

The ratio `vol60/vol300` defines slowing below 0.75 and accelerating above 1.25.
Otherwise it is steady. Both volatility estimates and the original directional
labels use prices strictly before entry. Groups shrink toward their parent and
fall back to that parent below 80 training windows or three training periods.
The 50,000-ppm limit is an offline research bound, not a production setting; no
scored width reached it.

The correction uses the latest **120 mature eligible reference windows**, at most
four hours old. For each, compute the smallest surviving integer width divided
by its base predicted width. After at least 30 observations, estimate the target
quantile of those ratios and shrink its logarithm toward zero with weight
`n/(n+30)`. Bound the factor to **0.75–1.3333**, and limit its change to **2% per
new entry**.

An outcome cannot update a prediction until **30 seconds after its expiry**.
Current or future outcome eligibility never determines whether a width is
predicted. Missing pre-entry features suppress quoting but do not erase valid,
completed earlier calibration; it expires by age. Every sampled day and native
run starts with fresh correction state. The update rule is fixed code; accepted
barriers stay fixed for their full 30 seconds. Learning uses the reference grid,
without assuming that customers actually entered every window.

## Selection and chronological evidence

Candidate selection uses expanding folds entirely inside the original first 14
training sample days: train on 6/9/12 days and score the next 3/3/2. The objective
balances daily calibration error, directional daily error and worst daily error,
with a penalty for quantile-loss deterioration above 10%. The selected rule is
`rolling_phase_120`. Outer validation, final slices and native recordings do not
choose its parameters. Full rankings and every rejected variant remain available.

The legacy reference target remains **48%**, with the descriptive 43–53% band.
These counts include initial learning periods; cold-start windows were not
removed to improve results.

| Diagnostic sample | Eligible windows | Old blend | Revised rule |
| --- | ---: | ---: | ---: |
| Historical validation, overall | 11,112 | 50.80% | 48.99% |
| Historical validation, pumps | 553 | 51.90% | 52.26% |
| Historical final slice, overall | 10,672 | 51.23% | 51.30% |
| Historical final slice, pumps | 412 | 41.50% | 46.60% |
| Historical final slice, dumps | 370 | 43.78% | 49.73% |
| First native recording | 859 | 39.12% | 46.45% |
| Second native recording | 752 | 44.41% | 47.07% |

The pooled final rate barely changes; the improvements are conditional calibration,
period stability and transfer. Final-slice quantile loss also falls from 79.86 to
79.38 ppm. This is a development result, not an independent probability guarantee.

| Daily stability measure | Old blend | Revised rule |
| --- | ---: | ---: |
| Validation mean absolute target error | 3.41 pp | 2.00 pp |
| Final-slice mean absolute target error | 5.71 pp | 3.43 pp |
| Final-slice worst daily absolute target error | 18.48 pp | 14.95 pp |
| Final-slice days within the reference band | 3/5 | 4/5 |

Both native recordings passed their original native chain and frozen-artifact
checks. Historical training fits the base scales; native corrections use only
earlier mature windows within the run under the fixed update law. Native hourly
and cold-start diagnostics are retained, including hours still outside the band.

## Remaining instability and capture decision

The 1 August 2026 oracle sample remains an outlier: **62.95%** survival, down from
66.48%, on 2,324 eligible paths. **31.84%** of those paths have no recorded price
movement over 30 seconds. This is an observed association, not proof that flat
paths alone cause the error or that the normalized stream is complete. The
lower correction bound is reached in the historical diagnostics. Tightening it
solely to fix this previously inspected day would be further model development,
not validation.

Individual pump-period rates also remain uneven: 55.56% in June and 42.61% in
October in the final slice, despite the improved pooled 46.60%. Only five pump
windows exist in the August outlier. Correlated context clusters and small
directional denominators limit interpretation.

The next investigation should distinguish flat/bursty oracle behavior using
information observable before entry, and inspect pump-period errors and correction
lag. Any added feature or bound should be chosen on earlier folds and assessed
without hiding excluded periods or initial learning. Native capture continuity
and deadline repairs remain separate requirements before an unattended run.

Historical provider normalization, first-of-month selection and nonrandom
freshness exclusions still apply. Refer to
[historical regime-data research](ADAPTIVE_REGIME_DATA_RESEARCH.md). The payout
product needs multiplier-specific `(1-h)/M` targets; this 48% reference experiment
does not validate the full pricing surface or LP economics.

## Reproduction and checks

```sh
PYTHONDONTWRITEBYTECODE=1 python3 scripts/stabilize_adaptive_corridor.py \
  --history .local/adaptive-corridor/20261027-oracle-history-v1 \
  --captures .local/prospective-runs/20261026-117ppm-8h \
             .local/prospective-runs/20261026-round2-314ppm-8h \
  --output /absolute/path/to/new-stability-research
```

The experiment saves its protocol and exact code before scoring, pins source
hashes, reconstructs the old baseline exactly, and retains model coefficients,
inner folds, per-period/per-regime scores, native hourly results, every prediction
and its correction/mature-outcome count.

Validation: **122 Python tests ran successfully, with three existing optional
skips**. New tests verify maturity delays, immunity to future prices and outcome
eligibility, bounded correction changes, session reset, history suppression,
age expiry, initial learning denominators, exact barrier touches, period/episode
balancing, sparse-group fallbacks and isolation from outer-period model selection.
