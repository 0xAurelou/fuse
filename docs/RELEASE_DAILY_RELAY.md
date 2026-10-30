# Shared-engine daily settlement binding — candidate

`engine/internal/dailyrelay` now links replayed papertrade decisions to the
isolated daily vault/custody contracts. This is candidate code and a local
rehearsal, not a production activation. All ten release gates remain open.

## Before signing

`Replay` recomputes every engine event/hash from the original policy. A caller
cannot supply a self-reported stage snapshot. Replay establishes integrity,
not source authority: a caller could recompute a different consistent branch.
`NewReader` is therefore keyless. Financial authorization requires
`NewSigningReader` with the live canonical sequencer and its fenced PostgreSQL
session. Before each signing role and after signing, the replay prefix must
match the authoritative journal and the durable leader/current head must still
match. A disconnected writer, memory-only replay or forged branch cannot
authorize outcomes. Already-recorded void rights remain completable keylessly.

`QuoteForStage` preserves the
native stake, multiplier, asset, prices and complete quote commitment. It
rounds the first admissible chain second upward and the exclusive native
expiry downward to its last admissible second. It never extends quote TTL.
Canonical bet and outcome times retain millisecond precision.

The reader requires an explicit manifest with pinned artifact bytes, runtime
code hashes, module addresses, chain ID, chain anchor and confirmation policy.
It validates required ABI shapes, module wiring and the current signer
generation at one confirmed block. The block is `head − confirmations`, using
the existing indexer's conservative convention. Replaced anchors or pinned
blocks halt verification; a reorg does not silently rebind financial history.

Each binding checks the successful acceptance receipt, original canonical
block, custody event, committed quote and stored vault bet. Owner, stake,
multiplier, asset, lower/reference/upper prices, policy quote commitment,
acceptance time and expiry must match the replayed stage. Historical quote
signer generations remain verifiable after rotation. PostgreSQL enforces
unique immutable ticket and stage identities per deployment.

Loaded records are untrusted inputs until fresh chain verification. Only a
reader-produced proof can be persisted; changing metadata or round-tripping
JSON cannot manufacture its in-memory provenance. This is an API misuse guard,
not a substitute for the receipt, source replay and pinned-node checks.

## Settlement and recovery

The planner revalidates bindings before producing a signed batch, a future-day
void queue request, signature-free void completion, a wait, or a request for
receipt reconciliation. It waits when native outcome/observation time is ahead
of confirmed chain time. Earlier daily closes must precede later-day outcomes.
It does not rerun an independent price/outcome model.

`Authorize` rejects changed plans, stale signer generations, changed chain state
and replaced previously verified blocks. It obtains the contract's exact
EIP-712 digest before invoking injected signing infrastructure, then verifies
each returned signature through `AccessController.verify`. There are no default
private keys or public-network broadcaster in this package. Complete-void
actions need no new signature after the original right is recorded.

`ReconcileBatch` requires the exact verified source prefix used by its signed
authorization. It checks a confirmed successful receipt, the signed batch
marker, every original-owner outcome/PnL event, and the actual single net USDC
transfer. A resolved storage flag alone cannot mark a payment complete.
Unexpected pool transfers, changed ticket metadata or altered transfer amounts
fail verification. PostgreSQL commits the exact proof and all paid-ticket
associations atomically; retries are idempotent and a different transaction
cannot replace a paid ticket. Restored proofs need fresh reconciliation before
they can be committed again.

## Durable settlement delivery

`Outbox` adds PostgreSQL recovery for cash batches, void queues and refunds. A dedicated
chain/payer has one non-reconnecting advisory-lock session and one active
intent. Global ticket claims prevent overlapping batches across payers.
`Active` discovers interrupted work after restart without a remembered ID.

`Prepare` saves the immutable intent before either financial signer runs,
checks the payer session before each callback, saves authorization calldata,
then reserves the nonce and exact unsigned EIP-1559 transaction before the
separate payer signer runs. Every signed field, chain, recovered sender and
canonical raw transaction must match. The exact raw bytes/hash commit before
`Deliver` can give them to an explicitly supplied broadcaster. Gas and fee
terms are explicit immutable inputs; no production default is installed.

Receipt absence means pending; an RPC error remains an error. Pending retries
keep the same raw bytes and nonce. An unknown consumed nonce halts the lane.
Successful inclusion stays `included` until `CommitBatch` verifies all outcomes
and the actual USDC transfer, or `CommitVoid` verifies the distinct void receipt.
The payment proof, paid-ticket rows, completed
outbox state and next nonce commit atomically. A confirmed canonical revert
releases ticket claims and advances past its consumed nonce without recording
payment. Later lane operations recheck the last finalized receipt anchor.

