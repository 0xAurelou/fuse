# Active capture continuity and policy validation — 29 October 2026

The frozen BTC trial remains on its original **06:31:07.783 WITA** deadline.
The two collectors and original supervisor continue running. No capture,
model, policy, threshold, original source, start time or deadline was changed.
Pricing outcomes have not been inspected.

Evidence: `.local/capture-readiness/20261029-active-continuity-v1/`.
Trial: `.local/prospective-runs/20261028-adaptive-context-8h-v1/`.

## Observed outages

The full receipt-prefix timestamp audit found simultaneous receiver gaps:

| Receiver a, WITA on 28 October | Receipt silence |
| --- | ---: |
| 22:51:26.107 → 22:57:07.530 | 341.423 seconds |
| 22:57:31.199 → 23:07:39.465 | 608.266 seconds |

Receiver b has the same two outages within milliseconds. Archived macOS events
show clamshell sleep at 22:51:26, dark wakes and maintenance sleeps, and lid/HID
wake at 23:06:38. Capture warnings also show an unavailable local address, DNS
failures and read timeouts during these intervals. These are common host and
network failures; two sockets do not give independent availability.

At **00:10:04.245 WITA**, the bounded prefix contained 9,726 receipts. Of 197
elapsed complete grid windows, **34 necessarily fail receiver freshness**,
including startup and grid rounding around the outages. The elapsed healthy
fraction is therefore **at most 163/197 = 82.74%**. Across the original 960-window
horizon, even perfect remaining freshness permits **at most 926/960 = 96.46%**
healthy coverage. The frozen 90% collection threshold remains possible.

These are necessary-failure bounds. They do not evaluate oracle equality,
receipt digests, adaptive eligibility, quote availability or survival. Those
checks can reduce final quality further. A fresh instantaneous status after
reconnection cannot establish uninterrupted collection.

The user expects another ten minutes of sleep while travelling home. That
interval remains an observed outage. No power-setting override, deadline
extension, gap interpolation or replacement attempt was introduced. Qualification
depends on the complete original horizon, including any further gaps.

### Third outage, observed by 01:41 WITA

The next full-prefix audit identifies a third simultaneous outage on 29 October:
receiver a has no receipt from **01:31:01.630 to 01:35:19.307** (257.677 seconds),
and receiver b from **01:31:01.581 to 01:35:25.607** (264.026 seconds). The host
log records clamshell sleep at **01:31:01** and wake at **01:35:05**, followed by
the observed receiver recovery. No additional reconnect warning was logged.
The logs establish sleep alignment; no missing prices are reconstructed.

At **01:41 WITA**, 43 of 380 completed grid windows necessarily fail freshness,
an increase of nine. Current receiver freshness has recovered. The elapsed
healthy fraction is at most 337/380 = **88.68%**; across the full original horizon,
the best possible healthy fraction is now 917/960 = **95.52%**, before checking
oracle equality, receipt digests or other eligibility rules. The 90% final
threshold remains possible, and the fixed run continues without extension.

Evidence: `.local/capture-readiness/20261029-continuity-incident-v2/`, including
the bounded-prefix report, filtered power events and capture warnings. The
earlier 34-window and 96.46% figures above are explicitly the earlier snapshot.

A subsequent power check reports **AC Power**, but also a **56% discharging
battery and 3h03 remaining**, with about 4h48 still needed for the original run.
This contradictory-looking status is recorded without diagnosing its cause.
The user confirmed **“Charger checked; lid will stay open.”** The immediate
subsequent system read still reports 56% discharging, so the confirmation and
observed power status are retained separately in `user-power-confirmation.json`;
power availability is not inferred from the answer alone. No power setting,
original capture process or frozen model was changed.

At the next power follow-up, the battery had fallen to **54%** and still
reported discharging, with approximately 2h47 estimated remaining. `pmset`
identified AC power, while a filtered battery-registry read reported
`ExternalConnected=false` and `IsCharging=false`; adapter wattage was not
available. These readings establish continued discharge but do not establish
its cause. The sanitized observation is retained as
`power-followup-0153.json` in the incident packet. The user was advised that a
direct connection to a known-working Mac charger and charging cable is the
next useful physical check. No software power settings were changed.

### Further sleep and reconnect gaps, observed through 02:20 WITA

