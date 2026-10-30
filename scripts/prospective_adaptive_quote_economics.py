#!/usr/bin/env python3
"""Freeze supplemental paper economics before results; consume sealed quotes later.

This protocol is introduced during collection, not at the original trial freeze.
It adds no price fitting, live trading, actual reserve fees or funded LP model.
"""
import argparse
from collections import defaultdict
import gzip
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import time

import adaptive_quote_economics as economics


def wall_ms():
    return time.time_ns()//1_000_000


def sha(path):
    result = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1 << 20), b''):
            result.update(block)
    return result.hexdigest()


def read(path):
    return json.loads(Path(path).read_text())


def write(path, value):
    with Path(path).open('x') as stream:
        json.dump(value, stream, indent=2, allow_nan=False)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())


def trial_bindings(trial):
    binding = read(trial/'freeze.json')
    if (sha(trial/'analysis-spec.json') != binding['analysis_spec_sha256'] or
            sha(trial/'frozen-policy.json') != binding['policy_sha256']):
        raise ValueError('original policy or analysis plan changed')
    spec = read(trial/'analysis-spec.json')
    for name, expected in spec['files_sha256'].items():
        if sha(trial/name) != expected:
            raise ValueError('original frozen file changed: '+name)
    manifest = read(trial/'manifest.json')
    return spec, manifest


def prepare(trial, compatibility, followup, historical, output):
    trial, compatibility, followup, historical, output = (
        p.resolve() for p in (trial, compatibility, followup, historical, output))
    spec, manifest = trial_bindings(trial)
    end = manifest['frozen_at_ms'] + manifest['duration_ms']
    now = wall_ms()
    if not manifest['frozen_at_ms'] < now < end:
        raise ValueError('supplemental protocol must be fixed during the original unelapsed capture')
    if ((compatibility/'analysis.json').exists() or
            (compatibility/'analysis-predictions.jsonl.gz').exists() or
            (followup/'result.json').exists()):
        raise ValueError('supplemental protocol must precede the first pricing result')
    prior = read(historical/'protocol.json')
    if prior['source_sha256']['adaptive_quote_economics.py'] != sha(economics.__file__):
        raise ValueError('previously declared paper strategy implementation changed')
    if (manifest['duration_ms'] != 8*3_600_000 or len(spec['candidates']) != 3 or
            spec['target_survival'] != .48):
        raise ValueError('this supplemental protocol requires the declared eight-hour, three-candidate trial')
    if output.exists():
        raise ValueError('preserve the prior supplemental protocol')
    output.mkdir(parents=True, mode=0o700)
    shutil.copyfile(__file__, output/'analyze.py')
    shutil.copyfile(economics.__file__, output/'adaptive_quote_economics.py')
    protocol = dict(version=1, prepared_at_ms=now, original_deadline_ms=end,
        original_directory=str(trial), compatibility_directory=str(compatibility),
        followup_directory=str(followup), historical_protocol=str(historical/'protocol.json'),
        original_analysis_spec_sha256=sha(trial/'analysis-spec.json'),
        original_manifest_sha256=sha(trial/'manifest.json'),
        compatibility_spec_sha256=sha(compatibility/'compatibility-spec.json'),
        followup_spec_sha256=sha(followup/'followup-spec.json'),
        historical_protocol_sha256=sha(historical/'protocol.json'),
        files_sha256={n:sha(output/n) for n in ('analyze.py', 'adaptive_quote_economics.py')},
        python_version=platform.python_version(), primary_candidate=spec['primary_candidate'],
        candidates=spec['candidates'], modes=['continuous', 'restart_half'],
        adopted_historical_spec=economics.SPEC,
        intervals='Full original eight hours and four fixed two-hour blocks; all cases reported.',
        history='Continuous trader state carries through all reporting blocks. restart_half uses empty private trader label state at entry and at four hours, matching the separately reset pricing replay. No reporting-block resets.',
        denominator='Every original 30-second grid point remains. Selected censored entries remain placed tickets; assumed refunds and independent all-survive/all-fail bounds are reported.',
        quote_mapping='width_ppm->width, shadow_survived->shadow; original paused, floor and pre-entry activity remain unchanged. No repricing.',
        selection='All 13 existing rules, both account counts and all four expense rates are reported. No strategy, threshold, candidate or positive-result subset is selected.',
        interpretation='Supplemental paper evidence on a prospectively frozen pricing model, with an economics protocol introduced during capture before first pricing analysis. It is not the original primary prospective protocol, independent per-strategy evidence, or funded product economics validation.',
        clean_cost_benchmarks='Inherited break_even_survival and expected_margin_at_48_percent describe clean resolved tickets. Additional fields adjust for expenses on all placed tickets, including assumed refunds.',
        software_fixture=(trial/'SYNTHETIC_FIXTURE.json').exists(),
        protocol_frozen_before_capture=False, protocol_frozen_before_first_result=True,
        pricing_refitted=False, live_pricing_outcomes_inspected=False,
        production_approved=False, economics_validated=False)
    write(output/'protocol.json', protocol)
    write(output/'freeze.json', dict(protocol_sha256=sha(output/'protocol.json'), prepared_at_ms=now))
    verify_protocol(output)
    return protocol


