# Recalibrated eight-hour prospective run — round 2

Status at setup: collecting observations. Start: **26 October 2026, 17:11:54
WITA (UTC+8)**. Fixed deadline: **27 October 2026, 01:11:54 WITA**.

Active directory: `.local/prospective-runs/20261026-round2-314ppm-8h`.
Calibration: `.local/pricing-recalibration/20261026-round2-8h`.

The previous completed [117-ppm recording](PROSPECTIVE_RUN_20261026.md) had 944
healthy windows, 98.33% coverage and 13.03% reference-window survival. It missed
the predeclared 43–53% target band. Its frozen files, receipts and evaluation are
unchanged. Those observations are now explicitly calibration data for round 2;
they cannot provide fresh prospective validation of the new candidate.

## Candidate selection

The loader verifies the completed receipt chain with its original frozen Go
executable and checks its completion status before extracting windows. It uses
the same manifest-time grid, receiver freshness, disagreement and outage rules
as the original analysis; 16 censored windows remain excluded. It does not create
a synthetic engine journal or interpolate across outages.

Eligible windows were split chronologically 60/20/20. Only the first 566 windows
selected the width, using the existing exact integer survival frontier with a
48% target and the narrowest width as the tie-breaker. The result is a fixed
**314-ppm half-width (3.14 bps)**, replacing 117 ppm for this new experiment.

| Retrospective segment | Healthy windows | Survival at 314 ppm |
| --- | ---: | ---: |
| Training | 566 | 47.88% |
| Validation diagnostic | 189 | 49.21% |
| Final diagnostic | 189 | 69.84% |

The high final-segment survival suggests temporal/regime drift. These figures do
not establish a stable 48% survival model. The candidate was not tuned again to
the final segment. This eight-hour capture is the fresh prospective evaluation.
Full-ladder conditional survival, costs, funded demand and production approval
remain outside this experiment.

## Freeze and operation

The new run pins its calibration, source receipt/manifest/verifier hashes,
training cutoff, candidate policy, executable, analysis code and preparation
code before collecting new observations. The source completed at 13:26:28 WITA,
strictly before the new freeze and collection. `recalibration-lineage.json`
records the transition without rewriting the old experiment.

The first-stage research hypothesis remains 48% ±5 percentage points, with at
least 400 healthy windows and 90% full-horizon coverage. Regime/effective-size
statistics remain descriptive. There is no within-run refit or early stopping
for success. Future analysis must not silently combine this run with the data
used to select its width.

Check status:

```sh
python3 scripts/prospective_capture.py status \
  --directory .local/prospective-runs/20261026-round2-314ppm-8h
```

The supervisor records status every five seconds. At the fixed deadline it
verifies the complete chain into `verification.json`, writes `analysis.json`,
and records completion or failure. On macOS it prevents idle sleep while
running. Keep the Mac powered and connected, and the workspace volume mounted;
shutdown, reboot or unavailable storage/network can interrupt collection. It
does not send a chat notification. No funds, trades, signing or public-chain
execution are involved.

## Reproducibility

`scripts/calibrate_capture.py` prepares a calibration from completed receipt
recordings. `scripts/capture_dataset.py` verifies their provenance and eligibility.
`scripts/prospective_capture.py freeze` supports both legacy engine journals and
verified receipt datasets, rechecking the exact source before freezing. Updated
candidate labels and scope use the actual width rather than hardcoding 117 ppm.

Setup checks covered exact touch arithmetic, chronological split isolation,
overlap removal, completed-source requirements, tamper detection and freezing a
different-width eight-hour candidate. The full Python suite ran 89 tests with
three optional Go-bridge tests skipped. The prospective result is pending.
