#!/usr/bin/env python3
"""X1000 joint-state formula development, frozen origins and independent replay."""
import argparse
from collections import Counter
import gzip
import json
import math
from pathlib import Path
import shutil
import time

import numpy as np

from audit_payout_walkforward import same
from fetch_tardis_liquidity_trial import origin
from joint_x1000 import (SPEC,TARGET,VARIANTS,admissible,cdf,fit,forecast,levels,quote,reference,vector)
from payout_risk import weekend
from research_active_tail import evaluation_rows,verify_plan as verify_active
from research_asset_corridors import source_files
from research_conditional_tail import verify_plan as verify_conditional
from research_flat_aware_payout import OOF_DATES,inputs as previous_inputs,selected
from research_payout_risk import digest,dump
from research_trial_liquidity import DATES
from research_trial_payout import save_gzip
from screen_payout_candidates import assess
from trial_payout import clean,metrics


def declare(active,conditional,output):
    if output.exists():raise ValueError('Use a new joint X1000 packet')
    for root,verify in ((active,verify_active),(conditional,verify_conditional)):
        verify(root);a=json.loads((root/'audit.json').read_text())
        if not a['passed'] or a['research_sha256']!=digest(root/'research.json'):raise ValueError('Matching audited parent required')
    output.mkdir(parents=True);(output/'source').mkdir();paths=sorted(set(source_files()+[Path(__file__).resolve()]))
    for p in paths:shutil.copyfile(p,output/'source'/p.name)
    plan=dict(spec=SPEC,active=str(active.resolve()),conditional=str(conditional.resolve()),input_sha256={name:{f:digest(root/f) for f in ('research.json','audit.json')} for name,root in (('active',active),('conditional',conditional))},source_sha256={p.name:digest(p) for p in paths},trial_dates=DATES,earlier_dates=OOF_DATES,declared_before_new_fits_and_replay=True,historical_outcomes_inspected=True,live_policy_changed=False,fresh_collector_changed=False,no_promotion=True)
    dump(output/'protocol.json',plan);return plan


def verify_plan(output):
    p=json.loads((output/'protocol.json').read_text())
    for name,sha in p['source_sha256'].items():
        if digest(output/'source'/name)!=sha or digest(Path(__file__).with_name(name))!=sha:raise ValueError('Joint source differs: '+name)
    for name,verify in (('active',verify_active),('conditional',verify_conditional)):
        verify(Path(p[name]))
        for f,sha in p['input_sha256'][name].items():
            if digest(Path(p[name])/f)!=sha:raise ValueError('Joint parent differs')
    return p


def summarize(rows,records):
    result={}
    for phase in ('earlier_oof','trial'):
        result[phase]={}
        for v in VARIANTS:
            groups={}
            for cohort in ('matched','all_clean'):
                groups[cohort]={}
                for g in ('overall','weekday','weekend'):
                    ids=selected(rows,phase,cohort,g);part=[rows[i] for i in ids];pred=[records[v][i] for i in ids];s=metrics(part,pred,1000)
                    s['admissible_paths']=sum(clean(r) and admissible(r) for r in part)
                    s['identity_fallback_offers']=sum(clean(r) and p['offered'] and p['calibration_source']=='identity' for r,p in zip(part,pred));groups[cohort][g]=s
            s=groups['matched']['overall'];p=s['pooled'];a=assess(dict(policy={'name':v},index=VARIANTS.index(v),daily=s['daily'],minimum_daily_availability=s['minimum_daily_availability'],pooled_survival=p['survival'],availability=p['availability'],offered=p['offered'],eligible=p['eligible']),1000)
            groups['screen']=dict(qualifies=a['eligible'],reasons=a['reasons']);result[phase][v]=groups
    return result


def manual_forecast(r,model):
    x=[1.]+[max(-5,min(5,(value-center)/sd)) for value,center,sd in zip(vector(r),model['center'],model['sd'])]
    z=max(-30,min(30,sum(a*b for a,b in zip(x,model['zero_coefficients']))));e=math.exp(-abs(z));p0=1/(1+e) if z>=0 else e/(1+e)
    return dict(p0=p0,mu=sum(a*b for a,b in zip(x,model['tail_coefficients'])),scale=model['tail_scale'],bucket=sum(p0>=cut for cut in model['risk_cuts']))


def manual_cdf(width,r,p):
    if width<=0:return 0.
    z=(math.log(width/(max(1.,r['adaptive_features']['vol_300_ppm'])*1000))-p['mu'])/p['scale']
    positive=1/(1+math.exp(-z)) if z>-700 else 0.
    return p['p0']+(1-p['p0'])*positive


