FUSE 100 — Go Engine: Full Functional & Technical Specification
Document version: 1.1
Date: 26 October 2026
Status: Engineering specification for implementation; not authorization to operate with real funds
Implementation language: Go
Intended integration: HyperCore BTC, ETH and HYPE oracle WebSockets and HyperEVM FUSE smart contracts
Scope: Engine behavior, architecture, data ownership, money flows, risk, settlement, operational security, failure handling and acceptance criteria. No implementation code is included.
1. Purpose and product boundaries
FUSE 100 is a single-stage BTC double-no-touch derivative. A user chooses a USDC stake and a whole-number total payout multiplier M from 2 through 100. One accepted stage lasts 30 seconds and survives only when no admitted canonical HyperCore BTC oracle observation touches or crosses either barrier. Survival automatically credits P = S × M USDC atomic units, including the original stake S; profit is S × (M − 1). A breach forfeits the active stake. There is no eight-stage progression, rollover, early cash-out or required post-win cashout action. Higher multipliers require strictly narrower, independently calibrated corridors. The UI calls this a payout multiplier, not margin leverage.

The top-right Degen switch opens BTC, HYPE and ETH charts with independent stakes, nine-preset payout dropdowns (2×, 5×, 10×, 25×, 50×, 100×, 250×, 1,000× and 10,000×), quotes and chart countdowns. Stages can overlap across assets; they are separate contracts, not a parlay. Switching layouts must preserve open stages. See [Degen mode](DEGEN_MODE.md) for API, pricing, combined risk and compatibility details.

The opt-in loopback [live paper desk](LIVE_PAPER_DESK.md) adds browser-only virtual accounts, a one-time 1,000-USDC grant and atomic quote/acceptance entry for each asset. It uses live paired oracle observations and normal reducer outcomes. Enter all 3 submits three independent paper entries. Its sessions cannot withdraw, and its ephemeral engine resets on restart. The signed wallet and contract execution paths do not receive this faucet.

The Go engine is responsible for trading logic and accounting, not onchain execution of individual stages. HyperEVM contracts are responsible for actual USDC custody, LP capital, epoch settlement, withdrawals, FUSE token distributions and token-redemption reserves.

Fixed product decisions: one independent 30-second stage; payout selection restricted to 2×, 5×, 10×, 25×, 50×, 100×, 250×, 1,000× and 10,000×; automatic win credit; HyperCore oraclePx as the sole outcome reference; offchain execution; separate customer custody, LP capital and FUSE reserve on HyperEVM; accepted obligations must remain funded.