The host subsequently records **clamshell sleep at 02:12:20**, dark wake at
02:15:42, maintenance sleep at 02:16:02 and dark wake at 02:18:16. This is
observed after the user's earlier power/lid confirmation; the logs do not
establish why the host entered those states. The recorder and completion-only
follow-up remain alive. The frozen collector reconnects without a restart.

Receiver a has a **407.311-second** interreceipt gap from 02:12:19.591 to
02:19:06.902. Receiver b has a **372.276-second** gap from 02:12:19.574 to
02:18:31.850, then a **16.831-second** gap before both are recovered by
02:19:07.185. Separate normal-expiry reconnects at 02:03 and 02:04 have
17.208- and 17.378-second gaps, respectively. These all remain subject to the
original eight-second freshness rule.

At **02:20:40 WITA**, both receivers are fresh and **60 of 459 completed
windows** necessarily fail freshness. Final healthy coverage is therefore
bounded above by **900/960 = 93.75%**, even with no further failures. The 90%
gate remains possible, not established; oracle agreement and native digests
still require final verification. The previous 43-window/95.52% and first
59-window/93.85% observations remain historical snapshots. No pricing outcome
has been evaluated, and the original 06:31:07.783 deadline is unchanged.

Evidence is retained in
`.local/capture-readiness/20261029-continuity-incident-v3/`. Its first snapshot
contains a still-open stale span and brief receiver-b recovery; its follow-up
records closed gaps and recovery of both feeds. The user was notified of the
new observed sleep and asked to wake the Mac and keep it awake. No power
setting, original process, candidate or frozen analyzer was changed.

### Power decline through 03:49 WITA

After the earlier charger confirmation, the battery continues to decline while
`pmset` identifies AC power. A follow-up physical question at approximately
02:33 asked whether a different known-working charger/cable or outlet could be
tried; no answer to that new question has been received at this snapshot.
By **03:49 WITA**, battery is **20%, discharging, approximately 1h05 remaining**,
with roughly **2h43** still needed for the original capture. The user was
notified that the Mac risks losing power before the deadline and asked to
connect a working charging source. The cause remains unestablished.

Repeated checks confirm that the original recorder and completion monitor are
still alive and the receivers are fresh. A fresh bounded-prefix audit records
**60 affected windows among 635 completed**, preserving the **93.75% best
possible final healthy-coverage bound**. This does not establish native digest
validity, oracle agreement or the final 90% quality gate. No pricing or
economics outcome has been inspected. The current horizon remains unchanged.
The six recent power observations are retained in the incident-v3 packet as
`power-trend-0330-0348.json`; the new continuity snapshot is
`20261029-adaptive-followup-v1/continuity-0349.json`.

At approximately **03:54 WITA**, two subsequent system reads report **26% and
charging**, up from the earlier 20%. This directly observed charging recovery
supersedes the earlier discharging state at this timestamp; its cause is not
inferred from the still-unanswered physical-power question. Both receivers are
fresh and the original recorder and completion monitor remain live. Evidence
is retained as `power-recovery-0354.json` in the incident-v3 packet. No capture
restart, deadline extension, pricing change or software power-setting change
was made.

The user subsequently confirmed **“We are good now.”** By **04:19 WITA**,
charging has persisted and the battery reports **55%**. The latest bounded
prefix still records **60 affected windows among 695 completed**; its final
healthy-coverage upper bound remains **93.75%**. Both receivers are fresh and
the original recorder and completion monitor remain live. The user's answer
and a fresh system read are retained separately in `user-power-resolution.json`,
alongside the power trend through this check. The cause of the charging
recovery is not inferred. No live pricing or economics outcome was inspected.

At **04:43 WITA**, battery has reached **76%**, and two reads now report
discharging with an estimated **5h17 remaining**, versus approximately **1h48**
left in the original capture. That estimate exceeds the remaining horizon;
it is not a guarantee or an explanation of the charging-state change. The
already authorized run continues without a new physical-confirmation request.
The timestamp-only audit still finds **60 affected windows among 744 completed**
and the same **93.75%** final healthy-coverage upper bound. Both receivers are
fresh. This observation is retained as `power-followup-0443.json` and
`20261029-adaptive-followup-v1/continuity-0443.json`.

### Normal-expiry reconnects, audited at 05:30 WITA

Two further receiver gaps coincide with logged **WebSocket close 1000 (normal):
Expired**: b from **05:12:22.174 to 05:12:39.271** (17.097 seconds), then a from
**05:13:45.350 to 05:14:02.041** (16.691 seconds). Queried host power logs have
no matching sleep/wake entries in the observed 05:00 onward interval. Both
receivers reconnect within the original running collector; no restart or
deadline change is made.