A never-prepared signed intent may be retired only after confirmed authorization
expiry/rotation and unchanged payer nonce. A prepared transaction cannot be
discarded this way; it needs a confirmed result or explicit nonce cancellation.
External-nonce reconciliation and approved production recovery policy still
need implementation/review. The payer must be dedicated to this lane, and
the injected transaction signer must never broadcast on its own.

`VoidProof` distinguishes a queued obligation from completed custody credit.
Queue verification checks the actual signed transaction input, its canonical
`FinalVoidQueued` event and unchanged ticket. The proof retains the original
source evidence and remains verifiable after unrelated journal/oracle receipts.
Queueing leaves the stake and original underwriting reserved, records no
payment, and releases only the transaction-processing claim and payer lane.

Completion requires that confirmed original queue proof, its fixed owner/stake
and matching final native decision. It verifies the actual `completeVoid` call,
both custody/vault completion events and zero LP PnL, and rejects physical USDC
movement between pool and custody. The credit is the original stake added to
customer custody availability; withdrawing that credit is a separate action.
The completion proof, paid-right record and terminal outbox state commit
atomically. Retries cannot replace the original queue or paid receipt.

Existing void rights need no live financial writer, new financial signatures,
fresh signer generation or expiry extension. Their completion stays available
through betting pauses and later signer rotations. A never-prepared completion
must be resumed; it cannot be retired as an expired financial authorization.
No live sender, production worker or public API route is installed.

## Fee replacement and cancellation

`PrepareReplacement` records an explicit decision and exact unsigned payload
before requesting another payer signature. It preserves the financial
authorization, calldata, gas, chain, target, value and original nonce. Both fee
cap and tip must increase above retained earlier attempts. Inputs are explicit;
the node may require a larger bump. No fee multiplier or public sender is added.

`PrepareCancellation` instead stages a zero-value, empty-data self-transfer
with exactly 21,000 gas at that same nonce. It needs the payer signer, not a
financial writer or new financial role signatures. Once a signed cancellation
exists, the API refuses to resume the original settlement or prepare a new
settlement fee replacement. It can still raise the cancellation's fees.

Every original and replacement raw transaction/hash remains retained.
`Observe` checks all signed hashes. It halts on RPC failure, contradictory
receipts, changed canonical history or unknown nonce consumption. An older
settlement may win against cancellation; its actual receipt must then undergo
normal payment/void proof verification. `transaction` retains the original
submission hash; `included_transaction` and `winning_attempt` identify the
confirmed winner used in financial proofs. A separately audited nonce consumer
uses `winning_attempt = -2` and retains its evidence in `nonce_recovery`.

A confirmed cancellation records no payment and changes no accepted obligation.
Only then can it atomically release processing claims and advance the payer
nonce. Existing payout reservations stay onchain. Cancellation does not revoke
an exposed contract authorization or prevent another sender from executing it;
execution by another sender must be reconciled separately from this nonce.

Unsigned staged replacement decisions can be resumed or explicitly abandoned;
abandonment never releases the nonce or discards a signed hash. The history
bound of 32 additional attempts is a candidate operational guard. Production
fee ceilings, node policy, target-chain finality and recovery ownership need
approval and independent review.

## External execution and nonce evidence

`ObserveTransaction` verifies the signed raw transaction, recovered sender,
nonce, chain, successful or reverted receipt, canonical block membership/index
and every receipt log identity. `FindNonce` scans an explicit range of up to
128 confirmed blocks. A missing result or RPC failure releases nothing.

`AdoptNonce` requires the actual transaction consuming exactly the reserved
payer nonce, including recovery after reservation but before raw signing.
The exact planned call remains subject to full payment/void proof. A reverted
or unrelated transaction records no payment and preserves accepted onchain
obligations. Unknown successful protocol calls or movements involving protocol
funds cannot be relabeled unrelated. Only proven nonce consumption releases
processing claims and advances the lane by that one nonce; there is no reset
to an unexamined RPC nonce.

`AdoptExternalExecution` verifies an exact planned call submitted by another
sender using the full batch or void receipt proof. It atomically commits that
proof and the external association. The original payer nonce and processing
claims remain held in `external_executed`; payment by another sender does not
consume them. Only later nonce evidence, a revert or cancellation closes the
lane as `external_reconciled`. Cleanup never records or charges the payment
again. Already executed calls cannot be sent or fee-replaced through the API.
Receipt-only reconciliation needs no live financial writer or signing keys.

Queue proofs also derive the actual historical signer generation from the
version before/after the block and its complete ordered rotation events.
Rotations after the queue transaction cannot change its asserted generation.
This corrects an earlier metadata-integrity gap; actual input/owner/stake
checks remain required.

