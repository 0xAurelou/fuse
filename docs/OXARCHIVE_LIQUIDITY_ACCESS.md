# 0xArchive ETH/HYPE free-tier access — 29 October 2026

The public catalogue lists native Hyperliquid ETH order books from 15 April
2023 and HYPE order books from 5 December 2024. These start dates do not prove
uninterrupted coverage, recent cadence, or suitability for corridor labels.

Authenticated access now works with the locally supplied API key. The sample
probe completed 16 historical requests: two one-hour windows on a completed
weekday and two on a completed weekend day, for both assets and both native
books and oracle contexts. No subscription, billing credential, upgrade or paid
export was created by this workflow.

| Asset | Native book observations in four hours | Typical book spacing | Oracle context observations | Typical oracle spacing |
| --- | ---: | --- | ---: | --- |
| ETH | 2,673 | 5.39–5.40 seconds | 237 | 60.60–60.72 seconds |
| HYPE | 2,680 | 5.39–5.40 seconds | 237 | 60.60–60.72 seconds |

The sample includes an ETH book gap of 46.05 seconds. HYPE's largest gap in these
four hours is 5.999 seconds. Only about 16.4% of the sample entry grid has a
strictly prior oracle context at most eight seconds old. The oracle cadence gate
fails for both assets; these minute-sampled contexts cannot establish
thirty-second oracle path extrema or flat-path wins.

The completed probe, raw pages, request IDs, credit headers and original source
snapshot are retained in `.local/market-history/0xarchive-ETH-HYPE-probe-v1`.
The earlier unauthenticated request remains in the access evidence directory;
its HTTP 401 is historical evidence, not the current access status.

Public evidence is retained in
`.local/market-history/0xarchive-ETH-HYPE-access-v1`: the complete symbol catalogue,
the two selected symbol records, and the unauthenticated response. The catalogue
contained 39,931 rows; the decoded source SHA-256 was
`27dce95a79484dd4f0ee102a0191a8478c78150077a4e6b816c65ab878b13b8c`.

## Key setup and first pull

Sign in at <https://0xarchive.io/signup> and create the Free-tier key. Free
advertises no card requirement, rolling 30-day history and 50,000 API credits.
Keep the key out of chat and source control. The prepared probe reads
`OXARCHIVE_API_KEY` from its environment, or the single assignment
`OXARCHIVE_API_KEY=your_key` in
`/Volumes/dev/fuse/.local/secrets/oxarchive.env`. The secrets directory is ignored
by Git and was created with mode 0700. The key file is parsed, never executed.

```sh
python3 -B scripts/probe_oxarchive_liquidity.py --output .local/market-history/0xarchive-ETH-HYPE-probe-v1
```

This performs market-data GET requests only: no checkout, account changes,
upgrade, export purchase, or wallet signing. It samples 00:00 and 12:00 UTC on
the most recent completed weekday and weekend day, for both assets. Each sample
is one hour, with all pages requested until explicit pagination completion.
It separately pulls native venue books (20 requested levels) and raw open-interest
contexts containing the oracle field. It does not mix reconstructed node books
with venue books. Requests are sequential at at most two per second, capped at
80 calls and eight MB per response, with a 100-credit reserve when the provider
reports the remaining balance. The probe stops on HTTP errors and cursor loops.
Raw responses, hashes, query parameters, request IDs, credit headers and summaries
are retained; the authentication header is never archived or printed. Redirects
are rejected to prevent forwarding credentials.

## Suitability gate

