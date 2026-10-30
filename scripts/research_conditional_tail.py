#!/usr/bin/env python3
"""Acceptance-aware calibration of frozen active-tail daily asset models."""
import argparse
from collections import Counter
import gzip
import json
import math
from pathlib import Path
import shutil
import time

import numpy as np

from active_tail_payout import admissible,forecast
from audit_payout_walkforward import same
from conditional_tail_payout import SPEC,VARIANTS,chosen,levels,quote,reference
from fetch_tardis_liquidity_trial import origin
from payout_empirical import EmpiricalPredictor
from research_active_tail import (evaluation_rows,independent_quote as native_independent,manual_cdf,manual_forecast,verify_plan as verify_parent)
from research_asset_corridors import source_files
from research_flat_aware_payout import inputs as previous_inputs,selected
from research_payout_risk import digest,dump
from research_trial_payout import save_gzip
from screen_payout_candidates import assess
from trial_payout import clean,metrics


def declare(parent,output):
    if output.exists():raise ValueError('Use a new conditional-tail packet')
    verify_parent(parent);meta=json.loads((parent/'research.json').read_text())
    output.mkdir(parents=True);(output/'source').mkdir();paths=sorted(set(source_files()+[Path(__file__).resolve()]))
    for p in paths:shutil.copyfile(p,output/'source'/p.name)
    plan=dict(spec=SPEC,parent=str(parent.resolve()),parent_sha256=digest(parent/'research.json'),
        source_sha256={p.name:digest(p) for p in paths},declared_before_replay=True,parent_outcomes_inspected=True,
        live_policy_changed=False,no_promotion=True)
    dump(output/'protocol.json',plan);return plan


def verify_plan(output):
    p=json.loads((output/'protocol.json').read_text());parent=Path(p['parent'])
    for n,sha in p['source_sha256'].items():
        if digest(output/'source'/n)!=sha or digest(Path(__file__).with_name(n))!=sha:raise ValueError('Conditional source differs: '+n)
    if digest(parent/'research.json')!=p['parent_sha256']:raise ValueError('Conditional parent differs')
    verify_parent(parent);return p


def summarize(rows,records):
    result={}
    for phase in ('earlier_oof','trial'):
        result[phase]={}
        for m in (100,1000):
            result[phase][str(m)]={}
            for v in VARIANTS:
                groups={}
                for cohort in ('matched','all_clean'):
                    groups[cohort]={}
                    for g in ('overall','weekday','weekend'):
                        ids=selected(rows,phase,cohort,g);groups[cohort][g]=metrics([rows[i] for i in ids],[records[m,v][i] for i in ids],m)
                s=groups['matched']['overall'];p=s['pooled'];checked=assess(dict(policy={'name':v},index=VARIANTS.index(v),daily=s['daily'],minimum_daily_availability=s['minimum_daily_availability'],pooled_survival=p['survival'],availability=p['availability'],offered=p['offered'],eligible=p['eligible']),m)
                groups['screen']=dict(qualifies=checked['eligible'],reasons=checked['reasons']);result[phase][str(m)][v]=groups
    return result


