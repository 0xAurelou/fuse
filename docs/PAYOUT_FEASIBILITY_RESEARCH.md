# Payout and quote-availability feasibility — 28 October 2026

Flat oracle paths impose a payout-dependent constraint before model fitting,
fees or capital controls. On the retained January/August raw days, even a
perfect refusal policy cannot retain 85% of the evaluated paths and support
equal-stake **5× zero-cost break-even**. This is a necessary finite-sample
constraint, not a future probability forecast or a production decision.

The [frozen eight-hour adaptive trial](PROSPECTIVE_ADAPTIVE_20261028.md) continues
unchanged. This study reads only retained development data, not that trial's
receipts or pricing outcomes. It selects no new formula and changes no quote,
model, threshold, payout or capture deadline. Reliable 48% calibration and
complete LP economics remain open goals.

## Exact bound

The product pays **stake × multiplier**, including the original stake. At a
fixed multiplier `M`, equal stakes and survival probability `p`, gross LP profit
per unit stake is `1 − M*p`. The configured research 5% gross-edge assumption
therefore targets `p = 0.95/M`; zero-cost break-even permits `p <= 1/M`.
The provisional research target of 48% is distinct from the 2× model's 47.5%.

On any healthy thirty-second path with **zero admitted oracle movement**, every
valid positive-width corridor survives. This remains true below one ppm. The
screen deliberately counts only zero movement, rather than treating the
earlier one-ppm minimum as a universal product floor. The actual product's ppb
quantization can create additional mandatory survivors; ignoring them makes this
bound optimistic.

Let `N` be the evaluated path count, `Z` its zero-motion count and `K` the number
retained. Even with perfect hindsight, at least `max(0, Z − (N − K))` retained
paths survive. Grant that every other retained path loses. To have survival at
most `u < 1`, the largest possible retained count is:

`K_max = min(N, floor((N − Z)/(1 − u)))`.

This grants future knowledge, unconstrained discrimination and favorable widths
for every moving path. It ignores lower calibration bands, width caps and
learning error. Failing it rules out the requested combination on those paths.
Passing it does **not** exhibit an implementable causal policy. Keeping zero
paths is reported as zero availability, never as successful calibration.

This is a count-based survival screen with one equal-stake ticket per retained
path at a fixed payout. Actual stake-weighted returns, arbitrary entry times,
selective traders, overlapping positions, refunds, debt, fees and capital flows
require separate stateful replay. No result here is a measured LP return.

## Data and results

The canonical cache contains twenty-four first-of-month UTC dates from November
2024 through October 2026. Complete raw days replace normalized days once on
twelve dates. Formats and repeated intervals are not pooled as independent
observations. The screen evaluates healthy outcome paths with clean pre-entry
history, retains grid/healthy/clean denominators and uses pre-entry regime and
activity labels. Outage-censored outcomes are outside the evaluated cohort;
these percentages are not full-grid uptime or an operational admission policy.

| Full raw day | Evaluated paths | Zero-motion paths | Maximum retention at 5× zero-cost break-even | Maximum retention at configured 5× 5% gross edge |
| --- | ---: | ---: | ---: | ---: |
| January 2026 | 2,768 | 1,008 (36.42%) | **79.48%** | **78.47%** |
| August 2026 | 2,766 | 895 (32.36%) | **84.53%** | **83.48%** |
| September 2026 | 2,758 | 47 (1.70%) | 100% | 100% |
| October 2026 | 2,769 | 48 (1.73%) | 100% | 100% |

The provisional 85% overall availability screen is incompatible with even
zero-cost 5× break-even on January/August's evaluated days. This varies over
dates; September/October passing the bound cannot establish cross-period
feasibility or calibration. Nonnegative reserve fees and operating costs cannot
repair an already negative gross edge.

The 5× zero-cost constraint is stronger in these separate eight-hour raw cells:

| Date and start, UTC | Evaluated paths | Zero-motion paths | Maximum retention |
| --- | ---: | ---: | ---: |
| January 2026, 00:00 | 926 | 353 | 77.32% |
| January 2026, 08:00 | 916 | 389 | 71.83% |
| August 2026, 00:00 | 927 | 352 | 77.45% |
| August 2026, 08:00 | 902 | 391 | 70.73% |

