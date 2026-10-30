# Historical data and adaptive regime iteration — 27 October 2026

The subsequent [pump calibration and stability iteration](ADAPTIVE_STABILITY_RESEARCH.md)
improves pump calibration and native transfer with phase-specific scales and a
bounded causal correction. Its remaining flat-heavy period failure keeps new
capture work on hold. The data acquisition and earlier comparisons below remain
as their original research record.

Additional pump/dump information was found and downloaded without paid access.
The research now retains both exchange-price proxies and directly relevant,
third-party recorded Hyperliquid oracle observations. These source roles remain
separate from the original native paired-receiver captures.

No live policy changed, no candidate was promoted and no new capture started.

## Data retained

* **Hyperliquid oracle history:** all 24 free first-of-month BTC sample days from
  November 2024 through October 2026, from Tardis. The 16.4 MB compressed archive
  contains **1,228,677 normalized observations**. The provider's archived public
  normalizer maps `oraclePx` to CSV `index_price`. No mark/trade price is
  substituted. The source, normalization code, coverage metadata, URLs and local
  SHA-256 hashes are retained in
  `.local/market-history/tardis-hyperliquid-BTC-monthly-samples-v1/`.
* **Exchange proxy:** a complete August 2024 Binance BTCUSDT spot month with
  **2,678,400 one-second candles**, downloaded and checked against its published
  SHA-256 checksum. The 80.0 MB compressed archive is retained in
  `.local/market-history/binance-spot-BTCUSDT-1s-2024-08/`. Outcome paths include
  every one-second high/low, not just closes. This is trade-price development
  data, not oracle validation.

The Tardis samples are 24 individual days, not continuous history over two years.
The normalizer emits on changes to tracked fields and may carry an unchanged
index value into another snapshot. Its files lack native receiver identities,
disagreement evidence and an authenticated completeness guarantee. Gzip CRCs
and locally pinned hashes detect retained-file corruption/change; they are not
published provider checksum attestations. First-of-month selection also has bias.

Of 69,120 historical oracle grid windows, 61,395 pass the single-stream eight-second
freshness screen and **43,002** also have clean preceding five-minute histories.
That is 62.2% of the complete sampled grid. Missing normalized rows do not prove
a receiver outage, and the resulting eligible sample may be selective. No gap is
interpolated and history resets at each sampled day. This screen does not
replicate the native two-receiver admission policy.