Not yet fixed: calibrated corridor for each multiplier and market regime (no shared 48% survival assumption); instant entry vs shared rounds; exact timestamp and gap adjudication policy; minimum stakes/rounding schedule; exact LP reserve-allocation policy; token emission decay; redemption penalty; independently enforceable operator-failure withdrawals. The software must support policy versioning and reject unsafe or unavailable configurations, rather than inventing production defaults.
2. Architecture and trust boundaries
2.1 Logical deployment
Operate a modular Go backend with one authoritative trading-state sequencer and independent supporting workers:
1. Client gateway: account authentication, session-authorized instructions, read APIs and user WebSocket delivery.
2. Oracle collector and sequencer: two independent HyperCore WebSocket connections, feed-health monitoring and a single deterministic canonical observation log.
3. Pricing and calibration module: versioned model produces barrier widths and the fully specified payoff for a requested stage.
4. Trading state machine: the only component allowed to accept trades, expire stages, release or replace risk reservations and finalize offchain balances.
5. LP risk manager: collateral sufficiency, portfolio exposure, concentration limits, circuit breakers and post-trade stress requirements.
6. Accounting ledger: immutable double-entry USDC and FUSE accrual records, plus physically funded/unfunded balance distinctions.
7. HyperEVM contract indexer: confirmed deposits, acknowledgements, refunds, LP funding, settlement epochs, withdrawals, reward events and redemption events.
8. Settlement coordinator: ordered epoch manifests, EIP-712 approval workflow, net USDC transfers and onchain transaction reconciliation.
9. Withdrawal coordinator: account balance locks, funded claim authorization and redemption of the customer's offchain entitlement into an onchain payment.
10. Reward processor: epoch mining scores, bounded emissions and distribution commitments.
11. Independent reconciler and monitoring: check internal liabilities against real vault assets; halt exposure creation when invariants break.
A single Go repository and PostgreSQL primary are sufficient for V0. Workers may run as separate processes, but there must never be two active writers of trading state. A standby can take over only after obtaining a durable leadership fence. A read cache or message broker is optional and never the source of truth for money.
2.2 Authority and guarantees
- HyperCore publishes the underlying oracle observations; it does not sign or guarantee FUSE outcomes.
- The Go engine determines accepted stages and resulting USDC entitlements according to its journaled rules.
- HyperEVM vaults physically hold USDC; an offchain balance does not itself move funds onchain.
- SettlementController records roots and performs authorized net settlement; a root proves commitment to state, not correctness of the trading computation.
- Independent risk authorization restricts capital-moving settlement operations, but is not a validity proof.
- Users retain wallet control over deposits and submitting authorized withdrawal claims. Under V0, new withdrawal authorizations still depend on the operator.
V0 is operator-trusted, not a rollup, even if Merkle roots are frequently published. No claim of trustless settlement or guaranteed operator-free exit is permitted until actually implemented and validated.
3. Account and independent-stage lifecycle
3.1 Accounts
Each account has independently tracked:
- Finalized, unspent USDC eligible for trading.
- USDC currently committed as an active stage stake.
- Earned, LP-backed but not yet onchain-funded USDC entitlements.
- Onchain-funded and withdrawal-eligible USDC.
- Pending withdrawal claims that can no longer be staked.
- Cumulative USDC already withdrawn onchain.
- Accrued, finalized and claimed FUSE rewards.
The UI may show a combined economic balance, but must not label unfunded winning entitlements as immediately withdrawable USDC.
3.2 Quotes and acceptance
A quote contains product `single-stage-v1`, asset, selected integer `multiplier`, stake, exact potential total payout, entry price reference, upper and lower oracle barriers, start/expiry convention, policy versions, quote lifetime and maximum LP liability. Quotes are indicative until durably accepted.

Acceptance occurs in one atomic transaction: authenticate user/session; deduplicate request; verify funds and quote validity; validate current oracle freshness; check pricing limits; reserve LP exposure; debit/lock trader stake; persist stage and accounting entries; append the authoritative event; and commit the result before notifying the client. If any condition fails, no partial financial state change is allowed.

The acceptance receipt identifies the full immutable contractual terms. An accepted stage cannot subsequently have its boundaries widened, payoff reduced or duration altered.
3.3 Stage outcomes
A stage can be active, survived, exploded or voided under a prepublished outage rule. On an admitted oracle observation at or below the lower barrier or at or above the upper barrier during the contractual observation window, the stage explodes. On expiry without an observed breach, and only when the feed meets the required completeness/health policy, the stage survives. No stage is resolved by reference to BBO, mark price or an arbitrary candle close.

Stage expiry, observation ordering and boundary inclusion must be frozen as a versioned protocol rule. The default proposed convention is that boundary touches count as failure and observations in the specified start-to-expiry interval count; handling an observation received after expiry that lacks trusted exchange event time remains a launch blocker.
3.4 Automatic credit and independent re-entry
On survival, return the stage's physically funded stake to available funded balance and credit P minus that funded amount as an unfunded LP-backed claim. Clear the active-stage lock. These two components total P and must not be presented as an already funded onchain withdrawal. Loss and void also clear the active-stage lock; a void restores the exact funded/unfunded stake components without awarding a payout or mining score.

The user may then request a fresh independent quote or withdrawal. A rejected next quote never changes a previously earned payout. One active or pending stage per account per asset is supported; combined account and LP risk limits remain shared. Re-entry may spend available funded balance and unpaid winnings, but replaces the spent unpaid claim with the new maximum obligation without treating that debt as physical money or reserving it twice.

