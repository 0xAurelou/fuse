# Later chronological pricing comparison — 28 October 2026

The subsequent [conditional frozen-distribution experiment](FROZEN_CONDITIONAL_CDF_RESEARCH.md)
tests pre-entry floor probabilities and positive movement quantiles. Timing-only
context still does not improve cross-period quote calibration; fresh market
context remains a separate follow-up lead.

The selection window now reaches the later oracle regimes rather than ending
with the original fourteen training dates. Complete retained raw January and
August 2026 days enter only when chronologically permitted. Two newly downloaded
raw September/October days are opened only after the earlier choice and all
models are pinned. The fixed retained benchmark with no pauses wins this
comparison, but conditional failures remain. No adaptive candidate is promoted
or frozen for an eight-hour capture.

The run took **117.88 seconds**, excluding the separate download and audit.
Artifacts are retained in
`.local/adaptive-corridor/20261028-temporal-pricing-v1/`; the reusable 24-date
cache is in `.local/adaptive-corridor/20261028-temporal-data-v1/`.

## Coverage and chronology

The cache preserves all 24 existing normalized sample dates and ten complete
raw replacements: November 2024–June 2025, January 2026 and August 2026. Each
full day has the original 2,880 half-minute grid entries, including invalid
outcomes and missing pre-entry history. A date is never counted twice in a fit.
No partial panels are merged into a full-day replacement and no gap is filled.

