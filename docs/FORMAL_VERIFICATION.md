# Formal verification

The suite combines **bounded symbolic execution of production contract bytecode** with **unbounded integer arithmetic lemmas**. It supplements the Foundry unit, fuzz and stateful invariant suites. The registry currently contains 26 bytecode checks and eight arithmetic lemmas.

The bytecode proofs use [Halmos](https://github.com/a16z/halmos) 0.2.6 and its pinned Z3 4.12.6 solver. Foundry's formal profile compiles Solidity 0.8.24 with the repository's Paris target and optimizer settings. CI pins Foundry 1.5.1. This is a collection of specific bounded proofs, not a claim of full protocol verification.

## Run

Install Python 3.12, Foundry and the pinned verifier in a project-local environment:

```sh
python3.12 -m venv .venv-formal
.venv-formal/bin/python -m pip install -r formal/requirements.txt
PATH="$PWD/.venv-formal/bin:$PATH" python3 scripts/verify_formal.py
```

An existing Halmos 0.2.6 installation works too. `HALMOS_BIN` can select its executable, and `Z3_BIN` can select Z3 4.12.6. By default the runner locates the solver installed alongside Halmos. It creates a temporary executable alias to handle macOS installation paths containing spaces. It does not modify the global installation.

The runner builds the formal profile, executes a concrete witness for every registered proof, proves the integer lemmas, runs Halmos, and validates its JSON. Outputs are `formal-results/halmos.json` and `formal-results/math.json`; CI uploads both. Generated artifacts and local environments are ignored by Git.

For diagnostics only, run a subset directly:

```sh
mkdir -p formal-results
FOUNDRY_PROFILE=formal halmos --match-test '^check_deposit_'
```

Subset results cannot satisfy the full verification gate. Direct Halmos invocation uses `z3` from PATH; the checked runner always selects and checks the pinned solver. The normal Foundry profile excludes the formal harnesses, so randomized tests and symbolic proofs remain separate.

## Bytecode proof registry

`formal/properties.json` records every required function signature. `formal/FUSEFormal.t.sol` deploys all real protocol modules and exercises their public functions. `formal/FUSEFormalWitness.t.sol` supplies concrete successful executions. The runner compares the registry to the compiled ABI and result set, so missing, renamed or filtered-out proofs fail the check.

Each proof starts from a fresh deployment with 1,000,000 USDC of LP capital, 10^18 atomic USDC units held by the harness, fixed account addresses, time 1700000000, and the configured one-day deposit refund timeout. The `amount`, deposit and PnL parameters below range over **every integer satisfying their assumptions**, rather than random samples.

In the table, a lower bound of 1 means one atomic unit; upper bounds use whole USDC/FUSE units unless explicitly stated otherwise.

| Proof | Property and explicit input bounds |
| --- | --- |
| `deposit_credit_excludes_refund` | Credited receipt cannot be refunded; amount 1–100,000 USDC |
| `deposit_refund_excludes_credit` | Anyone can trigger payer-only refund, which blocks subsequent credit; same amount range |
| `pending_deposit_cannot_fund_lp` | A loss settlement cannot spend pending funds; same amount range |
| `net_settlement_conserves_usdc` | Customer/LP USDC conserved for both PnL signs; deposit and PnL each 1–100,000 USDC, losses no greater than deposit |
| `underfunded_settlement_is_atomic` | A post-transfer shortfall restores deposit status, both balances, LP profit and checkpoint; amount 1–100,000 USDC |
| `epoch_cannot_execute_twice` | Replayed report cannot credit or settle twice; same amount range |
| `settlement_requires_independent_risk` | Settlement approval alone cannot finalize or credit; same amount range |
| `cumulative_withdrawal_pays_only_delta` | Two cumulative claims and replay pay exactly the final entitlement; first and increment each 1–100,000 USDC |
| `operator_cannot_redirect_withdrawal` | Valid operator authorization cannot redirect without account consent; amount 1–100,000 USDC |
| `signer_rotation_invalidates_authorization` | Rotating the withdrawal signer, even to itself, invalidates previously approved digest; same amount range |
| `guardian_pause_preserves_funded_claims` | Pause rejects deposits while honoring funded claims; same amount range |
| `reentrant_token_cannot_duplicate_withdrawal` | Token callback cannot reenter a claim or duplicate payment; amount 1–100,000 USDC |
| `reward_budget_and_bitmap_replay` | One reward pays once, preserves fixed supply and escrow accounting; amount 1–600M FUSE, bitmap index 257 |
| `reward_global_allocation_cap` | Two publications cannot exceed 600M or the declining epoch cap; each proposed budget 1–600M FUSE |
| `users_cannot_transfer_before_activation` | Distributed user tokens remain nontransferable before activation; amount 1–600M FUSE |
| `distributed_profit_cannot_be_reused` | After distributing 350 of 1000 USDC profit, another request of 1–100,000 USDC fails without moving assets |
| `redemption_burn_and_backing` | Redemption burns exact supply, accrues the fixed price, remains funded and cannot claim twice; 10,000,007 FUSE for every admissible account address |
| `redemption_splitting_same_account` | Two requests accrue the same total as their combined request; 10,000,007 and 20,000,009 FUSE, both request orders and every admissible account address |
| `next_redemption_epoch_excludes_prior_claims` | Subsequent snapshot deducts unpaid liabilities and uses the post-burn total supply; 10,000,007 FUSE for every admissible account address |
| `treasury_locked_without_approved_policy` | Transfer activation alone cannot release unallocated treasury; proposed amount 1–350M FUSE |
| `transfer_activation_delay_and_irreversibility` | Activation fails before two days, succeeds at the deadline and cannot be rescheduled; elapsed seconds 0–172799 |
| `reserve_funding_preserves_required_capital` | Funding fails atomically if it would breach the signed minimum; proposed amount 1–350 USDC after 1000 USDC profit |
| `reserve_cannot_underwrite_lp_payout` | Additional reserve assets cannot cover an LP payout shortfall; reserve donation 1–100,000 USDC |
| `lp_deposit_issues_proportional_shares` | A 100 USDC legacy entry issues exactly 100 fLP and conserves equity/supply for every provider except zero, harness, LP and share vault |
| `lp_redeem_cannot_skip_request` | Redeeming without a funded asynchronous request cannot move cash or create an exit liability; share input 1–100,000 × 10^6 atomic share units |
| `lp_profit_allocation_capped_at_35_percent` | Every uint16 governance allocation input above 3500 bps reverts; all lower values are stored exactly |

All USDC bounds above include every atomic unit, and FUSE reward bounds include every token atomic unit. The redemption bytecode proofs quantify account addresses and both request orders at the fixed amounts stated above; they do **not** quantify all token amounts. Admissible redemption accounts exclude zero, the harness, the LP/custody/reserve modules and the trader/treasury escrows (see the harness for exact exclusions). Their prices include fractional USDC atomic units, exercising floor rounding. The fixtures use the genesis supply denominator, 350 USDC backing and a 10% penalty. Unrestricted numeric bit-vector queries exceeded the solver budget; the separate integer lemmas below cover general arithmetic without treating those incomplete EVM runs as proofs. Subsequent price evolution across arbitrary histories is not exhaustively checked.

The fixture starts in the protocol-funded phase, retaining the legacy gross-profit reserve policy. The three LP checks above are limited to their stated transitions; they do not prove the entire external-LP lifecycle, fee crystallization or incentive integrator. `test/LPParticipation.t.sol` exercises those behaviors, including independent risk approval, liquidity-window invalidation, loss recovery, time weighting and vesting. `test/LPAccountingInvariant.t.sol` mixes external deposits, signed settlements, queued exits, partial claims and fee funding, asserting cash/share/liability conservation and a nondecreasing per-share high-water mark. These randomized checks complement the bounded proofs; they are not universal proofs over transaction histories.

## Integer lemmas

`formal/math_lemmas.py` uses Z3 mathematical integers with explicit satisfiable assumptions and requires `unsat` for each negated proposition. Timeout/unknown or counterexamples fail. Unlike the fixed-amount redemption bytecode proofs, these formulas quantify arbitrary nonnegative amounts and positive denominators by refuting the existence of a counterexample:

1. For every configured allocation percentage from 1 to 5000 bps, an allowed distribution consumes positive profit and no more than the remaining eligible profit.
2. Cumulative redemption updates telescope to the combined entitlement and never reduce accrual.
3. Splitting across two wallets cannot increase payout; its extra aggregate rounding loss is at most one atomic unit.
4. One floor loses strictly less than one atomic unit relative to the exact fraction.
5. Splitting reserve distributions cannot reduce the consumed-profit ceiling.
6. Two accounts whose total requested amount does not exceed supply cannot accrue more than the backing reserve, for every penalty from 0 to 10000 bps. The arithmetic can be extended to more accounts by induction; this script checks two accounts explicitly.
7. Subtracting prior liabilities before reserving new claims preserves aggregate backing as funded claims are paid.
8. Floor-priced deposits using the vault's virtual assets/shares cannot dilute existing LP equity at fair NAV, for arbitrary positive denominators and nonnegative contributions.

These are proofs of the stated arithmetic model. They do not establish that arbitrary EVM histories or overflow behavior implement that model. The bytecode checks and existing randomized tests separately connect the formulas to contract behavior within their stated domains.

## Trust assumptions and limits

- USDC is the exact-transfer mock from the Foundry fixtures. Fees and callbacks are disabled except for the explicit reentrant-withdrawal proof, which calls the gateway again during payout. The real protocol's transfer and reentrancy checks run. This suite does not formally model every malicious, rebasing, paused or upgraded token; other adversarial transfer behavior remains covered by the existing tests.
- Authorities are separate test-only ERC-1271 contracts approving exactly the selected digests. Production role, digest, signature-generation and ERC-1271 checks execute. ECDSA and hash unforgeability are assumptions; this is not a cryptographic proof. The verifier's symbolic hash/storage model also assumes the standard absence of relevant collisions.
- Setup governance is the harness. These proofs do not symbolically verify the entire OpenZeppelin timelock or multisig implementation. Their deployment/wiring and delay behavior have separate integration tests.
- Claims use an empty proof for a single-leaf reward root. The full Merkle-proof algorithm, arbitrary manifests, treasury policy claims and arbitrary bitmap indices are not universally proven here.
- Each function exercises only its stated finite transition sequence from the fixed initial deployment. The suite does not prove invariants over all possible transaction histories. No storage mutation, implementation substitution or authentication bypass is used to manufacture a protocol state.
- Loop unrolling is bounded at three, except the reentrant-token proof's bound of 32 to copy its fixed-size callback payload. The checked runner rejects **any** reported loop truncation, even if Halmos labels the result PASS. It also requires a normal terminating path, zero blocked paths, zero counterexamples, the complete registered result set, and successful concrete witnesses. Gate regression tests cover these rejection cases. Every panic code is treated as a failure; intended rejections must have the expected custom error.
- Per-branch solving is bounded at 100 ms, with a native 45-second Z3 timeout and 60-second Halmos assertion timeout. Solver uncertainty fails the gate. CI additionally bounds the job duration.
- Engine truth, oracle sequencing/correctness, offchain liabilities, accepted-stage collateralization, public-manifest availability, key independence and operator recovery remain external obligations. Formal checks do not remove the production blockers in the specification.
