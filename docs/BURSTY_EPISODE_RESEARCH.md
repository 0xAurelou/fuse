# Bursty episode refinement and full-day raw controls — 28 October 2026

Follow-up: [chronological raw-prior recalibration](CHRONOLOGICAL_RAW_PRIOR_RESEARCH.md)
now uses these full-day raw rows to replace matching prior-training dates,
strictly before each evaluated date. It leaves the January startup and June
later-phase failures unresolved and retains the existing research benchmark.

Eleven predeclared alternatives were compared across **188 eight-hour case intervals in 130 sessions**, including new full-day raw January and June 2025 controls. **Earlier-period selection retains `floor10_burst_pool120`**. No live candidate is promoted and **no new capture starts**.

Episode resets and feature matching reduce January’s later-phase error, but leave startup too high and do not solve June drift. The previous pool’s original June 06:00–14:00 failure is **38.24% survival in both restart and genuine continuous mode**. This is no longer an untested continuous-history gap. Within each source/run, all pricing variants preserve eligibility, both admission masks and frozen quotes.

## New data and what it resolves

Full-day raw BTC oracle data was fetched anonymously for the two known failure dates, with the eleven pricing alternatives and source hash pinned before downloading missing minutes. The request list contains **2,880 minutes**: **970 reused, 1,910 newly fetched**, with zero fetch errors. This adds trajectories on inspected dates, not independent calendar holdouts or prospective/native paired capture evidence.

| Date | Raw messages | Disconnect markers | Shared normalized timestamps | Oracle mismatches | Normalized eligible bursty paths | Raw eligible bursty paths | Prior training dates |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 2025-01-01 | 82,757 | 4 | 37,278 | 0 | 60 | 103 | 2 |
| 2025-06-01 | 82,539 | 85 | 36,790 | 0 | 5 | 100 | 7 |

The existing normalizer omits many unchanged heartbeat messages. The unchanged eight-second freshness and clean-history screens can therefore exclude paths that remain observable in raw data. June’s bursty evidence rises from **5 to 100 eligible paths**, January from **60 to 103**. Original source prices agree at all **74,068 shared timestamps**. This does not establish raw feed completeness or repair native capture reliability.

Both original short-panel restarts were reconstructed exactly from reused raw minutes, including every row and baseline width, shadow outcome, pause and cap flag. Full-day continuous inference starts at midnight; the original 04:15/06:00 scoring intervals can now retain genuine earlier same-day evidence. Their restart counterparts still clear private state and retain only the original five-minute feature lookback.

The full-day canonical 00:00/08:00/16:00 intervals and the original shifted panels are reported separately. They overlap each other and the earlier tests, so their pass counts are not added into one independent sample. Additional raw outcomes never select the research candidate or refit the original engine. Overlay priors continue to use only the preceding original monthly dates.

## January cancellation and June drift on the matched panels

| Panel | Pricing | Restart aggregate | Continuous aggregate | Restart first12 / later | Continuous first12 / later |
| --- | --- | ---: | ---: | ---: | ---: |
| 2025-01-01 | Simple floor | 58.82% | 56.86% | 83.33% / 51.28% | 75.00% / 51.28% |
| 2025-01-01 | Previous pool | 45.10% | 47.06% | 83.33% / 33.33% | 75.00% / 38.46% |
| 2025-01-01 | Faster clock | 43.14% | 45.10% | 75.00% / 33.33% | 75.00% / 35.90% |
| 2025-01-01 | Episode + feature matching | 58.82% | 56.86% | 83.33% / 51.28% | 75.00% / 51.28% |
| 2025-01-01 | Episode + faster step | 58.82% | 56.86% | 83.33% / 51.28% | 75.00% / 51.28% |
| 2025-06-01 | Simple floor | 41.18% | 41.18% | 50.00% / 36.36% | 50.00% / 36.36% |
| 2025-06-01 | Previous pool | 38.24% | 38.24% | 41.67% / 36.36% | 41.67% / 36.36% |
| 2025-06-01 | Faster clock | 38.24% | 38.24% | 41.67% / 36.36% | 41.67% / 36.36% |
| 2025-06-01 | Episode + feature matching | 41.18% | 41.18% | 50.00% / 36.36% | 50.00% / 36.36% |
| 2025-06-01 | Episode + faster step | 41.18% | 41.18% | 50.00% / 36.36% | 50.00% / 36.36% |

