#!/usr/bin/env python3
"""Evaluate a frozen adaptive research trial after native receipt verification."""
import argparse
import gzip
import json
from pathlib import Path
import platform
import subprocess
import time

import numpy as np

from analyze_capture import effective_size
from calibrate_pricing import wilson
from capture_dataset import file_hash
from frozen_context_cdf import all_series
from full_raw_pipeline import price, bounds
from native_adaptive_data import build_rows
from prospective_capture_v2 import verify_artifacts


def replay(rows,models,candidates,start,end):
    """Prices use private online state per replay; past features stay available."""
    output=[];saved={}
    midpoint=start+(end-start)//2
    for mode,parts in (('continuous',[rows]),('restart_half',[
            [r for r in rows if r['start']<midpoint],[r for r in rows if r['start']>=midpoint]])):
        values={c:[] for c in candidates}
        for part in parts:
            if not part:continue
            _,reference=price(part,models['fixed'])
            alternatives=all_series(reference,models['frozen'])
            for c in candidates:values[c].extend(alternatives[c])
        saved[mode]=values
        intervals=[('full',start,end)]+[(f'quarter{i}',start+i*(end-start)//4,start+(i+1)*(end-start)//4) for i in range(4)]
        for c,series in values.items():
            for name,left,right in intervals:
                part=[p for p in series if left<=p['row']['start']<right]
                groups=[('all','all',part)]
                for axis,field,labels in (('activity','activity_state',('frozen','sparse','bursty','active','missing_history')),
                        ('regime','market_regime',('range','mixed','pump','dump','missing_history'))):
                    groups.extend((axis,label,[p for p in part if p['row'][field]==label]) for label in labels)
                for axis,label,group in groups:
                    result=bounds(group);n=result['windows'];wins=result['survived']
                    outcomes=[p['survived'] for p in group if p['survived'] is not None]
                    output.append(dict(candidate=c,mode=mode,interval=name,start=left,end=right,axis=axis,group=label,
                        **result,descriptive_wilson95=wilson(wins,n),descriptive_effective_windows=effective_size(outcomes)))
    pairs=[]
    for mode,values in saved.items():
        base=values['retained_open']
        for c,series in values.items():
            common=[(a,b) for a,b in zip(series,base) if a['survived'] is not None and b['survived'] is not None]
            pairs.append(dict(mode=mode,candidate=c,common_quotes=len(common),
                both_survive=sum(a['survived'] and b['survived'] for a,b in common),
                challenger_only_survives=sum(a['survived'] and not b['survived'] for a,b in common),
                retained_only_survives=sum(b['survived'] and not a['survived'] for a,b in common),
                width_disagreements=sum(a['width_ppm']!=b['width_ppm'] for a,b in zip(series,base))))
    return output,saved,pairs


def analyze(directory,verifier,output):
    directory=directory.resolve();spec=verify_artifacts(directory)
    if spec.get('analysis_kind')!='frozen-context-adaptive-v1':raise ValueError('wrong adaptive analysis specification')
    if file_hash(verifier)!=spec['files_sha256']['fuse-capture']:raise ValueError('verifier differs from frozen recorder')
    if platform.python_version()!=spec['python_version'] or np.__version__!=spec['numpy_version']:
        raise ValueError('analysis runtime differs from frozen versions')
    output=output.resolve();trace=output.with_name(output.stem+'-predictions.jsonl.gz')
    if output.exists() or trace.exists():raise ValueError('preserve existing analysis; use a new output')
    verified=json.loads(subprocess.check_output([str(verifier.resolve()),'-verify','-output',str(directory)],text=True))
    manifest,head=verified['manifest'],verified['head']
    start=manifest['frozen_at_ms'];end=start+manifest['duration_ms']
    if (manifest['policy']!=json.loads((directory/'frozen-policy.json').read_text())
            or manifest['duration_ms']!=spec['duration_hours']*3600000
            or not spec['training_cutoff_ms']<spec['prepared_at_ms']<=start):
        raise ValueError('capture does not match the frozen model, policy or horizon')
    if time.time_ns()//1000000<end:raise ValueError('fixed horizon has not elapsed')
    path=directory/'receipts.jsonl';receipt_digest=file_hash(path)
    with path.open() as stream:receipts=[json.loads(line) for line in stream]
    if (receipts[-1]['hash'] if receipts else None)!=head['hash']:raise ValueError('capture changed after verification')
    models=json.loads((directory/'adaptive-models.json').read_text())
    rows=build_rows(receipts,manifest['policy'],start,end,directory.name)
    summaries,saved,pairs=replay(rows,models,spec['candidates'],start,end)
    if file_hash(path)!=receipt_digest:raise ValueError('capture changed during analysis')
    verify_artifacts(directory)
    with gzip.open(trace,'xt',compresslevel=5) as stream:
        for mode,values in saved.items():
            for candidate,series in values.items():
                for p in series:
                    r=p['row']
                    stream.write(json.dumps(dict(mode=mode,candidate=candidate,start=r['start'],
                        entry_healthy=r['entry_healthy'],valid_outcome=r['valid'],activity=r['activity_state'],
                        regime=r['market_regime'],width_ppm=p['width_ppm'],paused=p['paused'],
                        survived=p['survived'],shadow_survived=p['shadow_survived'],
                        floor=p.get('frozen_floor'),level=p.get('frozen_level')),allow_nan=False)+'\n')
    healthy=sum(r['valid'] for r in rows);primary=next(s for s in summaries if s['candidate']==spec['primary_candidate']
        and s['mode']=='continuous' and s['interval']=='full' and s['axis']=='all')
    result=dict(analysis_kind=spec['analysis_kind'],analysis_spec_sha256=file_hash(directory/'analysis-spec.json'),
        manifest_sha256=file_hash(directory/'manifest.json'),receipts_sha256=receipt_digest,receipt_hash=head['hash'],
        predictions_sha256=file_hash(trace),frozen_at_ms=start,planned_end_ms=end,collection_deadline_elapsed=True,
        grid_windows=len(rows),healthy_windows=healthy,full_horizon_healthy_fraction=healthy/len(rows),
        collection_quality_met=healthy>=spec['minimum_healthy_windows'] and healthy/len(rows)>=spec['minimum_full_horizon_coverage'],
        primary_candidate=spec['primary_candidate'],primary=primary,summaries=summaries,paired=pairs,
        prospectively_frozen=True,production_approved=False,economics_validated=False,
        limitations=spec['limitations'],interpretation=spec['interpretation'])
    with output.open('x') as stream:json.dump(result,stream,indent=2,allow_nan=False);stream.write('\n')
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('directory',type=Path)
    p.add_argument('--verifier',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();r=analyze(a.directory,a.verifier,a.output)
    print(json.dumps(dict(collection_quality_met=r['collection_quality_met'],primary=r['primary']),indent=2))
