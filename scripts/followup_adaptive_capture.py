#!/usr/bin/env python3
"""Wait for an existing frozen capture, then run its pinned supplemental replay.

No recording, pricing change, process termination, horizon extension or restart.
Only static bindings/status/process metadata are read before the original end.
"""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import time


def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda:f.read(1048576),b''):h.update(block)
    return h.hexdigest()


def read(path):return json.loads(path.read_text())


def write_new(path,value):
    with path.open('x') as f:json.dump(value,f,indent=2);f.write('\n')


def verify(trial,compatibility):
    freeze=read(trial/'freeze.json');spec=read(trial/'analysis-spec.json')
    if sha(trial/'analysis-spec.json')!=freeze['analysis_spec_sha256'] or sha(trial/'frozen-policy.json')!=freeze['policy_sha256']:
        raise ValueError('original freeze binding changed')
    for name,digest in spec['files_sha256'].items():
        if sha(trial/name)!=digest:raise ValueError('original frozen artifact changed: '+name)
    compat=read(compatibility/'compatibility-spec.json')
    if (sha(trial/'analysis-spec.json')!=compat['original_analysis_spec_sha256']
            or sha(trial/'manifest.json')!=compat['original_manifest_sha256']
            or str(trial)!=compat['original_directory']):
        raise ValueError('supplemental packet belongs to another original freeze')
    for name,digest in compat['files_sha256'].items():
        if sha(compatibility/name)!=digest:raise ValueError('supplemental source changed: '+name)
    manifest=read(trial/'manifest.json');end=manifest['frozen_at_ms']+manifest['duration_ms']
    if end!=compat['original_deadline_ms']:raise ValueError('supplemental deadline differs')
    return spec,compat,end


def process(pid,marker):
    p=subprocess.run(['/bin/ps','-p',str(pid),'-o','stat=','-o','command='],
                     text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=5)
    if p.stderr.strip():raise RuntimeError('cannot inspect original process: '+p.stderr.strip())
    if p.returncode==1 and not p.stdout.strip():return False
    if p.returncode or not p.stdout.strip():raise RuntimeError('unexpected process observation failure')
    state,command=p.stdout.strip().split(None,1)
    return not state.startswith('Z') and marker in command


def phase(now,end,supervisor_alive,recorder_alive,status):
    if supervisor_alive:return 'waiting_original_supervisor'
    if recorder_alive:return 'orphaned_recorder_requires_attention'
    if now<end:return 'original_ended_before_deadline'
    if status not in ('failed','completed'):return 'original_terminal_state_requires_attention'
    return 'ready_for_supplemental_verification'


def prepare(trial,compatibility,output):
    trial=trial.resolve();compatibility=compatibility.resolve();output=output.resolve()
    spec,compat,end=verify(trial,compatibility);status=read(trial/'status.json')
    if time.time_ns()//1000000>=end:raise ValueError('prepare this follow-up before the original deadline')
    if (compatibility/'analysis.json').exists() or (compatibility/'analysis-predictions.jsonl.gz').exists():
        raise ValueError('preserve existing supplemental outputs')
    supervisor=status['supervisor_pid'];recorder=status['capture_pid']
    if not process(supervisor,str(trial/'supervisor.py')) or not process(recorder,str(trial/'fuse-capture')):
        raise ValueError('both original process handles must be confirmed live')
    output.mkdir(parents=True,exist_ok=False);shutil.copyfile(__file__,output/'followup.py')
    plan=dict(version=1,prepared_at_ms=time.time_ns()//1000000,original_directory=str(trial),
        compatibility_directory=str(compatibility),original_deadline_ms=end,
        original_supervisor_pid=supervisor,original_recorder_pid=recorder,
        analysis_spec_sha256=sha(trial/'analysis-spec.json'),compatibility_spec_sha256=sha(compatibility/'compatibility-spec.json'),
        followup_source_sha256=sha(output/'followup.py'),python_version=platform.python_version(),
        python_executable=sys.executable,poll_seconds=10,post_deadline_attention_ms=300000,
        original_frozen_files_verified=len(spec['files_sha256']),
        action='After original deadline and both original handles exit, preserve/read original terminal status and native verification, recheck all bindings, then execute exact supplemental command/environment declared in compatibility-spec.json.',
        no_capture_restart=True,no_horizon_extension=True,no_pricing_retuning=True,
        live_pricing_outcomes_inspected=False,goal_complete=False,production_approved=False)
    write_new(output/'followup-spec.json',plan)
    return plan