January has 51 common bursty paths, June 34. Mode pairing verifies identical entry prices and realized movement on these paths. The first-twelve and later groups contain 12/39 paths in January and 12/22 in June. Phase groups below twenty are descriptive, not pass tests.

![Episode, restart and continuous phase calibration](../.local/adaptive-corridor/20261028-bursty-episodes-v1/episode-phase-comparison.png)

January’s episode/kernel variant restores later survival to **51.28%**, versus **33.33%** for the previous pool in restart mode. Startup stays **83.33%**, so aggregate survival becomes **58.82%** and fails. In continuous mode the same variant leaves startup at **75.00%**, later survival **51.28%** and aggregate **56.86%**. Correcting the later phase exposes the unresolved startup pricing rather than completing the calibration.

January’s later-phase rates with the episode/kernel method also match the simple floor. This mainly removes the previous pool’s late overcorrection; it does not demonstrate additional predictive skill or fix cold-start calibration.

June’s new matched continuous run leaves the previous pool at **38.24%**, exactly its restart rate. The episode/kernel variant changes startup from 41.67% to 50.00%, but later survival remains **36.36%** and aggregate **41.18%** in both modes. A longer preceding same-day history does not solve this failure.

## Original benchmark and later periods

Passes still use the legacy 48% survival target and 43–53% band, with at least twenty eligible/quoted paths. The original ten raw restart cases contain eight sufficiently populated bursty cells. Availability remains **89.48% pooled / 60.38% minimum** under previous-floor admission and **88.17% / 65.82%** under warmup/floor30 admission. Every eligible non-frozen path stays offered.

| Alternative | Original raw bursty passes | First12 survival | Later survival | Later normalized restart passes | Later normalized continuous passes |
| --- | ---: | ---: | ---: | ---: | ---: |
| `engine_floor10` | 1/8 | 61.02% | 49.19% | 5/11 | 4/11 |
| `floor10_burst_pool120` | 4/8 | 59.32% | 42.39% | 7/11 | 6/11 |
| `burst_clock120` | 5/8 | 58.47% | 41.75% | 8/11 | 7/11 |
| `burst_cdf60` | 3/8 | 60.17% | 47.90% | 6/11 | 7/11 |
| `episode_cdf` | 1/8 | 61.02% | 49.84% | 5/11 | 5/11 |
| `kernel_cdf` | 2/8 | 61.02% | 49.19% | 4/11 | 4/11 |
| `episode_kernel` | 1/8 | 61.02% | 49.84% | 5/11 | 5/11 |
| `episode_kernel_soft` | 1/8 | 61.02% | 49.84% | 5/11 | 5/11 |
| `episode_kernel_fast` | 1/8 | 61.02% | 50.81% | 5/11 | 5/11 |
| `episode_kernel_prior` | 1/8 | 61.02% | 50.49% | 4/11 | 4/11 |
| `episode_kernel_guard` | 1/8 | 61.02% | 49.84% | 5/11 | 5/11 |

The episode/kernel changes put original pooled later survival around 49.84%, but first-twelve survival remains 61.02%. Their original raw bursty passes fall to **1/8**, versus **4/8** for the retained pool and **5/8** for the faster clock. This is not a validated successor. The January 2026 08:00 first-twelve minimum-width floor remains 66.67%; a new price formula cannot bring that particular observed subset to 48% under the current minimum-width/admission constraints.

