#!/usr/bin/env python3
"""Pricing/settlement/weekly profit sharing are separate research stages.

5% operator income only at weekly close, after loss carryforward and protected
capital. LP and FUSE allocations close weekly too; quotes use pre-funded money.
"""
import argparse
from collections import deque
from dataclasses import asdict, replace
import hashlib
import json
from pathlib import Path
import random
import statistics

from dynamic_profit_allocation import allocate, ceildiv
from iterate_loss_rewards import InventoryReserve, Quoter, funded_policies, USDC
from stress_loss_rewards import Scenario, Stage

ROOT = Path(__file__).resolve().parent.parent


class WeeklyProfitShare:
    def __init__(self):
        self.cumulative_pnl = self.profit_mark = self.week_pnl = 0
        self.protocol_paid = self.backing_funded = 0
        self.weeks = []

    def settle(self, pnl):
        # Called only with resolved betting PnL. Quote edge and expected margin
        # are intentionally absent from this API.
        self.week_pnl += pnl
        self.cumulative_pnl += pnl

    def close(self, equity, required, allowance, target, credit_bps=9000):
        eligible = max(0, self.cumulative_pnl - self.profit_mark)
        allocation = allocate(eligible, equity, required, allowance, target, credit_bps, 'dynamic')
        record = dict(week=len(self.weeks) + 1, week_trading_pnl_usdc_units=self.week_pnl,
            cumulative_trading_pnl_usdc_units=self.cumulative_pnl,
            prior_profit_mark_usdc_units=self.profit_mark,
            loss_carried_usdc_units=max(0, self.profit_mark - self.cumulative_pnl),
            distributable_profit_usdc_units=allocation.distributable,
            protocol_usdc_units=allocation.protocol, backing_usdc_units=allocation.backing,
            new_profit_retained_usdc_units=allocation.lp_retained,
            required_capital_usdc_units=required, allowance_target_usdc_units=target)
        self.protocol_paid += allocation.protocol
        self.backing_funded += allocation.backing
        # Protected retained profits cannot become a later retroactive fee base.
        self.profit_mark = max(self.profit_mark, self.cumulative_pnl)
        self.week_pnl = 0
        self.weeks.append(record)
        assert allocation.protocol == allocation.distributable * 500 // 10000
        return allocation


