# Bursty pricing and correction-floor comparison — 28 October 2026

Twelve alternatives were compared on the same retained **172 eight-hour intervals** with frozen pricing and both admission masks fixed. The new variants apply only to bursty quotes; the non-bursty quotes retain their chosen base. Earlier expanding monthly folds select `floor10_burst_pool120`. This is research selection on previously inspected periods, not a promoted live candidate or an independent holdout. **No capture starts.**

The selected bursty-only pooled correction brings raw bursty passes to **4/8**, versus **1/8** for the simple 0.10 floor and **3/8** for the previous full feedback. It retains **10/10 overall and non-frozen raw passes**. Raw non-frozen quantile loss is **50.808 ppm**, essentially the same as the simple floor’s **50.811 ppm** and below full feedback’s **51.564 ppm**. This is progress on the retained paths, with unresolved failures described below.

## Raw eight-hour comparison

Passes use the legacy 48% reference, a 43–53% band and at least twenty eligible/quoted paths per group. The ten raw restart tests include only eight sufficiently populated bursty groups. Small groups remain visible rather than counting as passes.

| Pricing | Bursty passes | Non-frozen passes | Overall passes | Frozen passes | Non-frozen same-path loss (ppm) | Bursty same-path loss (ppm) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `baseline` | 0/8 | 7/10 | 7/10 | 4/10 | 50.822 | 48.750 |
| `engine_floor20` | 1/8 | 10/10 | 8/10 | 4/10 | 50.798 | 48.404 |
| `engine_floor10` | 1/8 | 10/10 | 10/10 | 4/10 | 50.811 | 48.362 |
| `feedback_state_fast` | 3/8 | 10/10 | 8/10 | 4/10 | 51.564 | 48.899 |
| `floor10_burst_static` | 1/8 | 10/10 | 9/10 | 4/10 | 50.827 | 48.619 |
| `floor10_burst_feedback4` | 3/8 | 10/10 | 10/10 | 4/10 | 50.831 | 48.677 |
| `floor10_burst_feedback1` | 3/8 | 10/10 | 10/10 | 4/10 | 50.822 | 48.533 |
| `floor10_burst_pool120` | 4/8 | 10/10 | 10/10 | 4/10 | 50.808 | 48.310 |
| `floor10_burst_pool60` | 3/8 | 10/10 | 10/10 | 4/10 | 50.796 | 48.110 |
| `floor10_burst_shape60` | 4/8 | 10/10 | 10/10 | 4/10 | 50.776 | 47.798 |
| `floor10_burst_shape60_guard` | 4/8 | 10/10 | 10/10 | 4/10 | 50.762 | 47.567 |
| `baseline_burst_shape60` | 4/8 | 7/10 | 7/10 | 4/10 | 50.776 | 48.009 |

Eligible quote availability is identical for all pricing alternatives: **89.48% pooled / 60.38% minimum** under previous-floor admission and **88.17% / 65.82%** under warmup/floor30 admission. Every non-frozen eligible path remains offered. The raw tests retain 9,291 eligible paths, of which 6,932 are non-frozen and 427 bursty. Complete-grid and pre-entry denominators are also retained and checked per case/group. These describe quote decisions on retained data, not capture uptime.

| UTC start | Bursty n | Baseline | Floor 0.10 | Feedback | Earlier-selected burst overlay |
| --- | ---: | ---: | ---: | ---: | ---: |
| 2025-01-01 04:15 | 51 | 58.82% | 58.82% | 52.94% | 45.10% |
| 2025-06-01 06:00 | 34 | 41.18% | 41.18% | 41.18% | 38.24% |
| 2025-07-01 09:30 | 10 | 20.00% | 20.00% | 20.00% | 20.00% |
| 2026-01-01 00:00 | 16 | 56.25% | 56.25% | 56.25% | 56.25% |
| 2026-01-01 08:00 | 25 | 64.00% | 64.00% | 64.00% | 60.00% |
| 2026-01-01 16:00 | 29 | 31.03% | 31.03% | 34.48% | 34.48% |
| 2026-05-01 07:15 | 92 | 55.43% | 55.43% | 47.83% | 48.91% |
| 2026-08-01 00:00 | 75 | 62.67% | 58.67% | 56.00% | 53.33% |
| 2026-08-01 08:00 | 49 | 55.10% | 46.94% | 55.10% | 44.90% |
| 2026-08-01 16:00 | 46 | 56.52% | 56.52% | 47.83% | 47.83% |