| Split / mode | Pricing | Bursty passes | Bursty mean absolute error (pp) | Bursty / non-frozen same-path loss (ppm) |
| --- | --- | ---: | ---: | ---: |
| validation / restart | Simple floor | 3/9 | 7.03 | 104.456 / 112.191 |
| validation / restart | Previous pool | 6/9 | 4.96 | 106.186 / 112.272 |
| validation / restart | Faster clock | 6/9 | 5.28 | 106.071 / 112.267 |
| validation / restart | Time-weighted CDF | 4/9 | 5.38 | 105.996 / 112.264 |
| validation / restart | Episode + feature matching | 4/9 | 5.86 | 105.198 / 112.226 |
| validation / restart | Episode + context prior | 1/9 | 8.25 | 106.715 / 112.297 |
| validation / continuous | Simple floor | 4/9 | 6.60 | 103.364 / 112.193 |
| validation / continuous | Previous pool | 6/9 | 4.96 | 104.985 / 112.270 |
| validation / continuous | Faster clock | 6/9 | 5.06 | 105.127 / 112.276 |
| validation / continuous | Time-weighted CDF | 5/9 | 4.73 | 105.116 / 112.276 |
| validation / continuous | Episode + feature matching | 5/9 | 5.54 | 104.112 / 112.228 |
| validation / continuous | Episode + context prior | 2/9 | 7.55 | 105.573 / 112.297 |
| test / restart | Simple floor | 5/11 | 7.94 | 79.476 / 83.609 |
| test / restart | Previous pool | 7/11 | 4.75 | 80.303 / 83.646 |
| test / restart | Faster clock | 8/11 | 4.33 | 80.609 / 83.659 |
| test / restart | Time-weighted CDF | 6/11 | 6.11 | 79.551 / 83.613 |
| test / restart | Episode + feature matching | 5/11 | 8.18 | 80.242 / 83.643 |
| test / restart | Episode + context prior | 4/11 | 8.31 | 80.546 / 83.657 |
| test / continuous | Simple floor | 4/11 | 8.07 | 79.503 / 83.576 |
| test / continuous | Previous pool | 6/11 | 5.17 | 79.555 / 83.578 |
| test / continuous | Faster clock | 7/11 | 4.70 | 80.819 / 83.634 |
| test / continuous | Time-weighted CDF | 7/11 | 5.58 | 80.010 / 83.598 |
| test / continuous | Episode + feature matching | 5/11 | 7.79 | 80.203 / 83.607 |
| test / continuous | Episode + context prior | 4/11 | 7.93 | 80.482 / 83.619 |

## Added full-day eight-hour calibration

| Alternative | Full-day restart bursty passes | Full-day continuous bursty passes | Shifted-panel restart passes | Shifted-panel continuous passes |
| --- | ---: | ---: | ---: | ---: |
| `engine_floor10` | 2/5 | 2/5 | 0/2 | 0/2 |
| `floor10_burst_pool120` | 5/5 | 4/5 | 1/2 | 1/2 |
| `burst_clock120` | 4/5 | 3/5 | 1/2 | 1/2 |
| `burst_cdf60` | 2/5 | 2/5 | 0/2 | 0/2 |
| `episode_cdf` | 2/5 | 2/5 | 0/2 | 0/2 |
| `kernel_cdf` | 2/5 | 2/5 | 0/2 | 0/2 |
| `episode_kernel` | 2/5 | 2/5 | 0/2 | 0/2 |
| `episode_kernel_soft` | 2/5 | 2/5 | 0/2 | 0/2 |
| `episode_kernel_fast` | 2/5 | 2/5 | 0/2 | 0/2 |
| `episode_kernel_prior` | 2/5 | 2/5 | 0/2 | 0/2 |
| `episode_kernel_guard` | 2/5 | 2/5 | 0/2 | 0/2 |

The retained pool passes **5/5 sufficiently populated canonical restart cells** and **4/5 continuous cells** on the added days. There are six planned cells: January’s 08:00 group has only eighteen bursty paths and does not count as a pass. It remains a visible miss at **38.89% restart / 16.67% continuous**. Small or absent groups are not successes.

