# Matched market context and priceability feedback — 28 October 2026

The earlier-fold winner improves the aggregate selection score while leaving
quotes open, but it still fails cross-period frozen-oracle calibration. Fresh
mark/oracle context adds very little beyond changing the online feedback rule.
The winner is now a **frozen research challenger for prospective falsification**,
not a validated pricing policy. A new observation-only eight-hour capture is
running; its [frozen plan](PROSPECTIVE_ADAPTIVE_20261028.md) records the known
failures and the retained control. Pricing and LP economics remain unvalidated.

## Matched experiment

The archive is `.local/adaptive-corridor/20261028-frozen-market-v2/`. The first
attempt, `...-v1`, stopped before selection on a logging variable collision.
Its partial artifacts and failure note remain intact. The corrected run adds a
replay smoke test and uses a new output directory. No failed-run outcome selected
a different model, feature, threshold or update rule.

Both feature families train on exactly the same clean frozen reference paths
with fresh market context. Timing uses the preceding thirteen inputs. Market
adds seven inputs: signed and absolute transformed mark/oracle gap, gap change
over thirty seconds, signed and absolute mark movement, and two interactions
with idle age and empty-bin share. These are pre-entry context only. The oracle
still defines entry and barrier outcomes. There is no mark-price substitution.

The last context receipt must be strictly before entry and no older than eight
seconds. The thirty-second-lag receipt uses the same freshness and strict-before
rules. Missing/stale context falls back to retained open pricing for **both**
families. Training and live-reference support do not depend on admission.
January and August frozen raw paths all have fresh context. Later raw context
is rebuilt from the retained full September/October files. Oracle and mark
crosschecks find zero mismatches across 111,795 shared normalized timestamps.

The hurdle logistic model and ten positive conditional quantiles retain the
preceding fit, clipping, sorting, integer barriers and 1–50,000 ppm width bounds.
Only path weighting is used. Each family has static/open, reference-feedback
open, priceability-feedback open, static gate53, priceability gate53 and
priceability gate65, plus retained open: thirteen variants.

Every online method updates the floor logit from every supported clean reference
after expiry plus thirty seconds. Reference feedback also updates the desired
CDF level from every reference. **Priceability feedback updates that level only
when the probability saved at quote time is below 0.48.** The choice uses no
current outcome and is independent of a gate's refusal. Bounds, anti-windup,
gains and four-hour stale resets remain unchanged. This prevents an infeasible
minimum-width forecast from driving the coverage level upward after a loss.
It supplies no conditional calibration guarantee.

## Earlier chronological selection

The same 14/17/20-date folds, frozen-phase charges, full-reference loss guards
and provisional 85% overall / 50% populated-frozen availability screens apply.
The final fit uses twenty-two dates ending before September. Choice and model
files are pinned before the later replay. September and October are already
inspected development data, not a fresh holdout.

| Variant | Score, lower is better | Availability screens |
| --- | ---: | --- |
| Market, priceability feedback, open | **12.547** | Pass |
| Timing, priceability feedback, open | 12.558 | Pass |
| Retained open | 13.389 | Pass |
| Timing, reference feedback, open | 13.892 | Pass |
| Market, reference feedback, open | 14.008 | Pass |
| Timing, static open | 15.553 | Pass |
| Market, static open | 17.010 | Pass |

All six gates fail the availability screens. The market priceability candidate
improves the retained aggregate score in all three selection folds:
13.127→12.724, 11.653→10.734 and 15.388→14.183. The 0.012 score advantage over
timing priceability is too small to establish a material market-context gain.
Neither the score nor availability feasibility means the calibration goal passes.

## Calibration remains inconsistent

These are full raw-date frozen paths, with private eight-hour restart state:

| Date | Paths | Retained open | Timing priceability open | Market priceability open |
| --- | ---: | ---: | ---: | ---: |
| January 2026 | 1,004 | 56.77% | 57.87% | 57.77% |
| August 2026 | 894 | 62.08% | 60.85% | 60.85% |
| September 2026 | 49 | 34.69% | 32.65% | 30.61% |
| October 2026 | 49 | 48.98% | 40.82% | 38.78% |

All open variants retain 100% of the common eligible references. On the 1,898
January/August frozen selection paths, retained survival is 59.27% and market
priceability survival is 59.22%. On the 98 later frozen paths, it worsens from
41.84% to 34.69%. Small later groups, repeated modes and source formats are not
independent evidence. Pooled full-state later survival remains close to 48%
because frozen entries are rare; that does not establish conditional calibration.

August's 08:00 restart case remains particularly clear. The minimum-width floor
is 241/390 = **61.79%**, already above the reference band. Retained quotes survive
249/390 = 63.85%; the open challenger survives 251/390 = 64.36%. The market
gate53 keeps only 135/390 = 34.62% and still survives 80/135 = 59.26%. Gate65
keeps 233/390 = 59.74%, survives 60.94%, and has an offered minimum-width floor
of 56.65%. Width changes cannot calibrate those unchanged offered populations.

## Verification and capture handoff

`audit_frozen_market.py` refits eight models exactly, recomputes selection and
898,560 predictions, and checks 840,480 control/non-frozen/fallback records
against the preceding archive. It rebuilds later context, verifies shared
training support and exact timing-fit parity, and tests own/future-label
exclusion, label maturity and refusal-independent learning on actual panels.
The audit binds the completed research JSON by hash.

The full suite passes **331 tests, with three existing optional skips**. New
tests cover matched support, market-signal recovery, priceability feedback,
fallback, chronological isolation, replay logging, native paired paths, causal
entry health, frozen models/sources, restart isolation, early-horizon rejection,
policy mutation and collection-quality failure after a long outage. A source
snapshot path typo found during these tests was corrected before freezing.

The native adapter also replays the retained 26 October recording after native
hash-chain verification: 960 grid windows, 836 healthy entries, 825 healthy
outcomes and 759 entries with clean feature history. This is a development
integration check, not new prospective evidence. Its evidence is retained at
`.local/capture-readiness/20261028-adaptive-analysis-v1/`.

The new freezer and analyzer snapshot the selected model, retained and timing
controls, source, runtime versions, health rules and evaluation plan. The recorder
is rebuilt and matches the previously successful live-preflight binary exactly.
The subsequent [eight-hour trial](PROSPECTIVE_ADAPTIVE_20261028.md) must be judged
after its original horizon; there is no refit or candidate reselection during
collection. A completed reliable recording can still reject this challenger.

```sh
OPENBLAS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 OMP_NUM_THREADS=1 \
  python3 -B scripts/research_frozen_market.py \
  --previous .local/adaptive-corridor/20261028-frozen-cdf-v1 \
  --output /absolute/path/to/new-market-study
OPENBLAS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 OMP_NUM_THREADS=1 \
  python3 -B scripts/audit_frozen_market.py \
  --output /absolute/path/to/new-market-study
```