def verify_protocol(packet):
    protocol = read(packet/'protocol.json')
    if sha(packet/'protocol.json') != read(packet/'freeze.json')['protocol_sha256']:
        raise ValueError('supplemental protocol changed')
    for name, expected in protocol['files_sha256'].items():
        if sha(packet/name) != expected:
            raise ValueError('supplemental source changed: '+name)
    if (sha(__file__) != protocol['files_sha256']['analyze.py'] or
            sha(economics.__file__) != protocol['files_sha256']['adaptive_quote_economics.py']):
        raise ValueError('executing economics source differs from frozen packet')
    trial = Path(protocol['original_directory'])
    spec, manifest = trial_bindings(trial)
    checks = ((trial/'analysis-spec.json', 'original_analysis_spec_sha256'),
        (trial/'manifest.json', 'original_manifest_sha256'),
        (Path(protocol['compatibility_directory'])/'compatibility-spec.json', 'compatibility_spec_sha256'),
        (Path(protocol['followup_directory'])/'followup-spec.json', 'followup_spec_sha256'),
        (Path(protocol['historical_protocol']), 'historical_protocol_sha256'))
    for path, key in checks:
        if sha(path) != protocol[key]:
            raise ValueError('supplemental input binding changed: '+key)
    compatibility = Path(protocol['compatibility_directory'])
    compat = read(compatibility/'compatibility-spec.json')
    for name, expected in compat['files_sha256'].items():
        if sha(compatibility/name) != expected:
            raise ValueError('compatibility source changed: '+name)
    followup = Path(protocol['followup_directory'])
    completion = read(followup/'followup-spec.json')
    if (compat['original_directory'] != str(trial) or
            compat['original_analysis_spec_sha256'] != protocol['original_analysis_spec_sha256'] or
            compat['original_manifest_sha256'] != protocol['original_manifest_sha256'] or
            compat['original_deadline_ms'] != protocol['original_deadline_ms'] or
            completion['original_directory'] != str(trial) or
            completion['compatibility_directory'] != str(compatibility) or
            completion['analysis_spec_sha256'] != protocol['original_analysis_spec_sha256'] or
            completion['original_deadline_ms'] != protocol['original_deadline_ms'] or
            completion['compatibility_spec_sha256'] != protocol['compatibility_spec_sha256'] or
            sha(followup/'followup.py') != completion['followup_source_sha256']):
        raise ValueError('compatibility or completion packet identity differs')
    if (manifest['frozen_at_ms'] + manifest['duration_ms'] != protocol['original_deadline_ms'] or
            spec['candidates'] != protocol['candidates'] or
            spec['primary_candidate'] != protocol['primary_candidate']):
        raise ValueError('supplemental trial identity differs')
    return protocol, spec, manifest


