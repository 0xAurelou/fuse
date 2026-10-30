# Native fixed-table compatibility with adaptive widths

The unchanged native single-stage product cannot represent every quote from
the frozen adaptive challenger through its existing integer-ppm fixed table.
It requires all nine preset multipliers and strictly decreasing positive
integer widths. With nine widths, the first (2x) width must therefore be at
least **9 ppm**. Adaptive **1–8 ppm** quotes cannot use this route unchanged.
Historical adaptive research already includes 1-ppm opportunities; no live
pricing outcomes were inspected to establish this compatibility constraint.

The retained software probe is
`.local/capture-readiness/20261029-adaptive-native-width-compatibility-v1/`.
It checks the exact previously tested fee-aware research binary, SHA-256
`cd97641a79f26f8945b90d6deab401c8305b47a15dba9fd06373a89bb6d55f8a`,
and all **82 isolated source files**. The active capture, current engine module
and frozen pricing model are unchanged. The probe uses native initialization
only and enters no quotes or trades.

| Native policy input | Actual result |
| --- | --- |
| Original nine-preset Brownian control | Accepted |
| Only 2x, fixed width 1 ppm | Rejected: all nine presets required |
| Nine fixed widths 8 through 0 ppm | Rejected: positive, strictly narrower widths required |
| Nine fixed widths 9 through 1 ppm | Accepted |
| Nine fixed widths all at 1 ppm | Rejected: strictly narrower widths required |

This is a limitation of the present **fixed-table interface**, not a theorem
that every adaptive pricing implementation is impossible. The native Brownian
interface has its own pricing rule; substituting its widths would change the
candidate being evaluated. Rounding adaptive quotes up to 9 ppm would also
change their outcomes and economics.

An exact funded adaptive replay therefore needs a separately implemented and
validated width interface with adequate resolution and explicit behavior for
the intended payout menu. Policy bounds, accepted terms, admission and
recovery accounting must remain auditable through that integration. No such
product or interface change was made by that retained 29 October probe.

The attempted adapter is preserved as a failed software experiment under
`.local/capture-readiness/20261029-adaptive-native-lp-smoke-v1/`, including its
source snapshot, native rejection audit and failure explanation. It stopped
at initialization before funding or quotes. The non-working development
entry point was removed. The subsequent five-case native boundary probe passes
all expected acceptance/rejection checks.

The separately frozen
[paper economics protocol](PROSPECTIVE_QUOTE_ECONOMICS_20261029.md) remains
unchanged and will evaluate the sealed quote tape after the original deadline.
It is not funded native LP validation. The native studies of shipped Brownian
presets remain evidence about that different pricing policy. This constraint
must be addressed before claiming that adaptive-width native economics or the
broader product economics have been validated.

## 30 October interface candidate

The current engine now adds a separate `multiplier_widths_ppb` table format,
with exact integer barriers and an explicit increasing subset of existing
presets. Every enabled market must use that format together; formula/PPM table
formats retain their previous menu requirements. Positive, bounded, strictly
decreasing PPB widths allow all nine presets with a first width of 1 ppm, and
allow an explicit 2x-only table without inventing eight unsupported quotes.
This supersedes the current-code compatibility gap, not the historical probe.

The [native integration candidate](NATIVE_PPB_INTEGRATION.md) describes the
source changes, tests and full retained-tape replay. Operator harness policy
updates inject exact sealed widths; a live adaptive pricing provider is still
absent. No model is fitted or approved by this interface change. In particular,
the retained adaptive trial remains a failed-quality 4%-target BTC 2x trial,
not evidence for a 7–10% release model or the other asset/payout combinations.