| Date / UTC hour | Bursty n | Previous pool restart | Previous pool continuous | Episode/kernel restart | Episode/kernel continuous |
| --- | ---: | ---: | ---: | ---: | ---: |
| 2025-01-01 / 00:00 | 58 | 51.72% | 51.72% | 55.17% | 55.17% |
| 2025-01-01 / 08:00 | 18 | 38.89% | 16.67% | 50.00% | 44.44% |
| 2025-01-01 / 16:00 | 27 | 44.44% | 48.15% | 62.96% | 62.96% |
| 2025-06-01 / 00:00 | 35 | 45.71% | 45.71% | 51.43% | 51.43% |
| 2025-06-01 / 08:00 | 25 | 44.00% | 40.00% | 40.00% | 36.00% |
| 2025-06-01 / 16:00 | 40 | 45.00% | 45.00% | 45.00% | 45.00% |

June’s canonical 08:00 slice is **44.00% restart / 40.00% continuous** with the retained pool. The shifted 06:00 control remains 38.24% in both. Thus conclusions depend on both start time and the available evidence; a favorable canonical aggregate does not resolve the original failure.

For previous-floor admission, all originally eligible paths are offered in the added suites: canonical restart **5,683**, canonical continuous **5,687**, shifted-panel restart **1,880**, shifted-panel continuous **1,882**. Their eligible availability is 100% within this admission policy. Different clean-history framing yields different overall eligible counts, so the paired bursty analysis uses intersections instead of equating denominators. Pre-entry and full-grid counts remain in the archive and do not represent capture uptime.

## Mechanisms and episode evidence

An episode begins at an eligible bursty entry after a five-minute burst-free gap, or when preceding five-minute volatility changes by a factor of at least two relative to the last bursty entry. All triggers use pre-entry features. Full reset anchors the correction at one; soft reset shrinks its log toward zero with a five-minute half-life across the gap. Only the selected episode’s mature bursty outcomes enter an episode-restricted leaf, so delayed outcomes from an earlier episode cannot contaminate it.

Feature matching uses distances in log preceding five-minute volatility, log fast/slow volatility ratio, log(1+idle seconds) and log(1+changes in sixty seconds), with fixed bandwidths log(2), log(2), 1, 1. The similarity weight is exp(-distance²/2), multiplied by a 30-minute time half-life. Parent transfer mass is capped by both effective sample size and total similarity/recency weight; unrelated evidence cannot regain full confidence merely by normalization.

The distribution mixture keeps training prior mass twelve, a latest-sixty non-bursty parent, latest-thirty bursty leaf and one-hour age cap. CDF references are normalized by training state factors. Conditional-prior variants add six cooling/balanced/fresh × recent/idle contexts; idle splits at five seconds. A leaf requires eighty windows across three periods or falls back to the bursty state prior. Every conditional leaf falls back in the January and June 2025 coefficient sets; the original final model supports only two of six leaves. More context labels do not create evidence.

Correction updates are limited to 5% per bursty entry, or 15% for the fast variant, except that an explicit episode reset may jump further toward the anchor. Factors remain bounded to 0.05–2 and widths to 1–50,000 ppm. These are new-quote changes; existing quotes remain fixed for their lifetime. Pump/dump bypass, frozen/non-bursty invariance, refusal-independent learning, period reset and expiry-plus-thirty-second maturity are preserved.

An additional episode-phase view splits the first sixty seconds after each pre-entry episode boundary from later decisions. The first group precedes maturity of that episode’s first thirty-second reference. It differs from the first twelve bursty decisions per eight-hour interval. The same pre-entry episode partition is used for every comparator.

| Matched source / mode | Pricing | Initial60s eligible / survival | Later eligible / survival |
| --- | --- | ---: | ---: |
| 2025-01-01 / restart | Previous pool | 25 / 56.00% | 26 / 34.62% |
| 2025-01-01 / restart | Episode + feature matching | 25 / 72.00% | 26 / 46.15% |
| 2025-01-01 / continuous | Previous pool | 25 / 56.00% | 26 / 38.46% |
| 2025-01-01 / continuous | Episode + feature matching | 25 / 72.00% | 26 / 42.31% |
| 2025-06-01 / restart | Previous pool | 17 / 47.06% | 17 / 29.41% |
| 2025-06-01 / restart | Episode + feature matching | 17 / 52.94% | 17 / 29.41% |
| 2025-06-01 / continuous | Previous pool | 17 / 47.06% | 17 / 29.41% |
| 2025-06-01 / continuous | Episode + feature matching | 17 / 52.94% | 17 / 29.41% |

