# Production release readiness

30 October 2026 (WITA). **Production approval: NO.** This is a working release
packet, not the requested final production package. The active goal remains
unfinished. The user changed the original weekly requirement to **daily
closes**, and requested LP withdrawals whenever economically feasible.
The user has now selected $250k LP/$125k backing funding targets, requested
bootstrap incentives below $3M aggregate LP equity, and expressed worldwide
distribution intent. These are not funding receipts or regional approvals.

The consolidated mechanism is [candidate specification](RELEASE_ECONOMIC_SPEC.md).
Its reference implementation is `scripts/release_accounting.py`, with focused
tests in `scripts/test_release_accounting.py`. Those files implement an offline
candidate. Separate source changes add the opt-in LP bootstrap taper, native
exact-width pricing and redemption through betting pauses, as described below.
No production deployment, deployed role, admission setting or balance has been
changed. Existing uncommitted work is preserved.

## Gates, in dependency order

| Gate | Current evidence and discrepancy | Required completion evidence | Status |
| --- | --- | --- | --- |
| 1. One specification | Consolidated candidate defines daily UTC attribution, 5% order, per-account loss recovery, frozen underwriting ownership, partial free withdrawals and dynamic allocation. Several parameters/design choices lack approval. | Named economic-owner approval of the exact hash, calibrated risk configuration and enforceable reward/redemption design. | Open |
| 2. Market pricing | All 108 unfitted Brownian variants fail. The subsequent causal empirical challenger loses on all 68 immediate configurations that receive quotes; 40 configurations receive none. The separate adaptive BTC 2× trial failed quality. | A calibrated model plus frozen, out-of-sample native acceptance results for every enabled pair and regime, informed-player/latency stresses and independent pricing review. | Open |
| 3. Capital | Native controls enforce per-bet/market/account/global limits. The synthetic stress permits an 80% LP loss. Isolated daily lot ownership now executes onchain; confirmed daily LP flows still need native capital projection. | Stress-approved limits, integrated capital projection, scalable reviewed contracts and separate funding verification. | Open |
| 4. Daily accounting | Actual Anvil/PostgreSQL rehearsal binds shared-engine outcomes, settles net USDC, closes daily and withdraws during pause. The cash-batch outbox survives crashes, a mined revert, lost send reply and terminal-write rollback. Existing production path remains legacy. | Scalable reviewed implementation, live admission ordering, capital projection, approved fee/recovery policy, complete incident handling and production deployment rehearsal. | Open |
| 5. Reward promises | Prior quoter reserves nominal allowance and inventory in a serial simulation; live contracts have no per-bet funded-minimum reservation. | Atomic durable acceptance, onchain enforceability, concurrency/crash tests, rate-bound redemption rights and exact precommit UI terms. | Open |
| 6. Backing/redemption | Contracts use total outstanding supply, unpaid-claim reservations and cumulative rounding. New source permits scheduling/starts/requests through betting pause; API discovers capability without relabeling legacy deployments. | Verify actual deployed capability and user path; enforce accepted minima against haircut/window changes, review residual policy and guarantee invariants. | Open |
| 7. Incentives | Candidate includes a $10k welcome allowance and token sublimit. New opt-in LP contract path tapers the finite 50M tranche below $3M; local tests/internal review pass, but daily ownership/exit integration and LP/player farming remain unresolved. | Actual multi-payout native attacks, reconciled externally reviewed campaign implementation, approved maximum exposure and combined-owner subsidy results. | Open |
| 8. Implementation/security | Existing contract and Go suites pass on current code, which implements different economics. No independent review of this candidate exists. | Reconcile source/spec/ABI/UI, resolve material findings, independent contract and pricing reports, deployed permission/parameter/upgrade evidence. | Open |
| 9. Operations | Existing capture continuity evidence includes an actual stale-feed/quality failure. Draft runbook now records recovery and claim obligations. | Named on-call owners, tested alerts and incident drills, fresh funded claims through pauses, executable recovery and exact UI timestamps. | Open |
| 10. Business/launch | $250k LP/$125k backing are user-selected targets, unverified. Worldwide intent recorded; region/channel approvals and funding verification remain open. Operations cash amounts and monthly spending limits are omitted at the user's request. | Funding verification, jurisdiction/distribution decisions and complete deployment-to-withdrawal rehearsal. | Open |

