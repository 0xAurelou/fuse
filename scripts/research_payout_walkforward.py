#!/usr/bin/env python3
"""Fit earlier asset histories and score each later sampled date exactly once."""
import argparse
import gzip
import json
from pathlib import Path
import shutil
import time

from payout_empirical import EmpiricalPredictor
from payout_risk import weekend
from payout_walkforward import (FAMILIES, SPEC, VARIANTS, fit_origin, floor_summary,
    forecasts, metrics, quote, reference, research_screen, schedule)
from research_payout_risk import ASSETS, MULTIPLIERS, digest, dump, load_parent

SOURCES = ('payout_walkforward.py','research_payout_walkforward.py','payout_empirical.py',
           'payout_risk.py','research_payout_risk.py','screen_payout_candidates.py')


def save_gzip(path, value):
    with gzip.open(path,'xt',compresslevel=5) as stream:
        json.dump(value,stream,separators=(',',':'),allow_nan=False)
        stream.write('\n')


def study_asset(asset, rows, output):
    dates = schedule(rows,asset)
    directory=output/asset;directory.mkdir();(directory/'origins').mkdir()
    references={family:[] for family in FAMILIES}
    later=[r for r in rows if r['period'] in dates]
    all_records={(m,v):[] for m in MULTIPLIERS for v in VARIANTS}
    origins=[]
    with gzip.open(directory/'predictions.jsonl.gz','xt',compresslevel=5) as stream:
        for day in dates:
            packet=fit_origin(rows,asset,day,references)
            path=directory/'origins'/(day+'.json.gz');save_gzip(path,packet)
            binding=dict(period=day,model_sha256=digest(path),training_dates=packet['movement']['training_dates'],
                         calibration_counts=packet['calibration_counts'])
            origins.append(binding)
            # The whole date is frozen before any of its labels join calibration.
            pending={family:[] for family in FAMILIES}
            predictor=EmpiricalPredictor(packet['movement'])
            for r in (r for r in later if r['period']==day):
                raw,values=forecasts(r,packet)
                for m in MULTIPLIERS:
                    for variant in VARIANTS:
                        p=quote(r,dict(p0=None,floor=None,calibrated0=False,calibrated_floor=False)
                                if variant=='minimum_width_floor' else values[variant],m,variant,predictor)
                        all_records[m,variant].append(p)
                        stream.write(json.dumps(dict(asset=asset,period=day,start=r['start'],multiplier=m,
                            variant=variant,**p),separators=(',',':'),allow_nan=False)+'\n')
                if r['valid'] and r['adaptive_features'] is not None:
                    for family in FAMILIES:
                        pending[family].append(reference(r,raw[family],family))
            for family in FAMILIES:references[family].extend(pending[family])
            print(json.dumps(dict(asset=asset,origin=day,training_dates=len(binding['training_dates']),
                                  calibration_references=binding['calibration_counts']['timing'])),flush=True)
    results={}
    for m in MULTIPLIERS:
        variants={}
        for variant in VARIANTS:
            records=all_records[m,variant]
            result=metrics(later,records,m)
            result['screen']=research_screen(result,m,variant)
            result['calendar_groups']={}
            for group in ('weekday','weekend'):
                pairs=[(r,p) for r,p in zip(later,records) if weekend(r)==(group=='weekend')]
                result['calendar_groups'][group]=metrics([r for r,p in pairs],[p for r,p in pairs],m)
            variants[variant]=result
        results[str(m)]=dict(variants=variants,floor=floor_summary(later,m),
            daily_floor=[dict(period=day,**floor_summary([r for r in later if r['period']==day],m)) for day in dates],
            qualifying_variants=[v for v,r in variants.items() if r['screen']['qualifies']])
    save_gzip(directory/'calibration-references.json.gz',references)
    result=dict(asset=asset,evaluated_dates=dates,warmup_dates=sorted({r['period'] for r in rows})[:6],
                unique_evaluated_entries=len(later),origins=origins,results=results,
                artifact_sha256={name:digest(directory/name) for name in
                    ('predictions.jsonl.gz','calibration-references.json.gz')},no_promotion=True)
    dump(directory/'research.json',result)
    return result


def declare(parent, output):
    if output.exists():raise ValueError('use a new output directory')
    output.mkdir(parents=True);(output/'source').mkdir()
    hashes={}
    for name in SOURCES:
        path=Path(__file__).with_name(name);shutil.copyfile(path,output/'source'/name);hashes[name]=digest(path)
    protocol=dict(spec=SPEC,parent=str(parent.resolve()),parent_sha256=digest(parent/'research.json'),
                  source_sha256=hashes,free_source='https://docs.tardis.dev/api/http-api-reference',
                  data_access='Existing first-of-month raw samples; no newly obtained continuous history',
                  coefficients_or_selection_reused_from_previous_fits=False)
    dump(output/'protocol.json',protocol)
    return protocol


def verify_sources(output):
    protocol=json.loads((output/'protocol.json').read_text())
    for name,sha in protocol['source_sha256'].items():
        if digest(output/'source'/name)!=sha or digest(Path(__file__).with_name(name))!=sha:
            raise ValueError('declared source differs: '+name)
    if digest(Path(protocol['parent'])/'research.json')!=protocol['parent_sha256']:
        raise ValueError('parent differs')
    return protocol


def run(output):
    start=time.monotonic();protocol=verify_sources(output)
    rows,_,bindings=load_parent(Path(protocol['parent']))
    results=[study_asset(a,rows[a],output) for a in ASSETS]
    result=dict(protocol=protocol,protocol_sha256=digest(output/'protocol.json'),bindings=bindings,
                research_sha256={a:digest(output/a/'research.json') for a in ASSETS},
                elapsed_seconds=time.monotonic()-start,
                unique_evaluated_entries={r['asset']:r['unique_evaluated_entries'] for r in results},
                qualifying_variants={r['asset']:{m:v['qualifying_variants'] for m,v in r['results'].items()} for r in results},
                no_promotion=True,live_policy_changed=False)
    dump(output/'research.json',result)
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--parent',type=Path);parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--declare',action='store_true');args=parser.parse_args()
    r=declare(args.parent,args.output) if args.declare else run(args.output)
    print(json.dumps(dict(completed=not args.declare,output=str(args.output),qualifying=r.get('qualifying_variants'))))
