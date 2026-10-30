# Non-frozen pricing research — 28 October 2026

Thirteen pricing alternatives were replayed with frozen widths and admission held fixed. Earlier monthly folds select `feedback_state_fast`. On the ten raw eight-hour restart tests, this brings non-frozen aggregate calibration from **7/10 to 10/10 passes** and reduces mean absolute case error from **3.02 to 1.24 percentage points**. A simpler relaxation of the original engine correction floor from 0.40 to 0.10 also passes all ten non-frozen tests and all ten overall tests. It was not the earlier-fold winner.

**No candidate is promoted and no capture starts.** The selected feedback rule increases same-path pricing loss and leaves conditional bursty/pump/dump misses. The lower-bound alternative also retains conditional failures. Frozen pricing is unchanged, so its unresolved failures remain. All results use the legacy 48% survival reference and 43–53% band, not a validated payout-product target.

## What changed

The research implementation is `scripts/nonfrozen_pricing.py`; `scripts/research_nonfrozen_pricing.py` performs selection and comparison. The existing capture, pricing, admission and frontend code was not changed. The alternatives are:

* Lower the private engine correction bound to 0.20 or 0.10; apply its forecasts to all three non-frozen states, or only sparse/bursty. This preserves the engine’s existing activity and pump contexts and learns all external reference outcomes. Its recalculated frozen quotes are discarded in favor of the fixed frozen forecasts.
* Apply a training-period-balanced static state correction, or a rolling state-specific quantile correction using 60/120 mature references.
* Fit a minimum-width/positive-movement mixture per state, with 60/120 mature references, training shrinkage and a slow or faster correction rate.
* Combine a training state factor with causal calibration feedback, using slow or faster updates.

The earlier-selected formula uses a separate accumulator for active, sparse and bursty states. For each eligible reference that matures, including paths refused by admission:

```text
q = 0.48
y = 1 if that reference survives the width issued by this candidate, else 0
theta[state] = clamp(theta[state] - 0.10 * (y - q), log(0.05), log(2))
requested = exp(theta[state]) after 12 mature references; otherwise 1
factor[state] moves toward requested by at most 5% per entry in that state
width = clamp(ceil(baseline_width * training_state_factor * factor[state]), 1, 50000)
```

The accumulator starts at zero for each new run/day and after its mature evidence has expired. Activation counts use the latest 120 references within four hours; the feedback accumulator itself integrates causal updates rather than recomputing only those 120 outcomes. Pending outcomes become available at expiry plus 30 seconds. No current-window validity or movement is used to choose its width. Each accepted quote remains fixed for its 30-second life.

Training state factors use equal-period weights, a 48th-percentile required-width/baseline-width ratio and log shrinkage toward one with prior mass 200. A state needs at least 80 windows across three periods; otherwise it uses the parent non-frozen prior. All priors are refitted on original training dates preceding each raw control. No raw outcome fits a prior.

The non-frozen minimum-width floors in August are well below the target, unlike some frozen subsets. In its first slice, active/sparse/bursty floors are 21.43% / 29.12% / 25.33%, while baseline survival is 61.61% / 53.35% / 62.67%. Narrowing is feasible on these observed paths. Removing part of the 0.40 correction constraint addresses a specific overpricing mechanism; it does not prove a unique best lower bound.

## Selection and retained comparison

The protocol declares all 13 alternatives before evaluating their new results. Expanding prefixes of 6/9/12 original monthly days fit coefficients; the next 3/3/2 days supply 24 fresh eight-hour selection cases. The score combines overall and non-frozen mean/quarter-worst absolute errors, half-weighted activity and directional errors, and a same-path quantile-loss penalty beyond 10% deterioration. Equal fold weights and declaration-order ties are explicit. The August 2026 failure, all raw tests, native recordings and later monthly splits do not enter selection. The protocol’s `raw_or_august_used_for_selection` field refers to this August 2026 failure; August 2025 is part of the earlier monthly selection dates.