`previous` is rejected for single-stage quotes. `/v1/cashout` is a historical ladder endpoint and rejects single-stage wins because credit has already occurred. Legacy product-less policies and their payout tables remain solely for deterministic historical journal/research replay. Resolution always follows the product in the accepted terms, even after a policy update.

4. Oracle ingestion and deterministic observation policy
4.1 Authoritative feed
Connect to each enabled asset's HyperCore activeAssetCtx WebSocket updates and read oraclePx. BTC remains the default; ETH and HYPE are optional versioned markets. Maintain independent canonical state and health per asset. The operator receives observations through at least two connections, records source messages and local receipt times, and selects one canonical ordered feed. Duplicated messages from redundant connections must not be treated as additional price updates.

HyperCore oracle updates are roughly every few seconds. The trading product is based on observed oracle states, not an invented continuous path between updates. The client chart may animate between updates for UX but must not imply interpolated prices affect settlement.
4.2 Time and ordering
The public WebSocket payload cannot be assumed to provide a unique authenticated source sequence and timestamp for every update. The engine's local sequence documents admission order, not proof that no earlier upstream message was missed. Consequently, the specification must publish a precise policy for admitting observations, defining stage start, evaluating barriers, closing stages and identifying ambiguous late arrivals. The selected policy is included in every accepted receipt.

Persist the raw payload, parsed integer price, receipt time, connection identity, canonical sequence, feed-health state and a cryptographic link to the event journal. Price comparisons use fixed-point integers, never floating-point comparison at the barriers.
4.3 Outage and recovery
On stale or disagreeing feeds: reject new quotes/entries; keep already accepted stages under an explicit pending or disputed state; attempt deterministic reconciliation; and use the announced void/refund or timeout policy if data completeness cannot be established. A post-reconnect snapshot cannot prove whether the price crossed a barrier during a missing interval. Do not simply award survival because no breach was observed during an outage. Do not retroactively erase a breach already established by valid data.
4.4 Historical calibration
Use collected HyperCore oracle observations as the definitive input when sufficient history is available. Binance and Reservoir can help develop models, but their trade-price or candle-based barrier frequencies are only proxies. Record dataset, model version, training window and out-of-sample error for each deployed pricing policy. No synthetic-study survival target may be silently treated as empirically validated.
5. Pricing engine
Production pricing must estimate first-passage survival probability for the canonical oracle observation process over the next 30 seconds. It must condition on current volatility regime, recent observations, selected payout multiplier, and any other proven out-of-sample predictor. It then produces symmetrical or explicitly permitted asymmetrical barriers and the fixed stage payout.

Payout arithmetic is exact: `payout = stake * multiplier`, with integers in USDC atomic units and a checked aggregate safety envelope. All 99 whole-number selections from 2 through 100 are supported; The UI uses a dropdown for all 99 integer payouts. For success probability q, expected gross return per staked unit is q × M. Thus a 100× payout breaks even at 1% success before costs; one survival target cannot price all multipliers.

The current paper/local implementation uses the versioned `model.dnt` rule `brownian-first-mode-v1`. For selected multiplier M, 30-second relative standard deviation v and target house edge h, compute `w ≈ pi*v / sqrt(8*ln(4*M/(pi*(1-h))))`, then `delta = floor(entry_price * floor(w*1e9) / 1e9)`. Lower/upper barriers are entry price minus/plus delta. Go and browser use matching fixed-point arithmetic. Quotes commit the assumptions and width; there is no empirical win-probability claim. Shipped assumptions v = 0.10% over 30 seconds and h = 5% remain research inputs. The full derivation, approximation bound, exact integer semantics and calibration limits are in [Barrier pricing](BARRIER_PRICING.md).

Higher multipliers narrow the formula corridor; higher volatility widens it. Reject stale/unhealthy inputs, zero/unrepresentable widths, unsafe maximum corridors and insufficient LP capacity. Historical `multiplier_widths_ppm` policies remain replayable; a model cannot enable both the formula and the historical table. Neither the old inverse-multiplier fixture nor historical 48% ladder calibration validates this formula on discrete oracle observations.