For the frozen activity subgroup, the configured 10× target permits at most
**49.78%** retention on August's 894 evaluated paths, below the provisional 50%
frozen screen. January's corresponding bound is 51.89%. At 25× and above,
January and August both fail that frozen screen. These are subgroup-specific
necessary constraints, not proposed live pause thresholds.

Across full canonical days, 5× through 100× fail the configured target/85%
combination on two of twenty-four dates; 250× and above fail on three, adding
June 2025. Frozen subgroup comparisons have twenty-one populated dates;
unpopulated groups remain visible and are not counted as passes.

## Why a 48% pass does not validate economics

Even at 2×, the provisional 43–53% research band spans gross margins from **+14%
to −6%** before costs. At exactly 48%, an equal-stake 2× batch has 4% gross
profit per stake. An illustrative flat 35% allocation of positive batch profit
leaves 2.6%; an additional assumed 1%-of-stake cost leaves **1.6%**. An assumed
5% cost instead leaves **−2.4%**.

The 35% batch haircut is a sensitivity example, **not execution of LPVault's
fee logic**. The actual contract uses high-water, capitalization and path-dependent
accrual. The existing `replay_lp_economics.py` and `contract_lp_model.py` handle
those effects for their recorded command populations; they have not yet validated
this adaptive candidate or all nine payouts. Costs here are declared scenarios,
not measured gas prices, operating expenses or live fee schedules.

Reusing 48% at 5× would imply −140% gross profit per stake; payout-specific
widths must target different probabilities. This arithmetic is a warning against
that inference, not a claim that the frozen trial offers a 5× ticket at its
48% corridor. Its scope remains first-stage survival research.

Maximum liability also adds across correlated tickets. Ten fully funded
10-USDC tickets at 10,000× require **999,900 USDC** of maximum LP obligation.
If their stakes are entirely unfunded claims, the obligation is **1,000,000
USDC**. A small average survival probability does not justify netting that
worst-case reserve. Real capital, account limits, accepted exposure, debt and
withdrawal reserves still require engine-backed admission replay.

## Eight-hour evidence limits

An eight-hour nonoverlapping thirty-second grid has at most 960 windows before
warmup, health censorship or refusals. Under independent Bernoulli assumptions:

| Payout | Configured target | Expected survivors in 960 windows | Chance of at least one survivor |
| --- | ---: | ---: | ---: |
| 2× | 47.5% | 456 | ~100% |
| 100× | 0.95% | 9.12 | 99.99% |
| 250× | 0.38% | 3.648 | 97.41% |
| 1,000× | 0.095% | 0.912 | 59.85% |
| 10,000× | 0.0095% | 0.0912 | **8.72%** |

At the 10,000× target, 31,533 independent windows—about 10.95 uninterrupted days—
would give a 95% chance of seeing even **one** survivor. One event is not a
calibration estimate. Serial dependence, conditional regimes and lower availability
make the real evidence problem harder. This does not authorize extending the
current trial, changing its target or claiming independent observations.

## Verification and next evidence

Artifacts are retained at
`.local/adaptive-corridor/20261028-payout-feasibility-v1/`. The audit rebuilds
20,736 case/target rows and all CSVs exactly, independently checks maximality on
20,052 nonempty bounds, and binds source, policy and input hashes. Five tests
include exhaustive small-population feasibility checks, exact integer boundaries,
cost arithmetic, additive funded/unfunded liability and rare-event counts.
The full Python suite passes **336 tests, with three existing optional skips**.

```sh
OPENBLAS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 OMP_NUM_THREADS=1 \
  python3 -B scripts/research_payout_feasibility.py \
  --dataset .local/adaptive-corridor/20261028-temporal-data-v1 \
  --late-raw .local/market-history/tardis-hyperliquid-BTC-temporal-late-v1 \
  --policy engine/config/paper-recovery.json \
  --output /absolute/path/to/new-payout-feasibility-run
OPENBLAS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 OMP_NUM_THREADS=1 \
  python3 -B scripts/audit_payout_feasibility.py \
  --output /absolute/path/to/new-payout-feasibility-run
```

The active trial must first complete its original fixed horizon and frozen
analysis. Its result can establish or contradict transfer for the research
challenger; it cannot establish the full payout menu's economics. Subsequent
payout work needs separately frozen multiplier-conditioned probabilities,
feasible availability by regime, adequate rare-event evidence and stateful
stake/strategy/fee/cost/correlated-exposure replay. None is replaced by passing
this necessary bound or a pooled 48% rate.
