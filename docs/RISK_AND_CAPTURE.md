# Backend recovery and prospective capture

This milestone adds opt-in research risk enforcement and a durable live market
recorder. Real-money/public execution remains disabled. The recorder collects
new observations only when explicitly run with a live endpoint; tests and old
replays do not add prospective evidence. See the complete
[production release gates](PRODUCTION_READINESS.md).

## Durable admission controller

`Policy.recovery` enables `fixed-usdc-research-v1`. All amounts are USDC atomic
units (1 USDC = 1,000,000 units); times are milliseconds. The separate example
`engine/config/paper-recovery.json` is for research, with unapproved limits and
uncalibrated pricing. Existing policies omit recovery, preserving old journal
commitments. To enable it, start a **new** journal/database with the explicit
policy. Never clear or replace an existing journal to reset risk.

The controller is part of the same sequenced transaction as the event, ledger,
snapshot and outbox. No new SQL table or separate ephemeral counter is involved.
Startup journal replay reconstructs and hash-checks every recovery transition.
Policy updates cannot add, remove, relax or reset recovery configuration; a
future approved migration needs an explicit reviewed carry-forward procedure.
Pricing-only updates preserve its counters. Manual resume does not override it.

Rules:

* Each active or pending stage reserves its **incremental payout minus stake**
  against both rolling loss budgets, the hard drawdown budget and (in probe mode)
  the probe budget. This is additional to the existing physical-capital check,
  which reserves the full payout minus physically funded stake, including debt.
  Correlated positions receive no diversification discount. Quotes are
  indicative; acceptance independently recomputes the complete reservation.
* Survival charges incremental payout minus stake once, at economic resolution.
  Funding that earned claim later does not charge it again. Explosion credits
  economic PnL by stake, including a rolled stake; void releases risk without a
  loss. Profits do **not** refill gross rolling loss budgets. Accrued reserve
  fees debit recovery PnL and loss budgets when accrued, not when paid.
* Drawdown is peak cumulative economic trading PnL minus current PnL, including
  newly accrued reserve fees. Stored PnL and peak share a periodically shifted
  origin, preserving their difference without accumulating unbounded profits.
  This shift never changes rolling losses. Fixed amounts ignore deposits,
  withdrawals and share ownership. New capital cannot refill spent limits and
  exits cannot reduce the recorded drawdown. Existing physical solvency checks
  continue to restrict capital operations. This is **not** a percentage-NAV
  drawdown policy or an approval of any capital/share conversion rule.
* Rolling losses include timestamps in `(now-window, now]`. There is no midnight
  reset. History is retained until outside the longest window. UTC is used only
  for Unix timestamps; wall-clock receipt timestamps must not regress.
* Reaching the pause drawdown blocks admission for the cooldown. After cooldown,
  a drawdown at/below the resume threshold reopens; otherwise the mode becomes a
  probe. Probe admission uses the remaining rolling-24h probe loss allowance,
  including earlier losses, and all other limits. A losing probe restarts the
  cooldown. There is no automatic doubling of probe size.
* Pauses gate quotes and entries, including independent re-entry. They do not gate accepted
  resolution, automatic win credit, funding or payment. Already accepted obligations are never
  revoked because a limit is reached. External fees can exhaust a budget while
  obligations remain open; this blocks further admission and does not revoke
  those obligations. The controller does not reserve hypothetical future
  operating costs or model capital losses outside its accounting scope.

`State.Recovery`, journal commitments and authenticated metrics expose mode,
drawdown, pending incremental risk and reopen time. The local process checking
risk is not a genuinely independent production signer/controller. Deployment,
independent replay validation, fault drills and approved limits remain gate 3/14
requirements. This implementation does not claim exact equivalence with the
simulation's per-share NAV controls.

## Prospective receipts, up to seven days

Build once from the engine directory:

```sh
cd engine
go build -o ../.local/fuse-capture ./cmd/fuse-capture
```

Choose a **precalibrated fixed fractional-width policy** with a new model version
and validity beyond the collection deadline. The existing pricing freeze workflow
in `scripts/validate_pricing.py` can produce the policy from a fitted candidate.
Do not fit it from the recording being evaluated. Then, from the repository root:

```sh
.local/fuse-capture -config /absolute/path/to/frozen-policy.json \
  -output .local/prospective-001 -duration 72h
```

