#!/usr/bin/env python3
"""Compare LP admission loss controls on matched synthetic market paths.

Research only: no contracts, wallets, RPC calls, policy deployment or pricing refit.
"""
import argparse
from dataclasses import asdict, replace
import hashlib
import json
from pathlib import Path
import statistics

from lp_risk import DAY, RiskPolicy
from simulate_lp_incentives import ROOT, Scenario, run


def policies():
    pause = dict(pause_drawdown_bps=1000, hard_drawdown_bps=2000,
                 resume_drawdown_bps=500, cooldown_seconds=2 * DAY)
    return [RiskPolicy(),
            RiskPolicy(name='24h-5pct', daily_loss_bps=500),
            RiskPolicy(name='24h-5pct-7d-10pct', daily_loss_bps=500, rolling_loss_bps=1000),
            RiskPolicy(name='pause-latched', probe_loss_bps=0, **pause),
            RiskPolicy(name='pause-probe', probe_loss_bps=25, **pause),
            RiskPolicy(name='combined', daily_loss_bps=500, rolling_loss_bps=1000, **pause),
            RiskPolicy(name='combined-tight', daily_loss_bps=250, rolling_loss_bps=500,
                       pause_drawdown_bps=500, hard_drawdown_bps=1000,
                       resume_drawdown_bps=200, cooldown_seconds=2 * DAY, probe_loss_bps=25)]


def environments(seed, days):
    base = Scenario(days=days, seed=seed, daily_log=True)
    funded = replace(base, games_per_day=3000, batches_per_day=12,
                     daily_trader_inflow_usdc=150_000, correlation_bps=0,
                     whitelist_day=1, public_day=7)
    return [replace(base, name='finite-wallets'),
            replace(funded, name='funded-steady'),
            replace(funded, name='cluster-3d', winner_cluster_days=tuple(range(30, 33))),
            replace(funded, name='cluster-10d', winner_cluster_days=tuple(range(30, 40))),
            replace(funded, name='repeated-clusters', winner_cluster_days=tuple(range(30, 33))
                    + tuple(range(60, 63)) + tuple(range(95, 98))),
            replace(funded, name='oracle-recovery', behavior='oracle-outage',
                    winner_cluster_days=tuple(range(35, 38))),
            replace(funded, name='incentive-demand-expiry', behavior='demand-collapse'),
            replace(funded, name='external-20pct-shock', behavior='drawdown')]


