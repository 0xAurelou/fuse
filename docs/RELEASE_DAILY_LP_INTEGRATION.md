# Daily LP accounting and shared settlement — candidate

This is isolated candidate code, not an approved deployment or a migration.
`src/DailyLPVault.sol` and `src/DailyBetCustody.sol` implement real ERC-20
custody and capital-lot transitions. Existing immutable LP/share/custody
contracts, deployment scripts, public API and frontend retain their current
behavior. All ten production gates remain open.

## Reuse papertrade settlement

Papertrade already uses `engine/internal/engine/oracle.go` and the common
reducer for paired-receiver observations, barrier touches, survival, delayed
voids and net settlement. The candidate uses those decisions rather than
introducing another price/outcome calculator. The read-only
`State.SettlementOutcome(stageID)` exporter returns the existing decision,
original terms commitment, journal/oracle commitments and integer USDC PnL.
It also distinguishes survival's canonical expiry from later processing time.
Barrier hits and final void determinations retain their recorded millisecond
times. No serialized state or legacy replay field changes.

The offline `fuse-research` bridge exposes this as
`{"kind":"settlement_outcome","stage_id":"stage-…"}` after journal replay.
It neither signs nor submits a transaction. The
[shared-engine relay candidate](RELEASE_DAILY_RELAY.md) now implements verified
journal replay, confirmed stage/ticket binding, checked signature requests,
day-aware planning and batch receipt reconciliation with PostgreSQL records.
Its durable outbox now survives local crashes, mined reverts and uncertain
broadcasts, including distinct queued-void and completed-refund proofs. The
rehearsal covers all three outcomes, writer-independent refunds and paused exits.
Same-nonce fee replacement/cancellation and exact external execution recovery
now pass locally while retaining every signed hash and keeping payment separate
from payer nonce cleanup. Live ingress ordering, approved recovery policy,
unclassified/idle nonce incidents and public API integration remain missing; the exporter does
not establish oracle truth.

`DailyBetCustody.settleBatch` accepts up to 16 outcomes under one EIP-712
authorization covering the ordered outcome array, journal hash, deadline,
chain, contract and current signer version. It keeps every original
underwriting allocation and transfers **losing stakes minus net winning
liabilities** once between customer custody and LP cash, matching the
papertrade settlement shape. Each ticket can settle once; a duplicate,
invalid last outcome or failed transfer reverts the complete batch. Customers
cannot withdraw interim credits during the atomic settlement. Single-outcome
settlement remains available. No FUSE backing can enter either capital pool.

Canonical bet/outcome times and close watermarks are milliseconds, matching
the Go engine. Quote freshness and authorization deadlines are EVM seconds.
Do not round a subsecond barrier hit into another accounting day.

## LP ownership, payouts and daily fees

Each signed contribution creates a nontransferable capital lot with its own
PnL and consumed-profit mark. Bets reserve maximum net liability in proportion
to eligible unreserved lot equity using integer largest remainders and stable
IDs. Outcomes retain those owners through partial withdrawal and runoff.
Loss marks survive daily closes; newcomers start at zero. An optional exit
request stops new underwriting, while free cash can be withdrawn without
request, timer, fresh NAV window or timely daily close. Unprocessed profits,
accepted risk and existing fee/backing reservations remain protected.

Customer stakes are physically locked in separate custody. Winning liabilities
are removed from LP equity and funded into custody atomically, before they can
be withdrawn. An oracle incident retains the original maximum reservation;
there is no credit for future losses, new deposits or unrelated reserve assets.
Both pools reserve arithmetic headroom for all possible open outcomes before
accepting new bets. Bet, market, account, active-ticket and global bounds are
enforced at execution. These bounds remain uncalibrated candidate settings.

Sequential UTC closes process the actually distributable per-lot eligible
profit once. The aggregate 5% fee precedes dynamic backing, using the economic
specification's buffers, 60-day target and 90% credit formula. Charges cannot
consume a lot's reserved risk. Fixed-destination fee/backing liabilities are
excluded from LP cash immediately and paid independently once per close.
Backing uses the actual `RedemptionReserve.fundReserve` pull path and clears
its exact allowance. A failed transfer preserves its liability for retry.
Reward demand, allowance, pending-credit completeness and oracle watermark
remain dual-attested inputs; funded reward promises are not implemented here.

## Recovery and bounded admission

A void can be finally determined after its expiry day. Authenticate that final
event through `resolve` to queue it while leaving customer stake and LP risk
reserved. Earlier daily closes can advance using the known future event,
without backdating it or releasing capital early. Once closes reach the
canonical day, anyone can `completeVoid` to refund only the original owner.
The recorded right survives pause, authorization expiry and signer rotation.
The canonical day cannot itself close while its queued void remains unexecuted.
Ordinary missing outcomes still block close. Batch planners must route future
voids through this queue and previously queued voids through completion; they
cannot blindly batch every exported event.

The current architecture bounds active lots at 64 and open bets at 1,024.
Unrestricted dust deposits would consume scarce slots indefinitely. Deposits
therefore require dual-signed capacity admission binding the owner, exact
amount, one-use ID and deadline of at most one hour. This is an authorization,
not a wallet identity cap. Anyone may be admitted; free exits need no signature.
Capacity-service policy and scalability for the intended public LP population
are unresolved release requirements. A 64-lot prototype is not proof of
adequate public capacity or support for the $3M incentive target.

New deposits use a paused, reconciled, zero-risk window during the current
accounting day. The window spans blocks until the next bet or outcome; it is
not a single timestamp. A newcomer cannot inherit an exiting lot's loss mark.

## Verification and remaining work

`test/DailyLP.t.sol` exercises actual token movements, original owners, paused
withdrawals, late/cross-boundary outcomes, deferred profits, daily loss
recovery, fee/backing order, signatures, rejected dust admission, failed
transfers, arithmetic bounds, all 27 market/payout pairs, and mixed net batches.
Randomized batch tests compare complete financial projections with individual
settlement. `scripts/generate_daily_accounting_vectors.py` exports independent
Python-ledger transitions into the committed Solidity fixture; the onchain test
compares every step's cash, exposure, fees, customer credit and three lots'
equity, reservations, PnL, marks and withdrawal capacity.

The 64-lot harness measured approximately 4.89M gas for signed acceptance,
14.24M for a signed 16-outcome net batch, and 3.31M for a signed close with
63 rounding remainders. These are harness call measurements, not target-chain
transaction estimates or approved operational limits. Maximum-open-bet close
gas and target-chain liveness still require verification; smaller batches do
not fix an oversized single acceptance or close.

Internal review found and fixed unauthorized dust-slot exhaustion and the
post-cutoff final-void deadlock; numerical settlement headroom was also added.
This does not replace independent contract/pricing review. Production still
needs reviewed scaling, live admission/capital projection, remaining transaction
recovery,
bootstrap checkpoints, reward reservation integration, client disclosures,
deployment migration/rehearsal and economic/capital sign-off. No funds moved
outside local tests and no campaign or deployment was activated.
