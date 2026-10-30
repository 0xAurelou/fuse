# Earlier raw training and bursty startup admission — 28 October 2026

Follow-up: [pre-entry signals and conditional pricing](PREENTRY_SIGNAL_RESEARCH.md)
replaces fixed startup warmup with trained entry-time risk gates and tests
conditional pricing with full quote retention. The risk gates remain inactive;
June later drift and January startup still prevent a successor or new capture.

This follow-up gathers earlier raw training data and compares causal bursty startup gates before any new capture. Engines, frozen pricing, the retained pooled bursty pricing algorithm and both existing frozen-admission policies remain fixed. No capture starts and no live candidate is promoted.

## Earlier data and chronological fitting

The download declaration pins the complete November and December 2024 sample days, ten admission rules and their source code before fetching any raw outcomes. All **2,880 minute responses** download anonymously with no errors, pass gzip/CRC validation and retain SHA-256 hashes. No credentials or paid endpoints are used.

| Date | Raw messages | Disconnect markers | Shared normalized timestamps | Price mismatches | Normalized / raw bursty paths |
| --- | ---: | ---: | ---: | ---: | ---: |
| November 1, 2024 | 84,271 | 2 | 38,968 | 0 | 10 / 31 |
| December 1, 2024 | 83,489 | 5 | 32,895 | 0 | 41 / 100 |

The raw samples expose **131 bursty paths versus 51** in the normalized rows, with zero oracle-price mismatches at all **71,863 shared timestamps**. Disconnect windows and the existing freshness/clean-history screens remain in place. More retained messages do not establish feed completeness.

Three prior sources isolate the changes: the normalized benchmark; the previous January/June 2025 raw replacements; and those replacements plus the new November/December raw rows. Each raw version replaces its matching normalized training day once. Fitting still uses the original training-date universe, equal date weighting and a strict date/maturity cutoff. January 2025 can learn only November/December 2024. June 2025 can additionally learn January 2025, but never its own June raw outcomes. Later dates can use all four replacements when they lie inside their training prefix.

Every training width is recomputed with the target model's fixed engine. The new samples increase coverage on existing dates; they add no calendar dates or independent holdouts. January still has only two prior training dates, so the bursty prior retains its existing fallback to the non-frozen parent rather than bypassing the three-period support requirement.

## Admission rules and comparison design

Ten rules are pinned before downloading: unchanged admission; warmup of six or twelve mature bursty references; a minimum-width-floor guard after six references; each warmup combined with that guard; episode-specific and context-specific warmup/guard; hysteresis; and shrinkage toward the chronological training prior. Floor entry uses the existing 53% upper reference, hysteresis resumes at 43%, and every outcome becomes available only at expiry plus thirty seconds. The recent pool holds at most thirty references for one hour.

Episode boundaries use only a five-minute burst gap or a twofold slow-volatility change. Context uses the existing fast/slow volatility bucket and pre-entry idle status. The rules add only bursty refusals. They never change a price, remove an existing refusal, alter a frozen decision or read the current outcome's validity/move before maturity. Refused reference paths continue to teach the pricing and admission state.

The experiment compares **21 variants**: ten gates with normalized priors, ten with the earlier raw priors, and unchanged admission with the previous two-day raw priors. All **104 eight-hour case intervals in 74 sessions** are replayed under both existing frozen-admission policies. Canonical full-day raw intervals, shifted intervals, original controls, normalized later periods and native replays remain separately reported because many paths overlap.

The first-twelve/later phase groups are fixed from pre-entry rank before refusal or outcome validity. A gate cannot move later quotes into the startup group. Reports retain offered counts, full reference outcomes, rejected survivors/failures, grid/pre-entry denominators and full-reference pricing loss. A phase with no quotes has no measured offered survival, and a case reduced below twenty offered paths never counts as a pass.

Restart/continuous comparisons verify identical prices and realized movement on common eligible paths. They also report both-offered intersections and disagreements in admission, since mode-specific quote selection can otherwise distort a calibration comparison. Continuous state is never reset at an eight-hour scoring boundary.

