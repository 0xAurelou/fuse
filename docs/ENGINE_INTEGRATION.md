# Engine integration

## Typed signatures

Use EIP-712 version `1`, the actual deployment chain ID, and destination module as `verifyingContract`:

| Message | Domain name | Authorities |
| --- | --- | --- |
| EpochSettlement | FUSE SettlementController | settlement and risk |
| ReserveAuthorization | FUSE LPVault | settlement and risk |
| WithdrawalAuthorization | FUSE WithdrawalGateway | withdrawal; optional account consent for redirects |
| CapacityAuthorization | FUSE LPShareVault | settlement and risk |
| LPUtilizationReport | FUSE LPIncentives | settlement and risk; publication also requires LP_REWARD_PUBLISHER |

Read each module's exact `*_TYPEHASH`. The specification fields are followed by `uint256 signatureVersion` from `AccessController.signatureVersion()`. This is a signed struct field, not a caller-selectable parameter. Any signing-authority rotation invalidates pre-rotation messages. EOA signatures use canonical `r || s || v`; contract authorities/accounts use ERC-1271. Distinct settlement/risk addresses must also have independent controllers operationally.

Compare locally generated digests with `hashSettlement`, `hashReserveAuthorization`, `hashWithdrawal`, `hashCapacity` and `hashUtilization` before signing. Shared Solidity/Go golden vectors cover these domains. The full domain, all fields and the current signature generation are bound to the digest.

## Settlement and reconciliation

1. Index deposits by `(chainId, custodyAddress, depositId)`, preserving payer, beneficiary and amount. Credit once. Observe timed-out refunds and apply a chain-confirmation/reorg policy before accepting offchain obligations.
2. Start at epoch 1, prior root zero, sequence 1. Subsequent epochs are exactly `latestEpoch + 1`, `priorRoot == currentRoot`, `fromSequence == lastSequence + 1`, and `toSequence >= fromSequence`. Journal and oracle hashes are nonzero. Timestamps cannot regress or be in the future.
3. Hash the ordered deposit array as `keccak256(abi.encode(uint256[] depositIds))`, including the standard ABI offset and length. Empty batches also use ABI encoding. Unknown, repeated, credited or refunded IDs revert.
4. Replay accepted trades against the **HyperCore BTC oracle** journal. Reconcile deposits, refunds, actual onchain withdrawals, all earlier settlements and open liabilities. Customer liability must reflect remaining obligations at execution, not a pre-withdrawal snapshot. Coordinate operator settlement production with withdrawal observation to avoid stale liability reports; contracts cannot independently repair offchain accounting races.
5. Positive trader PnL funds custody from LP; negative PnL funds LP from credited custody. Report the exact post-movement LP realized profit HWM. Risk attests required capital and open exposure; actual capital must cover required capital, which must cover reported exposure.
6. Any relayer may call `settle(report, depositIds, settlementSignature, riskSignature)`. Persist the complete report, deposit array and signatures. `CheckpointFinalized` and `checkpointHash` commit the report but do not store all its fields. Update canonical operator state only after confirmation.

The external risk service must guarantee maximum contractual payouts for all accepted stages before new acceptance, verify liabilities independently, and exclude token reserve backing from underwriting capital. Signatures and onchain solvency checks do not prove trading outcomes or oracle correctness.

## Withdrawals

Remove the request from spendable engine funds before issuing an authorization. `stateVersion` is its supporting finalized checkpoint epoch, nonzero and no greater than `latestEpoch`. The signature attests `accountStateHash`; there is no onchain account-state inclusion proof. Total payouts are bounded by custody's remaining funded liability.

Maintain one cumulative entitlement per account across all authorizations. A claim pays `cumulativeAmountUSDC - withdrawnCumulative[account]`. IDs are nonzero and unique across the gateway; never reuse an ID for a top-up. Spent, expired or non-increasing authorizations fail. An older authorization can still pay its remaining delta if no higher cumulative entitlement has been paid.

Recipients default to the account wallet. For redirects the account must either submit directly or independently sign the **same typed authorization digest**. Relayers supply this account signature as `recipientConsent`. ERC-1271 supports contract wallets. Operator signature alone cannot redirect funds.

Guardian pauses preserve valid funded claims. After signing rotation reissue unclaimed authorizations with the current generation and unchanged cumulative history. Fresh claims require operator availability; V0 has no forced exit or protection against dishonest dual-signed trading accounting.

## Reserve authorizations

Bind the latest epoch/root, amount, minimum post-transfer LP capital, current realized profit HWM, unique ID and deadline. Settlement and risk both sign. Minimum capital must cover the checkpoint requirement. The v2 allowance requires recovery to the historical profit HWM, uses the equity/capital solvency ramp, and retains at least twice required capital. `LPVault.reserveAllowance(minCapital)` reports the current amount and effective bps. Consume profit at the effective rate, rounded up, so a profit dollar cannot be distributed twice. Deposits and donations cannot manufacture profit. LP capital never includes reserve balances.