## Source reconciliation

| Proposed rule | Current source | Concrete gap |
| --- | --- | --- |
| Daily 5% protocol fee before FUSE and costs | `src/LPVault.sol`: `_crystallize`, `fundFUSEReserve`; `engine/internal/engine/reducer.go`: `fundSettlement` | No separate daily operator fee/close. Existing reserve allocation is capped at 3,500 bps and uses provisional capital multiples. |
| 7–10% measured pricing edge | `frontend/lib/trading.ts`: `DEFAULT_DNT`; `engine/internal/engine/pricing.go`; `engine/internal/engine/types.go`: `PayoutOptions` | Demo default is 500 bps Brownian; changing the label is not empirical validation. Actual menu is 2/5/10/25/50/100/250/1,000/10,000×. |
| LP capital accounts with original bet ownership and free partial withdrawals | `src/DailyLPVault.sol`; `src/DailyBetCustody.sol`; `engine/internal/dailyrelay`; legacy `src/LPShareVault.sol` / `src/LPVault.sol` | Stage/ticket binding and durable cash-batch delivery pass locally. Production deployment/API/frontend still use the shared HWM and 48-hour queue; live ingress, approved recovery policy, unclassified external/idle nonce incident handling, scaling and migration remain open. |
| Per-bet and per-market liability ceilings | `engine/internal/engine/capital.go`; `engine/internal/engine/reducer.go`; `engine/internal/api/server.go` | Opt-in custody-funded native controls and market debt attribution now pass local stress/replay checks and expose operator metrics. No calibrated/deployed limits or replacement LP capital contract exists. |
| Deferred protected profit, charged once when distributable | `scripts/weekly_profit_share.py`; `src/LPVault.sol`: `_crystallize` | Historical models consume protected profit marks. The new candidate avoids forgiving profit by temporarily filling exposure at a cutoff. Old results do not establish the amended rule. |
| Dollar-minimum reward and 9:1 loss/win entitlement | `scripts/iterate_loss_rewards.py`: `Quoter`; `engine/internal/rewards/rewards.go`; `src/RewardDistributor.sol` | Offline quote model is not wired into durable native acceptance. Current raw-score emission policy is not the proposed funded-dollar offer. Immutable roots bound total claims but do not prove score or per-bet promise correctness. |
| Total-supply backing | `src/FUSEToken.sol`; `src/RedemptionReserve.sol` | Actual supply allocation is 600M trader/50M LP/350M treasury, versus old 600M/400M prose and 950M research counterfactual. Preserve the actual allocation unless explicitly reapproved. |
| Below-$3M LP bootstrap | `src/LPIncentiveDistributor.sol`; `scripts/release_lp_bootstrap.py` | New `configureBootstrapCampaign` path implements the taper with existing share-vault checkpoints. Legacy configuration remains untapered; revised daily capital-account/withdrawal mechanics are not reconciled. |
| Redemption through a betting pause | `src/RedemptionReserve.sol`; `engine/internal/localdev/tokenomics.go` | New source decouples scheduling/starts/requests from betting pause and exposes confirmed capability. Existing immutable deployments remain legacy; per-bet funded-minimum enforcement is still absent. |
| Adaptive native pricing | `engine/internal/engine/types.go`; `engine/internal/engine/reducer.go`; `docs/NATIVE_PPB_INTEGRATION.md` | New PPB table format supports exact sealed widths and explicit preset subsets. Full retained paired-tape funded replay and software audit pass. A live adaptive provider and 7–10% pricing validation remain missing. |
| Honest availability/claim dates | `frontend/components/trade.tsx`; `frontend/components/dashboard.tsx`; `frontend/lib/demo.ts` | The demo is not a live reward reservation/claim backend. Exact entitlement and actual chain timestamps must come from enforceable accepted terms. |

