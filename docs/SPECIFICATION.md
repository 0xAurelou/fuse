# FUSE 100 — Smart Contract Specification

**Version:** 0.1 — Implementation draft  
**Network:** HyperEVM (mainnet 999, testnet 998)  
**Language:** Solidity 0.8.24+  
**Tooling:** Foundry, OpenZeppelin Contracts 5.x

## Architecture principles

FUSE uses an operator-secured deterministic trading engine. Smart contracts provide USDC custody, LP funding, net settlement, withdrawal claims, FUSE issuance, mining distributions and reserve-backed redemptions.

Every accepted Fuse remains an offchain obligation. Its settlement reference is the HyperCore BTC oracle, not BBO or mark price.

The initial contract system is **not trustless**. A checkpoint verifies that a state was committed, not that the trading engine calculated it correctly.

## Contract 1 — CustomerCustodyVault

**Purpose:** Hold deposited USDC and pay users their finalized withdrawal entitlements.

Core functions:

- `deposit(amount, beneficiary)` — Transfer USDC into custody and emit a uniquely identified deposit receipt.
- `acknowledgeDeposits(ids, epoch)` — Mark deposits as credited by a published settlement checkpoint.
- `refundUncreditedDeposit(id)` — Refund a deposit that has not been credited after a defined timeout.
- `payUser(recipient, amount, authorizationId)` — Transfer USDC following a verified withdrawal authorization.
- `transferRealizedLossToLP(amount, epoch)` — Move realized net customer losses to the LP vault under an approved settlement.

Requirements:

Every deposit has a unique ID and can only be credited or refunded once. Uncredited deposits remain protected and cannot be swept into LP funds.

The vault must use exact-transfer accounting and reject unexpected fee-on-transfer behavior. No administrator can perform arbitrary USDC withdrawals.

**Access:** Deposits are permissionless. Settlement and payout operations are restricted to their designated contracts.

## Contract 2 — LPVault

**Purpose:** Hold USDC underwriting capital and fund accepted winning payouts.

Core functions:

- `depositLP(amount)` — Add authorized LP capital.
- `fundNetTraderWins(epoch, amount)` — Transfer USDC to customer custody following a realized net LP loss.
- `receiveNetTraderLosses(epoch, amount)` — Record the USDC received from realized trader losses.
- `fundFUSEReserve(authorization, signatures)` — Transfer eligible realized profits into the segregated token reserve.
- `requestLPExit()` / `executeLPExit()` — Controlled LP capital withdrawals, disabled for public LP participation in V0.

Risk requirements:

1. New Fuse acceptance is rejected offchain if the LP cannot guarantee its maximum contractual payout.
2. Accepted liabilities must not depend on new deposits or future trader losses.
3. LP profit distributions cannot reuse capital already distributed.
4. Reserve funding requires an adjusted profit high-water mark and a post-transfer capitalization check.
5. A distinct risk approver must authorize capital-moving settlements.

The current candidate is a 35% maximum allocation of eligible profits, potentially increasing to 50% when sufficiently capitalized. These values remain configurable and require calibration.

No ERC-4626 LP shares in the initial implementation. Public LP participation introduces valuation and exit-liquidity requirements that should be handled separately.

## Contract 3 — SettlementController

**Purpose:** Apply aggregated USDC net settlements and publish ordered accounting commitments.

Each epoch report contains:

```solidity
struct EpochSettlement {
    uint64 epoch;
    bytes32 priorRoot;
    bytes32 newRoot;
    bytes32 journalHash;
    bytes32 oracleJournalHash;
    uint64 fromSequence;
    uint64 toSequence;
    uint64 asOfTimestamp;
    int256 netTraderPnLUSDC;
    uint256 customerLiabilityUSDC;
    uint256 reportedMaxOpenExposureUSDC;
    uint256 reportedRequiredLPCapitalUSDC;
    uint256 realizedProfitHWMUSDC;
    bytes32 depositBatchHash;
    uint256 deadline;
}
```

A positive `netTraderPnLUSDC` means LPVault owes money to customer custody. A negative value means realized trader losses are payable to LPVault.

The controller verifies ordered epochs, valid EIP-712 attestations from separate settlement and risk authorities, deposit acknowledgments and permitted capital movements.

USDC must actually move before a checkpoint asserting newly funded withdrawals is finalized.

A failed or insufficiently funded settlement reverts atomically.

**Important:** The reported PnL and liabilities are operator-produced figures. Onchain signatures do not independently verify the trading outcomes.

## Contract 4 — WithdrawalGateway

**Purpose:** Allow users to claim USDC without performing every trading operation onchain.

The engine first removes the requested funds from the user's spendable offchain balance, then issues an EIP-712 withdrawal authorization.

```solidity
struct WithdrawalAuthorization {
    address account;
    address recipient;
    uint256 cumulativeAmountUSDC;
    uint64 stateVersion;
    uint64 validUntil;
    bytes32 authorizationId;
    bytes32 accountStateHash;
}
```

The contract maintains:

```solidity
mapping(address => uint256) withdrawnCumulative;
```

For a valid authorization:

```solidity
amountToPay =
    authorization.cumulativeAmountUSDC
    - withdrawnCumulative[account];
```

The cumulative value prevents old and new authorizations from paying the same entitlement twice.

The destination must equal the account wallet unless the user independently authorizes a different recipient.

All withdrawals use replay protection, expiry checks, checks-effects-interactions ordering and a reentrancy guard.

