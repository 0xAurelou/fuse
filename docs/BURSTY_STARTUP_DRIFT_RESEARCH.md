# Bursty startup, later drift and restart/continuous calibration — 28 October 2026

Twelve alternatives were replayed across the same **172 eight-hour intervals** with admission, frozen pricing and original outcome eligibility fixed. Earlier-period selection now scores both restart and continuous modes and first-twelve/later phase error. It **retains `floor10_burst_pool120`**, the previous research candidate. No new alternative is selected, no live candidate is promoted and **no capture starts**.

The faster correction clock improves raw bursty passes from **4/8 to 5/8** and later normalized bursty passes from **7/11 to 8/11** in restart mode and **6/11 to 7/11** in continuous mode. It also worsens pooled later-phase survival from **42.39% to 41.75%**. A time-weighted distribution mixture brings that later group to **47.90%**, but passes only **3/8** raw bursty cases. These methods solve different pieces and do not establish stable startup/drift calibration.

## January and June diagnosis

The raw January failures are distinct. In January 2025, the previous pool passes the aggregate at 45.10% while first-twelve survival is 83.33% and later survival 33.33%. In January 2026, the 08:00 and 16:00 restart slices need corrections in opposite directions. At 08:00, **8 of the first 12 bursty paths survive at the minimum 1-ppm width**, so pricing alone cannot bring that observed subset into the 43–53% band. This is an attainable-width limit on a small retained subset, not a probability guarantee about future startup.

In the June 2025 raw control, median required-width/base-width rises from **0.947** in the first twelve decisions to **1.773** later. Carrying the earlier narrow-width evidence is a plausible source of drift error. The previous pool leaves survival at 38.24% overall. The normalized June 2026 day has separate high-survival failures and is compared below; the dates and sources are not pooled as one event.

![Startup and later calibration](../.local/adaptive-corridor/20261028-bursty-drift-v1/startup-drift-comparison.png)

## Raw restart calibration and phase error

All calibration pass counts use the legacy 48% target / 43–53% band with at least twenty eligible and quoted paths per group. Only eight of the ten raw restart tests have at least twenty bursty paths. First-twelve and later groups are ranked using pre-entry predictions, including decisions later censored; phase summaries are descriptive rather than pass tests. The first twelve bursty decisions can span hours.

| Alternative | Overall passes | Non-frozen passes | Bursty passes | First 12 survival | Later survival | Bursty same-path loss (ppm) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `engine_floor10` | 10/10 | 10/10 | 1/8 | 61.02% | 49.19% | 48.362 |
| `feedback_state_fast` | 8/10 | 10/10 | 3/8 | 61.86% | 45.31% | 48.899 |
| `floor10_burst_pool120` | 10/10 | 10/10 | 4/8 | 59.32% | 42.39% | 48.310 |
| `burst_clock120` | 10/10 | 10/10 | 5/8 | 58.47% | 41.75% | 48.494 |
| `burst_clock60` | 10/10 | 10/10 | 4/8 | 58.47% | 44.34% | 48.508 |
| `burst_feedback_leaky` | 10/10 | 10/10 | 1/8 | 61.02% | 49.19% | 47.995 |
| `burst_cdf120` | 10/10 | 10/10 | 3/8 | 59.32% | 44.98% | 48.095 |
| `burst_cdf60` | 10/10 | 10/10 | 3/8 | 60.17% | 47.90% | 47.899 |
| `burst_cdf60_own` | 10/10 | 10/10 | 2/8 | 60.17% | 48.22% | 48.131 |
| `burst_cdf60_prior4` | 10/10 | 10/10 | 3/8 | 60.17% | 46.28% | 47.757 |
| `burst_cdf60_guard` | 10/10 | 10/10 | 3/8 | 60.17% | 47.90% | 47.924 |
| `burst_cdf60_fast` | 10/10 | 10/10 | 2/8 | 59.32% | 48.22% | 48.052 |

The pooled first-twelve group has **118 eligible paths**, the later group **309**. They have different period weights, so a pooled phase difference is not by itself proof of within-run drift. The per-period examples above and phase archive retain that distinction. Quantile loss and calibration counts need not rank methods in the same order.

