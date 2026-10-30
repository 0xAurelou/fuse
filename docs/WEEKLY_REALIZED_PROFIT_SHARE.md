# Weekly realized profit sharing with loss carryforward

29 October 2026. The user selected **weekly net profit, carrying losses forward**. This is the current research candidate, replacing per-settlement fee crystallization in earlier studies. It is an offline specification and simulation; no contract, configuration, balances or deployment changed.

## Pricing and sharing are separate

| Quantity | Meaning | Used to pay the protocol? |
|---|---|---|
| 7–10% quoted house edge | Intended expected trading margin before FUSE rewards, dependent on correct pricing | No |
| Realized trading profit | Resolved stakes less total recognized payouts, including winnings owed but not yet claimed | Input to weekly accounting |
| Distributable new profit | Actual new profit after recovering carried losses and protecting required LP capital | Yes: fixed 5% |
| Remaining distributable profit | 95% after the protocol fee | Dynamic LP retention / FUSE backing |

For example, $10,000 of resolved stakes and $9,500 of total payout liabilities produce $500 of trading profit. With no carried loss or capital shortfall, the protocol receives **$25** and **$475** is allocated dynamically. A quoted 10% edge does not turn this actual $500 into $1,000 of revenue.

Here, “net” means net settled betting results across the week and after loss recovery. This research fee base precedes the LP/FUSE allocation; prefunded FUSE redemptions are tracked separately, not deducted again as betting payouts. Direct operating costs are not modeled. This is not a claim about bottom-line company earnings after expenses.

## Weekly close

1. Recognize completed bets and their full winning payout liabilities. Do not treat deposits, unresolved stake principal, LP contributions, FUSE backing or projected house margin as profit.
2. Net the entire week's positive and negative results. Pay no operator fee during the week.
3. Recover historical trading losses before recognizing a new fee base. The carryforward has no calendar reset.
4. Retain any new profit needed to protect the provisional **2× required capital** floor.
5. Pay the protocol **5% of the remaining distributable new profit**, rounded down in integer USDC units.
6. Allocate the remaining **95%** dynamically. Top up FUSE's standard reward allowance toward a **60-day target**, subject to **3× required capital** remaining in the LP. Retain the rest in LP equity.

The 60-day allowance target uses the latest 30 days of accepted, completed trading at the standard reward rate. Welcome rewards have a separate prefunded allowance. As in the earlier candidate, 90% of a new backing transfer becomes additional dollar quote allowance; this is a quote-budget parameter, not a fixed percentage split of profit. Token inventory also constrains quotes.

Already accepted reward offers use reserved capacity. Reward quotes and daily FUSE redemption windows continue between weekly closes. Newly funded backing becomes usable for new offers on the following day. No quote relies on profit that has not yet been earned.

The model conservatively uses the greatest accepted required-capital estimate during the week at its close, preventing a quiet final batch from freeing that estimate for distribution. The 2× / 3× multiples and historical exposure estimate are research parameters, not a validated risk engine or guarantee that starting LP principal is preserved.

## Carryforward examples

Within a single week, trading PnL of **+$10k, −$12k, +$2k** nets to zero, so the operator fee is zero. Paying after each of those steps could already have paid $500 at the first gain; weekly crystallization avoids that payment within this example's week.

Across weeks, assuming sufficient capital and no earlier profit mark:

| Week | Trading PnL | Loss still carried after close | New eligible profit | Protocol fee |
|---|---:|---:|---:|---:|
| 1 | −$1,000 | $1,000 | $0 | $0 |
| 2 | +$800 | $200 | $0 | $0 |
| 3 | +$500 | $0 | $300 | $15 |

In the fixed-capital model, this is tracked using cumulative settled trading PnL and its historical profit mark. The mark rises at each profitable weekly close, including profit retained for capitalization. Previously retained capitalization profit is not retrospectively taxed later. Prior reserve allocations are not counted as a new trading loss or charged twice.

**A weekly fee is final once earned.** A subsequent losing week does not claw it back; it creates loss carryforward that blocks new fees until recovered. Consequently, fees paid over many weeks can exceed 5% of the final cumulative trading profit. Weekly netting is not a single lifetime reconciliation.