def run(output):
    output=output.resolve();plan=read(output/'followup-spec.json')
    if sha(Path(__file__))!=plan['followup_source_sha256'] or platform.python_version()!=plan['python_version']:
        raise ValueError('follow-up source/runtime differs from preparation')
    trial=Path(plan['original_directory']);compatibility=Path(plan['compatibility_directory'])
    lock=(output/'followup.lock').open('a')
    fcntl.flock(lock.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
    if (output/'execution.json').exists() or (output/'result.json').exists():
        raise ValueError('preserve earlier follow-up execution; never replay automatically')
    previous=None;terminal_wait_started=None;last_binding_check=None
    def save(state,**extra):
        nonlocal previous
        event=dict(state=state,updated_at_ms=time.time_ns()//1000000,followup_pid=os.getpid(),
                   original_deadline_ms=plan['original_deadline_ms'],production_approved=False)
        event.update(extra)
        temporary=output/'status.tmp';temporary.write_text(json.dumps(event,indent=2)+'\n');temporary.replace(output/'status.json')
        if state!=previous:
            with (output/'events.jsonl').open('a') as f:f.write(json.dumps(event)+'\n')
            print(json.dumps(event),flush=True);previous=state
        return event
    try:
        while True:
            if last_binding_check is None or time.monotonic()-last_binding_check>=60:
                verify(trial,compatibility);last_binding_check=time.monotonic()
            if sha(trial/'analysis-spec.json')!=plan['analysis_spec_sha256'] or sha(compatibility/'compatibility-spec.json')!=plan['compatibility_spec_sha256']:
                raise ValueError('follow-up preparation bindings changed')
            now=time.time_ns()//1000000;end=plan['original_deadline_ms'];status=read(trial/'status.json')
            if (status['supervisor_pid']!=plan['original_supervisor_pid']
                    or status['capture_pid']!=plan['original_recorder_pid']):
                raise ValueError('original process identities changed in status')
            try:
                supervisor=process(plan['original_supervisor_pid'],str(trial/'supervisor.py'))
                recorder=process(plan['original_recorder_pid'],str(trial/'fuse-capture'))
            except (RuntimeError,subprocess.TimeoutExpired) as exc:
                save('process_observation_retry',error=str(exc));time.sleep(plan['poll_seconds']);continue
            state=phase(now,end,supervisor,recorder,status['state'])
            if now>=end and terminal_wait_started is None:terminal_wait_started=time.monotonic()
            save(state,original_supervisor_alive=supervisor,original_recorder_alive=recorder,
                 original_status=status['state'])
            if state=='ready_for_supplemental_verification':break
            drained_too_long=(terminal_wait_started is not None
                and (time.monotonic()-terminal_wait_started)*1000>plan['post_deadline_attention_ms'])
            if state!='waiting_original_supervisor' or drained_too_long:
                raise ValueError('original capture requires attention: '+state)
            time.sleep(plan['poll_seconds'])
        # Native verification must have succeeded in the original supervisor.
        # The supplemental analyzer independently verifies the chain again.
        original_proof=read(trial/'verification.json');manifest=read(trial/'manifest.json')
        if original_proof['manifest']!=manifest:raise ValueError('original native verification manifest differs')
        spec,compat,end=verify(trial,compatibility)
        if time.time_ns()//1000000<end:raise ValueError('original deadline has not elapsed')
        args=compat['execution_arguments']
        expected=['python3','-B',str(compatibility/'analyze.py'),str(trial),'--verifier',str(trial/'fuse-capture'),
                  '--output',str(compatibility/'analysis.json')]
        if args!=expected or compat['execution_environment']!={'PYTHONPATH':str(trial)}:
            raise ValueError('unexpected supplemental execution declaration')
        execution=dict(started_at_ms=time.time_ns()//1000000,original_terminal_status=status,
            original_verification_sha256=sha(trial/'verification.json'),compatibility_spec_sha256=sha(compatibility/'compatibility-spec.json'),
            arguments=args,environment=compat['execution_environment'],original_deadline_ms=end)
        write_new(output/'execution.json',execution);save('running_supplemental_analysis')
        env=dict(os.environ,**compat['execution_environment'],OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='1',MKL_NUM_THREADS='1')
        with (output/'analysis.stdout').open('x') as stdout,(output/'analysis.stderr').open('x') as stderr:
            proc=subprocess.run([plan['python_executable'],*args[1:]],cwd=compatibility,env=env,stdout=stdout,stderr=stderr)
        if proc.returncode:raise ValueError('supplemental analyzer exited '+str(proc.returncode))
        result=read(compatibility/'analysis.json');verify(trial,compatibility)
        if result.get('analysis_procedure')!='supplemental-policy-zero-compatibility-v1' or result.get('unmodified_frozen_analyzer') is not False:
            raise ValueError('supplemental repair disclosure missing')
        summary=dict(completed_at_ms=time.time_ns()//1000000,supplemental_analysis_completed=True,
            original_terminal_status_preserved=status['state'],original_deadline_ms=end,
            analysis_sha256=sha(compatibility/'analysis.json'),predictions_sha256=sha(compatibility/'analysis-predictions.jsonl.gz'),
            collection_quality_met=result['collection_quality_met'],original_trial_modified=False,
            unmodified_frozen_analyzer=False,goal_complete=False,production_approved=False,economics_validated=False)
        write_new(output/'result.json',summary);save('supplemental_analysis_completed',**summary)
    except Exception as exc:
        save('failed_requires_attention',error=str(exc));raise
    finally:
        fcntl.flock(lock.fileno(),fcntl.LOCK_UN);lock.close()


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('action',choices=('prepare','run'))
    p.add_argument('--directory',type=Path);p.add_argument('--compatibility',type=Path)
    p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    if a.action=='prepare':prepare(a.directory,a.compatibility,a.output)
    else:run(a.output)
