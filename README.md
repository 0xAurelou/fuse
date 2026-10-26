# FUSE 100

Foundry implementation of the [V0.1 specification](docs/SPECIFICATION.md). Solidity 0.8.24, OpenZeppelin Contracts **5.0.2**, Paris EVM target. Immutable modules, one-time counterparty wiring, no proxies or administrator asset sweeps.

This is an operator-secured custody system. Signatures commit operator accounting; they do not prove trading outcomes, oracle observations, entitlements or open exposure. Live funding requires the specification's final policy decisions and independent security review.

The primary app is now one 30-second BTC double-no-touch stage with a selectable total payout of **2×, 5×, 10×, 25×, 50×, 100×, 250×, 1,000× or 10,000×**. Wins credit automatically; every new stage requires a fresh quote. The Go engine and Next.js terminal implement this flow. See [engine specification](docs/GO_ENGINE_SPECIFICATION.md), [engine usage](engine/README.md), and [frontend setup](frontend/README.md). Payout includes the original stake; this is a fixed payout multiplier, not margin leverage. A payout dropdown controls formula-based barriers, with the countdown on the chart. The top-right **Degen** switch opens three independent BTC, HYPE and ETH tickets sharing one account and combined risk limits; see [Degen mode](docs/DEGEN_MODE.md). The [Brownian pricing model](docs/BARRIER_PRICING.md) uses explicit paper/local assumptions requiring independent oracle calibration.

The [live paper desk](docs/LIVE_PAPER_DESK.md) connects all three assets to live oracle prices, grants 1,000 virtual USDC per tab account and supports one-click individual or concurrent entries. Start its separate loopback backend with `./scripts/paper-desk.sh`. The Degen UI now has an illustrated anime nightclub theme, a spinning DJ cat and a motion pause control; the live chart data remains separate from the animated artwork.

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
| LPVault | Underwriting cash, LP-first profit waterfall, segregated exit/fee liabilities and dual-signed reserve funding |
| LPShareVault | Phased ERC-4626 equity entry, demand caps and FIFO ERC-7540 asynchronous exits |
| LPIncentiveDistributor | Time-weighted usable capital, demand-gated 90-day emissions and 30-day vesting |
| SettlementController | Ordered epochs, roots, contiguous sequences, deposit acknowledgments and atomic solvency checks |
| WithdrawalGateway | Expiring cumulative claims and independent account consent for redirects |
| FUSEToken | Fixed 1B supply, 600M trader / 50M LP / 350M treasury escrows, delayed transfers and allowance-backed redemption burns |
| RewardDistributor | Immutable Merkle epochs, declining budget caps, allocation ceiling and claimed-index bitmap |
| RedemptionReserve | Segregated backing, fixed-price epochs, cumulative burn pricing and funded USDC claims |

USDC uses atomic units (six decimals for the intended asset), FUSE 18 decimals. Both sender and recipient USDC balance deltas must equal the requested transfer. Fee-on-transfer and rebasing assets are unsupported. No network token address is hardcoded.

## Implementation choices

