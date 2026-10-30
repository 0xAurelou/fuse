# Production deployment and operations checklist

Candidate preparation, 30 October 2026 (WITA). This checklist has not been
executed against a production deployment. Daily closing supersedes the earlier
weekly proposal. Pair this with `RELEASE_ECONOMIC_SPEC.md`,
`RELEASE_READINESS.md` and `release/operating-budget.json`.

## Release and funding

- [ ] Name accountable economic, risk, contract, pricing, operations and business owners.
- [ ] Record approved specification/source hashes and every enabled asset/payout/duration.
- [ ] Bind native market-data, pricing-selection, stress and accounting artifacts to those sources.
- [ ] Verify the full retained-tape audit separately from unit tests. Keep the quality-failed 4%-target BTC 2× replay and the adverse full-menu formula controls in their original scope; its $27 peak liability does not calibrate a $250k production bankroll.
- [ ] Retain the rejected fitted challenger and its full refusal grid. Check all 108 immediate configurations, every delay/public rule and the separate software audit; 68 losing offered configurations plus 40 unavailable ones do not validate a release menu. Require new frozen native evidence for the replacement model.
- [ ] Obtain independent contract and pricing reviews; record each finding, fix hash and retest.
- [ ] Confirm launch jurisdictions and distribution terms with the responsible qualified advisers; save dated decisions.
- [ ] Verify funding readiness separately; omit operations cash amounts and monthly spending limits from the release document, as requested.
- [ ] Verify separate LP, backing, customer custody and operations funding; the user-selected $250k/$125k targets are not receipts.
- [ ] Approve per-bet/account/market/global limits and dollar buffers from stress results; do not reuse uncalibrated 2×/3× rules.
- [ ] Verify `funded-single-stage-capital-v1`, an exact cap for every enabled market and zero-exposure reconciliation before activating the native candidate. Retain unpaid winning debt by origin through withdrawals and observed settlement. Reproduce the stress result; its $200k/$250k loss envelope is not an approved risk tolerance.
- [ ] Deploy paused on the intended chain using the approved compiler/settings; compare bytecode, immutable token addresses and module wiring to the release manifest.
- [ ] Verify distinct settlement/risk authorities, signer rotation domains, multisig/timelock delay, guardians, schedulers and no unintended admin sweep/upgrade paths.
- [ ] Confirm supply escrows, authorized reward budgets, transfer activation, redemption policy and last-token restrictions.
- [ ] Verify deployed `supportsPausedRedemptions == true`, its code/ABI binding and the confirmed API capability before promising redemption through a betting pause. Legacy immutable deployments remain pause-gated.
- [ ] If LP bootstrapping is approved, use the reviewed `configureBootstrapCampaign` path, verify `bootstrapCampaign == true`, fixed $250k/$3M thresholds, finite escrow, original end, exclusions, liability reports, vesting and claims through pauses. Legacy `configureCampaign` remains untapered; do not use it as if it implements the candidate.
- [ ] Execute a funded canary: deposit, acknowledge, accept both outcome/reward possibilities, settle, claim, void, replay rejection, close and withdraw.
- [ ] Verify a refused/failed acceptance releases no partial reservation and cannot debit a user twice.
- [ ] Enable only validated pairs after the canary and all approvals; preserve the paused deployment if any item fails.

## Daily close, proposed 00:00 UTC / 08:00 WITA

