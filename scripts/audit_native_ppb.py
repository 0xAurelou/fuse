#!/usr/bin/env python3
"""Replay every native PPB audit response and independently reconcile cash.

Software verification only, not an external contract/pricing review. No network.
"""
import argparse
from collections import Counter
from copy import deepcopy
import gzip
import hashlib
import json
from pathlib import Path

from replay_lp_economics import Bridge, canonical


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda:f.read(1 << 20), b''):
            h.update(b)
    return h.hexdigest()


def read(path):
    return json.loads(Path(path).read_text())


def terminal_cash(state, initial_lp, customer_deposits):
    outcomes = Counter()
    lp_delta = turnover = 0
    for stage in state['stages'].values():
        status, terms = stage['status'], stage['terms']
        if status not in ('exploded','survived','voided') or terms['multiplier'] != 2 or terms['stake'] != 1_000_000 or terms['payout'] != 2_000_000:
            raise ValueError('unexpected terminal stage or payout')
        if terms.get('pricing_rule') != 'fixed-width-ppb-v1' or not 1_000 <= terms['width_ppb'] <= 50_000_000:
            raise ValueError('unexpected native pricing terms')
        if stage['funded']+stage['debt'] != terms['stake']:
            raise ValueError('stake funding mismatch')
        outcomes[status] += 1
        turnover += terms['stake']
        if status == 'exploded':
            lp_delta += terms['stake']
        elif status == 'survived':
            lp_delta -= terms['payout']-terms['stake']
    customers = sum(sum(a[k] for k in ('available','unfunded','earned_funded','earned_unfunded',
        'withdrawal_funded','withdrawal_unfunded','withdrawn')) for a in state['accounts'].values())
    if (customers-customer_deposits != -lp_delta or state['lp']-initial_lp != lp_delta
            or state['lp_profit'] != lp_delta or state['custody'] != customers
            or state['reserve'] != 0 or state['loss_clearing'] != 0):
        raise ValueError('independent cash reconciliation failed')
    return dict(lp_gross_pnl_usdc_units=lp_delta, trader_gross_pnl_usdc_units=-lp_delta,
                accepted_turnover_usdc_units=turnover, outcomes=dict(outcomes))


