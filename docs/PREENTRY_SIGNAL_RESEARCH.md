# Pre-entry admission signals and later-period bursty pricing — 28 October 2026

Follow-up: [chronological calibration and retained-price adapters](CALIBRATED_BURSTY_RESEARCH.md)
adds earlier-date calibration and support-controlled online updates. It verifies
a finite-sample January availability/calibration conflict and leaves June later
survival unresolved; no new capture or candidate promotion follows.

This iteration replaces mandatory startup warmup with a trained entry-time flat-risk signal and tests three pricing refinements against the retained pooled correction. Engines, frozen pricing and both frozen-admission policies stay fixed. No new capture starts and no live candidate is promoted.

## Models and safeguards

Eleven explicit pre-entry features describe idle time, change counts over thirty/sixty/three-hundred seconds, empty observation bins, variance concentration, slow volatility, fast/slow volatility shape, directional strength and its efficiency proxy, and an idle/cooling interaction. The efficiency proxy is directional strength divided by the square root of the change count, capped at one; it is available consistently in raw and normalized archives. No current movement, future validity or outcome field enters the feature vector.

A ridge-regularized logistic model estimates the probability that a thirty-second path survives even the minimum width. It learns from all eligible non-frozen reference paths on strictly earlier training dates, with equal weight per date. Two admission gates refuse a bursty quote only when predicted minimum-width survival exceeds 53% or 65%. There is no quote-count warmup. Current-feature availability and all existing refusals are preserved; active, sparse and frozen admission stays fixed.

Selection requires at least **95% pooled bursty quote retention and 90% retention in each populated case**, in every chronological fold and mode. The existing availability cost also remains. These are earlier-fold constraints, not a quota that selectively returns favorable future quotes. The full outer comparison reports any actual availability losses independently.

Four pricing methods are crossed with unchanged admission and both risk gates, for **twelve variants**:

- The retained pooled bursty correction is the control, using the preceding November/December 2024 and January/June 2025 raw replacements.
- A slow-volatility anchor can widen cooling-state bursty quotes when fast volatility has decayed. Its scale comes from preceding cooling/bursty references with adequate support, otherwise the non-frozen parent. Its effect tapers to zero as the fast/slow ratio approaches 0.75 and is full below 0.5.
- Conditional static pricing fits a regularized positive-path log-width model using entry features and the current engine width relative to slow volatility. Its positive quantile is adjusted using estimated minimum-width mass. It uses asymmetric Huber IRLS and is an approximate fitted quantile, not an exact calibration guarantee.
- Conditional residual pricing adds a causal, feature-matched correction from all matured non-frozen references. It uses at most 120 references within one hour, fifteen-minute decay, twelve training-prior pseudo-observations and a 5% update bound. There is no mandatory reference-count admission gate.

Every online label becomes usable only at expiry plus thirty seconds. Refused reference paths still learn; no customer trade is assumed. Alternative pricing changes only bursty widths. All bounds and features are fixed before outer replay. Widths use exact integer barriers and remain within 1–50,000 ppm.

The original fourteen training dates remain the universe: raw rows replace matching dates once, without adding restarted or continuous copies. Each prior uses only dates and matured outcomes before its scoring cutoff. All **104 eight-hour intervals in 74 sessions** remain in the comparison under both frozen policies. Overlapping original, canonical and shifted raw panels are reported separately, as are later normalized dates and native replays. They are not independent holdouts.

## Earlier-period selection

| Pricing | Selection score | Gate effect in earlier folds |
| --- | ---: | --- |
| Retained pool | 20.812 | Neither threshold activates |
| Slow-volatility anchor | 24.914 | Neither threshold activates |
| Conditional static | 32.901 | Neither threshold activates |
| Conditional residual | 32.677 | Neither threshold activates |

Lower is better. Scores combine the existing calibration, phase and availability objective with the unchanged full-reference pricing-loss guard. The retained score reconstructs the preceding experiment exactly. All variants meet the earlier availability constraint because the risk thresholds refuse no earlier-fold bursty quotes. This is not evidence that the classifier can identify startup failures. Those repeatedly inspected folds still contain only two distinct populated bursty cases.

## Admission quality and availability

Both risk thresholds are inactive on every evaluated bursty quote, in earlier folds and outer comparisons. Each pricing method therefore has the same results under unchanged admission, floor53 and floor65. The original raw restart availability stays **8,314/9,291 = 89.48%** under previous-floor frozen admission and **8,192/9,291 = 88.17%** under warmup/floor30; bursty availability stays **100%**. Grid and pre-entry denominators remain visible and unchanged. Frozen, active and sparse prices and admission remain exactly fixed.

This preserves quote availability but does not validate stronger admission. On January 2026's first twelve bursty quotes in the 08:00 restart interval, predicted minimum-width survival averages **9.21%**, with a maximum of **16.41%**. The observed floor is **8/12 = 66.67%**. No prediction approaches the refusal thresholds. The small sample is descriptive, but the mismatch explains why this model cannot resolve the observed startup conflict. Lowering a threshold to match those already inspected outcomes would not establish an effective rule.

The archive also reports prediction bins, observed floor rates and Brier scores against the chronological constant-floor prior on all reference paths. Risk quality must be assessed on that evidence, rather than crediting the gate for refusing nothing or fitting on the current failure's outcomes.

## January startup and June later pricing

All paths below remain offered. Conditional static and conditional residual pricing have identical focused survival counts, although their widths and losses differ. Entry-rank phase groups remain fixed across methods and modes.