Previously issued funded claims remain executable while valid, but **the absence of a forced-exit protocol means fresh withdrawals still depend on operator availability**.

## Contract 5 — FUSEToken

**Purpose:** Fixed-supply ERC-20 earned through trading activity.

Initial candidate allocations:

| Allocation | Tokens |
|---|---:|
| Emission escrow | 600,000,000 FUSE |
| Locked treasury escrow | 400,000,000 FUSE |
| Total genesis supply | 1,000,000,000 FUSE |

No public minting function exists after deployment.

Transferability begins disabled. Reward distribution can transfer tokens from the designated escrow to users, but users cannot freely trade FUSE until activation.

`enableTransfers()` is an irreversible, timelocked operation.

The Reserve contract may burn tokens voluntarily tendered for redemption. Burned FUSE cannot be reissued.

The 400M treasury allocation remains locked until a separate allocation policy is approved.

## Contract 6 — RewardDistributor

**Purpose:** Distribute FUSE mining rewards in epochs without minting tokens after each trading stage.

Offchain reward scoring uses actual accepted risk and completed stage outcomes.

Initial outcome weights:

| Outcome | Weight |
|---|---:|
| Survived stage | 1.0 |
| Exploded stage | 0.2 |

Core functions:

- `publishEpoch(epoch, merkleRoot, budget, manifestHash)`
- `claim(epoch, index, recipient, amount, proof)`
- `isClaimed(epoch, index)`

Each epoch has a bounded token budget and an immutable claim root.

Total allocations can never exceed the 600M mining escrow. Claims are checked for replay using a claimed-index bitmap.

The emission schedule declines over time. The provisional 20-day half-life is a simulation candidate, not a final contract constant.

Reward-score correctness remains offchain. Public reward manifests must support independent reconciliation against the trading journal.

## Contract 7 — RedemptionReserve

**Purpose:** Maintain the USDC backing allocated to FUSE and execute discounted redemptions.

Only LPVault may add protocol profit funding.

Backing is strictly segregated from LP trading capital.

Each redemption epoch snapshots:

```solidity
struct RedemptionEpoch {
    uint64 epochId;
    uint64 start;
    uint64 end;
    uint16 penaltyBps;
    uint256 supplySnapshot;
    uint256 availableReserveUSDC;
    uint256 requestedFUSE;
    uint256 accruedUSDC;
}
```

A user's redemption amount is determined from that epoch's fixed backing rate:

\[
USDC = \left\lfloor
\frac{FUSE_{burned}\times R_{snapshot}}
{S_{snapshot}}
\times(1-f)
\right\rfloor
\]

Where `f` is the redemption penalty.

All users in the epoch receive the same net price, subject to integer rounding. Cumulative per-account request calculations prevent transaction-splitting advantages.

Core functions:

- `fundReserve(amount)`
- `openRedemptionEpoch(start, end, penaltyBps)`
- `requestRedeem(amount)`
- `claimRedeemedUSDC(epoch)`

All tendered FUSE is burned. The portion of backing not paid because of the penalty remains in the reserve.

Outstanding USDC redemption liabilities are deducted before subsequent epoch snapshots.

The backing denominator counts the entire outstanding token supply, including tokens in emission and treasury escrows.

Candidate penalties are 10% and 20%. The exact rate and final-residual policy require approval before activation.

## Contract 8 — AccessController

Use role-based permissions, multisig governance and timelocks.

Separate authorities for settlement signatures, LP risk approval, withdrawal signatures, emission publication, redemption scheduling and emergency pausing.

Requirements:

- Settlement and risk signatures must be independently controlled.
- Guardian pauses must not give the guardian withdrawal authority.
- Role rotation must invalidate compromised signing domains.
- Upgrades must be timelocked or avoided for custody-critical immutable modules.
- Emergency procedures must distinguish suspending new trading from honoring funded user withdrawals.

## Required accounting invariants

The Foundry suite must enforce:

1. A deposit cannot be both credited and refunded.
2. A settlement epoch executes at most once.
3. No withdrawal authorization pays twice.
4. No uncredited customer deposit funds LP profit transfers.
5. LP and customer net settlements conserve USDC.
6. FUSE mining allocations never exceed escrowed emissions.
7. Burns monotonically reduce FUSE total supply.
8. Outstanding redemption claims remain fully funded.
9. Reserve USDC is never counted as LP underwriting capital.
10. Redemption order and transaction splitting do not change economic payouts beyond explicitly bounded rounding.
11. Reentrancy and signature replay cannot duplicate claims.
12. No signer can arbitrarily redirect user funds.

Additional offchain invariants must verify accepted-stage collateralization, oracle sequencing, customer liabilities and high-water-mark accuracy.

## Deployment sequence

**Phase 1:** CustomerCustodyVault, LPVault, SettlementController, WithdrawalGateway. Implement custody, deposit refunds, cumulative withdrawals, net settlements and reconciliation.

**Phase 2:** FUSEToken, allocation escrows, RewardDistributor, RedemptionReserve. Implement token supply, vesting restrictions, emissions and redemptions.

**Phase 3:** Integrate Rust trading engine, oracle observation journal, replay-based accounting and epoch manifests.

**Phase 4:** Foundry fuzz/invariant testing, testnet deployment, independent review and stress testing.

## Production blockers

The contract specification can guide development now, but production funding requires final decisions on oracle outage treatment, independent withdrawal recovery or explicit acceptance of operator custody risk, LP exposure verification, token allocation, redemption fee, and emission activation.

No customer USDC should be accepted for live trading before these conditions and security reviews are complete.