def audit_case(packet, plan, profile, receipts, quotes, decisions):
    name = profile['name']
    result = read(packet/(name+'-result.json'))
    state = read(packet/(name+'-state.json'))
    cash = terminal_cash(state, plan['initial_lp_usdc_units'],
        profile['accounts']*plan['customer_deposit_usdc_units'])
    if any(result[k] != v for k,v in cash.items()):
        raise ValueError('case output differs from independent cash')
    selected = {at for at, row in decisions.items() if profile['strategy'] in row['strategies']}
    accounts = {'trader-'+str(i) for i in range(profile['accounts'])}
    expected_attempts = {(at,owner) for at in selected for owner in accounts}
    seen_attempts = set()
    previous, count, oracle_index, init_count, snapshot_count = '', 0, 0, 0, 0
    seen_keys, ticks, settlements, deposits, acknowledgments = set(), set(), set(), set(), set()
    initial = read(packet/'initial-policy.json')
    current = deepcopy(initial)
    injection = 0
    bridge = Bridge(packet/'fuse-research')
    try:
        for line in (packet/(name+'-audit.jsonl')).open():
            row = json.loads(line)
            payload = {k:v for k,v in row.items() if k != 'hash'}
            if row['previous'] != previous or hashlib.sha256(canonical(payload).encode()).hexdigest() != row['hash']:
                raise ValueError('native audit chain changed')
            previous = row['hash']
            request = row['request']
            if request['kind'] == 'init':
                init_count += 1
                if count != 0 or request['policy'] != initial:
                    raise ValueError('unexpected initialization')
            elif request['kind'] == 'snapshot':
                snapshot_count += 1
                if row['response'].get('value') != state:
                    raise ValueError('final state differs from audited snapshot')
            elif request['kind'] == 'command':
                c = request['command']
                if c['key'] in seen_keys:
                    raise ValueError('duplicate command key')
                seen_keys.add(c['key'])
                kind, at = c['kind'], c['at']
                if kind == 'oracle':
                    original = receipts[oracle_index]
                    if (at, c['source'], c['raw']) != (original['at'],original['source'],original['raw']):
                        raise ValueError('oracle receipts changed, skipped or reordered')
                    oracle_index += 1
                elif kind == 'lp_fund':
                    if count != 1 or at != plan['start_ms'] or c['amount'] != plan['initial_lp_usdc_units']:
                        raise ValueError('unexpected LP funding')
                elif kind == 'deposit':
                    owner = c['actor']
                    if at != plan['start_ms'] or owner not in accounts or owner in deposits or c['amount'] != plan['customer_deposit_usdc_units'] or c['id'] != 'fund-'+owner.split('-')[-1]:
                        raise ValueError('unexpected customer funding')
                    deposits.add(owner)
                elif kind == 'ack_deposit':
                    if at != plan['start_ms'] or c['id'] in acknowledgments:
                        raise ValueError('unexpected deposit acknowledgment')
                    acknowledgments.add(c['id'])
                elif kind == 'quote':
                    key = at, c['actor']
                    if key not in expected_attempts or key in seen_attempts or c['amount'] != plan['stake_usdc_units'] or c['multiplier'] != 2:
                        raise ValueError('undeclared or repeated quote attempt')
                    # All receipt messages earlier than the action have already
                    # been consumed, and no same-time message can enter the quote.
                    if ((oracle_index and receipts[oracle_index-1]['at'] >= at)
                            or (oracle_index < len(receipts) and receipts[oracle_index]['at'] < at)):
                        raise ValueError('quote action reordered against receipt boundary')
                    seen_attempts.add(key)
                    quoted = quotes[at]
                    if current['model']['multiplier_widths_ppb']['2'] != quoted['width_ppm']*1000 or quoted['paused']:
                        raise ValueError('width differs from sealed pre-entry quote')
                    if row['response']['ok']:
                        terms = row['response']['value']['result']
                        delta = terms['entry_price']*quoted['width_ppm']//1_000_000
                        if (terms['width_ppb'] != quoted['width_ppm']*1000 or terms['lower'] != terms['entry_price']-delta or terms['upper'] != terms['entry_price']+delta):
                            raise ValueError('exact native barriers differ')
                elif kind == 'policy_update':
                    injection += 1
                    expected = deepcopy(current)
                    expected['version'] = expected['model']['version'] = 'sealed-adaptive-ppb-'+str(injection)
                    if at not in selected:
                        raise ValueError('model updated outside a selected entry')
                    expected['model']['multiplier_widths_ppb']['2'] = quotes[at]['width_ppm']*1000
                    if c['raw'] != expected:
                        raise ValueError('policy altered beyond exact sealed width injection')
                    current = expected
                elif kind == 'tick':
                    if at in ticks:
                        raise ValueError('duplicate grid/final tick')
                    ticks.add(at)
                elif kind == 'paper_settle':
                    if at in settlements:
                        raise ValueError('duplicate settlement')
                    settlements.add(at)
                elif kind != 'enter':
                    raise ValueError('undeclared native command')
            else:
                raise ValueError('undeclared bridge operation')
            actual = bridge.send(request, allow_reject=True)
            if actual != row['response']:
                raise ValueError('native response replay differs at record '+str(count))
            count += 1
            if count % 10000 == 0:
                print(json.dumps(dict(profile=name, native_audit_records_replayed=count)), flush=True)
    finally:
        bridge.close()
    start, end = plan['start_ms'], plan['start_ms']+plan['duration_ms']
    terminal = end+initial['void_delay_ms']
    expected_ticks = set(range(start,end,30_000)) | {end,terminal}
    expected_settlements = set(range(start+plan['settlement_interval_ms'],end,plan['settlement_interval_ms'])) | {terminal}
    if (init_count != 1 or snapshot_count != 1 or oracle_index != len(receipts) or seen_attempts != expected_attempts
            or ticks != expected_ticks or settlements != expected_settlements or deposits != accounts
            or acknowledgments != {'fund-'+str(i) for i in range(profile['accounts'])}
            or previous != result['audit_head'] or count != result['audit_records']
            or result['quote_attempts'] != len(expected_attempts) or result['intended_grid_entries'] != len(selected)
            or result['exact_width_policy_injections'] != injection):
        raise ValueError('native replay coverage or final audit binding incomplete')
    return dict(profile=name, all_records_reexecuted=count, all_original_receipts=oracle_index,
        selected_grid_entries=len(selected), quote_attempts=len(expected_attempts),
        independent_cash_verified=True, exact_barriers_verified=True)


def checked_case(packet, plan, profile, receipts, quotes, decisions):
    """Reuse only an immutable, input/source-bound completed case audit."""
    name = profile['name']
    path = packet/(name+'-audit-check.json')
    bindings = dict(protocol_sha256=sha(packet/'protocol.json'), auditor_sha256=sha(__file__),
        binary_sha256=sha(packet/'fuse-research'),
        files_sha256={name+suffix:sha(packet/(name+suffix))
                      for suffix in ('-audit.jsonl','-state.json','-result.json')})
    if path.exists():
        stored = read(path)
        if stored['bindings'] != bindings or stored['check']['profile'] != name:
            raise ValueError('completed native case audit binding changed; preserve evidence')
        return stored['check']
    check = audit_case(packet,plan,profile,receipts,quotes,decisions)
    with path.open('x') as f:
        json.dump(dict(bindings=bindings,check=check),f,indent=2); f.write('\n')
    return check