![Bursty calibration and fixed quote availability](../.local/adaptive-corridor/20261028-bursty-pricing-v1/bursty-comparison.png)

## Mechanisms tested

January bursty survival changes from 64% in one eight-hour slice to 31% in the next. A uniform reduction cannot handle both. The previous feedback rule waits for twelve mature bursty observations; in several periods the first twelve bursty decisions already have large directional error. The refinements test earlier feedback and sharing recent non-frozen references without changing admission.

| Alternative | Base | Method | Leaf minimum | Parent/leaf memory | Maximum age | Shape prior | Directional bypass |
| --- | --- | --- | ---: | ---: | ---: | --- | --- |
| `baseline` | `baseline` | comparator | — | — | — | — | — |
| `engine_floor20` | `engine_floor20` | comparator | — | — | — | — | — |
| `engine_floor10` | `engine_floor10` | comparator | — | — | — | — | — |
| `feedback_state_fast` | `feedback_state_fast` | comparator | — | — | — | — | — |
| `floor10_burst_static` | `engine_floor10` | static | — | — | — | — | — |
| `floor10_burst_feedback4` | `engine_floor10` | feedback | 4 | 60/30 | 1h | False | False |
| `floor10_burst_feedback1` | `engine_floor10` | feedback | 1 | 60/30 | 1h | False | False |
| `floor10_burst_pool120` | `engine_floor10` | hierarchy | 4 | 120/60 | 4h | False | False |
| `floor10_burst_pool60` | `engine_floor10` | hierarchy | 4 | 60/30 | 1h | False | False |
| `floor10_burst_shape60` | `engine_floor10` | hierarchy | 4 | 60/30 | 1h | True | False |
| `floor10_burst_shape60_guard` | `engine_floor10` | hierarchy | 4 | 60/30 | 1h | True | True |
| `baseline_burst_shape60` | `baseline` | hierarchy | 4 | 60/30 | 1h | True | False |

Comparator rows replay the prior baseline, 0.20/0.10 correction floors and selected full non-frozen feedback exactly. The correction-floor comparators lower only the private engine’s original 0.40 lower bound; they preserve its existing volatility, activity and pump conditioning. Frozen outputs are retained from the original fixed overlay.

The bursty overlays use period-balanced training priors. A state prior is the 48th-percentile required-width/base-width ratio, shrunk toward one with prior mass 200. Shape priors condition on past-only fast/slow volatility ratio: below 0.75, 0.75–1.5, or at least 1.5. A shape leaf needs 80 windows over three training periods; otherwise it falls back to the state prior. State priors use the existing parent fallback. Coefficients for each raw panel use only preceding original training dates. The earliest raw control therefore has only two original dates available.

The hierarchical burst overlay normalizes mature required-width ratios by each reference’s base width and training state/shape factor. A recent non-frozen parent quantile becomes active after twelve mature references and is shrunk toward one with prior mass twelve. After four mature bursty references, a bursty quantile is log-blended with that parent using weight n/(n+12). Only the resulting bursty quotes are changed. Frozen references never enter these pools.

The selected 120-reference variant uses a four-hour age cap and a latest-60 bursty leaf. The shorter variants use a latest-60 parent, latest-30 leaf and one-hour age cap. Correction factors are bounded to 0.05–2 and can move by at most 5% per bursty quote; final integer widths are clamped to 1–50,000 ppm. This rate limit applies to the overlay factor, not to total quote width when the base or pre-entry features change.

Feedback alternatives start after one or four mature bursty references. Their accumulator updates by `theta -= 0.10 * (survival_at_own_issued_width - 0.48)` and is bounded to log(0.05)–log(2). They learn their own issued-width outcomes, including references refused by admission, rather than borrowing baseline success labels. Expired evidence cannot seed fresh feedback after a gap.

For every method, references mature at expiry plus 30 seconds. Current/future validity and movement do not select current width; missing pre-entry history remains ineligible. Period boundaries reset private state. Every issued quote stays fixed for its lifetime. The directional bypass leaves pump/dump quotes at the base while continuing to learn causal reference paths.

## Earlier-period selection and its limits

The protocol freezes all twelve alternatives before scoring new results. Training prefixes contain 6/9/12 original monthly dates; the next 3/3/2 dates supply 24 fresh eight-hour cases. The score retains the previous overall/non-frozen/state/directional objective and adds bursty mean plus one-quarter worst absolute case error. A same-path loss penalty applies beyond 10% deterioration in non-frozen, bursty, pump or dump groups. Equal fold weights and declaration-order tie breaking are fixed. Raw outcomes, August 2026, native recordings and later monthly splits are excluded from this selection.

