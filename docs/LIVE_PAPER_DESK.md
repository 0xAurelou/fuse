# Live paper desk

The Degen desk can now trade **live BTC, HYPE and ETH HyperCore oraclePx** with virtual USDC. It uses the existing deterministic Go reducer and two independently reconnecting collectors, not browser-simulated prices or outcomes. The default trade layout remains available through the top-right switch.

## Run locally

Start the dedicated paper backend (port 8091, separate from the contract backend on 8080):

```sh
./scripts/paper-desk.sh
```

Configure `frontend/.env.local`:

```dotenv
FUSE_ENGINE_URL=http://127.0.0.1:8091
FUSE_PAPER_DESK=true
```

Then run `npm run dev` from `frontend/`, restarting an existing preview after changing these variables. Open [Degen](http://127.0.0.1:3100/trade?mode=degen), choose **Start paper · $1,000**, and select each asset's stake and payout from 2×, 5×, 10×, 25×, 50×, 100×, 250×, 1,000× and 10,000×. **Send it** enters one market; **Enter all 3** submits three independent entries concurrently. Stakes, price observations, barriers, clocks and results remain separate; all draw from the same paper balance and combined risk limits. A single market can reject while another accepts. Inputs remain locked for uncertain entries; retries retain the original terms and idempotency key.

The chart is a rolling buffer of polled live canonical prices and fills after opening the desk. It is presentation data, not settlement evidence. The server continues processing oracle observations while the page is hidden or disconnected. `LIVE` requires both asset-specific receivers to agree and be fresh; `SYNCING` or `OFFLINE` disables new entries. Existing stages follow the configured gap/refund policy. No feed is replaced with a fixture when the connection drops.

## Paper funds and account lifetime

- A new browser account receives exactly **1,000 virtual USDC** once. Resuming it does not mint another grant. A 256-bit account secret stays in tab-scoped session storage; it is not put in URLs or the engine journal. Reopening another tab creates another paper account. Reloading the same tab resumes its balance and stage history.
- The server issues a 24-hour paper session with read/quote/trade scopes. It has **no withdrawal scope**. There is no wallet prompt, deposit, onchain transaction or real USDC funding.
- The dedicated ephemeral engine seeds **1,000,000 virtual USDC** of LP capital. Automatic paper settlement funds resolved winnings through the ordinary accounting reducer. Equity, available funds, stakes in play and realized P&L are authoritative account values, not mock totals. History displays actual returned amounts: payout for a win, zero for a loss, original stake for a void.
- Restarting this `-memory` engine resets all virtual balances, history and sessions. The tab secret can then start the same account identity with a fresh grant in the new simulation. This mode provides no crash durability.
- `-paper-desk` requires a literal loopback IP, `-memory`, paper policy and an oracle URL. It cannot be enabled against the local-contract execution mode. The old signed wallet flow and its endpoints retain their existing behavior when this opt-in mode is disabled.

## API

`POST /v1/paper/session` accepts `{ "secret": "<64 lowercase hex characters>" }` and returns the account, token, grant and expiry. The idempotent deposit/ack journal keys ensure a single grant per account. Custom grant amounts and extra body fields reject.

`POST /v1/paper/entries` accepts `{ "asset": "HYPE", "amount": 10000000, "multiplier": 25 }`, a paper bearer token and an `Idempotency-Key`. Quote and acceptance execute under one sequencer lock, using the same admitted oracle state; no price update can intervene. They remain two replayable journal records. Retries return the original receipt without another stake debit, including after resolution. A reused key with changed terms rejects. API refusal leaves the ordinary engine's balance, risk, capacity and feed checks intact.

`GET /v1/markets` additionally reports `paper_desk`. Public market data comes through the documented [coin-specific activeAssetCtx subscriptions](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/websocket/subscriptions), using [WebSocket heartbeats](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/websocket/timeouts-and-heartbeats).

The formula still uses **uncalibrated** 30-second volatility assumptions (BTC 0.10%, ETH 0.15%, HYPE 0.30%, target edge 5%). Live prices do not validate these assumed probabilities. See [Barrier pricing](BARRIER_PRICING.md).

## Visual direction

The supplied Papertrade screenshot is a style reference: navy trading chrome, pastel accents, art behind the chart, compact order controls, and a positions/history region. The follow-up direction adds more anime characters, cats, spinning and nightclub energy. FUSE keeps three independent double-no-touch markets rather than copying long/short margin trading. Original [nightclub art, DJ cat and generation prompts](../frontend/public/art/README.md) supply the three chart backgrounds and rotating mascot. The background gently moves and changes saturation; price lines, barrier labels and clocks remain separate data layers. **DJ ON** pauses club animation; system reduced-motion preferences disable it automatically. No sound autoplays.

The Floor wall and in-flow Nova 2D stage have been replaced by a [Three.js + VRM VTuber companion](../frontend/public/characters/victoria/README.md), fixed to the screen's bottom-right. Its existing CC0 model has real skinned geometry, face morphs and spring bones; a POKEDANCE-inspired pointing loop, bigger accepted-position dance, distinct victory cheer and loss gesture, pointer-following head movement, dark violet clothing, lavender hair and headphones provide the current presentation. The avatar passes clicks through to the desk; small controls handle pause, minimize/restore and credits. DJ pause and system reduced-motion handling apply. No webcam or microphone is used. The earlier Nova source/export remains archived; PixiJS is no longer an app dependency. The frontend observes authoritative accepted receipts and newly survived/exploded stages for reactions, skipping old history and duplicate updates. The backend and financial command semantics are unchanged.