June has seventeen paths in each episode-phase group. Later episode survival remains **29.41%**, even when restart/continuous history and episode resets are changed. This is stronger evidence of a persistent conditional pricing miss than treating the problem solely as run startup. Small groups and reused paths remain descriptive.

## Selection and reproducibility

The phase-aware restart/continuous selection objective is unchanged from the preceding iteration. Original prefixes of 6/9/12 monthly training dates score the next 3/3/2 dates, with equal mode/phase weights as declared previously and the same loss guard. Raw extensions and 2026 failure dates are excluded. Selection is saved before the newly downloaded files are parsed for evaluation.

| Alternative | Score | Fold scores |
| --- | ---: | --- |
| `floor10_burst_pool120` | 21.557 | 22.972 / 21.387 / 20.313 |
| `burst_clock120` | 23.406 | 22.972 / 21.387 / 25.860 |
| `engine_floor10` | 31.432 | 33.994 / 21.387 / 38.917 |
| `burst_cdf60` | 31.820 | 33.668 / 21.387 / 40.404 |
| `episode_cdf` | 31.820 | 33.668 / 21.387 / 40.404 |
| `episode_kernel_fast` | 31.989 | 36.728 / 20.324 / 38.917 |
| `episode_kernel_prior` | 32.744 | 33.668 / 20.211 / 44.352 |
| `kernel_cdf` | 33.136 | 33.668 / 21.387 / 44.352 |
| `episode_kernel` | 33.136 | 33.668 / 21.387 / 44.352 |
| `episode_kernel_soft` | 33.136 | 33.668 / 21.387 / 44.352 |
| `episode_kernel_guard` | 33.136 | 33.668 / 21.387 / 44.352 |

The previous pool remains at 21.557, faster clock at 23.406. The earlier sample still contains only two distinct eight-hour bursty cells with at least twenty paths. Continuous replay and repeated inspection do not make these independent episodes. None of the new refinements earns replacement on this benchmark.

Implementation: `scripts/bursty_episodes.py`, `scripts/research_bursty_episodes.py`, `scripts/fetch_bursty_full_days.py`. Research archive: `.local/adaptive-corridor/20261028-bursty-episodes-v1/`. Raw archive: `.local/market-history/tardis-hyperliquid-BTC-bursty-full-days-v1/`. Retained evidence includes candidate/download protocols, minute/source hashes, earlier-fold models, final priors, 33,088 case/group/policy/model rows, 12,408 run-phase rows, 4,136 episode-phase rows, 979 paired rows and compressed predictions. New input sessions are cached separately with a SHA binding. All four comparators, original short-panel frames and shared raw/normalized oracle values reconstruct.

```sh
python3 -B scripts/research_bursty_episodes.py \
  --previous .local/adaptive-corridor/20261028-bursty-drift-v1 \
  --raw .local/market-history/tardis-hyperliquid-BTC-bursty-full-days-v1 \
  --output .local/adaptive-corridor/NEW-NONEXISTENT-DIRECTORY
python3 -B -m unittest discover -s scripts -p 'test_*.py'
```

Validation: **207 tests run successfully, with three existing optional skips**. Eleven added tests cover causal episode boundaries, expiry-plus-delay outcome use, old-episode pending isolation, kernel confidence, state/quote invariance, refusal learning, reset/rate/age/memory behavior, conditional fallback and guard rules, pre-entry episode-phase membership, and exclusion of later/raw outcomes from selection.

The next calibration experiment can now replace the poorly covered earlier normalized days with their complete raw reference paths, using only chronological training prefixes and keeping current-date outcomes out of each fit. That would test whether the priors, rather than another correction-rate change, explain startup error. This iteration deliberately holds that data-fitting choice fixed to isolate the new learning mechanisms. The retained January/June phase failures, frozen-state misses and original capture continuity/deadline issues still prevent freezing a successor and starting capture.