def manual_reference(r,p):
    minimum=max(1,math.ceil(10**9/r['entry']));required=max(1,((r['move']+1)*10**9+r['entry']-1)//r['entry'])
    return dict(asset=r['asset'],period=r['period'],start=r['start'],expiry=r['expiry'],weekend=weekend(r),bucket=p['bucket'],p0=p['p0'],admission=manual_cdf(minimum,r,p),win_threshold=manual_cdf(required,r,p) if required<=50000000 else None)


def verify_levels(saved,refs,asset,day):
    if any(r['asset']!=asset or r['period']>=day for r in refs) or len({r['start'] for r in refs})!=len(refs):raise ValueError('Invalid joint calibration population')
    refs=[r for r in refs if r['expiry']+30000<origin(day)];expected_keys=set()
    for bucket in (None,0,1,2,3):
        for group in ('global','weekday','weekend'):
            key=group+(':risk'+str(bucket) if bucket is not None else '');expected_keys.add(key)
            part=[r for r in refs if (bucket is None or r['bucket']==bucket) and (group=='global' or r['weekend']==(group=='weekend'))];dates=sorted({r['period'] for r in part})[-10:];part=[r for r in part if r['period'] in dates];s=saved[key]
            same(s['dates'],dates);same(s['n'],len(part))
            if not part:same(s,dict(level=TARGET,supported=False,n=0,dates=[],candidates=[],selected=None));continue
            counts=Counter(r['period'] for r in part);w=np.asarray([1/counts[r['period']]/len(counts) for r in part]);p0=np.asarray([r['p0'] for r in part]);admission=np.asarray([r['admission'] for r in part]);win=np.asarray([r['win_threshold'] if r['win_threshold'] is not None else math.inf for r in part]);codes=np.asarray([dates.index(r['period']) for r in part]);choices=[]
            if len(s['candidates'])!=81:raise ValueError('Joint calibration grid differs')
            for k,cell in enumerate(s['candidates']):
                b=TARGET*2**((k-48)/8);ids=np.flatnonzero((p0<b)&(admission<=b));n=len(ids);nd=len(np.unique(codes[ids]));mass=float(np.sum(w[ids]));wins=float(np.sum(w[ids[win[ids]<=b]]));rate=wins/mass if mass else None;estimate=(n*rate+32*b)/(n+32) if rate is not None else None;support=n>=200 and nd>=3
                same(cell,dict(level=b,offered=n,offered_dates=nd,weighted_offer_mass=mass,conditional_survival=rate,smoothed_survival=estimate,supported=support))
                if support and estimate<=TARGET:choices.append(cell)
            chosen=choices[-1] if choices else None;same(s['selected'],chosen);same(s['supported'],bool(chosen));same(s['level'],chosen['level'] if chosen else TARGET)
    if set(saved)!=expected_keys:raise ValueError('Joint calibration hierarchy differs')


def independent_quote(r,v,packet,p):
    f=r['adaptive_features'];b=r.get('liquidity');a=r.get('activity_features')
    why='missing_history' if f is None else 'missing_liquidity' if b is None else 'stale_liquidity' if not 0<r['start']-b['received_at_ms']<=5000 or not -2000<=r['start']-b['exchange_at_ms']<=5000 else 'flat_oracle_veto' if a['idle_is_lower_bound'] or a['idle_ms']>=30000 or a['changes_30']==0 else None
    level=TARGET;source='identity'
    if v!='joint_raw' and p is not None:
        g='weekend' if weekend(r) else 'weekday';bucket='risk'+str(p['bucket']);hierarchy=([g+':'+bucket,'global:'+bucket] if v=='joint_local' else [])+[g,'global']
        for key in hierarchy:
            if packet['levels'][key]['supported']:level=packet['levels'][key]['level'];source=key;break
    width=None;q=None;probability=None
    if why is None:
        q=(level-p['p0'])/(1-p['p0']);minimum=max(1,(10**9+r['entry']-1)//r['entry'])
        if q<=0 or q>=1:why='predicted_flat_risk'
        elif manual_cdf(minimum,r,p)>level:why='minimum_width_budget'
        else:
            value=math.log(max(1.,f['vol_300_ppm'])*1000)+p['mu']+p['scale']*math.log(q/(1-q));width=max(minimum,min(50000000,int(math.exp(min(30,value)))))
            while width>minimum and cdf(width,r,p)>level+1e-12:width-=1
            probability=manual_cdf(width,r,p);same(probability,cdf(width,r,p))
            if probability>level+1e-10:why='native_width_budget'
    delta=r['entry']*width//10**9 if width is not None else None;shadow=r['move']<delta if r['valid'] and delta is not None else None
    return dict(width=width/1000 if width is not None else None,width_ppb=width,barrier_delta_units=delta,offered=why is None,reason=why or '',shadow=shadow,survived=shadow if why is None else None,p0=p['p0'] if p is not None else None,bucket=p['bucket'] if p is not None else None,level=level,calibration_source=source,positive_q=q,model_survival=probability,parametric=True,empirical_rare_tail_evidence=False)


def study_asset(asset,earlier,rows,output,auditing=False):
    root=output/asset;pool=earlier+[r for r in rows if clean(r) and r.get('liquidity') is not None];later=evaluation_rows(earlier,rows);refs=[];records={v:[] for v in VARIANTS};origins=[];count=0
    if not auditing:root.mkdir();(root/'origins').mkdir()
    saved=json.loads((root/'research.json').read_text()) if auditing else None
    if auditing and digest(root/'predictions.jsonl.gz')!=saved['predictions_sha256']:raise ValueError('Joint trace differs')
    with gzip.open(root/'predictions.jsonl.gz','rt' if auditing else 'xt',compresslevel=5) as stream:
        for day in OOF_DATES+DATES:
            path=root/'origins'/(day+'.json.gz')
            if auditing:
                item=saved['origins'][len(origins)]
                if item['period']!=day or digest(path)!=item['sha256']:raise ValueError('Joint origin differs')
                with gzip.open(path,'rt') as s:packet=json.load(s)
                same(packet['model'],fit(pool,asset,day));verify_levels(packet['levels'],refs,asset,day)
            else:packet=dict(asset=asset,cutoff=day,model=fit(pool,asset,day),levels=levels(refs,asset,day),spec=SPEC);save_gzip(path,packet)
            origins.append(dict(period=day,sha256=digest(path)));pending=[];counts={v:0 for v in VARIANTS}
            for r in (r for r in later if r['period']==day):
                p=(manual_forecast if auditing else forecast)(r,packet['model']) if admissible(r) else None;ref=(manual_reference if auditing else reference)(r,p) if clean(r) and p is not None else None;stored_ref=None
                for v in VARIANTS:
                    value=independent_quote(r,v,packet,p) if auditing else quote(r,v,packet,p);records[v].append(value);count+=1
                    trace=dict(asset=asset,period=day,start=r['start'],multiplier=1000,variant=v,reference=ref,**value)
                    if auditing:
                        old=json.loads(stream.readline());same(old,trace);stored_ref=old['reference']
                    else:stream.write(json.dumps(trace,separators=(',',':'),allow_nan=False)+'\n')
                    counts[v]+=clean(r) and value['offered']
                if ref is not None:pending.append(stored_ref if auditing else ref)
            refs.extend(pending);print(json.dumps(dict(asset=asset,origin=day,auditing=auditing,training=packet['model']['rows'],offers=counts)),flush=True)
        if auditing and stream.readline():raise ValueError('Extra joint decisions')
    result=dict(asset=asset,origins=origins,results=summarize(later,records),decisions=count,predictions_sha256=digest(root/'predictions.jsonl.gz'),no_promotion=True)
    if auditing:same(saved,result)
    else:dump(root/'research.json',result)
    return result


def execute(output,auditing=False):
    started=time.monotonic();p=verify_plan(output);active=json.loads((Path(p['active'])/'protocol.json').read_text());earlier,rows,_,_,binding=previous_inputs(json.loads((Path(active['parent'])/'protocol.json').read_text()));reports=[]
    for a in ('ETH','HYPE'):reports.append(study_asset(a,earlier[a],rows[a],output,auditing))
    verify_plan(output)
    if auditing:
        meta=json.loads((output/'research.json').read_text());same(meta['bindings'],binding)
        if digest(output/'protocol.json')!=meta['protocol_sha256']:raise ValueError('Joint declaration differs')
        for a,sha in meta['research_sha256'].items():
            if digest(output/a/'research.json')!=sha:raise ValueError('Joint asset differs')
        result=dict(passed=True,research_sha256=digest(output/'research.json'),auditor_sha256=digest(Path(__file__)),assets=[dict(asset=r['asset'],models_refit=len(r['origins']),decisions_independently_replayed=r['decisions'],joint_calibration_population_verified=True) for r in reports]);dump(output/'audit.json',result)
    else:
        result=dict(protocol_sha256=digest(output/'protocol.json'),bindings=binding,research_sha256={r['asset']:digest(output/r['asset']/'research.json') for r in reports},elapsed_seconds=time.monotonic()-started,qualifying={r['asset']:[v for v,s in r['results']['trial'].items() if s['screen']['qualifies']] for r in reports},live_policy_changed=False,no_promotion=True);dump(output/'research.json',result)
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--active',type=Path);p.add_argument('--conditional',type=Path);p.add_argument('--output',type=Path,required=True);p.add_argument('--declare',action='store_true');p.add_argument('--audit',action='store_true');a=p.parse_args();r=declare(a.active,a.conditional,a.output) if a.declare else execute(a.output,a.audit);print(json.dumps(dict(declared=a.declare,audited=a.audit,passed=r.get('passed'),qualifying=r.get('qualifying'))))
