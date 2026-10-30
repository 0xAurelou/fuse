# Frozen-entry pricing and additional flat periods — 27 October 2026

Follow-up: [startup admission and changing flat conditions](STARTUP_ADMISSION_RESEARCH.md)
compares 21 guards over eight-hour starts, adds matched raw controls and a full
raw August day, and retains calibration and availability failures. No successor
or capture is promoted.

The new two-part pricing alternative improves the remaining August frozen
entries from **57.94% to 53.22%**, with the same 233 entries offered. It also
improves frozen-entry calibration on a newly retrieved complete raw January
day from **55.64% to 51.75%**, with the stricter pause held fixed. August still
narrowly misses the 43–53% reference band. Other periods and startup failures
prevent a stability or readiness claim. **No live candidate or capture started.**

## Pricing formula

The pause mask is fixed to the previous `frozen_floor_53` research alternative.
Non-frozen widths, outcome eligibility and the original engine are unchanged.
Every offered and refused reference path remains in the shadow denominator.
The target remains the legacy 48% experiment, not multiplier-specific payout
validation.

Sixteen variants compare static training adjustments, rolling corrections using
all or only previously offered frozen paths, shorter memories, idle groups,
faster correction steps, entry-clock updates and a two-part distribution. Every
correction uses only eligible past outcomes, available 30 seconds after expiry;
current outcome eligibility never controls an entry decision.

The useful diagnostic alternative is **`hurdle_all_120`**. Let `p₀` be estimated
minimum-width survival, and `F₊` the conditional distribution of required width
above the 1-ppm minimum. For widths at least that minimum:

```text
F(width) = p₀ + (1 − p₀) × F₊(width)
positive-component quantile = (0.48 − p₀) / (1 − p₀)
```

If `p₀ ≥ 0.48`, request the minimum width. Otherwise request that positive
quantile, expressed as a ratio to the original entry width. Both components
shrink toward period-balanced original training observations with a fixed
12-observation prior. The rolling pool contains the latest 120 mature frozen
reference outcomes, including refused ones, at most four hours old. At least
12 are needed before the new correction activates. The multiplicative correction
is bounded to 0.05–2 and changes by at most 2% per frozen entry; the resulting
width is rounded upward and bounded to 1–50,000 ppm. These limits apply to the
additional correction, not the complete width when its inputs change.

The minimum-width atom is an exact integer-price feasibility quantity; it is
not necessarily identical to zero movement. The empirical mixture is not a
confidence bound or a guaranteed conditional probability. Pricing cannot lower
survival below a state's actual minimum-width floor. No accepted corridor moves.

## Original data: same paths and same availability

| Frozen-entry sample | Baseline | Two-part alternative | Offered paths |
| --- | ---: | ---: | ---: |
| Original validation | 46.54% | 48.11% | 318 |
| Original final slice | 53.03% | 49.70% | 330 |
| August within final slice | 57.94% | **53.22%** | 233 |

August changes from 135 to 124 survivors on the same 233 offered frozen paths.
It would require at most 123 survivors to fall below the 53% ceiling. This small
boundary miss is not a reason to tune a coefficient to one more known outcome.
August aggregate offered-entry survival improves from **52.84% to 52.23%** at
unchanged **78.10%** eligible availability. Its full-window shadow survival
improves from **56.93% to 54.99%** on all 2,324 paths. Final full-window loss
improves from **79.1569 to 79.0692 ppm** on the same 10,672 paths; original
validation loss changes slightly adversely, **110.4984 to 110.4999 ppm**.

Pooled frozen success must not hide individual periods:

| Final day | Offered frozen paths | Baseline | Two-part alternative |
| --- | ---: | ---: | ---: |
| June | 22 | 40.91% | 40.91% |
| July | 24 | 50.00% | 50.00% |
| August | 233 | 57.94% | 53.22% |
| September | 22 | 18.18% | 18.18% |
| October | 29 | 51.72% | 51.72% |

Native overall survival remains 47.96%/47.47%, with 100% eligible availability.
There are only 10/7 frozen paths in the respective native runs, fewer than the
12-outcome activation minimum. Thus the unchanged native results do **not**
validate the new rolling frozen correction.

