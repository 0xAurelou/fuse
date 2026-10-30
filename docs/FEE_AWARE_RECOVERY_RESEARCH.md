# Fee-aware recovery and quote availability — 28 October 2026

A separate offline research bridge now charges reserve-fee accrual through the
engine's actual fee-event handler. The matched native replay shows that the
configured recovery controller protects capital by refusing most intended
tickets. It does **not** satisfy the combined pricing/availability goal. No new
budget or production policy is selected.

The [frozen adaptive capture](PROSPECTIVE_ADAPTIVE_20261028.md) keeps its original
model, update rules and deadline. This work reads retained 26 October recordings
only. It neither evaluates new pricing outcomes nor changes the frozen packet.

## Corrected research projection

The [preceding preset probe](SINGLE_STAGE_ECONOMICS_RESEARCH.md) identified a
research-wrapper gap: old `sync_lp` directly changed fee liabilities without
debiting recovery PnL. Production local `ReserveFeeAccrued` effects already
charge correctly. The original bridge, production engine source, historical
archives and running capture remain unchanged.

`scripts/prepare_recovery_research.py` creates an **isolated copy** of the engine.
The reviewed helper and bridge templates live under `scripts/research_engine/`;
they are outside the production Go module. Only that copied module receives
`ResearchSyncLP`. The helper requires unbound paper state, accepts monotonic
fee accrual, invokes the unchanged `LPVault.ReserveFeeAccrued` local-effect
handler, then verifies funding invariants. Cash/exit projections are explicit
successful-operation assumptions, not chain confirmations.

New fee increments consume recovery PnL and gross-loss budgets exactly once.
Repeated equal fees cannot charge again; capital projections cannot reset the
loss history or profit peak. A fee-induced pause cannot revoke accepted claims.
Invalid funding after the fee handler runs returns the original state without
leaking intermediate fee, pause or loss-history mutations. Fee reduction/funding,
operator-cost accrual and a full LP exit lifecycle are outside this version.

The completed build is
`.local/capture-readiness/20261028-research-fee-recovery-v3/`. It records the
original inputs, exact copied source, compiler version, bridge diff, binary,
race-test logs and vet output. The earlier `...-v2` attempt is retained: its new
engine checks passed, but the old bridge fixture attempted fee accrual at time
zero. The v2 fixture now sequences a tick first; the stricter provenance guard
remains. Production code was not relaxed to accommodate the fixture.

A synthetic accounting differential executes the same 25-USDC fee on both
bridges. The old bridge leaves recovery PnL at zero and accepts another quote.
The new bridge records −25 USDC, enters the configured pause and rejects it.
This proves the wrapper correction, not a market return. The native losing
paths below accrue zero fees; profitable-market fee behavior is therefore still
not established by these recordings.

## Matched native replay

The archived experiment is
`.local/adaptive-corridor/20261028-recovery-economics-v1/`. It compares fifty-four
matched pairs: two original thirty-minute native prefixes, nine payouts and
three fixed trader profiles. Initial LP capital is 250,000 USDC; accounts deposit
1,000 USDC each and request one-USDC tickets. Profiles are uniform one-account,
pre-entry-frozen-only one-account, and three synchronized accounts. Prices,
widths, stake, past-history gate, settlement schedule and exogenous intent times
match the preceding probe. No market paths are resampled or synthesized.

All fifty-four capital-only controls reproduce the preceding **complete Go final
states exactly**, including across the separate compiler/build. Common accepted
entries in both arms have identical entry price, barriers, stake and payout.
Only the configured fixed-USDC recovery policy differs. Its existing research
values are retained: 20-USDC daily gross-loss budget, 40-USDC rolling budget,
15/40-USDC pause/hard drawdowns, 5-USDC resume drawdown, two-day cooldown and
2-USDC probe budget. None is tuned from the replay.

All 108 cases conserve customer/LP trading PnL and clear terminal obligations.
The 2,786 accepted stages include 2,750 healthy native outcome comparisons and
36 voids. These are repeated paths across payouts/accounts/arms, not independent
samples. The audit rebuilds all 108 cases, all LP projections and every case
artifact exactly, covering 397,634 command-audit records. Each positive fee
increment is checked against the corresponding recovery PnL debit; short-horizon
loss histories reconcile surviving-ticket debits plus accrued fees.

## Protection comes with low availability

Uniform one-account results under the configured controller:

| Payout | First prefix accepted / intended | First-prefix LP trading PnL | Second prefix accepted / intended | Second-prefix LP trading PnL |
| --- | ---: | ---: | ---: | ---: |
| 2× | 15/31 = 48.39% | −15 USDC | 15/49 = 30.61% | −15 USDC |
| 5× | 4/31 = 12.90% | −16 USDC | 7/49 = 14.29% | −18 USDC |
| 10× | 2/31 = 6.45% | −18 USDC | 3/49 = 6.12% | −17 USDC |
| 25× and above | 0/31 | 0 | 0/49 | 0 |

