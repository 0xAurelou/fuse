# Oracle policy and trust decision record

Version under review: `paired-local-receipt-v1` with
`pending-then-refund-v1`. Status: **implementation documented; production approval
pending**. This file records current behavior for independent review. It does not
supply an oracle proof or approve an operator-trusted launch.

## Receipt and outcome rules

The collector subscribes to BTC `activeAssetCtx` on two separately reconnecting
WebSocket connections named `a` and `b`. Both use the **same configured endpoint**.
Their agreement provides connection redundancy, not independent upstream truth.
Only exact `oraclePx` decimal strings enter settlement. Prices have at most six
fractional digits, positive value and the engine's integer safety envelope.
BBO is research-only evidence; it cannot establish a barrier touch.

The single sequencer orders receipt commands and ticks by durable journal
sequence. Unix-millisecond local processing/receipt time, not an exchange event
timestamp or EVM timestamp, determines eligibility. Equal timestamps are ordered
by sequence. Regressing command time is rejected. Raw observations from each
receiver enter the oracle/journal commitments. Repeated prices refresh health;
only a changed paired canonical price advances the canonical price sequence.

A quote or acceptance requires both latest receiver prices to equal the current
canonical price, both receipts at or before the command time, and each age at
most `max_gap_ms`. Freshness equality is healthy. Quote expiry equality is
expired, as is model validity equality. Acceptance also requires the original
canonical sequence and policy version, a valid quote, balances and all current
risk/capital checks. A quote is not accepted exposure.

Before a non-`local_` command executes, time advances accepted stages using the
**prior** receiver state. A missing receiver, age **greater than** `max_gap_ms`,
or disagreement lasting **at least** `disagreement_ms` makes an unresolved stage
pending. Shorter disagreement still blocks admission. A paired observation can
resolve a touch only while `start <= receipt_time < expiry`. Equality at either
barrier explodes the stage. A touch observed at expiry cannot decide the old
stage. A previously established explosion remains final during later outages.

At expiry an active stage survives only with healthy prior receiver state. If
ambiguous it becomes pending. Pending is sticky: restored healthy prices cannot
turn it into survival. Paired touch evidence within the remaining window may
still establish explosion. Otherwise `time >= expiry + void_delay_ms` refunds the
stake's original funded/debt composition. No interpolation fills gaps and no
post-expiry price reconstructs an earlier touch. Settlement/funding never
rewrites accepted pricing terms. Changes to gap/disagreement/void timing are
rejected while stages remain open; accepted policy versions remain retained.

Collector reconnect uses exponential backoff up to 16 seconds. Reads time out at
45 seconds; application pings occur every 20 seconds. Reconnect alone does not
refresh health or erase pending status. New validated receipts must reestablish
agreement. The tick worker is necessary for timely outage/expiry processing.
Local contract commands intentionally do not advance trading outcomes; local
oracle/tick commands use the separately documented local clock mapping.

## Boundary evidence

Retain complete test output and fault traces for the release, not just this list.
Implemented checks include:

| Boundary | Test evidence |
| --- | --- |
| Exact freshness and disagreement cutoffs | `TestOracleHealthAndGapEqualityBoundaries` |
| Inclusive corridor touches and expiry exclusion | `TestTouchAndPostExpiry`, `TestFractionalResearchWidthHasExactTouchBoundary` |
| Sticky outage/pending and delayed refund | `TestGapIsPendingThenRefundAndDuplicateDoesNotHeal`, `TestUnpairedExpiryCannotLaterBecomeSurvival` |
| Final breach during later outage | `TestBreachAlreadyEstablishedSurvivesOutage` |
| Raw dual receipts and cancellation | `TestTwoReceiversPersistRawAndCancel` |
| BBO cannot become settlement evidence | `TestBBOValidationAndPriceIsolation`, `TestCollectorBBOEvidenceNeverSubmittedAsOracle` |
| Prospective restart, corruption, clock and deadline | `internal/capture/recorder_test.go` |

Production fault injection still needs disconnect/reconnect and endpoint outage
rehearsals, scheduling delays, failed durable writes, stalled ticks, malformed
frames, clock corrections and disagreement at every stage/expiry boundary. The
recorder alone is not a trading or fault-recovery proof.

## Trust decision required before launch

Current contracts accept signed accounting reports. Those reports and journal
roots commit an operator's accounting; they do not independently verify the
historical observation stream or all barrier touches. This implementation keeps
public execution disabled while the launch trust model remains undecided.

Release reviewers must choose and approve a complete design, including:

1. Observation provenance, independent upstream assumptions, receipt-time
   authority, ordering and the historical availability/retention guarantee.
2. What signers attest, independent validation/controller boundaries, compromise
   and equivocation detection, correction/dispute authority and response times.
3. Proof or attestation verification onchain, historical completeness throughout
   each 30-second interval, and behavior when evidence is incomplete.
4. How approved recovery/pauses preserve funded claims, and whether an
   operator-independent exit is required or bounded operator custody trust is
   explicitly accepted and disclosed.
5. Key rotation/revocation and governance procedures, public testnet fault drills,
   independent security review and customer-facing risk disclosures.

A current price observation alone cannot demonstrate historical completeness.
Do not replace this decision with two connections to one endpoint or a claim
that matching replay roots prove correct external prices. Record the final
approved design, exact implementation/release and reviewer signatures under
production gates 4, 5, 13 and 14.
