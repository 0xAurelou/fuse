# Native capital controls — release candidate

30 October 2026 (WITA). **Implemented and locally tested, not calibrated or
production approved.** No deployed contract or current desk policy is changed.

The candidate's single-stage, physically custody-funded bets now have an opt-in
native capital rule, `funded-single-stage-capital-v1`. It adds a maximum net LP
liability per bet and an explicit aggregate exposure limit for every enabled
market. Existing global/account limits and the dollar LP buffer also apply.
Amounts below are six-decimal USDC atomic units, not floating-point dollars.

```json
{
  "capital": {
    "rule": "funded-single-stage-capital-v1",
    "max_bet_liability": 25000000000,
    "max_market_exposure": {
      "BTC": 100000000000,
      "ETH": 100000000000,
      "HYPE": 100000000000
    }
  }
}
```

This is an illustrative fragment, not a complete or approved policy. Every
enabled market needs exactly one positive limit no greater than the global
ceiling. The net per-bet ceiling must also fit within the global ceiling.
It is not a stake cap: at 10,000×, one $1 funded bet needs $9,999 of net LP
capacity. Pricing evidence is required separately for each enabled pair.

## Obligations and acceptance

For each market, native exposure is the sum of open/pending maximum payouts
less physically funded stakes, plus that market's known unfunded winning
entitlements. A winner moves between those categories without releasing its
reservation. Moving an entitlement into a user withdrawal does not remove its
market debt. Only confirmed settlement funding clears it; the current settlement
funds all outstanding native debt atomically, not a selected market's portion. The market totals
reconcile exactly to global exposure; no diversification or opposite-position
credit applies.

Quote creation checks all limits, then atomic acceptance rechecks current
funding, per-bet, market, account and global capacity. Quotes reserve no capacity.
Concurrent entries cannot rely on the same remaining market allowance. LP cash
already reserved for fees or exits is unavailable. Segregated backing, pending
deposits and unsettled customer losses cannot finance new risk.

This rule requires physically custody-funded stakes, matching the current
release reference. Unpaid winnings remain owed but must be funded before they
can finance another bet. Older policies retain their historical debt-backed
re-entry behavior; their journals did not preserve the originating market of
fungible debt and are not advertised as having these new market controls.

An existing journal can activate the rule only with zero exposure and no
unsettled customer-loss clearing balance. Activation cannot manufacture market
attribution for outstanding legacy obligations. Once activated, the rule cannot
be removed by policy update. A market with open bets or unpaid winnings cannot
be removed. Versioned limit changes invalidate unaccepted old quotes; accepted
terms and existing payouts survive tightening and betting pauses. A reduced
limit can prevent resume/new risk until obligations run off or are funded.
Increasing the LP admission buffer cannot exceed cash left after every accepted
open obligation and unpaid winner. The boundary test reproduces the earlier
settlement lock, rejects a buffer one atomic unit above available headroom,
and pays the existing winner during a pause with the exact safe buffer.
The internal finding and candidate fix are recorded in
[`native-capital-review.json`](release/native-capital-review.json). Legacy
policies retain their earlier behavior; production capital-moving contracts
still require reconciliation with these native controls.

Native invariants require the market winning-debt ledger to equal all unfunded
customer debt, and every open candidate stake to be fully custody-funded.
They also reconstruct each market's unpaid winnings from committed stage outcome
sequences after the last funded-outcome watermark. Correct aggregate debt cannot
conceal assignment to the wrong market. That outcome watermark stays the same
between a settlement plan and later confirmation of the same funding.
Failed durable commits leave visible reservations unchanged and fence the
writer; restart/replay and exact retries credit the winner once.
The failure test uses the in-memory test store; it is not a PostgreSQL crash drill.

## Local verification and loss envelope

Ten engine tests include all nine presets for BTC/ETH/HYPE, exact atomic-unit
per-bet boundaries, competing concurrent entries, withdrawal debt provenance,
tighter limits during pause, activation/downgrade guards, malformed attribution,
storage-failure recovery, settlement planning, buffer-update payout protection
and segregated-capital exclusions. Two API tests check
operator-only metrics and the transition from open risk to unpaid winnings to
confirmed funding.

The synthetic native stress uses these **unapproved example limits**:
$250k LP cash, $25k per-bet liability, $100k per-market liability, $200k global
liability and a $25k cash buffer. It attempts four batches of all 27 pairs at
$50 stakes, maintaining constant healthy prices so every accepted bet wins.
Earlier winnings remain unfunded during later batches.

Of 108 grid attempts, 73 are accepted, 24 fail the per-bet limit and 11 fail
global capacity. A final $200 2× ticket brings accepted bets to 74 and fills
the global ceiling exactly: $199,800 of earlier winning debt plus $200 of new
open liability. Further entry is refused despite the unchanged physical
$250k LP balance. All winners then settle during a betting pause. LP cash
ends at **$50k**, and every customer's funded cash is paid: **$309,110**,
including **$109,110** of original customer deposits. Final custody and debt
are zero; the complete journal replays to the same state.

These limits therefore permit an **80% LP loss** in this sequence. Paying every
obligation proves the tested hard funding constraint; it does not establish an
acceptable loss tolerance, margin, survival probability or calibrated limit.
The paths are synthetic and perfectly correlated, not new market observations.
No physical funding, token backing or production transactions are evidenced.

## Monitoring and reproduction

The existing operator-authenticated `/metrics` endpoint now exposes configured
per-bet/global/account/market ceilings, each market's total exposure and unpaid
winnings, LP cash available after reservations, and admission cash headroom.
New USDC metrics end in `_usdc_units` and use six-decimal atomic units. Headroom
is `LPAvailable - exposure - LPBuffer`; it may be negative after a tighter
policy and does not include remaining market/global allowance. Alert comparisons
must use those limits too. Asset labels are restricted to supported enabled
markets. Legacy policies report `fuse_capital_limits_enabled 0` and omit market
attribution metrics. Configured controls are not an approval signal.

```sh
cd engine
GOCACHE=/private/tmp/fuse-release-go-cache go test ./internal/engine -run '^TestCapital' -count=1 -v
GOCACHE=/private/tmp/fuse-release-go-cache go test -race ./internal/engine -run '^TestCapital' -count=1
GOCACHE=/private/tmp/fuse-release-go-cache go test ./internal/api -run '^TestCapital' -count=1 -v
GOCACHE=/private/tmp/fuse-release-go-cache go test ./...
```

The bounded legacy comparison matches 33 responses, state hashes and journal
hashes against the previous PPB binary, including every preset quote, a
10,000× win and full withdrawal/payment. It does not prove compatibility over
every historical command. The earlier eight-hour replay remains bound to its
original binary/source snapshot and did not enable this new capital rule.

## Remaining release work

Stress-supported economic limits, informed-player market calibration, the new
daily LP capital-account contract, free withdrawals, funded reward promises,
independent reviews, deployed permission checks and funded staging rehearsal
remain incomplete. The old contracts still contain provisional capital
multiples and the earlier LP exit queue. These native controls do not replace
those contracts or complete release gates 3/4/8/9. Known winning debt is now
reserved by market; daily fee/PnL attribution is a separate unfinished change.
