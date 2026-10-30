# Fresh ETH/HYPE liquidity collection

The dedicated ETH/HYPE recorder is running as a local user LaunchAgent. It collects public Hyperliquid perpetual-market data independently of the engine and existing BTC capture. It uses no account, keys or trading endpoint.

The fourteen-day background horizon supplies two weekends; it is **not a waiting period before analysis**. The incoming partial day and first few hours can support exploratory inspection. A full-day read supplies better intraday coverage. A weekend comparison requires observing a weekend, and neither a few hours nor two weekends guarantees enough independent evidence for rare 1,000× outcomes.

The separate [historical liquidity-effect study](HISTORICAL_LIQUIDITY_EFFECT_RESEARCH.md) downloads native twenty-level ETH/HYPE book history for 22 first-of-month days per asset and joins the existing oracle archive. It supplies an immediate historical test of measured liquidity beyond activity/calendar features. Those monthly samples complement this fresh consecutive recording; they are not consecutive weeks or an independent research holdout.

## Current run

- Directory: `.local/liquidity-captures/20261029-ETH-HYPE-14d-v1`.
- Recording started on 28 October 2026 UTC / 29 October WITA.
- Fourteen complete UTC days: **29 October–11 November**. The preceding partial UTC day is retained separately.
- Fixed deadline: **12 November 2026 00:00 UTC / 08:00 WITA**.
- Service: `dev.fuse.eth-hype-liquidity.20261028175345-21ac77`.
- Per-user service file: `/Users/aurelou/Library/LaunchAgents/dev.fuse.eth-hype-liquidity.20261028175345-21ac77.plist`.

The collector runs independently of this chat, reconnects with bounded backoff and resumes the same archive after a process failure or later login. The deadline does not move on restart. `caffeinate -i` inhibits idle sleep only while the job runs. **The Mac must remain awake and online, and this volume must remain mounted.** Closing the lid, shutting down, logging out or losing network can interrupt observation; resuming cannot recover the missing interval. There is no remote collector or promised uninterrupted coverage.

## Recorded evidence

Each asset has four [documented public subscriptions](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/websocket/subscriptions): `activeAssetCtx`, `l2Book`, `bbo` and `trades`. Both assets share one new WebSocket connection. It sends the [documented heartbeat](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/websocket/timeouts-and-heartbeats). The existing BTC sockets and frozen research packet are untouched.

Raw messages retain their original JSON text, local wall and monotonic receipt times, session IDs and exchange timestamps wherever supplied. Oracle context has no exchange timestamp. Approximate one-second feature samples retain:

- Oracle price, mark price, update/change/idle metrics and freshness.
- Spread in bps from the most recently received fresh BBO or native L2 snapshot.
- Bid/ask notional in the top 1, 5, 10 and 20 visible levels.
- Captured depth within 1/5/10/25/50 bps, separate per-side band coverage, and imbalance for fully covered bands.
- Observed trailing trade count and notional, with per-session identity deduplication, bootstrap exclusion and a transport-coverage flag.

The native book supplies **up to twenty levels per side**, not the entire book. The live smoke test observed roughly five-second full-book updates and much more frequent BBO changes. The collector retains actual timing rather than assuming a faster book. HYPE's visible book did not reach 5 bps in that smoke sample: its captured amount remains a lower bound, and its full-band depth/imbalance are null. Book freshness uses both receipt and exchange time; missing or stale depth is never encoded as zero liquidity. BBO silence alone does not trigger a reconnect because that stream publishes changes.

Connection gaps, clock/loop gaps, malformed messages, sessions and stops are explicit events. Reconnects reset feature state; no earlier book or price is carried across a gap. Initial trade batches are retained raw but excluded from rolling volume. All summaries use strictly earlier receipts. Future thirty-second outcomes are deliberately built offline, using oracle freshness throughout the outcome and book freshness at entry only.

Five-minute segments are hash-linked, compressed and indexed. The active `.open` segment is flushed and fsynced at least every five seconds. Interrupted partial tails are preserved under `recovery/`; complete corrupt records cause failure. A read-only verifier checks record order, hashes, segment bindings and a bounded live prefix. Segment folders identify opening date; use receipt timestamps when assigning UTC days.

Collection stops at the frozen deadline, a user stop, less than 5 GiB free disk or the 20 GiB capture budget. Storage stops are explicit and do not masquerade as a completed sample. The recorder, feature code, inspector, archive code and vendored WebSocket client/license are pinned in the collection plan.

## Analysis boundary

`collection-plan.json` freezes an associational hypothesis: whether measured pre-entry spread, visible depth and trade activity explain subsequent zero oracle movement beyond oracle activity/volatility, UTC hour and weekend. It identifies zero motion as primary, with excursion and one-ppm survival as secondary outcomes. The partial startup day is exploratory. The first seven complete UTC days are development; the final seven are reserved for chronological evaluation. Any fitted analysis must be frozen before inspecting the final evaluation outcomes.

The plan does not establish causality, independent thirty-second trials, multi-venue liquidity, canonical two-receiver settlement evidence, payout calibration or LP profitability. Daily coverage and day/episode dependence remain part of the eventual analysis. No pricing model is loaded into this recorder.

## Operations and verification

Run these from the workspace. Use the frozen scripts for this archive:

```sh
python3 -B .local/liquidity-captures/20261029-ETH-HYPE-14d-v1/source/collect_liquidity.py status --directory .local/liquidity-captures/20261029-ETH-HYPE-14d-v1
python3 -B .local/liquidity-captures/20261029-ETH-HYPE-14d-v1/source/collect_liquidity.py verify --directory .local/liquidity-captures/20261029-ETH-HYPE-14d-v1
python3 -B .local/liquidity-captures/20261029-ETH-HYPE-14d-v1/source/inspect_liquidity_capture.py --directory .local/liquidity-captures/20261029-ETH-HYPE-14d-v1
```

The status command recomputes heartbeat and saved-feed ages against the caller's clock; an old saved “recording” state is not proof of current health. `launchd.log` retains service errors. The quality inspector reports receipt integrity, channel counts, session/gap events and sampled freshness/coverage without examining forward price outcomes. It reports a prefix, not continuous-window coverage; retry if rotation races a read.

To stop this recorder deliberately, create its own stop marker:

```sh
touch .local/liquidity-captures/20261029-ETH-HYPE-14d-v1/STOP
```

The service then closes and archives its current segment. A successful stop does not automatically restart during the current login session. This does not stop any BTC or trading process.

The final ninety-second smoke capture is retained at `.local/liquidity-captures/20261029-ETH-HYPE-smoke-v2`; its 1,655 linked records verify, with all eight asset/channel combinations present. Eighteen focused tests cover features, stale boundaries, BBO/L2 separation, bootstrap/deduplication, crash recovery, tamper rejection, service scope, mocked transport and fatal storage errors. The full Python suite ran **421 tests, with three skips and all others passing**. The primary archive retains the final test log, startup quality/status, and unchanged BTC-process/deadline/frozen-file checks.
