# FUSE release economic specification — candidate 1

Prepared 30 October 2026 (WITA). **Proposed, unsigned, not production authority.**
This is the consolidated candidate for release gate 1. It preserves the user's
fixed 5% protocol share, daily netting, permanent loss carryforward, 9:1 loss
reward weighting, and dynamic allocation. Choices introduced here require
economic-owner approval. The user subsequently selected daily closes and LP
withdrawals whenever economically feasible; those replace the initial weekly
close/full-lot-exit proposal. Passing a reference-model test does not approve
a contract or a deployment.

The user also selected $250k LP and $125k backing as launch funding targets,
requested LP incentives below $3M aggregate pool equity, and expressed worldwide
distribution intent. Funding remains unverified; the incentive mechanism below
is proposed and worldwide intent is not evidence of regional approval.

## Authority and scope

On approval, this document supersedes conflicting economic rules in
`TOKENOMICS_SPECIFICATION.txt`, `SPECIFICATION.md`, `WEEKLY_REALIZED_PROFIT_SHARE.md`,
`DYNAMIC_PROFIT_ALLOCATION.md`, and `FUSE_FUNDED_REWARDS_PROPOSAL.md`. Until then,
those documents and all retained experiments remain historical evidence with
their original assumptions. Their results must not be relabeled as tests of
this candidate. See `RELEASE_READINESS.md` for implementation gaps.

The release candidate is a single, funded, 30-second double-no-touch bet.
Total payout includes stake. Assets in the existing product are BTC, ETH and
HYPE; the current preset menu is 2, 5, 10, 25, 50, 100, 250, 1,000 and 10,000×.
An asset/payout pair stays disabled until its own pricing and execution evidence
passes. The old integer 2–100× menu and multistage ladder are not implicit
additional approved products. Other durations need separate validation.

All cash accounting uses six-decimal integer USDC; token accounting uses
18-decimal integer FUSE. Round fees down, required reservations up, and customer
claims down using a single cumulative recipient calculation. Atomic units,
rather than floating-point dollars, are authoritative.

## 1. Clock, attribution and finality

Accounting days are **00:00:00 UTC to the following 00:00:00 UTC**, half-open
`[start, end)`. The proposed cutoff time is 08:00 WITA. Day identity
is derived from the fixed UTC calendar, never 24 hours after a process restart.
At exactly `end`, first close the preceding day, then process new-day events.

Recognize betting PnL at the canonical outcome time: the first proven barrier
touch for a loss, expiry for a survival, or final void/refund determination.
Receipt, publication, settlement-transfer and user-withdrawal times do not
change economic attribution. A missing or disputed pre-cutoff outcome prevents
final close; it is not assumed to be a loss. Stop new entries if the close cannot
be reconciled. Post-cutoff profits cannot repair a pre-cutoff fee calculation.

A bet accepted before the cutoff and unresolved at it remains fully reserved.
Its stake is not profit. If its canonical outcome is at or after the cutoff,
recognize it in the next day. Close needs an authenticated oracle/journal
watermark covering the cutoff, complete deposit and settlement reconciliation,
and a unique sequential day ID. Late evidence before finality delays close;
material evidence contradicting an already finalized close is an incident that
halts distributions and requires a separately approved correction. Do not
silently edit a finalized day or rerun its fee.

## 2. Profit and losses

For a resolved bet with funded stake `s` and total payout entitlement `p`, LP
trading PnL is `s - p`. A win creates the entire entitlement immediately,
including money not withdrawn. A proven loss has `p = 0`; a void has `p = s`
and PnL zero. Inter-custody transfers settle existing entries and never create
additional profit. Neither an uncredited deposit nor an unresolved stake funds
new obligations or a distribution.

Exclude customer/LP deposits, donations, FUSE backing, reward allowance credits,
token issuance, redemptions and projected edge from trading PnL. Operating costs
are paid from a separate operations account **after the 5% fee**; they do not
reduce or enlarge the betting-profit fee base. FUSE funding also follows the
fee. If operations needs more money, its sponsor must provide separately
documented funding; changing the fee needs a new specification.

