> The default paper/local policies now use one stage with payout presets 2×, 5×, 10×, 25×, 50×, 100×, 250×, 1,000× and 10,000×. Any fixed-width/48%/ladder experiments below refer to historical research policies; they do not calibrate the new multiplier model. Existing databases must reopen with their frozen original policy before a versioned policy update, or use a new isolated database for a new policy.

# Local contracts + backend

This stack runs the actual compiled Solidity modules, a faucet USDC token, PostgreSQL, and the Go HTTP/WebSocket backend. It uses Anvil chain **31337** on loopback and well-known development wallets. Public-chain execution remains unavailable. The persistent development server and regression test use an explicit deterministic BTC price fixture. The separate live E2E below connects to HyperCore and settles against real `oraclePx`.

## Start, test, restart, stop

Prerequisites: Go 1.24+, Foundry (`forge`, `anvil`), Python 3, and PostgreSQL server binaries (`initdb`, `pg_ctl`, `psql`, `createdb`, normally found using `pg_config --bindir`). Run as your normal user, since PostgreSQL refuses to initialize as root.

From the repository root:

```sh
./scripts/local-stack.sh up
./scripts/local-stack.sh status
./scripts/local-stack.sh restart   # backend restart; chain/database stay running
./scripts/local-stack.sh down      # preserves development chain and database
./scripts/local-stack.sh up        # resumes the same local deployment
```

The default backend address is `http://127.0.0.1:8080`, Anvil tries port 8545, and PostgreSQL tries 55432. Occupied default ports are left untouched and replaced by available ports. Startup prints the actual URLs. Runtime files, database, logs, deployment manifest, and local executable live in `.local/`, which is gitignored. `runtime.json` is owner-readable and contains the generated operator token and connection details.

To verify the complete journey independently:

```sh
./scripts/local-e2e.sh
```

This creates fresh services on free ports, deploys the real contracts, runs the Go race-enabled E2E test, and stops its services afterward. The test covers:

- Refundable deposits stay untradable; timed-out refunds cannot become trading funds.
- Wallet challenge/session authentication, indicative quote, durable stage acceptance, and retry deduplication.
- A surviving 30-second 2× stage, automatic win credit, LP-loss funding, account-level withdrawal lock, a signed cumulative ticket, user-submitted payment, and rejection of replayed payment.
- A barrier breach, customer-loss transfer into LP, and real vault/ledger reconciliation.
- A bounded FUSE reward epoch, Merkle claim, token transfer, dual-signed reserve contribution, snapshot redemption, token burn, and USDC payment.
- Signer rotation and ticket expiration/reissue preserve the same locked cumulative entitlement.
- A durable signed transaction prepared before a simulated crash is recovered after PostgreSQL journal replay and broadcast exactly once.
- A finalized chain reorganization halts new exposure and preserves the existing journal and claims.
- USDC conservation across customer wallets, custody, LP, reserve and the faucet treasury.

A local time-control endpoint feeds paired observations at bounded intervals while advancing the persisted engine clock and Anvil time. This makes the 30-second and expiry scenarios reproducible without waiting in real time. The stage duration and contract deadlines are unchanged.

## Live HyperCore E2E: 100 traders and 250,000 USDC LP

```sh
./scripts/local-live-e2e.sh --traders 100 --seed 20261025
```

This is an independent fresh deployment with **250,000 faucet USDC** in the LP. The default is 100 client wallets; `--traders` supports 2–300 wallets (indices 5–304). Above 100, seeded per-run profit budgets scale inversely with population to preserve the original aggregate risk scale. An existing development stack stays running. The seed makes strategy profiles reproducible; live market outcomes still vary. The runner uses wall time for 30-second stages and stops its own services afterward. Chain, PostgreSQL data, deployed artifacts and evidence remain under `.local/live-runs/<timestamp>/`.

For a prospective target check, first produce a research candidate with `python3 scripts/calibrate_pricing.py`, then freeze it **before** the next run:

```sh
./scripts/local-live-e2e.sh --traders 300 --seed 20261026 \
  --config .local/pricing-calibration/policy.json \
  --calibration .local/pricing-calibration/calibration.json \
  --capture-seconds 600 --cohort-size 100 \
  --cohort-interval-seconds 180 --control-every 2
```

This starts three 100-wallet entry cohorts at 0/180/360 seconds. Half use the exact frozen candidate width, across all five strategies; the rest vary width. Price capture continues for at least ten minutes even if games finish earlier. Larger captures can use `--capture-seconds` up to 3600; wallet sessions refresh before later entries and final withdrawals. Allow additional time for setup, final claims and replay. Increasing wallets stresses integration; it does not add independent BTC price paths.