- Deposit IDs start at 1. Anyone can trigger a timed-out pending refund, always to its payer. Credit and refund race onchain: the first successful transaction wins. The engine must reconcile refunds before accepting offchain obligations.
- A checkpoint's customer liability is the **remaining** payable balance at execution, after prior onchain payouts and included deposits. Custody retains that liability plus all uncredited funds. Withdrawals reduce this liability.
- Positive trader PnL funds custody from LP; negative PnL funds LP from credited custody. Any failed funding, capital, liability or HWM check rolls back the entire epoch.
- LP cumulative realized profit excludes LP capital flows. Protocol-only operation retains the gross-profit/consumed-profit policy. Whitelisted/public participation permanently enables a contribution-adjusted per-share high-water mark: recover losses, retain capitalization profits, then accrue at most 35% of new eligible profit for FUSE backing. The candidate ramp is `alpha = cap × clamp((2E−3C)/(3C), 0, 1)`, retaining at least `2C`. Protected retained profits cannot be charged retroactively. Deposits/donations are not profit, and reserve funds never become underwriting capital.
- External LPs receive nontransferable equity shares. Entry and exit fulfillment require a fresh zero-exposure checkpoint and an atomic settlement/pause window; ordinary pauses cannot reuse old windows. Exit requests retain downside until fulfillment, wait at least 48 hours, follow FIFO, and preserve the `2C` floor. Funded claims are segregated and can be pulled during pauses. See [LP participation](docs/LP_PARTICIPATION.md) for interfaces, capacity and launch gates.
- A separate 50M FUSE escrow funds a one-time 90-day decaying LP campaign with 30-day vesting. Rewards use onchain account capital-time and dual-attested actual underwriting liability-time. Protocol and queued capital earn no rewards; idle-demand slots pay zero and missed slots expire. The campaign is inactive at deployment.
- Required LP capital must cover reported maximum exposure and actual LP assets must cover required capital after settlement/distribution. Reserve assets never count. Direct LP donations are not tracked LP deposits or spendable settlement funds.
- Emissions require an immutable schedule, finite end time and explicit activation. Budget caps decay by a configurable fraction per fixed interval, regardless of allocated amount. Unused caps do not carry forward. Publication IDs are sequential, but each publication consumes at most one current time slot: missed slots expire, late publication receives only the current decayed cap, and no second publication may reuse that slot. Allocation cannot exceed 600M FUSE. Claims do not expire. The provisional 20-day half-life is not hardcoded.
- Redemptions cannot open before token transferability. A future scheduled epoch takes its fixed reserve/supply snapshot when it actually starts, through permissionless activation or the first valid request. The scheduler chooses each epoch's penalty (0–10000 bps); 10% and 20% remain candidates. Governance must approve this authority and economics before activation. Requests occur in `[start, end)` and claims begin at `end`.
- Each epoch divides by the entire outstanding supply, including all three escrows. A single floor of the full discounted fraction and cumulative per-account requests make same-account splitting economically identical. Each distinct account rounds down by less than one USDC atomic unit; splitting wallets cannot increase aggregate payout. Mid-epoch funding affects later epochs only. Later snapshots deduct outstanding claims. Penalties and rounding residuals stay locked; no residual sweep exists. Burning the final outstanding token is disabled pending an approved final-residual policy.
- The treasury remains locked until governance approves a separate immutable Merkle allocation policy and manifest hash. Claims also require token transfer activation and cannot exceed 350M in total. No discretionary release or rescue exists; deployment approves no treasury policy.
- Guardian pauses stop customer deposits, settlements, reserve distributions, reward publication, epoch scheduling and new burns. LP recapitalization, refunds, published reward claims, valid funded withdrawals and accrued redemption claims remain executable. Only governance resumes. Guardian status grants no signing/payout authority.
- Rotating any signing authority increments a global generation and invalidates all previous settlement, reserve, withdrawal, capacity and LP-utilization signatures, including funded authorizations. Reissue unclaimed authorizations with unchanged cumulative history. Assigning the same signer again also invalidates signatures. Operational role changes do not rotate signers. Distinct signing addresses do not prove independent beneficial control.

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

After review, select a wallet explicitly and add `--broadcast` for testnet. Do not put private keys in source. The script emits `ModulesDeployed`, `LPModulesDeployed` and the complete `BootstrapBatch` (targets, values, calldata, predecessor, salt and delay). It does not submit multisig proposals.

1. Multisig calls the deployed timelock's `scheduleBatch` with the emitted arguments.
2. After the delay, execute the same batch. It wires modules once, installs authorities and atomically pauses trading.
3. Verify asset, bytecode, wiring, independent authority control, capital and monitoring. Complete production blockers before timelocking `AccessController.resumeTrading()`.
4. Review the [LP launch controls](docs/LP_PARTICIPATION.md) before advancing the LP phase or activating its campaign.
5. Approve and configure emissions and redemption economics separately, then activate through governance. Transfers require governance's `scheduleEnableTransfers()`, an additional token-level delay, and permissionless `enableTransfers()`.

