# FUSE Go engine

For live BTC/HYPE/ETH testing without wallets or real funds, run `./scripts/paper-desk.sh` from the repo root. The opt-in loopback-only [live paper desk](../docs/LIVE_PAPER_DESK.md) supplies 1,000 virtual USDC per tab account and automatic paper settlement on a separate backend port.

Go implementation of the [25 October 2026 engineering specification](../docs/GO_ENGINE_SPECIFICATION.md), alongside the existing Solidity contracts. The default server executes paper trading. A separate [local contract/backend stack](LOCAL_DEVELOPMENT.md) runs actual Anvil transactions, signed checkpoints, withdrawals, token claims and reserve redemptions with development-only wallets. Public-chain execution and real-money operation remain disabled.

Start the full local stack from the repository root with `./scripts/local-stack.sh up`; verify it with `./scripts/local-e2e.sh`. Run `./scripts/local-live-e2e.sh` for a fresh 250,000 USDC LP, 100 traders, and live HyperCore BBO plus oraclePx settlement evidence.

## Run

Go 1.24 or later and PostgreSQL 14 or later:

```sh
cd engine
go mod download
export DATABASE_URL='postgres://fuse:password@127.0.0.1:5432/fuse?sslmode=disable'
export FUSE_PAPER_ADMIN_TOKEN='<at least 32 random characters>'
go run ./cmd/fuse-engine -config config/paper.json
```

The database user needs schema-creation privileges for initial setup. Use a dedicated database and restricted application credentials. The server binds to `127.0.0.1:8080`. Configure TLS and rate limiting at the gateway before exposing a deployment. Session tokens belong in the Authorization header. Operational endpoints require the paper operator token; never embed that token in a browser application.

For an explicitly ephemeral demo use `-memory`. For live **paper** oracle observations add `-oracle wss://api.hyperliquid.xyz/ws`; this opens two independently reconnecting connections to the documented coin-specific `activeAssetCtx` subscriptions for all enabled markets. All accepted raw observations enter the journal. No oracle connection is required for historical simulation.

## Deterministic demo and replay

```sh
go run ./cmd/fuse-engine -commands testdata/paper-commands.jsonl > /tmp/fuse-journal.jsonl
go run ./cmd/fuse-engine -replay /tmp/fuse-journal.jsonl
```

The fixture simulates deposit, acknowledgement, a surviving 2× stage, automatic win credit, withdrawal lock, funding checkpoint and payment. The output journal contains 23 events. Replaying verifies every command, posting, notification, event hash and state hash. No HTTP server, database, or chain is used for this demo. Rejected commands abort offline input with a line number; exact retries produce no duplicate journal records. Policy changes are journaled with `policy_update` and a new unique version; changed pricing requires a new model version. Updates invalidate indicative quotes. Accepted stage terms stay fixed, and outage timings cannot change while any stage remains active or pending. Supply the original policy file for replay; changing even an uncalibrated model's metadata changes the state commitment and causes replay to fail.

## Paper protocol choices

`config/paper.json` is an explicit research fixture. Unsupported scheduling, admission, gap or operating modes fail startup. A deployment must never silently use these values as approved economics.

- Independent entry, one 30-second stage with a total payout multiplier from the nine presets: 2×, 5×, 10×, 25×, 50×, 100×, 250×, 1,000× and 10,000×; the observation window is `[accepted_at, expiry)`. Exact barrier touches fail. Local command time cannot regress.
- Both receivers must report the same selected asset’s `oraclePx` within the configured freshness bound before admission. Admission time is the sequencer's local receipt time of the confirming message. Distinct prices increment the canonical sequence; repeated prices refresh receiver health without creating another price observation. Raw messages from both receivers remain journaled. The cryptographic journal uses SHA-256; contract EIP-712 and reward commitments use Ethereum Keccak-256.
- A disagreement blocks entry immediately. An existing stage becomes pending after the explicit disagreement grace or freshness limit. An unhealthy feed at expiry also makes the stage pending. Pending stages never resume survival eligibility: a valid, paired breach before expiry can still establish a loss; otherwise the configured delay leads to a refund. Recovery snapshots never establish survival across a recorded gap. Previously established losses remain losses.
- The feed has no authenticated exchange event clock in this implementation. An update confirmed after expiry does not count retrospectively. This local admission convention is a paper policy that needs approval and validation before launch.
- Single-stage policies use `product: "single-stage-v1"` and versioned `model.dnt` assumptions. `brownian-first-mode-v1` computes corridor width from payout, 30-second relative volatility and target house edge; higher payouts narrow it and higher volatility widens it. Defaults are research assumptions of 0.10% 30-second volatility and 5% target edge, not empirical probabilities. See [the formula and bounds](../docs/BARRIER_PRICING.md). Historical width-table policies still replay; stale/unhealthy inputs or unsafe corridors reject quotes.
- `payout = stake * multiplier` exactly in integer USDC units; payout includes the stake. A 10-USDC stake at 100× pays 1,000 USDC total on success. Survival automatically credits funded/unfunded balance components and releases the account's stage lock. One active or pending stage per account per asset is supported; shared balances and combined risk limits apply across BTC, ETH and HYPE. Every re-entry is a fresh quote and underwriting decision; `previous` is rejected.
- A void restores the stake's exact funded and unfunded components and clears the stage lock. A breach forfeits the stake. Withdrawals retain their existing funding and account-lock rules.
- Product-less policies retain the eight-stage payout table only for historical replay/research. `testdata/legacy-ladder-policy.json` preserves the original fixture. Always open an existing journal with its original policy; a versioned `policy_update` is required to change products. Accepted stages resolve using their accepted product and terms. Never start a new policy against an old database or relabel historical ladder results as single-stage validation.