[Native book documentation](https://docs.0xarchive.io/rest-api/order-books-l2)
describes venue snapshots about every five seconds. The
[OpenAPI contract](https://docs.0xarchive.io/openapi.json) describes raw core
open-interest updates approximately once a minute when `interval` is omitted.
The price-history route is a projection of this same context source; a different
route name does not supply a denser oracle path.

The probe measures actual timestamp gaps and the fraction of 30-second entries
with a strictly prior fresh source observation (five seconds for books, eight
seconds for oracle). Minute oracle observations are never interpolated or carried
forward into apparent flat 30-second paths. Dense timestamps are only a candidate
gate: this API does not supply original recorder receipt timestamps, and cadence
alone does not prove every oracle update was retained.

After successful authentication, inspect the sample and source quality before
expanding to consecutive full UTC days within Free's rolling window. Keep date
selection independent of outcomes and retain gaps. If oracle history is minute
sampled, consecutive books can support liquidity diagnostics, but repeating the
original 30-second win test requires a separate matching high-frequency oracle
archive. No new corridor result is claimed by this access probe.

Thirteen focused tests pass, covering pagination, sparse-oracle rejection,
strict entry timing, asset/source identity, calendar selection, credential and
budget handling, redirects, timestamp units, bounded gzip decoding, resumable
page hashes, duplicate boundaries, and calendar weighting. The existing
historical study and live collector were not modified.

## Consecutive native-book download

`fetch_oxarchive_liquidity.py` fixes every UTC day from 30 September through
27 October 2026, both assets, `source=venue`, and 20 requested levels. It caps
three workers, 3,000 requests per invocation, ten GiB of compressed retained
responses and a 1,000-credit reserve when the provider reports the balance.
Each response is bounded at eight MB in both encoded and decoded form. Requests
do not change the account or buy data. Missing data is recorded as gaps, never
interpolated. The first phase and its frozen sources are retained under
`source-before-gzip`; the transport-only restart requests gzip and reuses the
same hashed JSON pages, dates, source and metric definitions.

```sh
python3 -B scripts/fetch_oxarchive_liquidity.py --directory .local/market-history/0xarchive-ETH-HYPE-consecutive-v1
python3 -B scripts/check_oxarchive_liquidity.py --directory .local/market-history/0xarchive-ETH-HYPE-consecutive-v1
```

The check reconstructs every page's source timestamp, cursor chain, row count,
duplicate boundaries, source freshness grid and gap intervals from hashed raw
responses. It rechecks book price/depth validity at every page boundary; the
downloader validates every retained book. It independently recomputes every
spread and top-five/top-twenty notional mean in float arithmetic and reconciles
them to the downloader's Decimal-derived means within 1e-8 relative/absolute
tolerance. Calendar comparisons give each full
UTC day equal weight and describe observed snapshots only. They cannot identify
a causal liquidity effect or validate the original corridor win rates.

## Completed results

The full download and raw-data audit passed: **895,963 native book snapshots**,
931 retained gzip pages, 215,738,443 compressed bytes, every declared asset/date
present, and no failed requests in the completed manifest. Both assets have 28
consecutive UTC dates, comprising 20 weekdays and eight weekend dates. Every
retained snapshot has 20 actual levels on each side.

| Asset | Books | Pages | Largest source gap | Within-day entries with strictly prior source book at most five seconds old |
| --- | ---: | ---: | --- | ---: |
| ETH | 447,950 | 465 | 654.689 seconds | 92.56% |
| HYPE | 448,013 | 466 | 658.992 seconds | 92.57% |

The largest gaps occur on 7 October. There are 251 ETH and 250 HYPE daily gap
segments longer than ten seconds, with exact intervals retained per day. These
are gap segments, not a count of distinct exchange incidents. Consecutive dates
do not imply uninterrupted observations. Normal roughly 5.4-second snapshot
spacing itself leaves some entries outside the fixed five-second freshness rule.
The within-day grid excludes each day's first midnight entry, where this
day-local check does not bring forward the previous day's book.

The calendar comparison uses equal-weight daily means of observed snapshots.
Depth is USD notional on the smaller of the top-five bid and ask sides; it is
visible one-venue depth, not whole-market liquidity or a complete price-band
depth measure.

| Asset | Weekday spread, bps | Weekend spread, bps | Weekend change | Weekday top-five depth, USD | Weekend top-five depth, USD | Weekend change |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| ETH | 0.41653 | 0.41058 | -1.43% | 738,076 | 844,793 | +14.46% |
| HYPE | 0.23599 | 0.17845 | -24.38% | 13,823 | 13,109 | -5.17% |

This window does not support a blanket thin-weekend rule: ETH's observed
top-five depth is higher on weekends, HYPE's is modestly lower, and both assets'
average observed spreads are narrower. These are descriptive associations in
one 28-day window, with no causal or profitability claim. The observations do
not establish why earlier corridor wins occurred.

The provider coverage calls succeeded for both assets. Their returned bodies
report global history extents, no gaps and approximately one-second book
cadence, despite our bounded queries and the raw native-venue gaps above. Those
broader metadata summaries are retained as supplementary evidence and are not
used as proof that this specific native-venue window is complete. Their oracle
context cadence is reported as 61 seconds, consistent with the measured sample.

**The exact thirty-second oracle corridor test remains unavailable from this
source alone.** Matching high-frequency oracle history is still needed. The
minute context feed must not be filled forward into apparent flat winning paths.
No pricing formula, payout policy or live quoting behavior was changed.

Audit result: `.local/market-history/0xarchive-ETH-HYPE-consecutive-v1/checks.json`.
The protocol SHA-256 is
`8565bc4f46560d0074e8555fbcca2616591542d25472cdc118c5b781bf48a341`;
the completed download manifest SHA-256 is
`0d2a99132cca65b8e070ee29f7902fc5bb2d5b5e1a56a3ba0e097431728bfddd`.
Raw responses, cursor provenance, exact gap intervals, daily means, checker
source and provider quality responses are retained in the same dataset folder.

Sources: [Free tier](https://docs.0xarchive.io/core-concepts/free-tier),
[credits](https://docs.0xarchive.io/core-concepts/credits),
[authentication](https://docs.0xarchive.io/authentication).
