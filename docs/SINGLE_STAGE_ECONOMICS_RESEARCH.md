# Native single-stage economics probe — 28 October 2026

The shipped **unfitted Brownian research assumptions** fail this bounded native
replay: all forty-five trading cases lose LP money before fees or costs. The
other nine cases contain no entries. Account and aggregate capital checks fund
accepted obligations, but do not prevent large cumulative losses. This rejects
these assumptions on the tested paths; it does not estimate a future return or
validate a replacement.

The [frozen adaptive capture](PROSPECTIVE_ADAPTIVE_20261028.md) remains unchanged
and continues collecting until its original deadline. This probe reads only
two completed 26 October recordings. It does **not** evaluate that adaptive
challenger, consume live trial outcomes, retune its model, or change a policy.

## Executed scope

The actual `fuse-research` bridge calls the production Go reducer on the original
native receiver messages. The policy is `engine/config/paper.json`: single-stage
BTC, all nine payout presets, fixed 1,000-ppm thirty-second volatility and 500-bps
target gross edge. These are documented research assumptions, not empirically
calibrated parameters. Neither a historical ladder nor a 48% corridor is relabeled
as a preset ticket.

The protocol pins the **first thirty minutes** of each named native recording:

| Retained recording | Prefix start, WITA | Receiver messages |
| --- | --- | ---: |
| `20261026-117ppm-8h` | 26 October, 05:26:28.943 | 3,524 |
| `20261026-round2-314ppm-8h` | 26 October, 17:11:54.890 | 3,516 |

Each complete recording is natively hash-verified before its prefix is selected.
The original messages, receiver identities, order and timestamps are retained.
There is no paired-feed fabrication, price interpolation, market resampling or
synthetic terminal price. These old recordings are development inputs; the probe
does not supply sixty minutes of new prospective evidence or two complete days.

The three trader profiles are fixed before replay:

- One funded account submits a one-USDC ticket at each eligible grid entry.
- One funded account submits only when pre-entry activity is classified frozen.
- Three funded accounts submit the same one-USDC ticket at the same timestamp.
  Their outcomes share one oracle path; no independent draws are invented.

All profiles use the same clean five-minute pre-entry-history gate, including
after outages. This allows a fair frozen-state comparison. **That extra strategy
gate is not a requirement of the shipped fixed-volatility quote engine itself.**
Current-window validity and movement do not select an entry. Each account starts
with an explicitly hypothetical 1,000-USDC deposit; this is not observed voluntary
customer demand. Stakes and selected payouts do not adapt to future outcomes.

Each of the fifty-four cases independently starts with 250,000 USDC of assumed
LP capital: 200,000 protocol and 50,000 across twenty-five external LP owners.
Successful share-economic bootstrap operations, virtual rounding, capitalization
and high-water reserve-fee accrual use `contract_lp_model.py`. The Go reducer
checks accepted stakes, immutable payout/barrier terms, debt, custody and capital
capacity. Paper settlement every five minutes funds actual debt and loss clearing.
No LP exit, reward emission, redemption, trader withdrawal or reserve funding
is projected in this bounded probe.

## Preset outcomes and losses

The uniform one-account results illustrate the scale mismatch. Rates exclude
voids; profit includes their zero trading payoff. Every ticket stakes one USDC.

| Payout | Configured target | First prefix survival | First prefix LP trading PnL | Second prefix survival | Second prefix LP trading PnL |
| --- | ---: | ---: | ---: | ---: | ---: |
| 2× | 47.5% | 30/30 = 100% | −30 USDC | 49/49 = 100% | −49 USDC |
| 5× | 19% | 30/30 = 100% | −120 USDC | 47/49 = 95.92% | −186 USDC |
| 10× | 9.5% | 29/30 = 96.67% | −260 USDC | 47/49 = 95.92% | −421 USDC |
| 100× | 0.95% | 28/30 = 93.33% | −2,770 USDC | 43/49 = 87.76% | −4,251 USDC |
| 1,000× | 0.095% | 27/30 = 90% | −26,970 USDC | 40/49 = 81.63% | −39,951 USDC |
| 10,000× | 0.0095% | 4/4 = 100% | −39,996 USDC | 5/8 = 62.5% | −49,992 USDC |

At 10,000×, a realized win leaves a large unfunded claim until settlement.
The existing account exposure limit rejects further quotes while that claim
remains. The first uniform account receives only **5 of 31 intended tickets**;
the second receives **8 of 49**. The corresponding rejected-quote counts are
26 and 41. Refusals remain in the availability denominator, rather than making
high-payout calibration appear successful.

The first prefix's common history gate permits 31 of 60 grid entries; the second
permits 49 of 60. An additional outage voids one accepted ticket per multiplier
in the first uniform-account case. Refunds stay in turnover/acceptance counts
and carry zero trading payoff. They are not silently scored as wins or losses.

## Correlation and cumulative risk

Three synchronized accounts triple exposure and payouts on the common paths:

| Case | Accepted tickets / attempts | LP trading loss | Peak total exposure | Settlement NAV drawdown |
| --- | ---: | ---: | ---: | ---: |
| First prefix, 100× | 93/93 | 8,310 USDC | 2,673 USDC | 3.324% |
| Second prefix, 100× | 147/147 | 12,753 USDC | 2,970 USDC | 5.1012% |
| First prefix, 10,000× | 15/93 | 119,988 USDC | 29,997 USDC | 47.9952% |
| Second prefix, 10,000× | 24/147 | 149,976 USDC | 29,997 USDC | **59.9904%** |

