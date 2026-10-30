# External LP participation

**Release-policy update:** the user's daily-accounting candidate requires
partial withdrawals whenever capital is free after accepted bets, known wins
and fee/backing reservations. Future-bet headroom and a delayed daily close
must not lock free principal. The [current release specification](RELEASE_ECONOMIC_SPEC.md#4-lp-ownership-and-capital-flows)
and executable reference use that rule. The isolated
[daily vault/custody candidate](RELEASE_DAILY_LP_INTEGRATION.md) now implements
these transitions with real test-token settlement and signed net batches
from shared-engine decisions. The share-vault implementation
described below still has the legacy 48-hour queue and zero-exposure windows;
it does not implement that release policy.

This implements the [LP participation amendment](LP_INCENTIVES_PROPOSAL.txt) for new deployments. `LPVault` continues to hold underwriting USDC; `LPShareVault` issues proportional equity shares and handles asynchronous redemption. `LPIncentiveDistributor` provides a finite bootstrap campaign. No public deployment or phase activation is performed by this change. The endogenous-capital research model and results remain in [the tokenomics report](TOKENOMICS_IMPLEMENTATION.md#external-lp-participation-amendment).

## Equity and settlement windows

USDC has six decimals and fLP has 18. Share conversions use OpenZeppelin ERC-4626's virtual asset (one atomic USDC) and virtual shares (10^12 atomic fLP). Direct donations do not increase accounted equity or manufacture profit. Shares are nontransferable to preserve phase eligibility, capital-owner reward accounting and protocol-capital exclusion.

```text
LP equity = min(accounted LP cash, actual LP USDC) − funded exits − accrued reserve fees
share NAV = (LP equity + 1) / (share supply + 10^12)
```

Equity can lose value and reach zero. fLP represents underwriting risk; its reported NAV is not a guaranteed immediately withdrawable balance. Required capital and incremental guaranteed liabilities exclude both funded exits and reserve fees. Token redemption backing is held separately and never funds LP losses.

External deposits and exit fulfillment require a zero-exposure checkpoint no older than one hour, plus a settlement-created liquidity window. The engine must hold its exclusive acceptance lock, reconcile all accepted obligations, obtain both report signatures, and call `SettlementController.settleAndPause`. The controller must hold `GUARDIAN`; it atomically settles, pauses, and records the current epoch and pause nonce. Plain guardian pauses do not open a window. Every resume or pause changes the nonce, so an old window cannot be reused, including within one block. Actual exposure and oracle/report truth remain dual-attested operator obligations.

## Phases and capacity

Governance advances exactly one phase at a time; transitions require fresh zero-exposure NAV and cannot be reversed:

| Phase | Admission | Economics |
| --- | --- | --- |
| Protocol | `LP_PROVIDER` accounts; capital permanently marked protocol-owned | Legacy gross-profit reserve accounting; shares issued for every seed contribution |
| Whitelisted | `LP_PROVIDER` receivers, fresh demand capacity and liquidity window | Permanent LP-first share waterfall; optional bootstrap campaign |
| Public | Any receiver under the same capacity/window gates | Same waterfall and remaining finite campaign |

The constructor's hard cap is 5M USDC, matching the proposed seed assumption; it does not create or supply that capital. The local backend retains its existing seed configuration. Governance may set `setDepositPolicy(hardCap, targetUtilizationBps)`; target utilization defaults to 20%. The external equity cap is:

```text
min(hard cap, eligible demand × 10000 / target utilization bps)
```

Deposits above this equity cap are rejected; existing equity is not forced out. Settlement and risk sign `CapacityAuthorization` for the latest checkpoint/root, monotonic nonce, eligible demand and deadline at most one hour away. Expired or zero-demand capacity admits no new external equity. Demand estimates must be tied to validated trader activity; contracts do not independently reconstruct prospective demand. Legacy `LPVault.depositLP` also mints shares and respects the same admission/cap rules.

## LP-first profit rights

Advancing to Whitelisted permanently enables share economics. At settled zero-exposure checkpoints, profit is measured against a **per-share high-water mark**. The old mark is scaled to the current share supply with upward rounding; fair-NAV contributions and exits cannot reset loss recovery. First recover prior losses. Only profits above that adjusted mark can accrue a reserve fee.

The allocation is capped at 3500 bps in code. For equity E and signed required capital C, the candidate ramp is `cap × clamp((2E−3C)/(3C), 0, 1)`, with the full cap when C is zero. Allocation also retains at least 2C. Profits protected by the capitalization gate raise the high-water mark immediately, so a later deposit cannot make them chargeable retroactively. At the full rate, 200k USDC of new eligible profit leaves 130k in LP equity and accrues 70k to FUSE backing. There are no additional operating/performance fees in this implementation.

Accrued fees are liabilities excluded from share NAV immediately. They enter the redemption reserve only after a dual-signed `fundFUSEReserve` authorization. Moving already accrued fees changes cash and the liability equally, preserving LP NAV. Reducing the future allocation rate to zero does not cancel previously accrued fees; `reserveAllowance` in share mode returns the accrued balance and uses 3500 bps only for legacy consumed-profit telemetry. Post-funding equity must retain twice the greater of signed minimum and required capital. Protocol-only deployments retain legacy gross-profit/consumed-profit behavior until phase advancement, with the same new 35% maximum.

## Asynchronous exit API

The vault follows [ERC-7540 asynchronous redemption](https://eips.ethereum.org/EIPS/eip-7540) with synchronous [ERC-4626 entry](https://eips.ethereum.org/EIPS/eip-4626). It advertises ERC-165, ERC-7540 operators/redeem and ERC-7575; it does not advertise asynchronous deposits.

1. `deposit(assets, receiver)` / `mint(shares, receiver)` issue equity at current valid NAV. Approve USDC to the share vault first.
2. `requestRedeem(shares, controller, owner)` escrows shares in FIFO order. `activeRequest(owner)` tracks one active request per share owner; `controllerRequest(controller)` separately tracks the controller's claim, also limited to one active request. Both slots remain occupied until the full claim is paid. Owners, their approved operators or share-allowance spenders can request with the owner as controller. A different controller must be an approved operator of the owner, and must either submit the request itself or approve the requester as its operator. Approving someone as your operator does not let you occupy their controller slot without their consent. Requests must cover at least 1 USDC at current accounted NAV; `minRedeemShares()` returns this floor in shares, rounded up. Smaller balances must be topped up before requesting an exit. There is no cancellation. Pending shares continue bearing PnL and earn no bootstrap rewards.
3. After at least 48 hours, anyone may `fulfillRedeem(requestId)` at a newer zero-exposure checkpoint whose signed `asOfTimestamp` is at or after the request's ready time. A valid liquidity window and a remaining 2C floor are required. Shares burn at **fulfillment NAV**, and USDC is segregated as a funded exit liability. FIFO head blocking can extend waits indefinitely; 48 hours is a minimum, not a payout promise.
4. Controller or its approved operator calls `redeem` or `withdraw` to pull the claimable assets. Partial claims use cumulative rounding and cannot increase total entitlement. `LPVault.requestLPExit()` and `executeLPExit()` are full-balance compatibility helpers after share economics is enabled.

`pendingRedeemRequest` and `claimableRedeemRequest` report the lifecycle. `maxRedeem` and `maxWithdraw` return funded claims, not the active share balance. `previewRedeem` and `previewWithdraw` always revert, as required for asynchronous redemption. Funded claims remain available during pauses and after NAV expiry. Operators are explicitly trusted to choose claim recipients; revoke them with `setOperator(operator, false)`.

## Temporary FUSE campaign

Genesis allocation is **600M trader mining + 50M LP bootstrapping + 350M locked treasury = 1B FUSE**. The LP allocation is deducted from the formerly unassigned treasury allocation, not minted later. All three escrows remain in the outstanding-supply backing denominator until tokens are burned.

Deployment binds the new LP escrow to `LPIncentiveDistributor` and the distributor to the share vault. Governance configures one future/current campaign start and utilization target. The campaign lasts 90 days; its daily linear-decay caps sum to exactly 50M. There is no extension, catch-up, extra allocation or treasury sweep. Unused tokens remain locked.

Capital-time is checkpointed onchain before every balance/equity change, split at daily boundaries. Each external account's score is its active equity integrated over time. Protocol-owned capital and queued shares get no reward; both remain in the total invested capital-time denominator while bearing underwriting risk. Claimable exits and reserve fees are excluded from equity. Flooring is conservative, so dust and excluded-capital allocations remain escrowed.

Settlement and risk attest **accepted incremental liability × seconds actually at risk**, with a journal hash, for each completed daily slot. `LP_REWARD_PUBLISHER` publishes only during the next 24 hours, with increasing slot IDs. Missed slots expire. The operator supplies no account scores or reward Merkle tree:

```text
slot budget = scheduled cap × min(1, actual liability-time / (total capital-time × target utilization))
account reward = slot budget × eligible account capital-time / total capital-time
```

Zero demand gives zero budget; idle or protocol capital cannot mine the full schedule. Liability-time is dual-attested rather than independently proven onchain. Anyone may relay `claim(epoch, account)` after the slot ends plus 30 days, paying only that account, once. Vested escrow releases can occur before general FUSE transfer activation, but distributed tokens remain nontransferable until activation. Claims do not expire.

The [release bootstrap candidate](RELEASE_LP_BOOTSTRAP.md) now adds a separate
`configureBootstrapCampaign(start, utilizationBps)` entry point. It applies a
capital-time taper of `clamp((3M - equity)/(3M - 250k), 0, 1)` to eligible
account scores, with an untapered total-capital denominator. At/above $3M new
score is zero; later lower equity can resume it only within the original
90-day campaign. Existing claims survive the threshold, exit and pause. The
legacy `configureCampaign` remains untapered, and configuration is still
one-time across both paths. New defaults remain campaign-inactive. This does
not replace the current exit queue or implement the proposed daily capital
accounts; production reconciliation and independent external review are open.

## Backend and launch operations

New manifests pin the share vault and distributor artifacts, ABI hashes and code. The local engine journals `LPExitReserved`, `LPExitPaid` and `ReserveFeeAccrued`; it checks gross cash, fee liability, exit liability and usable underwriting equity separately. Zero-valued added journal fields are omitted to preserve old replay hashes. Older manifests without the optional modules remain loadable.

Operator-authenticated local endpoints:

| Endpoint | Action |
| --- | --- |
| `POST /local/lp/liquidity-window` | Exclusive-lock reconciliation, signed zero-exposure checkpoint, atomic settle and pause |
| `POST /local/lp/capacity` | Dual-signed demand cap; body `{"eligible_demand_usdc_units": 1000000000000}` |
| `GET /v1/tokenomics` | Confirmed LP phase, shares, equity, cap, queue IDs, realized PnL, exposure, fees, exits, settled peak NAV/max drawdown and campaign state |

Mutation requests require `Idempotency-Key`; capacity-key reuse with changed demand fails. Resume trading through the existing operator flow after capital movements are reconciled. The supplied Go typed helpers encode both new EIP-712 domains, and capacity publication cross-checks its digest against the contract. Daily liability journals must be reviewed and published through `publishEpoch`; no automatic reward publisher is enabled by this change.

Fresh deployments remain paused, Protocol-only, and campaign-inactive. Phase advancement, caps, reward activation and public admission require explicit governance transactions. These immutable contracts cannot migrate already deployed 400M treasury escrows; existing deployments require a separately reviewed migration rather than changing an allocation in place. The initial multisig bootstrap installs no treasury release policy.

Tests cover the lifecycle, 65/35 economics, loss recovery, protected capitalization profits, demand caps, nonce invalidation, vesting, protocol/queue exclusions and conservation. The isolated Anvil/PostgreSQL/backend E2E includes a complete LP exit. Formal scope is listed in [FORMAL_VERIFICATION.md](FORMAL_VERIFICATION.md). Economic simulations remain independent evidence: severe correlated-winner drawdowns and long queues in the research matrix are unresolved launch risks. Simulated rolling loss budgets and recovery probes are not installed as engine admission controls here. No independent assessment or public launch is implied by the passing accounting tests.