Legacy 48% fixed-payout and ladder calibration experiments are historical research only. They do not validate the preset payout product. Production pricing must establish multiplier-conditioned first-passage survival and LP economics across prospective regimes, including the attainable probabilities of discrete oracle observations.

6. LP risk and solvency
The LP is the counterparty to every stage. It earns forfeited active stakes and funds valid survival payouts. It cannot rely on future trader losses or future FUSE buyers to honor current accepted payouts.

For a standalone stage with locked stake S and promised payout P, incremental LP funding can begin at P minus the already locked and irrevocably usable S, only if the accounting model proves that S remains available for this payout. Existing accrued wins, other active positions, unfunded available claims, and pending withdrawals must each be counted correctly. In ambiguous cases use conservative gross obligations rather than netting customer money twice.

At acceptance, enforce:
- LP-owned, available onchain assets cover worst-case additional losses and the configured safety buffer.
- Accepted active-stage obligations and already earned payouts are both covered, without duplicate claims on the same USDC.
- Aggregate exposure limits by asset, round, payout multiplier, account and concentration remain satisfied.
- All capital movements are reflected in effective onchain available liquidity, not just a projected balance.
For V0, conservative additive maximum-loss limits are preferable. Outcome-aware netting can be introduced only for mutually exclusive winning sets that are formally verified. Correlated survivors in the same round must be treated as potentially winning together.

The independent risk process monitors utilization, drawdown, concentration, pricing drift, oracle health, settlement backlog and a high-water-mark profit policy. When a limit is breached, stop accepting new exposure while preserving existing claims.
7. Accounting and persistence
Use PostgreSQL transactions, an append-only journal and a double-entry ledger. A single-writer sequencer orders all relevant commands and oracle outcomes. Every monetary action creates balancing debit/credit movements in the correct asset unit.

Separate accounts for customer pending deposits, customer available trading funds, locked stakes, earned claims, withdrawal queues, LP equity, realized LP profit/loss, LP reserved capacity, net settlement clearing, FUSE accrual and reserve funding. USDC uses base units; FUSE uses token base units. Monetary and price calculations must be overflow-safe and deterministic.

Every command has an idempotency key, a stable event sequence, a state-version reference and a journal hash. Persist the event, ledger postings, reservation change, materialized account state and outgoing notification together. State snapshots accelerate recovery but the journal remains authoritative. A full replay must reproduce the same positions, customer balances, LP liabilities, epoch reports and final state hash.

Core invariants: no negative spendable customer balance; no duplicated stake debit; no double-paid withdrawal; no double-released LP collateral; no minting FUSE beyond the emission allocation; reserve USDC never used as LP collateral; reconciliation between customer liabilities and onchain assets holds at every reported checkpoint.
8. HyperEVM integration
8.1 Contract adapters
The engine must integrate with the final deployed contracts, while remaining decoupled from their precise Go bindings:
Contract	Engine responsibility
CustomerCustodyVault	Index deposits, acknowledgments and refunds; reconcile actual USDC held
LPVault	Read LP-funded assets, reconcile trading PnL transfers, control eligible reserve funding
SettlementController	Publish ordered state checkpoints and perform signed net settlements
WithdrawalGateway	Produce funded, account-bound cumulative withdrawal authorizations; reconcile claims
FUSEToken	Track actual supply, transferable state and burns
RewardDistributor	Publish/reconcile epoch allocations and claims
RedemptionReserve	Verify actual USDC contributions, redemption epochs and token burns


The previously drafted Solidity interfaces are preliminary sketches, not finalized deployed ABIs. Integration must use compiled ABI artifacts pinned to chain ID, contract address and version. Signing domains must match contract implementation exactly.
8.2 Deposits and refunds
A Deposited event enters a pending state after chain confirmation; it is not yet tradable if the contract permits refunding unacknowledged deposits. Only after a finalized onchain DepositAcknowledged event can the engine credit an available customer balance. A refunded receipt can never subsequently be credited. The engine must remain safe under duplicate events and reorganizations.
8.3 Epoch settlement
The coordinator periodically closes a consistent event-log range; computes user balances, earned liabilities, open-risk reservations, net trader PnL and journal/oracle commitments; and obtains distinct settlement and risk authorizations. It sends a transaction through the SettlementController that physically moves net USDC between LP and customer custody as required. The checkpoint is confirmed only after its event, state root and transfers reconcile with a canonical onchain receipt.

