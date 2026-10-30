# Flat-state pause and quote availability — 27 October 2026

Follow-up: [frozen pricing and additional raw flat periods](FROZEN_PRICING_RESEARCH.md)
adds a two-part pricing alternative and verifies a second high-floor case in
raw January 2026 history. Whole-day and fresh-start results differ materially;
no candidate or capture is promoted.

The stricter mature-floor rule fixes **aggregate August calibration in this
retrospective replay**, at a material availability cost. It is retained as a
research alternative, with the current selected gate unchanged. No capture or
live update has started.

Artifacts are in `.local/adaptive-corridor/20261027-flat-pause-v1/`:
`protocol.json`, `research.json`, `report.md`, all predictions, daily results,
regime/activity results, earlier-fold scores, refusal episodes, source snapshots
and `pause-impact-audit.json`. The audit binds its research, prediction and
original feature inputs by SHA-256. The comparison is reproducible with:

```sh
python3 scripts/research_flat_pause.py \
  --dataset .local/adaptive-corridor/20261027-activity-features-v1 \
  --previous .local/adaptive-corridor/20261027-activity-calibration-v2 \
  --output /tmp/fuse-flat-pause-replay
```

The output directory must not already exist. All original data, eligibility,
the activity pricing model and the existing reference-window learning schedule
remain fixed. Every alternative has **identical corridor widths, corrections,
full-window shadow outcomes and full-window quantile loss**. This isolates entry
refusals from pricing improvements. The original gate reconstructs exactly on
every historical day and both native recordings.

## Rules compared

Twelve declared alternatives include the existing gate, no pause, additional
idle thresholds at 30/60/90/120 seconds, two recovery latches after 60 seconds idle,
and lower mature-floor thresholds at 53%/58%, with and without a 60-second idle
override. Added rules retain the existing gate. No-pause is an ablation.

The most available tested rule that brings August into the **43–53%** reference
band is **`frozen_floor_53`**. In addition to the existing gate, it refuses a new
entry when all three conditions hold:

1. The recorded price has not changed for at least 30 seconds before entry.
2. At least 30 eligible frozen-state reference outcomes have matured in the
   existing pool: latest 120, at most four hours old, available only 30 seconds
   after expiry, with the original daily/run reset.
3. More than 53% of that pool survived the minimum 1-ppm half-width.

This is a lagged empirical rule, not a confidence bound or guarantee. Missing
history still suppresses quotes; future outcome eligibility never decides entry.
All reference paths continue learning after maturity even while entries are
refused. Recovery-latch alternatives require two distinct observed changes in
the prior 30/60 seconds, persist through missing features and reset per day/run.
Unchanged heartbeats cannot release a latch or create price changes.

## August comparison

All **2,324** original eligible August paths remain in the full-window result.
The target is still the legacy **48%**, not multiplier-specific product pricing.

| Pause rule | Offered-entry survival | Offered / eligible | Availability | Refused |
| --- | ---: | ---: | ---: | ---: |
| No pause | 56.93% | 2,324 / 2,324 | 100.00% | 0 |
| Current gate | 54.98% | 2,050 / 2,324 | 88.21% | 274 |
| Idle ≥120 seconds | 54.16% | 1,959 / 2,324 | 84.29% | 365 |
| Idle ≥60 seconds | 53.43% | 1,810 / 2,324 | 77.88% | 514 |
| Idle ≥60 seconds, two-change/30-second recovery | 53.21% | 1,727 / 2,324 | 74.31% | 597 |
| **Frozen mature floor >53%** | **52.84%** | **1,815 / 2,324** | **78.10%** | **509** |
| Floor >53% or idle ≥60 seconds | 52.30% | 1,721 / 2,324 | 74.05% | 603 |
| Idle ≥30 seconds | 52.09% | 1,582 / 2,324 | 68.07% | 742 |

The complete twelve-rule table is in the artifact report. No tested rule both
passes August and preserves 85% eligible availability. That is the threshold
where the existing selection score adds a stronger availability penalty, not an
independently established product requirement.