## New real-data evidence

The [post-result pricing diagnostic](RELEASE_PRICING_DIAGNOSTICS.md) attributes
the fitted challenger's error across the complete menu and delay grid. Forty
of 68 quoted immediate configurations remain negative after hypothetical
perfect flat-path removal; the newest training labels used for offers are
29–243 days old. This requires positive-motion calibration and a validated
reference-age policy, in addition to flat-risk controls. The separate packet
is `.local/release-pricing/20261030-empirical-diagnostics-v1/`; its checks cover
cash, coverage and aggregation, with independent path reconstruction explicitly
false. It adds no new model, raw sample, native provider or release approval.

The frozen supplemental protocol in
`.local/capture-readiness/20261029-prospective-quote-economics-v1/` has now run
against the sealed native-verified quote tape. Its original protocol hash is
`e07f9f9b86a3b346e6aeeeca9062e87bd31c0f224476f8dc764ef052f2ee4110`.
It preserves **original trial failed**, **collection quality false**,
**economics validated false**, and **production approved false**.

The retained analysis has 786 healthy windows out of 960 (81.875%). For the
primary continuous candidate, 620 hypothetical one-dollar 2× tickets include
602 resolved outcomes and 18 censored outcomes. Assuming censored refunds,
LP gross PnL is $22 on $620 placed stakes, before rewards/capital/fees. Its
gross bounds for censored outcomes are $4 to $40. These are observations
about a 4%-target adaptive BTC model, not the proposed 7–10% release model.

The predeclared public `last12_majority_failed` strategy places 268 tickets,
with 136 surviving and 11 censored. Under the refund assumption its player
gross PnL is +$15; the LP's is -$15. Public `last_matured_failed` produces
player +$6 on 323 tickets under the same assumption. This shows why aggregate
margin cannot substitute for conditional-strategy tests. Neither result proves
a persistent exploit: the strategies reuse one dependent path, censoring can
change conclusions, and actual execution/costs/limits are not modeled. All
13 rules, three candidates, two restart modes, reporting periods and account
scalings remain in the 780-case output; no winning rule was selected for a
new test after observing these results.

The new release evidence generator binds these files and reports all 13
primary strategies, the complete unsupported-pair matrix, deterministic
capital cases and explicitly assumed incentive bounds. It does not turn any
release gate green.

Earlier native replay is also adverse evidence: the
[single-stage probe](SINGLE_STAGE_ECONOMICS_RESEARCH.md) reports all 45 trading
cases losing LP money under the shipped unfitted Brownian assumptions, with
nine no-entry cases. At 10,000×, one synchronized-account case loses $149,976
of an assumed $250,000 bankroll (59.9904%) on a short development prefix.
Funding each accepted obligation did not prevent repeated underwriting losses.
Those existing results reject the tested assumptions; they do not validate a
new edge setting or the daily capital-account candidate.

The subsequent [full-menu rejection grid](RELEASE_PRICING_VALIDATION.md)
uses ten matched raw calendar dates for all three assets, all nine payouts,
500/700/850/1,000-bps settings, five acceptance delays and eight fixed public
entry rules. All 108 immediate controls lose LP gross even under the most
LP-favorable censoring bound. There are 86,400 distinct asset/grid opportunities;
the 432,000 path envelopes and 43,200 strategy cases reuse those observations.
The 108 native formula vectors are exact Go exports. This is adverse historical
evidence, not a replacement pricing model, funded-bankroll validation, fresh
prospective result or independent external review. The source-bound software
audit is retained in the separate pricing packet and can be attached to a new
release evidence packet with `--release-pricing-packet`.

## Reproduce the candidate evidence

