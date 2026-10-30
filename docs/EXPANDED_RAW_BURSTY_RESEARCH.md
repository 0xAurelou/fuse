# Expanded raw training coverage — 28 October 2026

Follow-up: the [oracle–mark gap and adaptive quantile experiment](GAP_QUANTILE_RESEARCH.md) compares five fixed variants on matched feature support. January 2025 startup moves closer to target, but June later survival remains 8/22, floor-risk prediction does not improve, and earlier selection retains the existing benchmark. No capture starts.

Four additional complete raw training days modestly improve the pre-entry risk forecasts, but do not fix January startup or June later pricing. The expanded-data raw-mass adapter narrowly wins the existing earlier-fold objective, **20.758 versus 20.812**, while losing calibration passes across other periods. No successor is frozen or promoted and no capture starts. The existing retained pool remains the current research benchmark.

## Controlled data expansion

The acquisition protocol declared **all four consecutive missing monthly raw dates, February–May 2025**, before downloading their outcomes. Each complete UTC day uses 1,440 anonymous minute requests. All **5,760 requests** completed without fetch errors; compressed-response hashes and gzip CRCs were verified. The parser retained **327,922 messages**, recorded 61 disconnect markers and found **zero price mismatches across 199,072 shared raw/normalized timestamps**. Disconnects continue to censor outcomes under the existing rules.

| Training date | Messages | Disconnect markers | Shared timestamps | Normalized bursty paths | Raw bursty paths | Raw minimum-width survivors |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 2025-02-01 | 81,837 | 1 | 41,603 | 24 | 128 | 10 |
| 2025-03-01 | 81,360 | 1 | 51,362 | 94 | 105 | 3 |
| 2025-04-01 | 82,357 | 51 | 57,878 | 25 | 44 | 3 |
| 2025-05-01 | 82,368 | 8 | 48,229 | 11 | 94 | 7 |
| Total | 327,922 | 61 | 199,072 | 154 | 371 | 23 |

These are additional raw observations on **existing monthly dates**, not four new dates or independent holdouts. The 371 clean bursty paths include nine pump, fifteen dump, 102 range and 245 mixed observations. Those are path counts, not counts of independent market episodes. Only 23/371 = **6.20%** survive the minimum width; these days add cadence coverage but little evidence resembling January 2026's high-floor startup subset.

Raw rows replace normalized rows only on matching dates strictly before each fit cutoff. Each date still appears once, date balancing stays fixed and every training outcome must mature before the scoring date. The final fourteen-date model gains **671 → 888** bursty references; the June 2025 prior gains **388 → 605**. January 2025 stays at **131** because the new dates occur later and cannot train that model.

The experiment crosses the previous **sixteen formula/admission variants with two data sources**. Pricing algorithms, feature allowlist, chronological probability calibration, evidence thresholds, maturity delay, engine forecasts, frozen prices and frozen masks are unchanged. Non-bursty pricing and admission remain fixed. The existing retained pool is the explicit control.

## Earlier selection and transfer

Selection still uses the original six/nine/twelve-date prefixes and subsequent three/three/two normalized scoring dates. It retains the same objective, full-reference loss guard, refusal costs and **95% pooled / 90% per populated case** bursty retention requirements in both modes. Raw evaluation panels and later failures never select a model.

| Training / pricing | Earlier-fold score |
| --- | ---: |
| Expanded / raw-mass residual | **20.758** |
| Existing / retained pool | 20.812 |
| Expanded / retained pool | 21.557 |
| Existing / effective-twelve residual | 23.148 |
| Existing / raw-mass residual | 23.220 |
| Expanded / effective-twelve residual | 23.966 |
| Existing / effective-six residual | 24.324 |
| Expanded / effective-six residual | 25.142 |

Lower is better. Gates produce identical scores because none activates. The narrow winner is `expanded:mass_residual:unchanged`; this records the algorithmic selection result, not approval for a live candidate. Its three scores are **20.736 / 20.324 / 21.215**, versus the retained control's **20.736 / 21.387 / 20.313**. One fold improves, another worsens, and the mean gain is only 0.054. Repeated earlier selection still has only two distinct sufficiently populated bursty cases.

