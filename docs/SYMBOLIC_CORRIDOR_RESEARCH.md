# Symbolic corridor regression across periods — 28 October 2026

The subsequent [quantile-level feedback comparison](QUANTILE_LEVEL_RESEARCH.md)
changes the residual CDF's requested quantile using matured survival errors.
It repairs June's later finite survival count in a fast variant, while phase
cancellation and other conditional failures still prevent promotion.

Implemented and ran two bounded symbolic-regression experiments: a bursty-only fit and a shared non-frozen model with shrunk bursty calibration. Both discover and fit expression structures rather than only tuning controller parameters. Neither produces a more stable replacement for the retained benchmark. Some width-pricing losses improve, but later calibration passes deteriorate and June later survival remains 8/22. **No new candidate is promoted or frozen for capture, and no capture starts.**

The complete research pipelines took **82.93 seconds** and **86.15 seconds**, respectively, including input verification, expression fitting and later diagnostics. Audits were run separately.

## Formula discovery

The implementation is a local NumPy symbolic basis search, not the PySR package. [Symbolic regression](https://arxiv.org/abs/2305.01582) searches for interpretable mathematical expressions; this implementation deliberately restricts the grammar and computation budget.

Seven bounded pre-entry inputs are permitted:

| Input | Definition |
| --- | --- |
| `vol_ratio` | `clip(log(vol60 / vol300) / 2, -1, 1)` |
| `signed_drift` | `tanh(net300_bps × 100 / (sqrt(10) × vol300))` |
| `mark_gap` | `tanh(asinh(mark/oracle gap ppm / max(1, vol300)))`, using the retained fresh context feature |
| `concentration` | `2 × largest variance share over 300s − 1` |
| `idle` | `tanh(oracle idle milliseconds / 10000)` |
| `activity` | `tanh(log(1 + changes60) / 3)` |
| `efficiency` | `min(1, directional strength / sqrt(max(1, changes300)))` |

The volatility ratio and drift denominator use a 0.001 slow-volatility floor; the retained gap feature uses its original 1 ppm floor. There are no outcome, validity, future-price or calendar-date predictors. Range/pump/dump/mixed labels used for balancing and reporting already derive from pre-entry history; the formula uses continuous signals rather than branching on those labels.

Allowed expression operators are addition, multiplication, absolute value, tanh, and division by `1 + abs(denominator)`. Expressions are validated data trees, never evaluated Python strings. A model has an intercept and at most three symbolic terms, term depth at most two, and a combined complexity budget of seventeen term/tree units. Six beam members undergo four rounds of sixty-four mutation proposals, with duplicate structures removed. Each nonempty fit evaluates roughly 110–150 distinct structures.

Coefficients minimize a smoothed 48th-percentile regression objective on `clip(log(required width / earlier frozen gap forecast), -log(4), log(4))`, with ridge regularization. Structure selection uses strictly later dates within the allowed earlier training period: at least three dates fit coefficients, and the final quarter of dates validates structure. It charges average quantile loss, worst-date loss, worst sufficiently populated regime loss, and complexity. The selected coefficients are then refitted on the permitted earlier data. Thin data falls back to an intercept, and no earlier OOF references means neutral correction.

Every formula uses chronological out-of-model residuals from the retained archive: each underlying forecast model was trained on dates strictly earlier than its forecast date, and each label must mature before the formula's cutoff. The initial underlying forecasts were not regenerated or retrospectively improved.

## Two training populations

The first experiment fits only **757 bursty references across twelve dates** at the final cutoff. Those include 199 range, 513 mixed, **26 pump and 19 dump** paths. They are paths, not independent episodes.

The second experiment uses the complete **25,883 supported non-frozen references**: 6,588 range, 17,482 mixed, **911 pump and 902 dump**. Dates receive equal weight, with a 60/40 mixture of ordinary within-date path weighting and within-date regime balancing. A deterministic, label-blind uniform sample of at most 400 paths per date bounds coefficient-fit cost; all validation paths remain in structure scoring. The final parent coefficient fit uses 4,800 paths. A bursty quantile intercept is then shrunk toward that parent by `n / (n + 200)`; final `n = 757` gives weight 0.7910. This child calibration uses earlier allowed data but is in-sample relative to the expression fit, and is not claimed as independent calibration.

Only supported bursty quotes are repriced in either experiment. Frozen, active and sparse quotes and all admission decisions remain fixed. Larger non-frozen training support does not imply additional independent calendar periods.

Each population has static and delayed-adaptive variants plus intercept-only controls. The adaptive residual pool has at most 120 clean bursty paths, four-hour maximum age, one-hour half-life, three neutral pseudo-observations and a 5% correction step. Its multiplier is bounded at 0.5–2; the **combined** expression/online multiplier is bounded at 0.25–4. Labels enter at expiry plus thirty seconds, refused clean references still learn, and restart state is private. Continuous state is not reset at interval boundaries. Missing market context retains benchmark pricing.

## Selection and discovered formulas

All methods are compared on the same earlier 6/9/12-date prefix tests, retaining the original objective and loss guard as `legacy_score`. The new stability score adds `0.25 × worst fold + 0.25 × fold range + 0.02 × mean symbolic complexity`. This is a changed objective, so its values should not be compared directly to the previous experiment's legacy scores.

| Candidate | Legacy score | Stability score | Worst fold |
| --- | ---: | ---: | ---: |
| Previous Bayesian candidate | **15.788** | **20.767** | **17.186** |
| Retained benchmark | 20.812 | 26.427 | 21.387 |
| Bursty symbolic + adaptation | 24.070 | 35.920 | 33.299 |
| Shared symbolic, static | 24.253 | 35.860 | 33.043 |
| Shared symbolic + adaptation | 24.980 | 36.459 | 32.987 |

The existing controls reconstruct their preceding fold scores exactly. In both experiments, the previous Bayesian candidate wins earlier selection; its known later weaknesses still prevent promotion over the retained benchmark. Earlier scoring has only two distinct bursty cases with at least twenty paths, limiting inference even with a worst-fold penalty.

The bursty-only June formula is a small conditional correction:

```text
h(x) = 0.28725195 - 0.27498618 × tanh(idle_ms / 10000)
```

The July fit also selects idle; one earlier prefix selects concentration. The final bursty fit instead prefers the intercept `h = 0.17707220`. **Every shared-model fit chooses an intercept** after validation and complexity penalties. The final shared correction is `h = 0.1479889121`, approximately `1.1595 × frozen gap forecast` before online adjustment. Its parent intercept is 0.03790866 and its shrunk bursty shift is 0.11008025. The June shared fit is approximately 1.1485×.

For supported bursty entries, the final price is:

```text
width = clip(ceil(Q_gap(x) × exp(clip(h(x) + online_log_correction,
                                    -log(4), log(4)))), 1, 50000)
```

The exact executable coefficients and trees are archived; the displayed rounded expressions are explanatory, not prospective frozen candidates. Static `online_log_correction` is zero. The shared fit's preference for constants means this grammar/objective found no reliable additional conditional structure beyond the existing gap forecast; it does not establish that regime inputs are generally unnecessary.

## Period and regime comparisons

The following are populated bursty cells under the primary frozen admission policy. A pass requires at least twenty quotes and survival in the research 43–53% band. Counts are restart / continuous, and panels overlap.

| Panel | Retained | Previous Bayesian | Bursty symbolic adaptive | Shared symbolic adaptive |
| --- | --- | --- | --- | --- |
| Original raw | 4/8 · 2/5 | **5/8 · 3/5** | 3/8 · 1/5 | 3/8 · 1/5 |
| Canonical full raw | **5/5 · 4/5** | 4/5 · 4/5 | 3/5 · 3/5 | 3/5 · 3/5 |
| Later normalized test | **7/11 · 6/11** | 6/11 · 6/11 | 4/11 · 3/11 | 4/11 · 4/11 |

Later normalized restart full-reference bursty pricing loss improves **80.650 → 77.942 ppm** for bursty symbolic and **77.615 ppm** for the shared model, approximately 3.8% lower for the latter. This improvement does not imply calibrated corridor survival. Shared original raw restart loss is slightly worse at **48.484 versus 48.336 ppm**. Canonical raw restart loss improves **65.462 → 63.962 ppm**, despite its weaker pass count.

| Matched phase | Retained restart / continuous | Bursty symbolic adaptive | Shared symbolic adaptive |
| --- | --- | --- | --- |
| January 2025 startup | 10/12 · 9/12 | 8/12 · 8/12 | 8/12 · 8/12 |
| January 2025 later | 13/39 · 15/39 | 14/39 · 17/39 | 14/39 · 17/39 |
| June 2025 startup | 5/12 · 5/12 | 6/12 · 6/12 | 5/12 · 6/12 |
| June 2025 later | 8/22 · 8/22 | 8/22 · 8/22 | 8/22 · 8/22 |
| January 2026 startup | 9/12 · 9/12 | 9/12 · 9/12 | 9/12 · 9/12 |
| January 2026 later | 6/13 · 6/13 | 7/13 · 7/13 | 7/13 · 7/13 |

Bursty symbolic reduces June later pricing loss **71.622 → 68.302 restart / 71.184 → 67.813 continuous**, without adding survivors. The shared model yields 70.095 / 69.671. January 2026's existing finite startup bound remains: minimum-width quotes and at most two permitted refusals cannot reach the reference band on that observed subset.

On later normalized restart bursty paths, the shared adaptive formula produces **56.03% range survival on 141 paths**, 52.63% mixed on 266, 80% pump on **five**, and 42.86% dump on **twenty-one**. These are pooled descriptive groups, not period-level certification. Five pump paths are insufficient evidence of stability, despite the much larger parent training set.

Quote availability and every grid/entry/eligibility denominator stay fixed. All existing bursty quotes remain offered; original raw overall eligible-path availability stays **8,314/9,291 = 89.48%** under primary frozen admission and **8,192/9,291 = 88.17%** under the secondary policy. This does not establish prospective capture uptime.

![Symbolic search and period comparisons](/Volumes/dev/fuse/.local/adaptive-corridor/20261028-symbolic-pooled-v1/symbolic-comparison.png)

## Verification and reproduction

```sh
OPENBLAS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 OMP_NUM_THREADS=1 \
  python3 -B scripts/research_symbolic_corridor.py \
  --previous .local/adaptive-corridor/20261028-bursty-optimizer-v1 \
  --output .local/adaptive-corridor/20261028-symbolic-corridor-v1
OPENBLAS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 OMP_NUM_THREADS=1 \
  python3 -B scripts/audit_symbolic_corridor.py \
  --output .local/adaptive-corridor/20261028-symbolic-corridor-v1
OPENBLAS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 OMP_NUM_THREADS=1 \
  python3 -B scripts/research_pooled_symbolic.py \
  --previous .local/adaptive-corridor/20261028-symbolic-corridor-v1 \
  --output .local/adaptive-corridor/20261028-symbolic-pooled-v1
OPENBLAS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 OMP_NUM_THREADS=1 \
  python3 -B scripts/audit_pooled_symbolic.py \
  --output .local/adaptive-corridor/20261028-symbolic-pooled-v1
OPENBLAS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 OMP_NUM_THREADS=1 \
  python3 -B -m unittest discover -s scripts -p 'test_*.py'
```

Use new output directories. Each archive retains source snapshots, the declared grammar/objective, enriched earlier training references, searched structures, coefficients, selection, per-entry quotes, 11,648 case/group rows, 11,648 regime/group rows, 2,912 phase rows and 658 paired comparisons across 104 intervals in 74 sessions. Selection and all model files are saved and hashed before later replay, and checked unchanged afterward. Later outcomes do not return to the search. These repeatedly inspected dates remain development data rather than an independent holdout.

Both audits recomputed all ten formula models and their selection exactly, rebound 25,883 feature/OOF paths, verified 279,080 feature records and 22,290 preceding control predictions, and tested actual January/June counterfactuals for future-date exclusion, label maturity and online isolation given fixed base references. Non-bursty outcomes intentionally inform the shared offline model, but cannot update its online bursty pool. All admission and non-bursty prices remain unchanged. The comparison figure was visually checked.

The local suite ran **284 tests, with three existing optional skips and no failures**. Ten new tests cover nonlinear structure recovery, bounded grammar, chronology, no future-label fitting, causal replay, fallback, restart/continuous state, shared learning, shrinkage and bounded fit sampling. NumPy remains 1.26.1; no new dependency was installed. Remote CI was not run.

The result supports retaining the benchmark and capture hold. A larger unrestricted symbolic search would add overfitting opportunities without resolving the thin evaluation regimes or the finite startup bound. Further work should address objective/forecast drift and obtain genuinely unseen, adequately populated regime comparisons before choosing a capture candidate. Native continuity/deadline defects remain separate unresolved work, and the 48% target is still a research convention rather than payout-product validation.