```sh
python3 -B -m unittest discover -s scripts -p 'test_release_*.py'
python3 -B scripts/release_evidence.py --output .local/release-readiness/your-new-run \
  --release-pricing-packet .local/release-pricing/20261030-rejection-v1 \
  --native-packet .local/release-native-ppb/20261030-sealed-adaptive-v1
forge test --offline --summary
cd engine
GOCACHE=/private/tmp/fuse-release-go-cache go test ./...
```

Choose an unused output directory; existing evidence is never overwritten.
The report rechecks retained case/tape/receipt hashes and independently verifies
all 780 cash cases and 3,120 cost/censoring bounds. It does not refit pricing or
rerun the original capture. The original copied supplemental analyzer was
executed once and verified the native receipt chain before producing its
sealed output. Source hashes bind the candidate and existing implementation.

Initial focused coverage included 45 tests for the accounting candidate and
evidence auditing. Existing contracts passed 87 tests including stateful
accounting invariants; all Go packages passed their default suite. These
results are local software checks, not independent reviews, proof of market
calibration, or deployed configuration verification. Optional integration
tests require their explicitly named retained fixtures; skipped checks must
remain visible in the validation record.

The initial complete Python suite passed **608 tests with no skips**, using the
retained native recorder/policy, declared synthetic follow-up fixture,
historical economics protocol and a freshly built current `fuse-research`
binary. The default earlier invocation lacked these optional integration
inputs and reported ten skips; it is not the final integration result. Enable
them with `FUSE_TEST_RECORDER`, `FUSE_TEST_POLICY`,
`FUSE_TEST_SYNTHETIC_FOLLOWUP`, `FUSE_TEST_HISTORICAL_ECONOMICS` and
`FUSE_RESEARCH_BINARY`. Those synthetic integration checks verify software
behavior and evidence handling, not new observations or a successful market
trial. The retained validation record identifies the exact fixture paths.

The subsequent pricing work adds 20 focused replay/auditor tests plus one
release-attachment validation test: **66 focused release checks** now pass.
The full-menu software audit independently reconstructed all 432,000 raw
envelopes, 43,200 strategy cases and 1,800 joint cases and verified every
native formula vector. This is software verification, not the required
independent external pricing review. Set `FUSE_RELEASE_PRICING_BINARY` as well
to run the new 108-vector cross-language test without skipping it.

After the pricing packet attachment checks were added, the complete Python
suite passed **629 tests with no skips**, and the complete default Go suite
passed. The current release packet retains the full Python log, fixture paths
and hashes. Contract sources were unchanged by this pricing iteration; the
earlier 87-test Foundry result remains a baseline for those sources, not a
new review or a check of the proposed daily contract implementation.

The [below-$3M LP bootstrap candidate](RELEASE_LP_BOOTSTRAP.md) adds ten focused
checks, bringing focused release coverage to **76 passing tests**. It preserves
the fixed supply and separates vesting from free-capital withdrawals. Its
50M-token worst-case bound survives wholly self-funded LP/player liability-time;
no lower cost to farm that allocation or measured LP acquisition is established.
The funding record preserves LP/backing targets and worldwide intent without
including operations cash amounts or monthly spending limits, as requested.
Funding verification and approvals remain open.

The subsequent contract implementation adds an opt-in below-$3M campaign with
conservative index rounding, preserving the legacy untapered configuration.
Eight new Foundry tests include four rational-vector scenarios and 1,000
randomized deposit/time cases; the full contract suite passes **95 tests**.
Three internal reviewers covering twelve lenses reported no concrete new
finding. Sources and test logs are bound in the contract verification packet;
the [internal review record](release/lp-bootstrap-review.json) states its scope.
No campaign is activated. This implementation retains the old share-vault's
48-hour queue; it does not satisfy the new daily capital-account/free-withdrawal
requirement or the independent external review gate.

