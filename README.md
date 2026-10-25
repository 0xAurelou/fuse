# FUSE 100 contracts

Foundry implementation of the [V0.1 specification](docs/SPECIFICATION.md). Solidity 0.8.24, OpenZeppelin Contracts **5.0.2**, Paris EVM target. Immutable modules, one-time counterparty wiring, no proxies or administrator asset sweeps.

This is an operator-secured custody system. Signatures commit operator accounting; they do not prove trading outcomes, oracle observations, entitlements or open exposure. Live funding requires the specification's final policy decisions and independent security review.

## Build and test

```sh
forge install
forge fmt --check
forge build --sizes
forge test --offline
FOUNDRY_PROFILE=ci forge test --offline
```

Bounded formal verification is available separately:

```sh
python3.12 -m venv .venv-formal
.venv-formal/bin/python -m pip install -r formal/requirements.txt
PATH="$PWD/.venv-formal/bin:$PATH" python3 scripts/verify_formal.py
```

The verifier runs concrete proof witnesses, unbounded integer accounting lemmas, and symbolic EVM checks against the real protocol modules. CI rejects missing proofs, timeouts, counterexamples, blocked paths, all-reverting harnesses and loop truncation. See [formal verification scope and assumptions](docs/FORMAL_VERIFICATION.md); this is bounded verification, not a complete proof of the protocol or offchain engine.

`--offline` also avoids a macOS Foundry 1.5.1 system-proxy discovery crash in restricted environments. CI covers unit tests, fuzz tests and stateful accounting invariants; unexpected invariant-handler reverts fail the suite.

## Modules

| Contract | Responsibility |
| --- | --- |
| AccessController | Timelock governance, separate signers, signing generation, operational roles and guardian pause |
| CustomerCustodyVault | Exact USDC deposits, protected pending receipts, payer refunds and funded payouts |
| LPVault | Authorized capital, net settlements, adjusted profit consumption and dual-signed reserve funding |
| SettlementController | Ordered epochs, roots, contiguous sequences, deposit acknowledgments and atomic solvency checks |
| WithdrawalGateway | Expiring cumulative claims and independent account consent for redirects |
| FUSEToken | Fixed 1B supply, 600M emission escrow, 400M locked treasury, delayed transfers and allowance-backed redemption burns |
| RewardDistributor | Immutable Merkle epochs, declining budget caps, allocation ceiling and claimed-index bitmap |
| RedemptionReserve | Segregated backing, fixed-price epochs, cumulative burn pricing and funded USDC claims |

USDC uses atomic units (six decimals for the intended asset), FUSE 18 decimals. Both sender and recipient USDC balance deltas must equal the requested transfer. Fee-on-transfer and rebasing assets are unsupported. No network token address is hardcoded.

## Implementation choices

