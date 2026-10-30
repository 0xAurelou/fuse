#!/usr/bin/env python3
"""Offline native-policy boundary probe; no market observations or trades."""
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import time


MULTIPLIERS = (2, 5, 10, 25, 50, 100, 250, 1000, 10000)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(build, trial, output):
    build, trial, output = (p.resolve() for p in (build, trial, output))
    report = json.loads((build/'build.json').read_text())
    binary = build/'fuse-research-v2'
    if not report['completed'] or sha(binary) != report['binary_sha256']:
        raise ValueError('isolated native build changed')
    for name, digest in report['copied_source_sha256'].items():
        if sha(build/'engine'/name) != digest:
            raise ValueError('isolated source changed: '+name)
    binding = json.loads((trial/'freeze.json').read_text())
    if sha(trial/'frozen-policy.json') != binding['policy_sha256']:
        raise ValueError('frozen source policy changed')
    source = json.loads((trial/'frozen-policy.json').read_text())
    output.mkdir(parents=True, exist_ok=False)
    shutil.copyfile(__file__, output/'probe-source.py')
    shutil.copyfile(trial/'frozen-policy.json', output/'source-policy.json')
    cases = []
    definitions = (
        ('original-brownian-policy', None, None, True, None),
        ('two-only-one-ppm', (2,), (1,), False, 'single-stage multipliers must be'),
        ('nine-presets-first-eight-ppm', MULTIPLIERS, tuple(range(8, -1, -1)), False, 'strictly narrower'),
        ('nine-presets-first-nine-ppm', MULTIPLIERS, tuple(range(9, 0, -1)), True, None),
        ('nine-presets-first-one-ppm', MULTIPLIERS, (1,)*9, False, 'strictly narrower'),
    )
    for name, multipliers, widths, accepted, error in definitions:
        policy = deepcopy(source)
        policy.pop('markets', None)
        policy.pop('recovery', None)
        policy['version'] = 'software-policy-probe-'+name
        policy['model']['version'] = policy['version']
        if widths is not None:
            policy['multipliers'] = list(multipliers)
            policy['model'].pop('dnt', None)
            policy['model']['multiplier_widths_ppm'] = {str(m):w for m,w in zip(multipliers, widths)}
        request = dict(kind='init', policy=policy)
        proc = subprocess.run([str(binary)], input=json.dumps(request)+'\n',
                              text=True, capture_output=True, timeout=10, check=True)
        response = json.loads(proc.stdout)
        if response['ok'] != accepted or (error is not None and error not in response.get('error', '')):
            raise ValueError('unexpected native policy result: '+name)
        (output/(name+'.json')).write_text(json.dumps(dict(request=request, response=response), indent=2)+'\n')
        cases.append(dict(name=name, accepted=response['ok'], error=response.get('error')))
    result = dict(completed=True, observed_at_ms=time.time_ns()//1_000_000,
        software_only=True, live_receipts_read=False, market_observations=0,
        trades_or_quotes_entered=0, active_trial_modified=False,
        native_binary_sha256=report['binary_sha256'], isolated_source_files_verified=len(report['copied_source_sha256']),
        build_sha256=sha(build/'build.json'), source_policy_sha256=binding['policy_sha256'],
        cases=cases, minimum_two_times_fixed_table_width_ppm=9,
        argument='Nine strictly decreasing positive integers require the first to be at least nine. This is a restriction of this native fixed-table route, not a theorem that adaptive pricing or every native pricing interface is impossible.',
        implication='An exact funded replay of adaptive 1..8-ppm quotes cannot use this fixed-table route unchanged. Rounding widths up or substituting Brownian widths changes the candidate. A compatible width interface needs separate implementation and validation.',
        full_product_economics_validated=False, production_approved=False,
        files_sha256={p.name:sha(p) for p in output.iterdir() if p.is_file()})
    (output/'probe.json').write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps({k:result[k] for k in ('completed', 'cases', 'minimum_two_times_fixed_table_width_ppm',
        'isolated_source_files_verified', 'active_trial_modified')}, indent=2))
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build', type=Path, required=True)
    parser.add_argument('--trial', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    run(args.build, args.trial, args.output)
