# Flat/bursty oracle behavior and pump drift — 27 October 2026

Follow-up: [flat-state pauses and quote availability](FLAT_PAUSE_RESEARCH.md)
compares twelve rules with the pricing engine fixed. A stricter mature-floor
rule brings August's aggregate survival to 52.84% at 78.10% availability, but
does not resolve conditional misses or establish evidence for promotion.

The offline activity-aware rule improved pump calibration, native transfer and
the difficult flat-heavy period. It still does **not** justify starting a new
capture: the difficult day misses the reference band even after entry pauses.
All original recordings, outcomes and live pricing remain unchanged.

Final artifacts are retained in:

* `.local/adaptive-corridor/20261027-activity-features-v1/`: immutable past-only
  feature dataset, raw-source bindings and source-code snapshots.
* `.local/adaptive-corridor/20261027-activity-calibration-v2/`: protocol, models,
  rankings, per-period/per-regime results, refusal counts and every prediction.

The first comparison remains separately retained as `activity-calibration-v1`.

## Observations and feasibility

The normalized August 2026 sample contains recorded oracle prices unchanged for
up to **577.740 seconds**, while context messages continue arriving. Unchanged
message arrivals must not be counted as new price movements.

A free raw-message spot check at **1 August 2026, 11:55–11:56 UTC**, inside that
stretch, contains **58 BTC activeAssetCtx messages**, all explicitly carrying
`oraclePx = 63076.0`. Funding takes 12 distinct values and open interest takes
10, while oracle and mark prices remain unchanged. Thus the flat price field
already exists before CSV normalization for this checked minute. This does not
prove complete upstream observation, establish the cause, or verify the entire
nine-minute interval. The raw slice also has one leading disconnect marker.
The unchanged-value pattern is not evidence that every field or the connection
was inactive.