| Raw interval and mode | Retained startup / later | Slow anchor startup / later | Conditional startup / later |
| --- | ---: | ---: | ---: |
| January 2025 04:15–12:15, restart | 83.33% / 33.33% | 91.67% / 48.72% | 75.00% / 51.28% |
| January 2025 04:15–12:15, continuous | 75.00% / 38.46% | 83.33% / 51.28% | 66.67% / 51.28% |
| June 2025 06:00–14:00, restart | 41.67% / 36.36% | 41.67% / 36.36% | 50.00% / 36.36% |
| June 2025 06:00–14:00, continuous | 41.67% / 36.36% | 41.67% / 36.36% | 50.00% / 36.36% |
| January 2026 08:00–16:00, restart | 75.00% / 46.15% | 75.00% / 46.15% | 75.00% / 53.85% |
| January 2026 08:00–16:00, continuous | 75.00% / 46.15% | 75.00% / 46.15% | 75.00% / 53.85% |

Every startup group contains twelve eligible paths; later groups contain 39, 22 and 13, respectively. Twelve-path startup results are not pass claims. The June later result is **8/22** under every method, both modes, and neither risk gate suppresses that failure.

![Pre-entry pricing and fixed phase comparisons](../.local/adaptive-corridor/20261028-preentry-pricing-v2/preentry-phase-comparison.png)

Conditional pricing improves January 2025's later phase and reduces its startup overshoot, without making startup calibrated. It changes June startup to 50%, but leaves later drift unresolved. The slow anchor reduces June later quantile loss from **71.62 to 69.48 ppm** in restart mode, with no additional survivors, while worsening January overshoot and broader losses. The conditional residual changes June's later restart loss to **71.17 ppm**, also with no additional survivors.

The residual adapter's June later restart correction ranges **0.951–1.048**, median **0.990**. Its feature-matched recency mass has median **1.01**, versus twelve training-prior pseudo-observations; median effective sample size is 7.91. These are different confidence measures: low total weight leaves the prior dominant even when several weakly similar references exist. The tested adapter therefore makes only small width adjustments and does not supply a demonstrated solution to the large late moves. Retained per-entry diagnostics expose that limitation rather than implying that continuous history repaired it.

## Comparison across periods

All admission columns are identical for each pricing method because neither gate activates. Passes require twenty paths and survival in 43–53%; unchanged eligible denominators prevent thin cases disappearing from the comparison.

| Pricing | Original raw restart / continuous bursty passes | Canonical raw restart / continuous | Later normalized restart / continuous |
| --- | ---: | ---: | ---: |
| Retained pool | 4/8 / 2/5 | 5/5 / 4/5 | 7/11 / 6/11 |
| Slow anchor | 1/8 / 0/5 | 3/5 / 2/5 | 5/11 / 5/11 |
| Conditional static | 1/8 / 1/5 | 2/5 / 1/5 | 1/11 / 1/11 |
| Conditional residual | 2/8 / 1/5 | 3/5 / 2/5 | 1/11 / 1/11 |

There are ten original raw restart intervals with eight populated bursty cells, six original raw continuous intervals with five populated cells, and six canonical raw intervals with five populated cells. January 2025 08:00 has eighteen paths and is not counted as a canonical pass. Canonical and shifted panels overlap the original controls and must not be added as independent tests. The newer pricing may alter that small interval's result; its count remains eighteen and is still not a pass.

Conditional residual pricing reduces full-reference later normalized restart loss **80.650 → 76.881 ppm** and canonical raw restart loss **65.462 → 62.511 ppm**, but worsens original raw restart loss **48.336 → 48.648 ppm** and sharply reduces whole-case pass counts. A lower aggregate quantile loss does not establish stable per-period calibration.

The research benchmark remains the retained pooled correction with unchanged bursty admission. The new signal/model family preserves availability and provides useful risk and support diagnostics, but neither January startup nor June later drift is solved. Further work needs better observed update-timing/context evidence and chronological risk calibration; these results do not justify lowering refusal thresholds or weakening prior confidence specifically to fit the same inspected failures. No successor is frozen and capture stays on hold.

## Reproduction and verification

```sh
python3 -m pip install -r scripts/requirements-research.txt
OPENBLAS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 OMP_NUM_THREADS=1 \
  python3 -B scripts/research_preentry_bursty.py \
  --previous .local/adaptive-corridor/20261028-earlier-raw-startup-v1 \
  --output .local/adaptive-corridor/20261028-preentry-pricing-v2
OPENBLAS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 OMP_NUM_THREADS=1 \
  python3 -B -m unittest discover -s scripts -p 'test_*.py'
```

Use a new output directory for another replay. The archive retains the declaration, source snapshots, numerical fits and NumPy version, selection folds, full-reference and offered metrics, per-entry risk/pricing decisions, risk calibration bins and common/both-offered mode comparisons. The initial `v1` attempt was invalidated by the source guard after correcting a one-ppm no-op rounding edge in the slow anchor; none of its results are used. A regression test now requires an unchanged anchor quote to remain exactly unchanged.

NumPy 1.26.1 is pinned in the research requirements, matching the tested local environment. Both CI jobs that discover all Python tests now install it; the engine research job also selects Python 3.12. Remote CI was not run here. The local suite completes **233 tests** with three existing optional skips. New tests cover the feature allowlist, temporal outcome isolation, refused-reference learning, period resets, fixed non-bursty pricing, strict admission thresholds, quote-retention requirements, training cutoffs and integer no-op behavior.

The 48% survival target, 43–53% reference band and twenty-path pass minimum remain research conventions. Twelve-path startup samples are descriptive. Historical eligible-path quote availability does not establish native capture uptime. Capture continuity/deadline defects and payout-product validation remain separate unresolved work.
