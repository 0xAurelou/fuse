#!/usr/bin/env python3
"""Funded, exact-width reducer replay of the sealed BTC 2x adaptive tape.

This is retrospective integration evidence on a failed-quality 4%-target trial,
not new pricing, the 7--10% release model, voluntary demand or deployed money.
"""
import argparse
from collections import Counter
from copy import deepcopy
import gzip
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

from analyze_capture import windows
from release_evidence import pricing_evidence
from replay_lp_economics import Bridge

ROOT = Path(__file__).resolve().parent.parent
USDC = 1_000_000
GRID = 30_000
PROFILES = (
    dict(name='all_one', strategy='all_offered', accounts=1),
    dict(name='frozen_one', strategy='frozen_only', accounts=1),
    dict(name='last_failed_one', strategy='last_matured_failed', accounts=1),
    dict(name='all_three', strategy='all_offered', accounts=3),
)
SOURCES = ('scripts/research_adaptive_native_ppb.py', 'scripts/analyze_capture.py',
           'scripts/test_release_native_ppb.py',
           'scripts/replay_lp_economics.py', 'scripts/release_evidence.py',
           'scripts/release_accounting.py', 'scripts/release_lp_bootstrap.py',
           'scripts/contract_lp_model.py', 'scripts/calibrate_pricing.py',
           'engine/go.mod', 'engine/go.sum')


def sha(path):
    result = hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            result.update(chunk)
    return result.hexdigest()


def read(path):
    return json.loads(Path(path).read_text())


def write(path, data):
    with Path(path).open('x') as f:
        json.dump(data, f, indent=2, allow_nan=False)
        f.write('\n')


def fixed_policy(source):
    p = deepcopy(source)
    p.pop('markets', None)
    p.pop('recovery', None)
    p['multipliers'] = [2]
    p['version'] = p['model']['version'] = 'sealed-adaptive-ppb-initial-v1'
    p['model'].pop('dnt', None)
    p['model'].pop('multiplier_widths_ppm', None)
    p['model']['multiplier_widths_ppb'] = {'2': 1000}
    p['model']['dataset'] = 'Sealed BTC 2x adaptive tape; exact harness width injection, no coefficient fitting'
    p['model']['out_of_sample_error'] = 'Original trial failed quality; no production pricing validated'
    return p


def source_files():
    return sorted(set(SOURCES) | {str(p.relative_to(ROOT))
        for folder in ('engine/internal/engine', 'engine/cmd/fuse-research')
        for p in (ROOT/folder).glob('*.go')})


def declare(output, binary, supplemental):
    output, binary, supplemental = (Path(p).resolve() for p in (output, binary, supplemental))
    if output.exists():
        raise FileExistsError('preserve existing native replay')
    binding = pricing_evidence(supplemental)
    protocol = read(supplemental/'protocol.json')
    trial = Path(protocol['original_directory'])
    if (trial/'SYNTHETIC_FIXTURE.json').exists():
        raise ValueError('actual retained native receipts required')
    verified = json.loads(subprocess.check_output([str(trial/'fuse-capture'), '-verify', '-output', str(trial)], text=True))
    manifest = verified['manifest']
    output.mkdir(parents=True)
    files = {n: sha(ROOT/n) for n in source_files()}
    for name in files:
        path = output/'source'/name
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT/name, path)
    shutil.copyfile(binary, output/'fuse-research')
    (output/'fuse-research').chmod(0o700)
    initial = fixed_policy(manifest['policy'])
    write(output/'initial-policy.json', initial)
    write(output/'receipt-verification.json', verified)
    plan = dict(version='sealed-adaptive-native-ppb-v1', profiles=PROFILES,
        supplemental_directory=str(supplemental), supplemental_result_sha256=sha(supplemental/'result.json'),
        receipt_directory=str(trial), receipts_sha256=sha(trial/'receipts.jsonl'),
        receipt_head=verified['head']['hash'], receipt_count=verified['head']['sequence'],
        receipt_verifier_sha256=sha(trial/'fuse-capture'),
        predictions=str(Path(protocol['compatibility_directory'])/'analysis-predictions.jsonl.gz'),
        predictions_sha256=binding['predictions_sha256'],
        decisions_sha256=sha(supplemental/'entry-decisions.jsonl.gz'),
        binary_sha256=sha(output/'fuse-research'), source_sha256=files,
        initial_policy_sha256=sha(output/'initial-policy.json'),
        start_ms=manifest['frozen_at_ms'], duration_ms=manifest['duration_ms'],
        primary_candidate=protocol['primary_candidate'], mode='continuous',
        initial_lp_usdc_units=250_000*USDC, customer_deposit_usdc_units=1000*USDC,
        stake_usdc_units=USDC, multiplier=2, settlement_interval_ms=300_000,
        original_target_survival='0.48', original_target_edge_bps=400,
        original_trial_state=binding['original_trial_state'], collection_quality_met=False,
        profile_selection='Reuse all four profiles from the retained failed native adapter; outcomes of the sealed paper study were already inspected. No new holdout claim.',
        ordering='Every original paired receipt, unmodified and in recorded order; grid action precedes same-time receipts. No downsampling or manufactured prices.',
        policy_updates='Exact sealed ppm * 1000 in the new native PPB table; operator harness updates, not a live adaptive pricing service. Accepted terms remain fixed.',
        finalization='Advance original prior oracle state to original end and void grace; settle remaining real liabilities. No terminal price is invented.',
        economics='Fixed hypothetical funded customer deposits and one-USDC stakes. Gross native accounting only; no daily fee, reward, LP ownership/exit or operating cash flow implementation.',
        prospective_evidence=False, production_approved=False, economics_validated=False)
    write(output/'protocol.json', plan)
    write(output/'freeze.json', dict(protocol_sha256=sha(output/'protocol.json')))
    return plan


