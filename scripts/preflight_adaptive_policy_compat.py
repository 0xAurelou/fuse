#!/usr/bin/env python3
"""Offline end-to-end compatibility preflight using synthetic native receipts.

Reads only static artifacts from the ongoing trial. Never opens its receipts,
evaluates its outcomes, starts another capture or alters its frozen packet.
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

from capture_dataset import file_hash
from capture_policy_equivalence import compare_policy
from prospective_capture_v2 import verify_artifacts

ROOT=Path(__file__).resolve().parent.parent


def write(path,value):
    with path.open('x') as f:json.dump(value,f,indent=2);f.write('\n')


def rebind(directory):
    freeze=json.loads((directory/'freeze.json').read_text())
    freeze.update(analysis_spec_sha256=file_hash(directory/'analysis-spec.json'),policy_sha256=file_hash(directory/'frozen-policy.json'))
    (directory/'freeze.json').write_text(json.dumps(freeze,indent=2)+'\n')


def run(original,compat,output):
    original=original.resolve();compat=compat.resolve();output=output.resolve()
    spec=verify_artifacts(original);c=json.loads((compat/'compatibility-spec.json').read_text())
    for name,expected in c['files_sha256'].items():
        if file_hash(compat/name)!=expected:raise ValueError('compatibility packet changed: '+name)
    if file_hash(original/'analysis-spec.json')!=c['original_analysis_spec_sha256']:
        raise ValueError('compatibility packet belongs to a different trial')
    output.mkdir(parents=True,exist_ok=False)
    shutil.copyfile(__file__,output/'preflight-source.py')
    module=output/'engine';module.mkdir()
    for name in ('go.mod','go.sum'):shutil.copyfile(ROOT/'engine'/name,module/name)
    shutil.copytree(ROOT/'engine/internal',module/'internal')
    target=module/'cmd/synthetic-capture/main.go';target.parent.mkdir(parents=True)
    shutil.copyfile(ROOT/'scripts/research_engine/synthetic-capture/main.go',target)
    copied={str(p.relative_to(module)):file_hash(p) for p in module.rglob('*') if p.is_file()}
    goroot=subprocess.check_output(['go','env','GOROOT'],cwd=ROOT/'engine',text=True).strip()
    go=Path(goroot)/'bin/go';generator=output/'synthetic-capture'
    env=dict(os.environ,GOCACHE='/private/tmp/fuse-go-cache',GOTOOLCHAIN='local',
             OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='1',MKL_NUM_THREADS='1')
    with (output/'go-build.log').open('x') as log:
        subprocess.run([str(go),'build','-o',str(generator),'./cmd/synthetic-capture'],cwd=module,
            env=env,stdout=log,stderr=subprocess.STDOUT,check=True)
    policy=json.loads((original/'frozen-policy.json').read_text())
    # Deliberately backdated synthetic clock; the marker and report prohibit
    # interpreting an analyzer's generic frozen-model flag as real evidence.
    start=time.time_ns()//1000000-9*3600000
    synthetic_spec=dict(spec,prepared_at_ms=start-1000,
                        role='SYNTHETIC SOFTWARE FIXTURE; NOT PROSPECTIVE MARKET EVIDENCE')
    marker=dict(synthetic_only=True,prospective_evidence=False,real_market_evidence=False,
        original_directory=str(original),clock='Artificial historical start to exercise completed-horizon software gates offline',
        models='Exact archived frozen models; no fitting or candidate selection')
    events=[];cases=[]
    def command(args,directory,label,success=True):
        case_env=dict(env,PYTHONPATH=str(directory))
        with (directory/(label+'.stdout')).open('x') as stdout, (directory/(label+'.stderr')).open('x') as stderr:
            proc=subprocess.run([str(a) for a in args],env=case_env,stdout=stdout,stderr=stderr)
        events.append(dict(case=directory.name,label=label,arguments=[str(a) for a in args],exit_code=proc.returncode))
        if (proc.returncode==0)!=success:raise ValueError('unexpected subprocess result: '+label)
    def fixture(name,gap=0,delta=0):
        directory=output/name;directory.mkdir()
        for relative in spec['files_sha256']:
            destination=directory/relative;destination.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(original/relative,destination)
        (directory/'fuse-capture').chmod(0o700)
        shutil.copyfile(original/'frozen-policy.json',directory/'frozen-policy.json')
        shutil.copyfile(original/'freeze.json',directory/'freeze.json')
        write(directory/'analysis-spec.json',synthetic_spec)
        write(directory/'SYNTHETIC_FIXTURE.json',marker);rebind(directory)
        command([generator,'-directory',directory,'-start-ms',start,'-gap-ms',gap,'-policy-gap-delta',delta],directory,'generate')
        command([directory/'fuse-capture','-verify','-output',directory],directory,'native-verify')
        return directory
    def analyze(directory,compatible=True,label='compatible',success=True):
        script=compat/'analyze.py' if compatible else directory/'analyze.py'
        command([sys.executable,'-B',script,directory,'--verifier',directory/'fuse-capture',
                 '--output',directory/(label+'.json')],directory,label,success)
        return json.loads((directory/(label+'.json')).read_text()) if success else None
    for name,gap in (('synthetic-healthy',0),('synthetic-ten-minute-gap',600000),('synthetic-ninety-minute-gap',5400000)):
        directory=fixture(name,gap)
        compare_policy(json.loads((directory/'manifest.json').read_text())['policy'],policy)
        analyze(directory,False,'original-rejection',False)
        failure=(directory/'original-rejection.stderr').read_text()
        if 'capture does not match the frozen model, policy or horizon' not in failure:
            raise ValueError('original rejection is not the expected policy comparison')
        result=analyze(directory)
        if result['grid_windows']!=960 or result['collection_quality_met']!=(gap<5400000):
            raise ValueError('wrong original horizon or synthetic quality gate')
        # A canonical-input control must run the entirely unmodified analyzer.
        # Only the fixture policy/freeze binding changes, never a real trial.
        canonical=output/(name+'-canonical');shutil.copytree(directory,canonical)
        normalized=json.loads((canonical/'manifest.json').read_text())['policy']
        (canonical/'frozen-policy.json').write_text(json.dumps(normalized,indent=2)+'\n');rebind(canonical)
        baseline=analyze(canonical,False,'baseline')
        expected=dict(result);expected.pop('analysis_procedure');expected.pop('unmodified_frozen_analyzer')
        expected.pop('predictions_sha256');baseline.pop('predictions_sha256')
        if expected!=baseline:raise ValueError('numerical summaries differ after canonical control')
        with gzip.open(directory/'compatible-predictions.jsonl.gz','rt') as a, gzip.open(canonical/'baseline-predictions.jsonl.gz','rt') as b:
            if a.read()!=b.read():raise ValueError('per-entry predictions differ after canonical control')
        cases.append(dict(case=name,synthetic_only=True,receipt_count=json.loads((directory/'SYNTHETIC_GENERATION.json').read_text())['sequence'],
            grid_windows=result['grid_windows'],healthy_windows=result['healthy_windows'],
            collection_quality_met=result['collection_quality_met'],exact_numerical_control_parity=True,
            exact_decompressed_prediction_parity=True))
        print(json.dumps(cases[-1]),flush=True)
    bad=fixture('synthetic-changed-policy',delta=1)
    analyze(bad,True,'policy-rejection',False)
    if 'differs from frozen policy' not in (bad/'policy-rejection.stderr').read_text():
        raise ValueError('nonzero changed policy was not rejected by semantic check')
    corrupt=output/'synthetic-tampered-receipt';shutil.copytree(output/'synthetic-healthy',corrupt)
    receipt=corrupt/'receipts.jsonl';raw=receipt.read_bytes()
    changed=raw.replace(b'"oraclePx":"100000"',b'"oraclePx":"100001"',1)
    if changed==raw:raise ValueError('synthetic tamper fixture did not mutate oracle payload')
    receipt.write_bytes(changed)
    analyze(corrupt,True,'digest-rejection',False)
    if 'receipt chain, time or source invalid' not in (corrupt/'digest-rejection.stderr').read_text():
        raise ValueError('tampered receipt was not rejected by frozen native verifier')
    verify_artifacts(original)
    for relative,digest in copied.items():
        if file_hash(module/relative)!=digest:raise ValueError('isolated source changed')
    for name,expected in c['files_sha256'].items():
        if file_hash(compat/name)!=expected:raise ValueError('compatibility source changed during preflight')
    report=dict(completed=True,synthetic_only=True,real_market_evidence=False,live_receipts_read=False,
        original_frozen_files_verified=len(spec['files_sha256']),original_trial_changed=False,
        original_analysis_spec_sha256=file_hash(original/'analysis-spec.json'),
        compatibility_spec_sha256=file_hash(compat/'compatibility-spec.json'),
        preflight_source_sha256=file_hash(output/'preflight-source.py'),
        isolated_go_sources_sha256=copied,generator_sha256=file_hash(generator),
        go_version=subprocess.check_output([str(go),'version'],text=True).strip(),
        frozen_native_verifier_sha256=spec['files_sha256']['fuse-capture'],cases=cases,commands=events,
        nonzero_policy_change_rejected=True,tampered_receipt_rejected_by_native_verifier=True,
        notes='Synthetic historical clocks and software-only oracle schedules are deliberately fabricated fixtures. No market calibration, quote availability or LP economics conclusion follows. All numerical replays used the actual archived models and unchanged pricing stack.',
        production_approved=False,economics_validated=False,goal_complete=False)
    write(output/'preflight.json',report)
    return report


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--directory',type=Path,required=True)
    p.add_argument('--compatibility',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();run(a.directory,a.compatibility,a.output)