The deployment integration test executes this exact batch and verifies its delay and paused initial state. Tests do not deploy to public networks.

## Engine integration and remaining work

[Engine integration](docs/ENGINE_INTEGRATION.md) defines EIP-712 formats, sequences, journal reconciliation, reward leaves and recipient consent. The [Go engine](engine/README.md) supplies deterministic trading, risk, accounting, PostgreSQL durability, authenticated APIs and replay. A [full local contract/backend stack](engine/LOCAL_DEVELOPMENT.md) runs real Anvil settlements, funded withdrawals, FUSE reward claims, reserve funding and redemptions: start it with `./scripts/local-stack.sh up`, or validate it with `./scripts/local-e2e.sh`. Run `./scripts/local-live-e2e.sh` for live HyperCore oraclePx and BBO with 100 traders and a 250,000 USDC LP. The live runner also supports 300 wallets in spaced cohorts, a frozen pricing control group and prospective target gates; see the [local workflow](engine/LOCAL_DEVELOPMENT.md). Run `./scripts/local-hyperevm-e2e.sh` for the contract/backend journey on a pinned local fork of HyperEVM testnet. Public-chain execution and real-money mode remain disabled. No contract substitutes BBO or mark price for the HyperCore BTC oracle.

Production blockers remain: oracle outage policy; forced exits or explicit acceptance of operator custody risk; independent LP exposure verification; treasury policy; calibrated reserve allocation, penalty and emission policies; testnet stress testing; and independent review. Tests verify contract accounting, not the truth of signed offchain reports.

The [tokenomics implementation and research report](docs/TOKENOMICS_IMPLEMENTATION.md) maps the supplied specification to implemented controls, explicit research parameters, reproducible experiments and remaining launch decisions.

Run `python3 scripts/simulate_lp_incentives.py` to simulate the proposed external LP share model, asynchronous withdrawals, LP-first profit waterfall and temporary vested FUSE incentives with endogenous capital. This is an integer-ledger research model; contract behavior requires separate verification. See the [LP amendment and reproduction instructions](docs/TOKENOMICS_IMPLEMENTATION.md#external-lp-participation-amendment).

Run `python3 scripts/simulate_lp_risk.py` to compare rolling loss budgets, prospective drawdown floors, latched pauses and bounded recovery probes across matched multi-day winner clusters, oracle recovery and incentive expiry. Reports include admission throughput, withdrawal delays and LP cohort retention. These admission controls are simulation policies and do not change Go or Solidity execution.

Run `python3 scripts/optimize_lp_recovery.py` to search 24 recovery policies, freeze candidates from training scenarios, and evaluate them on separate seeds and weaker-demand/edge stresses. It distinguishes reopening trading from recovering the exact pre-loss share NAV peak. Adaptive probes respond only to realized gains and retain the hard drawdown floor.

Run `python3 scripts/replay_lp_economics.py` for the [contract-matched recorded LP replay](docs/CONTRACT_LP_REPLAY.md). It verifies retained journals, runs recorded oracle updates and trader decisions through the actual Go reducer, and projects current LP contract economics with 300, 150, 30 and zero retained wallets. Solidity differential vectors check the integer LP model. Cost assumptions, short market coverage and zero-trading runoff are explicit; the earlier synthetic recovery results remain separate. New local live runs also export canonical native gas receipts for coordinator-managed operations.

Backend research recovery controls and continuous prospective capture are documented
in [Risk and capture](docs/RISK_AND_CAPTURE.md). The complete
[production release gates](docs/PRODUCTION_READINESS.md) define pass conditions and
retained evidence for all 22 launch requirements; they remain open until reviewed.