## Earlier-fold selection

Selection uses only the original three chronological folds, both modes and normalized scoring inputs. It keeps the previous calibration/phase objective and full-reference pricing-loss guard, then charges incremental lost availability and previously populated bursty cells that become too small to assess. Phase errors use original eligible counts as weights; an empty offered phase receives a 52-point error charge. The exact cost is pinned in the protocol and runner.

The normalized unchanged benchmark reconstructs its previous **21.557** score exactly. The earlier raw prior with unchanged admission scores **20.812**, versus **22.711** for the previous January/June-only raw prior. Only the first fold improves; the other two are unchanged. The floor-only gate ties unchanged admission because it does not activate in these earlier folds, so this supplies no selection evidence for that gate.

Warmup of six references scores about **66.69** with the earlier raw priors; twelve-reference warmup scores **94.89**. The availability charge exposes the cost of suppressing thin bursty cases. These repeatedly inspected folds still contain only two distinct bursty cases with twenty or more paths. A small selection gain does not establish readiness or validate a new live candidate.

## January startup and June drift

Without an additional gate, earlier raw priors leave all the following phase survival rates unchanged from the normalized benchmark. The expanded fourteen-date prior now has **671 bursty references**, versus 591 in the previous raw replacement and 453 originally. June's chronological prior has 388 versus 265; January 2025 has 131 versus 51, but still only two prior dates and therefore the parent fallback.

| Raw interval and mode | No new gate: startup / later | Warm6 + floor: startup offered | Warm6 + floor: later offered |
| --- | ---: | ---: | ---: |
| January 2025 04:15–12:15, restart | 83.33% / 33.33% | 80.00%, 5/12 paths | 33.33%, 33/39 |
| January 2025 04:15–12:15, continuous | 75.00% / 38.46% | 80.00%, 5/12 | 39.39%, 33/39 |
| June 2025 06:00–14:00, restart | 41.67% / 36.36% | 33.33%, 6/12 | 35.71%, 14/22 |
| June 2025 06:00–14:00, continuous | 41.67% / 36.36% | 50.00%, 6/12 | 35.71%, 14/22 |
| January 2026 08:00–16:00, restart | 75.00% / 46.15% | No quotes, 0/12 | 40.00%, 10/13 |
| January 2026 08:00–16:00, continuous | 75.00% / 46.15% | No quotes, 0/12 | 40.00%, 10/13 |

All gated entries use the earlier raw prior. “Startup” means the first twelve pre-entry bursty decisions of the scored interval, not necessarily a contiguous six-minute episode. Phase membership stays fixed. Smaller offered samples and their uncertainty are explicit; no-quotes phases have no survival measurement.

![Startup calibration and refused paths](../.local/adaptive-corridor/20261028-earlier-raw-startup-v1/startup-phase-comparison.png)

January 2026 exposes the support problem: its first twelve restart decisions have **zero to three** mature bursty references in the trailing hour. The floor-only guard requires six, so it cannot activate during that startup phase. Warm6 instead refuses every startup quote. Continuous history does not improve the observed startup result. Aggregating the twelve outcomes afterward cannot provide the missing evidence at those earlier quote times.

Context warmup refuses every June and January 2026 quote in these matched intervals. In January 2025 it retains just two of thirty-nine later paths, with 50% restart / 100% continuous survival. Those tiny selected samples do not demonstrate calibration. The episode rule retains only four January 2025 paths and one June path. Longer twelve-reference warmup also leaves too few quotes to evaluate most original bursty tests.

The June drift remains a pricing failure: its unchanged later survival is 36.36% in both modes. Warm6 leaves 35.71% on fourteen later paths in both modes, rather than repairing that pricing. All refused survivors and failures remain in the full-reference diagnostics.

## Availability and comparison across periods

These results use earlier raw priors and previous-floor frozen admission. Both frozen policies are retained in the archive. Original raw restart tests contain ten intervals and eight populated bursty cells. Pass counts below use that fixed denominator; cells reduced below twenty quotes remain failures, not disappearing tests.

