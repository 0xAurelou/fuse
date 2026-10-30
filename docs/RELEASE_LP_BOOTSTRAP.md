# Below-$3M LP bootstrap — release candidate

30 October 2026 (WITA). **Proposed mechanism; opt-in contract path implemented
and locally tested, not activated or production approved.**
The user selected launch funding targets of $250,000 LP underwriting and
$125,000 segregated FUSE backing, and requested LP bootstrap incentives below
$3M. This proposal interprets $3M as aggregate pool underwriting equity, not
a wallet limit or an individual deposit size. Operations needs separate cash.
No funding receipts or escrow balances have been verified.

Reuse the existing **up-to-50M FUSE LP allocation**, within the fixed 1B supply.
Keep one 90-day declining campaign and 30-day vesting, with no guaranteed APY.
Do not mint, increase the 5% fee, spend LP cash on incentives, or divert backing
or operations cash. These are proposed uses of an existing allocation, not
approval to activate it. From a $250k seed, $2.75M more underwriting equity is
needed to reach the threshold; tokens do not supply that capital.

## Exact candidate rule

Let `E(t)` be actual aggregate net LP underwriting equity, including protocol
capital and capital still at risk during a pending exit. Exclude customer
custody, funded exit cash, accrued fee/backing transfers, segregated FUSE
backing and operations. Reconciled losses reduce equity. Never use an
end-of-day deposit snapshot to price the whole day's rewards.

```text
g(E) = clamp((3,000,000 - E) / (3,000,000 - 250,000), 0, 1)
capital_time = integral(E(t) dt)
liability_time = integral(accepted incremental LP liability(t) dt)
score_i = integral(eligible LP equity_i(t) * g(E(t)) dt)
utilization = min(1, liability_time / (capital_time * 20%))
reward_i = floor(scheduled_day_cap * utilization * score_i / capital_time)
```

Zero capital-time gives zero reward. All amounts use USDC/FUSE atomic units;
the reference uses exact rational scores and floors once per account per day.
The 20% utilization target is an inherited **research parameter**, subject to
capital stress and approval; it is not a recommended production risk level.
Capital/liability-time counts only reconciled, accepted risk, not turnover,
deposits, rejected demand or an expected future customer base.

Protocol capital and requested-exit portions do not earn, but remain in the
denominator while still underwriting. Partial free withdrawals preserve the
economic specification's ownership and loss marks. Checkpoint before each
capital, liability or eligibility change. Withdrawing free capital ends its
future score immediately; it does not cancel already accrued token rights.
Vesting restricts token claims, not withdrawal of otherwise free LP capital.
The candidate does not introduce an LP lock or an arbitrary exit delay.

At or above $3M, that interval's new score is zero. Rewards may resume for
later intervals below $3M within the same campaign. There is no permanent
TVL latch that a brief large deposit could use to disable everyone else's
campaign. Neither crossing the threshold nor withdrawing/redepositing starts
a new campaign, extends its end, or recovers an expired daily allocation.

For day `d` in `[0,90)`, use the existing contract's declining schedule:
`F(n) = floor(50M * n * (180-n) / 90²)`, `cap_d = F(d+1)-F(d)`.
All 90 caps sum exactly to 50M FUSE. Missed/unused slots remain locked,
with no catch-up, treasury sweep or reallocation. Once accrued, each daily
entitlement is immutable and claimable once, from day-end plus 30 days,
including after the LP exits or the pool later exceeds $3M.

## Scale of the subsidy

At $125k backing / 1B outstanding FUSE, the initial backing ratio is
$0.000125 per FUSE. The **whole 50M tranche corresponds to $6,250** at that
ratio. It is already included in the backing denominator. This is neither
additional operating cash nor a token market price or a promised dollar
return. Later backing additions, burns, haircuts and market prices can change
the value. Dollar value over all future states is not capped by $6,250.

The following upper-bound illustrations hold equity constant for 90 days,
assume it is entirely eligible external capital and meets target utilization.
They show this proposal's emission capacity, not predicted deposits or returns.
Actual protocol ownership, idle capital, later deposits and exits reduce awards.