| Alternative | Earlier-fold score | Fold scores |
| --- | ---: | --- |
| `feedback_state_fast` | 10.254 | 13.876 / 4.840 / 12.044 |
| `feedback_state` | 10.838 | 15.641 / 4.916 / 11.956 |
| `hurdle_quiet120` | 10.943 | 12.322 / 6.526 / 13.982 |
| `hurdle_state120_fast` | 11.012 | 13.398 / 6.262 / 13.375 |
| `baseline` | 11.029 | 12.668 / 6.439 / 13.982 |
| `engine_floor20` | 11.029 | 12.668 / 6.439 / 13.982 |
| `engine_floor10` | 11.029 | 12.668 / 6.439 / 13.982 |
| `engine_floor10_quiet` | 11.029 | 12.668 / 6.439 / 13.982 |
| `hurdle_state120` | 11.177 | 13.655 / 6.461 / 13.416 |
| `residual_state60` | 11.397 | 14.773 / 6.257 / 13.161 |
| `residual_state120` | 11.468 | 13.918 / 6.820 / 13.666 |
| `hurdle_state60` | 11.570 | 14.620 / 6.504 / 13.585 |
| `static_state` | 11.902 | 14.667 / 7.044 / 13.995 |

Feedback improves the score from 11.029 to 10.254, but loses to simpler candidates in some folds. The lower-bound changes tie baseline on these folds; this selection sample cannot identify 0.10 versus 0.20. Better raw results are reported as diagnostics without replacing the selected candidate after looking at August.

The full comparison has **172 eight-hour case intervals in 118 sessions**: 72 continuous normalized slices, 72 normalized fresh starts, two native recordings, six January raw slices/starts, and twenty raw-control/matched-normalized intervals. Continuous and fresh-start modes remain separate. All thirteen alternatives and both fixed admission masks are retained, across overall, non-frozen, frozen, active, sparse, bursty, pump and dump groups. Matching normalized data is not pooled with raw data.

## Ten raw eight-hour restart tests

| UTC start | Non-frozen n | Baseline non-frozen | Feedback non-frozen | Lower-bound non-frozen | Baseline overall | Feedback overall | Lower-bound overall | Eligible availability |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 2025-01-01 04:15 | 811 | 48.34% | 48.21% | 48.34% | 48.31% | 48.20% | 48.31% | 100.00% |
| 2025-06-01 06:00 | 778 | 49.74% | 48.07% | 49.74% | 49.14% | 47.75% | 49.14% | 100.00% |
| 2025-07-01 09:30 | 842 | 47.86% | 47.86% | 47.86% | 47.67% | 47.67% | 47.67% | 100.00% |
| 2026-01-01 00:00 | 574 | 53.48% | 50.70% | 51.92% | 54.02% | 52.01% | 52.89% | 85.96% |
| 2026-01-01 08:00 | 529 | 50.47% | 48.20% | 45.94% | 50.62% | 48.76% | 46.90% | 70.60% |
| 2026-01-01 16:00 | 660 | 44.39% | 47.42% | 43.94% | 46.61% | 48.87% | 46.27% | 95.57% |
| 2026-05-01 07:15 | 867 | 48.21% | 47.87% | 48.21% | 47.81% | 47.49% | 47.81% | 100.00% |
| 2026-08-01 00:00 | 575 | 56.17% | 51.48% | 50.78% | 56.76% | 53.15% | 52.61% | 80.58% |
| 2026-08-01 08:00 | 512 | 54.30% | 51.17% | 46.88% | 56.07% | 53.12% | 49.08% | 60.38% |
| 2026-08-01 16:00 | 784 | 49.74% | 49.74% | 49.74% | 50.53% | 50.53% | 50.53% | 100.00% |

The table uses the previous floor admission rule. “Lower-bound” is `engine_floor10`; “feedback” is the earlier-selected `feedback_state_fast`. The four extended controls begin at the exact times shown, rather than midnight-aligned eight-hour boundaries.

| Pricing / fixed admission | Overall passes | Non-frozen passes | Frozen passes | All three pass | Pooled eligible availability | Lowest case availability |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `baseline` / `previous_floor_53` | 7/10 | 7/10 | 4/10 | 4/10 | 89.48% | 60.38% |
| `engine_floor10` / `previous_floor_53` | 10/10 | 10/10 | 4/10 | 4/10 | 89.48% | 60.38% |
| `feedback_state_fast` / `previous_floor_53` | 8/10 | 10/10 | 4/10 | 4/10 | 89.48% | 60.38% |
| `baseline` / `warm12_floor30` | 7/10 | 7/10 | 7/10 | 6/10 | 88.17% | 65.82% |
| `engine_floor10` / `warm12_floor30` | 10/10 | 10/10 | 7/10 | 7/10 | 88.17% | 65.82% |
| `feedback_state_fast` / `warm12_floor30` | 9/10 | 10/10 | 7/10 | 7/10 | 88.17% | 65.82% |