Each nontransferable LP capital lot records cumulative recognized trading PnL
`P_i` and its consumed profit-base mark `H_i`, initially zero. At close:

```text
U_i = max(0, P_i - H_i)
U   = sum(U_i)
loss_i = max(0, H_i - P_i)
H_i := H_i + processed_base_i # after this close's calculation
```

Allocate the processed fee base `D` across accounts as `processed_base_i`;
these amounts sum exactly to `D`. Marks advance for that processed base,
including its retained LP remainder. Profit outside `D` because capital or
cash is unavailable stays pending; it is neither charged nor forgiven. A
later loss reduces that pending profit before any fee is earned. This
deliberately changes the earlier research rule that consumed protected profit
without a fee: that rule permits cutoff exposure to erase the fee base.
Previously processed amounts cannot be charged again.
Losses have no daily, annual, restart, deposit or withdrawal-request reset.
Prior fees are final: subsequent losses block future fees but do not claw back
fees already earned. Therefore lifetime fees need not equal 5% of final
lifetime PnL. This finality must be disclosed to LPs.

For example, +$1,000 then -$1,000 on successive days can pay $50 and $0 in
fees, despite zero aggregate trading profit. Netting those outcomes in one
week would pay zero. Daily frequency changes fee timing and total possible
fees; historical weekly experiment results do not describe it.

## 3. Capital and distributability

Maintain separate customer custody, LP underwriting cash, segregated FUSE
backing and operations accounts. A dollar can belong to only one of these.
No FUSE backing or pending customer deposit can underwrite a bet.

For each open/pending bet `j`, reserve `L_j = payout_j - physically funded,
ring-fenced stake_j`. Include liability-backed stakes correctly; untransferred
winnings do not become physically funded merely by being selected as a stake.
For each known win, reserve its remaining unfunded LP obligation `W_j` before
any user claim. A reservation moves from open exposure to recognized debt,
without an interval in which it is absent and without counting it twice.

```text
O = sum(L_j for every accepted unresolved bet)
W = sum(unfunded recognized customer entitlements)
C = confirmed LP cash, less already reserved operator fees,
    backing transfers, and finalized LP exit claims
hard_required = O + W + admission_buffer
```

Accept only if the post-acceptance state meets all of: per-bet liability cap,
per-market liability cap (open plus known unfunded debt), global liability cap,
account exposure cap and `C >= hard_required`. Sum simultaneous maximum wins;
give no correlation, opposite-side, future-loss, donation or new-deposit credit.
These tests must run atomically at acceptance, not only when showing a quote.

Replace the provisional 2×/3× rules with explicit dollar buffers and exposure
ceilings bound to a reviewed stress report. The exact calibration values are
**unapproved**. Admission, distribution and backing buffers obey
`0 <= admission_buffer <= distribution_buffer <= backing_buffer`. Until a
configuration and its evidence are approved, production admission and profit
distributions remain disabled. A model using illustrative buffers is not a
production capital calibration.

The [native capital-control candidate](RELEASE_CAPITAL_INTEGRATION.md) now adds
opt-in per-bet/per-market enforcement and exact market attribution of unpaid
winners for custody-funded single-stage bets. Its synthetic simultaneous-win
stress fills $200k of liability against $250k LP cash and pays all customers,
leaving $50k LP cash: an 80% loss permitted by the example limits. These are
not approved risk tolerances. Existing LP contracts, daily ownership/fees and
free withdrawals still need reconciliation; no deployed limit is changed.

For the daily allocation, loss receivables count in LP NAV but cannot finance
a cash distribution before reaching the LP account. Define:

```text
O_i = unresolved maximum LP obligation assigned to capital lot i
Q_i = min(U_i, max(0, net_equity_i - O_i))
D = min(sum(Q_i), max(0, C - W - O - distribution_buffer))
fee = floor(D * 500 / 10_000)
target = ceil(60 * standard_reward_need_over_previous_30_complete_UTC_days / 30)
gap = max(0, target - available_standard_allowance - pending_standard_credits)
need = ceil(gap * 10_000 / 9_000)
room = max(0, C - W - O - fee - backing_buffer)
backing = min(D - fee, need, room)
LP_retained_processed_profit = D - fee - backing
capital_protected_pending_profit = U - D
```

The first 30 days use the same fixed denominator of 30 with prelaunch activity
zero; no startup extrapolation or fabricated demand. Count the standard reward
that each completed, funded, nonvoid bet would require, including bets with no
reward offer; exclude welcome uplift. The 60-day runway and 90% credit remain
explicit candidate parameters, not optimized production facts. If an approved
parameter changes, record an effective future day and preserve accepted rights.

Calculate `fee` once on aggregate `D`. Allocate `D` across `Q_i` using largest
remainders and stable lot-ID ties, then allocate the combined fee/backing
charge proportionally to those processed bases by the same method. Never
floor a separate fee for every wallet. A charge cannot consume a particular
account's accepted-risk reservation, even if other accounts have free cash.
Reserve both transfers at close, exclude them immediately from spendable LP
cash/NAV, and pay each once using distinct close-linked authorization IDs.
Unused or delayed transfer authorizations cannot generate another fee base.
Only confirmed backing receipt creates a 90% standard-allowance credit, usable
at the next UTC day boundary. Count pending credits in the gap calculation so
one transfer is not requested twice.

## 4. LP ownership and capital flows

Each contribution creates a new capital account (lot) with its own zero trading
PnL and mark. At acceptance allocate the bet's maximum net LP obligation across
eligible accounts in proportion to their unreserved equity, using integer
largest remainders and stable lot IDs. Freeze those underwriting allocations
in the accepted bet. Allocate its outcome PnL to those same accounts using the
same allocation weights, even if capital has since been withdrawn. Each
account always retains enough equity for its own unresolved allocations.
Contributions never increase an existing
lot's mark or erase its losses. A newcomer pays fees on its own new profits,
even while an older lot is recovering losses. This requires lot/series
accounting; the existing single fungible-share high-water mark is insufficient.

**Partial withdrawals of free capital are allowed at any time**, including
while other bets are open or new betting is paused. This replaces the initial
calendar-locked exit proposal. For requested account `i`, cap executable cash by:

```text
own_free = max(0, net_equity_i - O_i - U_i)
pool_free = max(0, C - W - O)
withdrawable_i = min(own_free, pool_free)
```

`U_i` remains reserved until the daily close because both the fee and dynamic
backing allocation must be determined before those profits leave. This is not
an additional fee. Previously assigned open risk remains with its original
account; withdrawing capital cannot pass it to remaining LPs. Show available,
reserved-for-bets, reserved-for-close and pending/unfunded amounts separately.
Recheck the amount atomically at execution. No arbitrary 48-hour wait or
weekly window applies to otherwise free, reconciled withdrawal capacity.

The buffer for admitting future bets is **not an LP withdrawal liability**.
An LP may withdraw that headroom; the protocol must then reject new bets that
cannot meet its admission buffer. Deposits, expected future losses and FUSE
backing cannot replace the cash owed to existing winners. Known winnings
have priority: fund them before the LP payment or leave their entire unpaid
amount ring-fenced and immediately available for settlement. The user need
not withdraw their winnings first. A trading pause, missed daily close or
unrelated account's exit request cannot impose a calendar lock on this free
cash. No exit request is required for a partial withdrawal.

Delayed processing must preserve the canonical outcome day without rewinding
the observation clock. A winning outcome belongs to its exact expiry; a
barrier loss belongs to its authenticated earlier hit time. Close each day
once after its authenticated outcome watermark, even when the operator is
late. A delayed close can block new risk and unprocessed-profit release,
but cannot block safe principal withdrawals, funding existing winners or
paying already reserved close transfers. Outcomes in a finalized day cannot
be silently reassigned to the current day.