def manual_reference(r,p):
    minimum=max(1,math.ceil(10**9/r['entry']));required=max(1,-(-(r['move']+1)*10**9//r['entry']))
    from payout_risk import weekend
    return dict(asset=r['asset'],start=r['start'],expiry=r['expiry'],period=r['period'],weekend=weekend(r),p0=p['p0'],
        admission=manual_cdf(minimum,r,p),win_threshold=manual_cdf(required,r,p) if required<=50000000 else None)


def verify_levels(packet,refs,day,asset):
    if any(r['asset']!=asset or r['period']>=day for r in refs) or len({r['start'] for r in refs})!=len(refs):raise ValueError('Invalid audit calibration population')
    refs=[r for r in refs if r['expiry']+30000<origin(day)]
    for v in VARIANTS:
        for m in (100,1000):
            for g in ('global','weekday','weekend'):
                part=[r for r in refs if g=='global' or r['weekend']==(g=='weekend')];dates=sorted({r['period'] for r in part})
                keep=dates[-(3 if m==100 else 10):] if v=='conditional_recent' else dates
                part=[r for r in part if r['period'] in keep];saved=packet[v][str(m)][g];same(saved['dates'],keep);same(saved['n'],len(part))
                if not part:same(saved,dict(level=.95/m,supported=False,n=0,dates=[],candidates=[],selected=None));continue
                counts=Counter(r['period'] for r in part);weights=np.asarray([1/counts[r['period']]/len(counts) for r in part]);a=np.asarray([r['admission'] for r in part]);p=np.asarray([r['p0'] for r in part]);u=np.asarray([r['win_threshold'] if r['win_threshold'] is not None else math.inf for r in part]);codes=np.asarray([keep.index(r['period']) for r in part]);choices=[]
                if len(saved['candidates'])!=81:raise ValueError('Calibration grid differs')
                for index,cell in enumerate(saved['candidates']):
                    level=.95/m*2**((index-48)/8);ids=np.flatnonzero((a<=level)&(p<level));n=len(ids);nd=len(np.unique(codes[ids]));mass=float(np.sum(weights[ids]));win=float(np.sum(weights[ids[u[ids]<=level]]));rate=win/mass if mass else None
                    estimate=(n*rate+32*level)/(n+32) if rate is not None else None;support=n>=200 and nd>=3
                    expected=dict(level=level,offered=n,offered_dates=nd,weighted_offer_mass=mass,conditional_survival=rate,smoothed_survival=estimate,supported=support);same(cell,expected)
                    if support and estimate<=.95/m:choices.append(cell)
                selected=choices[-1] if choices else None;same(saved['selected'],selected);same(saved['supported'],bool(choices));same(saved['level'],selected['level'] if selected else .95/m)


def independent_quote(r,m,v,packet,p):
    level,source=chosen(packet,r,m,v);proxy=dict(packet,levels={str(m):{g:dict(level=level,supported=True) for g in ('global','weekday','weekend')}})
    result=native_independent(r,m,'active_calibrated',proxy,{},p);result['calibration_source']=source;return result


def study_asset(asset,earlier,rows,parent,output,auditing=False):
    root=output/asset;meta=json.loads((parent/asset/'research.json').read_text());later=evaluation_rows(earlier,rows);refs=[];records={(m,v):[] for m in (100,1000) for v in VARIANTS};origins=[];count=0
    if not auditing:root.mkdir();(root/'origins').mkdir()
    saved=json.loads((root/'research.json').read_text()) if auditing else None
    if auditing and digest(root/'predictions.jsonl.gz')!=saved['predictions_sha256']:raise ValueError('Conditional trace differs')
    with gzip.open(root/'predictions.jsonl.gz','rt' if auditing else 'xt',compresslevel=5) as stream:
        for item in meta['origins']:
            day=item['period'];path=parent/asset/'origins'/(day+'.json.gz')
            if digest(path)!=item['sha256']:raise ValueError('Conditional model differs')
            with gzip.open(path,'rt') as s:packet=json.load(s)
            level_path=root/'origins'/(day+'.json.gz')
            if auditing:
                with gzip.open(level_path,'rt') as s:cal=json.load(s)
                verify_levels(cal,refs,day,asset)
                expected=saved['origins'][len(origins)]
                if expected['period']!=day or digest(level_path)!=expected['sha256']:raise ValueError('Conditional origin differs')
            else:cal=levels(refs,day,asset);save_gzip(level_path,cal)
            origins.append(dict(period=day,sha256=digest(level_path)));packet['conditional_levels']=cal;pending=[];predictor=EmpiricalPredictor(packet['empirical']);counts={v:0 for v in VARIANTS}
            for r in (r for r in later if r['period']==day):
                p=(manual_forecast if auditing else forecast)(r,packet['model']) if admissible(r) else None
                ref=(manual_reference if auditing else reference)(r,p) if clean(r) and p is not None else None;stored_ref=None
                for m in (100,1000):
                    for v in VARIANTS:
                        value=independent_quote(r,m,v,packet,p) if auditing else quote(r,m,v,packet,predictor,p);records[m,v].append(value);count+=1
                        trace=dict(asset=asset,period=day,start=r['start'],multiplier=m,variant=v,reference=ref,**value)
                        if auditing:
                            old=json.loads(stream.readline());same(old,trace);stored_ref=old['reference']
                        else:stream.write(json.dumps(trace,separators=(',',':'),allow_nan=False)+'\n')
                        if m==1000:counts[v]+=clean(r) and value['offered']
                if ref is not None:pending.append(stored_ref if auditing else ref)
            refs.extend(pending);print(json.dumps(dict(asset=asset,origin=day,auditing=auditing,x1000_offers=counts)),flush=True)
        if auditing and stream.readline():raise ValueError('Extra conditional decisions')
    result=dict(asset=asset,origins=origins,results=summarize(later,records),decisions=count,predictions_sha256=digest(root/'predictions.jsonl.gz'),no_promotion=True)
    if auditing:same(saved,result)
    else:dump(root/'research.json',result)
    return result


def execute(output,auditing=False):
    started=time.monotonic();plan=verify_plan(output);parent=Path(plan['parent']);audit=json.loads((parent/'audit.json').read_text())
    if not audit['passed'] or audit['research_sha256']!=plan['parent_sha256']:raise ValueError('Matching parent audit required')
    prior=json.loads((parent/'protocol.json').read_text());earlier,rows,_,_,binding=previous_inputs(json.loads((Path(prior['parent'])/'protocol.json').read_text()));reports=[]
    for a in ('ETH','HYPE'):reports.append(study_asset(a,earlier[a],rows[a],parent,output,auditing))
    verify_plan(output)
    if auditing:
        meta=json.loads((output/'research.json').read_text());same(meta['bindings'],binding)
        if meta['protocol_sha256']!=digest(output/'protocol.json') or meta['parent_audit_sha256']!=digest(parent/'audit.json'):raise ValueError('Conditional binding differs')
        for a,sha in meta['research_sha256'].items():
            if digest(output/a/'research.json')!=sha:raise ValueError('Conditional asset differs')
        result=dict(passed=True,research_sha256=digest(output/'research.json'),auditor_sha256=digest(Path(__file__)),assets=[dict(asset=r['asset'],decisions_independently_replayed=r['decisions'],calibration_population_and_exposure_verified=True) for r in reports]);dump(output/'audit.json',result)
    else:
        result=dict(protocol_sha256=digest(output/'protocol.json'),parent_audit_sha256=digest(parent/'audit.json'),bindings=binding,research_sha256={r['asset']:digest(output/r['asset']/'research.json') for r in reports},elapsed_seconds=time.monotonic()-started,no_promotion=True,live_policy_changed=False);dump(output/'research.json',result)
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--parent',type=Path);p.add_argument('--output',type=Path,required=True);p.add_argument('--declare',action='store_true');p.add_argument('--audit',action='store_true');a=p.parse_args()
    r=declare(a.parent,a.output) if a.declare else execute(a.output,a.audit);print(json.dumps(dict(declared=a.declare,audited=a.audit,passed=r.get('passed'))))