| Alternative | Selection score | Fold scores |
| --- | ---: | --- |
| `floor10_burst_pool120` | 13.402 | 17.006 / 6.439 / 16.761 |
| `floor10_burst_feedback1` | 16.932 | 16.980 / 6.436 / 27.381 |
| `floor10_burst_feedback4` | 17.065 | 17.006 / 6.439 / 27.750 |
| `feedback_state_fast` | 18.077 | 18.644 / 4.840 / 30.748 |
| `floor10_burst_pool60` | 18.168 | 25.619 / 6.439 / 22.446 |
| `floor10_burst_shape60` | 18.268 | 25.919 / 6.439 / 22.446 |
| `floor10_burst_shape60_guard` | 18.268 | 25.919 / 6.439 / 22.446 |
| `baseline_burst_shape60` | 18.268 | 25.919 / 6.439 / 22.446 |
| `baseline` | 21.760 | 26.156 / 6.439 / 32.685 |
| `engine_floor20` | 21.760 | 26.156 / 6.439 / 32.685 |
| `engine_floor10` | 21.760 | 26.156 / 6.439 / 32.685 |
| `floor10_burst_static` | 21.760 | 26.156 / 6.439 / 32.685 |

| Training dates | Scoring cases | Eligible bursty paths | Bursty cases with at least 20 paths |
| ---: | ---: | ---: | ---: |
| 6 | 9 | 85 | 1 |
| 9 | 9 | 46 | 0 |
| 12 | 6 | 68 | 1 |

Only two earlier eight-hour cases meet the bursty reporting threshold; one fold contributes no eligible bursty case-error term at all. Pooled loss still includes all 199 bursty paths in these earlier scoring folds. The earlier winner is therefore weak selection evidence, not a stable or uniquely identified formula. Adjacent paths share market conditions and overlapping feature histories; repeated modes and matched sources reuse outcomes.

## Across later periods

Tables keep fresh-start and continuous modes separate. Validation has fifteen planned slices but only thirteen sufficiently eligible overall/non-frozen cells. Bursty denominators count only groups with at least twenty eligible paths. Both native recordings have fewer than twenty bursty paths, so their bursty calibration is not marked as passing.

| Source / mode | Group | Baseline passes | Floor 0.10 passes | Feedback passes | Burst-overlay passes | Baseline / floor / feedback / overlay loss (ppm) |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| validation / restart | all | 13/13 | 13/13 | 13/13 | 13/13 | 110.49 / 110.49 / 113.10 / 110.57 |
| validation / restart | non_frozen | 13/13 | 13/13 | 13/13 | 13/13 | 112.19 / 112.19 / 114.88 / 112.27 |
| validation / restart | bursty | 3/9 | 3/9 | 6/9 | 6/9 | 104.46 / 104.46 / 106.41 / 106.19 |
| validation / restart | pump | 5/10 | 5/10 | 3/10 | 5/10 | 171.31 / 171.31 / 179.58 / 172.05 |
| validation / restart | dump | 4/10 | 4/10 | 7/10 | 4/10 | 178.34 / 178.34 / 178.19 / 178.64 |
| validation / continuous | all | 13/13 | 13/13 | 13/13 | 13/13 | 110.50 / 110.50 / 113.22 / 110.57 |
| validation / continuous | non_frozen | 13/13 | 13/13 | 13/13 | 13/13 | 112.19 / 112.19 / 114.99 / 112.27 |
| validation / continuous | bursty | 4/9 | 4/9 | 8/9 | 6/9 | 103.36 / 103.36 / 105.43 / 104.99 |
| validation / continuous | pump | 5/10 | 5/10 | 4/10 | 5/10 | 170.87 / 170.87 / 179.09 / 171.30 |
| validation / continuous | dump | 4/10 | 4/10 | 7/10 | 4/10 | 177.95 / 177.95 / 178.19 / 178.20 |
| test / restart | all | 13/15 | 14/15 | 13/15 | 14/15 | 79.11 / 79.08 / 81.10 / 79.12 |
| test / restart | non_frozen | 13/15 | 14/15 | 15/15 | 15/15 | 83.64 / 83.61 / 85.79 / 83.65 |
| test / restart | bursty | 4/11 | 5/11 | 6/11 | 7/11 | 79.68 / 79.48 / 80.05 / 80.30 |
| test / restart | pump | 2/9 | 2/9 | 3/9 | 2/9 | 133.83 / 133.83 / 137.91 / 133.86 |
| test / restart | dump | 4/10 | 4/10 | 3/10 | 4/10 | 125.64 / 125.64 / 133.29 / 124.99 |
| test / continuous | all | 13/15 | 14/15 | 14/15 | 14/15 | 79.07 / 79.05 / 81.00 / 79.05 |
| test / continuous | non_frozen | 13/15 | 14/15 | 15/15 | 15/15 | 83.60 / 83.58 / 85.69 / 83.58 |
| test / continuous | bursty | 4/11 | 4/11 | 7/11 | 6/11 | 79.70 / 79.50 / 80.39 / 79.56 |
| test / continuous | pump | 2/9 | 2/9 | 2/9 | 2/9 | 133.88 / 133.88 / 137.75 / 133.99 |
| test / continuous | dump | 4/10 | 4/10 | 3/10 | 4/10 | 125.36 / 125.36 / 134.14 / 125.31 |
| native / restart | all | 2/2 | 2/2 | 2/2 | 2/2 | 87.65 / 87.65 / 90.21 / 87.66 |
| native / restart | non_frozen | 2/2 | 2/2 | 2/2 | 2/2 | 87.81 / 87.81 / 90.39 / 87.81 |
| native / restart | bursty | 0/0 | 0/0 | 0/0 | 0/0 | 90.62 / 90.62 / 91.22 / 90.72 |
| native / restart | pump | 1/2 | 1/2 | 1/2 | 1/2 | 108.06 / 108.06 / 112.25 / 108.06 |
| native / restart | dump | 0/2 | 0/2 | 1/2 | 0/2 | 145.28 / 145.28 / 146.86 / 145.28 |