Sources: [Tardis coverage/free samples](https://docs.tardis.dev/historical-data-details/hyperliquid),
[normalization mapping](https://github.com/tardis-dev/tardis-node/blob/master/src/mappers/hyperliquid.ts),
[Binance archive format/checksums](https://github.com/binance/binance-public-data),
[Hyperliquid oracle construction](https://hyperliquid.gitbook.io/hyperliquid-docs/hypercore/oracle).
The official Hyperliquid requester-pays S3 archive was investigated; anonymous
access returned 403 and no billed access was attempted.

## Directional evidence

At entry, pump/dump requires an absolute preceding five-minute log return of
at least **20 bps** and absolute return divided by square-root realized
log-return variation of at least **1.5**. The return sign chooses pump or dump.
Range requires an absolute return at most 5 bps and ratio at most 0.5; other
histories are mixed. Only preceding prices determine these labels.

The oracle samples contain **1,915 pump windows and 2,023 dump windows**. Merging
overlapping five-minute lookback plus 30-second outcome contexts within each
direction gives **458 pump and 477 dump clusters** across the chronological
slices. These clusters are descriptive, not statistically independent samples;
opposite-direction contexts can overlap. The definition differs from the earlier
efficiency ≥0.6 taxonomy, so these counts are not an expansion under an identical
label. Episode spans and denominators are retained in the generated CSVs.

## Formula comparisons

The models compare a fitted constant width, a global five-minute volatility scale,
a fitted fast/slow volatility mixture with optional nonnegative trend/jump terms,
and separate range/pump/dump/mixed volatility scales shrunk toward the global
scale. All inputs precede entry. Accepted barriers remain fixed for 30 seconds.
Structural searches and scale fitting use training data only.

For oracle history, the first 14 sampled days train, the next five validate, and
the final five (June–October 2026) provide final retrospective diagnostics.
The target is still the **legacy 48% reference experiment**.

| Model | Final oracle sample-day survival | Final exchange-proxy survival |
| --- | ---: | ---: |
| Fitted constant | 58.64% | 70.54% |
| Five-minute volatility | 52.45% | 49.94% |
| Fast/slow volatility mixture | 51.23% | 48.69% |
| Regime-specific volatility scales | 52.09% | 49.37% |

The two columns are different processes, training sets and diagnostic horizons:
10,672 eligible oracle windows across five sample days versus 20,160 exchange
windows in August's final seven days. Do not pool them. Within each column, every
model uses the same eligible windows. Quantile loss and width tails are retained,
not only survival percentages.

The oracle mixture fit is approximately
`width_ppm = ceil(0.9277852643 * max(1, 0.5*vol60 + 0.5*vol300))`, clamped to the
explicit offline research range. Extra linear trend/jump weights were zero.
The regime model's dump scale was approximately 1.0322 versus the global 0.9056,
about **14% wider for the same five-minute volatility**. This direction-specific
effect cannot be represented by a single global scale.

In the final oracle slice, separate regime calibration changed dump survival
from **41.62% to 50.54%** (370 windows), while pump survival changed only from
**40.05% to 40.78%** (412 windows). These are correlated, selected historical
groups, not established future probabilities. An acceptable overall rate can
still conceal a pump-specific miss.

## Transfer to native recordings

Both original captures passed their existing frozen-artifact and native
hash-chain checks. Historical models were replayed without refitting on native
capture outcomes. On the same clean-history rows, the historical fast/slow fit
survived **39.12%** in the first recording (859 windows) and **44.41%** in round 2
(752 windows). It therefore does not establish a stable successor to the prior
prototype. Different source collection/normalization and market conditions remain
possible contributors; this research does not identify a single causal explanation.

The data support further regime-aware development, especially distinct dump
calibration. They do not support choosing a successor from the best retrospective
cell. Remaining work includes pump-specific errors, calibration drift, robustness
across chronological periods and fresh reliable native observations. The payout
product needs multiplier-specific `(1-h)/M` targets and economics, not a universal
48% probability.

## Reproduction and artifacts

```sh
# Public free sample downloads; use a new directory.
PYTHONDONTWRITEBYTECODE=1 python3 scripts/fetch_regime_history.py \
  --output /absolute/path/to/new-sample-download

PYTHONDONTWRITEBYTECODE=1 python3 scripts/research_oracle_history.py \
  --samples .local/market-history/tardis-hyperliquid-BTC-monthly-samples-v1 \
  --captures .local/prospective-runs/20261026-117ppm-8h \
             .local/prospective-runs/20261026-round2-314ppm-8h \
  --output /absolute/path/to/new-oracle-research

PYTHONDONTWRITEBYTECODE=1 python3 scripts/research_market_regimes.py \
  --archive .local/market-history/binance-spot-BTCUSDT-1s-2024-08/BTCUSDT-1s-2024-08.zip \
  --output /absolute/path/to/new-exchange-proxy-research
```

Retained reports, pre-scoring protocols, exact source snapshots, model coefficients,
source hashes, episode spans and per-window predictions:

* `.local/adaptive-corridor/20261027-oracle-history-v1/`
* `.local/adaptive-corridor/20261027-historical-v1/`

Validation: **114 Python tests passed, with three existing optional skips**.
New tests cover millisecond/microsecond archive formats, high/low wick inclusion,
future-price isolation, missing-history rejection, episode clustering, checksum
validation, chronological fitting, and never substituting mark prices for oracle
values. The original artifacts and earlier research snapshots remain unchanged.