| Added bursty gate | All-path availability | Bursty availability | Bursty passes | Populated bursty cells made too small |
| --- | ---: | ---: | ---: | ---: |
| Unchanged | 89.48% | 100.00% | 4/8 | 0 |
| Floor only, six references | 89.48% | 100.00% | 4/8 | 0 |
| Warm6 + floor | 87.67% | 60.42% | 2/8 | 2 |
| Warm12 + floor | 86.29% | 30.44% | 2/8 | 6 |
| Episode warm6 + floor | 85.25% | 7.96% | 0/8 | 8 |
| Context warm6 + floor | 85.29% | 8.67% | 0/8 | 8 |

Hysteresis and prior shrinkage produce the same original raw availability and pass counts as Warm6 in this batch. Warmup without the floor guard also matches its corresponding warmup/floor result. The new gates preserve all prices, so full-reference pricing loss is identical across gates for a given prior. An improved offered-only statistic must not be described as a pricing improvement.

| Panel | No new gate: restart / continuous bursty passes | Warm6 + floor: restart / continuous |
| --- | ---: | ---: |
| Original raw | 4/8 / 2/5 | 2/8 / 1/5 |
| Canonical full-day raw | 5/5 / 4/5 | 1/5 / 1/5 |
| Later normalized test dates | 7/11 / 6/11 | 2/11 / 3/11 |

There are six canonical raw intervals but only five with twenty bursty paths. January 2025 08:00 has eighteen and is not a pass; its large restart/continuous miss remains. The shifted panels overlap the canonical and original panels and are not added as new independent tests. Later normalized bursty availability falls to 47.58% restart / 48.04% continuous under Warm6, with six of eleven previously populated cells made too small in each mode.

Earlier raw priors with unchanged admission retain the previous pass counts across these panels. Original raw bursty survival shifts from 47.07% to 47.54%, while full-reference loss slightly worsens, **48.310 → 48.336 ppm**. Later normalized restart loss worsens **80.303 → 80.650 ppm**. Shifted raw restart loss improves **48.082 → 47.953 ppm**. The loss evidence remains mixed despite the first-fold selection improvement.

No tested startup gate resolves January startup and June drift at acceptable retained coverage. Keep the earlier raw prior as a research alternative, retain unchanged admission as the benchmark, and leave capture on hold. The evidence points to two distinct limitations: insufficient timely bursty evidence for startup admission, and later-period pricing drift that quote refusal does not repair. Additional distinct preceding training dates would be needed to support a bursty-specific January 2025 prior rather than its two-date fallback.

## Reproduction and retained evidence

```sh
python3 -B scripts/fetch_earlier_bursty_training.py \
  --previous .local/adaptive-corridor/20261028-chronological-raw-priors-v2 \
  --output .local/market-history/tardis-hyperliquid-BTC-earlier-bursty-training-v1
python3 -B scripts/fetch_flat_samples.py --fetch \
  --output .local/market-history/tardis-hyperliquid-BTC-earlier-bursty-training-v1
python3 -B scripts/research_bursty_startup_raw.py \
  --previous .local/adaptive-corridor/20261028-chronological-raw-priors-v2 \
  --raw .local/market-history/tardis-hyperliquid-BTC-earlier-bursty-training-v1 \
  --output .local/adaptive-corridor/20261028-earlier-raw-startup-v1
python3 -B -m unittest discover -s scripts -p 'test_*.py'
```

Use new output directories for new declarations and experiments; the downloader resumes only the exact pinned requests. The archive retains source snapshots, input hashes, earlier raw rows, chronological priors, selection folds, offered/full-reference case and phase metrics, admission decisions, and mode pairs. All **225 Python tests** complete successfully with three existing optional skips. New tests cover maturity, refused-reference learning, current/future outcome isolation, episode/context resets, hysteresis/prior controls, preserved prices and non-bursty decisions, fixed phase membership, lost-availability penalties and both-offered pairing.

The legacy target is 48% survival with a 43–53% reference band, not payout-product validation. Twelve-path startup groups are descriptive. Native continuity/deadline defects remain unresolved by this research, and historical quote availability is not capture uptime.