Period-level fresh-start bursty results show whether a pooled improvement survives each date.

| Date / source | Eligible bursty paths | Cases ≥20 | Baseline passes | Floor 0.10 passes | Feedback passes | Burst-overlay passes |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 2025-01-01 / raw_control | 51 | 1 | 0 | 0 | 1 | 1 |
| 2025-06-01 / raw_control | 34 | 1 | 0 | 0 | 0 | 0 |
| 2025-07-01 / raw_control | 10 | 0 | 0 | 0 | 0 | 0 |
| 2026-01-01 / normalized | 9 | 0 | 0 | 0 | 0 | 0 |
| 2026-01-01 / raw | 70 | 2 | 0 | 0 | 0 | 0 |
| 2026-02-01 / normalized | 21 | 0 | 0 | 0 | 0 | 0 |
| 2026-03-01 / normalized | 140 | 3 | 2 | 2 | 2 | 3 |
| 2026-04-01 / normalized | 124 | 3 | 0 | 0 | 1 | 0 |
| 2026-05-01 / normalized | 216 | 3 | 1 | 1 | 3 | 3 |
| 2026-05-01 / raw_control | 92 | 1 | 0 | 0 | 1 | 1 |
| 2026-06-01 / normalized | 75 | 2 | 0 | 0 | 0 | 0 |
| 2026-07-01 / normalized | 102 | 3 | 1 | 1 | 2 | 2 |
| 2026-08-01 / normalized | 142 | 3 | 0 | 1 | 1 | 2 |
| 2026-08-01 / raw_control | 170 | 3 | 0 | 1 | 1 | 2 |
| 2026-09-01 / normalized | 52 | 2 | 2 | 2 | 2 | 2 |
| 2026-10-01 / normalized | 62 | 1 | 1 | 1 | 1 | 1 |
| 20261026-117ppm-8h / native | 12 | 0 | 0 | 0 | 0 | 0 |
| 20261026-round2-314ppm-8h / native | 15 | 0 | 0 | 0 | 0 | 0 |

The selected overlay improves normalized fresh-start bursty passes from **3/9 to 6/9** on validation and **5/11 to 7/11** on the later test split relative to the simple floor. Full feedback reaches 6/9 and 6/11. The selected overlay’s non-frozen loss is 112.272 ppm on validation and 83.646 ppm on later tests, versus 112.191 / 83.609 for the floor and 114.880 / 85.792 for full feedback. Overall loss stays much closer to the simpler floor, but conditional bursty loss is still higher than the floor in both later splits.

