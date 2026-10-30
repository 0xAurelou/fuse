#!/usr/bin/env python3
"""Proposed 5%-operator, dynamic LP/FUSE economics. Offline research only."""
import argparse
from collections import deque
from dataclasses import asdict, dataclass, replace
import hashlib
import json
from pathlib import Path
import random
import statistics

from iterate_loss_rewards import InventoryReserve, Quoter, USDC, funded_policies, scenarios
from stress_loss_rewards import Stage

ROOT = Path(__file__).resolve().parent.parent


def ceildiv(n, d):
    return (n + d - 1) // d


@dataclass(frozen=True)
class Allocation:
    eligible: int
    distributable: int
    protocol: int
    backing: int
    lp_retained: int
    restoration_retained: int


def allocate(profit, equity, required, allowance, target, credit_bps=9000, mode='dynamic'):
    """One zero-exposure checkpoint, all values integer USDC units.

    Protocol: always floor(5% * distributable). LP/FUSE: variable, not a fixed
    percentage. Existing losses and capital protected below 2C are excluded.
    Dynamic backing aims for 3C LP equity and a funded reward-allowance target.
    """
    if min(profit, equity, required, allowance, target) < 0 or not 0 < credit_bps <= 10000:
        raise ValueError('invalid allocation input')
    if mode not in ('dynamic', 'fixed35'):
        raise ValueError('invalid mode')
    distributable = min(profit, max(0, equity - 2 * required))
    protocol = distributable * 500 // 10000
    if mode == 'fixed35':
        backing = distributable * 3500 // 10000
    else:
        shortfall = max(0, target - allowance)
        needed = ceildiv(shortfall * 10000, credit_bps)
        headroom = max(0, equity - protocol - 3 * required)
        backing = min(distributable - protocol, headroom, needed)
    retained = profit - protocol - backing
    result = Allocation(profit, distributable, protocol, backing, retained, profit - distributable)
    assert result.protocol + result.backing + result.lp_retained == profit
    assert protocol == distributable * 500 // 10000
    assert protocol + backing <= distributable
    if equity >= 2 * required:
        assert equity - protocol - backing >= 2 * required
    if mode == 'dynamic' and backing:
        assert equity - protocol - backing >= 3 * required
    return result