These primitives cover the adapter's exact batch/queue/completion payloads.
Different authorizations, partial external batches, individual non-adapter
calls, governance multicalls and idle/multiple nonce gaps still require
incident handling and further integration. Unclassified evidence halts rather
than assigning a payment or skipping nonces. No production recovery worker is
installed.

## Executed rehearsal

Run in a new output directory:

```sh
GOCACHE=/private/tmp/fuse-release-go-cache python3 -B scripts/daily_settlement_e2e.py \
  --output .local/release-daily-bindings/a-new-run
```

The runner owns isolated loopback Anvil and PostgreSQL services, uses the
existing guarded local sender and faucet USDC, and stops its services afterward.
It refuses an existing output directory and excludes inherited external
database/port selections. Pinned artifacts and receipts remain reviewable.

The current run at `.local/release-daily-bindings/20261030-v18/` passed with:

- Five actual accepted tickets bound to replayed engine stages, including a
  PostgreSQL restart before signing.
- A survival and barrier loss settled in one batch with exactly **2 USDC** net
  LP profit; the native paper settlement agrees.
- A free **100 USDC** LP withdrawal during open risk, followed by a daily fee
  of **0.1 USDC** on that actual profit.
- A void finalized after midnight, queued through the previous close, then
  completed during pause after signer rotation without new signatures.
- Full LP and customer withdrawals during pause while unpaid fees stayed
  reserved; **125 USDC of synthetic segregated backing** remained unchanged.
- Rejections for unconfirmed acceptance, changed native terms/bindings,
  modified plans, replaced confirmed blocks, stale generations, already-settled
  signing, early void release and altered receipt-transfer amounts.
- A real PostgreSQL source-journal restart, with a disconnected source writer,
  keyless replay reader and recomputed alternative branch rejected before
  signing callbacks.
- Crashes before financial signing, after nonce reservation, after raw-byte
  persistence, during a pending transaction and after confirmed inclusion.
- An actual mined out-of-gas revert followed by settlement using the next
  nonce; a lost send reply; rejected payer-field tampering, overlapping payers,
  receipt RPC outage and simulated unknown nonce consumption.
- Expired never-prepared intent retirement and restart discovery. An injected
  failure of the terminal outbox write rolled back both the payment proof and
  all paid-ticket rows before a successful retry. Settled retries did not send
  another transaction.
- Separate durable queue/refund proofs, lost-reply/restart recovery for each,
  and original-owner custody credit once. Completion passed with the actual
  canonical writer disconnected, trading paused, another signer rotation and
  a delay past the old plan deadline. A newer journal preserved the queue proof.
- Changed queue/refund events, owner, self-consistent asserted calldata and
  unexpected pool transfers were rejected. A forced terminal refund-write
  failure rolled back the completion proof and paid-right update together.
- An expired prepared settlement cancelled through an actual same-nonce
  self-transfer, without recording payment or changing payout balances/exposure.
  Failed terminal persistence retained both claims and the payer lane.
- An actual pending fee replacement won and its receipt funded settlement.
  Lost replies/restarts retained both hashes without new financial signatures.
  An original queued-void transaction also won after cancellation preparation;
  its queue proof was recorded and the losing cancellation was not sent.
- An unrelated independently submitted transaction consumed a nonce after a
  reservation-only crash. Its confirmed raw/block evidence was found by a
  bounded scan; wrong nonce, block index and raw payload were rejected. No
  payouts or accepted exposure were released by that unrelated execution.
- Another relayer settled a separate zero-net batch. Payment proof and its
  association committed together while the original payer lane stayed locked;
  a later cancellation closed that nonce without recording the payment twice.
- An independently submitted matching refund was recovered after a lost reply,
  writer disconnection, pause and rotation. False historical signer-generation
  metadata was rejected. Injected persistence failures retained recoverable
  lane/claim state and rolled back financial proof associations.

These small synthetic amounts test accounting; they do not verify launch
funding, profitable prices, real feed latency, public-chain finality or capacity.

## Remaining integration

Production still needs the admission pipeline to order confirmed chain
acceptance alongside live oracle receipts and the native journal without
rewinding time. This rehearsal constructs that ordering explicitly. Confirmed
daily LP flows must also update the engine's capital projection before it
offers new quotes; onchain acceptance already rechecks real cash atomically.

The settlement coordinator now exercises those persistence and recovery steps
locally. Approved fee/recovery policy, unclassified/partial external execution,
idle or multiple nonce gaps and a production worker remain incomplete. Deployment
and public API/frontend integration, target-chain gas/finality validation,
reward/incentive checkpoints and independent review also remain open. The
rehearsal's daily-close inputs are explicit synthetic attestations, not a live
reward-demand accounting service. Existing production routes remain unchanged.