Partial cash withdrawals preserve the account's PnL and mark; they are capital
distributions, not transfers of loss-recovery rights to another LP. Every new
contribution opens a new account; it cannot top up an old loss-recovery account.
Accounts remain nontransferable. A full exit request excludes that account
from underwriting new bets, while its existing obligations run off. Permit
partial free cash releases during runoff. Preserve already funded exit claims
when new bets are paused. Do not promise an unconditional time for exposure to
clear during an oracle incident.

For this first model, **new deposits** still use a paused, zero-open-exposure,
fully reconciled window after a daily close. This is an entry restriction,
not a restriction on free-capital withdrawals. A broader deposit policy or
transferable fungible shares requires separate valuation and ownership rules.

Fully exited lots retain an immutable archive. New capital is a new lot;
previously paid/accrued fees cannot be escaped through withdrawal timing.
Changing wallets cannot transfer an old lot's loss recovery to new capital.
Existing contract LP shares cannot be migrated to these economics without a
funded reconciliation and an approved ownership/mark migration manifest.

The [daily LP integration candidate](RELEASE_DAILY_LP_INTEGRATION.md) now
implements real-token lot accounting and pause-safe free withdrawals in
isolated contracts. It reuses exported decisions from the papertrade Go
engine and supports signed journal batches with one net custody/LP transfer.
Its bounded account architecture requires per-deposit capacity authorization;
public scaling, production adapters and deployment reconciliation remain open.
Deposit windows span paused blocks after reconciliation, until a new bet or
outcome; no artificial same-timestamp requirement applies to the window.

A final void authenticated in a later accounting day can be queued without
releasing its original risk. Preceding closes retain that risk and use the
known final event as completeness evidence. Release/refund occurs once in its
canonical day. Never backdate a final void merely to unlock a daily close.

## 5. Funded rewards and inventory

Standard loss entitlement is `floor(stake * 200 / 10_000)` USDC units; the win
entitlement is `floor(loss_entitlement / 9)`. Welcome uses 1,000 bps, with a
$25 per-wallet limit, **$10,000 aggregate campaign limit**, and 100M FUSE
campaign inventory sublimit. Standard continuity begins with a separate
$10,000 allowance. Both allowances are subsets of the proposed $125,000
backing, not extra assets. These are finite candidate budgets; wallet caps
are not identity controls or an aggregate exposure limit.

Before accepting a rewarded bet, atomically reserve its larger dollar outcome,
worst-case token inventory, wallet allowance and aggregate campaign allowance.
Bind the reservation to account, bet ID, stake, both dollar entitlements,
maximum token requirement, reference redemption rate/window, policy version,
expiry and unique nonce. Settle/void once from canonical bet outcome evidence;
return only unused reservations. A stale UI quote must fail or be reconfirmed,
never turn into a smaller accepted reward. Serial durable acceptance must
remain correct across simultaneous requests and crashes.

Token reward entitlements and executable dollar minima are distinct. A dollar
minimum may be advertised only after the reviewed redemption mechanism ensures
it. The current offline model assumes 0% haircut, no reserve spending except
funded redemptions, and nondecreasing free backing per outstanding token.
Production must enforce these assumptions for accepted promises, bind a
usable redemption rate (not a higher intrawindow spot ratio), and ceil-reserve
enough tokens to deliver the minimum after claim rounding. A later policy,
funding change, pause or depleted inventory cannot reduce an accepted promise.
If those guarantees cannot be implemented within the original budget, revise
and approve the offer before launch; do not describe ordinary variable-price
FUSE as a guaranteed dollar payment.

No reward for a void or unfunded bet. A ticket with no funded offer may be
accepted only after showing zero reward and obtaining confirmation for those
terms. Publish the exact win/loss entitlement, inventory availability, quote
expiry, window/request deadlines and actual earliest claim timestamp before
commitment. Do not advertise instant or unconditional 24-hour redemption.

