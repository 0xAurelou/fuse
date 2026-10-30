# Payout-aware flat-risk modeling — 29 October 2026

The new model identifies a useful part of the high-payout failure: flat-oracle risk can be forecast before entry. It improves a proper probability score relative to a constant training-rate baseline, and causal gates remove many mandatory wins. It does not yet deliver calibrated 100×/1,000× pricing with broad quote availability. No candidate is promoted and no live policy, payout, horizon or ongoing capture changes.

## Model and experiment

Each asset has two probability heads: the chance of zero oracle movement over the next thirty seconds, and the chance that the path survives the research one-ppm minimum corridor. The second is constrained to be at least the first. Zero-motion survival is a product-level constraint for every positive width; the one-ppm floor is specific to these offline research barriers. The shipped engine uses finer ppb quantization.

Both heads use regularized logistic regression on strictly pre-entry inputs. Timing inputs are oracle idle age, thirty/sixty/three-hundred-second change counts, empty-bin share, variance concentration, fast/slow volatility, signed drift, directional strength, an idle/cooling interaction, and the lower-bound idle flag. Calendar adds UTC weekend and cyclic UTC hour. Market/calendar adds fresh mark/oracle gap and movement features plus an explicit missing-context flag. No date ID, current move, current validity or future-price predictor is permitted. Stale market context does not remove entries from the comparison.

Six candidates per asset cross three feature families with ridge 0.0001/0.003. Earlier training dates end in December 2025. January–May 2026 chooses the risk family/ridge using the mean daily zero/floor binary log loss, with equal label weights. Payout outcomes do not select the gate or pricing method. June–October 2026 remains already inspected development diagnostics, not untouched calendar-date holdouts or prospective validation. All models and the selection are hash-bound before this experiment scores later payout outcomes.

The movement component fits ten conditional quantiles of log required width relative to pre-entry slow volatility, using all positive-width training references and equal date weights. Levels are 0.0001, 0.0003, 0.001, 0.003, 0.01, 0.03, 0.1, 0.3, 0.5 and 0.8. Coefficients use smoothed quantile IRLS with ridge 0.001; predicted quantiles are sorted before interpolation. These numerical fits have no conditional coverage guarantee.

For payout `M`, the assumed 5% gross-edge target is `q = 0.95/M`. Given predicted minimum-width risk `p_min`, the requested positive-path quantile is:

`r = (q - p_min) / (1 - p_min)`

When `p_min > q`, no corridor within the one-ppm research bound can attain the target under that forecast. A predicted zero-motion probability above `q` is the stronger constraint that persists even if finer widths are allowed. Gated conditional quotes also require the requested positive quantile to lie inside the trained grid and `number_of_positive_training_rows × r >= 20`. This count is an explicitly global support screen, not twenty independent/local events or a confidence guarantee. Open controls retain a minimum-width shadow forecast for unsupported tails so the comparison cannot hide those outcomes.

The fixed gate thresholds are 25%, 50% and 100% of the payout target. Risk-only controls gate the original payout widths without changing them. Conditional variants also replace those widths. A weekday-only control tests the calendar hypothesis. Every refusal is an entry-time decision; realized outcomes never decide which quotes were offered.

Static and delayed-calibrated variants use the same frozen coefficients. The delayed version compares actual and expected zero/floor labels across at most 240 mature reference paths, with a four-hour age limit, one pseudo-event and odds adjustment bounded to 0.1–10. Labels enter only after expiry plus thirty seconds. All clean reference paths teach this calibrator, including paths whose quote was refused. Changing admission or widths cannot change the calibrator's information set. State resets between the sampled monthly days.

## Risk prediction

| Asset | Validation-selected risk family | Later actual minimum-width survival | Mean static prediction | Static log loss | Constant-rate log loss |
| --- | --- | ---: | ---: | ---: | ---: |
| ETH | timing:ridge0.0001 | 2.96% | 3.15% | 0.09682 | 0.13858 |
| HYPE | calendar:ridge0.003 | 0.42% | 0.53% | 0.02122 | 0.02717 |

Lower log loss is better. The model improves this historical probability score; that does not establish calibrated probabilities in every low-risk bucket. The retained `risk-reliability.csv` reports the rare-risk bins explicitly. ETH selects timing without calendar features. HYPE selects calendar jointly with hour-of-day, so the selection does not isolate a weekend effect or prove a liquidity mechanism. No order-book depth, spread or volume was measured.

## Risk-only filtering

The following fixed comparator refuses original-width quotes when predicted minimum-width risk exceeds the payout target. These rows use static risk; this threshold was declared rather than selected from later results.

| Asset | Payout | Target wins | Original win rate | Filtered win rate | Kept eligible quotes | Kept / eligible | Filtered wins |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| ETH | 100× | 0.950% | 3.151% | 0.524% | 57.05% | 7,821 / 13,709 | 41 |
| ETH | 1,000× | 0.095% | 2.969% | 0.000% | 3.68% | 504 / 13,709 | 0 |
| HYPE | 100× | 0.950% | 1.765% | 1.254% | 91.31% | 12,518 / 13,710 | 157 |
| HYPE | 1,000× | 0.095% | 0.416% | 0.000% | 14.43% | 1,978 / 13,710 | 0 |