The [native PPB interface](NATIVE_PPB_INTEGRATION.md) now removes the fixed-table
representation constraint without rounding adaptive quotes or inventing other
payout prices. Seven new Go tests pass, the complete default Go suite passes,
and 33 old/new native responses including state/journal hashes match. Nine
new Python adapter/auditor checks bring focused release coverage to **85**.
The full original paired tape has completed all four frozen profiles. The
all-offered one-account case returns LP gross +$28 on 620 accepted tickets;
the public last-matured-failed case returns LP −$2 on 323 tickets. Three
synchronized accounts reproduce three times the all-offered outcomes, LP +$84.
Peak liability is only $27 against hypothetical $250k LP cash. Exact observed
cash/liability checks reject understated peaks or unfunded states; this does
not calibrate production risk. The complete software audit passes: 208,134
responses and 196,700 receipt applications across four replays of the same
49,175 original paired receipts. All responses match, and four independent
terminal cash reconciliations plus sixteen illustrative cost checks pass.
Original failed quality, 4% target and all release gates remain unchanged.

With the complete native attachment checks, **91 focused release tests** and
the complete Python suite's **654 tests** pass without skips, using the new
native binary and all declared fixtures. The resumed test run binds 413 code
and test sources, unchanged throughout testing. Earlier native validation logs
and the 33-request compatibility result remain retained. Regression success
does not substitute for an external review. The v7 consolidated version-3 packet
at `.local/release-readiness/20261030-candidate-1-v7/` retains that source
snapshot, the completed native audit and validation logs.

The [redemption-pause integration](REDEMPTION_PAUSE_INTEGRATION.md) now closes
the current-source pause coupling in the reserve and local disclosure API.
Seven new contract tests include 1,000 randomized split-request cases; the
complete contract suite passes **102 tests**. Eleven confirmed-block RPC
scenarios cover new and legacy capabilities, unavailable reads, actual window
boundaries and missing snapshots; the complete default Go suite passes.
Three internal reviewers found no concrete new finding. This is not deployed
verification, independent external review or the missing per-bet reward
guarantee, so gates 5/6/8/9 remain open.

## What can advance without external decisions

The [native capital-control candidate](RELEASE_CAPITAL_INTEGRATION.md) adds ten
engine tests and two operator-metrics API tests. The stress holds prior winners
unfunded across later batches, fills the global ceiling with known debt plus
new open liability, then pays every customer during a pause. Separate checks
exercise concurrent market capacity, debt movement into withdrawals, failed
storage/retry, and reserved-fee/exit/backing/deposit/loss exclusions. The 33-request
legacy comparison passes against the earlier PPB binary. Default policies stay
unchanged; older replay packets retain their original source/binary scope.
The example limits permit an 80% LP loss and remain unapproved.
The buffer-update regression reproduces the old settlement lock and passes
with the candidate guard. All twelve new Go tests pass under the race detector;
the complete default Go suite and all **654 Python tests without skips** pass,
with 417 code/test source bindings unchanged throughout verification.
The capital verification packet is
`.local/release-capital/20261030-native-limits-v2/`; the refreshed consolidated
packet is `.local/release-readiness/20261030-candidate-1-v9/`. Earlier native
market results retain their original sources and do not evaluate this rule.

The subsequent LP-withdrawal clarification removes the future-bet admission
buffer from the reference's withdrawal calculation. An idle LP can fully exit
without a request or calendar delay, and an LP with accepted bets can release
only its unassigned cash. New risk must recheck the remaining capital. A
delayed daily close no longer blocks free principal, existing winner funding
or already reserved close transfers; delayed outcomes keep their canonical
day and cannot rewind processing time. The reference now has **50 accounting
tests**, including both acceptance/withdrawal orderings and preservation of
unpaid winnings, operator fees and backing transfers. This is executable
reference evidence; the Solidity 48-hour queue is unchanged and remains a
release blocker. The follow-up source-bound packet is
`.local/release-readiness/20261030-candidate-1-v10/`; prior packets retain their
original code and verification scope.

