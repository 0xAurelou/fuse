# Adaptive corridor research — 27 October 2026

The subsequent [historical-data and regime iteration](ADAPTIVE_REGIME_DATA_RESEARCH.md)
adds 24 third-party Hyperliquid oracle sample days and a month of exchange-price
proxies. It compares directional regime models and checks transfer to the native
recordings; no successor was promoted. The initial prototype below is retained
as its original research result.

The saved raw oracle receipts support fitting adaptive formulas and replaying
them without another capture for each adjustment. The offline implementation is
`scripts/adaptive_corridor.py`. It preserves the original captures and their
frozen evaluations. It does not change the live quote engine, promote a policy,
or start collection.

The retained replay, exact source snapshots, hashes, per-window predictions and
regime comparisons are in `.local/adaptive-corridor/20261027-v2/`. Reproduce into
a new output directory:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 scripts/adaptive_corridor.py \
  --captures .local/prospective-runs/20261026-117ppm-8h \
             .local/prospective-runs/20261026-round2-314ppm-8h \
  --output /absolute/path/to/new-replay
```

## Formula and fitting

For every healthy historical 30-second path, the target is its smallest surviving
integer ppm half-width, including rounded barriers and touch-is-loss. Features
use paired admitted observations strictly before entry:

* One- and five-minute realized log-return variation, rescaled to a 30-second
  horizon in ppm.
* Absolute one-minute log return, scaled by 30/60, as a recent directional-move
  feature.
* Largest absolute price step in the preceding minute, in ppm.

The candidate shape is a weighted volatility mixture plus nonnegative trend and
jump terms. For each of 48 declared structural combinations, a shape-weighted
quantile exactly fits its positive scale before integer rounding and caps. The
structural combination minimizes training continuous quantile loss. This is a
bounded empirical search, not a global optimum over all adaptive formulas.
[Quantile regression documentation](https://scikit-learn.org/stable/modules/generated/sklearn.linear_model.QuantileRegressor.html)
describes the quantile-loss principle; this script implements the small scalar
fit directly without adding a solver dependency.

All coefficients use only the first recording's earliest 60% of healthy windows,
further restricted to clean pre-entry history: **511 training windows**. The
remaining first-recording slices and the later recording never select model
coefficients. There is no interpolation or fallback prediction when a five-minute
lookback intersects a censored window. Every baseline uses the same eligible
rows. The comparison is conditional on complete healthy outcome paths; it does
not recover censored outcomes or establish whole-period quote availability.

For the legacy 48% reference target, the fit chose:

```text
vol300 = sqrt(sum(previous-five-minute log returns squared) * 30 / 300) * 1e6
width_ppm = clamp(ceil(1.0589578623079334 * max(1, vol300)), 1, 50000)
delta = floor(entry_price * width_ppm / 1e6)
lower = entry_price - delta
upper = entry_price + delta
```

Fast volatility, additional directional magnitude and jump weights were zero in
this training search. The formula still adapts through its changing volatility
input. Zero additional weights do not prove that pumping, dumping or jumps do
not matter. Distinct directional episodes remain scarce. The square-root time
rescaling is a feature definition to test, not an established forecasting law for
this oracle.

Model coefficients stay frozen during replay. Inputs and widths update for each
new entry; an accepted corridor stays fixed for its entire 30-second lifetime.
The 50,000-ppm clamp is an explicit offline research bound, not an approved
production limit; no observed prediction reached it.

## Replay results

The fixed baseline fitted on the same training rows was **323 ppm**. This differs
from the older 314-ppm experiment because fitting here requires clean pre-entry
history as well as a healthy outcome window. The original 314-ppm result remains
unchanged.

| Chronological slice | Windows | Fixed width survival | Adaptive survival |
| --- | ---: | ---: | ---: |
| First recording training | 511 | 48.14% | 47.36% |
| First recording validation | 159 | 49.69% | 45.28% |
| First recording final slice | 189 | 70.90% | 50.26% |
| Later recording | 752 | 64.49% | 55.45% |

The adaptive formula improves later overall calibration but still misses the
legacy 43–53% acceptance band in the later recording. Its quantile loss also
decreases on the later slices; all loss and width statistics are retained in the
CSV rather than using survival alone to select a visually attractive result.

| Later-recording prior volatility | Windows | Fixed survival | Adaptive survival | Adaptive mean half-width |
| --- | ---: | ---: | ---: | ---: |
| Quiet | 443 | 83.52% | 56.21% | 157.3 ppm |
| Normal | 100 | 47.00% | 52.00% | 327.3 ppm |
| Volatile | 209 | 32.54% | 55.50% | 522.1 ppm |

Use the generated CSV as the numerical authority. Pump/dump groups in the later
recording contain only 7 up and 18 down windows under the exploratory five-minute
directional-efficiency definition. These correlated groups cannot establish
separate directional calibration. Jumps also remain a limited sample.

Both recordings had already been examined before proposing the model, so every
number above is retrospective development evidence. Chronological coefficient
isolation prevents direct fitting on later outcomes; it does not turn previously
inspected recordings into fresh prospective holdouts. Serial dependence and
nonrandom capture gaps remain material limitations.

## Target and next experiment

The default 48% target continues the old reference experiment. The payout product
instead needs target survival `(1 - h) / M` for payout multiplier `M` and target
gross house edge `h`, before costs. `--target-survival` permits another research
target; the current sample does not validate the rare-event multiplier surface
or LP economics. See [barrier pricing](BARRIER_PRICING.md).

Before a fresh experiment, choose and freeze the formula, target, inputs,
freshness/history rules, rounding, bounds and regime evaluation plan. Repair the
[capture continuity and deadline issues](CAPTURE_INVESTIGATION_20261027.md), then
measure the frozen adaptive rule against new observations. Updating coefficients
online would need a separately specified and frozen learning schedule. No live
candidate is promoted by this replay.

Seven focused tests cover scalar quantile optimality, integer touches and caps,
future-price isolation, missing-history rejection, recovery of a known synthetic
trend/jump formula, isolation from later outcomes and preservation of retained
experiments. The complete Python suite passes with its existing optional skips.
