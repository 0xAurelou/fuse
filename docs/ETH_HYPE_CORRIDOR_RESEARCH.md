# Independent ETH and HYPE corridor fits — 28 October 2026

Separate models were fitted on each asset's own raw Hyperliquid oracle history. No BTC fitted coefficients were transferred. The artifacts contain the legacy 48% survival experiment and nine separate payout-specific fits. These are historical research models; the paper/live quote configuration and the ongoing BTC capture were not changed.

## Data, chronology and method

The pinned public Tardis request list contains 3,456 ten-minute raw `activeAssetCtx` slices. All requests completed without credentials or paid endpoints; compressed CRCs and local SHA-256 bindings were verified. Each first-of-month UTC date is a full raw day, not a continuous recording across months. Receipt timestamps, `oraclePx`, unchanged-price messages, mark context and disconnect markers are retained; mark prices never substitute for oracle outcomes.

ETH has 24 dates from November 2024 through October 2026. Provider coverage for HYPE begins on 5 December 2024, so its 22 monthly dates begin in January 2025. Missing earlier HYPE history is explicitly absent. Training ends with December 2025: fourteen ETH dates and twelve HYPE dates. January–May 2026 selects the primary family; June–October 2026 evaluates it after the choice and legacy models are pinned. Those later asset outcomes did not select a family, coefficient, target or threshold. Related calendar dates have already been studied for BTC, so these are withheld asset results within a development program, not prospective evidence.

The native BTC research machinery is reused with independent fits: period-balanced fast/slow volatility and directional scales, activity corrections, delayed reference updates, a frozen hurdle distribution and the full-core bursty residual prior. The five predeclared 48% comparators are slow volatility, activity+hurdle, full core, timing-context frozen feedback, and market-context frozen feedback. The two context methods replace only frozen pricing. Validation score is mean daily absolute survival error + 0.5 × mean populated activity/regime error + 0.25 × worst daily error, in percentage points; candidate order breaks ties. Cells need twenty paths for that descriptive score.

Each payout fit independently targets `0.95 / multiplier`, with the activity+hurdle model refitted at that target. The existing full-core and conditional-CDF update rules fix 48%, so those families are compared only in the 48% experiment. Payout-specific fits do not inherit a 48% survival probability. No payout-specific family search is claimed.

Entries are nonoverlapping thirty-second UTC grid windows. Features require five minutes of clean history strictly before entry. The eight-second single-stream freshness screen and disconnect censorship preserve missing outcomes; predictions are made without reading current outcome validity. Touching either rounded barrier loses. Research widths are integer ppm in [1, 50,000]. Delayed updates use outcomes only after expiry plus thirty seconds, and state resets at each sampled day. Pump/dump labels retain the BTC research definitions; their suitability for each asset remains a hypothesis.

## Primary 48% result

| Asset | Raw oracle observations | Clean training paths | Test paths | Validation-selected family | Test survival | Mean half-width, ppm |
| --- | ---: | ---: | ---: | --- | ---: | ---: |
| ETH | 2,001,920 | 39,851 | 13,709 | full_core | 48.22% | 288.61 |
| HYPE | 1,834,137 | 34,170 | 13,710 | market_priceable | 47.94% | 564.50 |

Mean half-width summarizes changing quotes, not a recommended fixed corridor. Pooled agreement with 48% does not establish calibration in each date or state.

| Withheld raw date | ETH survival | HYPE survival |
| --- | ---: | ---: |
| 2026-06-01 | 48.44% (2758 paths) | 48.08% (2758 paths) |
| 2026-07-01 | 48.08% (2658 paths) | 47.84% (2659 paths) |
| 2026-08-01 | 49.13% (2766 paths) | 48.05% (2766 paths) |
| 2026-09-01 | 47.64% (2758 paths) | 48.26% (2758 paths) |
| 2026-10-01 | 47.78% (2769 paths) | 47.45% (2769 paths) |

Pooled conditional results for the selected families:

| Group | ETH survival / paths | HYPE survival / paths |
| --- | ---: | ---: |
| active | 48.08% / 12241 | 48.00% / 13078 |
| sparse | 51.20% / 543 | 35.56% / 45 |
| bursty | 46.62% / 517 | 48.11% / 530 |
| frozen | 50.49% / 408 | 42.11% / 57 |
| pump | 50.87% / 519 | 48.93% / 1214 |
| dump | 50.97% / 565 | 47.64% / 1251 |

These paths share histories and market regimes. Counts and percentages are descriptive; thin or empty groups cannot certify conditional probabilities. No binomial independence is assumed.

## Payout-specific fits