## Offline checks and results

The new study contains **60 scenario controls**: three quoted edges, four random seeds, and five actual outcome/scenario combinations. Separate controls hold actual outcomes fixed while changing only the quoted edge label. They produce identical cash results and fees, confirming that the quote label is not booked as revenue. Repeated labels on the same actual path are controls, not independent market observations.

All paths use 180 trading days plus two explicit zero-trading runoff days, closing 26 full accounting weeks. Starting funds are $250k separate LP equity and $125k segregated USDC backing; the $10k welcome and $10k continuity allowances are subsets of that backing. Bets have $50 stakes and 2× total payouts. Baseline allows up to 300 bets/day across 300 funded wallets; higher volume uses 1,000. There is no new wallet funding, reward recycling, LP entry/exit or modeled customer retention response.

Medians across four calibrated baseline seeds:

| Nominal edge assumption | Actual settled trading PnL | Operator income over 180 trading days | Final LP equity | User reward value paid | Reward coverage |
|---|---:|---:|---:|---:|---:|
| 7% | $172,175 | $8,608.75 | $389,640.70 | $32,023.50 | 100% |
| 8.5% | $192,050 | $9,602.50 | $409,705.03 | $31,190.33 | 100% |
| 10% | $210,575 | $10,528.75 | $428,627.55 | $30,585.39 | 100% |

These are separate medians, not one reconstructed accounting path. Calibrated outcome probabilities are assumptions, not observed market pricing performance. The synthetic baseline operator income is only about $1.4k–$1.8k per 30 trading days, before expenses: the fixed 5% share does not itself establish a viable operating budget.

Higher-volume calibrated cases retained 100% reward coverage across the tested seeds. Winner-cluster scenarios produced median coverage of **55.8%, 64.8% and 74.7%** at 7%, 8.5% and 10% respectively. Weekly replenishment therefore does not guarantee continuous reward offers during drawdowns. Accepted offers remain funded; coverage measures which accepted bets could receive a quote, not a haircut to existing promises.

On the identical actual 0%-expected-margin controls, finite-sample median trading profit was $4,200 and operator payments $465, independent of the 7–10% quote label. Earlier profitable weeks followed by losses explain why that fee is not simply 5% of the final $4,200. Reward coverage was 62.0%.

On the actual −10%-expected-margin controls, median trading PnL was **−$249,525**, operator income **$0**, final LP equity **$475**, and reward coverage **43.2%**, regardless of the quoted edge. A nominal 10% target does not prevent underwriting losses. No FUSE backing was transferred back into the LP to cover them.

All 60 runs passed cash conservation, token inventory, funded quote and modeled capital checks. Eight weekly-accounting tests cover intraweek netting, cross-week recovery, finality of prior fees, capital protection and nominal-edge independence. Three recognition/timing tests and 47 preceding allocation/reward/edge tests also pass: **58 focused tests total**.

## Reproduction and implementation boundary

Run `python3 scripts/weekly_profit_share.py --seeds 4`. The output directory `.local/weekly-profit-share/20261029/` contains source hashes, assumptions, full weekly ledgers and the median report. The earlier `.local/realized-profit-stress/20261029/` holds 48 per-batch quote/outcome controls, explicitly labeled with their old fee timing; they are not weekly results.

Main sources are [weekly_profit_share.py](../scripts/weekly_profit_share.py), [test_weekly_profit_share.py](../scripts/test_weekly_profit_share.py), and the existing [dynamic allocation rule](../scripts/dynamic_profit_allocation.py).

Production implementation still needs a fixed weekly boundary, recognized liabilities for bets spanning that boundary, and LP share/capital-flow accounting that prevents deposit/withdrawal timing from resetting losses or avoiding accrued fees. Costs included in the fee base must also be specified. This fixed-capital, completed-outcome simulation does not implement those mechanisms or establish resistance to hedged/Sybil reward farming. It does not change existing supply allocations, contracts, launch settings or live payment rights.
