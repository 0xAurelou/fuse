# Startup admission and changing flat conditions — 28 October 2026

Twenty-one admission policies were implemented and compared with the previous
pricing fixed. A 12-outcome warmup with a 30-outcome floor window improves
joint overall/frozen calibration from **4/10 to 6/10 raw eight-hour tests**.
Its lowest overall quote availability rises from **60.38% to 65.82%**, while
pooled availability falls from **89.48% to 88.17%**. It is a diagnostic alternative,
not a selected replacement. **No policy passes all ten tests**, and earlier
training folds retain the previous rule. No candidate is promoted or capture
started.

The [non-frozen pricing follow-up](NONFROZEN_PRICING_RESEARCH.md) holds both
admission masks fixed and compares thirteen pricing refinements. Earlier-selected
state feedback brings non-frozen aggregate calibration to 10/10 raw eight-hour
tests without reducing availability. A simpler correction-floor relaxation also
passes all ten overall raw tests. Bursty and directional failures, pricing-loss
regressions and unchanged frozen misses prevent promoting either alternative or
starting capture.

## Admission changes

The fixed research pricing is `hurdle_all_120` from the previous iteration.
Every alternative preserves its widths, outcome eligibility, non-frozen
admission and full-window shadow outcomes. Gains here describe different offered
subsets; they are not pricing improvements on identical paths. The target is
the legacy 48% reference with a 43–53% band, not payout-product validation.

The alternatives cover:

* Refusing frozen entries until 12 or 30 eligible frozen reference outcomes have
  matured. These references continue to accumulate while entries are refused.
* Latest 30/60/120-outcome floor pools, with the original four-hour age limit or
  a shorter one-hour limit. The floor is empirical minimum 1-ppm survival.
* Hysteresis: pause above 53%, resume at 43%/48%, requiring two or six new mature
  outcomes. This is a research rule, not a confidence interval.
* A shadow-calibration guard: with 30 mature observations, pause outside
  38–58% shadow survival and resume within 43–53% after six new outcomes.
* An additional 60-second idle refusal, and clearing pending/mature evidence
  after missing pre-entry history.
* Conditional startup warmup only when pre-entry idle is at least 60 seconds
  or at least half the preceding ten 30-second bins have no observed change.
  This heuristic does not establish safety for the other entries.
* Combined fast/slow evidence: use the higher floor from latest 30 and 120
  outcomes, so a short pool cannot resume while the long pool remains high.
* A time-weighted floor with a 30-minute exponential decay time.

New frozen gates replace the previous frozen gate rather than being permanently
OR-ed with it. Other activity states retain their previous admission. Outcomes
enter a pool only **30 seconds after expiry**, and validity/movement/survival
are inspected only then. Periods and restarts clear state. Warmup re-arms if
evidence ages out; the missing-history variant also flushes pending observations.
Unchanged heartbeats are not price changes. No actual customer trade is assumed,
and no accepted corridor changes.

## Earlier selection and comparison design

The original earlier folds fit coefficients on 6/9/12 sample days and score the
next 3/3/2 within the first 14 days. Each scoring day is replayed as three fresh
eight-hour starts. The objective includes overall/directional/frozen calibration,
worst errors, the previous overall availability penalty with a stronger cost
below 85%, and an explicit cost for lost frozen availability. The 85% threshold
is a selection preference, not a product approval requirement. Calibration cells
need 20 offered paths; refusals still incur availability cost when they shrink
a cell below that threshold. No-quote cells never count as passing.

The previous gate wins at **13.298**. The closest new alternative is conditional
warmup with the time-weighted floor, **18.766**; conditional 30-outcome warmup
with dual memory scores **19.059**. The illustrative blanket 12/30 rule scores
**25.967**. The newly retrieved controls do not select a rule or fit coefficients.

The primary comparison contains **152 eight-hour cases**: three starts across
24 normalized days, with fresh and continuous modes kept separate; the same
modes for the full raw January day; and both original native runs. Five minutes
of raw/normalized left history support fresh later-day starts. Missing features,
future-censored outcomes and the complete 960-window grid remain visible.
The reconstructed original full-day/native results and previous January
eight-hour audit match exactly before new policies are evaluated.

## January: improvement that did not transfer everywhere

Fresh eight-hour starts in the complete January 2026 raw day:

| UTC interval | Previous frozen survival | 12/30 frozen survival | Previous →12/30 overall availability | 12/30 overall survival |
| --- | ---: | ---: | ---: | ---: |
| 00–08 | 55.41% | **52.43%** | 85.96% →81.97% | **53.23%** |
| 08–16 | 51.28% | **50.39%** | 70.60% →71.91% | 50.46% |
| 16–24 | 53.13% | **52.94%** | 95.57% →89.73% | 46.14% |

The 12/30 rule puts all three frozen cells in band, but the first overall cell
still misses. Blanket warmup also removes all 17 frozen entries in the native
runs because neither reaches 12 mature frozen observations. Native overall
availability is 98.94%; this supplies no successful frozen calibration test.
Conditional warmup with dual memory retains 12/17 native frozen entries and
99.69% overall availability, but its frozen sample remains too small.

On original normalized final-slice fresh starts, the 12/30 rule worsens offered
frozen survival from **56.54% to 61.38%**, with frozen availability falling
45.58% →34.61%. The conditional dual-memory variant gives 54.46% at 36.16%.
Adding its shadow guard yields a favorable pooled 47.98%, but only **one of four**
originally substantial frozen cases passes, and frozen availability falls to
23.63%. Pooled survival is not an adequate selection criterion.

