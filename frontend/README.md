# FUSE 100 single-stage terminal

Next.js App Router, React and TypeScript. The landing page and `/trade` offer one 30-second BTC double-no-touch stage with any whole-number total payout from **2× through 100×**, selected through a dropdown. The chart is on the left and the trading ticket is on the right; narrow mobile layouts stack the chart first. The countdown and progress bar live directly on the chart. Payout includes the original stake: $10 at 100× pays $1,000 total, or $990 profit. Higher payouts have narrower corridors.

```sh
cd /Volumes/dev/fuse/frontend
npm install
npm run dev
```

Open [the terminal](http://127.0.0.1:3100). The top-right **DEGEN** switch opens [three independent BTC, HYPE and ETH tickets](../docs/DEGEN_MODE.md), each with its own payout dropdown and chart countdown. Mode switching preserves active tickets; the positions table totals every open stake. The denser terminal uses flat panels, restrained asset colors and compact controls. By default it is a labeled design preview: exact integer stake/payout previews, illustrative corridors, and independent presentation timers. It never fabricates an accepted trade, win or financial balance. Public Data, Liquidity and FUSE screens retain labeled demonstration fixtures.

## Connect to the Go engine

For live BTC/HYPE/ETH prices with 1,000 virtual USDC, use the [live paper desk](../docs/LIVE_PAPER_DESK.md): start `./scripts/paper-desk.sh` from the repo root and set `FUSE_ENGINE_URL=http://127.0.0.1:8091` plus `FUSE_PAPER_DESK=true` in `.env.local`. Restart the frontend. The paper desk needs no wallet; it supports individual entries, Enter all 3, account equity and actual results history. Its tab account resumes on refresh, while restarting the ephemeral engine resets the simulation. The navy illustrated Degen theme uses [original raster artwork](public/art/README.md). The wallet integration below remains available when `FUSE_PAPER_DESK` is unset.

The Degen desk includes a [Three.js + VRM VTuber companion](public/characters/victoria/README.md), fixed to the bottom-right of the viewport. It has real skinned geometry, expression morphs, spring-bone hair, pointer-following head movement and a POKEDANCE-inspired pointing loop driven by arm IK. Accepted positions trigger a bigger dance, confirmed wins a whole-body victory cheer, and confirmed losses a short gesture. Wave is removed. Pause and minimize are available; the transparent canvas passes clicks through to the desk. The earlier Nova 2D rig remains archived and is no longer rendered. PixiJS has been removed from the app dependencies.

Start the paper or local engine using its documented funding/oracle setup and the new single-stage policy. Configure its challenge domain/allowed origin as `http://127.0.0.1:3100`. Then start the frontend:

```sh
FUSE_ENGINE_URL=http://127.0.0.1:8080 npm run dev
```

The server proxies only `/engine/v1/*` to the configured gateway's `/v1/*`; no admin endpoints or admin secrets are exposed. Set the same variable at build time for a production build. Changing between preview/engine modes requires restarting and, for a production build, rebuilding.

On the ticket, connect an injected Ethereum wallet and sign the gateway challenge. The scoped session remains in memory; wallet account/network changes clear it. Fund the account through the existing paper/local deposit and acknowledgment flow before trading. The terminal does not initiate deposits, withdrawals or chain transactions.

1. Choose stake and multiplier, then request a quote using `{amount, multiplier, asset}` (BTC may omit asset). Amount is exact USDC atomic units. No `previous` stage is sent. One wallet session and poll loop serve all three cards through `/v1/markets`; an older gateway falls back to BTC only. Missing markets remain unavailable.
2. Review the quoted barriers and total payout, then accept before expiry. Entry sends only its quote ID. Expired or rejected quotes require a fresh quote.
3. Acceptance locks the controls. The timer uses gateway time; only engine stage status determines survival, breach, pending resolution or refund. Polled chart samples are presentation data, never the settlement evidence.
4. Wins credit automatically. The next entry is a fresh independent stage; there is no rollover, early cash-out or post-win cashout button. Funded balances and unpaid winnings remain distinct in the backend. Withdrawal funding is a separate process.

An uncertain entry retains its original idempotency key and quote ID for retry, preventing a second debit or trade. Polling restores the most recent accepted stage after login. A browser refresh loses the in-memory session; reconnect to recover authoritative stage/account state.

Both shipped engine policies and preview corridors use the same **uncalibrated Brownian first-passage approximation**. Default 30-second relative volatilities are BTC 0.10%, ETH 0.15% and HYPE 0.30%, with a 5% target house edge. The model target is `(1 − edge) / payout`; it is not an empirically validated win probability. See [the formula, derivation and error bound](../docs/BARRIER_PRICING.md). The backend still disables public-chain execution. Historical ladder calibration cannot validate this new pricing.

## Validate

```sh
npm run typecheck
npm test
npm run build
```

Tests cover all 99 payout selections, exact USDC precision, invalid/unsafe inputs, formula-based corridors, cross-language reference vectors, filter/export consistency and the displayed solvency equation. Backend tests cover financial outcomes, funding and deterministic replay. The public analytics fixtures are separate from engine account/quote data and are explicitly labeled demo data.