def compute(predictions, protocol, start, analysis):
    sessions = defaultdict(list)
    for p in predictions:
        key = (p['mode'], p['candidate'])
        if key[0] not in protocol['modes'] or key[1] not in protocol['candidates']:
            raise ValueError('undeclared quote session')
        sessions[key].append(dict(start=p['start'], width=p['width_ppm'],
            shadow=p['shadow_survived'], floor=p['floor'], paused=p['paused'], activity=p['activity']))
    expected = {(m, c) for m in protocol['modes'] for c in protocol['candidates']}
    if set(sessions) != expected:
        raise ValueError('missing quote sessions')
    pricing = {(r['mode'], r['candidate'], r['interval'], r['group']):r
               for r in analysis['summaries'] if r['axis'] in ('all', 'activity')}
    cases, traces = [], []
    intervals = [('full', 0, 960)] + [('quarter'+str(i), i*240, (i+1)*240) for i in range(4)]
    for (mode, candidate), rows in sorted(sessions.items()):
        if [r['start'] for r in rows] != [start+i*30000 for i in range(960)]:
            raise ValueError('complete original quote grid required')
        chosen = (economics.decisions(rows) if mode == 'continuous' else
                  economics.decisions(rows[:480]) + economics.decisions(rows[480:]))
        traces.extend(dict(mode=mode, candidate=candidate, **d) for d in chosen)
        for name, left, right in intervals:
            for strategy in economics.STRATEGIES:
                for accounts in economics.ACCOUNTS:
                    case = economics.summarize(rows[left:right], chosen[left:right], strategy, accounts)
                    if accounts == 1 and strategy in ('all_offered', 'frozen_only'):
                        group = 'all' if strategy == 'all_offered' else 'frozen'
                        source = pricing[mode, candidate, name, group]
                        for a, b in (('selected_grid_entries', 'offered_pre_entry_decisions'),
                                     ('resolved_grid_entries', 'windows'), ('survived_grid_entries', 'survived')):
                            if case[a] != source[b]:
                                raise ValueError('original pricing denominator differs: '+a)
                    for cost in case['cost_sensitivity']:
                        placed, resolved = case['placed_tickets'], case['resolved_grid_entries']*accounts
                        allocated = cost['allocated_expense_usdc_units']
                        cost['resolved_survival_break_even_with_placed_expense'] = (
                            .5-allocated/(2*resolved*economics.UNIT) if resolved else None)
                        cost['expected_margin_per_placed_stake_at_48_resolved_with_censored_refunds'] = (
                            (resolved*economics.UNIT*.04-allocated)/(placed*economics.UNIT) if placed else None)
                    cases.append(dict(mode=mode, candidate=candidate, interval=name,
                        start=start+left*30000, end=start+right*30000, **case))
    return cases, traces