The ten tests contain 9,291 eligible reference paths, including 6,932 non-frozen and 2,359 frozen paths. Previous-floor admission retains 8,314 eligible paths, including every non-frozen path. Warmup/floor30 retains 8,192. Every pricing alternative retains exactly these same masks, per case and group. There are 9,317 pre-entry predictions on 9,600 grid entries: previous-floor admission offers 8,336 pre-entry quotes (89.47% of predictions; 86.83% of the grid), while warmup/floor30 offers 8,213 (88.15%; 85.55%). These grid and eligible metrics describe the retained paths, not capture uptime.

![Eight-hour calibration and availability](../.local/adaptive-corridor/20261028-nonfrozen-pricing-v1/eight-hour-comparison.png)

## What still fails

Non-frozen aggregate passes do not establish conditional calibration. In the first August slice the selected rule leaves active at **55.36%** and bursty at **56.00%**; in the second, bursty remains **55.10%**. Overall August survival remains just above band in the first two slices (**53.15% / 53.12%**) with previous-floor admission. The frozen subsets remain 58.72% / 84.38% / 54.61% across its three slices.

| Raw non-frozen state | Baseline passes | Feedback passes | Lower-bound passes | Feedback pooled survival |
| --- | ---: | ---: | ---: | ---: |
| active | 8/10 | 9/10 | 8/10 | 48.50% |
| sparse | 6/10 | 10/10 | 8/10 | 49.26% |
| bursty | 0/8 | 3/8 | 1/8 | 49.88% |

Bursty pooling at 49.88% hides five of eight conditional case failures. Raw pump/dump evidence is also thin: only 87 pump and 88 dump paths, with one and two cases respectively meeting the 20-path reporting threshold. Adjacent paths share market conditions and overlapping feature histories; continuous/restart comparisons also reuse outcomes. The threshold and the reference band are descriptive checks, not confidence guarantees.

Improved calibration is not uniformly lower pricing loss. On identical raw non-frozen paths, quantile loss is **50.822 ppm baseline**, **51.564 feedback (+1.46%)**, and **50.811 lower-bound**. The selected feedback rule also increases raw pump loss from 107.325 to 112.217 ppm. No loss is hidden by refusal.

## Later normalized periods and native recordings

Passes below require at least twenty originally eligible and twenty quoted paths. Validation has 15 planned slices but only 13 meet that condition; the two missing cells do not count as passes. Fresh-start and continuous rows reuse observations and must not be added as independent tests. All three variants have the same availability in each row.

| Source / mode | Group | Baseline passes | Feedback passes | Lower-bound passes | Baseline → feedback mean absolute error (pp) | Eligible availability |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| validation / restart | all | 13/13 | 13/13 | 13/13 | 0.83 → 0.33 | 100.00% |
| validation / restart | non_frozen | 13/13 | 13/13 | 13/13 | 0.95 → 0.32 | 100.00% |
| validation / restart | pump | 5/10 | 3/10 | 5/10 | 5.10 → 6.63 | 100.00% |
| validation / restart | dump | 4/10 | 7/10 | 4/10 | 5.74 → 5.69 | 100.00% |
| validation / continuous | all | 13/13 | 13/13 | 13/13 | 0.60 → 0.31 | 100.00% |
| validation / continuous | non_frozen | 13/13 | 13/13 | 13/13 | 0.71 → 0.25 | 100.00% |
| validation / continuous | pump | 5/10 | 4/10 | 5/10 | 4.82 → 6.54 | 100.00% |
| validation / continuous | dump | 4/10 | 7/10 | 4/10 | 5.54 → 5.56 | 100.00% |
| test / restart | all | 13/15 | 13/15 | 14/15 | 2.08 → 1.19 | 95.72% |
| test / restart | non_frozen | 13/15 | 15/15 | 14/15 | 1.93 → 0.79 | 100.00% |
| test / restart | pump | 2/9 | 3/9 | 2/9 | 8.55 → 7.49 | 100.00% |
| test / restart | dump | 4/10 | 3/10 | 4/10 | 5.42 → 8.13 | 100.00% |
| test / continuous | all | 13/15 | 14/15 | 14/15 | 1.75 → 0.80 | 95.23% |
| test / continuous | non_frozen | 13/15 | 15/15 | 14/15 | 1.72 → 0.53 | 100.00% |
| test / continuous | pump | 2/9 | 2/9 | 2/9 | 7.95 → 8.71 | 100.00% |
| test / continuous | dump | 4/10 | 3/10 | 4/10 | 5.46 → 7.13 | 100.00% |
| native / restart | all | 2/2 | 2/2 | 2/2 | 0.28 → 0.16 | 100.00% |
| native / restart | non_frozen | 2/2 | 2/2 | 2/2 | 0.40 → 0.31 | 100.00% |
| native / restart | pump | 1/2 | 1/2 | 1/2 | 5.33 → 5.39 | 100.00% |
| native / restart | dump | 0/2 | 1/2 | 0/2 | 7.48 → 8.43 | 100.00% |