Eligible quote availability is unchanged under both admission rules: **89.48% pooled / 60.38% minimum** under previous-floor admission and **88.17% / 65.82%** under warmup/floor30 admission. All 6,932 eligible non-frozen paths remain offered. Full-grid and pre-entry denominators are checked too; these values are not capture uptime. Frozen forecasts remain identical, including their unresolved failures.

| Raw source / UTC start | Bursty n | Simple floor | Full feedback | Previous pool | Faster clock | Time-weighted CDF |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| raw_control / 2025-01-01 04:15 | 51 | 58.82% | 52.94% | 45.10% | 43.14% | 56.86% |
| raw_control / 2025-06-01 06:00 | 34 | 41.18% | 41.18% | 38.24% | 38.24% | 41.18% |
| raw_control / 2025-07-01 09:30 | 10 | 20.00% | 20.00% | 20.00% | 30.00% | 20.00% |
| raw / 2026-01-01 00:00 | 16 | 56.25% | 56.25% | 56.25% | 50.00% | 56.25% |
| raw / 2026-01-01 08:00 | 25 | 64.00% | 64.00% | 60.00% | 52.00% | 64.00% |
| raw / 2026-01-01 16:00 | 29 | 31.03% | 34.48% | 34.48% | 37.93% | 34.48% |
| raw_control / 2026-05-01 07:15 | 92 | 55.43% | 47.83% | 48.91% | 48.91% | 51.09% |
| raw_control / 2026-08-01 00:00 | 75 | 58.67% | 56.00% | 53.33% | 53.33% | 58.67% |
| raw_control / 2026-08-01 08:00 | 49 | 46.94% | 55.10% | 44.90% | 44.90% | 51.02% |
| raw_control / 2026-08-01 16:00 | 46 | 56.52% | 47.83% | 47.83% | 45.65% | 50.00% |

The faster clock improves the January 2026 08:00 aggregate from 60.00% to 52.00%, but the 16:00 restart remains at 37.93% and the June 2025 raw control at 38.24%. The time-weighted CDF reduces late overshoot in the pooled phases without correcting those whole-case failures. No alternative passes all eight sufficiently populated raw bursty tests. The smaller-prior CDF reduces raw bursty loss most among these new variants, but it is not selected and still passes only 3/8 cases.

The January 08:00 aggregate gain is itself a cancellation: the faster clock
retains **75.00%** survival on the first twelve decisions, then falls to
**30.77%** on the later thirteen. The previous pool's corresponding later group
was **46.15%**. The clock removes two later survivors to obtain its passing
52.00% aggregate; it does not solve conditional startup calibration. The observed
minimum-width floor in the early group remains 66.67%. This trade-off is a reason
to retain the earlier selection result rather than promote the higher raw pass
count.

## Restart versus continuous

Continuous scoring retains the day’s earlier mature evidence; restart scoring clears it at each eight-hour start. Modes reuse observations and are not independent tests. Both native recordings have fewer than twenty bursty paths and no continuous counterpart. The June 2025 raw control is an eight-hour panel only: no full-day raw June continuous comparison is available. Normalized June 2025 has only five eligible bursty paths across its whole day, so it cannot fill that evidence gap.

| Split / mode | Simple floor bursty passes | Full feedback | Previous pool | Faster clock | Time-weighted CDF | Smaller-prior CDF |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| validation / restart | 3/9 | 6/9 | 6/9 | 6/9 | 4/9 | 6/9 |
| validation / continuous | 4/9 | 8/9 | 6/9 | 6/9 | 5/9 | 6/9 |
| test / restart | 5/11 | 6/11 | 7/11 | 8/11 | 6/11 | 7/11 |
| test / continuous | 4/11 | 7/11 | 6/11 | 7/11 | 7/11 | 7/11 |