| Constant pool equity | Taper factor | Maximum campaign FUSE, rounded down | Initial backing equivalent, approximately |
| --- | ---: | ---: | ---: |
| $250k | 100% | 50,000,000 | $6,250 |
| $500k | 90.91% | 45,454,545 | $5,682 |
| $1M | 72.73% | 36,363,636 | $4,545 |
| $2M | 36.36% | 18,181,818 | $2,273 |
| $2.75M | 9.09% | 4,545,454 | $568 |
| $3M or more | 0% | 0 | $0 |

If all initial $250k is protocol-owned, it earns **zero** bootstrap tokens.
An external contribution increases total equity, shares the denominator with
that seed and earns only for its own eligible capital-time. Seed ownership
must be disclosed and verified; the model does not assume the seed is external.

## Attacks, verification and implementation gap

The offline tests cover the exact finite schedule, zero demand, protocol/exit
exclusion, threshold crossings, time-weighted withdrawal, utilization scaling,
wallet splitting and rounding, vesting after exit, duplicate claims, skipped
slots and attempted campaign restart. Splitting otherwise identical ownership
across wallets cannot increase the aggregate rounded daily entitlement.

Even if all accepted liability-time is manufactured by overlapping LP/player
owners, this candidate cannot award more than 50M tokens in total. **Utilization
does not prove organic demand or make wash activity unprofitable.** Trading
profits/losses, trader rewards, fees and all other campaigns must still be
included in the combined-owner attack model. The global token bound survives
that failure; it does not prove this is an efficient acquisition expense.
No minimum cost to generate qualifying liability-time is established here.

`scripts/release_lp_bootstrap.py` is an exact offline reference. It assumes
truthful complete segments; it does not authenticate a journal, enforce block
time, serialize concurrent transactions, or prove ownership. The current
`LPIncentiveDistributor` now adds **`configureBootstrapCampaign(start,
utilizationBps)`**, which selects this fixed $250k-to-$3M taper for its one
finite campaign. Its index checkpoints old equity before relevant share,
eligibility and equity changes. Capital-time in the utilization denominator
remains untapered; eligible account scores receive the taper. The two index
divisions round downward, so the Solidity projection can award slightly less
than the rational reference, never more. Exact-reference vectors and randomized
deposit/time comparisons test that bound.

The existing `configureCampaign` method deliberately remains **untapered** for
legacy compatibility. Neither entry point can be used again after one is
selected. A release using the below-$3M rule must select the new bootstrap
method and verify `bootstrapCampaign() == true`, its fixed thresholds and its
original end. No campaign has been activated. Existing immutable deployments
cannot acquire this behavior without a separately reviewed deployment/migration.

The current share-vault still uses its previous **48-hour queued exits and
paused zero-exposure liquidity windows**. The taper adds no new lock, but that
vault is not the proposed daily capital-account/free-withdrawal implementation.
Do not present this contract change as completion of that separate requirement.

Local verification now includes eight dedicated Foundry tests, four independently
generated rational-vector scenarios, and 1,000 randomized deposit/time cases.
The full default contract suite passes **95 tests** with no failures/skips.
Tests include threshold crossings, the $250k full-rate boundary after losses,
zero accepted demand, mid-day deposits, queued exclusions, actual full exits,
claims during pause, and recovery below $3M without campaign extension.

An [internal review record](release/lp-bootstrap-review.json) binds the changed
distributor and dependent sources. Three workers covered twelve audit lenses
and reported no concrete new finding or actionable lead. This is not the
required independent external review; signed liability-time remains a trust
boundary and combined LP/player acquisition economics remain unproven.

Before activation, approve the taper, duration, budget and utilization target;
reconcile the implementation with the final capital-account/withdrawal design;
bind liability reports to the accepted-risk journal; and obtain the required
independent external review and deployed-configuration evidence. Show remaining campaign
capacity, current pool factor, exclusions, exact accrued tokens and actual
claim timestamps in the interface, without advertising a fixed APY.

Reproduce the focused checks with
`python3 -B -m unittest discover -s scripts -p 'test_release_lp_bootstrap.py'`.
The release evidence generator includes the exact integer scenario outputs
and source hashes. These checks do not approve a production incentive policy.
The separate contract verification packet is
`.local/release-bootstrap/20261030-contract-taper-v1/` and retains test logs,
source hashes and the rational-vector generator. Previous release packets keep
their historical offline-only scope.
