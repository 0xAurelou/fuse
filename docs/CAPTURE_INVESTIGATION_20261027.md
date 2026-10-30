# Capture-gap and corridor investigation — 27 October 2026

The subsequent [28 October reliability repair](CAPTURE_RELIABILITY_20261028.md)
addresses native deadline cancellation and adds a versioned supervisor with
freshness reporting. It passes simulated resume/silent-socket tests; a physical
host drill and a reliable new eight-hour capture remain outstanding. The original
investigation and recordings below are unchanged.

The investigation is complete. Both frozen recordings and their prospective
results are unchanged. No new candidate was selected and no capture was started.
The detailed report, input hashes, archived analysis code, window-level CSVs,
curves and gap evidence are retained in
`.local/capture-investigation/20261027-v2/`.

Reproduce into a new output directory:

```sh
PYTHONDONTWRITEBYTECODE=1 MPLCONFIGDIR=/private/tmp/fuse-matplotlib-cache \
python3 scripts/investigate_capture.py \
  --captures .local/prospective-runs/20261026-117ppm-8h \
             .local/prospective-runs/20261026-round2-314ppm-8h \
  --power-events .local/capture-investigation/20261027-v2/power-events.txt \
  --output /absolute/path/to/new-investigation
```

## Capture reliability

Both receipt chains passed native verification using their original frozen Go
executable. The diagnostic reconstruction matches every window’s eligibility and
price-path metrics from each frozen analyzer.

Round 2 lost 135/960 windows. **120 of those windows overlap simultaneous
receiver staleness**, totaling **58.70 minutes** with both receivers stale. The
longest receipt silence was **19.56 minutes**, on both connections. The last
hour had only **2 healthy windows out of 120**. The remaining exclusions include
startup, receiver disagreement and single-receiver/boundary effects. In the first
recording there were no receiver silences longer than the eight-second freshness
limit; its 16 exclusions were startup and disagreement/boundary effects.

The retained Mac power log records **Clamshell Sleep** beginning around
00:09–00:10 WITA on 27 October. Repeated sleep/dark-wake periods align with the
common receiver gaps. Capture logs show timeouts, unavailable local addresses and
network-address changes around those intervals. Two sockets on the same laptop
and endpoint share these failures. The idle-sleep guard did not prevent
lid-closed sleep.

The second process also completed verification about **15.47 hours after the
frozen deadline**. Local Go time documentation warns that monotonic time may stop
during system sleep; the existing context/timer design is consistent with that
late completion, but a controlled suspend/wake drill is still needed to reproduce
it. The separate wall-clock submission check worked: **zero receipts outside the
original eight-hour interval were retained**. Neither the delayed process exit
nor this investigation extends the sample period.

Before another unattended capture, use an always-on host or an open-lid powered
Mac, enforce a wall-clock deadline after resume, and monitor per-receiver
freshness and supervisor health. Do not relax oracle eligibility to hide gaps.
These are required follow-up improvements; the investigation does not claim to
have deployed them or recovered missing prices.

## Corridor comparison

All widths were evaluated on the **same healthy windows within each recording**.
Survival uses exact integer rounding and inclusive barrier-touch failure.

| Corridor half-width | First recording | Round 2 |
| --- | ---: | ---: |
| 250 ppm / 2.50 bps | 39.62% | 51.88% |
| 275 ppm / 2.75 bps | 44.92% | 55.88% |
| 300 ppm / 3.00 bps | 50.11% | 59.27% |
| 314 ppm / 3.14 bps | 52.54% | 61.33% |

Exact retrospective widths yielding 43–53% survival were **267–319 ppm** in the
first recording and **202–260 ppm** in round 2. Their ranges do not overlap:
there is no fixed integer width meeting the target in both observed healthy
samples. This is an empirical feasibility result, not an independent-sample
confidence claim or a conclusion about missing windows.

## Regimes use information available before entry

The original frozen labels depended on the corridor being evaluated, making some
conditional outcomes nearly tautological. This investigation preserves those
reports and uses new exploratory labels for comparisons. Labels do not change
with corridor width and use only the preceding five minutes of paired prices.

Low/medium/high realized log-return variation cutoffs, estimated from the first
recording’s training portion only, were **8.486 and 10.885 bps**. A lookback
covering an invalid window is marked `insufficient_clean_history`. No missing
prices were interpolated. Separate axes describe prior directional efficiency
and a prior maximum-step jump threshold. These are research definitions requiring
prospective evaluation, not approved production classifications.

| Prior volatility | First recording: windows / survival at 314 ppm | Round 2: windows / survival at 314 ppm |
| --- | ---: | ---: |
| Quiet | 374 / 70.86% | 443 / 83.07% |
| Normal | 260 / 42.69% | 100 / 47.00% |
| Volatile | 225 / 32.00% | 209 / 32.06% |
| Insufficient clean history | 85 / 56.47% | 73 / 32.88% |

This variation also appears before the major transport gaps: at 314 ppm,
round-2 survival was **391/477 (81.97%) in hours 1–4** and **115/346 (33.24%) in
hours 5–7**. Capture failures alone do not explain the pricing instability.

Following a recent large step, survival at 314 ppm was **3/30** in the first
recording and **4/33** in round 2. These small, correlated groups are not robust
calibration evidence. The directional-trend groups contained only 4 and 25
windows, respectively. There were 13 and 7 flat 30-second price paths, but no
complete flat five-minute histories. Trend, jump and flat-oracle coverage remain
limited; percentages cannot substitute for adequate evidence.

All corridor sizes, volatility/trend/jump groups and denominators are available
in `corridor-comparison.csv`. `hourly.csv`, `windows.csv` and `gaps.json` retain the
attribution needed to audit the summary.

## Decision before the next candidate

Do not make another global width adjustment based only on the pooled survival
rate. First make collection reliable and investigate a model whose width depends
on previously observed market conditions, using chronological training and a
fully specified frozen formula. Its limits, payout/fee assumptions, tail-risk
controls and regime evaluation plan need separate review and fresh prospective
evidence. Full-ladder economics remain outstanding.

The first capture supplied round-2 training data. This combined analysis is
post-hoc exploration, with nonrandom censoring and strong serial dependence; it
is not new validation of every tested width. No production approval follows.

Validation: 95 Python tests ran successfully with three optional Go-bridge tests
skipped. New tests cover exact correspondence with frozen window rules,
freshness/equality boundaries, overlap arithmetic, past-only feature isolation,
exact-touch scoring, power-event parsing and exact feasible-width intervals.
