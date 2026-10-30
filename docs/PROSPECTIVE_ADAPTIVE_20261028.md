# Frozen adaptive falsification trial — 28 October 2026

**Status: recording; pricing results pending.** The original eight-hour horizon
starts **28 October 2026, 22:31:07.783 WITA** and ends **29 October 2026,
06:31:07.783 WITA** (UTC+8). This is observation-only public BTC oracle
collection. No trades, funds or production pricing are involved.

**29 October, 05:30 WITA continuity update:** both receivers are fresh and the
original recorder and completion monitor remain live. Earlier sleep and
reconnect gaps remain in the record. Two new normal-expiry reconnects at 05:12
and 05:13 bring the metadata-only audit to 63
affected completed windows, leaving final
healthy coverage at most 93.44% even with no further losses. This is an upper
bound, not measured healthy coverage. The frozen analyzer also has an exact-JSON policy comparison error
caused by Go's explicit zero fields. Its original result will be preserved; a
separately disclosed compatibility analyzer has been prepared before inspecting
pricing outcomes. See [the continuity and validation record](CAPTURE_CONTINUITY_20261029.md).

**Power after recovery:** the battery rose from its earlier 20% low to 76%.
It now reports 64% and discharging with a 3h45 estimate, exceeding the roughly
one hour still required. The user confirmed **“We are good now.”** Earlier power
warnings and recovery observations remain in the continuity record.
No capture restart, horizon extension, pricing change or software power change
was made.

A separately pinned completion-only job now waits for the original supervisor
to finish, preserves its result, then runs the disclosed compatibility replay.
Its packet is `.local/capture-readiness/20261029-adaptive-followup-v1/`.
It changes neither the original collector nor its deadline. Read that packet's
status before attempting a manual supplemental analysis.

A separate paper-economics protocol was fixed at **02:29 WITA**, during capture
but before pricing results, using the already declared entry rules and cost
assumptions. It will consume only the sealed post-horizon quote tape. It is not
part of the original primary protocol or funded LP validation. See
[the supplemental protocol](PROSPECTIVE_QUOTE_ECONOMICS_20261029.md).

The earlier-fold winner `market:priceable_open` is frozen as an **unvalidated
research challenger**. Its aggregate score improved, but it fails known frozen
January/August and September/October cases. The trial tests transfer to fresh
observations; freezing it does not establish the desired cross-period
calibration. The [retrospective report](FROZEN_MARKET_CONTEXT_RESEARCH.md) retains
these limitations. Economics after payouts, fees, costs, strategies and LP
exposure are not evaluated.

## Frozen packet

Directory:
`.local/prospective-runs/20261028-adaptive-context-8h-v1/`.

- Primary: `market:priceable_open`, chosen by the archived earlier-fold score.
- Controls: `retained_open` and `timing:priceable_open`, named before capture.
- Models: archived twenty-two-date CDF fits and retained fourteen-date pricing
  bundle; no new fitting or choice from September/October or live observations.
- Analysis specification SHA-256:
  `7992cdd6c077aeded855aaadd6fffcd4e27524ce1b3fdb6744f5f742ec8b095c`.
- Frozen policy SHA-256:
  `e97340bd0a99ec85a2e0c955f085fbd1930dfd2ab8d47bdfaa07f815244badef`.
- Native recorder SHA-256:
  `e7f8b5ffc329744267a620ce37beedc8d6767eeaea1289ed9dd41358453eba4b`.

The specification pins 110 files, including the model bundle, selection,
research/audit evidence, Python source, input adapter, supervisor, analyzer,
recorder, native source and policy documents. `freeze.json` binds the analysis
and policy. The native manifest commits the original capture start, horizon and
policy. Python and NumPy versions are recorded and checked before analysis.

The recorder's 314-ppm policy field is observation transport metadata. Candidate
widths come from the frozen adaptive analyzer, not that field. No live order
execution or economic result may be inferred from the native policy's width.

## Inputs and permitted adaptation

Both receiver connections use the same upstream Hyperliquid oracle. Agreement
checks connection health; it does not establish independent oracle truth.
Native hash-chain verification precedes offline input construction. The native
paired receipt rules determine health and exact oracle barrier paths.

Entries lie on `manifest.frozen_at_ms + k*30000`. Features use five minutes of
clean history strictly before entry. Entry health uses only prior receiver
state; a subsequent outage censors its outcome without retroactively deleting
the entry decision. Receiver `a` supplies mark/oracle context strictly before
entry and entry-minus-thirty-seconds, fresh within eight seconds. Neither price
interpolation nor mark-as-oracle substitution is allowed. Missing market context
uses the frozen retained fallback. The capture uses one period identifier, with
no reset at a calendar boundary. This horizon crosses WITA midnight; it does not
cross UTC midnight.

The declared online updates remain enabled: clean reference labels mature at
expiry plus thirty seconds; the floor model learns all supported references;
the priceability coverage level learns only references whose saved forecast
floor is below 48%. These predetermined updates are part of the frozen model.
No coefficient fit, formula change, new threshold, candidate reselection,
horizon extension or early stopping for pricing success is allowed.

## Analysis and reliable completion

The primary replay is continuous over the full eight hours. A descriptive
restart replay resets private online state at four hours while retaining past
feature history. Two-hour blocks, pre-entry market regimes and oracle activity
groups report conditional behavior. Restart results reuse the same paths and
are not independent replications.

The analyzer retains a per-entry prediction trace, full grid/entry/healthy
outcome/quote denominators, conditional minimum-width bounds, survival,
descriptive Wilson intervals, serial-dependence diagnostics and paired
challenger/control outcomes. Point percentages or small conditional groups do
not independently establish a 48% probability. No single aggregate pass is a
promotion decision.

Collection quality requires at least 400 healthy outcomes and at least 90%
healthy-window coverage across the original horizon. Missing observations stay
in that denominator. Reliable completion and pricing calibration are distinct:
a verified, high-quality recording can reject the challenger.

The rebuilt recorder matches the binary that passed the prior live two-minute
health/deadline preflight. The v2 supervisor checks the original wall deadline,
receiver freshness and its own liveness. `caffeinate -i` runs with supervision;
it prevents idle sleep, not physical lid closure or power loss. Actual uptime
and the final coverage still have to be observed. No physical suspend/resume
drill or external alert service was added.

At completion, the frozen supervisor verifies all artifacts and native receipts,
then invokes its frozen adaptive analyzer. `analysis.json` and
`analysis-predictions.jsonl.gz` are written without replacing prior analyses.
Failed verification, runtime mismatch, early exit or inadequate coverage cannot
be treated as successful prospective evidence.

Read health without evaluating or retuning pricing during collection:

```sh
python3 -B .local/prospective-runs/20261028-adaptive-context-8h-v1/supervisor.py \
  status --directory .local/prospective-runs/20261028-adaptive-context-8h-v1
```

Do not start another supervisor, replace the packet, or extend the original
deadline. A failed or interrupted attempt requires a separately identified
successor with its own frozen plan and an honest failure record.