def simulate_weekly(quoted_edge_bps, actual_survival_bps, seed=20261029,
                    case='baseline', trading_days=180):
    if not 0 <= quoted_edge_bps < 10000 or not 0 <= actual_survival_bps <= 10000:
        raise ValueError('invalid quote or outcome probability')
    policy = funded_policies()[1]
    days = ceildiv(trading_days, 7) * 7
    s = Scenario(seed=seed, days=days, stop_day=trading_days, survival_bps=actual_survival_bps)
    if case == 'higher-volume':
        s = replace(s, traders=1000, games_per_day=1000)
    elif case == 'winner-cluster':
        s = replace(s, cluster_start=30, cluster_days=10)
    elif case == 'no-demand':
        s = replace(s, games_per_day=0)
    elif case != 'baseline':
        raise ValueError('invalid case')
    rng = random.Random(seed)
    reserve = InventoryReserve(policy.seed_usdc * USDC, policy.mining_tokens)
    quoter = Quoter(policy, reserve)
    shares = WeeklyProfitShare()
    lp = peak = s.lp_usdc * USDC
    wallets = [s.wallet_usdc * USDC] * s.traders
    history = deque(maxlen=30)
    week_required = 100 * USDC
    accepted = offered = rejected = reward_promises = 0
    max_drawdown = 0
    pending = []
    for day in range(days):
        for epoch in pending:
            reserve.claim(epoch)
        pending = []
        if day >= policy.days:
            quoter.closed = True
        stages, offers = [], []
        desired_standard = 0
        for batch in range(6):
            common = rng.randrange(10000)
            order = list(range(s.traders))
            rng.shuffle(order)
            if day >= s.stop_day:
                order = []
            batch_stages = []
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
                offers.append(quoter.quote(account, stake))
                u = common if rng.randrange(10000) < s.correlation_bps else rng.randrange(10000)
                won = u < s.survival_bps
                if s.cluster_start <= day < s.cluster_start + s.cluster_days:
                    won = True
                duration = 30000 if won else rng.randrange(1, 30000)
                stage = Stage(account, stake, won, duration)
                batch_stages.append(stage)
                desired_standard += stake * policy.loss_bps // (90000 if won else 10000)
            pnl = 0
            for stage in batch_stages:
                delta = stage.stake if stage.won else -stage.stake
                wallets[stage.account] += delta
                pnl -= delta
            lp += pnl
            shares.settle(pnl)
            required = max(100 * USDC, exposure + 100 * USDC)
            assert lp >= required
            week_required = max(week_required, required)
            stages.extend(batch_stages)
            accepted += len(batch_stages)
            peak = max(peak, lp)
            max_drawdown = max(max_drawdown, (peak - lp) / peak)
        offered += sum(o is not None for o in offers)
        if day < trading_days:
            history.append(desired_standard)
        target = ceildiv(sum(history) * 60, len(history)) if history else 0
        funding = 0
        if (day + 1) % 7 == 0:
            # All outcomes are now known. Account for unused quote reservations
            # that will return, without making any future revenue spendable.
            actual_standard = sum((o.win_value if t.won else o.loss_value)
                                  for o, t in zip(offers, stages) if o is not None and not o.launch)
            allowance_after_settlement = quoter.earned_left + quoter.held_earned - actual_standard
            allocation = shares.close(lp, week_required, allowance_after_settlement, target,
                                      policy.fee_budget_bps)
            lp -= allocation.protocol + allocation.backing
            funding = allocation.backing
            reserve.fund(funding)
            week_required = 100 * USDC
        promises, _ = quoter.settle(offers, stages)
        quoter.credit(funding)
        reward_promises += sum(promises.values())
        if promises:
            epoch = reserve.open(penalty=0)
            for account in promises:
                amount = reserve.tokens[account]
                if amount:
                    reserve.request(epoch, account, amount)
            pending.append(epoch)
        peak = max(peak, lp)
        max_drawdown = max(max_drawdown, (peak - lp) / peak)
        reserve.check()
        assert lp + reserve.balance + reserve.paid + sum(wallets) + shares.protocol_paid == (
            s.lp_usdc + policy.seed_usdc + s.traders * s.wallet_usdc) * USDC
    for epoch in pending:
        reserve.claim(epoch)
    assert reserve.paid == reward_promises
    assert len(shares.weeks) == days // 7
    assert lp == s.lp_usdc * USDC + shares.cumulative_pnl - shares.protocol_paid - shares.backing_funded
    turnover = accepted * s.stake_usdc * USDC
    return dict(quoted_house_edge_bps=quoted_edge_bps, actual_survival_bps_assumption=actual_survival_bps,
        case=case, seed=seed, trading_days=trading_days, accounting_days=days,
        nominal_expected_margin_usdc_units=turnover * quoted_edge_bps // 10000,
        nominal_expected_margin_booked_as_revenue=False,
        turnover_usdc_units=turnover, realized_trading_pnl_usdc_units=shares.cumulative_pnl,
        realized_trading_margin=shares.cumulative_pnl / turnover if turnover else None,
        protocol_usdc_units=shares.protocol_paid, new_backing_usdc_units=shares.backing_funded,
        lp_final_usdc_units=lp, rewards_usdc_units=reserve.paid, reserve_final_usdc_units=reserve.balance,
        accepted=accepted, rejected=rejected, reward_coverage=offered / accepted if accepted else 0,
        lp_max_drawdown=max_drawdown, emitted_fuse_units=str(reserve.emitted),
        weeks=shares.weeks, conservation_verified=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seeds', type=int, default=4)
    parser.add_argument('--output', type=Path, default=ROOT / '.local/weekly-profit-share/20261029')
    args = parser.parse_args()
    if args.seeds <= 0:
        parser.error('positive --seeds required')
    args.output.mkdir(parents=True, exist_ok=True)
    sources = [Path(__file__), ROOT / 'scripts/dynamic_profit_allocation.py',
               ROOT / 'scripts/iterate_loss_rewards.py', ROOT / 'scripts/stress_loss_rewards.py']
    assumption = dict(research_only=True, operator_bps=500, crystallization='weekly',
        loss_policy='Carry unrecovered losses forward without a calendar reset; no clawback of fees already earned in earlier weeks.',
        allocation='Close LP/FUSE profit allocation weekly after the 5% operator share; 60-day standard reward runway target.',
        recognition='Resolved trading PnL, including recognized winnings owed, drives profit. Quote edge is metadata, not booked revenue.',
        scope='180 trading days plus two zero-trading days close 26 full accounting weeks. No new market data '
              'is implied by runoff. No LP deposits/exits, direct costs, reward recycling or demand response assumed.',
        seeds=args.seeds, source_sha256={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sources})
    (args.output / 'experiment.json').write_text(json.dumps(assumption, indent=2) + '\n')
    rows = []
    for quoted in (700, 850, 1000):
        for seed in range(args.seeds):
            for case, actual in (('baseline',(10000 - quoted)//2), ('higher-volume',(10000 - quoted)//2),
                                 ('winner-cluster',(10000 - quoted)//2), ('baseline',5000), ('baseline',5500)):
                row = simulate_weekly(quoted, actual, 20261029 + seed, case)
                row['outcome_case'] = ('actual-breakeven' if actual == 5000 else
                                       'actual-negative10pct' if actual == 5500 else 'calibrated')
                rows.append(row)
    (args.output / 'results.json').write_text(json.dumps(dict(assumptions=assumption, results=rows), indent=2) + '\n')
    lines = ['# Weekly realized profit share, independently of quoted house edge', '',
             f'{len(rows)} quote/outcome scenario controls. Fixed 5% applies only to each completed week\'s '
             'distributable new profit after carryforward and capital protection. All conservation checks pass.', '',
             '| Quoted edge | Actual outcomes | Scenario | Realized trading PnL USDC | Operator paid USDC | LP final USDC | Rewards USDC | Reward coverage |',
             '|---|---|---|---:|---:|---:|---:|---:|']
    for quoted in (700,850,1000):
        for actualcase, case in (('calibrated','baseline'),('calibrated','higher-volume'),
                                 ('calibrated','winner-cluster'),('actual-breakeven','baseline'),
                                 ('actual-negative10pct','baseline')):
            group = [r for r in rows if r['quoted_house_edge_bps']==quoted and r['outcome_case']==actualcase and r['case']==case]
            med = lambda k:statistics.median(r[k] for r in group)
            lines.append(f"| {quoted / 100:.1f}% | {actualcase} | {case} | {med('realized_trading_pnl_usdc_units') / USDC:,.2f} | "
                         f"{med('protocol_usdc_units') / USDC:,.2f} | {med('lp_final_usdc_units') / USDC:,.2f} | "
                         f"{med('rewards_usdc_units') / USDC:,.2f} | {med('reward_coverage'):.1%} |")
    lines += ['', 'Quoted edges are distinct metadata for identical actual-breakeven or actual-loss paths. '
              'They produce identical fees. A 0% expected actual margin is not a promise of exactly zero '
              'realized profit in a finite sample. Fees earned in a profitable completed week are not '
              'refunded after later loss weeks; there are no new fees until the carryforward is recovered. '
              'Capital flows, unsettled positions crossing the accounting boundary, LP exits, actual costs '
              'and adversarial quote eligibility remain implementation/review work, not covered by this model.']
    (args.output / 'report.md').write_text('\n'.join(lines) + '\n')
    print(json.dumps(dict(evaluations=len(rows), report=str(args.output / 'report.md'))))


if __name__ == '__main__':
    main()
