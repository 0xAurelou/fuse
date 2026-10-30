# Native PPB pricing interface — 30 October 2026

**Interface implemented; full retained-tape replay and software audit complete. Production
pricing remains unvalidated.** No current desk configuration, deployed
contract, live collector or accepted bet has been changed.

The engine now accepts `model.multiplier_widths_ppb`, a distinct fixed-table
format with integer parts-per-billion half-widths. It requires an explicit,
increasing, unique subset of the existing 2/5/10/25/50/100/250/1000/10000
presets and exactly one positive width per selected payout. Widths must
strictly decrease with payout and obey the model's maximum width. Every
enabled asset must use this format together. Formula/PPM formats keep their
previous full-menu requirements; legacy omitted-menu behavior is preserved.

```json
{
  "multipliers": [2],
  "model": {
    "multiplier_widths_ppb": {"2": 1000}
  }
}
```

This is a fragment, not a complete policy. The other protocol, source,
validity and risk fields remain mandatory. Formula, PPM and PPB tables cannot
be combined. Omitted PPB fields do not alter old policy/journal encodings.
Both paper and local-Anvil modes use the same deterministic reducer; public
chain execution remains disabled.

For entry price `P`, native barriers are exactly
`P ± floor(P * width_ppb / 1,000,000,000)`. A 1-ppm historical quote maps to
1,000 ppb without changing any rounded barrier. A width producing zero price
units is rejected rather than widened. Quotes disclose `fixed-width-ppb-v1`
and the exact width. The table does not infer or advertise an empirical edge
or target survival. The quoter retains all existing funding, account/global
exposure, freshness, TTL and outage checks.

Operator-authenticated policy updates already exist. Each changed table needs
new policy/model versions; a policy update invalidates unaccepted old quotes,
while accepted stages retain their original terms. This supports an offline
exact-width adapter. **It does not implement a live adaptive pricing service**,
train a model, validate a payout subset, or authorize activating it. A live
provider still needs frozen causal feature/width rules, update sequencing,
durable recovery, latency validation and admission integration.

## Checks completed

Seven new Go tests cover exact widths down to 1 ppb, 1-ppm 2x-only pricing,
all nine presets at finer resolution, invalid/mixed menus, low-price rounding,
multi-asset quotes, exact touches, oracle-sequence invalidation, accepted
terms, winning liabilities, settlement, withdrawal and replay. The complete
default Go suite passes; its HTTP/WebSocket fixtures require localhost test
ports outside the restricted sandbox.

The legacy comparison replays **33 identical requests** against the old and
new native binaries: every preset quote, a 10000x win, unpaid winnings,
settlement, withdrawal and payment. Every response, state hash and journal
hash matches. This is a bounded compatibility check, not a proof over every
historical command. Its source is `scripts/verify_ppb_legacy.py`.

Six adapter/evidence tests include actual native synthetic fixtures: an exact
1-ppm win followed by an 8-ppm loss, a future oracle outage refund without
inventing a terminal price, and three synchronized accounts with unpaid
winning liabilities plus new risk. Four separate auditor tests reject
omitted winner cash, custody drift, open stages and changed pricing terms,
and require unchanged bindings before reusing a completed case audit.
Five attachment tests additionally check source/artifact bindings, complete
audit coverage, independent terminal cash, cost denominators and observed
capital. Together with prior checks, **91 focused release tests pass without
skips** when both native binary environment variables are set. The complete
Python suite passes **654 tests with no skips**, with retained integration
fixtures and the new native binary explicitly supplied. The resumed run binds
413 test/code sources, unchanged throughout testing. Earlier native-packet
validation records remain historical; full-tape result/audit completion is
separate from a passing regression suite.

## Frozen full-tape execution

Packet: `.local/release-native-ppb/20261030-sealed-adaptive-v1/`.
`protocol.json` and `freeze.json` were written before the first native result.
The packet snapshots all relevant reducer, bridge and adapter sources and the
binary. It re-verifies all 49,175 original paired receipts with the original
native recorder, and binds the sealed quote and public-strategy decision tapes.
It retains all 960 grid opportunities, without downsampling or invented feeds.

