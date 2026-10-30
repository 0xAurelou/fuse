# Capture reliability repair — 28 October 2026

Follow-up: the [later chronological report](TEMPORAL_PRICING_RESEARCH.md) records
a successful two-minute live preflight with 234 verified receipts, maximum
receiver gaps below 1.64 seconds and completion output about 14 ms after the
original deadline. This is short recorder health evidence, not a new eight-hour
pricing capture or a physical suspend/resume drill.

The native recorder now checks the original wall-clock deadline after wakeup,
including when both receiver sockets remain silent. A versioned supervisor adds
a separate deadline stop and reports receiver freshness and supervisor liveness.
These changes address the delayed-exit failure found in the
[capture investigation](CAPTURE_INVESTIGATION_20261027.md). They do not repair
missing observations or establish unattended host uptime. No new pricing
candidate is promoted, no model is frozen, and no prospective capture starts.

The retained benchmark and candidate-selection hold remain. The
[symbolic comparison](SYMBOLIC_CORRIDOR_RESEARCH.md) still supplies the latest
calibration evidence. Near-48% survival, quote availability, consistency and
prospective evidence remain distinct requirements; payout and LP economics
remain unvalidated.

## Deadline and continuity behavior

`engine/internal/capture/wall_deadline.go` samples UTC wall time on a one-second
ticker. It checks the current clock rather than a delayed ticker's timestamp.
An expired restart cancels immediately; crossing the deadline cancels the oracle
collector and closes both connections. The native append still rejects receipts
at or beyond the original deadline. Crossing that boundary between the caller's
check and the serialized append now produces a normal horizon stop, rather than
a storage-failure classification. The manifest format and receipt hash chain are
unchanged.

`scripts/prospective_capture_v2.py` independently compares wall time to the
manifest deadline during its five-second supervision cycle. It requests a
graceful stop, allows ten seconds for shutdown, then kills an unresponsive child.
A nonzero exit or a failed native verification leaves the run failed. Completion
still requires the original horizon to elapse, frozen-artifact verification,
native receipt verification and offline analysis. Interruption, low disk space
and early exit cannot become successful horizon completion. The supervisor never
extends the deadline or changes the eligible-window rules. Attempting to restart
a completed run is rejected before overwriting its final status.

New status reports include each receiver's receipt age and freshness against the
frozen `max_gap_ms`, whether both receivers are stale, and supervisor liveness
with a fifteen-second reporting threshold. A receiver's last observed timestamp
persists across status writes even when its messages disappear from the bounded
receipt tail. The `status` command recomputes health using the reader's current
clock, so an old healthy report exposes a stopped supervisor. These are receipt
freshness indicators; they do not certify price agreement, oracle correctness,
or eventual healthy-window coverage.

No process runs while the host is asleep. Ticker checks and supervisor polling
therefore apply once the host resumes and scheduling permits. The existing Mac
`caffeinate -i` guard still prevents idle sleep only. A powered open-lid Mac or
an always-on host, plus an external observer for stale health, remains required
for an unattended attempt. No external alert service was installed.

## Versioning and next capture

Historical research archives hash `scripts/prospective_capture.py` as an input.
That script remains byte-identical. Use the v2 supervisor and a freshly built
recorder for any new attempt; existing frozen recordings and their executables
remain untouched. The v2 freeze snapshots its own executable Python source as
`supervisor.py`, along with the existing policy, analyzer and binary bindings.
The v2 freeze still accepts a fixed fractional-width calibration. An adaptive
candidate requires a separately frozen formula, update rules, history and
admission rules, and evaluation plan before a prospective adaptive test.

After candidate selection, build the recorder as usual and use:

```sh
python3 -B scripts/prospective_capture_v2.py freeze \
  --directory /absolute/path/to/new-run \
  --calibration /absolute/path/to/calibration.json \
  --policy /absolute/path/to/policy.json --hours 8
python3 -B scripts/prospective_capture_v2.py run \
  --directory /absolute/path/to/new-run
python3 -B scripts/prospective_capture_v2.py status \
  --directory /absolute/path/to/new-run
```

Place the rebuilt `fuse-capture` binary inside that new directory before freezing.
These commands describe the successor collection workflow; they do not select
or authorize a pricing candidate by themselves.

## Verification

Four new Go tests cover an already-expired deadline, parent cancellation,
wall-clock advancement beyond an eight-hour horizon with an old tick timestamp,
append-boundary crossing, and cancellation of two connected silent WebSockets
after a simulated sixteen-hour-late resume. The original horizon and receipt
chain verify afterward. This is a deterministic simulated clock jump, not an
actual machine suspend/resume drill.

Eleven new Python tests cover receiver freshness/equality boundaries, missing feeds,
clock regression, stale saved status, bounded-tail continuity, v2 source freezing,
supervisor deadline enforcement, forced shutdown, interruption/disk stops,
early exit, completed-run restart rejection and failed native verification. Tests use local fixtures and injected
clocks rather than a live eight-hour stream. Existing freeze tests remain intact.

The retained evidence directory is
`.local/capture-readiness/20261028-v1/`, including a rebuilt recorder, source
snapshots, hashes and test logs. The existing research input/source bindings were
also checked after introducing the v2 module, without rewriting those archives.
The full Python suite passes 295 tests with three existing optional skips;
capture/oracle Go race tests and targeted `go vet` also pass. Retained bindings
verify 279,080 feature records, 25,883 OOF training paths and 130 input sessions.

Reproduction:

```sh
cd engine
GOCACHE=/private/tmp/fuse-go-cache go test -race \
  ./internal/capture ./internal/oracle ./cmd/fuse-capture -count=1
GOCACHE=/private/tmp/fuse-go-cache go vet \
  ./cmd/fuse-capture ./internal/capture ./internal/oracle
cd ..
OPENBLAS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 OMP_NUM_THREADS=1 \
  python3 -B -m unittest discover -s scripts -p 'test_*.py'
```

Remote CI and a physical host suspend/resume drill were not run. A reliable new
eight-hour recording remains an outstanding milestone.