def audit_completed_case(packet, name):
    """Audit an already completed case while other frozen cases are running."""
    packet = Path(packet).resolve()
    plan = read(packet/'protocol.json')
    if sha(packet/'protocol.json') != read(packet/'freeze.json')['protocol_sha256']:
        raise ValueError('case protocol changed')
    profile = next((p for p in plan['profiles'] if p['name'] == name),None)
    if profile is None:
        raise ValueError('case outside frozen profile set')
    for filename,digest in (('fuse-research',plan['binary_sha256']),
                            ('initial-policy.json',plan['initial_policy_sha256'])):
        if sha(packet/filename) != digest:
            raise ValueError('case native binary/policy changed')
    trial = Path(plan['receipt_directory'])
    decision_path = Path(plan['supplemental_directory'])/'entry-decisions.jsonl.gz'
    for path,digest in ((trial/'receipts.jsonl',plan['receipts_sha256']),
                        (Path(plan['predictions']),plan['predictions_sha256']),
                        (decision_path,plan['decisions_sha256'])):
        if sha(path) != digest:
            raise ValueError('case input changed')
    receipts = [json.loads(line) for line in (trial/'receipts.jsonl').open()]
    with gzip.open(plan['predictions'],'rt') as f:
        quotes = {r['start']:r for line in f if (r:=json.loads(line))['mode'] == plan['mode'] and r['candidate'] == plan['primary_candidate']}
    with gzip.open(decision_path,'rt') as f:
        decisions = {r['start']:r for line in f if (r:=json.loads(line))['mode'] == plan['mode'] and r['candidate'] == plan['primary_candidate']}
    return checked_case(packet,plan,profile,receipts,quotes,decisions)


def audit(packet):
    packet = Path(packet).resolve()
    if (packet/'audit.json').exists():
        raise FileExistsError('preserve existing native audit')
    plan, result = read(packet/'protocol.json'), read(packet/'result.json')
    digest = sha(packet/'protocol.json')
    if (digest != read(packet/'freeze.json')['protocol_sha256'] or digest != result['protocol_sha256']
            or result['completed'] is not True or result['production_approved'] is not False
            or result['economics_validated'] is not False or result['collection_quality_met'] is not False):
        raise ValueError('native protocol or scope binding differs')
    for name,h in plan['source_sha256'].items():
        if sha(packet/'source'/name) != h:
            raise ValueError('native snapshot source changed')
    for name,h in result['artifacts_sha256'].items():
        if sha(packet/name) != h:
            raise ValueError('native artifact changed')
    if sha(packet/'fuse-research') != plan['binary_sha256']:
        raise ValueError('native binary changed')
    if sha(packet/'initial-policy.json') != plan['initial_policy_sha256']:
        raise ValueError('native initial policy changed')
    trial = Path(plan['receipt_directory'])
    if sha(trial/'receipts.jsonl') != plan['receipts_sha256'] or sha(plan['predictions']) != plan['predictions_sha256']:
        raise ValueError('original receipt or quote changed')
    decision_path = Path(plan['supplemental_directory'])/'entry-decisions.jsonl.gz'
    if sha(decision_path) != plan['decisions_sha256']:
        raise ValueError('original strategy decisions changed')
    receipts = [json.loads(line) for line in (trial/'receipts.jsonl').open()]
    with gzip.open(plan['predictions'],'rt') as f:
        quotes = {r['start']:r for line in f if (r:=json.loads(line))['mode'] == plan['mode'] and r['candidate'] == plan['primary_candidate']}
    with gzip.open(decision_path,'rt') as f:
        decisions = {r['start']:r for line in f if (r:=json.loads(line))['mode'] == plan['mode'] and r['candidate'] == plan['primary_candidate']}
    if len(result['results']) != 4 or plan['profiles'] != [r['profile'] for r in result['results']]:
        raise ValueError('native profile coverage changed')
    expected_artifacts = {p['name']+suffix for p in plan['profiles']
                          for suffix in ('-audit.jsonl','-state.json','-result.json')}
    if set(result['artifacts_sha256']) != expected_artifacts:
        raise ValueError('native artifact coverage incomplete')
    if any(r != read(packet/(r['profile']['name']+'-result.json')) for r in result['results']):
        raise ValueError('aggregate and individual native results differ')
    checks = [checked_case(packet,plan,p,receipts,quotes,decisions) for p in plan['profiles']]
    report = dict(passed=True, auditor_sha256=sha(__file__), protocol_sha256=digest,
        result_sha256=sha(packet/'result.json'), cases=checks,
        all_original_receipt_replays=sum(c['all_original_receipts'] for c in checks),
        all_native_responses_reexecuted=sum(c['all_records_reexecuted'] for c in checks),
        independent_external_review=False, production_approved=False, economics_validated=False)
    with (packet/'audit.json').open('x') as f:
        json.dump(report,f,indent=2); f.write('\n')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--packet',type=Path,required=True)
    parser.add_argument('--case',help='Audit one completed case without promoting the unfinished full grid')
    args = parser.parse_args()
    if args.case:
        print(json.dumps(audit_completed_case(args.packet,args.case)))
    else:
        r = audit(args.packet)
        print(json.dumps(dict(passed=r['passed'], native_responses_reexecuted=r['all_native_responses_reexecuted'], production_approved=False)))
