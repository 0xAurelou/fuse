#!/usr/bin/env python3
"""Validate a predeclared, frozen pricing candidate against later live E2E evidence."""
import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import time
from decimal import Decimal

from analyze_papertrade import analyze
from calibrate_pricing import observations, survival, wilson, healthy_windows

ROOT = Path(__file__).resolve().parent.parent


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save_new(path, value):
    with path.open('x') as stream:
        json.dump(value, stream, indent=2)
        stream.write('\n')


def freeze_experiment(calibration, policy_path, directory, parameters):
    """Run before deployment or capture. Never refit or overwrite a candidate."""
    model = json.loads(calibration.read_text())
    policy = json.loads(policy_path.read_text())
    width = model['selected']['width_ppm']
    if policy['mode'] != 'local' or policy['model'].get('base_width_ppm') != width:
        raise ValueError('local policy must use the exact fitted candidate width')
    if any(policy['model'].get(key, 0) for key in ('base_width_bps', 'control_width_bps', 'volatility_factor')):
        raise ValueError('candidate must use only fractional fixed width')
    if model['selected']['target_survival'] != .48:
        raise ValueError('this experiment predeclares the 48% survival hypothesis')
    if parameters['control_every'] < 2 or parameters['capture_seconds'] < 60:
        raise ValueError('prospective experiment requires controls and at least 60 seconds of capture')
    cutoff = 0
    sources = []
    for source in model['dataset']:
        path = Path(source['path']).resolve()
        if digest(path / 'journal.jsonl') != source['sha256']:
            raise ValueError(f'fitted source journal changed: {path}')
        observed = observations(path)
        if observed:
            cutoff = max(cutoff, observed[-1][0])
        sources.append({'path': str(path), 'sha256': source['sha256']})
    now = int(time.time() * 1000)
    size = parameters['cohort_size'] or parameters['traders']
    horizon = max(parameters['capture_seconds'], ((parameters['traders']-1)//size)*parameters['cohort_interval_seconds']) + 720
    if cutoff >= now or policy['model']['valid_until'] <= now + horizon*1000:
        raise ValueError('candidate is stale, training is in the future, or validity ends during the experiment')
    directory.mkdir(parents=True, exist_ok=True)
    for src, name in ((calibration, 'frozen-calibration.json'), (policy_path, 'frozen-policy.json')):
        with (directory / name).open('xb') as stream:
            stream.write(src.read_bytes())
    manifest = {'version': 1, 'frozen_at_ms': now, 'training_cutoff_ms': cutoff,
                'calibration_sha256': digest(directory/'frozen-calibration.json'),
                'policy_sha256': digest(directory/'frozen-policy.json'), 'fit_sources': sources,
                'width_ppm': width, 'target_survival': .48, 'tolerance': .05,
                'minimum_nonoverlapping_windows': 400, 'minimum_coverage': .9,
                'maximum_void_fraction': .02, 'parameters': parameters,
                'production_approved': False,
                'rule': 'Fixed sample, no refitting or early success stopping. Nonoverlap does not eliminate serial dependence; Wilson intervals are descriptive.'}
    save_new(directory/'experiment.json', manifest)
    return manifest


def pricing_decision(successes, count, target=.48, tolerance=.05, minimum=400):
    interval = wilson(successes, count)
    if not count:
        return 'insufficient_evidence'
    low, high = target-tolerance, target+tolerance
    if interval[1] < low or interval[0] > high:
        return 'candidate_missed_target'
    if count < minimum:
        return 'insufficient_evidence'
    if interval[0] >= low and interval[1] <= high:
        return 'research_target_supported'
    return 'inconclusive'



def validate(experiment_path, directory):
    experiment_path, directory = experiment_path.resolve(), directory.resolve()
    spec = json.loads(experiment_path.read_text())
    root = experiment_path.parent
    if digest(root/'frozen-calibration.json') != spec['calibration_sha256'] or digest(root/'frozen-policy.json') != spec['policy_sha256']:
        raise ValueError('frozen candidate was changed')
    model = json.loads((root/'frozen-calibration.json').read_text())
    policy = json.loads((root/'frozen-policy.json').read_text())
    if model['selected']['width_ppm'] != spec['width_ppm'] or policy['model']['base_width_ppm'] != spec['width_ppm']:
        raise ValueError('frozen width does not match manifest')
    if directory != root/'evidence':
        raise ValueError('experiment must validate its own isolated evidence directory')
    summary = json.loads((directory/'summary.json').read_text())
    state = json.loads((directory/'final-state.json').read_text())
    tokenomics = json.loads((directory/'tokenomics.json').read_text())
    initial = json.loads((directory/'initial-policy.json').read_text())
    # The runner assigns local policy/model labels, preserving every numeric and
    # dataset parameter. Compare the full remaining objects, not just width.
    for item in (policy, initial):
        item.pop('version', None)
        item['model'].pop('version', None)
    if policy != initial:
        raise ValueError('executed policy differs from the frozen input')
    params = spec['parameters']
    expected_options = {'capture_duration_ns': params['capture_seconds']*10**9,
                        'cohort_size': params['cohort_size'],
                        'cohort_interval_ns': params['cohort_interval_seconds']*10**9,
                        'control_every': params['control_every']}
    if summary['trader_count'] != params['traders'] or summary['strategy_seed'] != params['seed'] or summary['simulation_options'] != expected_options:
        raise ValueError('executed population or timing differs from predeclared experiment')
    observed = observations(directory)
    if not observed or observed[0][0] <= max(spec['frozen_at_ms'], spec['training_cutoff_ms']):
        raise ValueError('capture is not strictly after candidate freeze and training')
    run_hash = digest(directory/'journal.jsonl')
    if run_hash in {source['sha256'] for source in spec['fit_sources']}:
        raise ValueError('prospective journal appears in fitted dataset')
    report = analyze(directory)  # Independently checks barriers, journal head and conservation.
    rows = healthy_windows(directory, initial, observed)
    possible = (observed[-1][0]-observed[0][0])//30000
    coverage = len(rows)/possible if possible else 0
    width = spec['width_ppm']
    successes = sum(row['max_move_units'] < row['entry']*width//1000000 for row in rows)
    cohorts = defaultdict(lambda: {'wallets': 0, 'controls': 0, 'trading_pnl_usdc_units': 0, 'outcomes': Counter()})
    groups = defaultdict(Counter)
    stage_index = defaultdict(Counter)
    for index, trader in enumerate(summary['traders']):
        expected_cohort = index//(params['cohort_size'] or params['traders'])+1
        if trader['cohort'] != expected_cohort:
            raise ValueError('wallet assigned to wrong cohort')
        is_control = index % params['control_every'] == 0
        if (trader['pricing_group'] == 'frozen-width-control') != is_control:
            raise ValueError('wallet control assignment changed')
        cohort = cohorts[str(trader['cohort'])]
        cohort['wallets'] += 1
        cohort['controls'] += int(is_control)
        cohort['trading_pnl_usdc_units'] += trader['pnl_usdc_units']
        if trader['status'] != 'complete':
            raise ValueError('wallet did not finish')
        for stage_id in trader['stage_ids']:
            stage = state['stages'][stage_id]
            accepted = state['policy_history'][stage['terms']['policy_version']]['model']
            expected_width = width if is_control else max(1, width*[60,75,85,90,95,100,105,110,125,150][index%10]//100)
            if accepted.get('base_width_ppm') != expected_width:
                raise ValueError('accepted stage width differs from predeclared profile')
            cohort['outcomes'][stage['status']] += 1
            groups[trader['pricing_group']][stage['status']] += 1
            if is_control:
                stage_index[str(stage['terms']['index'])][stage['status']] += 1
    rejects, unhealthy, snapshots, min_lp, min_buffer, gap = 0, 0, 0, summary['initial_lp_usdc_units'], summary['initial_lp_usdc_units'], 0
    queue_delays, retry_causes = [], Counter()
    for a, b in zip(observed, observed[1:]):
        gap = max(gap, b[0]-a[0])
    for line in (directory/'events.jsonl').open():
        event = json.loads(line)
        if event['kind'] == 'entry_retry':
            rejects += 1
            retry_causes[event['data']['error']] += 1
        if event['kind'] == 'entry_queue_wait':
            queue_delays.append(event['data']['delay_ms'])
        if event['kind'] == 'risk_snapshot':
            risk = event['data']; snapshots += 1
            unhealthy += int(not risk['healthy'])
            min_lp = min(min_lp, risk['lp_usdc_units'])
            min_buffer = min(min_buffer, risk['lp_usdc_units']-risk['exposure_usdc_units']-risk['lp_buffer_usdc_units'])
    outcomes = summary['outcomes']
    void_fraction = outcomes.get('void', outcomes.get('voided', 0))/max(1, sum(outcomes.values()))
    claims = [allocation for reward in state['local']['rewards'].values() for allocation in reward['allocations']]
    redemptions = list(state['local']['redemptions'].values())
    burned = sum(int(item['burned']) for item in redemptions)
    supply = int(tokenomics['supply_fuse_units'])
    checks = {'run_passed': summary['passed'], 'settlement_head_verified': summary['settlement_head_verified'],
              'postgres_replay_verified': summary['postgres_replay_verified'], 'zero_custody': summary['custody_usdc_units'] == 0,
              'zero_open_exposure': summary['exposure_usdc_units'] == 0,
              'supply_conserved': summary['usdc_total_supply_units'] == summary['usdc_sum_balances_units'],
              'all_local_operations_confirmed': all(op['status']=='confirmed' for op in state['local']['operations'].values()),
              'all_wallets_entered': all(trader['stage_ids'] for trader in summary['traders']),
              'capture_duration_met': observed[-1][0]-observed[0][0] >= params['capture_seconds']*1000,
              'oracle_window_coverage': coverage >= spec['minimum_coverage'],
              'void_fraction': void_fraction <= spec['maximum_void_fraction'],
              'ledger_capital_buffer_nonnegative': report['ledger_min_capital_buffer_usdc_units'] >= 0,
              'barriers_match': not report['barrier_mismatches'],
              'tokenomics_v2': tokenomics['tokenomics_controls_v2'],
              'treasury_locked': int(tokenomics['locked_escrows']['treasuryEscrow']) == 400000000*10**18,
              'fuse_supply_conserved': supply+burned == 1000000000*10**18,
              'emissions_capped': int(tokenomics['emissions']['totalClaimed']) <= int(tokenomics['emissions']['totalAllocated']) <= 600000000*10**18,
              'rewards_claimed': all(allocation['claimed'] for allocation in claims),
              'redemptions_paid': all(item['paid'] == item['accrued'] for item in redemptions),
              'reserve_reconciled': tokenomics['reserve_usdc_units'] == summary['reserve_usdc_units'] and tokenomics['unpaid_redemption_claims_usdc_units'] == 0}
    integrity = all(checks.values())
    decision = pricing_decision(successes, len(rows), spec['target_survival'], spec['tolerance'], spec['minimum_nonoverlapping_windows'])
    result = {'experiment_sha256': digest(experiment_path), 'journal_sha256': run_hash,
              'calibration_sha256': spec['calibration_sha256'], 'policy_sha256': spec['policy_sha256'],
              'run': str(directory),
              'frozen_width_ppm': width, 'target_survival': spec['target_survival'], 'tolerance': spec['tolerance'],
              'nonoverlapping_windows': len(rows), 'survived_windows': successes, 'base_width_survival': survival(rows, width),
              'descriptive_wilson_95pct_interval': wilson(successes, len(rows)),
              'minimum_windows': spec['minimum_nonoverlapping_windows'], 'pricing_decision': decision,
              'flat_oracle_windows': sum(row['max_move_units'] == 0 for row in rows),
              'window_outcomes': [{'start': row['start'], 'expiry': row['expiry'],
                                   'survived': row['max_move_units'] < row['entry']*width//1000000} for row in rows],
              'integration_passed': integrity, 'checks': checks, 'continue_local_e2e': integrity,
              'continue_unchanged_candidate_research': integrity and decision != 'candidate_missed_target',
              'production_approved': False, 'cohorts': dict(cohorts), 'pricing_groups': dict(groups),
              'economic_acceptance_established': False, 'empirical_organic_demand': False,
              'control_stage_index_outcomes': dict(stage_index), 'oracle_window_coverage': coverage,
              'stage_conditioned_pricing_validated': False,
              'continuation_scope': 'Local integration and further frozen-candidate observation only; conditional ladder survival and voluntary demand remain unvalidated.',
              'largest_paired_receipt_gap_ms': gap, 'entry_retries': rejects,
              'entry_retry_causes': dict(retry_causes),
              'entry_queue_max_delay_ms': max(queue_delays, default=0),
              'entry_queue_p95_delay_ms': sorted(queue_delays)[max(0, (len(queue_delays)*95+99)//100-1)] if queue_delays else None,
              'sampled_unhealthy_snapshots': unhealthy, 'risk_snapshots': snapshots,
              'sampled_lp_minimum_usdc_units': min_lp, 'sampled_capital_buffer_minimum_usdc_units': min_buffer,
              'ledger_lp_minimum_usdc_units': report['ledger_min_lp_usdc_units'],
              'ledger_capital_buffer_minimum_usdc_units': report['ledger_min_capital_buffer_usdc_units'],
              'ledger_peak_exposure_usdc_units': report['ledger_peak_exposure_usdc_units'],
              'final_lp_usdc_units': summary['final_lp_usdc_units'], 'lp_realized_pnl_usdc_units': summary['lp_realized_pnl_usdc_units'],
              'reserve_redemption_coverage': summary['reserve_redemption_coverage'], 'papertrade_analysis': report,
              'profit_hwm_usdc_units': tokenomics['profit_hwm_usdc_units'],
              'consumed_profit_usdc_units': tokenomics['consumed_profit_usdc_units'],
              'below_profit_hwm': tokenomics['realized_lp_profit_usdc_units'] < tokenomics['profit_hwm_usdc_units'],
              'reward_claims': len(claims), 'redemption_requests': len(redemptions),
              'redemption_paid_usdc_units': sum(item['paid'] for item in redemptions),
              'reserve_usdc_units': summary['reserve_usdc_units'],
              'gross_backing_usdc_per_fuse': str(Decimal(tokenomics['free_reserve_usdc_units'])*10**12/Decimal(supply)) if supply else None,
              'secondary_market_bid': tokenomics['secondary_market_bid'],
              'limits': 'Nonoverlapping windows still share a serially dependent BTC regime. Wallet/stage outcomes are correlated. Stage-conditioned counts are descriptive. Voluntary organic demand and long-term tokenomics viability remain unmeasured. A target miss is a research signal; passing this gate never approves public execution.'}
    return result


def aggregate(results):
    """Combine separately frozen runs of the same candidate, purging overlap."""
    if not results:
        raise ValueError('no prospective runs')
    keys = ('calibration_sha256', 'policy_sha256', 'frozen_width_ppm', 'target_survival', 'tolerance', 'minimum_windows')
    if any(any(result[key] != results[0][key] for key in keys) for result in results):
        raise ValueError('cannot combine different frozen candidates or gates')
    if len({result['journal_sha256'] for result in results}) != len(results):
        raise ValueError('duplicate prospective journal')
    retained, purged = [], 0
    for row in sorted((row for result in results for row in result['window_outcomes']), key=lambda row: (row['start'], row['expiry'])):
        if retained and row['start'] < retained[-1]['expiry']:
            purged += 1
        else:
            retained.append(row)
    successes = sum(row['survived'] for row in retained)
    first = results[0]
    decision = pricing_decision(successes, len(retained), first['target_survival'], first['tolerance'], first['minimum_windows'])
    integrity = all(result['integration_passed'] for result in results)
    return {'runs': results, 'calibration_sha256': first['calibration_sha256'], 'policy_sha256': first['policy_sha256'],
            'frozen_width_ppm': first['frozen_width_ppm'], 'target_survival': first['target_survival'], 'tolerance': first['tolerance'],
            'nonoverlapping_windows': len(retained), 'survived_windows': successes, 'purged_overlapping_windows': purged,
            'base_width_survival': successes/len(retained) if retained else None,
            'descriptive_wilson_95pct_interval': wilson(successes, len(retained)), 'minimum_windows': first['minimum_windows'],
            'integration_passed': integrity, 'pricing_decision': decision, 'continue_local_e2e': integrity,
            'continue_unchanged_candidate_research': integrity and decision != 'candidate_missed_target',
            'production_approved': False, 'economic_acceptance_established': False,
            'limits': first['limits']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--experiment', type=Path, help='single-run manifest; defaults to each run parent/experiment.json')
    parser.add_argument('--run', type=Path, nargs='+', required=True)
    parser.add_argument('--output', type=Path, help='required output directory when aggregating multiple frozen runs')
    args = parser.parse_args()
    if len(args.run) > 1:
        if args.experiment or args.output is None:
            parser.error('multiple runs use their own manifests and require --output')
        result = aggregate([validate(run.parent/'experiment.json', run) for run in args.run])
        args.output.mkdir(parents=True, exist_ok=True)
        (args.output/'prospective-validation.json').write_text(json.dumps(result, indent=2)+'\n')
        (args.output/'prospective-validation.md').write_text(
            '# Combined prospective validation\n\n'
            f"Integration passed: {result['integration_passed']}. Pricing: {result['pricing_decision']}. "
            f"Survived {result['survived_windows']}/{result['nonoverlapping_windows']} nonoverlapping windows; "
            f"95% descriptive interval {result['descriptive_wilson_95pct_interval']}; minimum {result['minimum_windows']}. "
            f"Purged overlapping windows: {result['purged_overlapping_windows']}.\n\n"
            + '\n'.join(f"- {run['run']}: {run['survived_windows']}/{run['nonoverlapping_windows']}, {run['pricing_decision']}" for run in result['runs'])
            + '\n\n'+result['limits']+'\n')
        print(args.output/'prospective-validation.md')
        if not result['integration_passed']:
            raise SystemExit('One or more prospective E2E runs failed integration gates')
        return
    run = args.run[0]
    result = validate(args.experiment or run.parent/'experiment.json', run)
    output = args.output or run
    output.mkdir(parents=True, exist_ok=True)
    (output/'prospective-validation.json').write_text(json.dumps(result, indent=2)+'\n')
    rate = 'unavailable' if result['base_width_survival'] is None else f"{result['base_width_survival']:.1%}"
    lines = ['# Prospective E2E decision', '',
             f"Local integration passed: **{result['integration_passed']}**. Pricing decision: **{result['pricing_decision']}**.", '',
             f"Frozen half-width {result['frozen_width_ppm']/100:.2f} bps; target 48% ±5 percentage points. {result['survived_windows']}/{result['nonoverlapping_windows']} nonoverlapping 30-second windows survived ({rate}). Descriptive Wilson 95% interval: {result['descriptive_wilson_95pct_interval']}. Minimum sample gate: {result['minimum_windows']} windows.", '',
             f"Continue local E2E: {result['continue_local_e2e']}. Continue the unchanged pricing candidate for further observation only: {result['continue_unchanged_candidate_research']}. Public execution approved: false.", '',
             '| Cohort | Wallets | Controls | Customer trading PnL USDC | Outcomes |', '|---:|---:|---:|---:|---|']
    for cohort, data in result['cohorts'].items():
        lines.append(f"| {cohort} | {data['wallets']} | {data['controls']} | {data['trading_pnl_usdc_units']/1e6:.6f} | {dict(data['outcomes'])} |")
    lines += ['', 'Exact-width control outcomes by ladder stage (correlated entries):', '',
              '| Stage | Survived | Breached | Voided | Observed survival among valid outcomes |',
              '|---:|---:|---:|---:|---:|']
    for index, counts in sorted(result['control_stage_index_outcomes'].items(), key=lambda item: int(item[0])):
        survived, breached, voided = counts.get('survived', 0), counts.get('exploded', 0), counts.get('voided', 0)
        rate = f'{survived/(survived+breached):.1%}' if survived+breached else 'unavailable'
        lines.append(f'| {index} | {survived} | {breached} | {voided} | {rate} |')
    lines += ['', 'The unconditional window estimate does not validate the conditional probability of surviving later stages. These entries share market paths and cannot be treated as independent trials. Stage-conditioned pricing still requires forward validation.']
    lines += ['', f"LP realized trading PnL: {result['lp_realized_pnl_usdc_units']/1e6:.6f} USDC. Final LP after any eligible reserve funding: {result['final_lp_usdc_units']/1e6:.6f} USDC. Realized-profit high-water mark: {result['profit_hwm_usdc_units']/1e6:.6f} USDC; below that mark: {result['below_profit_hwm']}. Positive profit below the prior peak remains in LP capital until recovery.", '',
              f"Oracle window coverage: {result['oracle_window_coverage']:.1%}. Flat oracle windows: {result['flat_oracle_windows']}/{result['nonoverlapping_windows']}; these survive any positive corridor and constrain attainable survival in this capture. Entry retries: {result['entry_retries']}. Reserve/redemption: {result['reserve_redemption_coverage']}.", '',
              f"Confirmed reward claims: {result['reward_claims']}; burn requests: {result['redemption_requests']}; paid redemption: {result['redemption_paid_usdc_units']/1e6:.6f} USDC. Reserve: {result['reserve_usdc_units']/1e6:.6f} USDC. Gross backing per outstanding FUSE: {result['gross_backing_usdc_per_fuse']} USDC. No secondary-market bid was supplied. These are actual local balances, not projected token prices.", '',
              'Checks: '+json.dumps(result['checks'], sort_keys=True), '', result['limits'], '',
              'All signed transactions execute on local Anvil chain 31337. Public HyperEVM inclusion and independent onchain oracle verification are outside this run.']
    (output/'prospective-validation.md').write_text('\n'.join(lines)+'\n')
    print(json.dumps({key: result[key] for key in ('integration_passed','pricing_decision','nonoverlapping_windows','survived_windows','base_width_survival','continue_local_e2e','continue_unchanged_candidate_research')}))
    print(output/'prospective-validation.md')
    if not result['integration_passed']:
        raise SystemExit('E2E integration/health gate failed; inspect retained evidence')


if __name__ == '__main__':
    main()
