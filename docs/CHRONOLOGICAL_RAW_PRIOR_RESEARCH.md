# Chronological raw-prior recalibration — 28 October 2026

Follow-up: [earlier raw training and startup admission](EARLIER_RAW_STARTUP_RESEARCH.md)
adds November/December 2024 raw rows and tests ten causal admission rules. The
earlier raw prior improves one selection fold, but warmup costs substantial
quote availability and leaves the focused failures unresolved. Capture stays on hold.

This experiment recalibrates the bursty priors with the expanded full-day raw January and June 2025 data. It replaces the matching normalized training dates without adding duplicate observations or changing the engine, frozen pricing, admission rules or correction settings. The earlier chronological folds retain the normalized-prior pooled correction. No new capture starts and no live candidate is promoted.

## Chronology and experiment boundaries

The original training-date universe remains fixed. Each fitted prior uses only dates strictly before the evaluated date; every training outcome must mature before that cutoff. Dates are sorted, entries must be unique, and the original equal-date weighting remains in place. A raw date replaces its normalized counterpart once. Restart, continuous and shifted copies never become additional training periods.

| Evaluation | Expanded raw data permitted in its prior |
| --- | --- |
| January 2025 | None; only November and December 2024 precede it |
| June 2025 | January 2025 only |
| July 2025 and subsequent evaluated dates | January and June 2025 |
| January 2026 | January and June 2025, within the original fourteen training dates |

Training forecasts are recomputed from raw rows using the evaluated model's fixed engine and fixed frozen overlay. Cached widths from another engine are not reused as fitting denominators. The original fourteen-date engine is retained for the 2026 monthly and native comparisons; earlier raw controls retain their original preceding-date engines. This isolates prior replacement from an engine retrain.

The prior changes state scale factors, minimum-width probability and stored positive CDFs. Four unchanged bursty methods are compared under normalized and raw-replacement priors: the retained 120-reference pool, its faster correction clock, the 60-reference CDF and episode/kernel CDF. The simple engine-floor relaxation is an additional fixed comparator: **nine variants**. Every variant changes only bursty pricing; frozen, active and sparse quotes remain identical within each session.

The evaluation excludes the original normalized training-date sessions because their cached engines used later training dates. It retains **104 eight-hour case intervals in 74 sessions**, covering later normalized dates, native replays, original raw controls and full-day/shifted raw extensions. Overlapping panels and restarted/continuous paths are comparisons, not independent observations.

Selection still uses the original 6/9/12-date training prefixes and the following 3/3/2 normalized dates, both modes, the same phase objective and the same pricing-loss guard. Raw replacement is allowed only inside each training prefix; raw evaluation paths do not enter the selection score. These repeatedly inspected calendar dates are not independent holdouts. Earlier selection still contains only two distinct bursty cases with twenty or more paths.

## Earlier-period selection

Lower scores are better. The normalized-prior scores reconstruct the previous experiment exactly.

| Method | Normalized prior | Raw-replacement prior |
| --- | ---: | ---: |
| Retained pool | 21.557 | 22.711 |
| Faster clock | 23.406 | 24.560 |
| CDF | 31.820 | 31.820 |
| Episode/kernel | 33.136 | 33.849 |

The simple floor scores 31.432. Added raw coverage does not select a successor under this unchanged objective.

## What the recalibration changes

| Prior evaluated on | Bursty training paths, normalized → raw | Bursty scale, normalized → raw | Minimum-width mass, normalized → raw |
| --- | ---: | ---: | ---: |
| January 2025 | 51 → 51 | 1.01195 → 1.01195 | 3.647% → 3.647% |
| June 2025 | 265 → 308 | 1.00973 → 1.00000 | 5.320% → 5.616% |
| January 2026 and final fourteen-date model | 453 → 591 | 1.04166 → 1.06124 | 4.783% → 4.217% |

January 2025 still falls back to the non-frozen parent because only two prior dates are available. Its displayed scale and minimum-width mass are the parent estimates, while 51 is the actual bursty child count. The fourteen-date fit gains 138 bursty references but no new calendar dates. Wider raw coverage changes the fitted priors and integer quote widths; it does not establish stability across additional independent periods. The retained pool changes 2,128 replay widths and five clean outcomes across the saved sessions, including overlapping continuous/shifted histories. These are not independent path counts.

## January startup and June drift

For the retained pool, **every survival rate below is unchanged by raw-prior replacement**. Mode pairs use identical eligible entry prices and realized moves. June and January 2026 still fail in both restart and continuous mode.

| Raw scoring interval | Mode | First12 survival | Later survival | Aggregate |
| --- | --- | ---: | ---: | ---: |
| January 2025, 04:15–12:15 | Restart | 83.33% (12 paths) | 33.33% (39) | 45.10% (51) |
| January 2025, 04:15–12:15 | Continuous | 75.00% (12) | 38.46% (39) | 47.06% (51) |
| June 2025, 06:00–14:00 | Restart | 41.67% (12) | 36.36% (22) | 38.24% (34) |
| June 2025, 06:00–14:00 | Continuous | 41.67% (12) | 36.36% (22) | 38.24% (34) |
| January 2026, 08:00–16:00 | Restart | 75.00% (12) | 46.15% (13) | 60.00% (25) |
| January 2026, 08:00–16:00 | Continuous | 75.00% (12) | 46.15% (13) | 60.00% (25) |