The next [daily LP integration candidate](RELEASE_DAILY_LP_INTEGRATION.md)
implements isolated real-token custody, original capital-lot ownership,
timer-free withdrawals and signed journal batches with one net USDC transfer.
The read-only shared Go exporter uses papertrade's existing decisions and
preserves millisecond canonical times. **35 new contract tests** include
1,000 cases each for randomized financial transitions and batch/individual
equivalence; the complete contract suite passes **137 tests**. The independent
reference now has **53 accounting tests**, plus two fixture checks and 37
step-by-step Solidity comparisons; all **670 Python tests**, the default Go
suite and focused Go race checks pass. A 33-request legacy comparison retains
identical state/journal responses. Two internal availability findings were
fixed: unsigned dust-slot exhaustion and a late-final-void close deadlock.

The refreshed source-bound packet is
`.local/release-readiness/20261030-candidate-1-v11/`. It retains compiler-verified
dependency hashes and current test logs. The 64-lot/16-outcome gas measurement
is approximately 14.24M harness gas; target-chain acceptance/close/batch
liveness, public scaling, actual stage-to-chain bindings, relay/recovery,
reward/incentive integration and independent review remain open. Existing
deployment/API/frontend behavior remains legacy. This is progress toward
gate 4, not production approval.

The [shared-engine binding adapter](RELEASE_DAILY_RELAY.md) now verifies full
journal replay against confirmed ticket commitments, canonical acceptance
receipts, stored bets, module wiring and pinned runtime code. It checks both
signature roles and rejects changed plans or stale generations. PostgreSQL
stores immutable ticket/stage bindings and atomically commits receipt-verified
paid-ticket associations. Batch reconciliation checks every outcome and the
actual net USDC transfer; storage flags alone cannot prove payment.

The isolated run at `.local/release-daily-bindings/20261030-v5/` passed under
the race detector: three bound outcomes, PostgreSQL restart, a 2-USDC net
settlement, 0.1-USDC daily fee, late void recovery after rotation, and customer
and LP withdrawals during pause. Synthetic backing stayed segregated. Native
terms, plan, generation, block-response and receipt-transfer tampering were
rejected. The default Go suite, focused race checks, seven release-evidence
tests and 33 legacy response comparisons pass. The refreshed packet is
`.local/release-readiness/20261030-candidate-1-v12/`; the 137-contract/670-Python
results remain explicitly scoped to their retained source-bound v11 run.

This closes the candidate's basic stage/ticket binding gap. Live admission and
oracle ordering, confirmed native LP capital projection, durable outbound
intent/raw-transaction recovery, void receipt observation, production routes,
capacity calibration and independent review remain unfinished.

Further internal review found that self-consistent replay alone did not prove
source authority. Financial signing now requires the live canonical sequencer
and its PostgreSQL leadership/head fence. The v6 local rehearsal rejects a
disconnected writer, keyless replay and a fully recomputed alternative branch
before signing callbacks; previously recorded voids still complete keylessly.
A focused source test also rejects memory-only authority, changed prefixes,
lost leadership and sequencers fenced after commit failure. The default Go
suite, focused race checks and seven release-evidence tests pass. The updated
source-bound packet is `.local/release-readiness/20261030-candidate-1-v13/`;
v12 retains the earlier code and does not establish this source-authority guard.
All ten release gates remain open.

The next cash-batch recovery candidate records intent before financial signing,
nonce/unsigned payload before payer signing and exact raw bytes before sending.
Its PostgreSQL lane lock and global ticket claims prevent conflicting delivery.
The v9 Anvil/PostgreSQL run recovered actual pending and reverted transactions,
restarted after inclusion, and forced a terminal-write failure to prove that
payment proof, paid-ticket rows and outbox completion commit together. RPC
outage and unknown nonce consumption halt rather than release reservations.
The source-bound packet is `.local/release-readiness/20261030-candidate-1-v14/`.
Cash-batch recovery is implemented locally; prepared expiry/cancellation,
fee replacement, void receipt proofs, live worker/ingress/capital integration,
scaling and independent review remain open. No production sender is installed.

