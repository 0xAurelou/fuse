# Degen desk

For a running three-market test with live oracle prices, virtual accounts and the illustrated after-hours theme, see [Live paper desk](LIVE_PAPER_DESK.md).

The default desk retains one BTC chart on the left and one trading ticket on the right. The top-right **DEGEN** switch opens BTC, HYPE and ETH side by side. Each has its own stake, payout dropdown limited to 2×, 5×, 10×, 25×, 50×, 100×, 250×, 1,000× and 10,000×, quoted barriers and 30-second chart countdown. Switching layouts preserves mounted tickets and active stages. The URL (`/trade?mode=degen`) and tab preference remember the layout. Narrow screens scroll the three cards horizontally.

These are three independent entries, not a combined/parlay contract. A user can hold one active or pending stage **per asset**. Each requires its own quote and acceptance; a breach, outage or expiry in one market must not resolve the others. The optional paper desk's **Enter all 3** button submits three independent entries, with per-market acceptance or rejection. The positions table and total stake exposure include all markets, even while the default desk hides two cards. Correlated market moves can lose every stake.

## Backend and shared risk

- `POST /v1/quotes` accepts optional `asset` (`BTC`, `HYPE`, `ETH`); omitted means BTC for compatibility. Entry still sends only the immutable quote ID. Quotes for different assets can coexist.
- `GET /v1/markets` returns each enabled asset's oracle, health, model and server time. `GET /v1/oracle?asset=HYPE` selects one market; omission retains BTC.
- `policy.model` remains BTC. Optional `policy.markets.ETH` and `.HYPE` hold separately versioned models. Disabled/unknown assets reject quotes. An asset with outstanding stages cannot be disabled.
- The collector subscribes to each enabled coin's `activeAssetCtx` on both receivers, using the [documented coin-specific subscription](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/websocket/subscriptions). It maintains separate canonical sequence, source agreement, gap history and oracle commitment per asset. Only that asset's admitted `oraclePx` observations determine its outcome.
- Account balance, funded/unfunded components, per-account risk budget and LP underwriting capacity remain shared. Admission rechecks them serially at acceptance. Three concurrent quotes cannot spend the same money three times; combined liabilities must fit capital. Payouts sum only if every separate stage survives.
- Aggregate contract settlement retains the existing ABI. Its oracle evidence commitment includes all observed markets. Optional JSON fields and BTC defaults preserve historical journal encodings. Existing journals require their original policy; new `markets-v5` configs require a fresh database or an explicit versioned policy update.

## Pricing assumptions

All assets use the formula in [Barrier pricing](BARRIER_PRICING.md). Each uses its own entry price and volatility assumption. Shipped paper/local models assume 30-second relative volatility of BTC **0.10%**, ETH **0.15%**, HYPE **0.30%**, with a **5% target edge**. These are uncalibrated research inputs, not measured probabilities. Each asset needs its own prospective oracle validation, including correlated aggregate LP losses.

## Preview and local development

Without `FUSE_ENGINE_URL`, the app explicitly shows demo traces and independent presentation timers; it moves no funds and invents no wins. With an enabled engine, missing or unhealthy assets remain unavailable rather than borrowing another asset's feed. An older BTC-only gateway can continue serving the default desk.

The deterministic local server seeds BTC at 100,000, ETH at 3,000 and HYPE at 40 (or restores their journaled prices), and refreshes each enabled fixture. Operator-only `POST /local/oracle` accepts `{ "asset": "HYPE", "price": "41" }`; omitted asset remains BTC. `/local/advance` advances all enabled fixtures while its `price` field controls BTC. These are explicit synthetic test prices. Live simulation uses the external collector instead.

Tests cover independent outcomes and outages, shared spending/risk limits, cross-asset quote retention, three-market HTTP and dual-source collection, deterministic replay, and real local contract settlement of concurrent positions.