| Payout | Target survival | ETH test survival | HYPE test survival | ETH mean half-width, ppm | HYPE mean half-width, ppm |
| --- | ---: | ---: | ---: | ---: | ---: |
| 2× | 47.50% | 47.29% | 47.16% | 284.92 | 556.04 |
| 5× | 19.00% | 20.77% | 18.94% | 152.38 | 304.49 |
| 10× | 9.50% | 12.07% | 9.88% | 106.05 | 219.65 |
| 25× | 3.80% | 6.62% | 4.33% | 68.30 | 142.64 |
| 50× | 1.90% | 4.85% | 2.75% | 50.18 | 111.23 |
| 100× | 0.95% | 3.15% | 1.77% | 11.83 | 80.27 |
| 250× | 0.38% | 2.97% | 0.49% | 5.25 | 11.89 |
| 1,000× | 0.0950% | 2.97% | 0.42% | 4.72 | 2.24 |
| 10,000× | 0.0095% | 2.96% | 0.42% | 1.70 | 1.49 |

The fits are complete even when their realized calibration is poor. In particular, a fitted narrow corridor cannot eliminate the mandatory survivors created by a flat oracle. The 1,000× and 10,000× targets imply fewer than twenty expected test wins per asset at the requested probability; those samples cannot validate rare-event pricing. Serial dependence further reduces the evidence.

| Asset | Evaluated test paths | Zero-motion paths | Zero-motion survival floor at full availability |
| --- | ---: | ---: | ---: |
| ETH | 13,709 | 406 | 2.96% |
| HYPE | 13,710 | 57 | 0.42% |

Every positive-width corridor survives an actually zero-motion path. The report deliberately distinguishes that product-level fact from additional survivors at the research one-ppm minimum; the shipped engine uses finer ppb quantization. Per-date optimistic retention bounds are saved in each asset's `feasibility.csv`. They grant perfect foresight and are necessary constraints, not causal admission policies.

All compared variants keep quotes open on feature-supported entries. The test counts above include only clean, healthy outcomes; each asset has 14,400 total test-grid entries. The full CSVs retain grid, pre-entry prediction and scored-outcome denominators, including thin groups. Eligible quote availability is 100% by construction and is not capture uptime or a guarantee of executable live quotes.

A 5% input target is not a measured house edge. `metrics.csv` also reports `1 − multiplier × realized survival` for an equal-stake historical batch before costs. It does not simulate trader selection, concurrent correlated liabilities, arbitrary entry times, reserve fees, capital flows or net LP returns. Those economics and fresh paired-receiver validation remain open.

## Artifacts and verification

Completed archive: `.local/adaptive-corridor/20261028-ETH-HYPE-raw-fits-v2`.

- `protocol.json`, `source/`, `dataset.json`, and `rows.jsonl.gz` bind the declared experiment, code and asset-labeled paths.
- `ETH/` and `HYPE/` each contain `models.json`, `legacy-models.json`, `selection.json`, `predictions.jsonl.gz`, `metrics.csv`, `feasibility.csv`, and `research.json`.
- `audit.json` reconciles original raw hashes/CRCs, training cutoffs, independent target-scale estimates, every saved exact barrier outcome, CSV populations/survival/mean-width/gross arithmetic, finite retention bounds, validation selection and complete frozen-model test replays.

The initial `...-v1` attempt stopped after ETH model fitting because a CSV writer call omitted its required field list. Its partial artifacts and `abandoned.json` are retained. The corrected `...-v2` reruns both assets without changing pricing rules, targets, date splits or selection; its end-to-end export regression test passes.

The focused suite covers asset separation, raw hash rejection, missing-feed censorship, strict touch loss, training maturity, payout targets, assembled-pipeline causality and complete model/CSV export. The corrected full Python regression suite passed 345 tests with three existing skips; the focused suite passes five tests. No existing pricing implementation was modified.

Reproduce with a new output directory after retaining or re-fetching the pinned public source data:

```sh
python3 -B scripts/research_asset_corridors.py --declare \
  --downloads .local/market-history/tardis-hyperliquid-ETH-HYPE-monthly-raw-v1 \
  --output .local/adaptive-corridor/NEW-ASSET-FITS
python3 -B scripts/research_asset_corridors.py \
  --downloads .local/market-history/tardis-hyperliquid-ETH-HYPE-monthly-raw-v1 \
  --output .local/adaptive-corridor/NEW-ASSET-FITS
python3 -B scripts/audit_asset_corridors.py --research .local/adaptive-corridor/NEW-ASSET-FITS
python3 -B -m unittest discover -s scripts -p test_asset_corridors.py
```

Sources: [provider coverage and first-of-month samples](https://docs.tardis.dev/historical-data-details/hyperliquid), [raw slices, receipt timestamps and disconnect markers](https://docs.tardis.dev/api/http-api-reference), [Hyperliquid oracle construction](https://hyperliquid.gitbook.io/hyperliquid-docs/hypercore/oracle).
