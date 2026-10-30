# Residual quantile-level feedback — 28 October 2026

The subsequent [full raw-oracle pipeline refit](FULL_RAW_PIPELINE_RESEARCH.md)
revisits the core engine, frozen overlay and admission rather than only bursty
pricing. Additional raw training support does not repair the later frozen-state
calibration/availability conflict; the candidate hold remains.

The new controller changes the residual CDF's quantile level using matured
survival errors, rather than always taking its 48th percentile. A fast variant
raises June's later survival from **8/22 to 10/22 in both modes** and improves
several bursty panel pass counts without refusing quotes. This is a useful
research lead, but it does not meet the goal: January still has startup/later
cancellation, frozen-state and directional misses remain, some pricing losses
increase, and the fast gain did not win earlier selection. **No candidate is
promoted or frozen for capture, and no capture starts.**

The full run took **89.64 seconds**, including input verification, earlier
selection and later diagnostics. Sources, selection, per-entry predictions,
reachability bounds and comparisons are retained in
`.local/adaptive-corridor/20261028-quantile-level-v1/`.

## Why this comparison

Earlier multiplicative feedback and symbolic corrections repeatedly left June
later survival at 8/22. An exact reachability check rules out a hard fourfold
ceiling as the explanation: **16/22 restart and 17/22 continuous** required widths
are within four times their respective frozen gap forecasts. Only three paths
survive the absolute one-ppm minimum, and none of these forecasts is itself at
one ppm. These are hindsight bounds, not usable entry signals; they show that
this particular failure is not structurally forced by the absolute minimum or
the correction ceiling.