A positive net trader PnL means LP funds move to customer custody. A negative net PnL means realized customer losses move to the LP, subject to recognized stake ownership and reserve rules. Customer pending deposits are never LP revenue.

A sensible initial checkpoint target is approximately one minute, not a requirement to write one root for every stage. Checkpoint latency is not stage execution latency. The engine must handle pending transactions, replacements, unknown receipts, retries and reorgs without submitting the same logical settlement twice.
8.4 Withdrawal flow
Users request a withdrawal from eligible available value. The engine first removes that amount from tradable funds and creates a pending claim; it cannot be staked again. A claim is issued only after the required USDC is physically funded in CustomerCustodyVault and represented by an appropriate finalized account state/checkpoint.

The authorization identifies account, recipient, cumulative eligible amount, state version, expiration, unique authorization ID and account-state commitment. The gateway tracks cumulative paid value so submitting an old and a new authorization cannot extract the same funds twice. Concurrent tickets must share an account-level entitlement lock/queue. Expired claims are released only after the chain is reconciled and there is no possibility that a valid pending transaction can still pay.

A third-party recipient requires independent user authorization. Once signed, the user may submit an otherwise valid funded ticket directly or via a relayer. However, requesting a new ticket depends on the operator in V0.
9. FUSE mining, LP reserve and redemption integration
Mining scoring is calculated at completed, finalized stages, not on arbitrary order submissions. The initial proposed outcome weights are 1.0 for survived and 0.2 for failed. The scoring formula must normalize genuine economic risk, stake, exposure duration and selected payout risk; no streak bonus. Total issuance is capped by epoch budgets and the mining escrow; no FUSE minting is triggered by an individual trade.

Reward epochs are compiled from the immutable trading journal into publicly reconcilable allocations. The engine submits allocation roots to RewardDistributor, and clients claim tokens onchain. Token transfer restrictions and their activation are enforced by contracts, not client flags.

The engine calculates proposed reserve contributions based on realized LP profit, adjusted high-water marks and post-transfer solvency. The contracts independently restrict fund movement. Reserve funding physically transfers USDC from LPVault into RedemptionReserve; the same USDC cannot secure live trading payouts.

Redemptions occur onchain, preferably in fixed-snapshot epochs. Each epoch applies its published backing-per-token denominator and penalty uniformly, subject to rounding and supply controls. The denominator includes outstanding supply that may later become redeemable—including escrowed tokens under the agreed model—so future emissions cannot silently dilute the advertised backing. The Go backend reports observed redemption events but must not fabricate reserve balances or determine how much onchain USDC the contract owes.

The candidate 35% allocation cap, potential 50% ramp, 10% or 20% redemption penalty and declining emissions remain policy candidates. They are not security constants to hard-code into Go.
10. Client/API contract (behavioral specification)
`POST /v1/quotes` accepts `{ "amount": 10000000, "multiplier": 100 }` (amount is integer atomic USDC). Missing, fractional, out-of-range multipliers and any `previous` are rejected. `POST /v1/stages` accepts only the quote ID for its immutable terms; the selected multiplier cannot be overridden on entry. Both commands require account-scoped authentication and stable idempotency keys. A 10-USDC/100× receipt promises exactly 1,000 USDC total if it survives, subject to the accepted oracle policy.

`GET /v1/oracle` includes `server_time`, `multiplier_min`, `multiplier_max`, feed state and the versioned policy. `GET /v1/stages` includes the selected multiplier in each stage's `terms`; automatic outcomes arrive through the existing account/event interfaces. Clients use server time for quote expiry and show pending resolution when the timer ends. The browser never decides survival, refund, loss or financial credit. Historical `index`/`initial` fields remain for receipt compatibility; new independent stages use index 1 and initial equal to stake.