![Chronological prior replacement and phase calibration](../.local/adaptive-corridor/20261028-chronological-raw-priors-v2/phase-comparison.png)

January 2025 cannot improve through these new training days without using future information. June's January-only raw prior changes prices slightly but leaves every focused phase's survival unchanged. With CDF or episode/kernel pricing, June startup remains 50.00% and later survival remains 36.36% in both modes; the later drift is not repaired by either the prior or continuous history.

January 2026 startup stays at 75% under all four methods in both modes. The retained pool's later phase stays at 46.15%; the faster clock stays at 30.77%, while CDF and episode/kernel stay at 53.85%. Updating the priors leaves the previous pattern intact. Eight of its twelve startup paths survive even at minimum width (66.67%): a positive-width price adjustment alone cannot bring that observed subset to 48% under the current admission constraint. This is a descriptive small-sample constraint, not an estimated population probability.

## Cross-period calibration, loss and availability

The following bursty pass counts are **identical before and after raw-prior replacement**. A pass requires twenty paths and survival within 43–53%. Original raw restart tests, canonical full-day raw panels and later normalized dates remain separate.

| Method | Original raw restart | Original raw continuous | Canonical raw restart / continuous | Later normalized restart / continuous |
| --- | ---: | ---: | ---: | ---: |
| Retained pool | 4/8 | 2/5 | 5/5 / 4/5 | 7/11 / 6/11 |
| Faster clock | 5/8 | 3/5 | 4/5 / 3/5 | 8/11 / 7/11 |
| CDF | 3/8 | 2/5 | 2/5 / 2/5 | 6/11 / 7/11 |
| Episode/kernel | 1/8 | 2/5 | 2/5 / 2/5 | 5/11 / 5/11 |

There are ten planned original raw restart tests but only eight populated bursty cells. The original raw continuous set has six intervals and five populated bursty cells. There are six canonical raw intervals; January 2025 08:00 has only eighteen bursty paths and is **not counted as a pass**. Its retained-pool survival remains 38.89% restart / 16.67% continuous. Canonical and shifted panels overlap, so their counts must not be added to the original tests as independent evidence.

The retained pool keeps 10/10 original raw overall and non-frozen aggregate passes, with only 4/10 frozen passes. Its original raw bursty survival changes slightly, 47.07% → 47.31%, but no whole-case bursty pass changes. Full-reference bursty quantile loss rises **48.310 → 48.333 ppm** on original raw restarts and **80.303 → 80.529 ppm** on later normalized restarts. Canonical raw restart loss improves slightly, 65.342 → 65.316 ppm. These mixed, small changes provide no consistent loss advantage.

All nine variants preserve both admission masks, eligible-path counts, pre-entry/grid denominators and every non-bursty quote. Original raw restart availability stays **8,314/9,291 = 89.48%** under previous-floor admission and **8,192/9,291 = 88.17%** under warmup/floor30; all 6,932 eligible non-frozen paths remain offered. These fractions describe eligible replay paths, not capture uptime or guaranteed executable quotes.

Recalibration alone has not solved startup or later drift. Retain the existing research benchmark; do not freeze these raw-replacement priors as a new candidate. A subsequent prior experiment needs additional preceding raw dates, particularly November/December 2024 for a causal January 2025 test. January 2026 also requires an explicit decision about the minimum-width/admission conflict rather than another prior fit on its own outcomes.

## Reproduction

```sh
python3 -B scripts/research_chronological_raw_priors.py \
  --previous .local/adaptive-corridor/20261028-bursty-episodes-v1 \
  --output .local/adaptive-corridor/20261028-chronological-raw-priors-v2
python3 -B -m unittest discover -s scripts -p 'test_*.py'
```

Use a new output directory for another replay. The first attempt (`v1`) stopped before evaluation on a runner cutoff-check data-shape error; it is retained as an incomplete attempt and is not used for results. The corrected runner validates maturity for both normalized and raw training rows. The completed archive binds source snapshots, raw/cache hashes, selection models, fitted priors, per-entry widths, case/phase metrics and identical-path mode comparisons. The derived comparison tables keep original raw, canonical full-day and shifted panels separate.

The full Python suite completes **213 tests**, with three existing optional skips. New tests cover replacement without duplication, own/future-date exclusion, maturity crossing the cutoff, target-engine recomputation, unchanged non-bursty pricing and future-outcome causality.

Native capture continuity and deadline defects remain separate unresolved work. Historical calibration does not repair them or validate payout-product economics. The 48% target, 43–53% band and twenty-path minimum remain legacy research references; startup groups with twelve paths are descriptive.