This command runs in the foreground until its pinned deadline (or interruption).
It opens the collector's two reconnecting connections to the same configured
upstream. It does not execute trades, accept deposits, sign, broadcast, establish
independent price truth or prove historical prices onchain. It writes:

* `manifest.json`: original policy and hash, endpoint, collection duration, and
  freeze time, created and synced before observations;
* `receipts.jsonl`: sequence, manifest-linked hash chain, local receipt time,
  receiver and validated raw BTC oracle message, synced before acknowledgment;
* `capture.lock`: exclusive process lock preventing concurrent writers.

The first previous-hash commits the full manifest. Reopen with exactly the same
arguments to validate the entire chain and continue toward the **original**
deadline. Restart cannot extend the sample period, retune the policy or erase
outages. Completed recordings can always be verified offline:

```sh
.local/fuse-capture -verify -output .local/prospective-001
python3 scripts/analyze_capture.py .local/prospective-001 \
  --verifier .local/fuse-capture --output .local/prospective-001-analysis.json
```

Stop the writer before analysis. The analyzer requires a fixed positive
`base_width_ppm`; it verifies receipts using the Go binary, builds nonoverlapping
30-second windows, censors unhealthy windows, excludes the unfinished terminal
window and reports flat, jumping, volatile, trending and quiet coverage. Regimes
use descriptive thresholds relative to the frozen corridor, with flat and jump
precedence. They are not an approved regime taxonomy. A simple positive-lag
outcome autocorrelation estimator reports descriptive effective sample size;
a constant sequence yields one effective sample. It neither supplies a robust
tail-safety bound nor authorizes production. A healthy 400-window count is only
a research minimum. Separate multiplier-conditioned single-stage/strategy experiments are still needed. Legacy ladder or 48% calibration is not validation of the 2×–100× corridor table.

Every receipt append is fsynced; a failed write fences the writer and stops the
CLI. An incomplete/corrupt tail fails verification without modifying evidence.
Preserve the original directory, investigate the storage incident and create an
explicitly linked new capture after recovery; do not silently truncate a tail.
An interruption leaves acknowledged receipts available for verification; no
successful-duration claim is made. Clock regression or policy expiry stops
capture. The fixed deadline allows gaps to reduce sample coverage rather than
moving the sample endpoint after seeing results. Capture verification scans the
whole stream with bounded memory; keep disk headroom and external backups.
The recorder itself does not rotate files, operate alerts, archive backups or
provide a monitoring service. Connection faults appear as receipt gaps and
collector logs. Current supervised collection is documented below.

## Supervised prospective runs

The [recalibrated round-2 run](PROSPECTIVE_RUN_20261026_ROUND2.md) is collecting
live observations under a frozen **eight-hour** protocol with a 314-ppm
half-width. The [first completed eight-hour run](PROSPECTIVE_RUN_20261026.md)
missed the 117-ppm survival hypothesis and is now explicitly retrospective
calibration data for round 2. The earlier 72-hour run was interrupted at the
user's request and retained with its original manifest and verified receipts.
The active supervisor keeps the
original deadline, writes `status.json` every five seconds, retains process logs,
and runs offline verification and analysis after collection ends. On macOS it
uses `caffeinate -i` while running; this prevents idle sleep, not shutdown,
reboot, power loss or loss of network/storage access.

The reproducible preparation entry point is `scripts/prospective_capture.py`.
Build `fuse-capture` into a new run directory, freeze a retained calibration and
its matching fixed-width policy, then run the copied `supervisor.py` from that
directory. Do not freeze into the active run or alter its snapshots. The
supervisor checks the frozen executable, analysis code and policy bindings.

Coverage uses the complete grid from the capture manifest's freeze time through
its original deadline. Unobserved leading and trailing intervals count against
coverage. The first interval cannot retroactively acquire a healthy entry price.
Regime/effective-size output remains descriptive; no production approval follows
from a sample minimum or favorable first-stage survival result.

`scripts/check_recovery.py` provides a separate Python integer-arithmetic checker
for recovery-enabled trading journals. It requires native Go replay first,
reconstructs risk from committed accepted terms/outcome notices and fee-accrual
events, checks admission limits, and compares the resulting recovery state with
the retained final snapshot. It does not independently establish oracle outcomes
or provide a production risk signer. The local contract/backend E2E now exercises
recovery enforcement and payment during a pause; CI retains its journal and runs
both checks. External review and genuinely independent controllers remain open.
