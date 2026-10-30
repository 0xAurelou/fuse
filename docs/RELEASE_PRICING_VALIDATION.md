# Full-menu release pricing rejection controls

30 October 2026 (WITA). **Production pricing is not validated.** The existing
unfitted Brownian assumptions fail this historical test at every asset, payout
and tested edge setting. Increasing the configured edge from 5% to 7–10% does
not reconcile the model with these observed oracle paths.

A subsequent [fitted empirical challenger](RELEASE_EMPIRICAL_PRICING.md) now
uses the same dated paths with strictly earlier matured references. At each
edge, all seventeen pairs receiving quotes also lose LP gross under the
LP-favorable censoring bound; ten pairs receive no quotes. Fitting this model
does not resolve the release blocker or create new validation data. The
original Brownian rejection packet below remains unchanged.

The packet is `.local/release-pricing/20261030-rejection-v1/`. Its declaration
fixes the grid, inputs, strategies, source hashes and native binary before this
grid is replayed. The underlying development dates and earlier outcomes had
already been inspected; this is neither a new independent holdout nor a fresh
prospective trial. No running capture, deployed contract, live quote policy,
market balance or frontend promise was changed.

## Complete scope and denominators

The input rule selects every retained **complete raw UTC BTC day** that also
has complete ETH/HYPE monthly raw coverage and provider-declared availability
for both assets. Incomplete and pre-coverage dates remain in the declaration's
exclusion log. Prices do not choose the dates. The resulting dates are:

2025-01-01, 2025-02-01, 2025-03-01, 2025-04-01, 2025-05-01, 2025-06-01,
2026-01-01, 2026-08-01, 2026-09-01 and 2026-10-01, all UTC. These include
weekdays, Saturdays and a Sunday; they do not represent continuous market
history between sample dates. All three assets share these dates and grid
timestamps, permitting actual contemporaneous cross-asset comparisons.

| Axis | Fixed values |
| --- | --- |
| Asset | BTC, ETH, HYPE |
| Total payout, including stake | 2, 5, 10, 25, 50, 100, 250, 1,000, 10,000× |
| Configured target edge | 500-bps control; 700, 850 and 1,000 bps |
| Duration | 30 seconds; the only current supported duration |
| Quote-to-acceptance delay | 0, 250, 1,000, 1,999, 2,000 ms |
| Fixed 30-second volatility assumption | BTC 1,000 ppm; ETH 1,500 ppm; HYPE 3,000 ppm |
| Public entry rules | All offered; prior-30-second flat/moving/100-ppm jump; mark-gap buckets; last mature outcome survived/failed |
| Illustrative expense rates | 0, 10, 50, 100 bps per accepted ticket, including unresolved tickets |
| Concurrent portfolios | One account per asset; exact three-account-per-asset scaling on the same paths |

There are **86,400 distinct asset/grid opportunities**, **432,000 delay-specific
path envelopes**, **43,200 daily strategy cases** and **1,800 daily joint-asset
cases**. The latter numbers repeatedly evaluate the same observations. They
are not additional market samples or independent trials.

The offline Go `fuse-research` bridge exports the actual integer formula for
all **108 asset/payout/edge combinations**. The Python replay matches every
exported width exactly; the previous 90 native golden vectors remain covered
by existing tests. The new bridge operation is read-only, paper-policy-only
and does not initialize or mutate trading balances. It does not make the
separate adaptive pricing candidate compatible with the native quote engine.

## Entry, timing and outcomes

Raw observations retain actual provider receipt times and `oraclePx`. Never
substitute `markPx`, duplicate a feed to create a second receiver, interpolate
an overnight path or delete a future outage from the entry denominator.

Only observations strictly before an action enter that action's state; a
receipt with the same millisecond is ordered after the action. Quote and
acceptance must be fresh within eight seconds. Any intervening price change
invalidates a delayed quote, including a change followed by a return to the
original price. Same-price refreshes do not increment this sequence analogue.
Acceptance at exactly two seconds is rejected, matching the strict TTL bound.
These rules are a **single-stream analogue**, not native dual-receiver health
or a verified operator acceptance journal.

Use the accepted quote's unchanged, integer-quantized barriers. Evaluate the
full thirty seconds starting at acceptance. Touching either barrier loses.
Any later excessive gap, conservatively bounded transport disconnect or lack
of archive coverage censors the entire outcome, even if some observed breach
exists. This deliberately conservative path test is not the native engine's
pending/void adjudication. Censored tickets remain placed tickets, with refund
arithmetic and independent all-survive/all-fail cash bounds shown separately.

Entry signals use only prior observations. Future path jumps are reported as
descriptive strata, never used to choose an entry. Mark-gap buckets use the
floor-rounded integer ppm gap and split it at 100 ppm (nominally one bp).
Public outcome-history rules assume access to all hypothetical accepted quote
results thirty seconds after expiry, irrespective of whether the strategy
itself entered. They reset between separately sampled dates, not within a day.
This is a disclosed hypothetical information surface, not observed user
behavior or proof of the best informed strategy.

## Rejection result

**All 108 immediate all-offered controls have negative LP gross arithmetic
even when every censored ticket loses for the trader.** The same result holds
for all 108 controls at each of 250, 1,000 and 1,999 ms. At 2,000 ms every
otherwise available quote is rejected, so that boundary supplies no price
performance evidence.

At the most conservative tested 10% configured target edge, observed trader
survival on clean hypothetical immediate tickets is:

| Payout | Target survival | BTC observed | ETH observed | HYPE observed |
| --- | ---: | ---: | ---: | ---: |
| 2× | 45% | 98.7390% | 98.7495% | 97.2552% |
| 5× | 18% | 96.5654% | 96.6351% | 94.2701% |
| 10× | 9% | 94.6078% | 94.7401% | 92.2394% |
| 25× | 3.6% | 91.8699% | 92.1172% | 89.8812% |
| 50× | 1.8% | 90.0446% | 90.1212% | 88.1048% |
| 100× | 0.9% | 88.3238% | 88.2228% | 86.4189% |
| 250× | 0.36% | 86.2721% | 85.9099% | 84.4265% |
| 1,000× | 0.09% | 83.2103% | 82.5589% | 81.6608% |
| 10,000× | 0.009% | 79.0407% | 77.2955% | 77.3277% |

For every immediate 10%-edge payout, BTC has 28,771 hypothetical accepted
tickets, 28,708 resolved and 63 censored; ETH has 28,770/28,708/62; HYPE has
28,772/28,709/63. The common survival denominators are retained in the packet.
These rates reject the tested unfitted assumptions on these paths. They do
not estimate future margins or validate a replacement volatility/CDF model.

Public selection is not required to beat these controls. For illustration,
the fixed `prior30_flat` rule on immediate 2×/10%-target quotes produces:

| Asset | Hypothetical accepted | Clean resolved | Trader wins | Player gross with censored refunds, one-USDC stakes |
| --- | ---: | ---: | ---: | ---: |
| BTC | 3,441 | 3,427 | 3,427 | +$3,427 |
| ETH | 1,391 | 1,385 | 1,384 | +$1,383 |
| HYPE | 302 | 300 | 299 | +$298 |

All eight rules remain reported at every configuration. This illustration
does not select a winning rule for a new holdout, measure voluntary demand,
or establish a forward statistical guarantee. The hypothetical gross arithmetic
has no bankroll/admission limits, replenishment, daily fees, rewards, hedging
costs or withdrawal flows. In particular, large negative unit PnL in a high
payout row is **not an observed or simulated funded-bankroll loss**.

## Latency and dependence evidence

The BTC all-offered quote-availability denominator is 28,771 across the ten
days, independent of edge/payout. Immediate entry takes all of those tickets.
At 250 ms the single-stream sequence/freshness rules take 28,032 and reject
739; at 1,000 ms they take 25,619 and reject 3,152; at 1,999 ms they take 21,800
and reject 6,971; at 2,000 ms they take none. Refusals are not silently removed
from the availability denominator. The replay contains corresponding ETH/HYPE
rows and natural quote-age/gap/jump strata for every formula configuration.

`joint.jsonl` preserves actual simultaneous three-asset win-count patterns and
pairwise resolved counts. Missing/rejected/censored legs stay visible. The
three-wallet version multiplies exposure and cash on the same paths; it does
not create three independent outcomes. These are liability diagnostics, not
an LP solvency or optimal hedge model.

## Verification, reproduction and remaining gate

The separate software auditor reconstructs the saved envelopes from the raw
observations without calling the replay's envelope function. It independently
replays label maturity, public selection, every case's integer cash and
censoring bounds, the daily-to-pooled summaries and simultaneous portfolios.
It re-exports all native formula vectors and checks source/artifact hashes.
Its `audit.json` reports the actual coverage and explicitly disclaims an
independent external review or production approval.

Twenty focused pricing/auditor tests cover price-sequence round trips, stale
prices, strict action ordering, TTL and expiry boundaries, barrier rounding
and touches, future disconnect leakage, outcome-label maturity, empty cases,
high-payout censoring arithmetic, dependence counts and evidence tampering.
Including the release attachment check and preceding accounting work, all
66 focused release checks pass. The full Python suite passed 629 tests with
no skips using the retained integration fixtures and current research binary;
all Go packages passed their default suite.

Run from the repository root, with the retained raw archives present:

```sh
cd engine
GOCACHE=/private/tmp/fuse-release-go-cache go build -o /private/tmp/fuse-release-pricing-research ./cmd/fuse-research
cd ..
FUSE_RELEASE_PRICING_BINARY=/private/tmp/fuse-release-pricing-research python3 -B -m unittest discover -s scripts -p 'test_release_pricing*.py'
python3 -B scripts/research_release_pricing.py --declare --binary /private/tmp/fuse-release-pricing-research --output .local/release-pricing/YOUR-NEW-PACKET
python3 -B scripts/research_release_pricing.py --output .local/release-pricing/YOUR-NEW-PACKET
python3 -B scripts/audit_release_pricing.py --research .local/release-pricing/YOUR-NEW-PACKET
python3 -B scripts/release_evidence.py --output .local/release-readiness/YOUR-NEW-PACKET --release-pricing-packet .local/release-pricing/YOUR-NEW-PACKET
```

Choose new directories: declaration, run and audit refuse to overwrite prior
or interrupted evidence. The runner reads retained data only and performs no
network requests. Protocols/manifests bind the original provider URLs, every
selected raw slice and excluded calendar coverage. Archive contents are not
bundled into a clean Git checkout; reproducibility requires those retained
files or matching verified downloads.

Release gate 2 remains open. A production candidate needs a genuinely calibrated
model for the full intended payout surface, an exact reviewed native quote
interface, causal informed-player/latency tests through actual acceptance and
bankroll constraints, and fresh frozen-policy evidence across independent
market episodes. Natural historical staleness and fixed latency what-ifs do
not substitute for outage, competing-feed and transaction-recovery drills.
The existing separate adaptive research also remains unvalidated and cannot
inherit these Brownian-control results.