These are **acceptance fractions, not survival probabilities**. The denominator
retains all strategy intents after the common known-history gate. Full grid,
history eligibility, quote attempts, accepted stages and outcomes remain
separate in each result. No-trade cases establish no calibration.

At the one-USDC minimum stake, a 25× ticket reserves 24 USDC of potential gross
loss, exceeding the entire 20-USDC daily budget before any outcome is known.
Every higher preset is therefore also unavailable under this configuration,
regardless of whether its width would have been well calibrated.

For three synchronized accounts, 2× acceptance falls to **15/93 = 16.13%** and
**15/147 = 10.20%**. The configured policy's largest observed trading loss is
20 USDC and largest settlement NAV drawdown is about **0.008%**. Its capital-only
control can lose almost 60% in the earlier uncalibrated 10,000× example. The
controller limits that loss by rejecting risk; it does not repair the unfitted
Brownian pricing or preserve useful availability.

The first frozen-only subgroup retains eight intended entries at 2×, four at
5× and two at 10×; higher payouts receive none. The second prefix has no
frozen-only intents. Those small or empty groups cannot establish conditional
calibration or a populated-cell availability pass.

## A throughput constraint even with calibrated pricing

Recovery budgets count **gross LP debits**, not net profit. Losing traders do
not replenish spent budget. At 2× and a one-USDC stake, each survivor consumes
one USDC. Even if pricing met the provisional 43–53% survival band, a fresh
20-USDC budget could support at most **46 resolved tickets** before twenty
survivors exhaust it: `ceil(0.43 * 46) = 20`, while
`ceil(0.43 * 47) = 21`. Fees, pending reservations and prior losses can only make
this optimistic bound tighter.

On an illustrative ideal book of 960 eligible opportunities, 85% availability
means at least 816 accepted tickets. The same band requires at least 351
survivors and thus at least 351 USDC of gross-loss capacity, even with favorable
ordering and zero fees. This is an arithmetic illustration, not a prediction
for the live capture, whose warmup and health reduce the eligible population.

Consequently, accurate widths alone cannot meet the requested availability at
that stake/throughput under this particular budget. This identifies a parameter
compatibility requirement; it does not approve increasing budgets, weaken the
goal's availability requirement or establish safe economics for any alternative.

## Costs, tests and remaining evidence

The same explicit zero/low/high cost assumptions are allocated economically.
They use simulated operation counts and retained service time, not measured
chain receipts. They are **not charged to controller PnL or onchain NAV**: this
version has no operator-cost accrual mechanism. Trading/refund accounting, fee
budgets and allocated service costs therefore have distinct scopes. No net-cost
drawdown guarantee is claimed.

The isolated build passes eight Go race tests and vet. Three additional race
tests run in another temporary copy cover rejection *after* the fee handler
has mutated its copy, positive-fee compatibility without recovery, and preservation
of a prior profit peak. Their evidence is at
`.local/capture-readiness/20261028-projection-atomicity-v1/`.

Four new Python tests exercise old-bridge rejection, exact capital-only state
parity, loss limits/refusal denominators, high-payout zero availability, and
positive-profit fee reconciliation. Two separate metamorphic tests translate
native test receipts across UTC midnight and verify unchanged pre-entry features,
health and continuous frozen feedback. Their synthetic prices are test fixtures,
not market evidence. The initial clock placement happened to cancel the feedback
at midnight; shifting the fixture boundary makes the nonzero-state assertion
meaningful without changing model code. The live horizon crosses WITA midnight
but not UTC midnight, as the corrected trial note states.

The current full Python suite passes **351 tests, with three existing optional
skips**. Original engine sources, prior experiment inputs and the live pricing
packet remain unchanged. The new bridge is an offline research capability,
not a production fee or risk-policy change.

```sh
OPENBLAS_NUM_THREADS=1 python3 -B scripts/prepare_recovery_research.py \
  --output /absolute/path/to/new-isolated-build
OPENBLAS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 OMP_NUM_THREADS=1 \
  python3 -B scripts/research_recovery_economics.py \
  --baseline .local/adaptive-corridor/20261028-single-stage-economics-v1 \
  --build /absolute/path/to/new-isolated-build \
  --output /absolute/path/to/new-matched-recovery-study
OPENBLAS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 OMP_NUM_THREADS=1 \
  python3 -B scripts/audit_recovery_economics.py \
  --output /absolute/path/to/new-matched-recovery-study
```

The next pricing evidence remains the original eight-hour frozen trial. Reliable
completion and calibrated conditional outcomes are still unproven. Broader
validated economics additionally requires a calibrated payout-specific candidate,
compatible throughput/capital budgets, fee-funding and cost integration, longer
and adversarial strategy replays, real demand/cost evidence and LP/incentive/exit
stress. This study demonstrates a corrected measurement path and an unsuccessful
protection/availability combination; it does not substitute either for that goal.