Earlier 6/9/12-day training prefixes score the next 3/3/2 days inside the
original first 14 sample days. The selection objective adds mean and worst
frozen-day error for groups with at least 20 offered paths to the previous
overall/availability objective, with a 10% full-window loss guard. The earlier
folds select **`offered_frozen_60_fast`**, tied with `all_frozen_120_clock` at
7.0354; the two-part alternative scores 7.5253, versus baseline 8.3005.
The selected faster variant still gives August **58.37%** frozen survival.
The two-part alternative is therefore a promising diagnostic, not a winner
promoted from the August cell.

## Additional raw flat periods

The existing normalized collection already covers every free first-of-month
sample since the provider's October 2024 coverage start. Its normalized emitter
can omit unchanged messages, so lack of normalized rows is not sufficient to
establish an upstream outage. The documented raw API also provides first-of-month
samples without a key. Official Hyperliquid S3 history uses requester-paid
transfer; this work used only the anonymous free route.

Sources: [provider coverage](https://docs.tardis.dev/historical-data-details/hyperliquid),
[raw API and disconnect markers](https://docs.tardis.dev/api/http-api-reference),
[official archive details](https://hyperliquid.gitbook.io/hyperliquid-docs/historical-data).

Downloaded five four-hour raw BTC panels, plus five minutes of left history
each: dense pre-entry flat-feature windows in January/July 2025 and May 2026,
and fixed 06–10 UTC controls in June 2025 and January 2026. Dense selection uses
pre-entry features, never subsequent movement or survival. The 1,225 minute
responses contain **70,982 messages** and **598 observed equal-price stretches
lasting at least 30 seconds**, including left-history spans. They contain 185
spans at least 60 seconds long. These spans are not independent episodes.

Raw prices match the normalized price at **all 34,294 shared timestamps**.
Raw and normalized panels remain separate datasets. Each keeps the eight-second
observation-gap and five-minute clean-history requirements; no interval is
interpolated. Four explicit raw disconnect markers are retained. A marker is
untimestamped, so it becomes known at the following timestamped message; that
outcome window is censored and subsequent history is excluded. No future marker
retroactively suppresses an earlier entry prediction.

| Four-hour panel | Raw eligible paths | Matched normalized eligible paths | Raw frozen paths | Minimum-width frozen survival |
| --- | ---: | ---: | ---: | ---: |
| January 2025 | 466 | 230 | 98 | 43.88% |
| July 2025 | 479 | 479 | 101 | 24.75% |
| May 2026 | 468 | 474 | 64 | 28.13% |
| June 2025 | 479 | 41 | 101 | 30.69% |
| January 2026 | 468 | 0 | 230 | **61.74%** |

The January 2026 panel supplies a second high-floor case beyond August. Its
frozen group cannot reach the reference band at any positive integer-ppm width
on those observed paths. The stricter pause refuses 200 frozen entries, leaving
30 offered at **83.33% survival**, with an offered minimum-width floor of
**66.67%**. All are during the initial evidence accumulation; the two-part
correction cannot rescue them. Overall availability falls to **57.26%**, and
aggregate offered survival remains **57.09%**. The other four raw panels make
zero refusals under either the existing or stricter floor rule.

## Complete January day

The high-floor discovery triggered a full-day developmental follow-up, retaining
every interval. All 1,440 raw minutes are archived, reusing 245 already pinned
minutes. It contains **83,884 messages**, **715 ≥30-second observed flat spans**,
301 spans at least 60 seconds long, and a longest observed span of **593.255
seconds**. Shared normalized prices agree at all 31,128 common timestamps.
The full day and its four-hour subset overlap and must not be counted as
independent evidence.

Raw messages yield **2,768** clean-history eligible paths and **1,004** frozen
paths, versus **125/9** in the original normalized day. Original artifact
eligibility is unchanged; these are newly qualified paths in a separate raw
dataset, not backfilled native receiver receipts.

| Full January day, two-part pricing | Offered frozen survival | Overall offered survival | Eligible availability |
| --- | ---: | ---: | ---: |
| No pause | 55.88% on 1,004 | 51.12% | 100% |
| Existing pause | 54.07% on 799 | 50.18% | 92.59% |
| Stricter floor pause | **51.75% on 514** | **49.17%** | **82.30%** |

With the stricter pause fixed, baseline pricing gives 55.64% frozen and 50.04%
overall survival on those identical 514/2,278 offered paths. The pricing
alternative lowers those to 51.75%/49.17% without another refusal. However,
the earlier-fold-selected faster variant still misses narrowly at **53.11%**
frozen survival on the same day. Coefficients fit only preceding original
training days; no raw panel refits the coefficients or selects a variant.
The normalized controls use matched horizons and resets.

The separate startup audit compares continuous full-day calibration against
fresh four- and eight-hour starts with five minutes of raw feature history,
including the original 06–10 control. Full-day baseline parity is checked before
slicing. Its complete results remain in `flat-startup-audit-v2/blocks.csv`;
successful whole-day results cannot stand in for every capture start or regime
segment. Four-hour frozen results illustrate the instability:

| January UTC interval | Continuous survival / offered | Fresh-start survival / offered |
| --- | ---: | ---: |
| 00–04 | 50.00% / 138 | 50.00% / 138 |
| 04–08 | **64.29% / 84** | **64.41% / 59** |
| 08–12 | No quotes / 0 | **67.35% / 49** |
| 12–16 | **39.71% / 68** | 52.80% / 161 |
| 16–20 | 51.85% / 135 | **54.81% / 135** |
| 20–24 | 51.69% / 89 | **56.06% / 66** |

In 04–08, even continuously calibrated offered frozen entries have a **55.95%**
minimum-width floor. Therefore delayed pause activation under regime drift is
also a problem, beyond startup and width estimation. The original 06–10 interval
offers 12 frozen paths at 41.67% with full-day state, versus 30 at 83.33% on a
fresh start. Those thin groups do not support a probability guarantee. Continuous
overall availability falls to **50.87%** in 08–12, despite the acceptable full-day
82.30% figure.

Eight-hour fresh starts, matching the intended next capture length, also fail
to establish stability:

| January UTC start | Frozen survival / offered | Overall survival | Eligible availability |
| --- | ---: | ---: | ---: |
| 00–08 | **55.41% / 222** | **54.02%** | 85.96% |
| 08–16 | 51.28% / 117 | 50.62% | **70.60%** |
| 16–24 | **53.13% / 224** | 46.61% | 95.57% |

Keeping full-day state instead of restarting at 08:00 yields frozen survival
of only **39.71% on 68 offered paths** over 08–16. Warm state is not uniformly
better: the pause and pricing memories both lag a changing flat-state regime.

## Artifacts, verification and decision

Retained research directories under `.local/adaptive-corridor/`:

* `20261027-frozen-pricing-v4/`: final 16 variants, models, earlier-fold ranking,
  every prediction, per-day/activity/regime results and source snapshots.
* `20261027-raw-flat-panels-v3/`: five additional raw panels, matched normalized
  controls, frozen coefficients, gap/marker metadata, rows and flat spans.
* `20261027-raw-flat-jan2026-v1/`: complete raw January day with the same tests.
* `20261027-flat-startup-audit-v2/`: full-day versus restart audit, with exact
  retained full-day parity checks.

Anonymous response bytes, request URLs, SHA-256 hashes and downloader snapshots
are under `.local/market-history/tardis-hyperliquid-BTC-raw-flat-panels-v1/`
and `tardis-hyperliquid-BTC-raw-jan2026-v1/`. Earlier pricing iterations and the
failed first raw parser attempt are preserved separately. The final pricing
iteration fixes zero-loss guard arithmetic without changing any result or
ranking from v3. The raw parser handles the provider's seven fractional-second
digits with exact millisecond flooring.

Verification: **148 Python tests, passing with three existing optional skips**.
Eleven new tests cover price/pause separation, delayed eligibility, offered-only
versus all-reference learning, the two-part formula, correction clock/bounds,
reset/age expiry, outer-data isolation, perfectly flat zero-loss folds, raw
timestamp precision, disconnect causality and flat-span gap separation.
Source snapshots and original source bindings remain pinned. Native receipts,
original frozen analyzers, accepted policies and live pricing remain unchanged.

This is substantial new development evidence, not an independent holdout or a
fresh prospective capture. All dates were already visible in normalized form;
raw retrieval adds previously excluded trajectories. January's full-day check
follows discovery of its four-hour failure. The main remaining problems are
startup admission when the floor is not yet estimable, conditional drift across
short periods, September's thin frozen sample, and choosing a pricing rule that
generalizes rather than one that repairs a known cell. Capture continuity and
deadline repairs also remain outstanding. No successor is promoted and no
capture is started by this research.
