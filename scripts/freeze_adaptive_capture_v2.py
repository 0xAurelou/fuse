#!/usr/bin/env python3
"""Version 2: prepare a future adaptive trial with native-canonical policy.

The original freezer and all existing trial packets remain unchanged.

Preparation never starts collection or certifies a candidate's calibration.
The selected archived model is copied without refitting or later-data selection.
"""
import argparse
from datetime import datetime,timezone
import json
from pathlib import Path
import platform
import shutil
import subprocess

import numpy as np

from capture_dataset import file_hash
from canonical_capture_policy import canonical_policy
from frozen_context_cdf import VARIANTS
from native_adaptive_data import SPEC as INPUT_SPEC
from prospective_capture_v2 import write_new,wall_ms
from research_frozen_market import DEPENDENCIES
from research_startup_admission import verify_code

ROOT=Path(__file__).resolve().parent.parent


def bindings(research):
    result=json.loads((research/'research.json').read_text());verify_code(research,result)
    for name,key in (('selection.json','selection_sha256'),('models.json','models_sha256'),
                     ('later-predictions.jsonl.gz','later_predictions_sha256')):
        if file_hash(research/name)!=result[key]:raise ValueError('research artifact changed: '+name)
    audit=json.loads((research/'audit.json').read_text())
    if (not audit['completed'] or audit.get('research_sha256')!=file_hash(research/'research.json')
            or file_hash(ROOT/'scripts/audit_frozen_market.py')!=audit['audit_source_sha256']):
        raise ValueError('a completed matching research audit is required')
    parent_path=Path(result['previous'])/'research.json'
    if file_hash(parent_path)!=result['previous_sha256']:raise ValueError('parent research changed')
    parent=json.loads(parent_path.read_text());temporal_dir=Path(parent['previous'])
    if file_hash(temporal_dir/'research.json')!=parent['previous_sha256']:raise ValueError('temporal research changed')
    temporal=json.loads((temporal_dir/'research.json').read_text())
    if file_hash(temporal_dir/'models.json')!=temporal['models_sha256']:raise ValueError('retained model changed')
    selection=json.loads((research/'selection.json').read_text())
    if selection['selected']!=result['selected'] or result['selected'] not in VARIANTS:raise ValueError('selection differs')
    fits=json.loads((research/'models.json').read_text())['22']
    cutoff=max(datetime.fromisoformat(f['cutoff']).replace(tzinfo=timezone.utc).timestamp()*1000 for f in fits.values())
    model=dict(fixed=json.loads((temporal_dir/'models.json').read_text())['14']['fixed_retained'],frozen=fits)
    return result,audit,model,int(cutoff)


