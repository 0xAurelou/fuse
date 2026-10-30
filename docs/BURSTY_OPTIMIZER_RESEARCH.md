# Automated corridor parameter search — 28 October 2026

The subsequent [symbolic-regression comparison](SYMBOLIC_CORRIDOR_RESEARCH.md) searches expression structures using bursty-only and shared non-frozen training. Neither symbolic method improves cross-period calibration; the retained benchmark and capture hold remain in place.

A bounded Bayesian optimizer now automates the next-parameter choice that previous experiments made manually. The first **32-trial search took 24.97 seconds after caching**; input verification, caching and later diagnostics brought the full run to **76.91 seconds**. It improved the earlier chronological selection objective **20.0941 → 15.7880**, a 21.43% reduction in that score. This is neither a profitability improvement nor an independent estimate of future calibration.

Later results are mixed. Original raw bursty pass counts improve, but January later pricing and some broader losses deteriorate. The retained benchmark stays in place. No candidate is promoted or frozen for capture, and no capture starts.

## What the small model does

[Bayesian optimization](https://arxiv.org/abs/1206.2944) uses a model of experiment results to choose promising parameters. Here a small Gaussian process models **backtest score as a function of parameters**, rather than forecasting BTC directly. The implementation uses the existing NumPy dependency and requires no new service, model download or credentials.

The first four proposals reconstruct existing controls. Proposals through trial ten provide initial exploration. Later proposals maximize approximate expected improvement over a pool of 1,024 sampled points, half concentrated around the incumbent; every fifth proposal remains global exploration. The Matérn 5/2 kernel, fixed length scale, numerical noise, seed, trial budget and parameter ranges are declared before scoring. This is a lightweight local implementation, with fixed surrogate settings and no claim of outperforming random search from this single pilot.

| Parameter | Declared search range | Best trial, displayed rounded |
| --- | --- | --- |
| Frozen forecast | Timing or timing plus mark/oracle gap | Gap |
| Evidence half-life | 15–180 minutes, logarithmic | 61.58 minutes |
| Maximum age | 2–8 half-lives | 5.87 half-lives, about 6.03 hours |
| Prior pseudo-observations | 0.25–24, logarithmic | 0.838 |
| Maximum multiplier change per supported entry | 1–40%, logarithmic | 40% |
| Learned-prior weight in log ratio space | 0–1 | 0.921 |

The prior knots become `exp(weight × log(original knot))`; weight zero is neutral and weight one reproduces the prior. The controller takes a weighted 48th percentile of prior knots and matured `required width / frozen forecast` ratios, moves toward it within the step limit, then multiplies the frozen forecast. Correction bounds remain 0.25–4, memory remains at most 120 bursty references, and final corridor bounds remain 1–50,000 ppm. Full-precision parameters are saved in `selection.json`; the displayed rounded values are not a new frozen candidate.

The main direction found is a substantially weaker prior than the preceding twelve pseudo-observations, allowing sparse live evidence to matter. The step reaches the declared upper bound. These observations are hypotheses for further research, not evidence that faster adaptation is universally better.

This version searches **parameters within the existing bursty residual family**. It does not discover arbitrary formulas or retune frozen/active/sparse pricing. For searching the structure of a readable formula, [symbolic regression such as PySR](https://arxiv.org/abs/2305.01582) is a possible later extension, with operator/complexity bounds and the same chronological evaluator. It has not been installed or run in this experiment.

## Selection boundaries and causal replay

Every trial uses the same original six-, nine- and twelve-date fitting prefixes and next three/three/two scoring dates as the previous research. Models and chronological forecast priors remain frozen. The objective, equal fold weights, restart/continuous disagreement penalty, phase errors and full-reference pricing-loss guard remain unchanged. The earlier scoring folds have only **two distinct bursty cases with at least twenty paths**; many overlapping observations do not supply additional independent episodes.

Only normalized sessions on those declared earlier scoring dates enter the optimizer. Labels enter the correction at expiry plus thirty seconds. Refused clean references still learn. Each restart has private state; continuous state is not reset at scoring boundaries. Other-state outcomes cannot update this correction when underlying retained references are fixed. Missing context uses the benchmark. Prices, masks, grid denominators and quote availability outside bursty repricing remain fixed.

The 95% pooled and 90% populated-case bursty retention checks run for both modes of every fold. Because this search changes pricing only, all trials retain 100% of benchmark bursty quotes. Every trial scores every fold; no later-fold outcome is skipped through adaptive pruning.

The shortlist is saved and hashed **before later diagnostics**, and diagnostics cannot feed back into proposals or ranking. Those later dates were inspected repeatedly in earlier work and remain development comparisons, not fresh holdouts. Selection calls the best trial `optimized`; this is a research selection, not live promotion.

## Later comparisons

These are descriptive populated bursty cells under the primary frozen admission policy. A pass means at least twenty quotes and survival in the research 43–53% band. The panels overlap.

| Panel | Retained restart / continuous | Previous selection restart / continuous | Optimized restart / continuous |
| --- | --- | --- | --- |
| Original raw | 4/8 · 2/5 | 4/8 · 0/5 | **5/8 · 3/5** |
| Canonical full raw | **5/5 · 4/5** | 2/5 · 3/5 | 4/5 · 4/5 |
| Later normalized validation | 6/9 · 6/9 | 6/9 · 6/9 | 6/9 · 6/9 |
| Later normalized test | **7/11 · 6/11** | 6/11 · 5/11 | 6/11 · 6/11 |

Calibration pass counts and width loss disagree in places. Original raw restart full-reference bursty pinball loss rises **48.336 → 49.676 ppm**; later normalized test restart rises **80.650 → 81.530 ppm**. Canonical continuous improves **65.532 → 64.597 ppm**. The optimizer did not solve cross-period stability.

On the matched January 2025 panel, optimized later survival is **12/39 restart and 13/39 continuous**, versus retained **13/39 and 15/39**, and previous selected binary correction **14/39 and 17/39**. June later remains **8/22** in both modes. January 2026 startup improves from 9/12 to **8/12** survivors but remains above the band, with later survival falling from 6/13 to **5/13**. The previously established finite January minimum-width/availability bound still applies; parameter search cannot remove it.

All previously offered bursty quotes remain offered. Original raw overall eligible quote availability stays **8,314/9,291 = 89.48%** for the primary policy and **8,192/9,291 = 88.17%** for the secondary policy. This says nothing about prospective capture uptime.

![Search progress and descriptive period comparisons](/Volumes/dev/fuse/.local/adaptive-corridor/20261028-bursty-optimizer-v1/optimizer-comparison.png)

## Reproduction and verification

```sh
OPENBLAS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 OMP_NUM_THREADS=1 \
  python3 -B scripts/research_bursty_optimizer.py \
  --previous .local/adaptive-corridor/20261028-bursty-residual-v1 \
  --output .local/adaptive-corridor/20261028-bursty-optimizer-v1 --trials 32
OPENBLAS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 OMP_NUM_THREADS=1 \
  python3 -B scripts/audit_bursty_optimizer.py \
  --output .local/adaptive-corridor/20261028-bursty-optimizer-v1
OPENBLAS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 OMP_NUM_THREADS=1 \
  python3 -B -m unittest discover -s scripts -p 'test_*.py'
```

Use a new output directory. The CLI accepts a bounded 4–256 trials, defaults to 32, and preserves completed records immediately in `trials.jsonl`. Forecasts are cached in memory across trials. Inputs and executable sources are bound through the retained source/hash chain; the protocol, exact parameters, every fold result and diagnostics are archived. Rerunning with the same seed and budget is reproducible; extending a completed archive in place is intentionally unsupported.

The audit reproduced all 32 proposals and the selected score exactly, verified 14,860 preceding control prediction records and 279,080 feature records, and checked actual January/June counterfactuals for label maturity and isolation from other-state labels. The four initial controls reconstruct the preceding fold scores. All 4,992 case/group rows, 1,248 phase rows and 282 paired comparisons retain the same admission/grid denominators. The figure was visually checked.

The full local Python suite ran **274 tests, with three existing optional skips and no failures**. Six new tests cover bounded search, deterministic proposals, trial protocol, control reconstruction, maturity, resets, fallback and fixed admission. Remote CI was not run.

The next research direction is a more robust regime-sensitive objective and a small, interpretable formula family, followed by confirmation on genuinely unseen dates. Increasing the search budget alone would mainly increase the opportunity to overfit the sparse existing scoring cases. The 48% target remains a research convention rather than payout-product validation; capture continuity/deadline issues remain separate work.