def run(packet):
    packet = packet.resolve()
    protocol, spec, manifest = verify_protocol(packet)
    if wall_ms() < protocol['original_deadline_ms']:
        raise ValueError('original capture horizon has not elapsed')
    if platform.python_version() != protocol['python_version']:
        raise ValueError('economics runtime differs')
    if any((packet/n).exists() for n in ('result.json', 'cases.jsonl', 'entry-decisions.jsonl.gz')):
        raise ValueError('preserve existing economics results')
    trial = Path(protocol['original_directory'])
    compatibility = Path(protocol['compatibility_directory'])
    followup = Path(protocol['followup_directory'])
    completed = read(followup/'result.json')
    if (completed.get('supplemental_analysis_completed') is not True or
            completed['original_deadline_ms'] != protocol['original_deadline_ms'] or
            completed['original_terminal_status_preserved'] not in ('failed', 'completed') or
            completed['original_terminal_status_preserved'] != read(trial/'status.json')['state']):
        raise ValueError('original completion and disclosed supplemental replay are required')
    analysis_path = compatibility/'analysis.json'
    tape = compatibility/'analysis-predictions.jsonl.gz'
    if sha(analysis_path) != completed['analysis_sha256'] or sha(tape) != completed['predictions_sha256']:
        raise ValueError('completed pricing output changed')
    analysis = read(analysis_path)
    if (analysis['analysis_spec_sha256'] != protocol['original_analysis_spec_sha256'] or
            analysis['manifest_sha256'] != protocol['original_manifest_sha256'] or
            analysis['predictions_sha256'] != sha(tape) or
            analysis['planned_end_ms'] != protocol['original_deadline_ms'] or
            analysis['frozen_at_ms'] != manifest['frozen_at_ms'] or
            analysis['primary_candidate'] != protocol['primary_candidate'] or
            analysis.get('analysis_procedure') != 'supplemental-policy-zero-compatibility-v1' or
            analysis.get('unmodified_frozen_analyzer') is not False):
        raise ValueError('pricing output identity or repair disclosure differs')
    native = json.loads(subprocess.check_output(
        [str(trial/'fuse-capture'), '-verify', '-output', str(trial)], text=True, timeout=60))
    if (native != read(trial/'verification.json') or native['manifest'] != manifest or
            native['head']['hash'] != analysis['receipt_hash'] or
            sha(trial/'receipts.jsonl') != analysis['receipts_sha256']):
        raise ValueError('final native receipt evidence differs')
    with gzip.open(tape, 'rt') as stream:
        predictions = [json.loads(line) for line in stream]
    cases, traces = compute(predictions, protocol, manifest['frozen_at_ms'], analysis)
    if len(cases) != 780 or len(traces) != 5760:
        raise ValueError('supplemental case or quote count differs')
    with (packet/'cases.jsonl').open('x') as stream:
        for r in cases:
            stream.write(json.dumps(r, allow_nan=False)+'\n')
    with gzip.open(packet/'entry-decisions.jsonl.gz', 'xt') as stream:
        for r in traces:
            stream.write(json.dumps(r, allow_nan=False)+'\n')
    verify_protocol(packet)
    if sha(tape) != completed['predictions_sha256'] or sha(analysis_path) != completed['analysis_sha256']:
        raise ValueError('pricing outputs changed during paper economics')
    result = dict(completed=True, completed_at_ms=wall_ms(),
        protocol_sha256=sha(packet/'protocol.json'), analysis_sha256=sha(analysis_path),
        predictions_sha256=sha(tape), cases_sha256=sha(packet/'cases.jsonl'),
        entry_decisions_sha256=sha(packet/'entry-decisions.jsonl.gz'),
        cases=len(cases), quote_decisions=len(traces),
        original_terminal_status_preserved=completed['original_terminal_status_preserved'],
        collection_quality_met=analysis['collection_quality_met'],
        software_fixture=protocol['software_fixture'],
        economics_protocol_frozen_before_capture=False,
        economics_protocol_frozen_before_first_result=True,
        interpretation=protocol['interpretation'],
        actual_reserve_fees_evaluated=False, funded_admission_evaluated=False,
        economics_validated=False, production_approved=False, goal_complete=False)
    write(packet/'result.json', result)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('prepare', 'run'))
    parser.add_argument('--packet', required=True, type=Path)
    parser.add_argument('--trial', type=Path)
    parser.add_argument('--compatibility', type=Path)
    parser.add_argument('--followup', type=Path)
    parser.add_argument('--historical', type=Path)
    args = parser.parse_args()
    result = (prepare(args.trial, args.compatibility, args.followup, args.historical, args.packet)
              if args.action == 'prepare' else run(args.packet))
    print(json.dumps({k:result[k] for k in ('prepared_at_ms', 'original_deadline_ms', 'completed',
        'cases', 'quote_decisions', 'economics_validated') if k in result}, indent=2))
