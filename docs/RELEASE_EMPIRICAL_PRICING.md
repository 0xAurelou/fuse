# Fitted release pricing challenger

30 October 2026 (WITA). **Production pricing is not validated.** This is a
retrospective fitted challenger to the [rejected Brownian controls](RELEASE_PRICING_VALIDATION.md).
It uses their same ten previously inspected, nonconsecutive UTC dates and
audited single-stream raw price paths. It introduces no independent market
sample, live quote provider, deployment or change to the enabled product menu.
All ten release gates remain open.

## Rejection result

At each 500/700/850/1,000-bps target edge, seventeen of the 27 asset/payout
pairs receive quotes. **All seventeen lose LP gross even if every censored
ticket loses for the player.** Ten pairs receive no quotes at all. Across the
four target edges this is 68 losing immediate configurations and 40 unavailable
configurations. All 108 remain unvalidated. The same rejection
holds at 250, 1,000 and 1,999 ms. At 2,000 ms there are no accepted tickets.

For the predeclared 850-bps midpoint, immediate one-USDC hypothetical tickets
produce the following counts and LP gross assuming censored refunds, before
fees, rewards and expenses:

| Total payout | BTC accepted / LP gross ($) | ETH accepted / LP gross ($) | HYPE accepted / LP gross ($) |
| ---: | ---: | ---: | ---: |
| 2× | 20,081 / -724 | 20,081 / -3,146 | 20,082 / -2,977 |
| 5× | 16,855 / -2,650 | 19,701 / -7,691 | 20,082 / -5,458 |
| 10× | 11,829 / -2,305 | 15,971 / -11,924 | 20,040 / -5,325 |
| 25× | 4,520 / -1,088 | 14,307 / -11,596 | 19,136 / -8,215 |
| 50× | Unavailable | 9,296 / -24,067 | 17,538 / -8,107 |
| 100× | Unavailable | 6,955 / -1,051 | 15,756 / -11,381 |
| 250× | Unavailable | Unavailable | 11,735 / -10,548 |
| 1,000× | Unavailable | Unavailable | Unavailable |
| 10,000× | Unavailable | Unavailable | Unavailable |

The nominal oracle-available denominator remains 28,771 BTC, 28,770 ETH and
28,772 HYPE grid points across the ten dates. Warm-up, missing context, insufficient
tail ranks, integer-width constraints and insufficient actual historical
survivors are reported separately. These denominators must not be replaced
with only the entries at which the challenger chose to offer a price.

Public selection is not necessary to reject this model. The fixed
`prior30_flat` rule also produces player gross of +$813 BTC, +$594 ETH and
+$73 HYPE on immediate 2×/850-bps tickets with censored refunds. Its respective
accepted/resolved/win/censored counts are 2,858/2,845/1,829/13,
1,294/1,288/941/6 and 205/203/138/2. Some other rules lose for the player;
all eight rules remain in the artifacts. These dependent historical outcomes
do not establish a persistent live exploit or future dollar margin.

This candidate is rejected for release use. It neither solves empirical
regime drift on the offered pairs nor supplies evidence for the unquoted tails.
The result does not justify promoting a favorable subset, changing the release
menu silently or treating a target-edge label as a measured margin.

The [error-attribution diagnostic](RELEASE_PRICING_DIAGNOSTICS.md) further
shows that 40 of the 68 quoted configurations still lose after granting
perfect hindsight removal of flat paths. The newest training labels used for
offers are 29–243 days old. A flat-risk gate alone cannot resolve this failure;
positive-motion calibration and reference-age policy remain requirements.

## Fixed scope and causal fitting

The declaration retains BTC, ETH and HYPE; every 2/5/10/25/50/100/250/1,000/10,000×
total payout; 500/700/850/1,000-bps target edges; the supported 30-second duration;
0/250/1,000/1,999/2,000-ms acceptance delays; and all eight public entry rules.
The exact two-second expiry remains a rejection boundary, not a successful
pricing observation. Illustrative expenses remain 0/10/50/100 bps per accepted
ticket. Cross-asset portfolios retain contemporaneous paths and one- or
three-account-per-asset arithmetic. These are repeated evaluations, not
independent samples or a funded capital model.

At each UTC day start, the model freezes only references that matured strictly
before that cutoff. References use accepted, uncensored immediate-entry paths
with known pre-entry activity, including paths that earlier versions of the
challenger would have refused. Learning is not conditional on winning trades
or a strategy's chosen entries. A label matures thirty seconds after expiry.
No current-day outcome updates that day's frozen distribution.

