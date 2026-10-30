# Full raw-oracle pipeline refit — 28 October 2026

The subsequent [later chronological comparison](TEMPORAL_PRICING_RESEARCH.md)
extends training/scoring through the later 2026 regimes and adds two newly
downloaded full raw days. It confirms the availability cost of the tested guards
and exposes weaker frozen-state transfer after expanding training.

The comparison now refits the main activity engine, frozen hurdle overlay and
bursty priors on retained raw oracle dates, rather than changing only bursty
pricing. It also scores frozen calibration and quote availability explicitly.
The extra raw training support does **not** repair the difficult regime. August
08:00 still offers only **32/389 frozen-state paths (8.23%)**, with **84.38%
survival** on those quotes. Removing pauses restores availability but leaves
frozen survival at **64.01%**. No candidate is promoted or frozen for capture,
and no new capture starts.

The complete run took **264.41 seconds**. Source snapshots, fitted models,
selection, per-entry predictions, exact finite-path bounds and comparisons are
retained in `.local/adaptive-corridor/20261028-full-raw-pipeline-v2/`.

## What changed

Three stages are crossed with the existing frozen-floor admission rule, the
warm12/floor30 rule, and a no-pause control, giving nine variants:

| Stage | Core engine | Frozen overlay and bursty priors |
| --- | --- | --- |
| Retained | Previously pinned | Previously pinned |
| Raw overlay | Previously pinned | Refit on preceding raw replacements |
| Raw core | Refit on preceding raw replacements | Refit using that core |

The formulas, integer barriers, one-ppm minimum, 50,000-ppm maximum and delayed
online update rules remain unchanged. Every permitted training date appears
once. A complete raw day replaces its normalized version when available;
otherwise the normalized day remains. Training excludes the scoring date and
later dates, and every training label must mature before the cutoff.

Final raw-core frozen training support rises **788 → 2,079 paths**, across the
same fourteen-date calendar universe with eight complete raw replacements.
The period-balanced training minimum-width survival estimate rises **18.38% →
22.55%**. Raw-overlay training also uses all 2,079 clean frozen references. More
paths within existing dates are not more independent dates or new prospective
evidence.

The new wrapper explicitly restores clean shadow labels before fitting the
all-reference frozen hurdle prior. The underlying fitter filters
`survived != None`, which otherwise can exclude refused training paths even
though this overlay's online rule learns from all references. The incomplete v1
run was interrupted before later diagnostics after this data-flow concern was
found; its snapshots and `abandoned.json` remain intact. A direct check showed
that no paths had actually been excluded in the three earlier prefixes, and
their fitted models are identical after the correction. This correction is not
claimed as the cause of the earlier calibration failures. The completed v2
audit verifies the full reference population in all new fits.

## Broader earlier selection

Selection retains the original 6/9/12-date prefixes and the same subsequent
3/3/2 scoring dates. Complete raw May and June 2025 scoring days replace their
normalized versions; the other scoring dates remain normalized. Raw restarts
retain pre-entry history features but start with private calibration state;
continuous runs do not reset at eight-hour scoring boundaries.

The new objective averages mean/worst errors for overall, frozen, active,
sparse, bursty, pump and dump groups, adds the existing phase error, charges
lost overall/frozen availability and applies full-reference loss guards.
Populated groups that lose enough quotes to fall below twenty are charged;
they cannot disappear from assessment. Provisional feasibility screens require
at least **85% overall availability** and **50% frozen-state availability** in
each relevant earlier case. These are research screens, not approved production
limits. The changed population and objective make these scores incomparable
with preceding normalized-only scores.

| Variant with existing admission | New earlier score | Fold scores |
| --- | ---: | --- |
| Raw overlay | **14.405** | 10.820 / 22.416 / 9.977 |
| Retained | 14.421 | 10.870 / 22.416 / 9.977 |
| Raw core | 14.576 | 11.674 / 22.200 / 9.854 |

No-pause variants tie their corresponding existing-admission controls because
those controls refuse no quotes in the earlier scoring cases. Every selected
earlier case therefore has 100% eligible availability. Warm12/floor30 variants
score 47.155–47.272 and fail the availability screens. The selected raw overlay's
small improvement comes from one fold; this does not establish transfer to the
later high-flatness conditions. Selection and all inner/outer models are pinned
and hashed before later replay.

## Later calibration and consistency

The following frozen-state passes require at least twenty offered paths and
survival in 43–53%. Denominators retain **all cases with at least twenty eligible
reference paths**, including cases where refusals leave fewer than twenty
quotes. Consequently some denominators differ from earlier descriptive tables
that counted only sufficiently populated offered groups. Panels and modes
overlap and are not independent confirmations.

