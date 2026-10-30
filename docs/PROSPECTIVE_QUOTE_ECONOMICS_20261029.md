# Supplemental paper economics fixed before live results

At **29 October 2026, 02:29:33.775 WITA**, a separate paper-economics protocol
was frozen for the already-running BTC adaptive trial. The original model,
eight-hour horizon, candidate selection and primary analysis remain unchanged.
**This economics protocol was introduced during capture, before the first
pricing result; it was not part of the original pre-capture protocol.** No live
pricing outcomes were inspected in preparing it.

The packet is
`.local/capture-readiness/20261029-prospective-quote-economics-v1/`.
Its `protocol.json` SHA-256 is
`e07f9f9b86a3b346e6aeeeca9062e87bd31c0f224476f8dc764ef052f2ee4110`.
It binds the original trial, compatibility analyzer, completion job, prior
historical economics protocol and both copied economics source files. No
extra background job or new live capture was started.

## Fixed scope

The implementation adopts the exact previously declared **13 entry rules**,
**one or three synchronized accounts**, **one-USDC unit tickets**, **2x total
payout** and **0/10/50/100-bps illustrative expense rates**. Every case is
reported; no profitable rule, threshold or candidate is selected. Rules based
on internal forecast floors remain labeled internal stress diagnostics. Public
history rules assume access to all offered quote opportunities and their
labels only after the existing conservative **entry-plus-60-second** delay.
This is a hypothetical observable quote surface, not measured trader behavior.

All three frozen pricing candidates and both pricing replays are included:
continuous operation and the descriptive private restart at four hours.
Continuous trader history carries through every reporting block. The restart
replay also resets private trader history at four hours. Full-eight-hour and
four two-hour reports reuse those same decisions, giving **780 cases** and
**3,120 cost sensitivities** from **5,760 quote-decision records**. These are
reused paths, not independent observations or multiple fresh captures.

Every original grid point remains in the quote tape. Selected entries with
censored outcomes remain placed tickets; expenses apply even when a refund is
assumed. Reports show the refund assumption and independent all-survive versus
all-fail monetary bounds. The clean-ticket break-even and target-margin
benchmarks inherited from the historical code are explicitly distinguished
from added fields that account for expenses on all placed tickets, including
assumed refunds. Gross settlement PnL drawdown is a unit-payoff diagnostic,
not actual funded LP NAV or a reserve-risk bound.

## Execution gate and evidence

The packet refuses to run before **06:31:07.783 WITA**, before the original
terminal status is preserved, or before the disclosed compatibility replay
completes. It verifies all original frozen files, the compatibility and
completion source bindings, the completed pricing hashes and the native
receipt chain. Economics uses the sealed quote tape without repricing. Its
all-offered and frozen-activity counts must agree with the original numerical
pricing summaries. A failed collection-quality gate remains visible even if
the descriptive economics calculation completes.

After the existing completion job finishes, execute the copied, bound source:

```sh
python3 -B /Volumes/dev/fuse/.local/capture-readiness/20261029-prospective-quote-economics-v1/analyze.py run --packet /Volumes/dev/fuse/.local/capture-readiness/20261029-prospective-quote-economics-v1
```

An actual early invocation was rejected before reading pricing results and
wrote no cases, decisions or result. The packet retains that gate evidence.

The separately marked software preflight is
`.local/capture-readiness/20261029-prospective-economics-preflight-v1/`.
It uses retained synthetic follow-up evidence and an explicitly artificial
preparation clock. Independent checks cover **780 cash/ticket cases**,
**3,120 expense/censoring cases**, **390 synchronized-account scalings** and
**420 complementary-strategy partition checks**. Its **156 artifact hashes**
were rechecked. Five new tests cover restart maturity, complete grids, pricing
denominators, early execution, native verification, model/tape tampering,
preservation of the original failure and refusal to overwrite results.
The current full workspace suite passes **436 tests with three existing
optional skips**, with the retained integration fixtures enabled. This change
adds five tests; independently developed workspace tests also affect the total.

This remains a first-stage paper accounting check. Actual reserve fees,
admission, recovery, bankroll constraints, LP funding, withdrawals, demand,
operating costs and intended multi-stage payouts are not simulated. No result
from this supplement alone establishes validated product economics,
cross-period calibration, production approval or completion of the broader goal.

A subsequent offline native boundary probe confirms an additional integration
limitation: the existing nine-preset integer-ppm fixed table requires at least
9 ppm for 2x and cannot exactly represent adaptive 1–8 ppm quotes. See
[the compatibility evidence](ADAPTIVE_NATIVE_WIDTH_COMPATIBILITY_20261029.md).
No width rounding, replacement pricing model or native validator change was
used to make those quotes pass. The paper protocol remains unchanged.
