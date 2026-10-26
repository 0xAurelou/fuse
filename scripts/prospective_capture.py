#!/usr/bin/env python3
"""Freeze and supervise a fixed-horizon, observation-only prospective experiment."""
import argparse
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parent.parent


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_new(path, value):
    with Path(path).open('x') as stream:
        json.dump(value, stream, indent=2)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())


def freeze(directory, calibration, policy, hours):
    if not 1 <= hours <= 168:
        raise ValueError('hours must be 1..168')
    directory = directory.resolve()
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    if (directory/'analysis-spec.json').exists() or (directory/'manifest.json').exists():
        raise ValueError('experiment already frozen; use a new directory')
    fitted = json.loads(calibration.read_text())
    original = json.loads(policy.read_text())
    selected = fitted['selected']
    if selected['width_ppm'] != original['model'].get('base_width_ppm'):
        raise ValueError('policy differs from fitted candidate')
    if any(original['model'].get(k, 0) for k in ('base_width_bps','control_width_bps','volatility_factor')):
        raise ValueError('a fixed fractional-width candidate is required')
    if selected['target_survival'] != .48:
        raise ValueError('this research protocol fixes the 48% hypothesis')
    cutoff, sources = 0, []
    for source in fitted['dataset']:
        if source.get('format') == 'oracle-receipts-v1':
            from capture_dataset import validate_source
            end, retained = validate_source(source)
            cutoff = max(cutoff, end)
            sources.append(retained)
            continue
        journal = Path(source['path'])/'journal.jsonl'
        if digest(journal) != source['sha256']:
            raise ValueError(f'training journal changed: {journal}')
        with journal.open() as stream:
            for line in stream:
                cutoff = max(cutoff, json.loads(line)['command']['at'])
        sources.append({'path':str(journal.resolve()),'sha256':source['sha256']})
    now = time.time_ns()//1_000_000
    if cutoff >= now:
        raise ValueError('training must end strictly before the experiment')
    if shutil.disk_usage(directory).free < 10*1024**3:
        raise ValueError('at least 10 GiB free disk required before starting')
    snapshots = {
        'frozen-calibration.json':calibration, 'source-policy.json':policy,
        'oracle-policy.md':ROOT/'docs/ORACLE_POLICY.md',
        'risk-policy.md':ROOT/'docs/RISK_AND_CAPTURE.md',
        'research-risk-policy.json':ROOT/'engine/config/paper-recovery.json',
        'analyze.py':ROOT/'scripts/analyze_capture.py',
        'supervisor.py':Path(__file__).resolve(),
        'calibrate_capture.py':ROOT/'scripts/calibrate_capture.py',
        'capture_dataset.py':ROOT/'scripts/capture_dataset.py',
        'calibrate_pricing.py':ROOT/'scripts/calibrate_pricing.py',
    }
    for name, source in snapshots.items():
        with (directory/name).open('xb') as stream:
            stream.write(source.read_bytes()); stream.flush(); os.fsync(stream.fileno())
    files = {name:digest(directory/name) for name in [*snapshots, 'fuse-capture']}
    spec = {
        'version':1,'prepared_at_ms':now,'duration_hours':hours,
        'training_cutoff_ms':cutoff,'training_sources':sources,
        'candidate_width_ppm':selected['width_ppm'],'target_survival':.48,'tolerance':.05,
        'minimum_healthy_windows':400,'minimum_full_horizon_coverage':.9,
        'window_ms':30000,'window_grid':'capture manifest frozen_at_ms + k*30000',
        'primary_analysis':'All full windows in the fixed horizon. Descriptive Wilson 95% interval versus [0.43,0.53]; never refit or stop early for success.',
        'regime_analysis':'Descriptive corridor-relative flat/jump/volatile/trending/quiet labels, frozen in analyze.py. No approved effective-size or per-regime safety threshold. Outcome-defined regimes cannot establish independent conditional calibration.',
        'collection_only':True,'production_approved':False,'oracle_policy_approved':False,
        'risk_limits_approved_for_production':False,
        'scope':f"Frozen {selected['width_ppm']}-ppm candidate. Prior recordings used for fitting are calibration data, not fresh validation for this candidate. No refitting or early success stopping after freeze. Model validity is extended solely for the observation horizon. No trades, funds, keys or public execution.",
        'files_sha256':files,
        'source_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
    }
    write_new(directory/'analysis-spec.json', spec)
    frozen = original
    frozen['mode'] = 'paper'
    frozen['version'] = 'prospective-'+directory.name
    frozen['recovery'] = json.loads((directory/'research-risk-policy.json').read_text())['recovery']
    frozen['model']['version'] = frozen['version']+f"-{selected['width_ppm']}ppm"
    frozen['model']['valid_until'] = now+(hours+24)*3_600_000
    frozen['model']['dataset'] += '; prospective analysis sha256='+digest(directory/'analysis-spec.json')
    frozen['model']['out_of_sample_error'] += '; extended validity is observation-only; no production or risk-policy approval'
    write_new(directory/'frozen-policy.json', frozen)
    write_new(directory/'freeze.json', {'analysis_spec_sha256':digest(directory/'analysis-spec.json'),
                                      'policy_sha256':digest(directory/'frozen-policy.json'),
                                      'prepared_at_ms':now,'production_approved':False})
    print(directory)