def run(s, mode='dynamic', runway=30):
    """Re-simulates admission with the changed LP economics, not a static replay.

    No LP share supply/capital flows: an equity HWM is equivalent to per-share
    loss recovery in this fixed-capital cohort. No old contract behavior claim.
    """
    policy = funded_policies()[1]
    reserve = InventoryReserve((policy.seed_usdc + s.reserve_usdc) * USDC, policy.mining_tokens)
    quotes = Quoter(policy, reserve)
    rng = random.Random(s.seed)
    wallets = [s.wallet_usdc * USDC] * s.traders
    lp = hwm = peak = s.lp_usdc * USDC
    protocol = funding = pnl_total = eligible_total = distributable_total = 0
    retained_total = rewards = accepted = rejected = offered = 0
    pending = []
    history = deque(maxlen=30)
    max_drawdown = 0
    timeline = []
    for day in range(s.days):
        for epoch in pending:
            reserve.claim(epoch)
        pending = []
        # Only prior matured, accepted trades set the standard-reward target.
        # The welcome promotion remains separately pre-funded.
        target = ceildiv(sum(history) * runway, len(history)) if history else 0
        day_stages, day_offers = [], []
        day_funding = day_credit = day_standard = day_ops = day_profit = 0
        for batch in range(6):
            common = rng.randrange(10000)
            order = list(range(s.traders))
            rng.shuffle(order)
            if day >= s.stop_day:
                order = []
            stages = []
            exposure = 0
            for j in range(batch * s.games_per_day // 6, (batch + 1) * s.games_per_day // 6):
                if not order:
                    break
                account = order[j % len(order)]
                stake = s.stake_usdc * USDC
                if wallets[account] < stake or 2 * (exposure + stake) + 100 * USDC > lp:
                    rejected += 1
                    continue
                exposure += stake
                offer = quotes.quote(account, stake)  # before examining outcome
                u = common if rng.randrange(10000) < s.correlation_bps else rng.randrange(10000)
                won = u < s.survival_bps
                if s.cluster_start <= day < s.cluster_start + s.cluster_days:
                    won = True
                farmer = account < s.traders * s.farmer_bps // 10000
                if farmer:
                    won = False
                duration = 30000 if won else s.farmer_duration if farmer else rng.randrange(1, 30000)
                stages.append(Stage(account, stake, won, duration))
                day_offers.append(offer)
                offered += int(offer is not None)
                day_standard += stake * policy.loss_bps // (90000 if won else 10000)
            pnl = 0
            for stage in stages:
                delta = stage.stake if stage.won else -stage.stake
                wallets[stage.account] += delta
                pnl -= delta
            lp += pnl
            pnl_total += pnl
            accepted += len(stages)
            required = max(100 * USDC, exposure + 100 * USDC)
            assert lp >= required
            eligible = max(0, lp - hwm)
            allocation = allocate(eligible, lp, required, quotes.earned_left + day_credit,
                                  target, policy.fee_budget_bps, mode)
            protocol += allocation.protocol
            day_ops += allocation.protocol
            eligible_total += eligible
            distributable_total += allocation.distributable
            retained_total += allocation.lp_retained
            day_profit += eligible
            funding += allocation.backing
            day_funding += allocation.backing
            # Count each funding transfer once in today's target calculation,
            # but do not make its allowance usable for new quotes until day end.
            day_credit += allocation.backing * policy.fee_budget_bps // 10000
            lp -= allocation.protocol + allocation.backing
            reserve.fund(allocation.backing)
            hwm = max(hwm, lp)  # retained capitalization profits are protected
            peak = max(peak, lp)
            max_drawdown = max(max_drawdown, (peak - lp) / peak)
            day_stages.extend(stages)
            assert lp + reserve.balance + reserve.paid + sum(wallets) + protocol == (
                s.lp_usdc + policy.seed_usdc + s.reserve_usdc + s.traders * s.wallet_usdc) * USDC
        promises, _ = quotes.settle(day_offers, day_stages)
        # Match each checkpoint's independently floor-rounded budget credit.
        quotes.earned_left += day_credit
        quotes.earned_credited += day_credit
        quotes.check()
        history.append(day_standard)
        if promises:
            epoch = reserve.open(penalty=0)
            for account in promises:
                amount = reserve.tokens[account]
                if amount:
                    reserve.request(epoch, account, amount)
            pending.append(epoch)
        rewards += sum(promises.values())
        reserve.check()
        timeline.append(dict(day=day + 1, eligible_profit_usdc_units=day_profit,
            protocol_usdc_units=day_ops, backing_usdc_units=day_funding,
            lp_equity_usdc_units=lp, allowance_usdc_units=quotes.earned_left,
            runway_target_usdc_units=target))
    for epoch in pending:
        reserve.claim(epoch)
    assert reserve.paid == rewards
    assert lp == s.lp_usdc * USDC + pnl_total - protocol - funding
    assert lp + reserve.balance + reserve.paid + sum(wallets) + protocol == (
        s.lp_usdc + policy.seed_usdc + s.reserve_usdc + s.traders * s.wallet_usdc) * USDC
    return dict(scenario=asdict(s), mode=mode, target_runway_days=runway,
        protocol_usdc_units=protocol, reserve_funded_usdc_units=funding,
        lp_final_usdc_units=lp, trading_pnl_usdc_units=pnl_total,
        eligible_profit_usdc_units=eligible_total, distributable_profit_usdc_units=distributable_total,
        new_hwm_profit_retained_usdc_units=retained_total, rewards_usdc_units=reserve.paid,
        reserve_final_usdc_units=reserve.balance, emitted_fuse_units=str(reserve.emitted),
        accepted=accepted, rejected=rejected, reward_coverage=offered / accepted if accepted else 0,
        lp_max_drawdown=max_drawdown, conservation_verified=True,
        timeline=timeline if s.seed == 20261029 else [])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seeds', type=int, default=4)
    parser.add_argument('--output', type=Path, default=ROOT / '.local/dynamic-profit-allocation/20261029')
    args = parser.parse_args()
    if args.seeds <= 0:
        parser.error('positive --seeds required')
    args.output.mkdir(parents=True, exist_ok=True)
    sources = [Path(__file__), ROOT / 'scripts/iterate_loss_rewards.py', ROOT / 'scripts/stress_loss_rewards.py']
    assumptions = dict(research_only=True, protocol_bps=500, seeds=args.seeds,
        allocation='Loss recovery and 2C protection precede distributable profit; protocol takes fixed 5%. '
                   'Dynamic backing tops up prior-observed standard reward runway, preserving target 3C LP equity. '
                   'LP retains the rest. Fixed35 control uses 5% operator / 35% backing / 60% LP.',
        scope='No LP deposits/exits or fee liabilities deferred; all permitted economic transfers assumed immediate. '
              'No contract execution, new pricing calibration, voluntary demand or future bids.',
        source_sha256={str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources})
    (args.output / 'experiment.json').write_text(json.dumps(assumptions, indent=2) + '\n')
    rows = []
    cases = scenarios() + [replace(scenarios()[0], name='low-capital-10k', lp_usdc=10000)]
    for case in cases:
        for seed in range(args.seeds):
            for mode, runway in (('fixed35', 30), ('dynamic', 30), ('dynamic', 60)):
                rows.append(run(replace(case, seed=20261029 + seed), mode, runway))
    (args.output / 'results.json').write_text(json.dumps(dict(assumptions=assumptions, results=rows), indent=2) + '\n')
    lines = ['# Fixed 5% protocol / dynamic LP and FUSE allocation', '',
             f'{len(rows)} synthetic evaluations. All conservation and accepted-quote checks passed.', '',
             '| Scenario | Mode / runway | Protocol USDC | LP final USDC | New backing USDC | Rewards paid USDC | Reward coverage |',
             '|---|---|---:|---:|---:|---:|---:|']
    for case in cases:
        for mode, runway in (('fixed35', 30), ('dynamic', 30), ('dynamic', 60)):
            group = [r for r in rows if r['scenario']['name'] == case.name and r['mode'] == mode and r['target_runway_days'] == runway]
            med = lambda key: statistics.median(r[key] for r in group)
            lines.append(f"| {case.name} | {mode} / {runway}d | {med('protocol_usdc_units') / USDC:,.2f} | "
                         f"{med('lp_final_usdc_units') / USDC:,.2f} | {med('reserve_funded_usdc_units') / USDC:,.2f} | "
                         f"{med('rewards_usdc_units') / USDC:,.2f} | {med('reward_coverage'):.1%} |")
    lines += ['', 'The 5% rate is checked per checkpoint against distributable profit. '
              'A ratio formed from aggregate median values need not equal 5%. '
              'No charge is taken on recovered drawdowns, deposits or protected retained profit. '
              'The runway uses only prior completed trading; funded quotes are not changed retrospectively. '
              'These results assume synthetic pricing and finite funded wallets, not measured demand or a launch approval.']
    (args.output / 'report.md').write_text('\n'.join(lines) + '\n')
    print(json.dumps(dict(evaluations=len(rows), report=str(args.output / 'report.md'))))


if __name__ == '__main__':
    main()
