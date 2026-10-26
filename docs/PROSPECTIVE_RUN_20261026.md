# Prospective observation run — 26 October 2026

**Completed:** 56,147 receipts, all chain-verified; 944 healthy windows out of
960 (98.33% coverage); 123 survived (13.03%). The 117-ppm candidate missed its
43–53% target band. The following describes that retained experiment. A new
[recalibrated eight-hour run](PROSPECTIVE_RUN_20261026_ROUND2.md) is now collecting
fresh observations; this recording is calibration data for round 2.

The first completed observation-only recording started on **26 October 2026 at 05:26:28
WITA (UTC+8)**. At the user's request its fixed duration is **eight hours**, ending
**26 October 2026 at 13:26:28 WITA**. It runs in the background on this Mac. Keep
the Mac powered, connected and the `/Volumes/dev/fuse` volume mounted. Shutdown,
reboot or loss of network/storage can interrupt collection. No real funds,
trading, signing or public-chain deployment are involved.

Completed run directory: `.local/prospective-runs/20261026-117ppm-8h`.

The earlier 72-hour run started at 05:08:01 WITA and was cleanly stopped at
05:26:07 WITA when the user changed the requested duration. All **2,128 receipts**
passed offline verification. Its manifest still says 72 hours; it is retained as
an interrupted experiment in `.local/prospective-runs/20261026-117ppm-72h`, with
`interrupted-verification.json` and the user-request record. It has not been
relabeled as a completed eight-hour sample. `replacement.json` and
`supersedes.json` link the two runs. None of its observations were used to refit
the new run's candidate.

## Frozen research protocol

The retained calibration selected a fixed **117-ppm half-width (1.17 bps)** for
the 30-second corridor. The previous 41-window prospective result was marked
insufficient evidence and allowed unchanged-candidate observation. The newer
78-ppm fit was not substituted into this run. No candidate was refitted from
these new observations.

The original calibration, input policy, oracle/risk documentation, executable,
analyzer and supervisor were copied before collection. `analysis-spec.json`
commits their hashes, training-source hashes/cutoff, the fixed horizon and
descriptive analysis rules. The new policy preserves the fitted width and
historical error metadata, binds the analysis-spec hash, uses paper mode and
extends model validity solely for this observation period. That extension is not
a calibration or production approval. The capture manifest and its linked
receipt chain bind the resulting frozen policy.

The research minimum remains 400 healthy windows and 90% full-horizon coverage.
The declared first-stage hypothesis is 48% survival with a ±5-percentage-point
descriptive target band. Windows are fixed to the manifest-time grid, including
leading/trailing outages in the denominator. Regime coverage and effective sizes
are diagnostics; approved regime-specific safety/precision thresholds and
complete ladder/strategy validation remain outstanding. None of these research
criteria authorizes production.

## Operation and retained evidence

Check status from the repository root:

```sh
python3 scripts/prospective_capture.py status \
  --directory .local/prospective-runs/20261026-117ppm-8h
```

`status.json` reports process IDs, update/receipt timestamps, receipt count,
receiver timestamps and the original deadline. `capture.log` retains connection
errors; `supervisor.log` retains supervisor failures. A status value of
`recording` must be considered alongside fresh timestamps; a stale file is not
proof that a process remains alive.

At the deadline, the supervisor stops collection, verifies the entire retained
chain into `verification.json`, and writes `analysis.json` using the frozen
analyzer. It records completion or failure in `status.json`. It does not send a
chat notification. Do not edit or delete the frozen files, extend the deadline,
or silently truncate an incomplete receipt tail. An interrupted, intact run can
be resumed with its copied supervisor toward the original deadline after
confirming the old processes have exited; a corrupt tail requires preserved
evidence and an explicit recovery decision.

In the earlier 72-hour run, the first **578 receipts** were copied as a bounded
startup prefix and verified offline. On interruption the entire 2,128-receipt
recording was verified. Those proofs belong to the interrupted run; the active
eight-hour recording receives its own complete verification at its deadline.
Hash integrity does not establish economic viability.

## Recovery validation completed during collection

Retained local evidence: `.local/risk-validation/20261026-contract-e2e`.

The actual Anvil contracts, HTTP backend and PostgreSQL journal completed the
recovery-enabled journey. It covered deposit acknowledgement, accepted trading,
settlement, withdrawal payment/replay rejection, reward claims, reserve funding,
redemption/burns, signer rotation, database/controller restart, transient RPC
failure, LP entry/FIFO exit and a finalized-reorganization halt.

A synthetic local profile then reached a drawdown pause. Governance resume and
a new deposit did not erase recovery losses; new quotes were rejected while an
accepted withdrawal was funded and paid. These are local test limits, distinct
from production approval and from the observation-only recorder's unused trading
configuration.

`independent-arithmetic-retained.json` checks **649 journal events, four accepted
stages and four resolutions**. The separate Python checker agrees with native Go
replay and the final recovery state. Its proof retains journal, policy, snapshot,
checker and verifier hashes. This is an arithmetic cross-check of committed
outcomes, not independent price adjudication, a production signing controller or
external security approval. The E2E log's earlier 646-event count excludes the
final reorganization/halt events included in the exported 649-event journal.

Validation at setup: the contract/backend E2E passed with race detection,
`go vet ./...` passed, and all **84 Python tests** passed with the optional Go
research bridge enabled. CI now runs the recovery checker and retains the E2E
artifacts. The [production release gates](PRODUCTION_READINESS.md) remain open.