The new raw comparisons cover **1 September and 1 October 2026**, complete UTC
days. The request list and study family were declared before downloading. All
**2,880 minute responses** downloaded successfully, totaling **5,519,534 compressed
bytes**. Gzip CRCs, local hashes, minute coverage and declared request URLs verify.
Tardis documents first-of-month historical feeds as available without a key;
no authenticated or paid request was used. See the
[provider API reference](https://docs.tardis.dev/api/http-api-reference).

These are new raw observations on dates whose normalized data was already
inspected. They are third-party single-stream oracle history, not native paired
receipts, untouched calendar-date holdouts, or a live prospective capture.

| Prefix training dates | Scoring dates | Raw replacements permitted to train |
| --- | --- | --- |
| First 14, through December 2025 | January–March 2026 | Eight earlier full raw days |
| First 17, through March 2026 | April–June 2026 | Above plus January 2026 |
| First 20, through June 2026 | July–August 2026 | Same nine raw days; own August excluded |
| First 22, through August 2026 | September–October, later diagnostics | Above plus August 2026; later raw excluded |

All training labels must mature before the cutoff. The new final model fits
63,360 grid rows, including **4,332 clean frozen-state references** and ten raw
replacement dates. Its period-balanced frozen minimum-width probability is
**21.55%**. Extra frozen paths do not make a single scalar prior condition on
the particular kind of oracle inactivity at a new entry.

## Predeclared comparison

The fixed retained pipeline is compared with a raw-core pipeline refitted on
each expanding prefix. Both use the preceding activity engine, frozen hurdle
overlay, floor10 non-frozen relaxation and bursty pool formulas. There are five
admission policies per stage: existing frozen floor, warm6/floor12,
warm6/floor30, warm12/floor30, and no pause. The new short rules use the existing
causal guard implementation with six mature startup paths and twelve/thirty
recent paths. Refused reference labels still mature and teach the models.

The full-state objective, phase charge, full-reference loss guards and
provisional 85% overall / 50% populated-frozen availability screens are unchanged
from the immediately preceding full-raw study. The score includes frozen,
active, sparse, bursty, pump and dump calibration. Restarts use available
pre-entry history but start with private calibration state; continuous replay
does not reset at eight-hour scoring boundaries.

| Variant | Earlier score | Availability screens |
| --- | ---: | --- |
| Fixed retained, no pause | **12.283** | Pass |
| Expanding raw core, no pause | 12.420 | Pass |
| Fixed retained, warm6/floor12 | 34.265 | Fail |
| Expanding raw core, warm6/floor12 | 34.325 | Fail |
| Fixed retained, existing floor | 61.886 | Fail |
| Expanding raw core, existing floor | 62.047 | Fail |

The other warmup variants also fail availability. The new later selection
therefore reveals a problem the earlier normalized-only folds missed: every
tested pause policy violates the availability screen in some case. Selecting
no pause establishes availability in this comparison; it does **not** establish
conditional calibration or remove the January/August minimum-width conflicts.
The selection and all four prefix model bundles are saved and hashed before
opening September/October raw payloads. Later results cannot change the ranking.

## Newly opened raw comparisons

The two raw days contain **168,883 messages**. All **111,795 shared normalized
timestamps** have matching oracle values. Raw and normalized formats retain
their own freshness and history exclusions; a missing normalized update is not
treated as proof of a raw feed outage. The raw days have 5,527 clean eligible
paths and **49 frozen paths per day**, compared with 22 and 29 clean frozen
paths in the earlier normalized feature cache.

| Raw date | Fixed retained, restart / continuous survival | Expanding raw core, restart / continuous |
| --- | --- | --- |
| September 2026, all states | 48.19% / 48.08% | 48.01% / 47.90% |
| October 2026, all states | 47.60% / 47.42% | 47.31% / 47.09% |
| September, frozen (49 paths) | **34.69% / 36.73%** | **24.49% / 28.57%** |
| October, frozen (49 paths) | 48.98% / 48.98% | 42.86% / 42.86% |

Both no-pause variants offer all 5,527 eligible paths in each mode. They issue
5,548 quotes on the 5,760 raw grid entries; missing pre-entry history still
prevents a quote and later-invalid outcomes are not used for entry decisions.
All six raw eight-hour overall cells pass the descriptive 43–53% screen in both
modes. The overlapping restart/continuous results are not independent samples.

The fixed benchmark's pooled raw pump survival is **48.56% restart / 48.08%
continuous on 208 paths**; dump survival is **50.78% / 50.26% on 193**. These
pooled rates conceal variation across the smaller per-period groups. Frozen
eight-hour passes are **1/2 populated cells** in both modes: September 00:00 has
**12/35** survivors in either mode, while October 16:00 has **14/28**. The
expanding model has 8/35 and 13/28. Thin-cell point estimates are descriptive,
not probability certifications; near-target pooled survival alone is insufficient.

The warm6/floor12 rule retains only **61/98 frozen quotes restart** and **63/98
continuously** across these days without improving frozen calibration. It even
removes all four eligible frozen quotes in September's 08:00 restart. Opening
fewer quotes cannot be mistaken for solving the forecast problem.

## Verification

The audit rebinds the 24-date cache to its verified parents and all ten complete
raw replacements, replays selection from pinned models, reparses and replays the
later raw data, and recomputes **691,200 prediction records**. Counterfactual
refits at the seventeen- and twenty-two-date cutoffs remain identical when own
and future labels change. Every candidate's actual August quote/admission state
is unchanged until the declared expiry-plus-thirty-second maturity boundary.
All 279,080 parent feature bindings verify. Four new tests cover complete-day
grids, source replacement, later cutoff isolation, private restart inputs and
delayed short-guard decisions. The full Python suite passes **311 tests, with
three existing optional skips**. No dependency was installed; remote CI was not
run.

```sh
OPENBLAS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 OMP_NUM_THREADS=1 \
  python3 -B scripts/research_temporal_pricing.py \
  --dataset .local/adaptive-corridor/20261028-temporal-data-v1 \
  --raw .local/market-history/tardis-hyperliquid-BTC-temporal-late-v1 \
  --previous .local/adaptive-corridor/20261028-full-raw-pipeline-v2 \
  --output /absolute/path/to/new-temporal-run
OPENBLAS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 OMP_NUM_THREADS=1 \
  python3 -B scripts/audit_temporal_pricing.py \
  --output /absolute/path/to/new-temporal-run
```

The archive has 5,760 case/group rows, 5,760 regime/group rows, 1,440 phase rows,
3,600 finite-bound summaries and 360 paired comparisons across 72 intervals in
48 sessions. These include both raw and normalized later panels on the same
dates and repeated policies, not that many independent experiments.

## Next pricing step and live recorder preflight

The data now include high-floor frozen conditions in January/August and
low-floor frozen conditions in September. Simply increasing raw training and
using a common frozen prior makes the later low-floor quotes worse. The next
pricing experiment should condition the minimum-width probability and positive
movement distribution on pre-entry context, rather than choose another broad
pause threshold from a common frozen pool. This remains developmental work;
the September/October data are now inspected development data as well.

A separate **two-minute live recorder preflight** completed with 234 natively
verified receipts, 117 per receiver. Maximum receipt gaps, including horizon
boundaries, were 1,630 and 1,635 ms against the 8,000-ms limit. No receipt lies
outside the original horizon; completion JSON was written approximately 14 ms
after its deadline. Three of four full windows are healthy; the initial window
has no entry price at freeze. Evidence is in
`.local/capture-readiness/20261028-live-preflight-v1/health-report.json`.

The preflight evaluates no corridor survival and selects no model. It confirms
a short live receipt/deadline path, not unattended eight-hour continuity or a
physical suspend/resume drill. The copied executable's permission was restored
before the recorder created a manifest or receipts; the initial shell failure
is retained in the log. A frozen adaptive candidate, its new eight-hour capture
and validated payout/fee/cost/strategy-conditioned LP economics remain open.
