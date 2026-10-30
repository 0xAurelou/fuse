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

The [conditional frozen-CDF comparison](FROZEN_CONDITIONAL_CDF_RESEARCH.md)
models pre-entry minimum-width probability and positive movement separately.
Online floor estimates improve on August, but quote calibration/availability
do not; the retained open benchmark still wins. Exploratory saved market-gap
context provides a follow-up information lead. No candidate is frozen for an
eight-hour pricing capture.

The [later chronological comparison](TEMPORAL_PRICING_RESEARCH.md) extends fits
through 2026, adds complete raw January/August coverage, and opens predeclared
September/October raw days only after selection/model pinning. Overall survival
stays near target with no pauses, but frozen-state calibration still fails and
the expanding refit worsens it. A separate two-minute live recorder preflight
passes receipt/deadline checks; no eight-hour candidate capture has started.

The [full raw-oracle pipeline refit](FULL_RAW_PIPELINE_RESEARCH.md) expands the
main engine and frozen prior training, and explicitly scores frozen availability.
It does not repair August: the existing rule still offers 32/389 frozen paths
with 84.38% survival; no-pause restores availability but leaves 64.01% survival.
Exact minimum-width bounds expose the admission/forecast conflict. No candidate
is promoted or frozen for capture.

The [quantile-level feedback comparison](QUANTILE_LEVEL_RESEARCH.md) changes the
residual CDF level from matured survival errors. A fast variant raises June later
survival from 8/22 to 10/22 in both modes and improves several bursty panels, but
January phase cancellation, frozen/directional misses and larger losses remain.
It does not win earlier selection. No successor is promoted or frozen for capture.

The [28 October reliability repair](CAPTURE_RELIABILITY_20261028.md) adds native
wall-clock deadline checks and the versioned
`scripts/prospective_capture_v2.py` supervisor with receiver/supervisor health.
Use a rebuilt recorder and v2 supervisor for new captures. The original
supervisor remains unchanged for archived research reproducibility. Controlled
failure tests pass; actual host continuity and a new eight-hour capture remain
outstanding, alongside selection of a defensible adaptive candidate.

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

The [recalibrated round-2 run](PROSPECTIVE_RUN_20261026_ROUND2.md) completed its
frozen **eight-hour** protocol with a 314-ppm half-width and missed both the
survival and coverage requirements. The
[capture-gap and corridor investigation](CAPTURE_INVESTIGATION_20261027.md)
retains detailed attribution and comparisons; no successor has been chosen. The [first completed eight-hour run](PROSPECTIVE_RUN_20261026.md)
missed the 117-ppm survival hypothesis and is now explicitly retrospective
calibration data for round 2. The earlier 72-hour run was interrupted at the
user's request and retained with its original manifest and verified receipts.
The active supervisor keeps the
original deadline, writes `status.json` every five seconds, retains process logs,
and runs offline verification and analysis after collection ends. On macOS it
uses `caffeinate -i` while running; this prevents idle sleep, not shutdown,
reboot, power loss or loss of network/storage access.

