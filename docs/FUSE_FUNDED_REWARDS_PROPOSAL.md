# FUSE funded rewards: a concrete launch candidate

29 October 2026. Research proposal, using the user's **$100k–$150k USDC backing budget**. The candidate uses $125k. Economics and quote accounting have been simulated; the product flow and accepted-quote enforcement described here are not implemented in the trading contracts or frontend.

**Profit-allocation amendment:** the current design candidate now uses [fixed 5% protocol income with a dynamic LP/FUSE split](DYNAMIC_PROFIT_ALLOCATION.md). That follow-up re-simulates 132 scenarios with the operator fee included. The fixed-35% figures below record the preceding reward-offer study; they have not been relabeled as results for the amended allocation.

**Pricing assumption update:** the user subsequently specified a 7–10% house edge. The [updated sensitivity study](HOUSE_EDGE_SENSITIVITY.md) treats that as pre-reward edge and adds 72 scenario evaluations. The 4% figures below remain historical; in particular, the 2x welcome bet is no longer positive player EV under the updated edge, although some higher-multiplier welcome bets still are.

**Current fee timing:** [weekly net realized profit with losses carried forward](WEEKLY_REALIZED_PROFIT_SHARE.md), as selected by the user. The protocol receives 5% of distributable new realized profit at weekly close; quoted house edge is not revenue. The preceding settlement-by-settlement allocation studies are historical comparisons. Rewards continue to use prefunded quotes and daily redemption windows.

## The player offer

**Choose your payout. Survive 30 seconds. Win USDC. Earn USDC-backed FUSE on completed bets, with larger rewards on losses. Redeem in daily windows or keep the tokens.**

Use dollar amounts on the ticket and receipt. Keep the 9:1 weighting as an internal rule:

| Reward regime | Losing $100 earns FUSE worth at least | Winning with $100 stake earns FUSE worth at least |
|---|---:|---:|
| Welcome offer, while eligible and funded | $10.00 | $1.111111 |
| Standard offer, while funded | $2.00 | $0.222222 |

Amounts refer to the intended minimum USDC redemption value under the accepted quote, not a secondary-market token price or a claim on LP equity. Winning USDC payouts are separate. A losing bet still loses its USDC stake. Welcome rewards are capped at **$25 per wallet** and **$10,000 of aggregate quoted value**. The global cap remains necessary because wallet caps do not prevent wallet splitting.

An example ticket for a $50, 2x round during the welcome offer:

```text
Stake                          50.00 USDC
If you survive                100.00 USDC total payout
FUSE reward if you survive       0.555555 USDC minimum redemption value
FUSE reward if you explode       5.00 USDC minimum redemption value
Welcome allowance remaining     25.00 USDC
Next redemption window          [actual onchain opening/closing times]
Claim available                 [actual onchain claim time]
```

The receipt shows FUSE earned, its accepted USDC minimum, current backing per FUSE, and the next claim time. A user can burn for the next available redemption or retain FUSE for exposure to future reserve backing. No APR, future appreciation, profitable play or recovery of the full loss is promised. Transfer fees, gas and supported claim costs must be reflected before an actual user confirms a claim.

Replace an unspecified future redemption opening with **published daily windows and 0% redemption penalty** for this candidate. Claims settle after their window closes. The research aggregates publication and requests daily; it does not establish an exact wall-clock withdrawal SLA. The product must show actual timestamps, including settlement/publication delays, instead of saying withdrawals are instant or always available within 24 hours.

## Funding and ownership

| Item | Candidate |
|---|---|
| Segregated starting USDC backing | $125,000 external funding |
| Welcome quote allowance | $10,000, within that initial backing |
| Standard-reward continuity allowance | $10,000, within that initial backing |
| Subsequent standard quote allowance | 90% of actually funded new reserve profits, usable from the next day |
| Token supply | Fixed 1B genesis; all outstanding escrows remain in the backing denominator |
| Trader inventory tested | Current 600M; separate 950M new-allocation counterfactual |
| Welcome token sublimit | 100M FUSE within trader inventory |
| Campaign horizon tested | 180 days |

The two $10k allowances are budgets for the current value of token rights released from escrow. They are subsets of the $125k backing, not two additional cash deposits. Token inventory and backing value constrain every quote; a USDC budget alone cannot justify issuing unavailable tokens. Unused budgets do not automatically transfer USDC out of the reserve.

Underwriting capital is separate. The comparison retains the previous study's assumed **$250k LP capital**, so the main test begins with **$375k combined LP plus backing capital**. The user's backing budget is not reused to fund accepted bets. No cash is transferred by this research.

Existing LP economics remain the source of new backing: loss recovery, capitalization and the high-water mark precede a maximum 35% allocation from eligible new profits. The 90% quote-allowance parameter applies to USDC already funded into the FUSE reserve; it does not raise that 35% maximum or take 90% of LP capital. Prior funding cannot be credited again.