The grouping hierarchy is exact pre-entry activity/mark-gap/quote-age, then
activity, then the asset's global references. Each group needs at least 200
references across three earlier sampled dates. All payouts share the first
eligible distribution; an unsupported tail cannot silently switch to a
different population. The first three sampled dates supply warm-up references.
The dates between these samples are unobserved.

For entry price `P` and maximum observed absolute excursion `X`, both in native
integer price units, a reference's minimum surviving width is:

```text
threshold_ppb = ceil((X + 1) * 1_000_000_000 / P)
allowed_rank = floor(N * (10_000 - target_edge_bps) / (10_000 * total_payout))
```

The offered integer width is below the first disallowed order statistic,
capped at 50,000,000 ppb. Touching a barrier loses. Higher offered payouts must
have strictly narrower ppb widths **and** strictly smaller integer price
deltas. Widths that round to zero, exceed native arithmetic bounds or leave
fewer than twenty actual surviving references are refused. At least twenty
allowed reference ranks are also required before choosing a width.

These are empirical support rules, not confidence bounds. Dependent windows,
regime changes, grouped fallback and order-statistic ties can make the observed
future margin very different from the requested edge. Twenty observed tail
events do not establish safety for rare high payouts. Refusal does not validate
the product or authorize removing it from the release requirement.

The same quote-time corridor is evaluated at each declared acceptance delay.
Public-history signals use only actually accepted hypothetical outcomes after
their delayed expiry plus thirty seconds, whether or not that particular
strategy entered. This disclosed information surface is not observed player
demand. Future outages retain accepted tickets in the censoring denominator;
refund, all-win and all-loss cash bounds remain separate.

## Evidence and verification

The original `.local/release-pricing/20261030-empirical-challenger-v1/` reached
all scheduled forecast and strategy cases, then terminated before native
quantization because `copyfile` had removed the executable bit from the sealed
Go bridge. It produced no completed result or audit and is preserved. The v2
declaration changes packaging to preserve execution permission and verifies
it before replay. The fitted economic rule and inputs are unchanged.

The replacement packet is
`.local/release-pricing/20261030-empirical-challenger-v2/`. Its frozen protocol
binds the model, runner, independent checker, tests, transitive Python helpers,
all native engine/research-command Go sources, binary, policy, Python runtime
and audited baseline artifacts. The model and complete quote forecast traces
record daily model identifiers, reference support, maturity cutoffs, widths,
integer deltas and every refusal reason.

The completed software check reconstructs all **3,110,400 asset/payout/edge
forecasts**, **43,200 daily strategy cases**, **1,800 joint cases** and
**616,398 distinct native quantization vectors**. These reuse **86,400 distinct
asset/grid opportunities**. The declaration SHA-256 is
`9d00c4624fb54282b86f6ea2efbf418e8486c1c0f5fdf2f218e253572ac24138`;
the result SHA-256 is
`f46d7702a855449f39b225ea7f845ca79854ee227e5a6dbb2c2d9b911925b057`.

`scripts/audit_release_empirical.py` independently reconstructs reference
thresholds, ranks, fit groups, causal cutoffs, public histories, cash arithmetic,
censoring, pooled summaries and joint cases. It does not call the challenger's
fit, surface or replay functions. It reexecutes every distinct offered
price/width/delta through the Go engine's actual `MulDiv` arithmetic. This checks
integer quantization; it does not establish dual-receiver health, native
acceptance or live settlement. The checker's raw envelopes come from the
separately audited baseline, rather than another new market capture.

The release evidence builder requires a complete hash-bound software audit,
the full case grid, all artifacts and explicit false production/holdout/native
admission flags before attaching this packet. Software cross-checks are not an
independent external pricing review.

## Reproduction

The retained raw baseline catalogs, artifacts and original native executable
must remain accessible at their recorded paths. Use a fresh output directory;
completed and interrupted packets are never overwritten. From `engine/`:

```sh
GOCACHE=/private/tmp/fuse-release-go-cache go build -o /private/tmp/fuse-release-empirical-reproduction ./cmd/fuse-research
```

From the repository root:

```sh
python3 -B -m unittest discover -s scripts -p test_release_empirical.py
python3 -B scripts/research_release_empirical.py --declare --baseline .local/release-pricing/20261030-rejection-v1 --binary /private/tmp/fuse-release-empirical-reproduction --output .local/release-pricing/empirical-reproduction
python3 -B scripts/research_release_empirical.py --output .local/release-pricing/empirical-reproduction
python3 -B scripts/audit_release_empirical.py --output .local/release-pricing/empirical-reproduction
```

The deployment boundary is unchanged: a fitted offline replay cannot satisfy
the release gate without full supported-market availability, adversarial
execution evidence, a live native provider, stress-calibrated funded limits,
fresh frozen holdout results and independent pricing review.