The [upstream subscription](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/websocket/subscriptions) and [heartbeat](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/websocket/timeouts-and-heartbeats) formats informed the collector. Their messages do not prove feed completeness.

## Accounting and durability

`internal/engine` is a pure reducer plus a mutex-protected sequencer. It clones the proposed state, advances time, validates the command and every financial invariant, and only then atomically appends to storage. Clients receive acceptance after commit. An uncertain database commit fences the process until restart/replay; it never resumes writing based on an assumption that the commit failed.

The PostgreSQL adapter holds a session advisory lock on a dedicated connection. It also increments a durable leadership generation and checks generation, sequence and prior hash inside each transaction. It never reconnects that writer connection automatically. A second writer cannot acquire leadership. A standby must obtain the lock and replay before serving writes.

Each transaction writes the append-only event, double-entry postings, latest materialized state and account outbox together. SQL triggers reject journal, posting and outbox updates/deletes. The application owns no broker or cache that can create money. Startup verifies the snapshot and replays the complete authoritative journal. This favors validation over fast startup; snapshot-assisted replay and retention need further scale work.

USDC is an integer in six-decimal atomic units; oracle prices use six-decimal fixed-point units. Intermediate multiplication uses `math/big`, with explicit int64 aggregate safety envelopes. FUSE manifests use uint256-sized decimal strings in 18-decimal token units. Postings use positive debits and negative credits. LP risk reservations are balanced in a separate memo asset, so reservations cannot be confused with custody assets.

Accounts distinguish available funded money, available unfunded claims, held-run earned components, locked stage components, withdrawal components, pending deposits and cumulative paid value. Economic balance is never labeled as a funded withdrawal ticket. Pending deposits remain refundable and untradable until the explicit paper acknowledgement; refund and acknowledgement exclude each other.

Worst-case risk is additive across all potentially correlated stages. Each active stage reserves its entire payout less **only its physically funded stake**; already earned unfunded claims and withdrawal queues are reserved separately. Independent re-entry removes any spent unfunded claim before reserving the new maximum obligation; unpaid winnings are never physical custody cash. Unsettled customer losses and redemption reserves provide no underwriting capacity.

Paper checkpoints transfer simulated net PnL, fund all existing debt and retain required LP capital. Their journal hash commits the event range ending immediately before the checkpoint command; the checkpoint event itself is included in the next range. They are explicitly marked `paper-confirmed` and are not Solidity settlement reports. Withdrawal requests lock the entitlement immediately. Only one request per account is allowed until its funded paper payment; there is no unsafe expiry-unlock or redirect path. The sample operator payment is a simulator command, not an onchain authorization.

## HTTP API