Filtering reduces mandatory wins, but it does not allocate the remaining probability budget to moving-path wins. At 100×, ETH becomes more conservative than the 0.95% target at a substantial availability cost; HYPE still exceeds its target and its 1% zero-cost break-even win rate. At 1,000×, the retained samples imply fewer than two expected wins per asset at the requested probability. Zero observed wins on those small retained samples is not evidence that 1,000× probabilities or LP profitability are established.

## Conditional lower-tail pricing

The conditional formula changes widths as well as applying the full-target risk gate and the declared positive-tail support screen:

| Asset | Payout | Win rate | Kept eligible quotes | Kept quotes | Wins |
| --- | ---: | ---: | ---: | ---: | ---: |
| ETH | 100× | 1.024% | 55.54% | 7,614 | 78 |
| ETH | 1,000× | 0.000% | 0.20% | 27 | 0 |
| HYPE | 100× | 1.242% | 90.47% | 12,404 | 154 |
| HYPE | 1,000× | 0.000% | 0.15% | 20 | 0 |

The lower-tail formula does not consistently repair the remaining pricing error. Its 1,000× support screen leaves almost no usable quotes. Without any gate, the new static formula has the following win rates:

| Asset | 100×, target 0.95% | 1,000×, target 0.095% |
| --- | ---: | ---: |
| ETH | 3.436% | 2.962% |
| HYPE | 1.430% | 0.416% |

Repricing alone leaves the flat-path constraint in place. The delayed-calibration and stricter 25%/50% gates are retained as matched comparisons in `metrics.csv`; no favorable later cell chooses a production rule.

No tested variant simultaneously meets the provisional 85%-availability reference in every later day and the pooled ±25%-of-target survival reference. Those references are descriptive research screens. Every 1,000× variant also lacks twenty expected later wins at its target. An empty or nearly empty quote set is reported as inadequate evidence, never as a calibration pass.

## Interpretation and next work

This is a useful pre-entry risk detector, with an explicit cost in refused quotes. It gives the product a way to estimate when a high payout is difficult or impossible under the forecast. It does not yet supply an acceptable full pricing policy. Fewer low-risk quotes, uncertain tail probabilities and changing regimes remain material limitations.

The next experiment should calibrate low-risk probability buckets and moving-path tails on additional preceding dates, then test a frozen rule across consecutive fresh weeks containing multiple weekends. Gate thresholds must be chosen before that prospective evaluation, with quote availability, refusals, tail support, calibration and stake-weighted economics assessed together. A simple weekend ban is not established by these monthly samples.

Gross arithmetic in the CSV is `1 − M × realized win rate` for equal stakes before costs. It does not include trader selection, overlapping exposure, aggregate BTC/ETH/HYPE losses, LP fees, refunds, reserve dynamics or execution costs. Paper/live pricing and balances remain unchanged.

## Reproduction and evidence

Archive: `.local/adaptive-corridor/20261029-payout-flat-risk-v1`. Parent raw dataset: `.local/adaptive-corridor/20261028-ETH-HYPE-raw-fits-v2/`.

- `protocol.json` and `source/` pin the model, features, targets, gates, support and selection before the experiment.
- Each asset has `models.json`, `selection.json`, `predictions.jsonl.gz`, `metrics.csv`, `risk-metrics.csv`, `risk-reliability.csv` and `research.json`.
- `audit.json` binds original raw payload hashes and reconstructs risk selection, probability forecasts, delayed reference calibration, entry decisions, integer barrier outcomes, positive-tail support and metric arithmetic.

The independent audit checks 1,843,200 saved decisions across both assets and verifies 3,456 original raw payloads. The focused suite passes eleven tests, including a complete fit/export/audit fixture. The full Python suite ran 374 tests: three existing skips and all others passed.

Use a new directory for reproduction; existing model packets and audits are preserved:

```sh
python3 -B scripts/research_payout_risk.py --declare \
  --parent .local/adaptive-corridor/20261028-ETH-HYPE-raw-fits-v2 \
  --output .local/adaptive-corridor/NEW-PAYOUT-RISK
OPENBLAS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 python3 -B scripts/research_payout_risk.py \
  --parent .local/adaptive-corridor/20261028-ETH-HYPE-raw-fits-v2 \
  --output .local/adaptive-corridor/NEW-PAYOUT-RISK
python3 -B scripts/audit_payout_risk.py --research .local/adaptive-corridor/NEW-PAYOUT-RISK
python3 -B -m unittest discover -s scripts -p test_payout_risk.py
```

The offline forecast API is `risk(pre_entry_row, risk_model)` in `scripts/payout_risk.py`, which returns `(zero_motion_probability, minimum_width_probability)`. `conditional_width` requests a payout-specific lower-tail width and returns its support diagnostics. Neither forecast function reads the current outcome. Accepted ticket terms are not modified by this research.