Once Whitelisted LP participation is enabled, the per-share waterfall supersedes this protocol-only allowance calculation. Profits accrue reserve fees at settlement after loss recovery/capitalization, with a 35% ceiling. The allowance becomes the accrued fee liability, subject to retaining twice the capital requirement. Funding an accrued fee reduces gross cash and fee liability equally, preserving LP equity. The legacy realized/consumed-profit fields remain journal telemetry and signature inputs. Read `shareEconomics()` and the actual onchain allowance rather than deriving an allowance from gross profit in external-LP mode.

## LP shares, cash liabilities and liquidity windows

Index `LPDeposited`, `ReserveFeeAccrued`, `LPExitReserved`, `LPExitPaid` and `ReserveFunded`. Physical LP cash includes funded exits and accrued fees; **usable LP equity excludes both**. Every quote-admission, buffer, exposure and checkpoint capital check must use usable equity. Never count an exit liability twice or allow it to fund trader wins. A claim pays from reserved cash without reducing the remaining LP share NAV. Account the two liabilities separately and reconcile against onchain getters; the Go journal omits new zero-valued fields to preserve prior replay hashes.

External capital moves only in a fresh, zero-exposure settlement window. Hold the same exclusive engine lock used by trade acceptance while reconciling, signing and executing `settleAndPause`. Its caller and the controller need `GUARDIAN`. The atomic transaction finalizes the report, pauses and records `(navEpoch, pauseNonce)`. Any later pause or resume invalidates the window; a plain pause never opens one. Reconcile LP events before resuming trading. Do not reuse an old zero-exposure report while the engine has accepted new guarantees. Settlement `asOfTimestamp`, rather than transaction time, determines exit eligibility.

The local operator API provides `POST /local/lp/liquidity-window` and `POST /local/lp/capacity`, with operator authentication and `Idempotency-Key`. Capacity body: `{"eligible_demand_usdc_units": 1000000000000}`. The latter independently checks the local digest against `hashCapacity` before both signatures. Demand must reflect eligible validated trader activity. Reusing a capacity key with changed demand is rejected. These are local-development APIs; real signing infrastructure still supplies production attestations.

Exact new EIP-712 struct schemas (append the current `uint256 signatureVersion` as shown):

```text
CapacityAuthorization(uint64 epoch,bytes32 checkpointRoot,uint256 eligibleDemandUSDC,uint256 nonce,uint256 deadline,uint256 signatureVersion)
LPUtilizationReport(uint64 epoch,uint256 liabilitySeconds,bytes32 journalHash,uint256 deadline,uint256 signatureVersion)
```

Capacity binds the latest root/epoch, next nonce and a deadline at most one hour away. Incentive epochs are daily campaign slots, not settlement IDs. Publish only a completed slot in its next 24 hours, with actual accepted incremental USDC liability multiplied by seconds at risk and a reconciled evidence hash. Onchain capital-time supplies account weights; no LP reward Merkle root is accepted. Protocol/queued capital has zero eligible account weight. Vested claims start 30 days after slot end. Daily publishing is not automated by the local API. See [LP participation](LP_PARTICIPATION.md) for the full lifecycle and launch defaults.

## Reward and redemption manifests

Reward leaves use OpenZeppelin StandardMerkleTree's double-hashed ABI format:

```solidity
keccak256(bytes.concat(keccak256(abi.encode(
    uint256(chainId), address(distributor), uint64(epoch),
    uint256(index), address(recipient), uint256(amount)
))))
```

Use sorted-pair Merkle proofs and unique indices per epoch. Anyone can relay; payment goes to the committed recipient. Publish an immutable root, bounded budget and manifest hash. Public manifests must disclose allocations and their reconciliation to accepted risk and completed-stage journal entries. Outcome weights, journal correctness and manifest availability remain offchain. Independently check the allocation sum before publication: a root exceeding its budget cannot overspend escrow, but can exclude later claimants.

Redemptions accrue at request time and become claimable at epoch end. Per-account accrued USDC is:

```text
floor(cumulativeFUSE * (10000 - penaltyBps) * reserveSnapshot / (supplySnapshot * 10000))
```

Use one floor of the full expression. Index epoch snapshots, requests, burns and claims. Funding during an epoch does not change its price. Later snapshots subtract all unpaid claims, count the entire token supply including escrows, and retain penalties and rounding residuals as backing.


Treasury allocation is separate from mining: governance may approve one immutable allocation root and manifest hash through the timelock. No policy is approved at deployment. Its double-hashed leaves encode `(uint256 chainId, address treasuryEscrow, uint256 index, address recipient, uint256 amount)` with sorted-pair proofs. Claims require both the policy and activated token transfers, use a bitmap, and cannot release more than the 350M allocation. New genesis allocation reserves 600M for traders and 50M for LPs, keeping total supply at 1B. All three escrows count in the redemption denominator.

V2 mining manifests commit their complete scoring policy, per-stage evidence, total score, requested/activity/used budgets and root. The linear exposure rule has no V0 streak bonus or wallet cap. Current emission slots expire without catch-up and require an immutable finite horizon. See `GET /v1/tokenomics` for confirmed local disclosures.