All four profiles from the earlier failed adapter are retained: all offered
quotes with one account, frozen-oracle quotes with one, public last-matured-
failed with one, and all offered quotes with three synchronized accounts.
Each has hypothetical $250k LP capital, $1,000 per trader and $1 stakes.
Five-minute native cash settlements preserve already recognized liabilities.
Exact sealed widths are injected through journaled operator harness updates.
Finalization advances the prior oracle state through the original end and
void grace, with no fabricated terminal price.

The original trial remains **failed**, collection quality **false** and target
edge **4%**. Its original/public strategy results were already inspected.
This is retrospective native integration evidence, not a fresh prospective
test, the proposed 7–10% release model, actual customer demand, independent
samples or validation of the other assets/payouts. Native outcomes on paths
censored by the original analyzer are retained separately; they are not all
assumed refunds. Daily fees, funded token promises, LP ownership/withdrawals,
onchain execution and measured operating costs are outside this replay.

All four executions and their software audits have completed. The audit
reexecutes **208,134 native responses** and **196,700 receipt applications**
across four replays of the same **49,175 original paired receipts**. Every
response matches; terminal cash reconciles separately for all four cases.
The original trial's failed quality and 4% target are preserved.

| Profile | Accepted | Survived | Exploded | Voided | LP gross PnL | Peak LP liability |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| All offered, one account | 620 | 290 | 318 | 12 | +$28 | $9 |
| Frozen oracle, one account | 9 | 3 | 6 | 0 | +$3 | $2 |
| Last matured failed, one account | 323 | 159 | 157 | 7 | −$2 | $5 |
| All offered, three synchronized accounts | 1,860 | 870 | 954 | 36 | +$84 | $27 |

The negative LP result gives the public conditional player +$2 gross before
costs; one dependent path does not establish a systematic exploit. The three
accounts reuse identical outcomes. Peak liability is only $27 against $250k
hypothetical LP funding, so this schedule does not calibrate production capital
limits. Known unfunded winning debt peaks at $24 in that case. A separate
attachment check recomputes these maxima and minimum observed cash headroom
from the audited responses; it rejects a lower reported peak or unfunded state.

There are 18 analyzer-censored accepted stages in the one-account all-offered
case: native adjudication proves six additional losses and voids twelve. The
last-failed case has eleven such stages: four additional losses and seven
voids. These explain the change from paper LP +$22/−$6 under assumed refunds
to native +$28/−$2. Censoring was not silently replaced with a refund rule.

`scripts/audit_native_ppb.py` reexecutes every recorded native request/response, checks every original
receipt and selected quote opportunity, and separately reconciles terminal
cash. Completed cases can be audited separately with `--case NAME` while the
remaining cases run. An immutable case check binds its protocol, auditor,
binary, command audit, final state and result; changed bindings prevent reuse.
The full audit still requires every frozen profile and aggregate artifact.
This is a software cross-check, not an independent external review. The
consolidated packet at `.local/release-readiness/20261030-candidate-1-v7/`
binds the result, complete audit, current source snapshots and validation logs.
Do not restart primary execution in an existing or interrupted packet. An
interrupted auditor may resume by reusing only completed, source/input-bound
case checks, preserving its earlier logs. The user pause and resumed logs are
retained; this does not create new market observations.

## Reproduction

Build a new uniquely named `fuse-research` binary. Use its absolute path in
`FUSE_NATIVE_PPB_BINARY` and `FUSE_RELEASE_PRICING_BINARY` for the focused
Python suite. The full suite additionally needs the previously documented
retained capture/follow-up/economics fixture variables.

```sh
python3 -B scripts/research_adaptive_native_ppb.py declare \
  --output .local/release-native-ppb/your-unused-packet \
  --binary /absolute/path/to/new-fuse-research \
  --supplemental .local/capture-readiness/20261029-prospective-quote-economics-v1
python3 -B scripts/research_adaptive_native_ppb.py run \
  --output .local/release-native-ppb/your-unused-packet
python3 -B scripts/audit_native_ppb.py \
  --packet .local/release-native-ppb/your-unused-packet
```

Current-source changes during execution fail the final source check. Archived
evidence belongs to its immutable snapshot. The release-pricing attachment now
verifies that snapshot and explicitly reports differences from current source,
instead of relabeling an old audited formula as a check of new product code.
Strict current-source verification remains the default for executing a frozen
pricing protocol. Snapshot tampering still fails in either verification mode.