The runner copies the candidate policy and calibration into `frozen-policy.json` and `frozen-calibration.json`, pins their SHA-256 hashes and training journal hashes in `experiment.json`, and predeclares timing, population, target 48% ±5 percentage points, 400 nonoverlapping windows, 90% eligible-window coverage and a 2% maximum void fraction. Stale candidates are rejected before deployment. It validates actual accepted widths and policy, chronology, real contract reconciliation, reward claims, burns, conservation and exact replay. Disagreements exceeding the committed timeout invalidate calibration windows, even when paired receipts are less than eight seconds apart.

At larger populations, clients submit at most eight entries per scheduler pass so outcomes, settlements and risk logging remain serviced. Queue delay is logged separately from the 60-second quote-admissibility retry timeout, which starts at the first actual request. Accepted prices and stage times always come from the current server clock; the two-second quote TTL is unchanged. Identical current width policies are reused. The reducer sorts stage IDs once per event, preserving existing notice ordering and replay commitments. Analysis reconstructs LP equity and open exposure from every journal posting/notice, in addition to sampled risk logs.

Reconciliation batches every account's cumulative withdrawal read at the same confirmed block, checking response counts and IDs even when reordered. Idle syncs verify the chain without mining new empty history; new chain activity still receives the configured confirmations. A transport timeout/EOF makes quote/stage admission and health return 503 until a successful sync. Existing claims remain recorded. A confirmed reorg or accounting mismatch still causes a permanent journaled halt. The local RPC client allows up to 60 seconds per request; the live simulator retries transient failures only for idempotent keyed actions or cached withdrawal authorizations. The deterministic E2E injects an RPC outage and verifies recovery before exercising the permanent reorg halt.

`evidence/prospective-validation.md` and `.json` report separate integration and pricing decisions, cohort and stage-index outcomes, LP PnL, reserve backing, claim counts and feed health. A short run can pass integration while pricing remains insufficient or misses the target. Wilson intervals are descriptive: nonoverlap does not remove serial dependence. No result enables public execution or establishes organic demand. Preserve a candidate unchanged for forward validation; after refitting, use a new experiment and future data.

To recheck a retained frozen experiment:

```sh
python3 scripts/validate_pricing.py \
  --experiment "$RUN/../experiment.json" --run "$RUN"
```

Accumulate longer observation across separately frozen runs of the **same** candidate without refitting. The validator requires identical policy/calibration hashes and gates, rejects duplicate journals and purges overlapping windows:

```sh
python3 scripts/validate_pricing.py --run "$RUN_A" "$RUN_B" "$RUN_C" \
  --output .local/pricing-validation/combined
```

Four hundred 30-second windows require at least 200 minutes of eligible price history; more wallets cannot shorten that requirement. Captures across different regimes are still needed beyond this descriptive gate. Every included run must independently pass the integration and feed-health checks.

Internet access to `wss://api.hyperliquid.xyz/ws` is required. Two connections subscribe to BTC `activeAssetCtx`; one also subscribes to `bbo`, following the [HyperCore schema](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/websocket/subscriptions). Only paired `oraclePx` observations adjudicate barriers. BBO is evidence with exchange/receipt times, bid/ask prices and sizes. Both receivers share one upstream. A feed failure follows the explicit disagreement/gap/refund policy and never substitutes fixture prices.

With the default single-stage policy, seeded profiles choose among 2×, 5×, 10×, 25×, 50× and 100×, all with target stage count 1. Widths are calculated from the selected multiplier and the policy's Brownian model and are never retuned per trader. Seeded stake/risk budgets, entry waves and repeat-entry delays remain deterministic. The profile strategies span low/balanced/high multiplier preferences, delayed entry and independent re-entry. All-win liabilities are bounded before the experiment.

Legacy policies still generate the earlier eight-stage, varied-width/early-cashout/ladder/risk-aware experiments. Their fixed-width controls and 48% calibration tools explicitly remain historical research; the runner rejects those fixed-width controls for the new single-stage product.

Stakes include cents and fractional USDC, and depend on seeded risk budgets rather than observed outcomes. All wallets start with 1,000 test USDC; deposits include varied idle balances. Each client authenticates and submits actual deposits, quotes, stages and withdrawals. The runner checks that deposits are unspendable before the signed contract acknowledgement. Every accepted quote retains its immutable policy/model version and selected multiplier. Widths remain deliberate **untrained experiment inputs**, not calibrated fair prices.

