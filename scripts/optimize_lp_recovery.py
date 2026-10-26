#!/usr/bin/env python3
"""Bounded LP recovery search with frozen, held-out synthetic validation."""
import argparse
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict, replace
import hashlib
import json
from pathlib import Path
import statistics

from lp_risk import DAY, RiskPolicy
from simulate_lp_incentives import ROOT, run
from simulate_lp_risk import environments


def candidates():
    result = []
    for pause in (750, 1000):
        for hours in (6, 24, 48):
            for initial, maximum in ((25, 0), (100, 0), (25, 100), (25, 200)):
                name = f'pause{pause}-cool{hours}h-probe{initial}-max{maximum}'
                if (pause, hours, initial, maximum) == (1000, 48, 25, 0):
                    name = 'baseline'
                result.append(RiskPolicy(name=name, pause_drawdown_bps=pause,
                                         hard_drawdown_bps=2000, resume_drawdown_bps=500,
                                         cooldown_seconds=hours * 3600, probe_loss_bps=initial,
                                         probe_max_loss_bps=maximum, probe_positive_batches=3,
                                         probe_step_gain_bps=10))
    return result


def metrics(result):
    s = result['scenario']
    episodes = result['nav_recovery_episodes']
    deficits = [q for q in episodes if q['first_deficit_at_seconds'] is not None]
    recovered = [q for q in deficits if q['nav_recovered_at_seconds'] is not None]
    delays = [(q['nav_recovered_at_seconds'] - q['first_deficit_at_seconds']) / DAY for q in recovered]
    # Never drop censored recoveries from an average or call a reopened vault
    # fully recovered. Each unrecovered episode receives the full horizon cost.
    penalized = delays + [s['days']] * (len(deficits) - len(recovered))
    risk = result['risk_controls']
    reopened = [q for q in risk['pause_episodes'] if q['reopened_at_seconds'] is not None]
    return {'environment': s['name'], 'seed': s['seed'], 'policy': s['risk_policy']['name'],
            'nav_deficit_episodes': len(deficits), 'nav_recovered_episodes': len(recovered),
            'nav_unrecovered_episodes': len(deficits) - len(recovered),
            'worst_nav_recovery_days': max(delays, default=None),
            'penalized_worst_days': max(penalized, default=0),
            'penalized_recovery_days': penalized,
            'reopen_delay_days': [(q['reopened_at_seconds'] - q['paused_at_seconds']) / DAY for q in reopened],
            'unreopened_pauses': len(risk['pause_episodes']) - len(reopened),
            'max_drawdown': result['max_share_drawdown'], 'accepted_stages': result['accepted_stages'],
            'overdue_pending_requests': result['overdue_pending_requests'],
            'oldest_pending_wait_days': result['oldest_pending_wait_days'],
            'payouts_funded': risk['accepted_payouts_funded'],
            'ledgers_conserved': result['conservation_verified'],
            'other_flow_floor_breaches': risk['other_flow_floor_breaches'],
            'external_underwriting_pnl_usdc_units': result['external_underwriting_pnl_usdc_units'],
            'external_withdrawals_usdc_units': result['external_withdrawals_usdc_units'],
            'post_bootstrap_retention': result['post_bootstrap_retention']}


def evaluate(job):
    case, keep_full, log = job
    result = run(case, keep_events=log)
    if not result['conservation_verified'] or not result['risk_controls']['accepted_payouts_funded']:
        raise ValueError('ledger or accepted payout failure')
    return {'scenario': asdict(case), 'metrics': metrics(result),
            'result': result if keep_full else None}


def execute(jobs, workers, label):
    results = []
    with ProcessPoolExecutor(max_workers=workers) as pool:
        for i, result in enumerate(pool.map(evaluate, jobs)):
            results.append(result)
            if (i + 1) % 8 == 0 or i + 1 == len(jobs):
                print(f'{label}: {i + 1}/{len(jobs)} trajectories', flush=True)
    return results


def rank(training, policies):
    baseline = {(r['metrics']['environment'], r['metrics']['seed']): r['metrics']
                for r in training if r['metrics']['policy'] == 'baseline'}
    ranked = []
    for policy in policies:
        rows = [r['metrics'] for r in training if r['metrics']['policy'] == policy.name]
        if not rows:
            continue
        steady = [r['accepted_stages'] / max(1, baseline[(r['environment'], r['seed'])]['accepted_stages'])
                  for r in rows if r['environment'] == 'funded-steady']
        delays = [value for r in rows for value in r['penalized_recovery_days']]
        unfinished = sum(r['nav_unrecovered_episodes'] for r in rows)
        dd = max(r['max_drawdown'] for r in rows)
        overdue = max(r['overdue_pending_requests'] for r in rows)
        feasible = (unfinished == 0 and dd <= .20 + 1e-12 and steady and min(steady) >= .8
                    and overdue == 0 and all(r['payouts_funded'] and r['ledgers_conserved'] for r in rows))
        ranked.append({'policy': asdict(policy), 'training_feasible': bool(feasible),
                       'unrecovered_episodes': unfinished, 'max_drawdown': dd,
                       'min_steady_throughput_vs_baseline': min(steady) if steady else None,
                       'worst_penalized_nav_recovery_days': max(delays, default=0),
                       'median_penalized_nav_recovery_days': statistics.median(delays) if delays else 0,
                       'max_overdue_requests': overdue})
    return sorted(ranked, key=lambda r: (not r['training_feasible'], r['unrecovered_episodes'],
                                        r['worst_penalized_nav_recovery_days'],
                                        r['median_penalized_nav_recovery_days'], r['max_drawdown'],
                                        r['policy']['probe_max_loss_bps']))