## 6. Backing, supply and redemption

Use 1B fixed genesis FUSE. Current contracts allocate 600M trader, 50M LP,
350M locked treasury; the older 600M/400M document is stale. This candidate
does not authorize a 950M trader reallocation. All outstanding supply,
including every locked/unclaimed escrow allocation, stays in the denominator.

```text
free_backing = reserve_USDC_balance - unpaid_redemption_claims
backing_per_FUSE = free_backing / total_outstanding_FUSE
```

Use nonoverlapping daily UTC windows, proposed `[00:00, next 00:00)` with 0%
haircut for the funded-reward candidate. Snapshot supply and free backing at
actual window start; show a delayed start honestly. Existing claims remain
funded when a later window starts. Burn tendered tokens once at request;
accrue each recipient's cumulative `floor(tendered * snapshot_backing /
snapshot_supply)` and reserve the incremental liability immediately. Claims
are available after that window's end and can be paid only once. Repeated
requests by one recipient use cumulative rounding. Across wallets, splitting
must not increase aggregate payout.

Funding added after a window snapshot affects later windows. Never use the
higher current spot backing to promise redemption at an older lower rate.
The final outstanding token burn stays disabled until a separately approved
residual policy is implemented. LP losses have no path into this reserve.

Pause new bets independently of existing payouts and redemptions. The
[current-source pause fix](REDEMPTION_PAUSE_INTEGRATION.md) now permits
authorized window scheduling, starting and requests during a betting pause,
while preserving activation, allowance, time, supply and backing guards.
Accrued claims remain payable. The new capability getter lets clients preserve
legacy behavior for older immutable deployments. Verify the actual deployed
capability and user path before making this promise; no deployment was changed
here. Authority to change haircuts/windows must still preserve accepted minima
and claims, which are not yet reserved/enforced per bet.

## 7. Pricing, economics and launch restrictions

The target 7–10% pricing edge is before rewards and is not operator income.
No exact value in that range is approved by this document. For payout `m`,
the model target survival is `(1 - edge) / m`; empirical conditional survival,
jumps, observation latency and strategic selection determine actual returns.
Changing the existing 500-bps Brownian setting to 700–1,000 bps does not
validate a corridor. Freeze candidates before evaluation and report every
supported pair, regime and predeclared strategy, with dependence-aware
uncertainty and rejected/censored opportunities preserved.

The [full-menu historical controls](RELEASE_PRICING_VALIDATION.md) now reject
all 108 asset/payout/edge settings of the current unfitted Brownian assumptions,
including 700–1,000 bps, even with LP-favorable unresolved-outcome bounds. These
unit-ticket results do not model funded admission or approve a replacement.
An edge-configuration change alone cannot satisfy the pricing release gate.

The subsequent [fitted empirical challenger](RELEASE_EMPIRICAL_PRICING.md)
also fails: at every tested edge, seventeen pairs receive quotes and all lose
LP gross even under the LP-favorable censoring bound; ten pairs receive none.
Strictly causal fitting on these previously inspected, nonconsecutive dates
does not establish current-regime calibration, high-payout support or a fresh
native holdout. This model must not be promoted as the economic specification's
validated pricing implementation.

The retained prospective BTC 2× adaptive trial failed collection quality.
Its compatibility replay and supplemental paper economics do not establish
funded native economics or approve other payouts/assets. Adaptive 1–8 ppm
quotes could not be represented unchanged through the historical nine-preset
integer-ppm fixed-table route. A new [native PPB table interface](NATIVE_PPB_INTEGRATION.md)
now supports exact widths and explicit preset subsets. The full retained-tape
funded replay and source-bound software audit are complete; a live adaptive
provider and release-model validation are still absent. Do not attribute old results to a new pricing
service or relabel that 4%-target trial as validation of this candidate.

Maximum direct current-dollar welcome subsidy is bounded by the global funded
campaign reservation, not wallet count. Retained FUSE can appreciate, so that
bound is not a bound on all future holder value or secondary-market proceeds.
Measure opposite-side/offset bets, deliberate losses, high payouts, LP/player
overlap and redemption timing against actual quotes. Negative player trading
EV does not by itself imply a nonextractable reward subsidy.

## 8. LP bootstrap and launch funding

Use $250k underwriting and $125k segregated backing as the user-selected funding
targets. Neither amount is available to pay operating bills. Operations cash
amounts and monthly spending limits are outside this document's scope at the
user's request; funding verification remains open. From that seed, the pool needs another
$2.75M underwriting equity to reach $3M. No funds or receipt have been verified.

The [LP bootstrap candidate](RELEASE_LP_BOOTSTRAP.md) reuses the existing up-to-50M
FUSE LP escrow, with one 90-day campaign and 30-day token vesting. Its proposed
time-local taper is `clamp((3M - E)/(3M - 250k), 0, 1)` on aggregate underwriting
equity, multiplied into eligible account capital-time. Awards also require
actual accepted liability-time against a proposed 20% utilization target.
Protocol/requested-exit capital cannot earn, and slots expire without catch-up.
No new score accrues at or above $3M; dropping below it can resume accrual only
within the original campaign. This never resets a campaign or extends it.
Already accrued rights survive exits, later TVL changes and betting pauses.
Token vesting adds no restriction to economically available LP withdrawals.

The 50M token ceiling bounds even wholly self-funded qualifying liability-time;
it does not establish organic demand or unprofitable LP/player farming. With
$125k backing and 1B outstanding tokens, the whole tranche has a $6,250 initial
backing equivalent, not a guaranteed future dollar value or APY. The new
`LPIncentiveDistributor.configureBootstrapCampaign` now implements the taper
against the current share vault, with local differential/randomized tests.
Its legacy configuration path remains untapered. Neither path is activated,
and the revised capital-account/free-withdrawal model is still absent from
those contracts. The parameters and reconciled implementation still need
approval and independent external review.

Worldwide distribution is the user's intended scope. The budget records this
without marking any jurisdiction or channel approved. Launch-region decisions,
distribution arrangements and funding verification remain required release
evidence, as do the separate capital and backing receipts.

## Approval record and required inputs

| Decision/evidence | Candidate or required record | Status |
| --- | --- | --- |
| Economic authority | Named owner, dated approval of this document's SHA-256 | Missing |
| Daily boundary/finality | User selected daily; proposed 00:00 UTC; canonical-outcome attribution | Time proposed |
| 5% base/order | New daily profit after losses/capital; fee before FUSE and expenses | User requirement; consolidated |
| LP ownership/withdrawals | Per-account marks and frozen bet ownership; partial free withdrawals anytime | User direction; mechanism proposed |
| Capital-protected profit | Defer unprocessed profit rather than forgiving its fee base | Proposed anti-avoidance change |
| Pricing | Frozen calibrated edge/model for each enabled pair | Missing |
| Capital | Approved dollar buffers, ceilings and simultaneous-win stress | Missing |
| Reward guarantee | Reviewed enforceable reservation/redemption design | Missing |
| Starting funds | User-selected targets: $250k LP + $125k backing | Targets selected; no funding verified |
| LP bootstrap | User requested incentives below $3M pool equity; proposed finite taper in linked candidate | Threshold requested; mechanism unapproved |
| Supply policy | Preserve current 600M/50M/350M allocations | Proposed |
| Operations/compliance | Worldwide distribution intent; named owners, regional/channel decisions and funding verification | Intent recorded; evidence missing |
| Independent reviews | Contract and pricing reports for reconciled immutable sources | Missing |

Any approval identifies the exact source hash and effective deployment. A
checkbox or model test cannot replace the owner's decision, a bank/onchain
funding receipt, an independent review, or jurisdiction-specific advice.