That 35% limit describes the contracts and historical study. The [allocation amendment](DYNAMIC_PROFIT_ALLOCATION.md) proposes replacing the fixed backing share with a needs-based allocation after a fixed 5% operator cut of distributable realized profit, while preserving loss recovery and LP capital protection.

For a new deployment, prefer testing **95% player rewards / 5% external-LP incentives / 0% discretionary token treasury**. This would improve the community-allocation story against Papertrade. It does not create USDC, alter the 1B backing denominator, or increase the immediate dollar reward from a fixed quote. Founder funding and operating compensation would need a separate, explicit policy. Existing immutable allocations have not been changed; the 950M inventory is only a counterfactual in this study. Do not describe a preminted, escrowed fixed supply as having no premint.

## Why the reward rule changes

The earlier raw 9:1 rule multiplied stake by duration and a fixed token rate. It made immediate genuine losses earn almost nothing, and the USDC cost of a reward grew with backing per token.

The candidate quotes a bounded dollar value for a **completed, funded outcome**, independent of loss duration. For equal stakes, a loss quote is nine times its win quote, subject only to integer rounding. A $100 standard loss targets $2 of current redemption value whether existing backing is $100k, $125k or $100M. More valuable FUSE means fewer tokens are released, rather than a larger current-dollar subsidy.

Before seeing the outcome, the quoter reserves:

1. The full losing-outcome dollar amount from an already funded allowance.
2. The worst-case token quantity at current free backing per outstanding token.
3. Welcome wallet and campaign capacity, if the quote uses that offer.

Winning settlement returns unused capacity. New LP profit cannot finance an offer until it has actually reached the reserve. Unfunded, voided or expired entries must release their unused reservation. An accepted reward cannot be reduced because later bets exhausted a campaign budget. When new offers are unavailable, the ticket must disclose zero reward before entry; gameplay can continue with the stated payout and no reward offer.

The current contracts do not enforce these new reservations or accepted USDC minima. A live implementation needs an enforceable quote/claim design, reserved escrow inventory, confirmed settlement linkage, expiry and void handling, and published redemption windows. The offline Python quoter is an economic model of that behavior, not an onchain guarantee or a security assessment.

## What the iterations showed

The final study evaluates **eight configurations on 40 synthetic funded trading paths**: ten scenarios and four seeds. Including baseline hold-to-end controls, this produces **352 policy/timing evaluations**, plus **32 offset-pair bounds**. All integer USDC, token inventory, quote-reservation and redemption conservation checks pass. **31 focused tests** cover this work and the preceding stress model.

Baseline assumptions remain 300 wallets with $1,000 each, up to 300 $50 one-stage 2x bets daily, 48% survival, no customer topups and no recycling of redemption proceeds. This is a 4% assumed underwriting edge, not measured production pricing. No changes in retention or demand are assumed.

### Backing budget comparison

Medians across four seeds; candidate 2% standard / 10% welcome, $25 welcome cap, $10k standard continuity allowance, current 600M trader inventory:

| Starting backing | Baseline rewards paid | Baseline rewarded bets | Higher-volume rewarded bets | Higher-volume FUSE released |
|---|---:|---:|---:|---:|
| $100k | $33,254.61 | 100% | 95.4% | approximately 600M |
| $125k | $33,254.61 | 100% | 100% | approximately 537M |
| $150k | $33,254.61 | 100% | 100% | approximately 476M |

Higher volume means 1,000 funded wallets and up to 1,000 bets/day, retaining the same finite $1,000-per-wallet bankroll and 180-day horizon. It is a separate funded-population assumption, not evidence of growth. The $100k case's higher-volume reward coverage ranges from 88.8% to 97.6%; $125k and $150k cover every tested higher-volume bet. Higher backing reduces token consumption for the same current-dollar promise. **$125k is the working compromise**, with $150k providing more remaining inventory.

The $125k baseline median ends with approximately $127,991 of reserve USDC after paying rewards. About 235M FUSE have been released and burned through daily redemption. The matched earlier raw-score policy, given the same $125k seed, seeds and trading paths but its original duration scoring and 10% redemption penalty, pays a median **$6,262.79**. The revised offer pays approximately **5.3 times** as much USDC. That difference spends more existing token rights and removes the haircut; it is not extra LP profit or money created by changing a multiplier.

### Stress results for the candidate

| Scenario | Rewards paid, median | Rewarded bets, median | Implication |
|---|---:|---:|---|
| Baseline | $33,254.61 | 100% | All four seeds cover every baseline bet |
| No demand | $0 | No bets | Backing remains committed; no rewards are fabricated |
| Demand stops after day 30 | $10,445.78 | 100% of accepted bets | No assumed future activity funds previous promises |
| Ten-day winner cluster | $22,126.78 | 59.9% | Future offers stop as allowance depletes; accepted rewards remain honored |
| Negative underwriting edge | $16,705.50 | 43.3% | Subsidy budget cannot fix an LP losing money |
| 2% rather than 4% underwriting edge | $33,037.83 | 98.0% | The continuity allowance helps; funding is still conditional |
| Higher volume | $101,190.44 | 100% | Remaining 600M inventory is materially tighter |
| $100M historical starting reserve | $33,254.61 | 100% | Dollar-normalized issuance avoids the earlier backing-driven reward explosion |

