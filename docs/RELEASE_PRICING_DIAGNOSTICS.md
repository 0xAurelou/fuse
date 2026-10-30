# Why the fitted release challenger fails

30 October 2026 (WITA). **Production pricing remains unvalidated.** This
post-result diagnostic attributes errors in the already rejected
[empirical challenger](RELEASE_EMPIRICAL_PRICING.md). It neither fits a new
model nor selects a launch subset, threshold or live policy. All ten release
gates remain open.

## Findings across the full menu

The retained packet is
`.local/release-pricing/20261030-empirical-diagnostics-v1/`. It evaluates all
three assets, nine payouts, four edge settings and five acceptance delays on
the same ten dates. All **15,552,000 delayed forecast evaluations** are retained
in **27,000 daily cases**, including the all-path cohort and its complete
flat/moving/jump/missing-history pre-entry partition. These repeatedly evaluate
the parent's **86,400 distinct asset/grid observations**.

Among the 108 immediate asset/payout/edge configurations:

| Diagnostic | Configurations |
| --- | ---: |
| Receives quotes | 68 |
| Receives no quotes | 40 |
| Realized wins exceed the selected historical survivor fractions | 68 of 68 quoted |
| Flat paths alone make LP gross negative under the most favorable censoring bound | 16 of 68 quoted |
| Still loses after perfect hindsight removal of all flat paths, under the most favorable censoring bound | 40 of 68 quoted |

The last two groups overlap. They are separate necessary diagnostic bounds,
not an allocation of all losses into mutually exclusive causes. All 68 quoted
configurations already have negative LP gross under the parent's favorable
censoring bound. Empty configurations have no calibration estimate.

The newest matured training label used for an offer was **29.001–243.129 days
old** at quote time. This is training-data age, not oracle receipt age. Quotes
and price receipts can satisfy their short validity checks while the model's
reference distribution contains no recent regime evidence. The diagnostic
does not identify age as the cause of a particular error or choose an approved
maximum training age.

For example, immediate ETH 2×/850-bps quotes have 1,285 flat-path wins and
10,301 positive-motion wins. Even after removing every realized flat path,
the retained moving cohort loses at least **$1,806** on one-USDC tickets,
granting player losses on all unknown outcomes. HYPE 2× has only 204 flat wins
against 11,298 positive-motion wins; the same favorable calculation still
loses **$2,718**. A flat-risk gate alone cannot repair those unchanged corridors.

## Exact meaning of the bounds

For `R` clean resolved tickets, `C` censored accepted tickets, `Z` zero-motion
wins, `V` positive-motion wins and total payout multiplier `M`, in one-USDC
ticket units:

```text
LP gross with censored refunds = R - M * (Z + V)
LP upper if only flat paths win = R + C - M * Z
LP upper after hindsight flat removal = R - Z + C - M * V
```

The bounds grant every censored ticket a player loss and give the model every
other favorable classification allowed by the stated comparison. A negative
upper bound rejects that comparison even under these concessions. A positive
bound does not produce a causal filter, a profitable model or a future
probability estimate. Realized zero motion is an outcome label, unavailable
when accepting a bet. These calculations retain the original offered widths;
they do not counterfactually reprice the remaining cohort.

Historical expected wins sum the model's actual selected survivor fraction
at each resolved accepted quote. The artifacts retain exact rational sums,
the nominal target sums and observed-minus-historical differences. Repeated
historical windows are dependent. Neither these fractions nor their sums are
confidence guarantees for current conditional risk.

Touching the exact integer barrier is a loss. The diagnostic separates touches
from larger excursions, flat wins from positive-motion wins, and censored
tickets from all resolved labels. Delayed acceptance refusals remain refused;
the exact two-second boundary supplies no accepted-ticket performance evidence.

## Verification and reproduction

The declaration binds the software-audited parent, its original forecast/case
files, the audited path envelopes, Python runtime, diagnostic source/tests and
the imported parent source closure. The runner reconciles every all-path daily
and pooled count/cash result to the parent's audited results.

A separate bookkeeping checker verifies every configuration, daily activity
partition, pooled integer/rational sum, label-age range, payout and censoring
bound. It does not independently rebuild the diagnostic's zero-motion labels
from raw receipts; the parent retains its full path/forecast software audit.
This work is not independent external pricing review.

Eight diagnostic tests and six checker/report tests pass. They cover exact
cash decomposition, censored placement, strict touch loss, empty cohorts,
future training labels, source/input mutation, complete menu coverage,
missing/duplicate cases, exact rational aggregation and attempted promotion of
the diagnostic into a probability claim. Source snapshots, checks and a
complete artifact manifest remain in the packet.

From the repository root, using a fresh output directory and the original
retained parent/raw paths:

```sh
PYTHONPATH=scripts python3 -B -m unittest test_release_empirical_diagnostics test_release_empirical_diagnostic_report
python3 -B scripts/diagnose_release_empirical.py --declare --parent .local/release-pricing/20261030-empirical-challenger-v2 --output .local/release-pricing/diagnostic-reproduction
python3 -B scripts/diagnose_release_empirical.py --output .local/release-pricing/diagnostic-reproduction
python3 -B scripts/report_release_empirical_diagnostics.py --output .local/release-pricing/diagnostic-reproduction
```

## Requirements for the replacement

A replacement must address positive-motion tails as well as minimum-width
flat risk. Its training/reference age and update policy need validation against
the intended regimes; a recent file publication date cannot substitute for
recent labels or demonstrated transfer. Use consecutive matched observations
across all three assets, with earlier training and separate frozen evaluation
periods. Rare-tail support, quote availability, informed-player selection,
latency and correlated funded exposure remain requirements for every supported
payout. These diagnostics cannot justify silently dropping difficult products.

The native integration also needs explicit per-asset/per-payout availability.
The current PPB table route requires a common configured payout set and a
positive width for every pair. It cannot directly represent the challenger's
asymmetric BTC/ETH/HYPE refusals while retaining the complete product menu.
Fabricating an offered width or removing a payout globally would misrepresent
that model. A future provider must carry refusal reasons and support metadata
through quote admission and the interface, while preserving existing accepted
barriers and settlement obligations. No such provider is installed by this study.
