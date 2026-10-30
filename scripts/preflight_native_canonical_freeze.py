#!/usr/bin/env python3
"""Exercise the future freezer and unchanged analyzer on a synthetic horizon.

No live receipts, new fitting, live candidate selection or external oracle.
The copied software fixture uses an explicitly artificial historical clock.
"""
import argparse
import gzip
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

from canonical_capture_policy import canonical_policy
from capture_dataset import file_hash
from freeze_adaptive_capture_v2 import freeze
from prospective_capture_v2 import verify_artifacts, write_new


def run(original, research, generator_packet, output):
    original = original.resolve()
    research = research.resolve()
    generator_packet = generator_packet.resolve()
    output = output.resolve()
    original_spec = verify_artifacts(original)
    generator_report = json.loads((generator_packet/'preflight.json').read_text())
    generator = generator_packet/'synthetic-capture'
    if file_hash(generator) != generator_report['generator_sha256']:
        raise ValueError('synthetic generator changed')
    if generator_report['frozen_native_verifier_sha256'] != original_spec['files_sha256']['fuse-capture']:
        raise ValueError('generator preflight used a different verifier')
    output.mkdir(parents=True, exist_ok=False)
    shutil.copyfile(__file__, output/'preflight-source.py')
    prepared = output/'prepared-software-packet'
    freeze(prepared, research, original/'source-policy.json', original/'fuse-capture')
    prepared_spec = verify_artifacts(prepared)
    if file_hash(prepared/'analyze.py') != file_hash(original/'analyze.py'):
        raise ValueError('original analyzer changed')
    if (prepared/'manifest.json').exists() or (prepared/'receipts.jsonl').exists():
        raise ValueError('preparation unexpectedly started a root market capture')
    fixture = output/'SYNTHETIC-eight-hour-control'
    shutil.copytree(prepared, fixture)
    spec = json.loads((fixture/'analysis-spec.json').read_text())
    start = time.time_ns()//1_000_000 - 9*3_600_000
    old_spec_hash = file_hash(fixture/'analysis-spec.json')
    spec.update(prepared_at_ms=start-1000,
                role='SYNTHETIC SOFTWARE FIXTURE; NO PROSPECTIVE MARKET EVIDENCE')
    (fixture/'analysis-spec.json').write_text(json.dumps(spec, indent=2)+'\n')
    policy = json.loads((fixture/'frozen-policy.json').read_text())
    policy['model']['dataset'] = policy['model']['dataset'].replace(old_spec_hash, file_hash(fixture/'analysis-spec.json'))
    canonical, _ = canonical_policy(policy, fixture/'fuse-capture', fixture/'fixture-policy-probe')
    (fixture/'frozen-policy.json').write_text(json.dumps(canonical, indent=2)+'\n')
    binding = json.loads((fixture/'freeze.json').read_text())
    binding.update(analysis_spec_sha256=file_hash(fixture/'analysis-spec.json'),
                   policy_sha256=file_hash(fixture/'frozen-policy.json'),
                   policy_probe_report_sha256=file_hash(fixture/'fixture-policy-probe/report.json'))
    (fixture/'freeze.json').write_text(json.dumps(binding, indent=2)+'\n')
    write_new(fixture/'SYNTHETIC_FIXTURE.json', dict(synthetic_only=True,
        market_evidence=False, artificial_start_ms=start, candidate_refitted=False))
    commands = []
    def command(label, args):
        env = dict(os.environ, PYTHONPATH=str(fixture), OPENBLAS_NUM_THREADS='1',
                   OMP_NUM_THREADS='1', MKL_NUM_THREADS='1')
        with (output/(label+'.stdout')).open('x') as stdout, (output/(label+'.stderr')).open('x') as stderr:
            result = subprocess.run([str(a) for a in args], stdout=stdout, stderr=stderr, env=env, timeout=180)
        commands.append(dict(label=label, arguments=[str(a) for a in args], exit_code=result.returncode))
        if result.returncode:
            raise ValueError('preflight command failed: '+label)
    command('generate', [generator, '-directory', fixture, '-start-ms', start])
    command('native-verify', [fixture/'fuse-capture', '-verify', '-output', fixture])
    native = json.loads((output/'native-verify.stdout').read_text())
    if native['manifest']['policy'] != canonical or native['head']['sequence'] != 14400:
        raise ValueError('native policy or synthetic receipt count differs')
    command('unchanged-analysis', [sys.executable, '-B', fixture/'analyze.py', fixture,
        '--verifier', fixture/'fuse-capture', '--output', fixture/'analysis.json'])
    result = json.loads((fixture/'analysis.json').read_text())
    if result['grid_windows'] != 960 or result['healthy_windows'] != 959 or not result['collection_quality_met']:
        raise ValueError('unexpected synthetic horizon or quality gate')
    predictions = fixture/'analysis-predictions.jsonl.gz'
    with gzip.open(predictions, 'rt') as stream:
        count = sum(1 for _ in stream)
    if count != 5760:
        raise ValueError('synthetic prediction count differs')
    verify_artifacts(prepared)
    verify_artifacts(fixture)
    verify_artifacts(original)
    report = dict(completed=True, software_only=True, live_receipts_read=False,
        new_market_capture_started=False, prospective_market_evidence=False,
        model_refitted=False, production_approved=False, economics_validated=False,
        original_bound_files_verified=len(original_spec['files_sha256']),
        prepared_bound_files_verified=len(prepared_spec['files_sha256']),
        original_analysis_spec_sha256=file_hash(original/'analysis-spec.json'),
        prepared_analysis_spec_sha256=file_hash(prepared/'analysis-spec.json'),
        analyzer_sha256=file_hash(fixture/'analyze.py'),
        unmodified_frozen_analyzer=True, supplemental_comparison_repair_used=False,
        native_receipts_verified=14400, synthetic_prediction_count=count,
        synthetic_healthy_windows=959, synthetic_grid_windows=960,
        preflight_source_sha256=file_hash(output/'preflight-source.py'),
        generator_sha256=file_hash(generator), commands=commands,
        artifacts_sha256={str(p.relative_to(output)):file_hash(p)
            for p in output.rglob('*') if p.is_file()})
    write_new(output/'preflight.json', report)
    print(json.dumps({k:report[k] for k in ('completed', 'software_only',
        'native_receipts_verified', 'synthetic_prediction_count',
        'unmodified_frozen_analyzer', 'original_bound_files_verified')}, indent=2), flush=True)
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--original', required=True, type=Path)
    parser.add_argument('--research', required=True, type=Path)
    parser.add_argument('--generator-packet', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    run(args.original, args.research, args.generator_packet, args.output)