## Risk calibration and availability

For raw January 2026 08:00–16:00 startup in restart mode, the observed minimum-width survival remains **8/12 = 66.67%**:

| Forecast | Existing mean / expanded mean | Existing Brier / expanded Brier | Existing log loss / expanded log loss |
| --- | ---: | ---: | ---: |
| Static | 9.21% / 9.46% | 0.5404 / 0.5374 | 1.6713 / 1.6491 |
| Chronological | 6.75% / 7.54% | 0.5704 / 0.5604 | 1.9049 / 1.8216 |
| Context | 9.27% / 10.05% | 0.5320 / 0.5227 | 1.7802 / 1.7049 |

All three forecasts improve slightly with the fuller data, yet substantially underestimate this observed subset. On the original raw restart set's 427 bursty paths, observed minimum-width survival is **18.74%**. Expanded static / chronological / context means become **9.51% / 8.11% / 8.66%**, with Brier scores **0.1548 / 0.1589 / 0.1559**, versus existing **0.1556 / 0.1614 / 0.1585**. The expanded static fit remains better than either expanded probability correction on this pooled set.

Maximum bursty risks across the evaluated entries are **32.15% / 30.95% / 40.04%**, below the unchanged 53% gate threshold. No gate refuses a bursty quote, and all earlier retention constraints pass. Bursty quote retention stays **100%**. Original raw eligible-path availability remains **8,314/9,291 = 89.48%** under previous-floor frozen admission and **8,192/9,291 = 88.17%** under warmup/floor30. Their grid availability remains **86.83% / 85.55%**. Eligibility, grid and issued-decision denominators are retained separately.

## January and June pricing

The following phases retain identical pre-entry membership and quote availability. Startup has twelve paths; later groups contain 39 for January 2025, 22 for June 2025 and thirteen for January 2026.

| Raw interval | Mode | Existing retained startup / later | Expanded retained startup / later | Expanded raw-mass startup / later |
| --- | --- | ---: | ---: | ---: |
| January 2025 04:15–12:15 | Restart | 83.33% / 33.33% | 83.33% / 33.33% | 83.33% / 33.33% |
| January 2025 04:15–12:15 | Continuous | 75.00% / 38.46% | 75.00% / 38.46% | 75.00% / 38.46% |
| June 2025 06:00–14:00 | Restart | 41.67% / 36.36% | 41.67% / 36.36% | 41.67% / 36.36% |
| June 2025 06:00–14:00 | Continuous | 41.67% / 36.36% | 41.67% / 36.36% | 41.67% / 36.36% |
| January 2026 08:00–16:00 | Restart | 75.00% / 46.15% | 75.00% / 46.15% | 75.00% / 53.85% |
| January 2026 08:00–16:00 | Continuous | 75.00% / 46.15% | 75.00% / 46.15% | 75.00% / 53.85% |

All new residual adapters still produce **8/22 June later survivors in both modes**. Expanded raw-mass later loss is **71.089 / 70.660 ppm**, versus retained **71.622 / 71.184 ppm**, a small improvement without repairing survival. It is also worse than the previous raw-mass adapter's **70.613 / 70.162 ppm**. Expanded retained-pool later loss worsens to **71.933 / 71.584 ppm**. Additional training data therefore does not consistently improve this focused phase.

January 2026 residual adapters raise later survival from 6/13 to **7/13 = 53.85%**, above the 53% reference boundary; startup remains 9/12. January 2025's prior and forecasts remain unchanged under the same algorithm, as required by chronology. Refitting on February–May cannot repair January 2025 startup using information available then.

The [previous finite-subset feasibility bound](CALIBRATED_BURSTY_RESEARCH.md) still applies: retaining 90% of January 2026's 25 eligible bursty paths permits only two refusals. Even optimal refusal and minimum-width pricing leave at least **6/10 = 60%** startup survival. This is a constraint on that observed subset, not a population probability. More training data cannot make its 43–53% target compatible with the current retention requirement.

![Expanded raw training comparison](../.local/adaptive-corridor/20261028-expanded-bursty-v1/expanded-comparison.png)

## Whole-case stability