| Method and path | Behavior |
| --- | --- |
| `POST /v1/auth/challenge` | `{account}` → single-use domain-bound EIP-191 challenge, 60-second expiry |
| `POST /v1/auth/verify` | `{id,signature}` → 30-minute scoped bearer session |
| `DELETE /v1/session` | Revoke current session |
| `GET /v1/oracle` | Canonical oracle, receiver health and explicit model/policy |
| `GET /v1/account` | Funding-aware balance breakdown and state sequence |
| `GET /v1/stages` | Account's complete stage terms and outcomes, including selected multiplier and immutable quote terms |
| `GET /v1/withdrawals` | Account's locked/funded/paid paper withdrawal records |
| `POST /v1/quotes` | `{amount,multiplier,asset?}` → quote for one stage; multiplier must be one of 2, 5, 10, 25, 50, 100, 250, 1000 or 10000 |
| `POST /v1/stages` | `{id: quote_id}` → durable acceptance receipt |
| `POST /v1/cashout` | Historical ladder-only cashout; single-stage wins are credited automatically |
| `POST /v1/withdrawals` | `{amount}` → lock an available economic entitlement |
| `GET /v1/events?after=N` | Private, sequenced catch-up page and next global cursor |
| `GET /v1/ws?after=N` | At-least-once private event delivery; resume with the returned cursor |
| `GET /healthz` | Storage-fence readiness; oracle health is separate |
| `GET /metrics` | Operator-authenticated integrity/risk/oracle metrics |
| `GET /admin/journal?after=N` | Operator-authenticated complete journal pages for audit/export |
| `POST /admin/commands` | Operator-authenticated paper funding/oracle/checkpoint/payment controls |

Use `Authorization: Bearer <session>` for account endpoints. Quote, enter, cashout and withdrawal require an `Idempotency-Key` of at most 100 bytes. The gateway binds commands to the authenticated account. Reusing a key with different terms rejects; exact retries return the original receipt even after later state changes. Server sequence is also state version. A catch-up page scans up to 500 global events, hides other accounts' payloads, and advances the cursor over filtered events. Deduplicate by sequence on the client. WebSocket bearer headers work with SDK clients; a browser gateway would need a reviewed cookie/subprotocol authentication flow. No query-string session token is accepted.

Sessions are deliberately in memory and restart revokes all of them. The current challenge verifier supports EOA personal signatures. ERC-1271 session authentication, distributed gateway session storage, broader anti-abuse controls and browser session transport remain integration work.

Paper operator commands use a unique `admin/` key and `kind` from `policy_update` (the complete new policy in `raw`), `lp_fund`, `deposit`, `ack_deposit`, `refund_deposit`, `oracle`, `tick`, `pause`, `resume`, `paper_settle`, `paper_pay`. Amounts are atomic units. Deposit `actor` is a normalized beneficiary wallet; operator authorization does not grant any live-chain capability. HTTP always assigns receipt time; use offline command files for historical timestamps. Periodic ticks resolve stages even when no clients are connected. Periodic paper settlement is manual through the operator command, so its timing can be controlled in experiments.

## Contract compatibility and incentives

The contracts emit `DepositCredited`, not the specification's illustrative `DepositAcknowledged`. The shared encoding adapter matches the repository's full EIP-712 structs, including global `signatureVersion`. Shared golden vectors are checked by both Go and the **actual Solidity implementations** in `test/EngineEncodingVectors.t.sol`. Reward leaves double-hash ABI encoding and use OpenZeppelin-compatible complete sorted-pair Merkle trees.

Create a manifest only from a reviewed deployment:

```sh
# From the repository root; addresses.json maps every module name to a deployed address.
forge build --offline
python3 scripts/export_engine_manifest.py --addresses /path/to/addresses.json \
  --chain-id 998 --confirmations 20 --output /path/to/deployment.json
cd engine
go run ./cmd/fuse-contracts -manifest /path/to/deployment.json
# Optional read-only check of RPC chain ID and presence of deployed code:
go run ./cmd/fuse-contracts -manifest /path/to/deployment.json -rpc "$HYPEREVM_RPC_URL"
```

The confirmation count is an example command argument, not an approved finality policy. Manifest checks pin **complete compiled artifact bytes** and require module addresses/versions and actual events. Code presence is not bytecode equivalence, wiring verification or deployment approval. The read-only indexer decodes pinned ABIs, orders/deduplicates logs, waits for confirmations, checks canonical hashes before and after reads, and halts on a finalized reorganization. A financial consumer must persist each projected block with its cursor atomically. The paper server has no financial chain consumer; the separate local stack projects confirmed blocks atomically into its local ledger. The local ledger credits deposits only after finalized onchain acknowledgement; public-chain trading is unavailable.

The signing interface requires external infrastructure. `CheckedSign` refuses an unavailable signer or mismatch with an independently obtained onchain digest. The paper adapter does not implement submission; the separate local controller adds guarded signing, durable broadcast and receipt reconciliation for development. No production signer/private key exists; the separate guarded local adapter uses explicit public development keys.

Compile a paper reward manifest from a replay-verified journal:

```sh
go run ./cmd/fuse-rewards -journal /tmp/fuse-journal.jsonl \
  -policy config/paper-rewards.json -from 1 -to 22 -epoch 1 \
  -budget 1000000000000000000 -cap 1000000000000000000 \
  -remaining-allocation 1000000000000000000 \
  -chain-id 998 -distributor 0x1111111111111111111111111111111111111111
```

This address is solely an encoding fixture. Supply independently observed emission caps and remaining allocation for a manifest review. After epoch one, `-previous` requires a sequential, nonoverlapping previous manifest. The default v2 mining policy scores linear stake × actual at-risk duration × outcome weight (1.0/0.2), with no streak bonus or wallet cap. Earlier final outcomes cannot be rewarded again through later funding notices. Voids and order submissions score zero. The activity rate is an explicit research input (100 FUSE per one-USDC/30s survival-weight equivalent), not an approved economic rate. Used budget is bounded by the requested/scheduled capacity and activity eligibility. Manifests commit total score, policy and per-stage evidence. Integer dust stays unallocated; this CLI never publishes or claims tokens.

Local reserve planning mirrors the v2 historical-HWM recovery gate, SR allocation ramp, ceil-rounded consumed profit and 2× required-capital floor. `GET /v1/tokenomics` exposes supply, escrow, emission, capital and exact rational backing disclosures from the confirmed chain cursor. `secondary_market_bid` stays null without an observed venue.

## Checks

```sh
cd engine
go test -race ./...
go vet ./...
# Once per fresh isolated test database (the test creates immutable financial records):
FUSE_TEST_DATABASE_URL='postgres://.../fuse_engine_test?sslmode=disable' go test -race ./internal/storage -count=1
cd ..
forge fmt --check
forge test --offline
```

CI runs the Go race suite against a fresh PostgreSQL service and the Solidity suite. Tests cover all nine preset payouts and automatic credit, touches and expiry, oracle gaps, ambiguous expiry, established breaches, unpaid-win re-entry, historical ladder replay, correlated exposure, concurrent retries, refundable deposits, locked withdrawals, funding, duplicate payments, replay, database rollback, recovery and leadership exclusion; API tests cover signatures, revocation, account isolation, cursor catch-up and WebSocket origin checks. Contract tests cover actual EIP-712 and leaf compatibility, finality waits, duplicate logs and finalized-reorg halts. These tests do not satisfy the specification's deployed testnet acceptance journey or its p99/load objectives.

## Delivery boundary

| Milestone | State |
| --- | --- |
| M0 compatibility freeze | Compiled-artifact exporter, read-only validator/indexer and independently checked encodings provided. Reviewed deployment, signer ownership, finality and launch policy freeze remain required. |
| M1 deterministic paper engine | Implemented: journal/sequencer, ledger/risk, oracle collector, explicit research pricing, state machine, PostgreSQL fencing, HTTP/private WebSocket delivery, offline replay and simulator journey. Scale/recovery drills remain to be measured. |
| M2 contract integration | Implemented and E2E-tested on local Anvil: confirmed block projection, ordered signed settlements, durable prepared-transaction recovery, vault reconciliation and funded cumulative withdrawals. Public HyperEVM integration and production transaction replacement/signing remain disabled. |
| M3 incentives/reserve | Local E2E covers bounded reward publication/claims, dual-signed reserve funding, redemption snapshots, burns and USDC payments. Public-network economics and operational activation remain unapproved. |
| M4 production | Disabled. Needs calibration, full load tests, operational controls, independent security review, approved limits and incident/recovery drills. |

V0 remains operator trusted. A journal root commits accounting; it does not prove correct outcomes. No operator-independent forced exit, production readiness, audited security, or real-fund authorization is claimed.

Optional durable fixed-USDC recovery limits, the research-only
`config/paper-recovery.json`, and the multi-day `fuse-capture` recorder are described
in [Risk and capture](../docs/RISK_AND_CAPTURE.md). Recovery pauses restrict new
risk while preserving funding/payment of accepted obligations. These controls do
not approve a real-money launch; see [release gates](../docs/PRODUCTION_READINESS.md).

## Optional Degen desk

The [Degen mode specification](../docs/DEGEN_MODE.md) defines three independent BTC, HYPE and ETH tickets. `/v1/markets` exposes enabled models and feeds; `/v1/oracle?asset=HYPE` selects one feed. `policy.markets` contains additional asset models. Quotes omit `asset` for backward-compatible BTC. Paper/local configs use versioned `markets-v5` policies; do not open existing databases with a different initial policy. ETH/HYPE volatility assumptions remain uncalibrated. The collector subscribes to all configured markets, while accounting and contract settlement aggregate obligations.