Feedback brings all fifteen normalized later-test non-frozen slices into band for both modes. However validation fresh-start pump passes fall from 5/10 to 3/10, and later-test fresh-start dump passes fall from 4/10 to 3/10 with mean absolute error increasing from 5.42 to 8.13 points. Later-test fresh-start non-frozen loss increases from 83.640 to 85.792 ppm (+2.57%). The lower-bound alternative leaves those pump/dump counts unchanged. Neither alternative establishes stable conditional pricing.

On the two native recordings, feedback overall survival is 48.20% / 47.87%, versus 47.96% / 47.47% baseline. Both variants pass both overall and non-frozen aggregate checks; feedback raises non-frozen loss from 87.806 to 90.388 ppm (+2.94%) pooled. These are retrospective adaptive replays of recordings originally captured with fixed widths, not the actual outcomes of newly issued adaptive quotes. Eligible availability is 100% after clean-history selection, while complete-grid pre-entry quote fractions remain 90.21% / 79.06%. Prior capture gaps and deadline behavior are not repaired by this pricing study.

## Evidence and reproducibility

The immutable archive is `.local/adaptive-corridor/20261028-nonfrozen-pricing-v1/`. It retains the predeclared protocol, earlier-fold models/ranking, final priors, source snapshots, all 35,776 case/group/policy/model rows, summaries, and compressed predictions including both admission masks. Input hashes bind the two parent session caches. Original monthly archives, raw response files, native receipts, parent metadata and parent source snapshots are reverified. Archived baseline case counts are reconstructed before any comparison. Invariants check every frozen forecast, eligibility, admission and per-case/group availability.

```sh
python3 -B scripts/research_nonfrozen_pricing.py \
  --admission .local/adaptive-corridor/20261028-startup-admission-v2 \
  --controls .local/adaptive-corridor/20261028-admission-8h-controls-v1 \
  --output .local/adaptive-corridor/NEW-NONEXISTENT-DIRECTORY
python3 -B -m unittest discover -s scripts -p 'test_*.py'
```

The suite runs **173 tests: OK, three existing optional skips**. The twelve new tests cover expiry-plus-delay causality, refused-reference learning, state isolation, period/age resets, memory/step/bounds, hurdle arithmetic, feedback at its own issued width, frozen/mask/eligibility invariance, quiet scope, parent fallback, weighted CDF compression, fixed-mask denominators, and exclusion of outer outcomes from selection.

These are repeated research diagnostics on inspected periods, not independent holdouts. The next unresolved pricing work is the bursty conditional failures and preserving pump/dump calibration while adapting to flat transitions. The correction-floor relaxation is a useful simpler comparator, not a retrospectively validated live selection. Frozen admission/pricing and capture continuity/deadline repairs remain separate blockers before freezing a new candidate and starting a new capture.

The [bursty-only follow-up](BURSTY_PRICING_RESEARCH.md) compares earlier feedback,
shared non-frozen reference pools and volatility-conditioned priors against the
unchanged floor and feedback comparators. A pooled bursty correction improves
raw bursty passes to 4/8 while retaining 10/10 overall/non-frozen passes and
unchanged availability. Opposite-direction misses, startup/late cancellation and
different continuous-mode results still prevent promotion or capture.