At **05:29:54.724 WITA**, the bounded-prefix audit finds **63 affected windows
among 837 completed**, including three additional freshness failures. Final
healthy coverage is now at most **897/960 = 93.4375%**, even with no further
losses. The 90% collection gate remains possible and still requires final
native verification and oracle-agreement assessment. Both receivers are fresh,
the original recorder and completion monitor are live, and all 110 frozen files
verify unchanged. Pricing and economics outcomes remain unread.

Evidence is retained in
`.local/capture-readiness/20261029-continuity-incident-v4/`, including the two
reconnect log entries and the timestamp-only prefix report. Earlier 60-window
and 93.75% bounds remain historical observations.

## Read-only observer

`scripts/capture_continuity.py` fixes a byte boundary before reading a growing
receipt file, streams only that prefix, ignores a partial final line, and
records its SHA-256. It checks sequence/linkage, source names, monotone receipt
times and all 110 frozen artifacts. It does not acquire the native writer lock
or read oracle values for its calculations. It explicitly does **not** claim
native genesis/digest verification. Native verification remains a post-capture
step.

Freshness equality is inclusive at 8,000 ms. A stale prior state at a boundary
can invalidate the previous expiry and next entry; these closed boundaries are
included in the necessary-failure count. Post-deadline receiver silence is
reported separately from freshness at the original horizon end.

## Policy serialization defect

The native manifest's policy is semantically unchanged, but it differs as a
JSON object from `frozen-policy.json`. Go's `Model` has four integer fields
without `omitempty`: `base_width_bps`, `control_width_bps`, `max_drift_bps` and
`volatility_factor`. Absent input fields decode as zero and appear explicitly
when Go writes the manifest.

The actual differences are exactly nine added zeros: `model.max_drift_bps`
and all four fields in each optional ETH/HYPE model. The BTC adaptive candidate
and transport width are unchanged. The frozen analyzer uses exact object
equality and therefore will reject this manifest before pricing. Its failure
must remain in the original record. A successful numerical replay cannot erase
that end-to-end procedural defect.

Before inspecting pricing outcomes, a separate compatibility packet was prepared:
`.local/capture-readiness/20261029-adaptive-policy-compat-v1/`.
Its `compatibility-spec.json` pins the original specification/analyzer/manifest,
the supplemental source, helper and exact diff. The repair permits only the four
declared absent-integer-to-zero expansions and requires every other field and
value to match. Unknown fields, nonzero differences, Boolean/float zeros and
missing emitted fields fail. It adds explicit procedural-repair metadata to
the output. All numerical pricing, data, replay, horizon, native verification
and quality checks remain the frozen implementation.

The supplemental analyzer has **not run on the live capture**. A separately
pinned completion-only follow-up now waits for the original supervisor to finish
and preserve its verification/failure, then executes the pinned arguments and
`PYTHONPATH` in the compatibility specification. Results stay in that separate
packet, preserving the original trial. Both packets' hashes are checked again
before execution. Read the follow-up status before attempting any manual
invocation, to avoid competing for the same output. A corrected future freeze
needs an end-to-end recorder/analyzer preflight that exercises native policy
serialization.

### Completion-only follow-up

Directory: `.local/capture-readiness/20261029-adaptive-followup-v1/`.
`followup-spec.json` binds the source, original specification, compatibility
packet, exact original process IDs and 06:31:07.783 WITA deadline. Source SHA-256:
`040fd23a9eb78eebbdd17c9041e6452f1f5aaa22044d34faf13eb119cb5c0f3c`.
At launch it confirms original supervisor 34507 and recorder 34511 are live;
the follow-up's process ID is 63611. `status.json` and process inspection supply
current state; a saved PID alone is not proof of liveness.

Before the original end it reads only static bindings, process identities and
saved status. It does not read live receipts or pricing outputs, acquire the
native capture lock, change power settings, stop a process, restart collection
or extend its horizon. Both original handles must exit, the original terminal
state and native verification must be present, and all pinned hashes must match
before the supplemental analyzer is invoked. The analyzer independently checks
native receipts and the original horizon again.