- [ ] Persist the cutoff, calendar day ID, prior close hash and exact terminal journal sequence.
- [ ] Reconcile both oracle receivers, canonical outcomes/watermark, deposits, customer cash, open obligations, known unfunded wins and pending payouts.
- [ ] If a pre-cutoff outcome is ambiguous, pause new entries and distributions; preserve its reservation and existing claims. Resolve using the accepted oracle/refund rule.
- [ ] Assign crossing bets to the correct day and retain their original LP underwriting owners.
- [ ] Recompute per-account PnL, consumed bases, loss carryforward, pending protected profit, prior charges and free cash; require an independent risk reconciliation.
- [ ] Reserve `floor(5% * D)` once; calculate dynamic backing only afterward and within post-transfer global and per-account capital headroom.
- [ ] Atomically commit the close before authorizing payments. Crash recovery must reproduce the same close/authorization IDs rather than closing again.
- [ ] Pay operator/backing reservations once, reconcile actual receipt and make 90% backing credits usable only at the next UTC day boundary.
- [ ] Publish a close receipt with amounts, roots, open/known obligations, deferred profit, funding status and any delay; do not expose private customer data.
- [ ] Recompute free LP withdrawal amounts after every liability, capital or distribution change; partial free withdrawals need no artificial calendar delay.
- [ ] Exclude future-bet admission headroom from withdrawal obligations. Exercise both acceptance/withdrawal transaction orders: recheck the winning transaction's committed state and reject any stale amount; preserve every accepted maximum payout and unpaid win.
- [ ] During a missed daily close, execute free principal withdrawals and fund existing winners while keeping unprocessed profit reserved. Backfill authenticated outcomes into their canonical day, close each day once and preserve a monotonic observation clock.
- [ ] Reuse shared Go outcome exports; verify accepted onchain ticket/terms/time bindings against the replayed journal before signing. Preserve millisecond canonical times; separate second-based authorization deadlines.
- [ ] Require the live canonical sequencer and fenced PostgreSQL source for financial signing. Demonstrate that a consistent forged branch, memory-only replay, disconnected writer and lost leadership reach no signing callback. Preserve keyless completion of recorded void rights.
- [ ] Run `scripts/daily_settlement_e2e.py` in a new directory. Verify artifact/runtime pins, anchor/depth, old quote generations after rotation, PostgreSQL restart, exact batch outcome/USDC receipt proof and paid-ticket immutability. Reproduce intent/nonce/raw-byte crashes, lost send reply, mined revert and terminal-write rollback. Keep the payer dedicated; verify lane ownership and cross-payer ticket exclusion.
- [ ] Discover active work from the durable outbox after restart. Distinguish absent receipts from RPC failure; retain raw bytes/hash/nonce through uncertainty. Require monetary proof before payment completion. Reproduce prepared expiry/cancellation and pending fee replacement, checking every retained hash and the original-wins race. Confirm cancellations never mark payouts complete and terminal failure retains claims/lane. Reproduce exact external execution and unknown reserved-nonce audits: verify signed raw body, recovered sender, canonical block/index, nonce and payment proof separately. A different relayer payment must keep our nonce held until cleanup; unrelated nonce consumption must not mark payouts paid. Approve fee/recovery limits and implement handling for unclassified/partial calls and idle/multiple nonce gaps before enabling a live worker.
- [ ] Reproduce distinct durable void queue/refund proofs and actual-call verification. Queueing must preserve stake and underwriting; completion must credit the original owner once with zero LP PnL. Disconnect the financial writer, pause trading, rotate signers and pass the old plan deadline before completion. Force a terminal refund-write failure and verify both the completion proof and paid-right update roll back together. Retain the original queue after payment.
- [ ] Rehearse signed net batches, mixed win/loss/void outcomes, duplicate/last-item rejection and atomic failed-transfer retry. Queue final future-day voids before earlier closes; complete their fixed-owner refunds only in the canonical day.
- [ ] Validate bounded account admission and target-chain gas for acceptance, maximum-open-risk close and settlement batches. Reject unsigned dust-slot consumption; ensure admission IDs survive retries only when no transfer committed.
- [ ] Archive proof that no uncredited deposit, FUSE backing or new LP contribution was counted as betting profit.

## Monitoring and response

Thresholds must be approved values bound to the risk configuration; blank
thresholds fail readiness. Alert routing/on-call names and drill receipts are
required. Do not infer production readiness from a locally passing test.