def freeze(directory,research,policy,recorder):
    result,audit,models,cutoff=bindings(research)
    now=wall_ms()
    if cutoff>=now:raise ValueError('training must end before preparation')
    if directory.exists():raise ValueError('preserve old runs; choose a new directory')
    if shutil.disk_usage(directory.parent).free<10*1024**3:raise ValueError('at least 10 GiB free disk required')
    original=json.loads(policy.read_text())
    if original['duration_ms']!=30000 or original['max_gap_ms']!=8000 or original['disagreement_ms']!=1500:
        raise ValueError('native policy differs from frozen research health rules')
    directory.mkdir(mode=0o700)
    names=tuple(dict.fromkeys(DEPENDENCIES+('native_adaptive_data.py','analyze_adaptive_capture.py',
        'freeze_adaptive_capture.py','freeze_adaptive_capture_v2.py',
        'canonical_capture_policy.py','capture_policy_equivalence.py','prospective_capture_v2.py','audit_frozen_market.py','calibrate_pricing.py')))
    for name in names:shutil.copyfile(ROOT/'scripts'/name,directory/name)
    shutil.copyfile(ROOT/'scripts/analyze_adaptive_capture.py',directory/'analyze.py')
    shutil.copyfile(ROOT/'scripts/prospective_capture_v2.py',directory/'supervisor.py')
    shutil.copyfile(recorder,directory/'fuse-capture');(directory/'fuse-capture').chmod(0o700)
    for source,name in ((research/'research.json','research.json'),(research/'audit.json','research-audit.json'),
            (research/'selection.json','selection.json'),(policy,'source-policy.json')):
        shutil.copyfile(source,directory/name)
    # The binary is the executable authority. Also retain the changed native
    # source, because the Git commit alone does not include workspace changes.
    for relative in ('engine/cmd/fuse-capture/main.go','engine/internal/capture/recorder.go',
            'engine/internal/oracle/collector.go','engine/internal/capture/wall_deadline.go',
            'engine/go.mod','engine/go.sum','docs/ORACLE_POLICY.md','docs/RISK_AND_CAPTURE.md'):
        target=directory/'native-source'/relative;target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(ROOT/relative,target)
    write_new(directory/'adaptive-models.json',models)
    files={str(p.relative_to(directory)):file_hash(p) for p in directory.rglob('*') if p.is_file()}
    selected=result['selected'];candidates=list(dict.fromkeys((selected,'retained_open','timing:priceable_open')))
    spec=dict(version=1,analysis_kind='frozen-context-adaptive-v1',prepared_at_ms=now,duration_hours=8,
        training_cutoff_ms=cutoff,primary_candidate=selected,candidates=candidates,target_survival=.48,tolerance=.05,
        minimum_healthy_windows=400,minimum_full_horizon_coverage=.9,files_sha256=files,input_spec=INPUT_SPEC,
        research_sha256=file_hash(research/'research.json'),selection_sha256=file_hash(research/'selection.json'),
        audit_sha256=file_hash(research/'audit.json'),python_version=platform.python_version(),numpy_version=np.__version__,
        window_grid='Original manifest frozen_at_ms + k*30000; five-minute clean history before quoting',
        replays='Primary continuous full 8h. Descriptive private restart at 4h retains only past feature history, resets every online pricing accumulator. Two-hour blocks and activity/regime groups use pre-entry labels.',
        model_rule='Archived 22-date fitted CDFs and 14-date retained benchmark. No fit, search, selection, threshold change or early success stopping during capture. Exact declared matured-label online updates remain enabled.',
        quote_availability='Report full grid, entry decisions, clean evaluable outcomes, and retained quotes separately; censored outcomes never erase pre-entry decisions.',
        interpretation='Point rates and descriptive Wilson intervals against [0.43,0.53] are diagnostics. Serial dependence, sparse conditional groups and reused restart paths preclude independent per-cell guarantees. A completed run can fail pricing calibration.',
        limitations='Selection improves aggregate earlier score but frozen raw January/August and later September/October do not consistently meet target. Market context adds little beyond the feedback change. Both local receivers share one upstream oracle. Native paired-receipt features differ from historical single-feed training. Fees, costs, strategies, demand and LP exposure are not evaluated.',
        role='Prospective falsification of an unvalidated research challenger and retained control; no production promotion',
        collection_only=True,production_approved=False,economics_validated=False,
        native_policy_canonicalization='Exact frozen recorder emits an empty offline 1ms fixture before final policy binding; only omitted Model integer zeros may expand. This is preparation, not a live market freeze or validation.',
        source_commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip())
    write_new(directory/'analysis-spec.json',spec)
    frozen=original;frozen['mode']='paper';frozen['version']='adaptive-observation-'+directory.name
    frozen['model'].update(version=frozen['version'],base_width_ppm=314,base_width_bps=0,control_width_bps=0,
        volatility_factor=0,valid_until=now+32*3600000,
        dataset='Observation transport only; adaptive widths are evaluated by frozen analyze.py; analysis sha256='+file_hash(directory/'analysis-spec.json'),
        out_of_sample_error='Unvalidated adaptive falsification trial; transport width is not the candidate prediction')
    frozen,probe=canonical_policy(frozen,directory/'fuse-capture',directory/'policy-probe')
    write_new(directory/'frozen-policy.json',frozen)
    write_new(directory/'freeze.json',dict(analysis_spec_sha256=file_hash(directory/'analysis-spec.json'),
        policy_sha256=file_hash(directory/'frozen-policy.json'),prepared_at_ms=now,production_approved=False,
        native_policy_canonicalized=True,policy_probe_report_sha256=file_hash(directory/'policy-probe/report.json')))
    return spec


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--directory',type=Path,required=True)
    p.add_argument('--research',type=Path,required=True);p.add_argument('--policy',type=Path,required=True)
    p.add_argument('--recorder',type=Path,required=True);a=p.parse_args()
    r=freeze(a.directory.resolve(),a.research.resolve(),a.policy.resolve(),a.recorder.resolve())
    print(json.dumps(dict(directory=str(a.directory.resolve()),primary_candidate=r['primary_candidate'],capture_started=False),indent=2))