Settlements execute every 15 seconds while positions remain open and again at the end. Their EIP-712 digests, checkpoint roots, contiguous sequence ranges, capital requirements, vault balances and cumulative withdrawals are verified against the deployed contracts. Single-stage winners are credited automatically; legacy ladder experiments retain historical cashout commands; final claims are actually paid and replayed payment attempts must fail. Reward allocations are claimed. Profit-backed reserve funding and token burn/redemption occur only when the observed path produces distributable realized LP profit, with a recorded skip otherwise. The separate deterministic E2E always exercises both financial directions.

The runner checks zero final exposure, fully paid customer custody, USDC supply conservation and exact PostgreSQL replay. It also updates the repository data analysis with `scripts/analyze_papertrade.py`.

The evidence directory contains:

- `report.md`: readable per-trader stakes, stage counts, withdrawals and trading PnL.
- `profiles.json`: the complete seeded strategy/size/timing plan for every wallet.
- `settlements.json` and `settlements.md`: onchain checkpoint digests, roots, sequence ranges, transaction hashes, capital requirements and net custody/LP transfers.
- `summary.json`: totals, outcomes, market message counts, supply conservation and replay result. USDC integers use six decimal places; FUSE integers use eighteen.
- `events.jsonl`: timestamped raw BBO/oracle evidence, deposit actions, entries, outcomes, risk snapshots, withdrawals and reward/redemption actions. No session tokens or private keys.
- `journal.jsonl`: the complete ordered, hash-linked ledger, double-entry postings, prepared transaction hashes, and decoded/raw canonical contract evidence.
- `final-state.json`: accounts, positions, capital, policy history, chain operations, rewards and claims, including partial state if a run fails.

For example, point `RUN` at the printed evidence directory:

```sh
jq -c 'select(.kind == "stage_entered" or .kind == "stage_outcome" or .kind == "risk_snapshot" or .kind == "withdrawal_paid")' "$RUN/events.jsonl"
jq -c 'select(.kind == "market_bbo") | {received_at, bbo: .data.raw.data}' "$RUN/events.jsonl"
jq '{passed, outcomes, initial_lp_usdc_units, final_lp_usdc_units, exposure_usdc_units, postgres_replay_verified, traders}' "$RUN/summary.json"
```

## HyperEVM settlement compatibility and coverage limits

```sh
./scripts/local-hyperevm-e2e.sh
python3 scripts/analyze_papertrade.py
```

The fork runner reads the official [HyperEVM testnet RPC](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/hyperevm), verifies chain 998, pins a source block/hash, and starts a **local Anvil chain 31337** with Cancun rules. It deploys the real contracts locally and runs the race-enabled contract/backend recovery suite: deposits, positive/negative settlements, withdrawals, rewards, reserve funding, token burn/redemption, signature rotation/expiry, restart recovery and local reorg halt. Source details, result and transcript are retained in `.local/fork-runs/<timestamp>/`.

No transaction is submitted to public HyperEVM. A fork test checks local EVM execution against a HyperEVM state snapshot; it does not test HyperBFT inclusion/finality, public RPC write behavior, public governance configuration, or settlement against a public deployment. The development adapter still refuses public chain IDs 998/999. Signatures attest operator accounting; contracts do not independently verify oracle paths or offchain liabilities.

The analysis utility reads completed live runs and the deterministic paper fixture. It independently checks barrier outcomes against paired oracle receipt observations, journal continuity, customer/LP PnL and USDC conservation, and reports per-width outcomes and scenario diversity. Its report is `.local/papertrade-analysis/report.md`. Short correlated experiments do not validate fair pricing or production readiness.

## Deposit → trade → withdraw through the running backend

The stack seeds LP with 1,000,000 test USDC and each trader with 1,000 test USDC. Alice uses development wallet index 5; Bob uses 6. Their public test keys are the scalar values 5 and 6, padded to 32 bytes; use these only with this local fixture. Transactions made by the wallet CLI are signed by the client, while settlement/risk/withdrawal authorizations use separate development authorities.

Load the selected URLs and local credentials into your shell:

```sh
RPC=$(python3 -c 'import json; print(json.load(open(".local/runtime.json"))["rpc_url"])')
API=$(python3 -c 'import json; print(json.load(open(".local/runtime.json"))["http_url"])')
ADMIN=$(python3 -c 'import json; print(json.load(open(".local/runtime.json"))["admin_token"])')
BIN="$PWD/.local/fuse-local"
MANIFEST="$PWD/.local/deployment.json"

"$BIN" wallet -rpc "$RPC" -manifest "$MANIFEST" -wallet 5 -action balances
"$BIN" wallet -rpc "$RPC" -manifest "$MANIFEST" -wallet 5 -action login -api "$API" > .local/session.json
SESSION=$(python3 -c 'import json; print(json.load(open(".local/session.json"))["token"])')

# Deposit 100 test USDC onchain. It remains pending until acknowledgement.
"$BIN" wallet -rpc "$RPC" -manifest "$MANIFEST" -wallet 5 -action deposit -amount 100000000
curl -fsS -X POST "$API/local/sync" -H "Authorization: Bearer $ADMIN"
curl -fsS -X POST "$API/local/checkpoints" -H "Authorization: Bearer $ADMIN" \
  -H 'Idempotency-Key: walkthrough-deposit'

# Request and accept a 10-USDC stage with a 2× total payout.
curl -fsS "$API/v1/quotes" -H "Authorization: Bearer $SESSION" \
  -H 'Idempotency-Key: walkthrough-quote' -H 'Content-Type: application/json' \
  -d '{"amount":10000000,"multiplier":2}' > .local/quote.json
QUOTE=$(python3 -c 'import json; print(json.load(open(".local/quote.json"))["result"]["id"])')
curl -fsS "$API/v1/stages" -H "Authorization: Bearer $SESSION" \
  -H 'Idempotency-Key: walkthrough-entry' -H 'Content-Type: application/json' \
  -d "{\"id\":\"$QUOTE\"}" > .local/stage.json
STAGE=$(python3 -c 'import json; print(json.load(open(".local/stage.json"))["result"]["id"])')

# Survive using the explicit constant-price fixture; the payout credits automatically.
curl -fsS "$API/local/advance" -H "Authorization: Bearer $ADMIN" \
  -H 'Content-Type: application/json' -d '{"seconds":31,"price":"100000"}'


# Lock 20 USDC. Authorization first funds a signed checkpoint if necessary.
curl -fsS "$API/v1/withdrawals" -H "Authorization: Bearer $SESSION" \
  -H 'Idempotency-Key: walkthrough-withdrawal' -H 'Content-Type: application/json' \
  -d '{"amount":20000000}' > .local/withdrawal.json
WITHDRAWAL=$(python3 -c 'import json; print(json.load(open(".local/withdrawal.json"))["result"]["id"])')
curl -fsS -X POST "$API/v1/withdrawals/$WITHDRAWAL/authorization" \
  -H "Authorization: Bearer $SESSION" > .local/ticket.json
"$BIN" wallet -rpc "$RPC" -manifest "$MANIFEST" -wallet 5 \
  -action claim-withdrawal -ticket .local/ticket.json
curl -fsS -X POST "$API/local/sync" -H "Authorization: Bearer $ADMIN"
curl -fsS "$API/v1/account" -H "Authorization: Bearer $SESSION"
```

Use fresh idempotency keys for a new walkthrough/run; an exact retry returns the original receipt. Quote lifetime is two seconds, so accept a fresh quote if typing manually. Changing the local oracle to a barrier-touching/crossing price before expiry produces a loss; a later unrelated price does not invalidate a completed successful stage. Each independent re-entry supplies `amount` and `multiplier` in a fresh quote. `previous` is rejected under the default single-stage policy.

## Incentives and reserve

The test suite exercises the full token flow. For manual experiments, after finalized stage outcomes:

| Endpoint | Authorization and input |
| --- | --- |
| `POST /local/rewards` | Operator + idempotency key, `{"budget":"1000000000000000000000"}` in FUSE base units |
| `GET /v1/rewards` | Trader session; returns that trader's committed allocation and proof |
| `POST /local/reserve` | Operator + key, `{"amount":2000000}` in USDC base units; requires realized LP profit and remaining solvency |
| `POST /local/redemptions` | Operator + key, `{"duration":60,"penalty_bps":1000}`; opens a fixed-snapshot epoch starting two chain seconds later |
| `GET /v1/redemptions` | Trader session; observed burns, accrued USDC and paid USDC |
| `POST /local/oracle` | Operator, `{"price":"101000"}`; paired local observation used by the stage state machine |
| `POST /local/advance` | Operator, `{"seconds":31,"price":"100000"}`; explicit synthetic observations and clock advancement |
| `POST /local/sync` | Operator; confirm/index/reconcile current chain state and recover any pending transaction |
| `GET /local/state` | Operator; journaled operations, checkpoint and accounting diagnostics |
| `GET /local/deployment` | Local contract addresses and fixture wallet metadata |

Save `GET /v1/rewards` output to `.local/rewards.json`, then claim with:

