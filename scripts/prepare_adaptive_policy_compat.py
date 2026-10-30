#!/usr/bin/env python3
"""Prepare a disclosed policy-serialization repair outside a frozen trial.

Does not execute analysis, inspect outcomes, mutate the trial or alter pricing.
The unmodified supervisor/analyzer remains responsible for the original result.
"""
import argparse
import difflib
import json
from pathlib import Path
import shutil
import time

from capture_dataset import file_hash
from capture_policy_equivalence import compare_policy
from prospective_capture_v2 import verify_artifacts


def patched_source(source):
    changes=(
        ('from prospective_capture_v2 import verify_artifacts\n',
         'from prospective_capture_v2 import verify_artifacts\nfrom capture_policy_equivalence import compare_policy\n'),
        ("manifest['policy']!=json.loads((directory/'frozen-policy.json').read_text())",
         "not compare_policy(manifest['policy'],json.loads((directory/'frozen-policy.json').read_text()))['semantic_policy_match']"),
        ('prospectively_frozen=True,production_approved=False,economics_validated=False,',
         "prospectively_frozen=True,analysis_procedure='supplemental-policy-zero-compatibility-v1',\n        unmodified_frozen_analyzer=False,production_approved=False,economics_validated=False,"),
    )
    for old,new in changes:
        if source.count(old)!=1:raise ValueError('unexpected frozen analyzer; refuse automatic patch')
        source=source.replace(old,new)
    compile(source,'supplemental-analyze.py','exec')
    return source


def prepare(directory,output):
    directory=directory.resolve();output=output.resolve();spec=verify_artifacts(directory)
    manifest=json.loads((directory/'manifest.json').read_text())
    comparison=compare_policy(manifest['policy'],json.loads((directory/'frozen-policy.json').read_text()))
    source=(directory/'analyze.py').read_text();patched=patched_source(source)
    output.mkdir(parents=True,exist_ok=False)
    (output/'analyze.py').write_text(patched)
    shutil.copyfile(Path(__file__).with_name('capture_policy_equivalence.py'),output/'capture_policy_equivalence.py')
    shutil.copyfile(__file__,output/'prepare-source.py')
    (output/'analyzer.diff').write_text(''.join(difflib.unified_diff(source.splitlines(True),patched.splitlines(True),
        fromfile='original-frozen-analyze.py',tofile='supplemental-analyze.py')))
    hashes={name:file_hash(output/name) for name in ('analyze.py','capture_policy_equivalence.py','prepare-source.py','analyzer.diff')}
    result=dict(prepared_at_ms=time.time_ns()//1000000,original_directory=str(directory),
        original_analysis_spec_sha256=file_hash(directory/'analysis-spec.json'),
        original_analyzer_sha256=file_hash(directory/'analyze.py'),
        original_manifest_sha256=file_hash(directory/'manifest.json'),files_sha256=hashes,
        original_deadline_ms=manifest['frozen_at_ms']+manifest['duration_ms'],
        policy_comparison=comparison,frozen_files_verified=len(spec['files_sha256']),
        analysis_procedure='supplemental-policy-zero-compatibility-v1',
        scope='Only accept the exact Go Model omitted-int64-to-zero expansion and annotate procedural repair. Native verification, original horizon, source/model checks, data construction, pricing, replay, thresholds and all numerical calculations stay unchanged.',
        original_expected_behavior='Unmodified frozen analyzer rejects the JSON-object policy mismatch before pricing; preserve that failure and its supervisor status.',
        execution_environment=dict(PYTHONPATH=str(directory)),
        execution_arguments=['python3','-B',str(output/'analyze.py'),str(directory),'--verifier',str(directory/'fuse-capture'),'--output',str(output/'analysis.json')],
        analysis_executed=False,pricing_outcomes_inspected=False,original_trial_modified=False,
        prospective_model_unchanged=True,unmodified_frozen_analyzer=False,
        production_approved=False,economics_validated=False,
        interpretation='A numerical replay using the frozen model with a disclosed validation repair is supplemental evidence. It does not erase the original procedural failure or by itself establish reliable frozen end-to-end completion.')
    verify_artifacts(directory)
    with (output/'compatibility-spec.json').open('x') as stream:json.dump(result,stream,indent=2);stream.write('\n')
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--directory',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);a=p.parse_args();r=prepare(a.directory,a.output)
    print(json.dumps(dict(analysis_executed=r['analysis_executed'],files_sha256=r['files_sha256']),indent=2))