| Signal | Required response/drill |
| --- | --- |
| Realized gross and after-reward margin by pair, regime and public strategy | Investigate conditional player advantage; stop the affected new quotes when a preapproved threshold trips. Preserve existing payouts. |
| Open exposure plus known unfunded wins; per-account/market/global ceilings; free capital | Reject new risk atomically at a limit; run simultaneous-winner and concurrent-withdrawal drills. Never use reserve backing as LP support. |
| Native capital metrics and policy availability | Scrape operator-authenticated market exposure/unfunded-winning debt and configured ceilings; compare both cash headroom and market/global room. Legacy policies omit market attribution and report controls disabled. Test alert delivery and reconcile values to the journal. |
| Quote inventory and dollar allowances, pending reservations/credits, campaign totals | Stop offering unfunded rewards before acceptance; accepted rights stay intact. Test double submits, retries, restart and inventory depletion. |
| Total FUSE, locked allocations, reserve balance, unpaid claims and free backing | Reconcile supply/burns/claims to chain; isolate backing discrepancies; keep funded accrued claims payable. |
| Daily fees, pending protected profit, consumed bases and unpaid distribution reservations | Halt distributions on mismatch; replay from a durable checkpoint; verify no missed/double daily close. |
| Oracle freshness/agreement, receipt-chain continuity, price jumps and quote age | Stop new bets on uncertainty; enforce accepted pending/refund rules and keep obligations reserved. Test disconnection, stale replay and reorg evidence. |
| Settlement inclusion/finality, RPC/DB health, signatures and journal roots | Reconcile before retry; never reset balance/nonce to recover a transaction. Test reverted, dropped, duplicated and reorged transfers. |
| LP withdrawable/reserved balances and queue age | Show actual capacity and cause of delay; preserve underwriting ownership through partial release and runoff. |
| Aggregate LP equity, bootstrap taper, remaining daily/total FUSE and vesting | Reconcile capital/liability-time before every change; crossing $3M stops new score without erasing accrued rights. Test withdrawal/redeposit cannot reset the campaign or delay free withdrawals. |
| Redemption start/end, unpaid claim age and failed transfer attempts | Show actual chain times; retain liabilities across windows and retries; do not allow a betting pause to silently invalidate promised reward access. |
| Operations cash runway and recurring costs | Escalate before funds run out; no spending from customer custody, LP capital or segregated backing. |

## Emergency and recovery rehearsal

- [ ] Pause new bets while an existing win is unfunded, then fund/pay it without resume or debt loss.
- [ ] Pause after a reward was accepted but before its outcome; prove its entitlement and redemption access survive.
- [ ] Pause before a scheduled redemption start; start explicitly and by request without resuming bets. Burn, reserve, cross a window with an unpaid old claim, and claim both obligations once after their actual end times. Verify failed transfers preserve debt for retry and API availability matches the deployed capability.
- [ ] Kill/restart the coordinator at acceptance, outcome, daily commit and transfer-confirmation boundaries; reconcile the durable journal and chain with no duplicate money/reward movement.
- [ ] Exercise oracle outage, invalid/disagreeing prices, delayed outcomes, settlement insufficiency, RPC outage and token transfer failure.
- [ ] Prove retries preserve authorizations/reservations and that no operator recovery action releases owed backing or spends a customer's uncredited deposit.
- [ ] Complete a full daily cycle with partial LP withdrawal during open risk, a newcomer after reconciliation, a loss day, recovery and a later profitable day.
- [ ] Repeat on the intended staging chain/configuration and save hashes, transaction receipts, timestamps and responsible reviewers.

## Evidence required for the final package

One signed-off specification, reconciled source/bytecode/configuration, complete
reproducible pricing and solvency artifacts, independent reviews with resolved
findings and funding verification, plus this
executed checklist and incident drill records. Until those exist, production
activation stays unapproved.