def compare(results):
    controls = {(r['scenario']['name'], r['scenario']['seed']): r for r in results
                if r['scenario']['risk_policy']['name'] == 'current'}
    rows = []
    for result in results:
        s = result['scenario']
        control = controls[(s['name'], s['seed'])]
        retention = result['post_bootstrap_retention']
        before = retention.get(str(s['bootstrap_days'] - 1), {})
        after30 = retention.get(str(s['bootstrap_days'] + 29), {})
        after90 = retention.get(str(s['bootstrap_days'] + 89), {})
        cohorts = before.get('bootstrap_owners', 0)
        risk = result['risk_controls']
        episodes = risk['pause_episodes']
        reopened = [q for q in episodes if q['reopened_at_seconds'] is not None]
        rows.append({'environment': s['name'], 'seed': s['seed'], 'policy': s['risk_policy']['name'],
                     'max_drawdown': result['max_share_drawdown'],
                     'final_lp_usdc_units': result['lp_final_usdc_units'],
                     'reserve_funded_usdc_units': result['reserve_funded_usdc_units'],
                     'accepted_stages': result['accepted_stages'],
                     'accepted_stages_vs_current': result['accepted_stages'] / control['accepted_stages'] if control['accepted_stages'] else None,
                     'payouts_funded': risk['accepted_payouts_funded'],
                     'admission_floor_breaches': 0,  # Guard raises on any such breach.
                     'other_flow_floor_breaches': risk['other_flow_floor_breaches'],
                     'risk_rejected_stages': sum(risk['rejected_stages_by_limit'].values()),
                     'pending_exit_owners': result['pending_lp_owners'],
                     'overdue_pending_requests': result['overdue_pending_requests'],
                     'longest_fulfilled_wait_days': result['longest_fulfilled_wait_days'],
                     'oldest_pending_wait_days': result['oldest_pending_wait_days'],
                     'queue_delayed_days': result['withdrawal_queue_delayed_days'],
                     'fulfilled_withdrawals': result['fulfilled_withdrawals'],
                     'external_lp_participants': result['participating_external_lps'],
                     'external_deposits_usdc_units': result['external_deposits_usdc_units'],
                     'external_withdrawals_usdc_units': result['external_withdrawals_usdc_units'],
                     'external_underwriting_pnl_usdc_units': result['external_underwriting_pnl_usdc_units'],
                     'lp_earned_fuse_units': result['lp_bootstrap_earned_fuse_units'],
                     'pause_episodes': len(episodes), 'reopened_episodes': len(reopened),
                     'unrecovered_episodes': len(episodes) - len(reopened),
                     'longest_recovery_days': max(((q['reopened_at_seconds'] - q['paused_at_seconds']) / DAY for q in reopened), default=None),
                     'terminal_mode': risk['mode'],
                     'lp_cohort_at_bootstrap_end': cohorts,
                     'retained_30d': after30.get('still_invested_owners') if after30 else None,
                     'retained_90d': after90.get('still_invested_owners') if after90 else None,
                     'unrequested_90d': after90.get('unrequested_owners') if after90 else None,
                     'invested_retention_90d': after90.get('still_invested_owners', 0) / cohorts if after90 and cohorts else None,
                     'unrequested_retention_90d': after90.get('unrequested_owners', 0) / cohorts if after90 and cohorts else None,
                     'cohort_equity_before_usdc_units': before.get('remaining_equity_usdc_units'),
                     'cohort_equity_after90_usdc_units': after90.get('remaining_equity_usdc_units')})
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / '.local/lp-risk-research')
    parser.add_argument('--seed', type=int, default=20261026)
    parser.add_argument('--seeds', type=int, default=3, help='consecutive matched seeds, 1..20')
    parser.add_argument('--days', type=int, default=180)
    parser.add_argument('--quick', action='store_true', help='first seed, three policies and four environments')
    args = parser.parse_args()
    if not (1 <= args.seeds <= 20 and args.days > 0):
        parser.error('invalid seed count or horizon')
    selected = policies()
    seeds = list(range(args.seed, args.seed + args.seeds))
    if args.quick:
        seeds, selected = seeds[:1], [selected[i] for i in (0, 4, 5)]
    cases = []
    for seed in seeds:
        worlds = environments(seed, args.days)
        if args.quick:
            worlds = [worlds[i] for i in (1, 3, 4, 6)]
        for world in worlds:
            cases.extend(replace(world, risk_policy=policy) for policy in selected)
    args.output.mkdir(parents=True, exist_ok=True)
    sources = ['scripts/lp_risk.py', 'scripts/simulate_lp_risk.py',
               'scripts/simulate_lp_incentives.py', 'scripts/simulate_tokenomics.py']
    manifest = {'research_only': True, 'seed_count': len(seeds),
                'source_sha256': {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in sources},
                'scenarios': [asdict(case) for case in cases],
                'comparison_rule': 'Same seed, environment, inflows and deterministic per-trade latent outcome draws; admission, wallet funding, LP behavior and later stage availability may change.',
                'loss_definition': 'Gross incremental LP debits to surviving positions, without offsetting losing-trader revenue. At-risk exposure reserved before outcomes. 24h/7d trailing windows, not midnight resets.',
                'loss_reference': 'Per-share NAV at/before each window start; conservatively rounded at 1e36 precision. Fair-NAV capital flows scale budgets and spent loss together and never reset them.',
                'recovery': 'Full pause for two days; 0.25%-of-reference-NAV rolling 24h gross-loss probe cap, subject to all normal loss limits and prospective hard drawdown headroom. Reopen at 5% drawdown, or 2% for tight policy. No peak/loss reset, rescue injection, or assumed successful recovery.',
                'floor_scope': 'New accepted underwriting only. An explicit external drawdown shock may cross the floor; report separately and fence new exposure.',
                'retention': 'Owners holding >=1 USDC of equity at day 89; count the same owners at days 119/179. Queued invested capital and unrequested capital reported separately. Missing cohorts/horizons are unavailable, not 0% retention.',
                'production_approved': False, 'contract_execution': False}
    (args.output / 'experiment.json').write_text(json.dumps(manifest, indent=2) + '\n')
    results = []
    for i, case in enumerate(cases):
        logged = case.seed == seeds[0] and case.name in ('cluster-10d', 'repeated-clusters', 'incentive-demand-expiry')
        result = run(case, keep_events=logged)
        if logged:
            path = args.output / f'{case.name}-{case.risk_policy.name}-events.jsonl'
            events = result['events'] + [{'kind': 'risk_mode_changed', **event}
                                         for event in result['risk_controls']['transitions']]
            def timestamp(event):
                if 'at_seconds' in event:
                    return event['at_seconds']
                end_of_day = event['kind'] in ('daily_accounting_verified', 'lp_rewards_earned', 'drawdown_stress')
                return (event['day'] + int(end_of_day)) * DAY
            with path.open('w') as stream:
                for event in sorted(events, key=timestamp):
                    stream.write(json.dumps(event) + '\n')
        result.pop('events')
        if not result['conservation_verified'] or not result['risk_controls']['accepted_payouts_funded']:
            raise ValueError(f'ledger or accepted payout failure: {case.name}/{case.risk_policy.name}')
        results.append(result)
        if (i + 1) % 8 == 0:
            print(f'Simulated {i + 1}/{len(cases)} matched risk trajectories', flush=True)
    comparisons = compare(results)
    report = {'manifest': manifest, 'comparisons': comparisons, 'results': results,
              'all_ledgers_conserved': True, 'all_accepted_payouts_funded': True,
              'economic_acceptance_established': False}
    (args.output / 'results.json').write_text(json.dumps(report, indent=2) + '\n')
    lines = ['# LP loss controls: matched simulation comparison', '',
             f'{len(results)} trajectories × {args.days} days; {len(seeds)} matched seeds. All USDC/FUSE/share ledgers conserved and accepted payouts funded. Research only; no contract execution.', '',
             'Budgets consume gross LP payments to winners. A profitable net batch cannot erase consumed risk budget. All limits apply before new acceptance; accepted outcomes settle normally.', '',
             '| Environment | Policy | Worst drawdown | Median stages vs current | Max overdue exits | Reopened / pause episodes |',
             '|---|---|---:|---:|---:|---:|']
    for world in dict.fromkeys(row['environment'] for row in comparisons):
        for policy in selected:
            rows = [row for row in comparisons if row['environment'] == world and row['policy'] == policy.name]
            volume = [row['accepted_stages_vs_current'] for row in rows if row['accepted_stages_vs_current'] is not None]
            fraction = f'{statistics.median(volume):.1%}' if volume else 'N/A'
            lines.append(f"| {world} | {policy.name} | {max(row['max_drawdown'] for row in rows):.3%} | {fraction} | {max(row['overdue_pending_requests'] for row in rows)} | {sum(row['reopened_episodes'] for row in rows)} / {sum(row['pause_episodes'] for row in rows)} |")
    lines += ['', 'Policy definitions:', '']
    lines.extend(f'- `{p.name}`: 24h loss {p.daily_loss_bps/100:.2f}%, {p.rolling_days}d loss {p.rolling_loss_bps/100:.2f}%, pause {p.pause_drawdown_bps/100:.2f}%, hard drawdown {p.hard_drawdown_bps/100:.2f}%, resume {p.resume_drawdown_bps/100:.2f}%, probe {p.probe_loss_bps/100:.2f}%. Zero limit disables that control; zero probe latches a triggered pause.' for p in selected)
    lines += ['', 'LP cohort after incentive expiry (first seed; invested includes queued capital):', '',
              '| Environment | Policy | Owners at day 89 | Invested day 119 | Invested day 179 | Unrequested day 179 |',
              '|---|---|---:|---:|---:|---:|']
    for row in comparisons:
        if row['seed'] == seeds[0] and row['environment'] in ('funded-steady', 'incentive-demand-expiry', 'cluster-10d'):
            fmt = lambda value: 'N/A' if value is None else str(value)
            lines.append(f"| {row['environment']} | {row['policy']} | {row['lp_cohort_at_bootstrap_end']} | {fmt(row['retained_30d'])} | {fmt(row['retained_90d'])} | {fmt(row['unrequested_90d'])} |")
    lines += ['', 'A hard drawdown floor constrains incremental underwriting losses, not a separate external balance shock. The external-20pct-shock cases deliberately test this limit. No accepted payout is canceled or reduced by a pause.', '',
              'A latched pause can preserve remaining capital while leaving trading permanently stopped. Probe recovery is conditional on profitable future trades; it is not guaranteed and cannot spend through the hard floor. Budgets and high-water marks never reset on resume or fair-NAV capital flows.', '',
              'Lower drawdown may come with sharply lower admission and underwriting demand. Compare matched throughput, queue waits, remaining cash claims and post-incentive LP retention; do not select parameters from drawdown alone.', '',
              'Funded environments assume $150k/day of external trader funding. Finite-wallet cases assume none. Bernoulli paths and LP demand responses are synthetic. These cases do not validate oracle pricing, public settlement, production economics or any contract implementation.', '',
              'experiment.json pins inputs and source hashes; results.json includes complete daily ledgers, pause episodes, retention and comparisons. The *-events.jsonl files contain first-seed stressed/expiry paths and risk transitions. Prior pricing candidates and LP research results are not overwritten.']
    (args.output / 'report.md').write_text('\n'.join(lines) + '\n')
    print(args.output / 'report.md')
    print(json.dumps({'trajectories': len(results), 'days': args.days,
                      'all_ledgers_conserved': True, 'all_accepted_payouts_funded': True,
                      'economic_acceptance_established': False, 'contract_execution': False}))


if __name__ == '__main__':
    main()