def verify(output, current_sources=True):
    output = Path(output)
    plan = read(output/'protocol.json')
    if sha(output/'protocol.json') != read(output/'freeze.json')['protocol_sha256']:
        raise ValueError('native replay protocol changed')
    for name, digest in plan['source_sha256'].items():
        if sha(output/'source'/name) != digest or (current_sources and sha(ROOT/name) != digest):
            raise ValueError('native replay source changed: '+name)
    trial = Path(plan['receipt_directory'])
    for path, digest in ((output/'fuse-research', plan['binary_sha256']),
                         (output/'initial-policy.json', plan['initial_policy_sha256']),
                         (trial/'receipts.jsonl', plan['receipts_sha256']),
                         (trial/'fuse-capture', plan['receipt_verifier_sha256']),
                         (Path(plan['predictions']), plan['predictions_sha256']),
                         (Path(plan['supplemental_directory'])/'result.json', plan['supplemental_result_sha256']),
                         (Path(plan['supplemental_directory'])/'entry-decisions.jsonl.gz', plan['decisions_sha256'])):
        if sha(path) != digest:
            raise ValueError('native replay input changed: '+str(path))
    return plan


class Replay:
    def __init__(self, bridge, policy, plan, profile, receipts, quotes, decisions, rows):
        self.bridge, self.policy = bridge, deepcopy(policy)
        self.plan, self.profile, self.receipts = plan, profile, receipts
        self.quotes, self.decisions, self.rows = quotes, decisions, rows
        self.serial = self.peak_exposure = self.peak_debt = 0
        self.view = None
        self.rejects, self.counts = Counter(), Counter()
        self.entries = []
        self.intended = self.attempted = self.injections = 0

    def command(self, kind, at, optional=False, **fields):
        self.serial += 1
        response = self.bridge.send(dict(kind='command', command=dict(
            kind=kind, key='native-ppb/'+str(self.serial), at=at, **fields)), allow_reject=optional)
        self.counts[kind] += 1
        if not response['ok']:
            self.rejects[kind+': '+response['error']] += 1
            return None
        self.view = response['value']
        self.peak_exposure = max(self.peak_exposure, self.view['exposure'])
        self.peak_debt = max(self.peak_debt, self.view['debt'])
        return self.view.get('result')

    def entry(self, at):
        self.command('tick', at)
        if at > self.plan['start_ms'] and (at-self.plan['start_ms']) % self.plan['settlement_interval_ms'] == 0:
            self.command('paper_settle', at)
        if self.profile['strategy'] not in self.decisions[at]['strategies']:
            return
        quoted = self.quotes[at]
        width = quoted['width_ppm']
        if type(width) is not int or not 1 <= width <= 50000 or quoted['paused']:
            raise ValueError('selected quote unavailable in sealed tape')
        self.intended += 1
        if self.policy['model']['multiplier_widths_ppb']['2'] != width*1000:
            self.injections += 1
            updated = deepcopy(self.policy)
            updated['version'] = updated['model']['version'] = 'sealed-adaptive-ppb-'+str(self.injections)
            updated['model']['multiplier_widths_ppb']['2'] = width*1000
            self.command('policy_update', at, raw=updated)
            self.policy = updated
        for i in range(self.profile['accounts']):
            owner = 'trader-'+str(i)
            self.attempted += 1
            quote = self.command('quote', at, optional=True, actor=owner, amount=self.plan['stake_usdc_units'], multiplier=2)
            if quote is None:
                continue
            delta = quote['entry_price']*width//1_000_000
            if (quote['pricing_rule'] != 'fixed-width-ppb-v1' or quote['width_ppb'] != width*1000 or
                    quote['lower'] != quote['entry_price']-delta or quote['upper'] != quote['entry_price']+delta):
                raise ValueError('native terms differ from sealed quote')
            stage = self.command('enter', at, optional=True, actor=owner, id=quote['id'])
            if stage is not None:
                self.entries.append(dict(start=at, stage_id=stage['id']))

    def run(self):
        start = self.plan['start_ms']
        end = start+self.plan['duration_ms']
        self.view = self.bridge.send(dict(kind='init', policy=self.policy))['value']
        self.command('lp_fund', start, amount=self.plan['initial_lp_usdc_units'])
        for i in range(self.profile['accounts']):
            self.command('deposit', start, actor='trader-'+str(i), id='fund-'+str(i), amount=self.plan['customer_deposit_usdc_units'])
            self.command('ack_deposit', start, id='fund-'+str(i))
        index = 0
        for at in range(start, end, GRID):
            while index < len(self.receipts) and self.receipts[index]['at'] < at:
                row = self.receipts[index]
                self.command('oracle', row['at'], source=row['source'], raw=row['raw'])
                index += 1
            self.entry(at)
            if (at-start) % 3_600_000 == 0:
                print(json.dumps(dict(profile=self.profile['name'], through_ms=at, receipts=index,
                    accepted=len(self.entries), commands=self.serial)), flush=True)
        while index < len(self.receipts):
            row = self.receipts[index]
            self.command('oracle', row['at'], source=row['source'], raw=row['raw'])
            index += 1
        self.command('tick', end)
        self.command('tick', end+self.policy['void_delay_ms'])
        self.command('paper_settle', end+self.policy['void_delay_ms'])
        state = self.bridge.send(dict(kind='snapshot'))['value']
        comparisons = 0
        for entry in self.entries:
            stage = state['stages'][entry['stage_id']]
            row, quoted = self.rows[entry['start']], self.quotes[entry['start']]
            if row['valid']:
                delta = stage['terms']['entry_price'] * quoted['width_ppm'] // 1_000_000
                expected = row['move'] < delta
                if stage['terms']['entry_price'] != row['entry'] or expected != quoted['shadow_survived'] or (stage['status'] == 'survived') != expected:
                    raise ValueError('native healthy outcome differs from sealed path')
                comparisons += 1
        stages = list(state['stages'].values())
        outcomes = Counter(s['status'] for s in stages)
        pnl = sum(s['terms']['stake'] if s['status'] == 'exploded' else
                  s['terms']['stake']-s['terms']['payout'] if s['status'] == 'survived' else 0 for s in stages)
        customer = sum(sum(a[k] for k in ('available','unfunded','earned_funded','earned_unfunded',
            'withdrawal_funded','withdrawal_unfunded','withdrawn')) for a in state['accounts'].values())
        customer -= self.profile['accounts']*self.plan['customer_deposit_usdc_units']
        if (pnl != state['lp_profit'] or customer != -pnl or state['lp'] != self.plan['initial_lp_usdc_units']+pnl
                or self.view['active'] != 0 or self.view['debt'] != 0 or self.view['exposure'] != 0
                or state['loss_clearing'] != 0):
            raise ValueError('native terminal accounting mismatch')
        turnover = sum(s['terms']['stake'] for s in stages)
        result = dict(profile=self.profile, grid_windows=len(self.rows), all_original_receipts=index,
            intended_grid_entries=self.intended, quote_attempts=self.attempted,
            accepted_stages=len(stages), outcomes=dict(outcomes), rejected_actions=dict(self.rejects),
            healthy_outcome_comparisons=comparisons,
            accepted_censored_path_stages=len(stages)-comparisons,
            accepted_turnover_usdc_units=turnover, lp_gross_pnl_usdc_units=pnl,
            trader_gross_pnl_usdc_units=customer, lp_terminal_usdc_units=state['lp'],
            peak_exposure_usdc_units=self.peak_exposure, peak_unfunded_debt_usdc_units=self.peak_debt,
            exact_width_policy_injections=self.injections, operation_counts=dict(self.counts),
            audit_records=self.bridge.count, audit_head=self.bridge.head,
            cost_sensitivity=[dict(cost_bps=b, assumed_expense_usdc_units=turnover*b//10000,
                lp_gross_less_assumed_expense_usdc_units=pnl-turnover*b//10000) for b in (0,10,50,100)],
            actual_onchain_or_operating_costs=False, daily_fee_or_rewards_evaluated=False,
            production_approved=False, economics_validated=False)
        return result, state


def run(output):
    output = Path(output).resolve()
    plan = verify(output)
    if any((output/n).exists() for n in ('result.json', 'run-started.json')):
        raise FileExistsError('preserve completed or interrupted native replay')
    write(output/'run-started.json', dict(protocol_sha256=sha(output/'protocol.json')))
    receipts = [json.loads(line) for line in (Path(plan['receipt_directory'])/'receipts.jsonl').open()]
    if len(receipts) != plan['receipt_count']:
        raise ValueError('receipt count mismatch')
    with gzip.open(plan['predictions'], 'rt') as f:
        quotes = {r['start']:r for line in f if (r:=json.loads(line))['mode'] == plan['mode'] and r['candidate'] == plan['primary_candidate']}
    with gzip.open(Path(plan['supplemental_directory'])/'entry-decisions.jsonl.gz', 'rt') as f:
        decisions = {r['start']:r for line in f if (r:=json.loads(line))['mode'] == plan['mode'] and r['candidate'] == plan['primary_candidate']}
    rows = {r['start']:r for r in windows(iter(receipts), read(output/'initial-policy.json'),
        plan['start_ms'], plan['start_ms']+plan['duration_ms'])}
    expected = set(range(plan['start_ms'], plan['start_ms']+plan['duration_ms'], GRID))
    if set(rows) != expected or set(quotes) != expected or set(decisions) != expected:
        raise ValueError('sealed quote/decision/path grid incomplete')
    for at, row in rows.items():
        if row['valid'] != quotes[at]['valid_outcome']:
            raise ValueError('archived path validity differs')
    results = []
    for profile in plan['profiles']:
        name = profile['name']
        with (output/(name+'-audit.jsonl')).open('x') as audit:
            bridge = Bridge(output/'fuse-research', audit)
            try:
                case = Replay(bridge, read(output/'initial-policy.json'), plan, profile, receipts, quotes, decisions, rows)
                result, state = case.run()
            finally:
                bridge.close()
        write(output/(name+'-state.json'), state)
        write(output/(name+'-result.json'), result)
        results.append(result)
        print(json.dumps(dict(completed_profile=name, lp_gross_pnl_usdc_units=result['lp_gross_pnl_usdc_units'])), flush=True)
    verify(output)
    artifacts = {p.name:sha(p) for p in output.iterdir() if p.is_file() and p.name.endswith(('-audit.jsonl','-state.json','-result.json'))}
    result = dict(completed=True, protocol_sha256=sha(output/'protocol.json'), results=results,
        artifacts_sha256=artifacts, original_trial_state=plan['original_trial_state'], collection_quality_met=False,
        actual_paired_reducer_admission=True, funded_hypothetical_deposits=True,
        live_adaptive_service_implemented=False, release_7_to_10_percent_model=False,
        daily_fee_or_rewards_evaluated=False, production_approved=False, economics_validated=False)
    write(output/'result.json', result)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    prepare = sub.add_parser('declare')
    prepare.add_argument('--output', type=Path, required=True)
    prepare.add_argument('--binary', type=Path, required=True)
    prepare.add_argument('--supplemental', type=Path, required=True)
    execute = sub.add_parser('run')
    execute.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.action == 'declare':
        p = declare(args.output, args.binary, args.supplemental)
        print(json.dumps(dict(declared=True, profiles=len(p['profiles']), production_approved=False)))
    else:
        r = run(args.output)
        print(json.dumps(dict(completed=r['completed'], profiles=len(r['results']), production_approved=False)))
