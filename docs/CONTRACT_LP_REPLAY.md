# Contract-matched LP economics replay

This report and its retained journals describe historical ladder research. They are preserved unchanged as evidence and do not establish pricing or economics for the current single-stage 2×–100× product.


This milestone connects recorded HyperCore data to the actual Go trading reducer and an integer projection of the current LP contracts. It preserves the older synthetic simulations and their results. Public execution remains disabled.

Run from the repository root:

```bash
python3 scripts/replay_lp_economics.py
```

The command builds an offline Go bridge, verifies both retained 300-wallet journals, and writes `.local/contract-lp-replay/experiment.json`, `results.json`, `report.md`, per-case LP logs and hash-linked research audit logs. Full journal verification and all eight cases can take several minutes. `FUSE_GO` can specify a Go executable if the default toolchain is unavailable. A prebuilt binary is also supported:

```bash
cd engine
go build -o /tmp/fuse-research ./cmd/fuse-research
cd ..
python3 scripts/replay_lp_economics.py --binary /tmp/fuse-research \
  --output .local/contract-lp-replay/full
```

Use repeated `--run RUN_ID` arguments for other **chronological, disjoint, completed local captures**. The current scheduler deliberately rejects recordings lasting a full day: epoch publication would need to be interleaved with market activity first. Historical model validity and oracle health are evaluated at the recorded timestamps; the tool does not refresh expired pricing policies or authorize future entries.

Successful source verifications are checkpointed with the journal, initial/final state and research-binary hashes. An unchanged retry can reuse that checkpoint; `--reverify-sources` forces full recomputation. Economic cases always rerun. The hypothetical contract clock uses recorded receipt milliseconds rounded down to seconds; historical block timestamps are not substituted for that explicit assumption.

## What is reproduced

Before counterfactual analysis, Go re-executes every original journal command, recomputes all event commitments, and compares the complete final state with the retained snapshot. The replay then converts confirmed deposits, credits, settlements and paid withdrawals into paper operations. Quote/stage IDs are remapped, while entry times, funding, sizes, ladder/cashout decisions and historical policy changes remain recorded inputs. Paired source receipts, health, pending/refund rules, barrier touches, payout arithmetic and admission constraints come from the actual Go reducer. BBO is supporting evidence; outcomes use `oraclePx`.

Demand sensitivity removes whole wallets with a fixed hash ordering, yielding nested 300/150/30/0-wallet groups for each default recording. It retains their recorded deposits and decisions, adds no new trader funding, and does not replace rejected dependent actions with invented trades. Cases use the same market paths and are correlated. They do not add independent pricing evidence or measure organic demand.

Each case starts a new, hypothetical share-enabled deployment with **250,000 USDC total LP capital**, split into **200,000 protocol-owned and 50,000 from 25 external LPs**. That allocation is an assumption, not a claim that external LPs funded the recorded deployments. Each recording resets that capital; recordings are not stitched into a multi-day market path.

Bootstrap assumes a previously dual-attested 50,000 USDC of eligible demand to permit that initial allocation. Participation is thinned after the vault is funded. The zero-wallet case therefore measures demand disappearing from a prefunded vault; it does not establish new LP deposit capacity from zero demand.

`scripts/contract_lp_model.py` matches the economic transitions in `LPVault`, `LPShareVault` and `LPIncentiveDistributor`:

- Six-decimal USDC, 18-decimal shares, one virtual atomic asset and `10^12` virtual shares.
- Phase/whitelist gates, fresh zero-exposure NAV, settlement-created liquidity windows, resume/pause invalidation, expiring utilization-based capacity and integer conversions.
- Per-share loss-recovery HWM, capitalization ramp, at most 35% reserve fees, the two-times-required-capital floor, accrued fees excluded from usable equity, and separate reserve funding.
- FIFO 48-hour exit requests, a later fresh NAV epoch, shares exposed until fulfillment, segregated claimable USDC, and cumulative rounding on partial pull claims.
- Exactly 50M FUSE over a **linear 90-day schedule**, capital-time/global-index/account rounding, utilization scaling, protocol and pending-share exclusion, next-day publication deadlines, and vesting **30 days after the epoch ends**.