| Split / mode | Pricing | Non-frozen passes | Bursty mean absolute case error (pp) | Bursty / non-frozen loss (ppm) |
| --- | --- | ---: | ---: | ---: |
| validation / restart | Simple floor | 13/13 | 7.03 | 104.456 / 112.191 |
| validation / restart | Full feedback | 13/13 | 3.89 | 106.410 / 114.880 |
| validation / restart | Previous pool | 13/13 | 4.96 | 106.186 / 112.272 |
| validation / restart | Faster clock | 13/13 | 5.28 | 106.071 / 112.267 |
| validation / restart | Time-weighted CDF | 13/13 | 5.38 | 105.996 / 112.264 |
| validation / restart | CDF, smaller priors | 13/13 | 4.21 | 105.979 / 112.263 |
| validation / continuous | Simple floor | 13/13 | 6.60 | 103.364 / 112.193 |
| validation / continuous | Full feedback | 13/13 | 3.79 | 105.426 / 114.989 |
| validation / continuous | Previous pool | 13/13 | 4.96 | 104.985 / 112.270 |
| validation / continuous | Faster clock | 13/13 | 5.06 | 105.127 / 112.276 |
| validation / continuous | Time-weighted CDF | 13/13 | 4.73 | 105.116 / 112.276 |
| validation / continuous | CDF, smaller priors | 13/13 | 3.89 | 105.116 / 112.276 |
| test / restart | Simple floor | 14/15 | 7.94 | 79.476 / 83.609 |
| test / restart | Full feedback | 15/15 | 5.01 | 80.047 / 85.792 |
| test / restart | Previous pool | 15/15 | 4.75 | 80.303 / 83.646 |
| test / restart | Faster clock | 15/15 | 4.33 | 80.609 / 83.659 |
| test / restart | Time-weighted CDF | 14/15 | 6.11 | 79.551 / 83.613 |
| test / restart | CDF, smaller priors | 15/15 | 4.56 | 79.634 / 83.616 |
| test / continuous | Simple floor | 14/15 | 8.07 | 79.503 / 83.576 |
| test / continuous | Full feedback | 15/15 | 4.36 | 80.390 / 85.689 |
| test / continuous | Previous pool | 15/15 | 5.17 | 79.555 / 83.578 |
| test / continuous | Faster clock | 15/15 | 4.70 | 80.819 / 83.634 |
| test / continuous | Time-weighted CDF | 14/15 | 5.58 | 80.010 / 83.598 |
| test / continuous | CDF, smaller priors | 15/15 | 4.95 | 80.060 / 83.601 |

## Identical-path mode comparison

The paired analysis intersects eligible bursty entry timestamps within each source/date/interval and checks identical entry price and realized movement. This avoids interpreting different denominators as model consistency. The archive retains **81 matched intervals per alternative**, including empty/small groups, with per-mode eligible counts, common-path counts, width disagreements, survival and loss. Summary gaps below use only common groups with at least twenty paths. A small gap can mean both modes fail in the same direction.

| Matched group | Cases ≥20 | Simple floor gap (pp) | Full feedback | Previous pool | Faster clock | Time-weighted CDF | Smaller-prior CDF |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Raw January 2026 | 2 | 1.72 | 1.72 | 0.00 | 1.72 | 1.72 | 1.72 |
| Raw August 2026 | 3 | 2.81 | 6.26 | 0.72 | 2.13 | 0.68 | 3.49 |
| Normalized validation | 9 | 0.43 | 1.08 | 0.49 | 0.53 | 0.64 | 0.32 |
| Normalized later test | 11 | 0.95 | 3.17 | 0.59 | 1.00 | 0.53 | 0.38 |

| Source / UTC start | Common bursty paths | Pricing | Restart survival | Continuous survival | Width disagreements |
| --- | ---: | --- | ---: | ---: | ---: |
| raw / 2026-01-01 08:00 | 25 | Time-weighted CDF | 64.00% | 64.00% | 15 |
| raw / 2026-01-01 08:00 | 25 | Faster clock | 52.00% | 52.00% | 5 |
| raw / 2026-01-01 08:00 | 25 | Previous pool | 60.00% | 60.00% | 24 |
| raw / 2026-01-01 16:00 | 29 | Time-weighted CDF | 34.48% | 37.93% | 13 |
| raw / 2026-01-01 16:00 | 29 | Faster clock | 37.93% | 34.48% | 17 |
| raw / 2026-01-01 16:00 | 29 | Previous pool | 34.48% | 34.48% | 17 |
| normalized / 2026-06-01 08:00 | 40 | Time-weighted CDF | 62.50% | 62.50% | 18 |
| normalized / 2026-06-01 08:00 | 40 | Faster clock | 62.50% | 62.50% | 33 |
| normalized / 2026-06-01 08:00 | 40 | Previous pool | 62.50% | 62.50% | 33 |
| normalized / 2026-06-01 16:00 | 34 | Time-weighted CDF | 55.88% | 55.88% | 6 |
| normalized / 2026-06-01 16:00 | 34 | Faster clock | 52.94% | 52.94% | 13 |
| normalized / 2026-06-01 16:00 | 34 | Previous pool | 55.88% | 55.88% | 19 |