- Deposit IDs start at 1. Anyone can trigger a timed-out pending refund, always to its payer. Credit and refund race onchain: the first successful transaction wins. The engine must reconcile refunds before accepting offchain obligations.
- A checkpoint's customer liability is the **remaining** payable balance at execution, after prior onchain payouts and included deposits. Custody retains that liability plus all uncredited funds. Withdrawals reduce this liability.
- Positive trader PnL funds custody from LP; negative PnL funds LP from credited custody. Any failed funding, capital, liability or HWM check rolls back the entire epoch.
- LP cumulative realized profit is measured before reserve distributions. Its HWM is the greatest positive cumulative profit observed. Reserve funding consumes profit at `ceil(amount * 10000 / allocationBps)` and is limited to current net profit above that consumed mark. Losses must be recovered before further distributions. Governance may configure the default 35% allocation up to 50%; changes affect only unconsumed profit. LP deposits and donations are not realized profit.
- Required LP capital must cover reported maximum exposure and actual LP assets must cover required capital after settlement/distribution. Reserve assets never count. Direct LP donations are not tracked LP deposits or spendable settlement funds.
- Emissions require an immutable schedule and explicit activation. Budget caps decay by a configurable fraction per fixed interval, regardless of allocated amount. Unused caps do not carry forward. Publication is sequential, may be delayed, and cannot allocate more than 600M FUSE. Claims do not expire. The provisional 20-day half-life is not hardcoded.
- Redemption activation approves retained residual backing. The scheduler chooses each epoch's penalty (0–10000 bps); 10% and 20% remain candidates. Governance must approve this authority and economics before activation. Requests occur in `[start, end)` and claims begin at `end`.
- Each epoch divides by the entire outstanding supply, including both escrows. A single floor of the full discounted fraction and cumulative per-account requests make same-account splitting economically identical. Each distinct account rounds down by less than one USDC atomic unit; splitting wallets cannot increase aggregate payout. Mid-epoch funding affects later epochs only. Later snapshots deduct outstanding claims. Penalties and rounding residuals stay locked; no residual sweep exists.
- The treasury remains locked until governance approves a separate immutable Merkle allocation policy and manifest hash. Claims also require token transfer activation and cannot exceed 400M in total. No discretionary release or rescue exists; deployment approves no treasury policy.
- Guardian pauses stop deposits, settlements, reserve distributions, reward publication, epoch scheduling and new burns. LP recapitalization, refunds, published reward claims, valid funded withdrawals and accrued redemption claims remain executable. Only governance resumes. Guardian status grants no signing/payout authority.
- Rotating any signing authority increments a global generation and invalidates all previous settlement, reserve and withdrawal signatures, including funded authorizations. Reissue unclaimed authorizations with unchanged cumulative history. Assigning the same signer again also invalidates signatures. Operational role changes do not rotate signers. Distinct signing addresses do not prove independent beneficial control.

## Deployment

`script/Deploy.s.sol` deploys a self-administered OpenZeppelin timelock and all modules. The multisig is the sole proposer/canceller; execution is permissionless after the delay. The deployer gets no admin role. Nonlocal runs require chain ID 998 or 999 and a deployed governance contract.

Export the following variables or supply them in a local `.env`:

```sh
USDC_ADDRESS=0x...
GOVERNANCE_MULTISIG=0x...
GOVERNANCE_DELAY=172800
DEPOSIT_REFUND_TIMEOUT=86400
TRANSFER_ACTIVATION_DELAY=172800
SETTLEMENT_SIGNER=0x...
RISK_SIGNER=0x...
WITHDRAWAL_SIGNER=0x...
EMISSION_PUBLISHER=0x...
REDEMPTION_SCHEDULER=0x...
GUARDIAN=0x...
LP_PROVIDER=0x...
```

Durations are illustrative, not approved production parameters. Verify the intended USDC asset separately. Simulate using:

```sh
forge script script/Deploy.s.sol:Deploy --rpc-url "$HYPEREVM_RPC_URL" --sender "$DEPLOYER_ADDRESS"
```

After review, select a wallet explicitly and add `--broadcast` for testnet. Do not put private keys in source. The script emits `ModulesDeployed` and the complete `BootstrapBatch` (targets, values, calldata, predecessor, salt and delay). It does not submit multisig proposals.

1. Multisig calls the deployed timelock's `scheduleBatch` with the emitted arguments.
2. After the delay, execute the same batch. It wires modules once, installs authorities and atomically pauses trading.
3. Verify asset, bytecode, wiring, independent authority control, capital and monitoring. Complete production blockers before timelocking `AccessController.resumeTrading()`.
4. Approve and configure emissions and redemption economics separately, then activate through governance. Transfers require governance's `scheduleEnableTransfers()`, an additional token-level delay, and permissionless `enableTransfers()`.

The deployment integration test executes this exact batch and verifies its delay and paused initial state. Tests do not deploy to public networks.

## Engine integration and remaining work

[Engine integration](docs/ENGINE_INTEGRATION.md) defines EIP-712 formats, sequences, journal reconciliation, reward leaves and recipient consent. The Rust trading engine, oracle observer, durable journal and public manifest service are absent from this repository and remain external integration work. No contract substitutes BBO or mark price for the HyperCore BTC oracle.

Production blockers remain: oracle outage policy; forced exits or explicit acceptance of operator custody risk; independent LP exposure verification; treasury policy; calibrated reserve allocation, penalty and emission policies; testnet stress testing; and independent review. Tests verify contract accounting, not the truth of signed offchain reports.