In forced-loss cohort tests, 60 farmers lose their $60k bankroll and redeem a median $2,400, remaining **$57,600 cash-negative**. Immediate and late losses receive the same bounded current-dollar treatment. This tests pure losing, not all possible hedged strategies or LP ownership combinations.

The extra $10k standard continuity allowance raises winner-cluster coverage from approximately 27.1% to 59.9%, and weak-edge coverage from 65.8% to 98.0%, relative to the same quote model without it. It reduces interruptions; it does not provide unlimited rewards through an unprofitable regime.

Three-percent ongoing loss rewards look better in a baseline-only test, paying approximately $46,574.40, but higher-volume coverage falls to 71.0% and weak-edge coverage to 69.0%. Choose **2%** for the first candidate instead of optimizing the headline percentage on one baseline.

## The economic limit remains visible

At 48% survival and 2x payouts, a 2% loss reward plus one-ninth win reward costs an expected **1.1467% of stake**. The assumed 4% underwriting edge produces 1.4% of stake in reserve funding at the full 35% allocation; 90% of that is a 1.26% quote allowance. This supports the candidate's mean subsidy under the stated assumptions, before costs and temporal HWM effects. A 3% loss reward costs about 1.72%, above that recurring allowance.

The 10% welcome offer costs about 5.7333% of stake under the same outcome assumptions, making the welcome bet's expected result positive by about 1.7333% before costs. It is a **deliberately funded promotion**, not a sustainable permanent rate. At other survival probabilities and payouts, the expected subsidy changes. The $25 wallet cap and global quote budget bound initial issuance value, but do not establish that real users rather than bots will collect it.

A hypothetical zero-net-cost winning/losing pair earns gross-outcome rewards. Splitting it between wallets can also bypass wallet-level welcome concentration limits. These are assumed adversarial pairs, not demonstrated complementary FUSE tickets, but the tests prove that wallet caps and dollar normalization alone are not a hedge or Sybil defense. The current-value budget also does not cap what previously issued FUSE may redeem for after future backing growth. LP-share ownership can change an attacker's economic cost and needs separate review.

LP drawdown risk and operator/withdrawal dependencies remain separate from the reward offer. Positive current-value rewards cannot replace empirical quote calibration, funded demand, enforceable user exits or independent review.

## Positioning against Papertrade

Papertrade already rewards eligible losses with PAPER and offers staking participation in USDC revenue. Its documented issuance is community-oriented, without a team allocation. Those are existing strengths rather than new FUSE differentiators. [Paper emissions](https://docs.papertrade.xyz/learn/paper-emissions/), [staking dividends](https://docs.papertrade.xyz/learn/staking-dividends/).

FUSE should lead with **short rounds, a known winning payout, a visible dollar reward, and published redemption windows**. The proposed player can see the token's funded redemption benefit before entry, while retaining the choice to keep it. Community-first allocation would strengthen that story further. These are reasons to test the offer, not evidence that it will outperform Papertrade on returns or retention.

The next product experiment should compare the raw-token ticket with the dollar-quoted ticket using funded users and the same game pricing. Measure actual voluntary repeat play, incremental net contribution after rewards, net claim cost and how welcome rewards concentrate across linked activity. Cap the experiment's subsidy and token inventory in advance. Do not use recycled reward volume or token notional as proof of retention.

## Reproduction and artifacts

```sh
python3 -m unittest discover -s scripts -p 'test_loss_reward*.py'
python3 scripts/iterate_loss_rewards.py --profile funded --seeds 4
```

- `scripts/iterate_loss_rewards.py`: funded-value quote and reservation model.
- `scripts/test_loss_reward_iteration.py`: economic and quote lifecycle checks.
- `.local/loss-reward-iteration/20261029-funded-v3/experiment.json`: assumptions, policies and source hashes.
- `.local/loss-reward-iteration/20261029-funded-v3/results.json`: every policy, scenario, seed, hold control and hedge bound.
- `.local/loss-reward-iteration/20261029-funded-v3/report.md`: generated comparison tables.
- `.local/loss-reward-iteration/20261029-funded-v3/raw-score-control.json`: matched four-seed $125k control.
- Earlier $25k and unbuffered $100k–$150k iterations remain in adjacent output directories with copies of their exact model sources.

No contracts, live reward policies, allocations, redemption schedules or balances were changed. This is a concrete pilot specification and reproducible economic study; actual attractiveness and safe execution remain to be demonstrated.
