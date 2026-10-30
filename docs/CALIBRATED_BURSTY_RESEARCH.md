# Chronological risk calibration and retained-price drift adapters — 28 October 2026

Follow-up: the [expanded raw training comparison](EXPANDED_RAW_BURSTY_RESEARCH.md) adds complete February–May 2025 raw days under the same formulas and constraints. Risk forecasts improve modestly, but January startup and June later survival remain unresolved and cross-period pricing passes deteriorate for the narrow earlier-fold winner. No successor is frozen or capture started.

Sixteen variants compare January startup risk and June later pricing while preserving the existing quote-retention requirements. All existing bursty quotes remain offered, but neither new risk gate activates, June later survival remains **8/22 = 36.36%** in both modes, and broader pricing passes deteriorate. The retained pooled correction remains the research benchmark. No candidate is promoted or frozen and no capture starts.

## A finite-sample limit on January startup

January 2026 08:00–16:00 has twenty-five eligible bursty paths, including twelve in the startup group. **Eight of those twelve survive the minimum allowed width.** Retaining at least 90% of the case permits at most two refusals: at least twenty-three paths must remain offered.

Even an oracle that identified the best two startup paths to refuse and priced every remaining path at minimum width would leave **six minimum-width survivors among ten startup quotes: 60% survival**. This is above the 43–53% reference band. Both restart and continuous runs have the same bound. No fitted probability calibration can remove this conflict under the current width/admission constraints.

This is a bound for the already observed subset, not an estimate of its population survival probability. The first twelve bursty quotes also need not be consecutive grid entries. It does not prove a general product limitation; it prevents interpreting another fit to this particular subset as a solution while claiming 90% case retention.

## What changed

The preceding pre-entry feature model and raw training universe remain fixed. The experiment adds two probability corrections:

- **Chronological calibration:** each prior sample day is predicted by a binary classifier fitted only on earlier days. Those out-of-fold forecasts and their subsequently matured labels train a regularized intercept/slope calibration, with a bursty child when it has eighty paths and three scoring dates; otherwise it uses the non-frozen parent. The first two training dates have no earlier out-of-fold support and retain an identity fallback. January 2025 therefore cannot learn a correction from its own January outcomes.
- **Context calibration:** the chronological estimate receives a beta-style update from matured, feature-matched non-frozen reference paths. Evidence must have at least one unit of recency/similarity mass and six effective references; transfer mass is capped at twenty-four. Quotes do not require a warmup. The absence of qualifying evidence leaves the chronological probability in place.

The online reference pool contains at most 120 paths within one hour, with fifteen-minute decay. Matching uses idle time, change cadence, concentration, volatility shape and directional efficiency, plus the retained quote width relative to slow volatility. Labels become usable only at expiry plus thirty seconds. Refused reference paths still learn; current validity and movement never control the forecast or admission decision.

For June pricing, all new adapters multiply the **retained pooled price**, rather than the conditional static price that lost many cross-period passes in the preceding iteration. They compare raw similarity mass with effective-count weighting at minimum effective support of six or twelve. Effective count cannot inflate an arbitrarily tiny similarity mass: both support conditions must pass. Each adapter keeps twelve training-prior pseudo-observations, a 5% update limit and the same integer width bounds. An unchanged retained-price control remains explicit.

Four pricing methods are crossed with unchanged admission, the static risk gate, the chronological gate and the context gate, all at the existing 53% floor threshold: **sixteen variants**. Earlier-fold selection still requires at least **95% pooled bursty retention and 90% per populated case**, charges lost availability and uses full-reference pricing loss. No model learns from its evaluated date or from raw evaluation outcomes for selection.

## Risk accuracy and quote availability

The chronological correction learns from the earlier periods, but does not transfer well to the later flat-state changes. On January 2026 startup in restart mode:

| Risk forecast | Mean predicted minimum-width survival | Observed floor | Brier score | Log loss |
| --- | ---: | ---: | ---: | ---: |
| Static feature model | 9.21% | 66.67% | 0.5404 | 1.6713 |
| Chronological calibration | 6.75% | 66.67% | 0.5704 | 1.9049 |
| Context calibration | 9.27% | 66.67% | 0.5320 | 1.7802 |

Context calibration slightly improves Brier score on that twelve-path subset, but worsens log loss and leaves the mean probability far below the observed floor. It does not establish accurate calibration or justify a new refusal rule.

On the original raw restart set's **427 bursty paths**, static / chronological / context mean probabilities are **9.09% / 7.14% / 7.62%**, against an observed floor of **18.74%**. Brier scores are **0.1556 / 0.1614 / 0.1585**. The retrospective chronological correction lowers risk in the wrong direction for these later observations; local evidence partly offsets it but does not beat the static model overall. Risk metrics use all reference paths, not just offered winners or an in-sample calibrator fit.

All three gates remain inactive in every earlier fold and evaluated bursty case. Quote retention is therefore **100% of the existing bursty quotes**, and both earlier availability constraints pass. Original raw overall availability remains **89.48%** under previous-floor frozen admission and **88.17%** under warmup/floor30. No frozen, sparse or active price/admission changes. An inactive gate preserves availability but is not evidence of successful risk screening.