The previous pool gives 60.00% in both January 08:00 modes: consistency does not make that a pass. Faster-clock January 16:00 is 37.93% restart / 34.48% continuous, so its startup gain does not resolve the opposite-direction miss. Normalized June 2026 08:00 remains 62.50% in both modes for the previous pool and faster clock. Its 16:00 slice improves from 55.88% to 52.94% in both modes with the faster clock.

## Methods and selection

All new overlays use the fixed 0.10 correction-floor base and change only bursty quotes. Other activity states and the frozen overlay retain that base. Existing floor, full-feedback and pooled-correction comparators are reconstructed against the previous archive.

* **Correction clocks:** retain the previous log-quantile hierarchy and priors, but move the private correction toward its mature target on every clean non-frozen grid entry, rather than only when another bursty quote appears. Both the existing 120/60 pools with a four-hour cap and 60/30 pools with a one-hour cap are tested.
* **Leaky feedback:** use each new quote’s own survival outcome with gain 0.10, but decay accumulated log correction toward zero with a 30-minute half-life. Updates are aged by their scheduled maturity after gaps; the factor still moves by at most 5% per clean non-frozen entry.
* **Distribution mixtures:** combine the stored training bursty CDF, a recent non-bursty parent CDF and recent bursty outcomes before taking the 48th percentile. This avoids geometrically blending a tiny lower quantile into a larger one. Training uses its existing 128 equal-mass positive-ratio knots and minimum-width atom; the atom is placed at the current minimum-width ratio. Positive ratios are normalized by training state factors. Unlike the clock-only ablations, bursty observations do not also appear in the CDF parent pool.
* CDF variants compare a four-hour unweighted pool with a one-hour pool and 30-minute time half-life, no parent transfer, smaller training/parent masses, a pump/dump bypass and a faster 15% burst-entry adjustment. The usual CDF step is 5% per bursty entry. The shared parent has fixed total mass after twelve mature observations; time weights change its composition. Bursty observation weights themselves decay, so their total evidence mass decreases with age.

All updates wait until expiry plus 30 seconds. Current/future path validity and movement never select current width. Refused reference paths continue learning. Pending observations beyond the age cap are discarded; period boundaries reset private state. Correction factors remain within 0.05–2, final integer widths within 1–50,000 ppm, and each issued quote stays fixed for its lifetime. Rate limits apply to the correction factor, not total width when the base changes.

| Alternative | Family | Parent / leaf memory | Age cap | Time half-life | Training / parent CDF mass | Step |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| `engine_floor10` | pinned comparator | — | — | — | — | — |
| `feedback_state_fast` | pinned comparator | — | — | — | — | — |
| `floor10_burst_pool120` | pinned comparator | — | — | — | — | — |
| `burst_clock120` | clock | 120/60 | 4h | 0min | 12/12 | 5% |
| `burst_clock60` | clock | 60/30 | 1h | 0min | 12/12 | 5% |
| `burst_feedback_leaky` | feedback | 60/30 | 1h | 30min | 12/12 | 5% |
| `burst_cdf120` | cdf | 120/60 | 4h | 0min | 12/12 | 5% |
| `burst_cdf60` | cdf | 60/30 | 1h | 30min | 12/12 | 5% |
| `burst_cdf60_own` | cdf | 60/30 | 1h | 30min | 12/0 | 5% |
| `burst_cdf60_prior4` | cdf | 60/30 | 1h | 30min | 4/4 | 5% |
| `burst_cdf60_guard` | cdf | 60/30 | 1h | 30min | 12/12 | 5% |
| `burst_cdf60_fast` | cdf | 60/30 | 1h | 30min | 12/12 | 15% |