Continuous-mode bursty counts favor full feedback: 8/9 versus 6/9 for the new overlay on validation, and 7/11 versus 6/11 on later tests. The new overlay therefore does not dominate across restart/continuous modes. Their shared observations do not supply independent confirmation.

Under warmup/floor30 admission, the selected overlay still passes 10/10 overall, 10/10 non-frozen and 4/8 bursty raw cases. Frozen passes remain 7/10, so joint overall/non-frozen/frozen passes remain 7/10; the previous-floor mask retains 4/10 joint passes. Changing non-frozen pricing does not solve these frozen failures.

## Startup and remaining limitations

The selected overlay leaves January raw bursty survival at **60.00% / 34.48%** in its 08:00 and 16:00 starts, and June at **38.24%**. August improves to **53.33% / 44.90% / 47.83%**: its first slice still misses the upper band by 0.33 percentage points. No alternative passes every sufficiently populated raw bursty case.

Startup here means the first twelve bursty decisions, which may span hours in a sparse state. Diagnostics rank pre-entry predictions before looking at later outcome health. Each first-twelve group therefore includes decisions later censored; fewer than twenty observations are descriptive only. In continuous mode this rank restarts at each scored interval, so only fresh-start rows describe run startup.

| Raw fresh-start pricing | First 12 bursty decisions: eligible / survival | Later bursty decisions: eligible / survival |
| --- | ---: | ---: |
| `baseline` | 118 / 61.02% | 309 / 51.46% |
| `engine_floor20` | 118 / 61.02% | 309 / 49.84% |
| `engine_floor10` | 118 / 61.02% | 309 / 49.19% |
| `feedback_state_fast` | 118 / 61.86% | 309 / 45.31% |
| `floor10_burst_pool120` | 118 / 59.32% | 309 / 42.39% |

The selected overlay still has **59.32%** pooled survival among its first twelve bursty decisions per raw test and **42.39%** afterward, versus 61.02% / 49.19% for the simple floor and 61.86% / 45.31% for full feedback. The phase groups have different period weights, so this pooled difference alone does not prove within-run lag. A concrete unresolved example is the January 2025 control: 83.33% survival on its first twelve decisions and 33.33% on the later 39, despite a passing 45.10% aggregate. Startup error and later overshoot can cancel.

Aggregate calibration, conditional calibration and quantile loss must be assessed together. Reducing an aggregate error does not establish stable bursty, pump or dump pricing. Frozen quotes and their unresolved conditional misses remain unchanged under both admission masks. No pricing study repairs the retained capture continuity/deadline problems. All these dates were inspected previously, and this iteration does not supply independent validation.

## Reproducibility

Implementation: `scripts/bursty_pricing.py`, `scripts/research_bursty_pricing.py`. Archive: `.local/adaptive-corridor/20261028-bursty-pricing-v1/`. It includes the declared protocol, earlier-fold models/ranking, final state/shape priors, source snapshots, compressed predictions, 33,024 case/group/policy/model rows, startup diagnostics, selection exposure and this plot. It reconstructs all four prior comparators, including widths’ mean, survival counts and same-path loss. Original archives/raw responses/native receipts and parent metadata/source/input hashes are reverified. Every overlay checks non-bursty invariance; all candidates check frozen forecasts, admission masks, eligibility and quote-availability denominators.

```sh
python3 -B scripts/research_bursty_pricing.py \
  --previous .local/adaptive-corridor/20261028-nonfrozen-pricing-v1 \
  --output .local/adaptive-corridor/NEW-NONEXISTENT-DIRECTORY
python3 -B -m unittest discover -s scripts -p 'test_*.py'
```

Validation: **184 tests run successfully, with three existing optional skips**. Eleven new tests cover burst-only/frozen/mask/eligibility invariance, expiry-plus-delay causality, mature non-frozen transfer, earlier warmup and refused-reference learning, own-width feedback, directional protection, age/period/memory/rate bounds, stale pending evidence, shape/fallback rules, startup denominators, and exclusion of later outcomes from selection.

The [startup and drift follow-up](BURSTY_STARTUP_DRIFT_RESEARCH.md) tests faster
correction clocks, decaying feedback and time-weighted CDF mixtures against both
restart and continuous runs. It also compares identical eligible paths between
modes. Some aggregate and later-phase metrics improve, but January startup and
June drift remain unresolved; earlier-period selection retains this iteration's
pooled correction. Capture stays on hold.
