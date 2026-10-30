#!/usr/bin/env python3
"""Audit synthetic replay parity, native chains, freshness and failure gates.

No ongoing receipt file is opened. This is software evidence, not calibration.
"""
import argparse
from collections import Counter
import gzip
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

from capture_continuity import metadata
from capture_dataset import file_hash
from prospective_capture_v2 import verify_artifacts

ROOT=Path(__file__).resolve().parent.parent


def audit(directory,compatibility,output):
    directory=directory.resolve();compatibility=compatibility.resolve();output=output.resolve()
    report=json.loads((directory/'preflight.json').read_text())
    if not report['completed'] or not report['synthetic_only'] or report['live_receipts_read']:
        raise ValueError('a completed synthetic preflight is required')
    if file_hash(directory/'preflight-source.py')!=report['preflight_source_sha256']:
        raise ValueError('preflight source changed')
    if file_hash(directory/'synthetic-capture')!=report['generator_sha256']:
        raise ValueError('synthetic generator changed')
    for name,digest in report['isolated_go_sources_sha256'].items():
        if file_hash(directory/'engine'/name)!=digest:raise ValueError('copied Go source changed: '+name)
    if file_hash(compatibility/'compatibility-spec.json')!=report['compatibility_spec_sha256']:
        raise ValueError('compatibility spec changed')
    compat=json.loads((compatibility/'compatibility-spec.json').read_text())
    for name,digest in compat['files_sha256'].items():
        if file_hash(compatibility/name)!=digest:raise ValueError('compatibility source changed: '+name)
    original=Path(compat['original_directory']);spec=verify_artifacts(original)
    if (file_hash(original/'analysis-spec.json')!=report['original_analysis_spec_sha256']
            or file_hash(original/'manifest.json')!=compat['original_manifest_sha256']):
        raise ValueError('original trial static bindings differ')
    output.mkdir(parents=True,exist_ok=False)
    shutil.copyfile(__file__,output/'audit-source.py')
    proofs=[]
    for case in report['cases']:
        root=directory/case['case'];canonical=directory/(case['case']+'-canonical')
        for target in (root,canonical):verify_artifacts(target)
        result=json.loads((root/'compatible.json').read_text())
        baseline=json.loads((canonical/'baseline.json').read_text())
        for field in ('manifest.json','receipts.jsonl','adaptive-models.json','analysis-spec.json'):
            if file_hash(root/field)!=file_hash(canonical/field):raise ValueError('control input differs: '+field)
        if file_hash(root/'compatible-predictions.jsonl.gz')!=result['predictions_sha256']:
            raise ValueError('compatibility trace differs from result')
        if file_hash(canonical/'baseline-predictions.jsonl.gz')!=baseline['predictions_sha256']:
            raise ValueError('control trace differs from result')
        compared=dict(result);compared.pop('analysis_procedure');compared.pop('unmodified_frozen_analyzer')
        compared.pop('predictions_sha256');baseline.pop('predictions_sha256')
        if compared!=baseline:raise ValueError('all numerical summaries must match canonical control')
        with gzip.open(root/'compatible-predictions.jsonl.gz','rt') as a, gzip.open(canonical/'baseline-predictions.jsonl.gz','rt') as b:
            trace=a.read()
            if trace!=b.read():raise ValueError('prediction records differ')
        counts=Counter();seen=set()
        for line in trace.splitlines():
            prediction=json.loads(line);key=(prediction['candidate'],prediction['mode'],prediction['start'])
            if key in seen:raise ValueError('duplicate prediction')
            seen.add(key);counts[key[:2]]+=1
        expected={(candidate,mode):960 for candidate in spec['candidates'] for mode in ('continuous','restart_half')}
        if dict(counts)!=expected:raise ValueError('trace omitted original grid, candidate or replay')
        native=json.loads(subprocess.check_output([str(root/'fuse-capture'),'-verify','-output',str(root)],text=True))
        with (root/'receipts.jsonl').open() as stream:receipts=[json.loads(line) for line in stream]
        manifest=native['manifest'];start=manifest['frozen_at_ms'];end=start+manifest['duration_ms']
        if receipts[-1]['hash']!=native['head']['hash'] or file_hash(root/'receipts.jsonl')!=result['receipts_sha256']:
            raise ValueError('result/native receipt evidence differs')
        # Both synthetic feeds are paired at exactly the same timestamp.
        # Thus no sustained disagreement occurs and freshness is the exact
        # health loss here. The observer never reads oracle values.
        if any(a['at']!=b['at'] or a['source']!='a' or b['source']!='b' or a['raw']!=b['raw']
               for a,b in zip(receipts[::2],receipts[1::2])):
            raise ValueError('synthetic fixture lacks exact simultaneous feed pairs')
        freshness=metadata(receipts,start,end,end,manifest['policy']['max_gap_ms'])
        healthy=960-freshness['freshness_affected_complete_windows']
        if result['healthy_windows']!=healthy:raise ValueError('independent freshness denominator disagrees')
        quality=healthy>=spec['minimum_healthy_windows'] and healthy/960>=spec['minimum_full_horizon_coverage']
        if result['collection_quality_met']!=quality:raise ValueError('wrong frozen collection threshold')
        proofs.append(dict(case=case['case'],native_receipts_verified=len(receipts),
            independent_healthy_windows=healthy,predictions_compared=len(seen),
            all_numerical_summaries_equal=True,all_prediction_records_equal=True,
            collection_quality_met=quality))
    # Exercise the actual time gate with natively valid, explicitly synthetic
    # future timestamps. Nothing is captured from a network or a real oracle.
    future=output/'synthetic-future-horizon';future.mkdir();healthy_case=directory/'synthetic-healthy'
    synthetic_spec=json.loads((healthy_case/'analysis-spec.json').read_text())
    for name in (*synthetic_spec['files_sha256'],'analysis-spec.json','frozen-policy.json','freeze.json','SYNTHETIC_FIXTURE.json'):
        target=future/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(healthy_case/name,target)
    (future/'fuse-capture').chmod(0o700)
    subprocess.run([str(directory/'synthetic-capture'),'-directory',str(future),'-start-ms',str(time.time_ns()//1000000-7*3600000)],check=True)
    subprocess.run([str(future/'fuse-capture'),'-verify','-output',str(future)],stdout=subprocess.DEVNULL,check=True)
    failures=[]
    def reject(case,label,expected):
        env=dict(os.environ,PYTHONPATH=str(case),OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='1',MKL_NUM_THREADS='1')
        args=[sys.executable,'-B',str(compatibility/'analyze.py'),str(case),'--verifier',str(case/'fuse-capture'),
              '--output',str(output/(label+'.json'))]
        proc=subprocess.run(args,env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        (output/(label+'.stdout')).write_text(proc.stdout);(output/(label+'.stderr')).write_text(proc.stderr)
        if proc.returncode==0 or expected not in proc.stderr or (output/(label+'.json')).exists():
            raise ValueError('expected fail-closed gate did not hold: '+label)
        failures.append(dict(label=label,exit_code=proc.returncode,expected_message=expected,output_written=False))
    reject(future,'unelapsed-horizon','fixed horizon has not elapsed')
    reject(directory/'synthetic-changed-policy','nonzero-policy','differs from frozen policy')
    reject(directory/'synthetic-tampered-receipt','receipt-digest','receipt chain, time or source invalid')
    tampered=output/'synthetic-model-tamper';shutil.copytree(future,tampered)
    with (tampered/'adaptive-models.json').open('ab') as f:f.write(b' ')
    reject(tampered,'changed-frozen-model','frozen artifact changed: adaptive-models.json')
    verify_artifacts(original)
    artifacts={str(p.relative_to(directory)):file_hash(p) for p in directory.rglob('*') if p.is_file()}
    result=dict(completed=True,synthetic_only=True,real_market_evidence=False,original_live_receipts_read=False,
        previous_goal_turn_classification='progress',preflight_sha256=file_hash(directory/'preflight.json'),
        preflight_artifacts_sha256=artifacts,audit_source_sha256=file_hash(output/'audit-source.py'),
        compatibility_spec_sha256=file_hash(compatibility/'compatibility-spec.json'),
        original_frozen_files_verified=len(spec['files_sha256']),cases=proofs,failure_gates=failures,
        production_approved=False,economics_validated=False,goal_complete=False)
    with (output/'audit.json').open('x') as f:json.dump(result,f,indent=2);f.write('\n')
    print(json.dumps(dict(completed=True,cases=proofs,failure_gates=failures),indent=2))
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--directory',type=Path,required=True)
    p.add_argument('--compatibility',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();audit(a.directory,a.compatibility,a.output)