The next candidate adds distinct durable queued-void and completed-refund
proofs. Actual transaction input, original-owner/stake binding, canonical
events and zero LP PnL are verified. Queueing records no payment and keeps
stake/exposure reserved; completion credits custody once. The v12 local run
completed after writer disconnection, betting pause, another signer rotation
and expiry of the old plan deadline. A later journal prefix preserved the
original queue proof. Injected terminal persistence failure rolled back both
completion proof and paid-right update before retry. The source-bound packet
is `.local/release-readiness/20261030-candidate-1-v15/`. Prepared cancellation,
fee replacement, external execution/nonce reconciliation, live worker and
admission/capital integration, scaling and independent review remain open.
All ten release gates remain open.

The next candidate retains original and replacement raw transactions in one
nonce slot. The v14 local run cancelled an expired prepared settlement without
marking payouts complete, then settled through an actual pending fee
replacement. Its original queued-void transaction also won after cancellation
was prepared, proving that all signed hashes are observed and the real winner
is reconciled. Cancellation terminal-write failure retained both processing
claims and the payer lane. The source-bound packet is
`.local/release-readiness/20261030-candidate-1-v16/`. Production fee/recovery
policy, unknown/external execution reconciliation, live ingress/capital/worker
integration, scaling and independent review remain open. All ten gates remain
open.

The next candidate reconciles confirmed external nonce consumers and exact
planned executions by another relayer. Its v18 local run audited a nonce
consumed after reservation but before raw signing, independently settled a
zero-net batch, kept the payer lane held until cancellation, and recovered a
matching untracked refund through writer outage/pause/rotation. Raw signature,
recovered sender, block membership/index, nonce and semantic receipt proofs
are checked separately. Triggered persistence failures preserved recoverable
claims/lane state and rolled back financial proof associations. Historical
queue generation metadata now agrees with pre/post-block version and rotation
events; a self-consistent false generation is rejected. The packet is
`.local/release-readiness/20261030-candidate-1-v17/`. The primitives handle the
adapter's exact payloads; unclassified/partial calls, idle/multiple nonce gaps,
production policy, live worker/ingress/capital integration, scaling and
independent review remain open. All ten release gates remain open.

The current combined packet is
`.local/release-readiness/20261030-candidate-1-v18/`. It adds the rejected
fitted challenger, all 3,110,400 reconstructed forecasts, 43,200 strategy cases,
1,800 joint cases and 616,398 native integer-quantization vectors. It preserves
the failed first packaging attempt and the earlier settlement rehearsal in
their original scopes. Current Go regression, focused race, Python and legacy
compatibility checks accompany the new source snapshot; the historical
137-contract/670-Python evidence is not relabeled as a new run. No live quote
provider or production policy was installed. All ten gates remain open.

Implement the approved economic mechanism in isolated candidate sources only
after material specification choices are settled; use the reference as test
vectors, then add differential checks against real Solidity/Go transitions.
The exact-width archived native replay/audit is complete within its recorded
scope. The [fitted historical challenger](RELEASE_EMPIRICAL_PRICING.md) is also
rejected: every offered asset/payout pair loses at every target edge, and
unavailable tails remain unresolved. Build and validate the live adaptive
provider and calibrate every product pair intended for launch. Any supported
menu change needs an explicit decision; unavailable products cannot be silently
omitted from the evidence or counted as successful calibration. Resolve the funded-reward guarantee and pause
controls before changing the UI to promise it.

External dependencies are explicit: economic sign-off, capital-source receipts,
funding verification, independent contract/pricing reviews, and
launch jurisdiction/distribution evidence. No reviewer has been contacted,
money moved, region authorized or deployment activated by this work.