def validation_worlds(seed, days):
    worlds = environments(seed, days)
    cluster = next(world for world in worlds if world.name == 'cluster-10d')
    worlds += [replace(cluster, name='thin-edge-cluster', survival_bps=5400),
               replace(cluster, name='low-funded-cluster', daily_trader_inflow_usdc=15000,
                       games_per_day=300, batches_per_day=6),
               replace(cluster, name='no-demand-after-loss', demand_stops_day=40)]
    return worlds


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / '.local/lp-recovery-optimization')
    parser.add_argument('--days', type=int, default=180)
    parser.add_argument('--workers', type=int, default=2)
    parser.add_argument('--quick', action='store_true')
    args = parser.parse_args()
    if not (args.days >= 45 and 1 <= args.workers <= 4):
        parser.error('days must be >=45 and workers 1..4')
    policies = candidates()
    train_seeds, test_seeds = [20261026, 20261027], [20261126, 20261127, 20261128, 20261129]
    train_world_names = ('funded-steady', 'cluster-10d', 'repeated-clusters')
    if args.quick:
        policies = [p for p in policies if p.name == 'baseline' or
                    (p.cooldown_seconds == DAY and p.probe_max_loss_bps == 200)]
        train_seeds, test_seeds = train_seeds[:1], test_seeds[:1]
        train_world_names = train_world_names[:2]
    args.output.mkdir(parents=True, exist_ok=True)
    sources = ['scripts/lp_risk.py', 'scripts/simulate_lp_incentives.py',
               'scripts/simulate_lp_risk.py', 'scripts/simulate_tokenomics.py',
               'scripts/optimize_lp_recovery.py']
    manifest = {'research_only': True, 'method': 'Exhaustive comparison within a bounded 24-policy grid; not convex or global economic optimization.',
                'source_sha256': {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in sources},
                'training_seeds': train_seeds, 'held_out_seeds': test_seeds, 'days': args.days,
                'training_environments': train_world_names,
                'candidates': [asdict(p) for p in policies],
                'objective': 'Minimize worst then median time from first stress NAV deficit to exact pre-cluster peak recovery. Unrecovered deficits receive a full-horizon penalty. Reopening at 5% drawdown is a separate metric.',
                'constraints': {'hard_drawdown_bps': 2000, 'resume_drawdown_bps': 500,
                                'min_steady_throughput_vs_baseline': .8, 'max_overdue_requests': 0,
                                'all_training_deficits_recovered': True, 'all_accepted_payouts_funded': True},
                'adaptation': 'Start probe at 0.25%/24h gross loss. Double only after three positive settled probe batches AND 0.1% net NAV gain since the last step. Any negative settled NAV change returns to the base cap. Existing spent losses, prior NAV peaks and the 20% hard floor persist.',
                'scope': 'Synthetic conditional outcomes; no oracle pricing fit, debt haircut, new token price, rescue contribution, backend policy change or contract execution.'}
    (args.output / 'experiment.json').write_text(json.dumps(manifest, indent=2) + '\n')
    jobs = [(replace(world, risk_policy=p), False, False) for seed in train_seeds
            for world in environments(seed, args.days) if world.name in train_world_names for p in policies]
    training = execute(jobs, args.workers, 'Training')
    ranked = rank(training, policies)
    (args.output / 'training.json').write_text(json.dumps({'trajectories': training, 'ranking': ranked}, indent=2) + '\n')
    selected = [RiskPolicy(**r['policy']) for r in ranked[:2]]
    baseline = next(p for p in policies if p.name == 'baseline')
    if baseline not in selected:
        selected.append(baseline)
    selection = {'selected_from_training_only': ranked[0] if ranked[0]['training_feasible'] else None,
                 'evaluation_policies': [asdict(p) for p in selected],
                 'rule': 'Frozen before held-out execution. No reselection from held-out outcomes.',
                 'training_sha256': hashlib.sha256((args.output / 'training.json').read_bytes()).hexdigest(),
                 'experiment_sha256': hashlib.sha256((args.output / 'experiment.json').read_bytes()).hexdigest()}
    selection_path = args.output / 'selection.json'
    selection_path.write_text(json.dumps(selection, indent=2) + '\n')
    frozen = hashlib.sha256(selection_path.read_bytes()).hexdigest()
    jobs = []
    for seed in test_seeds:
        worlds = validation_worlds(seed, args.days)
        if args.quick:
            worlds = [w for w in worlds if w.name in ('funded-steady', 'cluster-10d', 'thin-edge-cluster', 'no-demand-after-loss')]
        for world in worlds:
            for policy in selected:
                jobs.append((replace(world, risk_policy=policy), True,
                             seed == test_seeds[0] and world.name == 'cluster-10d'))
    held_out = execute(jobs, args.workers, 'Held out')
    if hashlib.sha256(selection_path.read_bytes()).hexdigest() != frozen:
        raise ValueError('frozen selection changed during validation')
    for row in held_out:
        events = row['result'].pop('events')
        if events:
            path = args.output / f"cluster10-{row['metrics']['policy']}-events.jsonl"
            with path.open('w') as stream:
                for event in events:
                    stream.write(json.dumps(event) + '\n')
    output = {'experiment': manifest, 'selection': selection, 'selection_sha256': frozen,
              'held_out': held_out, 'economic_acceptance_established': False,
              'production_approved': False, 'contract_execution': False,
              'all_ledgers_conserved': all(row['metrics']['ledgers_conserved'] for row in held_out),
              'all_accepted_payouts_funded': all(row['metrics']['payouts_funded'] for row in held_out)}
    (args.output / 'held-out.json').write_text(json.dumps(output, indent=2) + '\n')
    lines = ['# LP recovery optimization', '',
             f'{len(training)} training trajectories; {len(held_out)} held-out trajectories; {args.days} days each.', '',
             'Candidates were frozen before held-out execution. Primary recovery means reaching the exact pre-cluster NAV peak, not merely reopening trading. All settings retain the 20% prospective drawdown floor and 5% reopening threshold.', '',
             '| Held-out environment | Policy | NAV deficits recovered | Worst completed recovery days | Worst drawdown | Max overdue requests |',
             '|---|---|---:|---:|---:|---:|']
    for world in dict.fromkeys(row['metrics']['environment'] for row in held_out):
        for policy in selected:
            rows = [row['metrics'] for row in held_out if row['metrics']['environment'] == world and row['metrics']['policy'] == policy.name]
            delays = [row['worst_nav_recovery_days'] for row in rows if row['worst_nav_recovery_days'] is not None]
            duration = f'{max(delays):.2f}' if delays else 'N/A'
            lines.append(f"| {world} | {policy.name} | {sum(r['nav_recovered_episodes'] for r in rows)}/{sum(r['nav_deficit_episodes'] for r in rows)} | {duration} | {max(r['max_drawdown'] for r in rows):.2%} | {max(r['overdue_pending_requests'] for r in rows)} |")
    lines += ['', 'All simulated ledgers conserved and accepted payouts remained funded.', '',
              'Held-out steady-market admission throughput relative to the baseline:', '',
              '| Policy | Minimum across held-out seeds | Median |', '|---|---:|---:|']
    steady = {(row['metrics']['seed'], row['metrics']['policy']): row['metrics']['accepted_stages']
              for row in held_out if row['metrics']['environment'] == 'funded-steady'}
    for policy in selected:
        ratios = [steady[(seed, policy.name)] / max(1, steady[(seed, 'baseline')]) for seed in test_seeds]
        lines.append(f'| {policy.name} | {min(ratios):.1%} | {statistics.median(ratios):.1%} |')
    lines += ['', 'Worst completed recovery excludes unfinished episodes; always read it alongside the recovered/total count. Unfinished episodes remain explicit in held-out.json and receive a horizon penalty in training.', '',
              'No-demand and external-shock cases are stress limits, not guaranteed recoveries. A pause/probe controller cannot create counterparty revenue or restore a breached hard floor without an actual source of funds.', '',
              'LPs who withdrew during drawdown crystallized their losses. Recovery of remaining share NAV does not reimburse those withdrawals. Inspect investor PnL, queue waits, admission throughput and retention as well as recovery duration.', '',
              'Policy names encode pause bps, cooldown hours, initial probe bps and adaptive maximum bps. max0 means a fixed probe. training.json records the full ranking; selection.json freezes the candidates; held-out.json retains full validation ledgers and metrics.', '',
              'Funded scenarios assume external trader cash; market paths and LP behavior are synthetic. This search neither validates real demand nor approves economic parameters or contract deployment.']
    (args.output / 'report.md').write_text('\n'.join(lines) + '\n')
    print(args.output / 'report.md')
    print(json.dumps({'training_trajectories': len(training), 'held_out_trajectories': len(held_out),
                      'training_feasible_candidate': selection['selected_from_training_only'] is not None,
                      'selected_policy': ranked[0]['policy']['name'] if ranked[0]['training_feasible'] else None,
                      'contract_execution': False}))


if __name__ == '__main__':
    main()