```sh
"$BIN" wallet -rpc "$RPC" -manifest "$MANIFEST" -wallet 5 \
  -action claim-reward -rewards .local/rewards.json -epoch 1
"$BIN" wallet -rpc "$RPC" -manifest "$MANIFEST" -wallet 5 \
  -action redeem -amount 1000000000000000000000
"$BIN" wallet -rpc "$RPC" -manifest "$MANIFEST" -wallet 5 \
  -action claim-redemption -epoch 1
```

Redemption requires a funded/open epoch and time within its request window; payment begins after its end. Reserve funding is rejected unless realized LP profit covers the contribution under the actual contract allocation policy. Losing stages must first be settled; trader deposits alone do not qualify as LP profit. Every backend proposal is checked against contract-computed typed digests before development signing.

## Durability and failure behavior

Signed transaction bytes, logical operation ID, immutable report/manifest and transaction hash are journaled **before broadcast**. The sequencer excludes concurrent balance changes while a capital-moving operation is prepared/reconciled. After a crash or unknown submission result, the coordinator checks the same transaction hash and resends the same signed bytes if necessary. It does not allocate a new nonce for the same logical operation. A reverted receipt releases the operation gate without applying its proposed funding; successful accounting follows confirmed contract logs only.

Deposit acknowledgements and checkpoint funding apply atomically with their indexed block and durable cursor. Pending deposits remain protected. Withdrawals stay locked until an actual gateway payment; there is no automatic unlock on ticket expiry. Expired or rotated signatures can be replaced only after chain reconciliation, with unchanged cumulative history and a new authorization ID. Previous authorizations remain in the journal/history. The backend never signs third-party redirects in this local implementation.

Reconciliation checks custody/LP/reserve USDC, pending deposits, funded liabilities, LP accounted capital, realized profit/HWM, token supply and per-account cumulative withdrawals at the indexed block. A finalized cursor reorg or a financial mismatch records a durable halt; offchain `resume` cannot bypass it. Funded onchain tickets still follow the contract rules. There is no automatic rewriting of accepted claims after a finalized reorganization.

PostgreSQL stores exact encoded journal/snapshot bytes alongside JSONB query projections. This preserves nested raw-payload order and financial hashes across recovery. Existing journals written without encoded bytes fall back to their old projection and must pass full replay; any legacy normalization divergence fails closed.

## Local-only boundaries and configuration

`fuse-local` refuses non-loopback HTTP RPC URLs, DNS hostnames, redirects, proxies, a non-Anvil client, or a chain ID other than 31337. It checks the guard again before signing/broadcasting. The backend also refuses non-loopback listen addresses. `fuse-engine` remains the paper-only server; it cannot activate these development keys. There is no production/private-key configuration switch.

Local deployment uses the real immutable modules with a development EOA governor, distinct signing wallets, a 10-second deposit refund timeout, a one-second token transfer activation delay, and explicit emission/redemption fixtures. These are local test settings. The production timelock deployment script and protocol contracts are unchanged. The only new Solidity artifact is `script/LocalUSDC.sol`, whose constructor and mint function require chain 31337.

Configuration overrides:

- `FUSE_LOCAL_DIR`: separate runtime directory (default `.local`). Use a new directory for an independent fresh chain/database.
- `FUSE_LOCAL_RPC_PORT`, `FUSE_LOCAL_HTTP_PORT`, `FUSE_LOCAL_PG_PORT`: explicit ports; occupied explicit ports fail startup.
- `PGBIN`: PostgreSQL server binary directory.
- `GO_BINARY`: Go executable override.
- `FUSE_LOCAL_DATABASE_URL`: an existing isolated PostgreSQL database; the runner will not create/stop its server. E2E tests require an empty database.

This completes a local contract/backend integration. Public HyperEVM deployment, calibrated market pricing, production signing infrastructure, broader transaction replacement strategies, independent risk operations, scale targets and security review remain separate production work.

## LP participation

New local deployments include the equity share vault and LP incentive distributor, with participation Protocol-only and the campaign inactive. Operator endpoints `/local/lp/liquidity-window` and `/local/lp/capacity` support reconciled capital movements; the isolated E2E exercises an external deposit, realized profit and fee funding, a 48-hour request, fresh-NAV fulfillment and pull payout. `GET /v1/tokenomics` separates gross LP cash, usable equity, accrued fees and funded exits. See [LP participation](../docs/LP_PARTICIPATION.md) for signed schemas, governance activation and queue semantics. Existing pinned deployments require a fresh isolated deployment to exercise the new contracts; no in-place treasury migration is performed.