The public interface must allow:
- Wallet challenge and verification; scoped session creation, expiry and revocation.
- Per-asset oracle state, feed health, model version and relevant barrier parameters through /v1/markets (BTC remains the /v1/oracle default).
- Indicative quotes, with explicit expiration and prospective risk limitations.
- Stage entry, authoritative outcome query, automatic win credit and fresh independent entry.
- Complete stage history, selected multipliers and immutable accepted execution receipts.
- Transparent available, locked, pending, funded and withdrawn USDC breakdown.
- Withdrawal request, ticket/status lookup and chain confirmation tracking.
- FUSE mining accrual, epoch allocations and onchain claim status.
Client WebSockets deliver at-least-once sequenced updates and support cursor-based catch-up on reconnect. Messages include a durable server sequence and state version; clients deduplicate, rather than assuming exactly-once network delivery.

UX latency should not depend on the Ethereum transaction lifecycle: entering a Fuse is acknowledged immediately after the engine's durable internal acceptance. Its oracle chart changes only on canonical oracle observations, while countdowns, animations and local UI components may refresh smoothly. Display explicit transitions such as pending → accepted → survived/exploded → funded → withdrawable → paid onchain.
11. Operational security and failure behavior
Failure	Required response
HyperCore WS stale or ambiguous	Reject new stages, keep impacted positions pending; invoke documented gap resolution; never assume survival
Oracle receiver disagreement	Quarantine ambiguous updates, stop new entries and audit admission order
Engine process crash	Restart from durable journal/snapshot; deduplicate previously committed client commands
Multiple writers detected	Fence all but one writer; stop trade acceptance until leadership is verified
PostgreSQL unavailable	Fail closed for state-changing commands; do not acknowledge unstored trades
HyperEVM RPC outage	Trading may continue only while independently funded-risk limits remain reliable; stop new claims and reduce/stop new exposure when chain state is stale
Settlement tx pending/reorged	Preserve journal epoch; retry/reconcile idempotently; do not create a second logical settlement
LP capacity insufficient	Reject new entries; preserve all previously accepted and earned claims
Risk signature unavailable	No capital-moving epochs can be finalized; block affected withdrawals or new exposure according to limits
Withdrawal authorization expired	Reconcile chain before unlocking entitlement or issuing a replacement
Reward processor unavailable	Trading continues; rewards accumulate durably and publish later within emission limits
Operator disappears	Previously funded valid withdrawal claims may still execute; there is no guaranteed new forced exit in V0


Use external signing infrastructure (HSM/KMS or controlled signer), separated risk and settlement permissions, timelocked configuration changes, access logs, wallet/session scopes and documented operator key rotation. An emergency pause must not be treated as permission to confiscate outstanding customer claims.
12. Performance, availability and observability
Proposed nonbinding engineering objectives, subject to load testing:
Metric	Target to validate
Accepted command acknowledgment	p99 below 150 ms excluding external network RTT
Oracle-to-state-machine processing	p99 below 100 ms after local receipt
Client event fanout	p99 below 200 ms after durable commit
Normal checkpoint cadence	~60 seconds, adaptive to activity and withdrawal demand
Stage expiry lag	Measured and bounded by oracle/expiry policy; not falsely advertised as instant
Initial capacity	1,000 concurrent active stages, then 10,000 in load tests
Financial integrity	Zero unexplained ledger/onchain reconciliation differences


Publish metrics for oracle observation age and disagreements, pending position resolution, quote rejects, stage outcomes by difficulty, LP utilization, maximum correlated payout, unresolved wins, unfunded customer liabilities, checkpoint lag, RPC/indexer head lag, cumulative withdrawal balances, reward allocation usage, reserve funding, and deterministic replay divergences.