Peak open obligation and cumulative loss are different quantities. Five-minute
settlements fund prior winnings and release account capacity for fresh risk.
The shipped capital-only policy keeps every accepted payout funded, while
repeated losing underwriting can consume much of the LP bankroll. These cases
do not test the separate fixed-USDC recovery policy, and cannot establish an
acceptable loss limit or availability after a drawdown pause.

The frozen-only profile finds eight eligible entries in the first prefix and
zero in the second. At 100× its first-prefix outcomes are six wins and two
losses; at 10,000× it accepts four of eight intents, with three wins and one
loss. These tiny strategy-selected samples are descriptive. Zero-trade cases
provide no pricing evidence, and repeated accounts/payouts are not independent
observations of the oracle process.

## Fees, costs and a research-bridge limitation

No reserve fee accrues on these losing paths. A separate deterministic test
with narrow corridors exercises positive profit, high-water accrual, cash and
fee segregation. That fixture validates an accounting path, not market pricing.
The actual contract's successful-operation projection is used; no constant
35% haircut substitutes for path-dependent accrual in this replay.

The zero/low/high cost scenarios are pinned explicit assumptions inherited from
`replay_lp_economics.py`. Gas estimates use simulated LP/trader deposits and
settlement counts; offchain quotes and entries are not charged fictitious
onchain gas. Recorded prefix service time determines the illustrative operator
cost allocation. Cleanup ticks invent no price. Costs do not alter custody or
contract NAV, since the contracts have no such operator-cost withdrawal rule.
The low-cost scenario adds about **2.10 USDC** per one-account case, making all
losses worse. These are not measured chain receipts or operating expenses.

The existing research bridge directly projects LP fee liabilities through
`sync_lp`. That path **does not invoke the recovery controller's fee-PnL
accounting**, unlike real `ReserveFeeAccrued` effects. Combining this projection
with a recovery policy would therefore misstate risk budgets. The new harness
explicitly rejects that combination. A separate correctly integrated and tested
fee/recovery projection is required before claiming controller-plus-fee results.
No production engine behavior was changed here.

A synthetic accounting differential at
`.local/capture-readiness/20261028-fee-recovery-projection-gap-v1/` confirms the
gap: projecting a 25-USDC fee through the old bridge leaves recovery PnL at zero
and permits a fresh quote. Under the configured real fee rules, that expense
would debit PnL by 25 USDC and cross the 15-USDC pause drawdown. The existing Go
`TestRecoveryLPFlowsAndFeeFundingCannotResetLimits` passes against actual local
fee effects, including budget exhaustion and pause. This is a research-wrapper
integration defect, not evidence that production fee effects omit the debit.

## Verification and limits

Archive:
`.local/adaptive-corridor/20261028-single-stage-economics-v1/`.
It retains source and policy hashes, the executable, native input bindings,
per-case command/response hash chains, final Go states, LP checkpoints, results,
costs and availability. All 2,680 accepted stages conserve customer/LP trading
PnL, close their terminal obligations and reconcile custody through actual
settlement. **2,644 healthy-path outcome comparisons** match exact oracle
barriers. The remaining accepted stages are voids. These counts include repeated
paths across presets and accounts; they are not independent effective samples.

The audit re-executes all fifty-four cases, compares all case artifacts byte for
byte and rebuilds all LP projections and costs. Its command traces cover 200,050
audited records. Four tests cover actual-reducer preset accounting, correlated
accounts, causal strategy selection, future outage refunds, positive-profit
fees and rejection of unsupported recovery/fee combinations. A fixture assertion
was corrected before the experiment: clean lookback starts at 330 seconds,
because the initial censored window remains in a full five-minute lookback at
300 seconds. The full suite passes **340 tests, with three existing optional
skips**.

The first audit attempt completed all replay cases but stopped before file
comparison because it compared an in-memory tuple with a list loaded from JSON.
The retained failure note records this. JSON-normalizing that comparison changes
no pricing, strategy or input. The corrected full audit passes, including exact
per-case command traces, final states, LP checkpoints, results and CSV hashes.

```sh
cd engine
GOCACHE=/private/tmp/fuse-go-cache go build \
  -o /private/tmp/fuse-research ./cmd/fuse-research
cd ..
OPENBLAS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 OMP_NUM_THREADS=1 \
  python3 -B scripts/research_single_stage_economics.py \
  --binary /private/tmp/fuse-research \
  --output /absolute/path/to/new-single-stage-probe
OPENBLAS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 OMP_NUM_THREADS=1 \
  python3 -B scripts/audit_single_stage_economics.py \
  --output /absolute/path/to/new-single-stage-probe
```

This is a bounded baseline rejection and integration check. The full objective
still needs calibrated adaptive widths, useful availability across regimes,
stable fresh/continuous operation and completed prospective evidence. Validated
economics additionally needs multiplier-conditioned pricing, feasible discrete
oracle probabilities, correctly integrated recovery fees, measured costs,
stake-sensitive/adversarial strategies, longer regimes and LP/incentive/withdrawal
stress. Neither funded obligations nor the live trial's eventual aggregate
48% survival can replace those requirements.