The model assumes successful, authorized attestations and exact token transfers. It is not a replacement for Solidity signature, role, callback/reentrancy, chain inclusion or governance tests. Source recordings predate these LP contracts; the new LP balances are explicitly counterfactual. Trader reward/redemption flows are independently covered by the existing local E2E and are not projected into the new LP model's 50M emission escrow.

## Runoff and costs

After the recorded workflow ends, the replay stops market activity. LPs request exits; on day 3 a fresh zero-exposure checkpoint permits fulfillment and payment. Daily epoch publication is exercised, and epoch-1 rewards are claimed on day 31. No prices are invented during this runoff. These dates exercise contract timing, not future returns or withdrawal availability under ongoing risk. A long-run recovery date or annualized APY cannot be inferred from these captures.

Default cost cases are explicit zero/low/high assumptions. Override them with `--costs path/to/costs.json`:

```json
[
  {
    "name": "my explicit cost assumptions",
    "gas_price_gwei": "0.1",
    "native_usd": "30",
    "operating_usd_per_day": "100"
  }
]
```

All amounts accept decimal strings and use exact arithmetic. Per-operation gas assumptions and simulated operation counts are pinned in the manifest. Offchain trading entries have no invented onchain gas charge. Service costs cover the recorded workflow duration; runoff transaction gas is included, while 30 days of idle infrastructure cost are not projected. Costs are allocated in a separate economic PnL column: the contracts do not authorize an operator expense deduction from LP NAV.

Retained recordings do not contain measured execution gas receipts. Future local live runs now export `gas-receipts.json`: canonical `gasUsed`, `effectiveGasPrice`, native execution fee, block and transaction hash for each **coordinator-managed operation**. Direct wallet transactions, deployment/setup and infrastructure costs remain outside that file. The exporter checks receipt success, transaction identity, block number and canonical block hash. Local Anvil gas is not evidence of public HyperEVM fees; no native/USD price is inferred. The deterministic contract/backend E2E exercises this export too.

## Verification and artifacts

```bash
python3 scripts/generate_lp_model_vectors.py
forge test --match-contract LPModelDifferentialTest
cd engine
go test ./cmd/fuse-research
go build -o /tmp/fuse-research ./cmd/fuse-research
cd ..
FUSE_RESEARCH_BINARY=/tmp/fuse-research \
  python3 -m unittest discover -s scripts -p 'test_contract_lp_replay.py' -v
```

Generated Solidity expectations are checked for drift by Python tests. Foundry compares 10 snapshots (130 economic fields) against real deployed contracts and compares all 90 emission caps. Additional tests cover stale/open NAV, window invalidation, FIFO/capital preservation, pending/protocol rewards, publication expiry, vesting, deterministic attrition, exact costs and audit tampering. A bridge integration test drives a real Go oracle barrier touch through settlement and projected fee segregation. CI runs that integration without external services or retained private recordings.

The Go bridge uses stdin/stdout only: no HTTP, RPC, signing or deployment path. LP cash/fee/exit projections enter through explicit harness operations. They are checked against the Go ledger before any subsequent admission. These adjustments are recorded in research audit logs, **not presented as confirmed engine transactions**.

Re-execute the Go requests/responses and validate the audit hash chain with:

```bash
python3 scripts/replay_lp_economics.py --binary /tmp/fuse-research \
  --verify-audit .local/contract-lp-replay/full/20261026-012628-10000-audit.jsonl
```

This check replays Go requests and verifies the integrity of LP snapshot records; it does not independently derive the Python LP arithmetic. Solidity differential tests and a full rerun from the pinned source inputs provide that separate check. The manifest pins source journals, snapshots, BBO logs, the research binary and relevant Go, Solidity, OpenZeppelin and Python source hashes. Earlier development data and later retrospective holdout are identified explicitly; no pricing or risk policy is selected from the holdout.

Production work remains: more independent prospective regimes, stage-conditioned pricing, voluntary funded demand, complete measured costs, integrated trader/LP token demand, backend enforcement of the recovery controller, disruption tests with live LP operations, public-testnet inclusion and independent security review.
