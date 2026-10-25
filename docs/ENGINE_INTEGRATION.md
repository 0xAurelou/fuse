# Engine integration

## Typed signatures

Use EIP-712 version `1`, the actual deployment chain ID, and destination module as `verifyingContract`:

| Message | Domain name | Authorities |
| --- | --- | --- |
| EpochSettlement | FUSE SettlementController | settlement and risk |
| ReserveAuthorization | FUSE LPVault | settlement and risk |
| WithdrawalAuthorization | FUSE WithdrawalGateway | withdrawal; optional account consent for redirects |

Read each module's exact `*_TYPEHASH`. The specification fields are followed by `uint256 signatureVersion` from `AccessController.signatureVersion()`. This is a signed struct field, not a caller-selectable parameter. Any signing-authority rotation invalidates pre-rotation messages. EOA signatures use canonical `r || s || v`; contract authorities/accounts use ERC-1271. Distinct settlement/risk addresses must also have independent controllers operationally.

Compare locally generated digests with `hashSettlement`, `hashReserveAuthorization` and `hashWithdrawal` before signing. Unit tests cross-check the encoding against Foundry's independent EIP-712 encoder. The full domain, all fields and the current signature generation are bound to the digest.

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

Bind the latest epoch/root, amount, minimum post-transfer LP capital, current realized profit HWM, unique ID and deadline. Settlement and risk both sign. Minimum capital must cover the checkpoint requirement. The configured fraction of current net profit above the consumed profit HWM bounds distribution. Deposits and donations cannot manufacture profit. LP capital never includes reserve balances.

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


Treasury allocation is separate from mining: governance may approve one immutable allocation root and manifest hash through the timelock. No policy is approved at deployment. Its double-hashed leaves encode `(uint256 chainId, address treasuryEscrow, uint256 index, address recipient, uint256 amount)` with sorted-pair proofs. Claims require both the policy and activated token transfers, use a bitmap, and cannot release more than the 400M allocation.
