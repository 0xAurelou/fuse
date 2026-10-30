#!/usr/bin/env python3
"""User-specified 7-10% pre-reward edge sensitivity; no pricing config edits."""
import argparse
from dataclasses import replace
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import statistics

from dynamic_profit_allocation import run
from stress_loss_rewards import Scenario, USDC

ROOT = Path(__file__).resolve().parent.parent
MULTIPLIERS = (2, 5, 10, 25, 50, 100, 250, 1000, 10000)


def economics(edge_bps, multiplier=2, loss_reward_bps=200):
    if not 0 <= edge_bps < 10000 or multiplier < 1 or not 0 <= loss_reward_bps <= 10000:
        raise ValueError('invalid economics')
    edge = Fraction(edge_bps, 10000)
    survival = (1 - edge) / multiplier
    rebate = Fraction(loss_reward_bps, 10000)
    rewards = rebate * ((1 - survival) + survival / 9)
    return dict(survival=survival, gross_house_edge=edge,
                expected_reward=rewards, effective_house_edge=edge - rewards,
                protocol_share_of_turnover=edge / 20)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seeds', type=int, default=4)
    parser.add_argument('--output', type=Path, default=ROOT / '.local/house-edge-stress/20261029')
    args = parser.parse_args()
    if args.seeds <= 0:
        parser.error('positive --seeds required')
    args.output.mkdir(parents=True, exist_ok=True)
    sources = [Path(__file__), ROOT / 'scripts/dynamic_profit_allocation.py',
               ROOT / 'scripts/iterate_loss_rewards.py', ROOT / 'scripts/stress_loss_rewards.py']
    assumptions = dict(research_only=True, edge_bps=(700, 850, 1000), seeds=args.seeds,
        source='User-specified 7-10% nominal edge, assumed BEFORE FUSE rewards; not independently measured.',
        pricing='2x total payout in simulations; survival=(1-edge)/2. Exact EV sensitivity also covers allowed multipliers.',
        protocol='5% of distributable new realized profit, with loss recovery and capital gates.',
        rewards='10% welcome / 2% standard loss-value quotes; wins one ninth; $25 welcome wallet cap, $10k global allowance.',
        capital='Separate $250k LP / $125k FUSE backing; $10k standard continuity allowance within backing.',
        behavior='Finite funded wallets, no customer topups, no reward recycling. Activity is assumed; no real retention inferred.',
        source_sha256={str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources})
    (args.output / 'experiment.json').write_text(json.dumps(assumptions, indent=2) + '\n')
    rows, ev = [], []
    for edge in assumptions['edge_bps']:
        for multiplier in MULTIPLIERS:
            for loss_bps in (200, 1000):
                calc = economics(edge, multiplier, loss_bps)
                ev.append(dict(edge_bps=edge, multiplier=multiplier, loss_reward_bps=loss_bps,
                               **{k:float(v) for k,v in calc.items()}))
        base = Scenario(survival_bps=(10000 - edge) // 2)
        cases = [replace(base, name='baseline'),
                 replace(base, name='higher-volume', traders=1000, games_per_day=1000),
                 replace(base, name='winner-cluster', cluster_start=30, cluster_days=10)]
        for case in cases:
            for seed in range(args.seeds):
                for mode in ('fixed35', 'dynamic'):
                    result = run(replace(case, seed=20261029 + seed), mode, 60)
                    result['assumed_house_edge_bps'] = edge
                    result['customer_trading_bankroll_remaining_usdc_units'] = (
                        case.traders * case.wallet_usdc * USDC - result['trading_pnl_usdc_units'])
                    assert result['customer_trading_bankroll_remaining_usdc_units'] >= 0
                    rows.append(result)
    payload = dict(assumptions=assumptions, results=rows, expected_values=ev)
    (args.output / 'results.json').write_text(json.dumps(payload, indent=2) + '\n')
    lines = ['# 7-10% pre-reward house edge', '',
             f'{len(rows)} synthetic allocation evaluations and {len(ev)} exact expected-value sensitivities. '
             'All conservation checks passed. No deployment or pricing configuration was changed.', '',
             '## Expected economics at 2x', '',
             '| Pre-reward edge | Survival | Standard reward / stake | Net edge after standard rewards | Net edge during welcome | Operator / turnover before costs |',
             '|---|---:|---:|---:|---:|---:|']
    for edge in assumptions['edge_bps']:
        standard, welcome = economics(edge), economics(edge, loss_reward_bps=1000)
        lines.append(f"| {edge / 100:.1f}% | {float(standard['survival']):.2%} | "
                     f"{float(standard['expected_reward']):.4%} | {float(standard['effective_house_edge']):.4%} | "
                     f"{float(welcome['effective_house_edge']):.4%} | {float(standard['protocol_share_of_turnover']):.3%} |")
    lines += ['', 'The operator/turnover column assumes all expected underwriting profit is distributable; '
              'actual HWM/capital gates and costs change realized income. Rewards use equal-stake outcome percentages '
              'without a duration penalty, at current USDC redemption value. Welcome is promotional and capped.', '',
              '## Dynamic 60-day allocation: four-seed medians', '',
              '| Scenario | Assumed edge | Accepted bets | LP gross trading profit USDC | Operator USDC | New backing USDC | Rewards USDC | Coverage |',
              '|---|---:|---:|---:|---:|---:|---:|---:|']
    for case in ('baseline', 'higher-volume', 'winner-cluster'):
        for edge in assumptions['edge_bps']:
            group = [x for x in rows if x['scenario']['name'] == case and x['assumed_house_edge_bps'] == edge and x['mode'] == 'dynamic']
            med = lambda k:statistics.median(x[k] for x in group)
            lines.append(f"| {case} | {edge / 100:.1f}% | {med('accepted'):,.0f} | "
                         f"{med('trading_pnl_usdc_units') / USDC:,.2f} | {med('protocol_usdc_units') / USDC:,.2f} | "
                         f"{med('reserve_funded_usdc_units') / USDC:,.2f} | {med('rewards_usdc_units') / USDC:,.2f} | "
                         f"{med('reward_coverage'):.1%} |")
    lines += ['', '## Welcome sensitivity across payout choices', '',
              '| Assumed edge | 2x player EV | 5x player EV | 10x player EV | 100x player EV | 10,000x player EV |',
              '|---|---:|---:|---:|---:|---:|']
    for edge in assumptions['edge_bps']:
        values = [-float(economics(edge, m, 1000)['effective_house_edge']) for m in (2,5,10,100,10000)]
        lines.append(f"| {edge / 100:.1f}% | " + ' | '.join(f'{v:+.4%}' for v in values) + ' |')
    lines += ['', 'A non-profitable 2x welcome bet does not establish that all high-multiplier welcome bets are '
              'negative EV. Where the capped promotion produces positive EV, bots and wallet splitting remain relevant. '
              'Exact EV sensitivities assume correctly calibrated probabilities and executable quoted payouts; '
              'they are not historical estimates or evidence of a profitable real strategy.', '',
              'Higher nominal edge improves margin but consumes a finite customer bankroll faster. Accepted-bet counts '
              'are mechanical bankroll/admission effects, not measured retention. The existing checked-in local/paper '
              'pricing defaults still specify 500 bps (5%); this study does not change them or establish that 7-10% '
              'has been realized in live markets. Full fixed35 controls, source hashes and every seed are retained in the JSON artifacts.']
    (args.output / 'report.md').write_text('\n'.join(lines) + '\n')
    print(json.dumps(dict(evaluations=len(rows), ev_cases=len(ev), report=str(args.output / 'report.md'))))


if __name__ == '__main__':
    main()