The saved recordings also support an
[offline adaptive-corridor research replay](ADAPTIVE_CORRIDOR_RESEARCH.md).
Its past-only formula improves later calibration but still misses the reference
target band in the later recording. It is retrospective development evidence;
the live pricing policy and frozen capture evaluations remain unchanged.
The subsequent [historical regime-data research](ADAPTIVE_REGIME_DATA_RESEARCH.md)
retains additional third-party oracle samples and separate exchange-price proxies,
with direction-specific comparisons and native-capture transfer diagnostics.
The [pump calibration and stability iteration](ADAPTIVE_STABILITY_RESEARCH.md)
adds a bounded correction based on mature past windows. It improves conditional
calibration and native transfer, while a flat-heavy historical period remains
outside the reference band; no new capture or live pricing update has started.
The subsequent [flat/bursty oracle iteration](ADAPTIVE_ACTIVITY_RESEARCH.md)
adds pre-entry activity features and explicitly reports research pauses alongside
full-window shadow results. The difficult flat-heavy day still misses, so this
does not promote a successor or start collection.
The [flat-state pause comparison](FLAT_PAUSE_RESEARCH.md) holds pricing fixed
across twelve rules. A stricter mature-floor rule brings August's aggregate
survival into band at 78.10% eligible availability, versus 88.21% currently.
Earlier folds cannot distinguish that rule, and retained frozen entries still
miss conditionally. It remains a research alternative; capture stays on hold.
The [frozen-pricing and raw-history follow-up](FROZEN_PRICING_RESEARCH.md)
improves offered frozen calibration and exposes additional flat paths hidden by
normalized-message exclusions. A full January raw day supports the stronger
pause at a material availability cost, while startup and conditional failures
remain visible. These separate historical diagnostics do not authorize a new
capture or live pricing change.
The [startup admission iteration](STARTUP_ADMISSION_RESEARCH.md) compares
21 causal guards with fixed pricing and ten raw eight-hour restart tests.
Warmup and shorter floor memory improve some cases, but no policy passes all
of them; raw August also exposes non-frozen pricing misses. Earlier-fold
selection retains the previous guard. No new capture has started.
The [non-frozen pricing comparison](NONFROZEN_PRICING_RESEARCH.md) replays
thirteen refinements on 172 eight-hour case intervals with both admission masks
fixed. State feedback and a simpler correction-floor relaxation improve raw
non-frozen aggregate passes from 7/10 to 10/10 without changing availability.
Conditional bursty and pump/dump failures remain, feedback increases pricing
loss, and frozen misses persist. Neither is promoted; capture remains on hold.
The [bursty-only pricing follow-up](BURSTY_PRICING_RESEARCH.md) compares twelve
alternatives while holding admission and frozen quotes fixed. A pooled bursty
correction retains the simple floor's 10/10 raw overall/non-frozen passes and
improves bursty passes to 4/8, versus 1/8 for the floor and 3/8 for full feedback.
Its pricing loss stays close to the simple floor, but conditional misses and
startup/late cancellation remain. Earlier selection has only two sufficiently
populated bursty cases. No candidate is promoted and capture stays on hold.
The [bursty startup/drift comparison](BURSTY_STARTUP_DRIFT_RESEARCH.md) adds
phase-aware selection and identical-path restart/continuous comparisons. Faster
correction clocks improve raw bursty aggregate passes to 5/8, but January's
passing aggregate still hides startup/later cancellation. Time-weighted CDFs
improve pooled later calibration while leaving more whole-case failures.
Earlier-period selection retains the previous pooled correction; no successor
is promoted and no capture starts.
The [episode and full-day raw comparison](BURSTY_EPISODE_RESEARCH.md) adds
complete January/June 2025 controls and verifies the original short restarts.
June's 38.24% bursty failure persists in both restart and continuous modes.
Episode/feature refinements remove some January late overcorrection but leave
startup high. Earlier selection retains the previous pool. The added raw
references expose substantial normalized-data exclusions; no successor is
frozen and capture remains on hold.
The [chronological raw-prior recalibration](CHRONOLOGICAL_RAW_PRIOR_RESEARCH.md)
replaces matching training dates with expanded raw rows using only preceding
dates, while holding engines, frozen quotes and admission fixed. Bursty training
references rise from 453 to 591, but January 2026 startup remains 75% and June
2025 later survival remains 36.36% in both modes. Earlier folds retain the
normalized-prior pool; raw-prior replacement changes no bursty pass counts.
No new candidate is frozen and no capture starts.
The [earlier raw and bursty startup-admission comparison](EARLIER_RAW_STARTUP_RESEARCH.md)
adds complete November/December 2024 raw training days and 21 prior/admission
variants. Earlier raw coverage raises final bursty training support to 671 paths,
but January startup and June later drift remain. Warm6 removes all January 2026
startup quotes and reduces original raw bursty availability to 60.42%; context
and episode rules leave still fewer quotes. Earlier selection favors the new
raw priors with unchanged admission, based on one improving fold. No admission
successor is validated, no candidate is promoted and capture remains on hold.
The [pre-entry signal and conditional pricing comparison](PREENTRY_SIGNAL_RESEARCH.md)
tests twelve variants with fixed frozen decisions and explicit quote-retention
constraints. Learned flat-risk gates retain all bursty quotes but underestimate
January startup risk and never activate. Conditional pricing improves June
startup to 50%, while later survival remains 36.36% in both modes. January 2025
later pricing improves, but cross-period pass counts deteriorate. The retained
pool remains the benchmark; no new capture or live promotion follows.
The [chronological risk-calibration and retained-price adapter comparison](CALIBRATED_BURSTY_RESEARCH.md)
tests sixteen variants. All existing bursty quotes remain offered, but learned
calibration still underestimates January risk and June later survival stays at
8/22 in both modes. A finite-sample bound also shows that January's startup
cannot reach the reference band while retaining 90% of that case's quotes under
the current minimum width. Small June loss gains do not survive broader period
comparisons; the retained benchmark and capture hold remain in place.
The [expanded raw training comparison](EXPANDED_RAW_BURSTY_RESEARCH.md) adds
complete February–May 2025 raw coverage, increasing final bursty training paths
from 671 to 888. The expanded raw-mass adapter narrowly wins earlier selection,
but January startup and June's 8/22 later survival remain unchanged, with fewer
passes across other periods. Quote availability is preserved; this does not
justify freezing a successor or starting capture.
The [oracle–mark gap and adaptive quantile comparison](GAP_QUANTILE_RESEARCH.md)
tests five variants using saved market context and delayed quantile tracking.
It preserves quote availability and improves some aggregate losses, but June
later survival remains 8/22 and cross-period passes deteriorate. The retained
benchmark wins earlier selection; no successor or new capture follows.
The [isolated bursty-feedback comparison](BURSTY_FEEDBACK_RESEARCH.md) freezes
the fitted quantiles and tests three alternatives to shared correction transfer.
Bursty-only gap feedback wins earlier selection at 20.094 versus retained 20.812,
but June later survival remains 8/22 and broader passes remain below retained.
Admission stays fixed; the retained benchmark and capture hold remain in place.
The [bursty residual-quantile comparison](BURSTY_RESIDUAL_RESEARCH.md) adds
required-width ratios, longer memory and strictly chronological forecast priors.
The gap prior matches retained's later normalized pass counts at lower pricing
loss, but June later survival remains 8/22 and canonical raw passes deteriorate.
No successor is promoted or capture started.

The [automated parameter search](BURSTY_OPTIMIZER_RESEARCH.md) adds a bounded
Bayesian optimizer with cached pre-entry forecasts. Its 32-trial pilot takes
25 seconds after caching and improves earlier selection 20.094 to 15.788 while
retaining all benchmark quotes. Later results remain mixed: original raw passes
improve, January later pricing worsens and June later survival stays 8/22.
The retained benchmark and capture hold remain in place.

The [symbolic-regression comparison](SYMBOLIC_CORRIDOR_RESEARCH.md) searches
bounded pre-entry expressions with bursty-only and shared non-frozen training.
The shared model has 25,883 earlier references, including 911 pump and 902 dump
paths, but selects constant corrections after validation. Later normalized
restart pricing loss improves about 3.8% while populated bursty calibration
passes fall from 7/11 to 4/11. June later survival remains 8/22. Both audits pass;
the retained benchmark and capture hold remain in place.

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