Provide operator dashboards, auditable append-only logs, backup/recovery drills and alerts with trading-pause thresholds. Monetary correctness takes precedence over low-latency UX.
13. Testing and acceptance requirements
Before testnet integration, prove:
1. Determinism: repeated replay of the same events produces identical state and ledger hashes.
2. Stage boundaries: exact touches, post-expiry observations, missing data and rounding lead to the same outcome every time.
3. Atomicity: account funds and LP exposure cannot be spent twice under concurrent requests or retries.
4. Single-stage accounting: every supported payout preset has the exact total payout; a win credits automatically once; independent re-entry of unpaid winnings replaces the old claim correctly. Exact retries cannot duplicate a payout, and rejected entries preserve all existing claims. Legacy journals still replay unchanged.
5. Correlated payout: the LP can honor all contracts that can legally win together.
6. Oracle failure: feed gaps, receiver divergence and reconnects never accidentally create winning or losing outcomes contrary to the public policy.
7. Deposit safety: a refundable or refunded deposit cannot be credited to trading.
8. Settlement idempotence: epoch replay, transaction replacement and chain reorganization cannot move funds twice.
9. Withdrawal safety: overlapping cumulative tickets, recipient changes and expiry races cannot duplicate payments.
10. USDC conservation: total physical custody and recognized LP/customer claims reconcile across vaults and epochs.
11. Token invariants: emission cap, rewarded-stage eligibility, backing segregation and redemption accounting hold.
12. Recovery: process crash, leader failover, signer rotation and restore-from-backup preserve previously acknowledged instructions.
On testnet, validate with the actual compiled Solidity contracts: an end-to-end journey from deposit → onchain acknowledgment → stage entry → survival/loss → withdrawal funding → authorization → onchain payment, plus LP-loss funding, token epoch claims and reserve redemptions. These acceptance criteria are not satisfied by compiling interface sketches alone.
14. Implementation milestones
M0 — Cross-contract compatibility freeze
Finalize Solidity event and function semantics, signing domains, contract ownership, USDC denomination, epoch reporting, vault asset-ownership assumptions, admission-time policy, rounding and the operator-failure posture. Publish deploy manifests for Go consumption.
M1 — Fully deterministic paper engine
Deliver oracle collector, event sequencer, quote and pricing module, stage state machine, simulated LP and USDC ledger, account API, client WebSocket stream and reproducible historical/live-paper replay. No onchain asset keys required.
M2 — HyperEVM testnet integration
Wire real compiled contract ABIs; index acknowledged deposits; generate and reconcile settlement epochs; sign and submit funded withdrawal tickets; implement reorg handling, signer separation, vault reconciliation and pause behavior.
M3 — FUSE incentive and reserve integration
Publish bounded reward epochs and claim roots; compute adjusted realized LP profit; initiate approved reserve transfers; index token-redemption events and reconcile balances.
M4 — Production hardening
Collect and backtest canonical oracle histories, calibrate survival targets, test 100× correlated payouts, commission independent security reviews, exercise operator key and outage recovery, document custody/withdrawal limitations, validate real-money limits and complete incident response runbooks.
15. Explicit exclusions for V0
No CLOB, per-stage HyperEVM transactions, required HyperCore trading or hedging orders, trustless validity proofs, public ERC-4626 LP market, lending, margin leverage beyond the game's payout structure, FUSE collateral utility or unproven revenue from token buyers. Shared rounds and portfolio outcome netting are possible later but are not mandatory implementation prerequisites unless selected for launch.
16. Decisions required before real-money release
Must freeze before contract-integrated build: final smart-contract ABI/event shape; oracle admission and missing-data policy; stake limits and integer payout schedule; independent-entry versus shared-round semantics; the customer/LP/settlement liability ownership model; EIP-712 signer separation and finality policy.

May be configured after paper calibration but before real-money launch: target survival probability and pricing model, LP buffer parameters, maximum reserve allocation, emission budgets and schedule, transferability activation, redemption penalty and minimum economic liquidity targets.

Cannot be claimed until designed and implemented: operator-independent dispute/forced-exit path and onchain proof that the offchain trading ledger is correct. V0 deliberately makes neither guarantee.
Overall acceptance statement: The Go engine is ready for a staged implementation when it can deterministically accept and resolve oracle-based Fuse positions, reserve worst-case funded LP liabilities, reconcile all USDC movements with deployed HyperEVM contracts, publish reproducible epoch records and guarantee that no client receives an unfunded onchain withdrawal authorization. The specification is an engineering contract for developers, not evidence of a deployed or audited production system.