The protocol declares all alternatives before their new results. Original 6/9/12 monthly training prefixes score the next 3/3/2 monthly dates in both modes. The previous bursty objective gains half the phase-error component, weighting first-twelve and later phases equally and weighting absolute case errors by paths within each phase. The mean mode score plus one-quarter absolute mode-score gap penalizes a large restart/continuous difference. The existing 10% same-path loss guard remains for non-frozen, bursty, pump and dump groups. Equal fold weights and declaration-order ties are fixed. Raw tests and 2026 failure periods do not select a candidate; the earlier normalized January/June 2025 dates still occur in the declared original training/scoring prefixes.

| Alternative | Score | Fold scores |
| --- | ---: | --- |
| `floor10_burst_pool120` | 21.557 | 22.972 / 21.387 / 20.313 |
| `burst_clock120` | 23.406 | 22.972 / 21.387 / 25.860 |
| `burst_cdf60_prior4` | 26.252 | 32.878 / 19.148 / 26.730 |
| `burst_clock60` | 28.266 | 32.146 / 21.387 / 31.265 |
| `feedback_state_fast` | 28.811 | 27.889 / 20.366 / 38.179 |
| `burst_cdf120` | 28.818 | 32.013 / 21.387 / 33.054 |
| `burst_cdf60_own` | 28.985 | 32.719 / 20.211 / 34.024 |
| `burst_feedback_leaky` | 30.734 | 33.668 / 20.324 / 38.209 |
| `engine_floor10` | 31.432 | 33.994 / 21.387 / 38.917 |
| `burst_cdf60` | 31.820 | 33.668 / 21.387 / 40.404 |
| `burst_cdf60_guard` | 31.820 | 33.668 / 21.387 / 40.404 |
| `burst_cdf60_fast` | 31.820 | 33.668 / 21.387 / 40.404 |

This retains the previous pool at 21.557, ahead of faster clock at 23.406. The earlier sample still has only two distinct eight-hour bursty cells with at least twenty paths in restart mode; continuous replay reuses those observations. Adding mode/phase terms does not create more independent burst episodes. No improvement on an inspected failure is substituted for this ranking after looking at the raw tests.

## Reproducibility and remaining work

Implementation: `scripts/bursty_drift.py`, `scripts/research_bursty_drift.py`. Retained archive: `.local/adaptive-corridor/20261028-bursty-drift-v1/`. It includes the declared protocol, source snapshots, earlier-fold models/ranking, 33,024 case/group/policy/model rows, 12,384 phase rows, 972 paired rows and compressed predictions. Final priors are reused from the hash-bound preceding bursty archive; the earlier selection folds refit on their original training prefixes. Original raw files, native receipts, input caches, parent metadata and source hashes are reverified. All three comparators, frozen/non-bursty invariance, masks, eligibility and availability are checked.

```sh
python3 -B scripts/research_bursty_drift.py \
  --previous .local/adaptive-corridor/20261028-bursty-pricing-v1 \
  --output .local/adaptive-corridor/NEW-NONEXISTENT-DIRECTORY
python3 -B -m unittest discover -s scripts -p 'test_*.py'
```

Validation: **196 tests run successfully, with three existing optional skips**. Twelve new tests cover expiry-plus-delay causality, private entry clocks, full-CDF arithmetic, recency weighting, parent/leaf separation, own-width feedback and decay, age/memory/period/rate bounds, guard and invariant behavior, pre-entry phase membership, identical-path pairing, and exclusion of later outcomes from both-mode selection.

The next unresolved pricing questions are startup evidence that can distinguish the opposite January conditions, and adaptation to changing burst episodes without later overcorrection. More earlier raw bursty episodes would help test those mechanisms; tuning repeatedly against these same few dates does not establish readiness. The June raw continuous-history gap, frozen-state misses and prior capture continuity/deadline issues remain unresolved. These findings keep capture on hold.

The [episode and raw full-day follow-up](BURSTY_EPISODE_RESEARCH.md) now fills
the January/June 2025 raw continuous-history gap. The original restart frames
reconstruct exactly, and June's matched bursty survival remains 38.24% in both
modes. Eleven alternatives test episode resets and feature-matched evidence;
none replaces the previous pool. New raw data exposes 100 eligible June bursty
paths versus five in the normalized day, providing a separate basis for later
chronological recalibration. Startup/late cancellation and drift remain open;
capture stays on hold.
