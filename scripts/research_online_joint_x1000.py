#!/usr/bin/env python3
"""Causal within-day feedback on frozen joint X1000 asset models."""
import argparse
from bisect import bisect_left
import gzip
import json
import math
from pathlib import Path
import shutil
import time

from audit_payout_walkforward import same
from joint_x1000 import admissible,forecast
from online_joint_x1000 import SPEC,VARIANTS,Feedback,quote,reference
from research_active_tail import evaluation_rows
from research_asset_corridors import source_files
from research_flat_aware_payout import inputs as previous_inputs,selected
from research_joint_x1000 import (independent_quote,manual_forecast,verify_plan as verify_parent)
from research_payout_risk import digest,dump
from screen_payout_candidates import assess
from trial_payout import clean,metrics


def declare(parent,output):
    if output.exists():raise ValueError('Use a new online-joint packet')
    verify_parent(parent)
    output.mkdir(parents=True);(output/'source').mkdir();paths=sorted(set(source_files()+[Path(__file__).resolve()]))
    for p in paths:shutil.copyfile(p,output/'source'/p.name)
    plan=dict(spec=SPEC,parent=str(parent.resolve()),parent_sha256=digest(parent/'research.json'),source_sha256={p.name:digest(p) for p in paths},declared_before_online_replay=True,parent_outcomes_inspected=True,live_policy_changed=False,fresh_collector_changed=False,no_promotion=True)
    dump(output/'protocol.json',plan);return plan


def verify_plan(output):
    p=json.loads((output/'protocol.json').read_text());parent=Path(p['parent'])
    for name,sha in p['source_sha256'].items():
        if digest(output/'source'/name)!=sha or digest(Path(__file__).with_name(name))!=sha:raise ValueError('Online joint source differs: '+name)
    if digest(parent/'research.json')!=p['parent_sha256']:raise ValueError('Online joint parent differs')
    verify_parent(parent);return p