The raw response, request URL, timestamps and locally computed SHA-256 are retained
in `.local/adaptive-corridor/20261027-raw-flat-audit-v1/`. Access used the documented
unauthenticated first-of-month route, without a key or billed account:
[provider raw API](https://docs.tardis.dev/api/http-api-reference.md).

The added features use only observed prices **strictly before entry**:

* Distinct price changes over the last 30, 60 and 300 seconds.
* Time since the last observed change, with a lower-bound flag if no change has
  been observed since the day's first anchor.
* Fraction of the preceding ten 30-second bins with no change.
* Fraction of five-minute realized variance contributed by the largest change.

Duplicate unchanged heartbeats cannot alter these features. There is no invented
change at startup, interpolation or modification of the original path eligibility.

Exploratory states are frozen (idle ≥30 seconds), then sparse (≥30% empty bins or
≤3 changes/minute), then bursty (one change contributes ≥50% of variation), and
otherwise active. These are recorded-process labels, not verified feed-health
claims or proof that the upstream oracle stopped updating.

Of **742** eligible August paths entered in the frozen state, **56.47%** survive
even a **1-ppm** half-width, the minimum width in this research family. Survival
only increases with wider corridors. Thus no positive integer-ppm width can
bring that observed conditional group into the **43–53%** band. This is an
empirical feasibility result for those paths, not a future-probability guarantee
or a claim about finer-than-ppm pricing models.

## Model iteration and selection

Eight variants compare the previous phase/rolling rule with activity-specific
scales, conditional rolling corrections, wider bounded corrections, a separate
pump correction pool and explicit pauses. Expanding folds use only the original
first 14 training sample days: train on 6/9/12 and score the next 3/3/2. Outer
periods and native recordings do not choose model parameters. All periods were
already inspected during earlier development, so this remains retrospective.

The leading inner-fold rule is **`activity_pause_wide`**. It retains the prior
fast/slow volatility and pump-phase formula, adding:

* Activity multipliers fitted from period-balanced training quantiles and shrunk
  toward one. Groups below 80 windows or three periods use the parent.
* Global and context-specific corrections using mature reference outcomes.
  Active pumps have their own rolling pool; other entries use their activity
  pool. A subgroup needs 12 mature observations and shrinks toward the global
  correction with a fixed 30-observation prior.
* A correction bounded to **0.4–2.0**, changing by at most **2% per new entry**.
  This limit applies to the correction, not the entire width when market inputs
  or phase labels change. Outcomes mature 30 seconds after expiry. The previous
  120-window/four-hour memory, daily/run reset and initial learning rules remain.
* An explicit hypothetical new-entry pause when the training or mature-past
  empirical minimum-width survival floor is high. Training requires ≥200 windows
  over ≥3 periods and a floor above target+10 pp. Recent evidence requires ≥30
  mature subgroup observations and a floor above target+15 pp. These thresholds
  are research rules, not confidence bounds.

The initial training multipliers are approximately 1.0037 for active, 0.8716 for
bursty, 1.0673 for sparse and 1.1716 for frozen. A flat state does not necessarily
justify a narrower corridor: subsequent bursts and the conditional movement
distribution matter. The correction can respond to subsequent period drift.

Pauses are decided from training or mature past evidence, never the current
outcome. Paused reference paths still update calibration after maturity; no
customer entry is assumed. Full-window shadow predictions retain every original
eligible path. No earlier outcome is recategorized and no accepted barrier moves.

Selection explicitly penalizes lost availability, penalizes days below 85%
availability more strongly, and guards against >10% worsening in full-window
quantile loss. The top two inner scores are close, **3.465 versus 3.486**; this
does not establish a uniquely superior or robust production model.

## Results against the previous research rule

The target remains the legacy **48% reference**, not the complete payout surface.

| Diagnostic sample | Previous survival | Revised offered-entry survival | Revised full-window shadow | Offered among eligible paths |
| --- | ---: | ---: | ---: | ---: |
| Historical validation, overall | 48.99% | 48.42% | 48.42% | 100% |
| Historical validation, pumps | 52.26% | 51.18% | 51.18% | 100% |
| Historical final slice, overall | 51.30% | 49.30% | 49.87% | 97.43% |
| Historical final slice, pumps | 46.60% | 48.06% | 48.06% | 100% |
| Historical final slice, dumps | 49.73% | 50.27% | 50.27% | 100% |
| First native recording | 46.45% | 47.96% | 47.96% | 100% |
| Second native recording | 47.07% | 47.47% | 47.47% | 100% |

Historical final-slice pump/dump denominators remain **412/370**; neither group
loses entries. Native denominators remain **859/752**. The hypothetical pause
removes **274 of 10,672** eligible final historical entries, all on the August
day. There are no paused eligible validation or native entries. Availability
here is measured among the existing clean-history, outcome-eligible paths; it is
**not capture coverage** or a claim to offer quotes throughout missing history.

| Final diagnostic day | Previous | Revised offered | Revised shadow | Offered among eligible paths |
| --- | ---: | ---: | ---: | ---: |
| 1 June | 47.98% | 48.55% | 48.55% | 100% |
| 1 July | 49.03% | 48.28% | 48.28% | 100% |
| 1 August | 62.95% | **54.98%** | **56.93%** | **88.21%** |
| 1 September | 47.91% | 47.86% | 47.86% | 100% |
| 1 October | 46.93% | 46.82% | 46.82% | 100% |

The August improvement is not entirely from refusal: its full-window shadow
survival falls from 62.95% to 56.93% before considering pauses. Refusing 274
entries lowers the offered-entry rate further to 54.98%, which **still fails**.
All 2,324 original eligible August paths remain visible in the shadow result.

Mean absolute daily error falls from **2.00 to 0.80 pp** in validation and from
**3.43 to 1.82 pp** in the final slice for offered entries. On the final slice,
worst daily error falls from **14.95 to 6.98 pp**. On the identical 10,672 eligible
paths, full-window shadow quantile loss improves from **79.38 to 79.16 ppm**
(`full-window-loss-audit.json`). Pump-specific quantile loss increases from
132.90 to 133.88 ppm on the same 412 paths; better calibration percentages do
not imply improvement on every loss measure. Quoted-only overall loss has a
different denominator after pauses and must not be compared as if paths matched.

Pump drift improves in July (46.10% →48.23%) and October (42.61% →45.22%). June
remains 55.56% on 72 pump paths; August has only five pump paths. Full per-period
regime denominators are in `period-groups.csv`, not concealed by the pooled
48.06% pump result. Serial dependence still limits interpretation.

## Decision and remaining work

No capture or live policy update has started. The leading rule improves the
requested behaviors but still misses the difficult day and has a close inner
selection margin. Further work should inspect the duration and reliability of
the conditional flat-state floor, the delay before rejecting an unpriceable
state, the availability/calibration tradeoff, and remaining pump periods.
Choosing a stronger pause or narrower bound solely to fix the known August
sample would be another development iteration, not independent validation.

Third-party first-of-month sampling, normalized carried index values, nonrandom
freshness exclusions and dependence remain material. The captured-source
continuity/deadline issues also remain separate work. Payout pricing requires
multiplier-specific `(1-h)/M` targets and economic validation.

## Reproduction and verification

```sh
PYTHONDONTWRITEBYTECODE=1 python3 scripts/oracle_activity_features.py \
  --history .local/adaptive-corridor/20261027-oracle-history-v1 \
  --captures .local/prospective-runs/20261026-117ppm-8h \
             .local/prospective-runs/20261026-round2-314ppm-8h \
  --output /absolute/path/to/new-activity-features

PYTHONDONTWRITEBYTECODE=1 python3 scripts/research_activity_calibration.py \
  --dataset .local/adaptive-corridor/20261027-activity-features-v1 \
  --previous .local/adaptive-corridor/20261027-stability-v2 \
  --output /absolute/path/to/new-activity-research
```

The old rule is reconstructed exactly on every historical split. Original raw
archives, feature snapshots and native receipts are bound by hashes; native
chains/frozen analyzers were verified during activity-feature preparation. The
analysis retains predictions, matured evidence counts, refusal reasons, shadow
outcomes, every model and fold, and the exact code used.

Validation: **130 Python tests ran successfully, with three existing optional
skips**. Added tests cover strict pre-entry activity, heartbeat invariance, startup
anchors, state precedence, exact previous-rule parity, delayed eligibility,
future-outcome isolation, pause/shadow denominators, sparse-group fallback,
correction bounds and isolation from outer-period model selection.