## January and June phase calibration

The raw shifted January 2025 and June 2025 panels and January 2026 08:00 interval retain identical pre-entry phase membership across variants. Every startup phase has twelve reference paths; their later groups have 39, 22 and 13. All remain offered.

| Interval | Mode | Retained startup / later | New residual adapters startup / later |
| --- | --- | ---: | ---: |
| January 2025 04:15–12:15 | Restart | 83.33% / 33.33% | 83.33% / 33.33% |
| January 2025 04:15–12:15 | Continuous | 75.00% / 38.46% | 75.00% / 38.46% |
| June 2025 06:00–14:00 | Restart | 41.67% / 36.36% | 41.67% / 36.36% |
| June 2025 06:00–14:00 | Continuous | 41.67% / 36.36% | 41.67% / 36.36% |
| January 2026 08:00–16:00 | Restart | 75.00% / 46.15% | 75.00% / 53.85% |
| January 2026 08:00–16:00 | Continuous | 75.00% / 46.15% | 75.00% / 53.85% |

The three adapters have the same survival counts on these focused phases, although their widths and losses differ. The January 2026 later result becomes 7/13 = 53.85%, just above the reference band, while startup remains high. No gate suppresses that miss.

![Calibrated risk and retained-price adapters](../.local/adaptive-corridor/20261028-calibrated-bursty-v1/calibrated-phase-comparison.png)

June's raw-mass adapter reduces later full-reference quantile loss **71.622 → 70.613 ppm** in restart mode and **71.184 → 70.162 ppm** continuously. The effective-six adapter yields **71.202 / 70.900 ppm**; effective-twelve yields **71.005 / 70.682 ppm**. None produces another surviving path. Smaller loss and continuous history therefore do not repair the observed later survival drift.

## Comparison across periods and selection

Lower earlier-fold scores are better: retained pool **20.812**, effective-twelve **23.148**, raw-mass **23.220**, effective-six **24.324**. Gates leave scores unchanged because none activates. The previous baseline score reconstructs exactly. The same inspected selection periods still contain only two distinct bursty cases with twenty or more paths.

| Pricing | Original raw restart / continuous bursty passes | Canonical raw restart / continuous | Later normalized restart / continuous |
| --- | ---: | ---: | ---: |
| Retained pool | 4/8 / 2/5 | 5/5 / 4/5 | 7/11 / 6/11 |
| Raw-mass residual | 2/8 / 0/5 | 5/5 / 5/5 | 6/11 / 4/11 |
| Effective-six residual | 2/8 / 0/5 | 5/5 / 5/5 | 6/11 / 4/11 |
| Effective-twelve residual | 2/8 / 0/5 | 5/5 / 5/5 | 6/11 / 4/11 |

The canonical continuous gain comes with worse performance on other panels. Canonical and shifted raw panels overlap original controls and are not independent additions. There are six canonical intervals, five sufficiently populated; the eighteen-path January 2025 08:00 interval is never counted as a pass merely because it is small. The original raw restart set has ten intervals but eight populated bursty cells; the original continuous set has six intervals and five populated cells.

Full-reference original raw restart loss rises **48.336 → 48.671 / 48.873 / 48.819 ppm** for raw-mass / effective-six / effective-twelve. Later normalized restart loss rises **80.650 → 81.935 / 82.145 / 82.384 ppm**. June's small focused loss gain is not a stable cross-period improvement. The retained pool remains the benchmark.

The evidence separates two issues: January's finite startup target conflicts with the retained-quote constraint, while the tested prior/context transfer is still insufficient to fix June's later prices. These results do not support a new candidate. Additional distinct preceding oracle-update regimes would be more informative than another probability remap fitted toward the same inspected January outcomes.

## Reproduction and verification

```sh
OPENBLAS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 OMP_NUM_THREADS=1 \
  python3 -B scripts/research_calibrated_bursty.py \
  --previous .local/adaptive-corridor/20261028-preentry-pricing-v2 \
  --output .local/adaptive-corridor/20261028-calibrated-bursty-v1
OPENBLAS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 OMP_NUM_THREADS=1 \
  python3 -B -m unittest discover -s scripts -p 'test_*.py'
```

Use a new output directory for another experiment. Existing raw archives, engines, frozen masks, feature models and source snapshots remain pinned; the new research uses separate modules. The run retains **26,624 case/group rows**, **6,656 phase rows**, **1,504 common/both-offered mode comparisons**, chronological calibration folds, reference/quote denominators, all risk scores and per-entry diagnostics across **104 eight-hour intervals in 74 sessions**. Repeated and overlapping paths are not independent holdouts or a prospective capture.

The Python suite runs **241 tests**, with three existing optional skips and no failures. New tests cover binary-fit equivalence and width independence, chronological out-of-fold predictions and maturity, tiny-weight rejection, shared versus independent replay, current/future outcome isolation, refused-reference learning, period resets, non-bursty invariance and unchanged admission prices. NumPy remains pinned at 1.26.1; remote CI was not run here.

The 48% target and 43–53% band remain legacy research references, not payout-product validation. Native capture continuity and deadline defects remain separate work. Historical eligible-path availability does not establish capture uptime. Capture stays on hold.