The stricter floor gate costs **235 additional eligible entries**, or **10.11
percentage points** of August availability versus the current gate. Those added
refusals comprise 168 shadow survivors and 67 shadow failures. Across all 509
refusals there are 364 survivors and 145 failures. These are reference outcomes,
not actual trades or an economic profitability claim.

Full-window August survival stays **56.93%** and loss stays **32.4619 ppm** for
every rule. Quoted-only calibration improves by changing the offered subset.
It does not demonstrate better pricing on the same paths.

Among all 2,342 pre-entry decisions with a width, including later-censored
outcomes, the floor rule refuses 511 and offers 1,831: **78.18%** availability.
Across all 2,880 grid windows, including missing history, it offers **63.58%**.
The current gate offers 2,068/2,342 pre-entry decisions (**88.30%**) and
2,068/2,880 grid windows (**71.81%**). None of these ratios is continuous feed
uptime or native paired-capture coverage.

## Transfer and remaining calibration

| Sample | Current survival → stricter floor | Current → stricter availability |
| --- | ---: | ---: |
| Validation, 11,112 eligible paths | 48.42% →48.42% | 100% →100% |
| Final slice, 10,672 eligible paths | 49.30% →48.78% | 97.43% →95.23% |
| First native run, 859 eligible paths | 47.96% →47.96% | 100% →100% |
| Second native run, 752 eligible paths | 47.47% →47.47% | 100% →100% |

The stricter rule changes no validation or native decisions. In the final slice,
only August changes; June/July/September/October retain 100% eligible availability.
All 412 final pump and 370 final dump paths remain offered, with survival
48.06%/50.27%. Final mean absolute daily error falls from **1.82 to 1.40 pp**,
with all five aggregate days in the band. Full-window final loss is still
**79.1569 ppm** on the identical 10,672 paths.

Aggregate daily success does not resolve conditional pricing. Among August's
742 frozen entries, the current gate offers 468 at 64.74% survival. The stricter
gate offers 233 at **57.94%**, still outside the band. Their empirical minimum
width survival is **42.49%**, down from 52.78% in the previously offered frozen
subset. Therefore this retained subset is no longer demonstrably unpriceable
within the band at all positive integer-ppm widths; the remaining pricing and
adaptation lag deserve investigation. This is retrospective feasibility, not
evidence of a future conditional distribution. August sparse/bursty entries
also remain at **54.19%/58.45%**, with denominators 788/142.

There are 191 contiguous August refusal episodes on the 30-second grid under
the stricter rule, versus 102 currently. Median sampled duration rises from
30 seconds to one minute; the longest rises from seven to 9.5 minutes. These
are sampled decision runs, not independent market episodes. The tested recovery
latches consume additional availability while still missing August's aggregate
upper band; they do not improve this tradeoff.

## Selection and decision

The original earlier-fold procedure refits the activity engine on 6/9/12 sample
days and scores the next 3/3/2 inside the first 14 training days. It retains the
daily/directional/worst error objective and availability penalty. Identical
full-window losses need no extra differential loss penalty.

The **existing gate remains selected**. Existing, no-pause and both mature-floor
alternatives tie at **3.465088** because they make **zero refusals in every
earlier scoring fold**. The declared tie rule keeps the existing gate. Thus
earlier folds provide no discriminating evidence for changing the floor. The
blanket idle alternatives score worse overall. The final-training fit of the
stricter floor refuses two training entries, which is not fresh evaluation.

The 53% boundary comes from the existing reference band, but this is still
another experiment after August and all other periods were inspected. Its
aggregate pass is not independent validation. Source limitations, serial
dependence, thin pump periods and unresolved native capture reliability/deadline
issues remain. The next research question is pricing the retained frozen and
sparse/bursty paths without using refusal to conceal conditional misses, while
obtaining distinct evidence where a floor gate actually activates.

**No candidate promotion or new capture.** The stronger floor remains an
inspectable alternative with its full availability cost, not a replacement
chosen solely to repair August. Verification: 137 Python tests run, passing
with three existing optional skips; seven new tests cover pause boundaries,
recovery, maturity, future-outcome isolation, full denominators, baseline parity
and selection isolation.