Counts require at least twenty offered paths and survival within 43–53%; small cells are never counted as passes. Primary frozen admission is fixed throughout.

| Training / pricing | Original raw restart / continuous passes | Canonical raw restart / continuous | Later normalized restart / continuous |
| --- | ---: | ---: | ---: |
| Existing / retained pool | 4/8 / 2/5 | 5/5 / 4/5 | 7/11 / 6/11 |
| Expanded / retained pool | 4/8 / 2/5 | 4/5 / 4/5 | 7/11 / 6/11 |
| Expanded / raw-mass residual | 3/8 / 0/5 | 5/5 / 5/5 | 5/11 / 4/11 |
| Expanded / effective-six residual | 2/8 / 0/5 | 5/5 / 5/5 | 6/11 / 5/11 |
| Expanded / effective-twelve residual | 2/8 / 0/5 | 5/5 / 5/5 | 6/11 / 4/11 |

Canonical panels overlap the shifted controls; their apparent gain does not offset losses elsewhere or constitute independent confirmation. Six canonical intervals were planned, five sufficiently populated. The sixth, January 2025 08:00, remains an eighteen-path descriptive cell.

Expanded raw-mass full-reference loss rises **48.336 → 48.582 ppm** on original raw restart paths and **80.650 → 81.648 ppm** on later normalized restart paths. Expanded retained pricing slightly reduces those aggregate losses to **48.297 / 80.466 ppm**, but gains no passes there, loses a canonical restart pass and worsens focused June loss. Neither result establishes better stability across periods.

The retained benchmark therefore stays in place. The new data are saved for later research. Another remap toward the same inspected startup labels would not resolve the finite constraint or establish transfer. Further useful work needs stronger preceding evidence for changing high-floor conditions and a pricing change that improves later-phase calibration across periods under the same availability limits.

## Reproduction and validation

```sh
python3 -B scripts/fetch_expanded_bursty_training.py \
  --previous .local/adaptive-corridor/20261028-calibrated-bursty-v1 \
  --output .local/market-history/tardis-hyperliquid-BTC-expanded-bursty-training-v1
python3 -B scripts/fetch_flat_samples.py --fetch \
  --output .local/market-history/tardis-hyperliquid-BTC-expanded-bursty-training-v1
OPENBLAS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 OMP_NUM_THREADS=1 \
  python3 -B scripts/research_expanded_bursty.py \
  --previous .local/adaptive-corridor/20261028-calibrated-bursty-v1 \
  --raw .local/market-history/tardis-hyperliquid-BTC-expanded-bursty-training-v1 \
  --output .local/adaptive-corridor/20261028-expanded-bursty-v1
python3 -B scripts/summarize_expanded_bursty.py \
  --output .local/adaptive-corridor/20261028-expanded-bursty-v1
OPENBLAS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 OMP_NUM_THREADS=1 \
  python3 -B scripts/audit_expanded_bursty.py \
  --output .local/adaptive-corridor/20261028-expanded-bursty-v1
```

Preparation and research commands require fresh output directories; preserve existing pinned archives. Fetch resumes its exact declared request list. The archive retains 53,248 case/group rows, 13,312 phase rows and 3,008 common/both-offered comparisons across **104 intervals in 74 sessions**, plus training provenance, source snapshots, numerical fits, risk scores and per-entry decisions. Repeated paths are not independent observations.

The control reconstructs **26,624 existing case/group rows, all earlier selection scores, and 118,880 per-entry prediction records exactly**. Raw/input/source hashes were reverified. Mutating own and future labels leaves fitted January/June models unchanged within 1e-10. Chronological calibration dates, maturity cutoffs, fixed non-bursty outputs and the finite January bound pass verification. The comparison figure was rendered and visually checked.

The local Python suite passes **245 tests**, with three existing optional skips and no failures. Four new tests exercise numerical sensitivity to legitimate raw replacements, isolation from own/future labels, date uniqueness and label maturity. NumPy remains 1.26.1; remote CI was not run.

The 48% target and 43–53% band remain research conventions rather than payout-product validation. Historical eligible-path availability does not establish native capture uptime. Native continuity/deadline defects remain separate unresolved work; capture stays on hold.