| Frozen panel | Retained restart / continuous | Selected raw overlay | Raw core | Raw core + warm12/floor30 |
| --- | --- | --- | --- | --- |
| Original raw | 4/10 · 1/6 | 4/10 · 1/6 | 5/10 · 1/6 | 8/10 · 3/6 |
| Canonical full raw | 6/6 · 4/6 | 5/6 · 4/6 | 6/6 · 4/6 | 4/6 · 2/6 |
| Later normalized test | 0/4 · 0/4 | 0/4 · 0/4 | 0/4 · 0/4 | 0/4 · 0/4 |

Every stage has exactly the same admission counts under each matching policy.
With existing admission, original raw overall availability remains **89.48%
restart / 80.43% continuous**; frozen availability is **58.58% / 42.94%**.
Aggregate availability therefore conceals much worse availability in particular
frozen intervals.

Raw-core original raw restart overall/non-frozen passes remain 10/10 and
bursty passes remain 4/8. Canonical raw restart bursty passes deteriorate 5/5 →
3/5. The January startup/later counts and June later **8/22** are unchanged
throughout these refits. Later normalized pump passes remain 2/9; dump passes
are 4/10 restart and 5/10 continuous, versus 4/10 in both retained modes.
Refitting the core does not establish cross-regime calibration.

## August exposes the admission problem

These are the same raw 08:00–16:00 paths, with 901 eligible outcomes, including
389 frozen and 512 non-frozen paths:

| Raw-core admission | Overall quoted / eligible | Overall survival | Frozen quoted / eligible | Frozen survival | Frozen minimum-width survival on offered paths |
| --- | ---: | ---: | ---: | ---: | ---: |
| Existing floor | 544/901 | 49.26% | 32/389 | 84.38% | 78.12% |
| Warm12/floor30 | 593/901 | 48.90% | 81/389 | 60.49% | 59.26% |
| No pause | 901/901 | 54.38% | 389/389 | 64.01% | 61.95% |

Near-target overall survival with the first two policies is not useful
conditional calibration: most frozen-state quotes are refused and those still
offered miss badly. The no-pause control shows that restoring availability alone
does not solve pricing.

The exact minimum-width bound makes the limitation concrete. Of the currently
offered 32 frozen paths, **25 survive every allowed positive width**. Even with
perfect hindsight, at least **18 additional refusals** would be needed to put
that finite offered subset into 43–53%; no width formula can repair it while
keeping all those quotes.

Across all 389 eligible frozen paths, 241 survive minimum width. An optimistic
hindsight selector would need at least **75 refusals**, permitting at most
**314/389 = 80.72% retention** in the reference band. This grants perfect refusal
selection and arbitrary widths for all other paths, ignoring the upper width
cap. It is an optimistic finite-path bound, not a forecast, an implementable
admission policy, or a promise that 80% retention is achievable causally. The
current 8.23% retention is far below that optimistic bound and still selects a
poorly calibrated subset.

## Verification and next action

The audit recomputes selection and all inner models exactly; verifies twenty
archived new-model prior populations, 279,080 feature records and 936,720 prediction
records; and independently recomputes 9,360 finite-path bounds. Actual
January/June counterfactuals verify exclusion of own/future training labels and
the sixty-second entry-to-label maturity delay for every new stage/policy.
Eligibility denominators remain fixed, and saved widths are identical across
admission policies within each stage.

Five new tests cover exact integer refusal bounds against exhaustive small
subsets, future-date exclusion, private retained models, inclusion of refused
clean training labels, and explicit availability failures. The complete Python
suite passes **307 tests with three existing optional skips**. No dependency
was installed, and remote CI was not run.

```sh
OPENBLAS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 OMP_NUM_THREADS=1 \
  python3 -B scripts/research_full_raw_pipeline.py \
  --previous .local/adaptive-corridor/20261028-quantile-level-v1 \
  --output /absolute/path/to/new-full-raw-run
OPENBLAS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 OMP_NUM_THREADS=1 \
  python3 -B scripts/audit_full_raw_pipeline.py \
  --output /absolute/path/to/new-full-raw-run
```

The archive retains 7,488 case/group rows, 7,488 regime/group rows, 1,872 phase
rows, 4,680 bound summaries and 423 paired comparisons across 104 intervals in
74 sessions. Within-run caching reduces repeated fits to eighteen distinct
new models. All inspected dates remain development data.

The next candidate needs a causal admission/forecast rule that transfers to
later oracle update regimes, with an evaluation population that can distinguish
that behavior before selection. Merely refitting the old scalar priors on more
raw paths does not supply it. Broader chronological use of already inspected
later development dates and distinct raw regimes is warranted before another
small parameter search. The full goal remains open: a defensible frozen
adaptive candidate, reliable new eight-hour observations, and subsequent
payout/fee/cost/strategy-conditioned LP economics validation.