Process-inspection errors remain observation retries rather than terminal
capture decisions. Early termination, changed identities, absent verification,
changed files or a post-deadline supervisor that fails to finish require review.
The drain allowance starts when the follow-up observes the elapsed deadline,
allowing the original supervisor to finish after host resume without extending
the recording horizon. A separate ownership lock and exclusive execution receipt
prevent simultaneous or repeated analysis attempts.

An offline, native-verified synthetic smoke test exercised the entire follow-up
and supplemental analyzer, preserved the synthetic original failure, and wrote
the disclosed result. A second execution attempt was rejected without changing
the earlier result/status/receipt. Evidence is retained in
`.local/capture-readiness/20261029-followup-smoke-v2/`; its historical clock and
oracle data are explicitly synthetic. The first synthetic fixture's invalid
out-of-range test PID correctly caused observation retries; only that helper
was stopped, and its failure record remains under `...followup-smoke-v1`.
Three targeted tests cover deadline/handle gates and process-observation errors;
the full suite passes **382 tests with three existing optional skips**. None of
this is evidence about the live candidate's pricing performance.

## Verification and interpretation

The full Python research suite passed: **363 tests, three existing optional
skips**. New checks cover growing-file boundaries, partial tails, metadata
rejection, no price dependence, post-horizon ages, exact-zero policy comparison,
and 100 randomized synthetic constant-oracle paths against the original health
analyzer. A synthetic replay with a fixed reference-price fixture produces
identical numerical summaries and decompressed predictions with and without
the policy-comparison repair. The live model packet remains untouched.

### Full native/synthetic preflight

The follow-up preflight uses the actual archived model bundle and complete
unchanged pricing stack, with Go-generated synthetic native manifests and hash
chains. The exact frozen `fuse-capture` binary independently verifies the chains.
No live receipt file is opened, and no network is used. Artificial historical
clocks and fabricated oracle schedules are explicitly marked as synthetic.

Evidence:
`.local/capture-readiness/20261029-synthetic-adaptive-preflight-v2/` and
`.local/capture-readiness/20261029-synthetic-adaptive-audit-v1/`.
The first implementation attempt is preserved separately as `...preflight-v1`;
it stopped before native verification because the copied executable lacked its
execute bit. The corrected attempt explicitly preserves executable access.

| Synthetic eight-hour input | Native receipts | Healthy windows / original 960 | Quality gate |
| --- | ---: | ---: | --- |
| Continuous feed | 14,400 | 959 / 960 | Pass |
| Ten-minute common outage | 14,100 | 938 / 960 | Pass |
| Ninety-minute common outage | 11,700 | 778 / 960 | Fail |

For each input, the supplemental analyzer matches every numerical summary and
all 5,760 prediction records against the **unmodified** analyzer supplied with
the equivalent explicit-zero policy. Across the three cases, the audit compares
**17,280 predictions**, verifies **40,200 native receipts**, and independently
reconstructs the exact freshness losses without inspecting oracle values for
that calculation. The original JSON-object comparison rejects the unexpanded
input as expected. The canonical control also demonstrates why a future freeze
should canonicalize the native policy before binding and collecting it.

Four actual subprocess failure checks reject an unelapsed original horizon, a
nonzero manifest policy change, a tampered receipt and a changed frozen model.
None writes a pricing result. `go vet` passes for the isolated generator.
The audit hashes all retained preflight artifacts; it leaves the original
110-file trial and separately prepared compatibility packet unchanged.

These fixtures establish software behavior and replay parity. Their quality
passes and numerical predictions provide **no real-market calibration or
prospective evidence**, and do not predict the duration of the user's actual
sleep or reconnection delay.

The next evidence is the final native verification and original fixed-horizon
quality assessment, followed by the disclosed supplemental frozen-model replay.
Neither current health bounds nor a 48% point rate establishes cross-regime
calibration, production readiness or validated payout/LP economics.

### Separate future preparation fix

`freeze_adaptive_capture_v2.py` now canonicalizes a future policy with the exact
retained recorder before final binding. Two empty offline probes establish
native policy roundtrip conformance; a separate nonempty synthetic fixture
passes the unchanged original analyzer and native receipt verification.
This leaves the current trial and its disclosed compatibility procedure
untouched. See `NATIVE_CANONICAL_FREEZE_20261029.md` and the retained
`20261029-future-canonical-freeze-v1` preflight packet. The full current workspace
suite passes 425 tests with three existing optional skips, including four new
native integration tests. This software result is not market validation.