def manual_reference(r,p):
    value=dict(asset=r['asset'],start=r['start'],expiry=r['expiry'],valid=r['valid'],zero=r['move']==0 if r['valid'] else None,p0=p['p0'],positive_score=None)
    if r['valid'] and r['move']>0:
        required=max(1,((r['move']+1)*10**9+r['entry']-1)//r['entry']);z=(math.log(required/(max(1.,r['adaptive_features']['vol_300_ppm'])*1000))-p['mu'])/p['scale'];e=math.exp(-min(745,abs(z)));value['positive_score']=1/(1+e) if z>=0 else e/(1+e)
    return value


def manual_state(valid_refs,expiries,maturity,at):
    stop=bisect_left(maturity,at);start=max(bisect_left(expiries,at-21600000),stop-480);part=valid_refs[start:stop];positive=[r for r in part if r['zero'] is False];n=len(part);np=len(positive);zeros=sum(r['zero'] for r in part);expected=sum(r['p0'] for r in part);hits=sum(r['positive_score']<=.01 for r in positive)
    return dict(references=n,positive_references=np,zero_events=zeros,raw_zero_sum=expected,positive_anchor_events=hits,flat_factor=max(.1,min(10.,(1+zeros)/(1+expected))) if n>=60 else 1.,tail_factor=max(.25,min(4.,(1+hits)/(1+.01*np))) if np>=100 else 1.)


def manual_quote(r,v,packet,p,state):
    f=state['flat_factor'] if v!='joint_static' else 1.;t=state['tail_factor'] if v=='joint_online_full' else 1.;corrected=dict(p,p0=p['p0'] if f==1 else p['p0']*f/(1-p['p0']+p['p0']*f),mu=p['mu'] if t==1 else p['mu']-p['scale']*math.log(t)) if p is not None else None
    value=independent_quote(r,'joint_raw',packet,corrected)
    return dict(value,raw_p0=p['p0'] if p is not None else None,flat_odds_factor=f,tail_odds_factor=t,matured_references=state['references'],matured_positive_references=state['positive_references'])


def summarize(rows,records):
    result={}
    for phase in ('earlier_oof','trial'):
        result[phase]={}
        for v in VARIANTS:
            groups={}
            for cohort in ('matched','all_clean'):
                groups[cohort]={}
                for g in ('overall','weekday','weekend'):
                    ids=selected(rows,phase,cohort,g);part=[rows[i] for i in ids];pred=[records[v][i] for i in ids];s=metrics(part,pred,1000);s['offers_with_active_feedback']=sum(clean(r) and p['offered'] and (p['flat_odds_factor']!=1 or p['tail_odds_factor']!=1) for r,p in zip(part,pred));groups[cohort][g]=s
            s=groups['matched']['overall'];p=s['pooled'];checked=assess(dict(policy={'name':v},index=VARIANTS.index(v),daily=s['daily'],minimum_daily_availability=s['minimum_daily_availability'],pooled_survival=p['survival'],availability=p['availability'],offered=p['offered'],eligible=p['eligible']),1000);groups['screen']=dict(qualifies=checked['eligible'],reasons=checked['reasons']);result[phase][v]=groups
    return result


def parent_predictions(parent,asset):
    path=parent/asset/'research.json';meta=json.loads(path.read_text());top=json.loads((parent/'research.json').read_text())
    if digest(path)!=top['research_sha256'][asset] or digest(parent/asset/'predictions.jsonl.gz')!=meta['predictions_sha256']:raise ValueError('Online parent trace differs')
    with gzip.open(parent/asset/'predictions.jsonl.gz','rt') as stream:
        for line in stream:
            r=json.loads(line)
            if r['variant']=='joint_raw':yield r


def study_asset(asset,earlier,rows,parent,output,auditing=False):
    root=output/asset;later=evaluation_rows(earlier,rows);parent_meta=json.loads((parent/asset/'research.json').read_text());models={}
    for item in parent_meta['origins']:
        path=parent/asset/'origins'/(item['period']+'.json.gz')
        if digest(path)!=item['sha256']:raise ValueError('Online model binding differs')
        with gzip.open(path,'rt') as s:models[item['period']]=json.load(s)
    # The auditor uses an offline indexed reference population; strict time slices
    # must reproduce the forward pending/recent queues at every entry.
    valid_refs=[]
    if auditing:
        for r in later:
            if clean(r) and admissible(r):valid_refs.append(manual_reference(r,manual_forecast(r,models[r['period']]['model'])))
    expiries=[r['expiry'] for r in valid_refs];maturity=[x+30000 for x in expiries];feedback=Feedback(asset);records={v:[] for v in VARIANTS};count=0;expected=parent_predictions(parent,asset)
    if not auditing:root.mkdir()
    saved=json.loads((root/'research.json').read_text()) if auditing else None
    if auditing and digest(root/'predictions.jsonl.gz')!=saved['predictions_sha256']:raise ValueError('Online trace differs')
    with gzip.open(root/'predictions.jsonl.gz','rt' if auditing else 'xt',compresslevel=5) as stream:
        previous_day=None
        for r in later:
            packet=models[r['period']];state=manual_state(valid_refs,expiries,maturity,r['start']) if auditing else feedback.advance(r['start']);p=(manual_forecast if auditing else forecast)(r,packet['model']) if admissible(r) else None;ref=(manual_reference if auditing else reference)(r,p) if p is not None else None;old=next(expected)
            if (old['asset'],old['period'],old['start'])!=(asset,r['period'],r['start']):raise ValueError('Online parent population differs')
            for v in VARIANTS:
                value=manual_quote(r,v,packet,p,state) if auditing else quote(r,v,packet,p,state)
                if v=='joint_static':same({k:value[k] for k in old if k not in ('asset','period','start','multiplier','variant','reference')},{k:x for k,x in old.items() if k not in ('asset','period','start','multiplier','variant','reference')})
                trace=dict(asset=asset,period=r['period'],start=r['start'],multiplier=1000,variant=v,state=state,reference=ref,**value)
                if auditing:same(json.loads(stream.readline()),trace)
                else:stream.write(json.dumps(trace,separators=(',',':'),allow_nan=False)+'\n')
                records[v].append(value);count+=1
            if not auditing and ref is not None:feedback.push(ref)
            if previous_day!=r['period']:print(json.dumps(dict(asset=asset,origin=r['period'],auditing=auditing)),flush=True);previous_day=r['period']
        if next(expected,None) is not None:raise ValueError('Extra online parent paths')
        if auditing and stream.readline():raise ValueError('Extra online decisions')
    result=dict(asset=asset,results=summarize(later,records),decisions=count,predictions_sha256=digest(root/'predictions.jsonl.gz'),static_parent_control_reproduced=True,no_promotion=True)
    if auditing:same(saved,result)
    else:dump(root/'research.json',result)
    return result


def execute(output,auditing=False):
    started=time.monotonic();p=verify_plan(output);parent=Path(p['parent']);a=json.loads((parent/'audit.json').read_text())
    if not a['passed'] or a['research_sha256']!=p['parent_sha256']:raise ValueError('Matching joint parent audit required')
    joint=json.loads((parent/'protocol.json').read_text());active=json.loads((Path(joint['active'])/'protocol.json').read_text());earlier,rows,_,_,binding=previous_inputs(json.loads((Path(active['parent'])/'protocol.json').read_text()));reports=[study_asset(asset,earlier[asset],rows[asset],parent,output,auditing) for asset in ('ETH','HYPE')];verify_plan(output)
    if auditing:
        meta=json.loads((output/'research.json').read_text());same(meta['bindings'],binding)
        if meta['protocol_sha256']!=digest(output/'protocol.json') or meta['parent_audit_sha256']!=digest(parent/'audit.json'):raise ValueError('Online bindings differ')
        for asset,sha in meta['research_sha256'].items():
            if digest(output/asset/'research.json')!=sha:raise ValueError('Online report differs')
        result=dict(passed=True,research_sha256=digest(output/'research.json'),auditor_sha256=digest(Path(__file__)),assets=[dict(asset=r['asset'],decisions_independently_replayed=r['decisions'],offline_maturity_slices_match_forward_feedback=True,static_parent_control_reproduced=True) for r in reports]);dump(output/'audit.json',result)
    else:
        result=dict(protocol_sha256=digest(output/'protocol.json'),parent_audit_sha256=digest(parent/'audit.json'),bindings=binding,research_sha256={r['asset']:digest(output/r['asset']/'research.json') for r in reports},elapsed_seconds=time.monotonic()-started,qualifying={r['asset']:[v for v,s in r['results']['trial'].items() if s['screen']['qualifies']] for r in reports},live_policy_changed=False,no_promotion=True);dump(output/'research.json',result)
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--parent',type=Path);p.add_argument('--output',type=Path,required=True);p.add_argument('--declare',action='store_true');p.add_argument('--audit',action='store_true');a=p.parse_args();r=declare(a.parent,a.output) if a.declare else execute(a.output,a.audit);print(json.dumps(dict(declared=a.declare,audited=a.audit,passed=r.get('passed'),qualifying=r.get('qualifying'))))