The new mechanism is inspired by
[adaptive conformal inference](https://arxiv.org/abs/2106.00170) and
[quantile tracking/control](https://arxiv.org/abs/2307.16895). It is a bounded
research adaptation, **not an implementation of their coverage guarantees**.
Discrete price barriers, a restricted oracle state, delayed labels, level/width
limits and finite eight-hour intervals prevent importing a long-run or
conditional guarantee from those papers.

## Frozen mechanism and selection

The experiment retains the previous Bayesian candidate's gap forecast,
chronological residual priors and full-precision parameters: approximately
61.58-minute half-life, 6.03-hour maximum age, 0.838 prior observations,
40% maximum multiplier change per supported entry and 0.921 learned-prior
weight. Neither the forecast nor its coefficients are refitted.

For each matured clean bursty reference, including refused references:

```text
level = clip(level + gain * (0.48 - shadow_survived), 0.02, 0.98)
requested_multiplier = weighted_quantile(prior_knots + recent_ratios, level)
width = clip(ceil(gap_forecast * limited_multiplier), 1, 50000)
```

The level starts at 0.48. Gains are fixed at **0.01, 0.03 and 0.10** before
selection. Each is tested with the existing 0.25–4 multiplier limits and with
those relative limits removed; absolute width limits remain in both. A
static-level relaxed control isolates the effect of removing the relative
limits. The retained benchmark and previous Bayesian controller make nine
variants in total. CDF ratios use at most 120 clean matured bursty paths, the
original time decay and prior mass. Labels enter at expiry plus thirty seconds.
An outward level update at an absolute width bound is blocked. Stale evidence
resets the level; restart state is private and continuous scoring boundaries
do not reset it. Missing market context retains the benchmark quote.

Earlier selection uses the unchanged 6/9/12-date prefix tests, objective,
full-reference loss guards, and availability constraints. The original controls
reconstruct exactly. Selection is pinned and hashed before later diagnostics:

| Variant | Earlier score | Fold scores |
| --- | ---: | --- |
| Slow level feedback, either bound rule | **15.602** | 14.455 / 16.417 / 15.935 |
| Previous Bayesian controller | 15.788 | 14.455 / 17.186 / 15.723 |
| Medium level feedback, either bound rule | 17.309 | 14.772 / 16.417 / 20.739 |
| Fast level feedback, either bound rule | 17.430 | 14.883 / 16.417 / 20.989 |
| Retained benchmark | 20.812 | 20.736 / 21.387 / 20.313 |

The slow bounded method wins by declaration-order tie breaking. The relaxed
static control exactly matches the previous Bayesian scores. The earlier folds
still contain only two distinct bursty cases with at least twenty paths. The
fast method's later improvements cannot retrospectively change this ranking.

## Cross-period calibration and availability

Passes mean at least twenty offered paths and observed survival in 43–53%.
These are descriptive screens with coarse finite counts, not independent
statistical certifications. Panels and restart/continuous paths overlap.

| Bursty panel | Retained restart / continuous | Bayesian | Selected slow | Fast bounded |
| --- | --- | --- | --- | --- |
| Original raw | 4/8 · 2/5 | 5/8 · 3/5 | 5/8 · 3/5 | **8/8 · 4/5** |
| Canonical full raw | **5/5 · 4/5** | 4/5 · 4/5 | 4/5 · 4/5 | 5/5 · 3/5 |
| Later normalized test | 7/11 · 6/11 | 6/11 · 6/11 | 5/11 · 7/11 | **9/11 · 9/11** |

The selected slow controller weakens later restart calibration. The fast
controller improves original raw and later normalized passes, but loses a
canonical continuous pass. Removing its relative correction limits does not
improve these pass counts and can worsen phase behavior.

No admission decisions change and all existing bursty quotes remain offered.
Original raw overall eligible-path availability stays **8,314/9,291 = 89.48%**
under the primary frozen admission policy and **8,192/9,291 = 88.17%** under the
secondary policy. Frozen, active and sparse prices remain unchanged. Original
raw restart overall/non-frozen pass counts stay 10/10, while frozen passes
remain 4/10. Later normalized overall passes remain 14/15, and frozen restart
passes remain 0/4. Historical eligibility does not establish capture uptime.

Fast bounded bursty full-reference pricing loss increases **48.336 → 53.823 ppm**
on original raw restart paths and **80.650 → 85.383 ppm** on later normalized
restart paths. Canonical continuous loss increases **65.532 → 70.226 ppm**.
These are quantile-loss changes, not measured fees, financial losses or LP costs.

## Phases and directional evidence

Each cell below gives startup survivors/count · later survivors/count. Startup
is the first twelve pre-entry bursty predictions, independent of outcomes.

| Matched interval | Retained restart / continuous | Selected slow | Fast bounded |
| --- | --- | --- | --- |
| January 2025 | 10/12 · 13/39 / 9/12 · 15/39 | 7/12 · 13/39 / 8/12 · 13/39 | 7/12 · 16/39 / 7/12 · 16/39 |
| June 2025 | 5/12 · 8/22 in both | 5/12 · 9/22 in both | **5/12 · 10/22 in both** |
| January 2026 | 9/12 · 6/13 in both | 8/12 · 5/13 in both | **8/12 · 4/13 in both** |

Fast June later survival reaches **45.45%**, but its later quantile loss rises
**71.622 → 78.111 ppm restart** and **71.184 → 79.684 ppm continuously**.
January 2026's fast aggregate is **12/25 = 48%**, while its startup and later
survival are **66.67% and 30.77%**. That aggregate therefore does not demonstrate
stable conditional pricing. Relaxing the correction bound lowers continuous
January later survival further to **2/13**.

The previously established January startup minimum-width constraint remains:
eight of twelve paths survive one ppm, and the allowed two case refusals cannot
bring that observed startup subset below 60% survival. Changing CDF levels
cannot eliminate this finite-subset conflict.

On later normalized restart bursty paths, fast bounded survival is **49.65% range
(141 paths)**, **46.62% mixed (266)**, **80% pump (five)** and **52.38% dump
(twenty-one)**. Across all activity states, pooled directional rates are near
target, but per-period pump passes are still only **1/9**, versus retained 2/9;
dump passes are 5/10 versus 4/10. Pooled rates cannot replace date-level
comparisons, and five bursty pump paths cannot establish directional calibration.

## Verification and next decision

The audit recomputes earlier selection exactly, verifies 279,080 feature records,
checks all 66,870 prediction records and reconstructs 14,860 preceding control
predictions. Actual January/June counterfactuals confirm mature-label timing,
non-bursty label isolation given fixed underlying references, and learning
independent of refusals. Every grid/entry/eligible denominator and all non-bursty
prices remain fixed. Seven new tests cover these causal rules, private restart
state, stale resets, declared bounds, exact zero-gain equivalence and a known
synthetic distribution shift. The complete Python suite passes **302 tests with
three existing optional skips**. No new dependency was installed; remote CI was
not run.

```sh
OPENBLAS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 OMP_NUM_THREADS=1 \
  python3 -B scripts/research_quantile_level.py \
  --previous .local/adaptive-corridor/20261028-symbolic-corridor-v1 \
  --output /absolute/path/to/new-quantile-level-run
OPENBLAS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 OMP_NUM_THREADS=1 \
  python3 -B scripts/audit_quantile_level.py \
  --output /absolute/path/to/new-quantile-level-run
```

The archive contains 14,976 case/group rows, 14,976 regime/group rows, 3,744 phase
rows, 312 reachability summaries and 846 paired comparisons across 104 intervals
in 74 sessions. Selection and code hashes remain unchanged through diagnostics.
All inspected dates remain development data.

The experiment identifies a controller response that can repair June's finite
survival count, but a prospective candidate still needs a defensible choice
across dates, startup/later phases, frozen states and directions. The evidence
does not support simply loosening multiplier limits or promoting the
later-best gain. A reliable new eight-hour capture and validated payout/LP
economics remain outstanding. Collection tooling repairs are tracked separately
in the [capture reliability report](CAPTURE_RELIABILITY_20261028.md).
