# Adaptive quote selection and 2× economics — 29 October 2026

The archived adaptive quotes do **not** establish robust economics. Uniform
entry can look close to 48% while quote-time entry selection changes the payout
distribution. This probe evaluates the archived adaptive candidate family and
its earlier-fold fits, complementing the shipped-Brownian-policy reducer and
recovery studies. It changes no pricing model or live capture.

Evidence: `.local/adaptive-corridor/20261029-adaptive-quote-economics-v1/`.
Inputs: the previously audited `20261028-frozen-market-v2` quote tapes, selected
before the ongoing prospective capture. These dates and their pricing outcomes
were already inspected development data. This is not an independent holdout or
a prospective economics result.

## Fixed experiment

The probe consumes saved widths and labels without fitting or repricing. It
evaluates `market:priceable_open`, `retained_open` and `timing:priceable_open`
across all retained selection/later tapes. Raw and normalized sources, dates,
continuous operation and eight-hour restarts remain separate. Daily descriptive
sums below combine only three adjacent blocks of a single continuous day.
Earlier predictions use the archived expanding 14/17/20-date fits: January's
market model was fitted on fourteen preceding dates and August's on twenty.
September/October use the twenty-two-date fitted models frozen for the current
trial. Earlier-period results therefore describe historical transfer of the
candidate family; they are not an in-sample replay of today's twenty-two-date
model on its own training dates.

Thirteen rules are fixed before this economics replay: every offered entry;
frozen-only; nonfrozen-only; width at most ten ppm; width above ten ppm; one-ppm
minimum width; last matured opportunity survived; last matured opportunity
failed; last twelve matured opportunities have a strict survivor majority;
the corresponding strict failure majority; forecast floor at least 48%; floor
at least 53%; and floor below 48%. Every rule is reported. No rule, width,
coefficient, target or cost is optimized.

Width and activity are available before entry. Public opportunity labels mature
only at entry plus sixty seconds, including the thirty-second corridor and the
existing conservative thirty-second label delay. The history includes prior
offered opportunities whether this trader entered them or not. A continuous
trader carries history across reporting blocks; a restarted trader starts with
empty label history. The three floor-based rules are **internal forecast stress
diagnostics**; the product does not necessarily expose that signal to traders.

Each counterfactual ticket stakes one USDC and pays two USDC total on survival:
LP trading PnL is +1 for failure and −1 for survival. One and three synchronized
accounts are evaluated. Three accounts multiply the same path's gains and
losses; they do not provide three independent observations.

Selected censored entries remain in the placed-ticket denominator. The central
scenario assumes they are refunded, with zero trading PnL. Separate lower and
upper bounds assign every censored entry survival or failure. This refund
scenario is not an execution claim: the quote tape alone cannot determine every
native reducer outcome around an outage.

Illustrative total expenses are 0, 10, 50 and 100 basis points of placed stake,
including assumed-refunded tickets. They are **not measured reserve fees, gas,
operating costs or fee-on-profit accrual**. Actual reserve funding, admission,
Recovery limits, customer bankrolls, share NAV, liquidity and demand are outside
this uncapped quote-tape calculation. The separate native reducer studies retain
their funding/controller evidence and limitations.

## Primary candidate on raw continuous dates

Gross figures assume censored refunds, one account and one-USDC stakes. Positive
figures indicate LP gains; negative figures indicate LP losses and corresponding
customer gains. The full archive
retains all declared rules and controls; this table shows uniform entry and one
fixed quote-time activity rule across every raw date.

| UTC date | All offered: resolved survival | All offered: LP gross USDC | Frozen-only: resolved survival | Frozen-only: LP gross USDC |
| --- | ---: | ---: | ---: | ---: |
| 1 January | 50.00% (1,384/2,768) | 0 | 57.27% (575/1,004) | −146 |
| 1 August | 51.41% (1,422/2,766) | −78 | 60.18% (538/894) | −182 |
| 1 September | 48.04% (1,325/2,758) | +108 | 34.69% (17/49) | +15 |
| 1 October | 47.27% (1,309/2,769) | +151 | 40.82% (20/49) | +9 |

Uniform archived quote eligibility is 2,769–2,779 entries out of 2,880 per day.
This is historical single-feed research eligibility, not measured native live
quote availability. Uniform censored entries number 10, 10, 11 and 10;
frozen-only censored entries number 5, 5, 0 and 0, respectively. January's
frozen-only gross loss remains between **141 and 151 USDC** under either extreme
censored-outcome assignment; August's remains between **177 and 187 USDC**.
The negative results do not depend on refunding the unknown outcomes.

The same fixed rule “enter after the last matured public opportunity failed”
also illustrates selection sensitivity on September: 727 survivors among 1,434
resolved entries (50.70%), versus uniform entry's 48.04%. Its 1,438 placed entries
give **−20 USDC gross**, bounded by −24 to −16 under the four censored outcomes,
while uniform entry gives +108 USDC. With the illustrative 1% expense, its net
becomes −34.38 USDC. The rule gives +29, +33 and +11 USDC gross on January,
August and October. This is a development diagnostic across many declared rules,
not evidence of a universally profitable adversarial policy. Serial dependence
and strategy comparison preclude treating these proportions as independent
probability guarantees.

One-ppm selection loses 116 and 137 USDC gross on January and August, with 684
and 643 resolved entries. September has no such entries and October has only
one; those later outcomes do not validate the rule or the tail behavior.

## Calibration tolerance and economics

For a clean resolved 2× ticket with survival probability `p` and expense fraction
`c`, LP expected return per staked unit is `1 − 2p − c`. Exactly 48% gives 4%
gross margin. The provisional 43–53% diagnostic band spans **+14% to −6% gross**
before costs. Thus meeting that band is not sufficient to establish positive
economics. The band's interpretation and the frozen capture target are
unchanged by this observation.

The per-case `expected_margin_at_48_percent` and `break_even_survival` fields are
clean-ticket theoretical benchmarks. Where censored tickets are assumed refunded
but still charged expenses, the resolved-ticket break-even is lower:
`0.5 − expense_fraction × placed / (2 × resolved)`. `daily-report.json` provides
that adjusted value, and all case outputs retain actual expense calculations and
two-sided censoring bounds. For example, January's uniform gross zero becomes
−27.78 USDC at the illustrative 1% expense, before any other unmodeled costs.

## Verification and remaining work

The audit exactly recomputes **207,360 quote-time decisions** and **5,616
eight-hour cases**. It crosschecks **648** denominators/outcome counts against
the original audited pricing cells, verifies **432** complementary-strategy
partitions and **2,808** synchronized-account scaling pairs, and checks cash
conservation and both censoring bounds. Future-outcome/censorship mutations
leave every tested pre-maturity decision unchanged. The full Python suite
passes **379 tests with three existing optional skips**, including concurrent
unrelated asset-research tests.

The current BTC capture remains unchanged on its original 06:31 WITA deadline.
Only its receipt timestamps and process health were observed during this study.
The handoff metadata audit still finds 34 necessarily freshness-affected windows;
its best possible final healthy fraction is 96.46%, before agreement and other
quality checks. No live pricing outcome, new coefficient fit, or capture
extension was used.

The next requirement remains frozen-candidate evidence on a reliable new horizon,
followed by funded execution, actual fees/costs, strategy-dependent demand and LP
risk evaluation. This diagnostic strengthens the case against promoting the
current challenger on aggregate survival alone; it does not validate product
economics or complete the research goal.
