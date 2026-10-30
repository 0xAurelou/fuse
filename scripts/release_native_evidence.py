"""Bind the completed full native PPB replay without promoting its pricing scope."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
USDC = 1_000_000
PROFILES = (
    dict(name='all_one',strategy='all_offered',accounts=1),
    dict(name='frozen_one',strategy='frozen_only',accounts=1),
    dict(name='last_failed_one',strategy='last_matured_failed',accounts=1),
    dict(name='all_three',strategy='all_offered',accounts=3),
)


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda:f.read(1 << 20),b''):
            h.update(b)
    return h.hexdigest()


def read(path):
    return json.loads(Path(path).read_text())


def observed_capital(path, expected_records):
    """Recompute observed cash headroom from software-audited native responses.

    This paper replay has no local fee/exit reservations. These maxima describe
    this ticket schedule only; they are not a stress-calibrated capital limit.
    """
    peak_exposure = peak_debt = count = 0
    minimum_headroom = None
    funded = False
    with Path(path).open() as stream:
        for line in stream:
            row = json.loads(line)
            count += 1
            response = row['response']
            if row['request']['kind'] == 'snapshot' or not response['ok']:
                continue
            view = response['value']
            lp, exposure, debt = (view[k] for k in ('lp', 'exposure', 'debt'))
            if (any(type(n) is not int or n < 0 for n in (lp, exposure, debt))
                    or debt > exposure or exposure > lp):
                raise ValueError('native observed capital is unfunded or invalid')
            peak_exposure = max(peak_exposure, exposure)
            peak_debt = max(peak_debt, debt)
            funded |= row['request'].get('command', {}).get('kind') == 'lp_fund'
            if funded:
                headroom = lp - exposure
                minimum_headroom = headroom if minimum_headroom is None else min(minimum_headroom, headroom)
    if count != expected_records or minimum_headroom is None:
        raise ValueError('native observed capital coverage incomplete')
    return dict(peak_exposure_usdc_units=peak_exposure,
        peak_unfunded_debt_usdc_units=peak_debt,
        minimum_observed_cash_headroom_usdc_units=minimum_headroom,
        stress_calibrated=False)


def native_evidence(packet):
    packet = Path(packet).resolve()
    plan, result, audit = (read(packet/n) for n in ('protocol.json','result.json','audit.json'))
    protocol_hash = sha(packet/'protocol.json')
    if (protocol_hash != read(packet/'freeze.json')['protocol_sha256']
            or result['protocol_sha256'] != protocol_hash or audit['protocol_sha256'] != protocol_hash
            or audit['result_sha256'] != sha(packet/'result.json')
            or audit['auditor_sha256'] != sha(packet/'auditor-source.py')):
        raise ValueError('native evidence binding mismatch')
    required_sources = {'engine/internal/engine/types.go','engine/internal/engine/reducer.go',
                        'engine/internal/engine/pricing.go','engine/cmd/fuse-research/main.go',
                        'scripts/research_adaptive_native_ppb.py'}
    if not required_sources <= plan['source_sha256'].keys():
        raise ValueError('native core source bindings incomplete')
    for n,h in plan['source_sha256'].items():
        if sha(packet/'source'/n) != h:
            raise ValueError('native source snapshot changed')
    if sha(packet/'fuse-research') != plan['binary_sha256']:
        raise ValueError('native binary changed')
    required_false = ('collection_quality_met','live_adaptive_service_implemented',
        'release_7_to_10_percent_model','daily_fee_or_rewards_evaluated',
        'production_approved','economics_validated')
    if (result['completed'] is not True or result['actual_paired_reducer_admission'] is not True
            or result['funded_hypothetical_deposits'] is not True
            or any(result[k] is not False for k in required_false)
            or result['original_trial_state'] != 'failed' or plan['collection_quality_met'] is not False
            or plan['original_target_edge_bps'] != 400 or plan['multiplier'] != 2
            or audit['passed'] is not True or audit['independent_external_review'] is not False
            or audit['production_approved'] is not False or audit['economics_validated'] is not False):
        raise ValueError('native evidence scope changed')
    if plan['profiles'] != list(PROFILES) or [r['profile'] for r in result['results']] != list(PROFILES):
        raise ValueError('native profile grid incomplete')
    expected = {p['name']+suffix for p in PROFILES for suffix in ('-audit.jsonl','-state.json','-result.json')}
    if set(result['artifacts_sha256']) != expected:
        raise ValueError('native artifact grid incomplete')
    for name,h in result['artifacts_sha256'].items():
        if sha(packet/name) != h:
            raise ValueError('native artifact changed')
    if [c['profile'] for c in audit['cases']] != [p['name'] for p in PROFILES]:
        raise ValueError('native audit profile grid incomplete')
    total_receipts = total_records = 0
    capital = []
    for row, check in zip(result['results'],audit['cases']):
        name = row['profile']['name']
        if row != read(packet/(name+'-result.json')):
            raise ValueError('native individual result differs from aggregate')
        if (check['all_records_reexecuted'] != row['audit_records']
                or check['all_original_receipts'] != plan['receipt_count']
                or row['all_original_receipts'] != plan['receipt_count']
                or check['selected_grid_entries'] != row['intended_grid_entries']
                or check['quote_attempts'] != row['quote_attempts']
                or check['independent_cash_verified'] is not True or check['exact_barriers_verified'] is not True):
            raise ValueError('native audit coverage incomplete')
        observed = observed_capital(packet/(name+'-audit.jsonl'), row['audit_records'])
        if any(observed[k] != row[k] for k in ('peak_exposure_usdc_units', 'peak_unfunded_debt_usdc_units')):
            raise ValueError('native observed capital differs from summary')
        capital.append(dict(profile=name, **observed))
        state = read(packet/(name+'-state.json'))
        stages = list(state['stages'].values())
        if any(s['status'] not in ('survived','exploded','voided') or s['terms']['stake'] != USDC
               or s['terms']['payout'] != 2*USDC for s in stages):
            raise ValueError('native terminal scope changed')
        pnl = sum(USDC if s['status']=='exploded' else -USDC if s['status']=='survived' else 0 for s in stages)
        turnover = len(stages)*USDC
        if (len(stages) != row['accepted_stages'] or turnover != row['accepted_turnover_usdc_units']
                or pnl != row['lp_gross_pnl_usdc_units'] or pnl != state['lp_profit']
                or row['trader_gross_pnl_usdc_units'] != -pnl
                or state['lp'] != plan['initial_lp_usdc_units']+pnl
                or row['healthy_outcome_comparisons']+row['accepted_censored_path_stages'] != len(stages)):
            raise ValueError('native independent cash or denominator mismatch')
        costs = row['cost_sensitivity']
        if [c['cost_bps'] for c in costs] != [0,10,50,100]:
            raise ValueError('native cost grid incomplete')
        for c in costs:
            expense = turnover*c['cost_bps']//10_000
            if c['assumed_expense_usdc_units'] != expense or c['lp_gross_less_assumed_expense_usdc_units'] != pnl-expense:
                raise ValueError('native cost cash mismatch')
        total_receipts += check['all_original_receipts']
        total_records += check['all_records_reexecuted']
    if audit['all_original_receipt_replays'] != total_receipts or audit['all_native_responses_reexecuted'] != total_records:
        raise ValueError('native audit totals mismatch')
    changed = [n for n,h in plan['source_sha256'].items() if not (ROOT/n).exists() or sha(ROOT/n) != h]
    return dict(directory=str(packet),protocol_sha256=protocol_hash,result_sha256=sha(packet/'result.json'),
        audit_sha256=sha(packet/'audit.json'),auditor_sha256=audit['auditor_sha256'],
        native_binary_sha256=plan['binary_sha256'],audited_sources_sha256=plan['source_sha256'],
        changed_current_sources=changed,current_engine_sources_match=not any(n.startswith('engine/') for n in changed),
        original_trial_state='failed',collection_quality_met=False,original_target_edge_bps=400,
        actual_paired_reducer_admission=True,funded_hypothetical_deposits=True,
        all_original_receipt_replays=total_receipts,all_native_responses_reexecuted=total_records,
        independent_cash_cases=4,cost_checks=16,cases=result['results'],observed_capital=capital,
        live_adaptive_service_implemented=False,release_7_to_10_percent_model=False,
        daily_fee_or_rewards_evaluated=False,independent_external_review=False,
        production_approved=False,economics_validated=False)