def verify_artifacts(directory):
    binding = json.loads((directory/'freeze.json').read_text())
    if digest(directory/'analysis-spec.json') != binding['analysis_spec_sha256'] or digest(directory/'frozen-policy.json') != binding['policy_sha256']:
        raise ValueError('frozen plan or policy changed')
    spec = json.loads((directory/'analysis-spec.json').read_text())
    for name, expected in spec['files_sha256'].items():
        if digest(directory/name) != expected:
            raise ValueError(f'frozen artifact changed: {name}')
    return spec


def progress(directory):
    path = directory/'receipts.jsonl'
    if not path.exists():
        return {'sequence':0,'receipt_bytes':0}
    with path.open('rb') as stream:
        stream.seek(max(0, path.stat().st_size-65536))
        tail = stream.read()
    complete = tail.split(b'\n')[:-1]
    rows = []
    for line in complete:
        try:
            rows.append(json.loads(line))
        except (ValueError, UnicodeDecodeError):
            continue  # First line can start before the bounded tail read.
    feeds = {row['source']:row['at'] for row in rows}
    head = rows[-1] if rows else {}
    return {'sequence':head.get('sequence',0),'last_receipt_ms':head.get('at'),
            'last_receipt_hash':head.get('hash'),'receiver_last_receipt_ms':feeds,
            'receipt_bytes':path.stat().st_size}


def supervise(directory):
    directory = directory.resolve()
    spec = verify_artifacts(directory)
    with (directory/'supervisor.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX|fcntl.LOCK_NB)
        interrupted = [False]
        def stop(_signal, _frame):
            interrupted[0] = True
        signal.signal(signal.SIGTERM,stop); signal.signal(signal.SIGINT,stop)
        status = {'supervisor_pid':os.getpid(),'started_at_ms':time.time_ns()//1_000_000,
                  'state':'starting','production_approved':False}
        def save(state, **extra):
            status.update(state=state,updated_at_ms=time.time_ns()//1_000_000,**progress(directory),**extra)
            temp = directory/'status.tmp'
            with temp.open('w') as stream:
                json.dump(status,stream,indent=2);stream.write('\n');stream.flush();os.fsync(stream.fileno())
            temp.replace(directory/'status.json')
        child, awake = None, None
        try:
            save('starting')
            with (directory/'capture.log').open('ab') as log, (directory/'capture-result.jsonl').open('ab') as result:
                child = subprocess.Popen([str(directory/'fuse-capture'),'-config',str(directory/'frozen-policy.json'),
                                          '-output',str(directory),'-duration',str(spec['duration_hours'])+'h'],
                                         stdin=subprocess.DEVNULL,stdout=result,stderr=log,close_fds=True)
                status['capture_pid'] = child.pid
                if sys.platform == 'darwin' and shutil.which('caffeinate'):
                    awake = subprocess.Popen(['caffeinate','-i','-w',str(os.getpid())],stdin=subprocess.DEVNULL,
                                             stdout=subprocess.DEVNULL,stderr=log,close_fds=True)
                    status['idle_sleep_prevention_pid'] = awake.pid
                disk_failure = False
                while child.poll() is None:
                    if interrupted[0] or shutil.disk_usage(directory).free < 1024**3:
                        disk_failure = not interrupted[0]
                        child.terminate()
                        try:child.wait(timeout=10)
                        except subprocess.TimeoutExpired:child.kill();child.wait()
                        break
                    manifest = directory/'manifest.json'
                    if manifest.exists():
                        m=json.loads(manifest.read_text());status['deadline_ms']=m['frozen_at_ms']+m['duration_ms']
                    save('recording')
                    time.sleep(5)
                if interrupted[0]:
                    save('interrupted',capture_exit_code=child.returncode);return
                if disk_failure or child.returncode:
                    raise RuntimeError(f'capture failed; exit={child.returncode}, disk_floor={disk_failure}; inspect capture.log')
            deadline = json.loads((directory/'manifest.json').read_text())
            deadline = deadline['frozen_at_ms']+deadline['duration_ms']
            if time.time_ns()//1_000_000 < deadline:
                save('interrupted',capture_exit_code=child.returncode);return
            verify_artifacts(directory)
            save('verifying')
            with (directory/'verification.json').open('x') as stream:
                subprocess.run([str(directory/'fuse-capture'),'-verify','-output',str(directory)],stdout=stream,check=True)
                stream.flush();os.fsync(stream.fileno())
            subprocess.run([sys.executable,str(directory/'analyze.py'),str(directory),'--verifier',str(directory/'fuse-capture'),
                            '--output',str(directory/'analysis.json')],check=True)
            save('completed',capture_exit_code=child.returncode,analysis_path=str(directory/'analysis.json'))
        except Exception as exc:
            save('failed',error=str(exc))
            raise
        finally:
            if child is not None and child.poll() is None:
                child.terminate();child.wait(timeout=10)
            if awake is not None:
                awake.terminate();awake.wait(timeout=5)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['freeze','run','status'])
    parser.add_argument('--directory',type=Path,required=True)
    parser.add_argument('--calibration',type=Path,default=ROOT/'.local/pricing-calibration/calibration.json')
    parser.add_argument('--policy',type=Path,default=ROOT/'.local/pricing-calibration/policy.json')
    parser.add_argument('--hours',type=int,default=72)
    args=parser.parse_args()
    if args.action=='freeze':freeze(args.directory,args.calibration,args.policy,args.hours)
    elif args.action=='run':supervise(args.directory)
    else:print((args.directory/'status.json').read_text())

if __name__=='__main__':main()