## Additional raw eight-hour controls

To check the normalization issue exposed by January, the 21 policy definitions
were pinned before retrieving additional raw outcomes. Four previous four-hour
panels were extended to eight hours with the same starts: January/July 2025,
June 2025 and May 2026. The complete August 2026 raw day was also retrieved.
This used the same documented free anonymous first-of-month route, with no
credentials or paid transfer. Of 3,380 retained minute files, 980 were reused
with identical hashes and 2,400 newly downloaded. There are **196,742 raw
messages**, with zero oracle-price mismatches at **105,323 shared normalized
timestamps**. Explicit disconnect markers and >8-second gaps remain screened;
no missing path is interpolated.

The new raw tests plus the three existing January starts form **ten distinct
eight-hour raw test intervals across six dates**, containing 9,291 qualified
paths and 2,359 frozen paths. Fresh and continuous modes are never pooled.
Matched normalized controls and all continuous-day results are retained separately.

| Policy | Both overall/frozen cells pass | Frozen passes | Pooled overall availability | Lowest overall availability |
| --- | ---: | ---: | ---: | ---: |
| Previous floor rule | 4/10 | 4/10 | 89.48% | 60.38% |
| Blanket 12-outcome warmup, 30-outcome floor | **6/10** | **7/10** | **88.17%** | **65.82%** |
| Conditional 12-outcome warmup, dual memory | 5/10 | 6/10 | 86.50% | 56.83% |
| Conditional dual memory plus shadow guard | 5/10 | 6/10 | 82.60% | 56.83% |

The complete 21-rule table is retained in the control artifact's `report.md`.
The illustrative 12/30 alternative lowers mean absolute frozen case error from
**7.86 to 4.95 pp** and worst frozen error from **36.38 to 12.49 pp**. It offers
1,260/2,359 frozen paths, versus 1,382 previously. Its worst **overall** case
error worsens slightly, **8.76 to 9.01 pp**. This is a tradeoff, not dominance.

All four added non-August controls pass both cells with the 12/30 rule, at
96.93%, 98.73%, 98.61% and 98.61% overall availability. August remains the
shared failure:

| Raw August UTC interval | Previous frozen survival / offered | 12/30 frozen survival / offered | Previous →12/30 overall availability | 12/30 overall survival |
| --- | ---: | ---: | ---: | ---: |
| 00–08 | 58.72% / 172 | **60.00% / 160** | 80.58% →79.29% | **57.01%** |
| 08–16 | 84.38% / 32 | **60.49% / 81** | 60.38% →65.82% | **55.14%** |
| 16–24 | 54.61% / 152 | **53.24% / 139** | 100% →98.61% | 50.27% |

The middle raw August frozen group has a **61.95% minimum-width floor** over
389 paths. The 12/30 rule's retained 81-path subset still has a **59.26% floor**,
so narrower positive integer-ppm widths cannot repair that observed subset.
The dual-memory rule refuses every frozen entry in that interval. Even then,
unchanged non-frozen quotes survive **54.30%**, above the reference ceiling.
Non-frozen survival is also **56.17%** in the first August interval. Admission
changes confined to frozen entries do not repair those conditional pricing misses.

## Artifacts and decision

Retained under `.local/adaptive-corridor/`:

* `20261028-startup-admission-v1/`: first 15-policy comparison.
* `20261028-startup-admission-v2/`: final 21 policies, earlier-fold ranking,
  all original-source cases, source snapshots and compressed input/prediction
  archives. Original 15-policy metrics are exactly unchanged after the additions.
* `20261028-admission-8h-controls-v1/`: pinned-policy raw checks, matched controls,
  per-case denominators, joint-pass counts, all forecasts and the detailed report.

Response bytes, request URLs, reuse bindings and source snapshots are in
`.local/market-history/tardis-hyperliquid-BTC-8h-admission-controls-v1/`.
`scripts/startup_admission.py` implements the causal guards;
`research_startup_admission.py` runs the earlier comparisons;
`fetch_admission_controls.py` prepares the bounded extension; and
`validate_admission_controls.py` tests it without changing policies.

Verification: **161 Python tests run, passing with three existing optional skips**.
Thirteen new tests cover maturity, future-outcome isolation, warmup, hysteresis,
shadow recovery, gap reset, age expiry, dual/time-weighted evidence, strict
boundaries, unchanged widths and denominators, outer-data isolation and the
requirement for actual offered samples in joint-pass counts. Native receipts,
original eligibility, frozen analyzers and live pricing are unchanged.

These are retrospective development tests. Dates were previously inspected in
normalized form; half of each extended control was already available in raw
form. Policy freezing before the added raw data prevents another round of
threshold tuning on it, but does not create independent validation. Cases and
observed flat episodes are serially dependent. Quote availability is among
qualified paths, not continuous capture uptime; pre-entry and full-grid counts
are retained as well. No-quote or fewer-than-20 offered cells do not pass.

**No successor selected, no new capture.** Earlier-fold selection keeps the
previous guard. The shorter-memory warmup remains a useful research alternative,
but no tested policy generalizes across all eight-hour starts. The next required
research includes pricing the non-frozen August misses alongside the floor and
admission dynamics, plus capture continuity/deadline repairs before any fresh run.
