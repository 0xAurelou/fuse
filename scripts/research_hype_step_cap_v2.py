#!/usr/bin/env python3
"""Diagnose five HYPE wins and test one pre-entry observed-step width cap."""
import argparse
from bisect import bisect_left
from collections import Counter
from datetime import datetime,timezone
import gzip
import json
import math
from pathlib import Path
import shutil

from audit_payout_walkforward import same
from fetch_tardis_liquidity_trial import DATES,origin
from joint_x1000 import admissible,cdf,forecast
from oracle_gap_features import raw_timestamp
from oracle_step_cap_v2 import SPEC,apply,step_features
from research_asset_corridors import source_files
from research_flat_aware_payout import inputs as previous_inputs
from research_online_joint_x1000 import verify_plan as verify_parent
from research_payout_risk import digest,dump
from research_market_regimes import price_units
from research_trial_payout import save_gzip
from payout_risk import weekend
from trial_payout import clean,metrics


def paths(parent):
    online=json.loads((parent/'protocol.json').read_text());joint=Path(online['parent']);j=json.loads((joint/'protocol.json').read_text());a=json.loads((Path(j['active'])/'protocol.json').read_text());flat=Path(a['parent']);f=json.loads((flat/'protocol.json').read_text());payout=json.loads((Path(f['previous'])/'protocol.json').read_text());liquidity=Path(payout['liquidity']);raw=Path(json.loads((liquidity/'protocol.json').read_text())['raw']);return flat,joint,liquidity,raw


def declare(parent,output,amends=None):
    if output.exists():raise ValueError('Use a new HYPE step-cap packet')
    verify_parent(parent);a=json.loads((parent/'audit.json').read_text())
    if not a['passed'] or a['research_sha256']!=digest(parent/'research.json'):raise ValueError('Matching audited HYPE baseline required')
    _,_,liquidity,raw=paths(parent);output.mkdir(parents=True);(output/'source').mkdir();sources=sorted(set(source_files()+[Path(__file__).resolve()]))
    for p in sources:shutil.copyfile(p,output/'source'/p.name)
    plan=dict(spec=SPEC,parent=str(parent.resolve()),parent_sha256=digest(parent/'research.json'),parent_audit_sha256=digest(parent/'audit.json'),liquidity=str(liquidity.resolve()),rows_sha256=digest(liquidity/'rows.jsonl.gz'),raw=str(raw.resolve()),raw_manifest_sha256=digest(raw/'download-manifest.json'),source_sha256={p.name:digest(p) for p in sources},declared_before_cap_replay=True,five_baseline_wins_inspected=True,eth_unchanged=True,live_policy_changed=False)
    
    if amends:plan['implementation_amendment']=dict(previous=str(amends.resolve()),protocol_sha256=digest(amends/'protocol.json'),research_sha256=digest(amends/'research.json'))
    dump(output/'protocol.json',plan);return plan


def verify_plan(output):
    p=json.loads((output/'protocol.json').read_text());parent=Path(p['parent']);verify_parent(parent)
    if p.get('implementation_amendment'):
        a=p['implementation_amendment'];r=Path(a['previous'])
        if digest(r/'protocol.json')!=a['protocol_sha256'] or digest(r/'research.json')!=a['research_sha256']:raise ValueError('Previous HYPE implementation record differs')
    for n,sha in p['source_sha256'].items():
        if digest(output/'source'/n)!=sha or digest(Path(__file__).with_name(n))!=sha:raise ValueError('HYPE step-cap source changed: '+n)
    for root,f,sha in ((parent,'research.json',p['parent_sha256']),(parent,'audit.json',p['parent_audit_sha256']),(Path(p['liquidity']),'rows.jsonl.gz',p['rows_sha256']),(Path(p['raw']),'download-manifest.json',p['raw_manifest_sha256'])):
        if digest(root/f)!=sha:raise ValueError('HYPE step-cap input changed')
    return p


def raw_day(raw,day):
    manifest=json.loads((raw/'download-manifest.json').read_text());observed=[];markers=[];waiting=False;previous=None
    for item in sorted((f for f in manifest['files'] if f['day']==day),key=lambda f:f['at_ms']):
        path=raw/item['path']
        if item['status']!='downloaded' or digest(path)!=item['sha256']:raise ValueError('HYPE raw segment changed')
        with gzip.open(path,'rt') as stream:
            for line in stream:
                if not line.strip():waiting=True;continue
                stamp,payload=line.rstrip('\n').split(' ',1);at=raw_timestamp(stamp)
                if previous is not None and at<previous or not item['at_ms']<=at<item['at_ms']+item['duration_ms']:raise ValueError('HYPE raw timestamp differs')
                previous=at;v=json.loads(payload);d=v['data']
                if v['channel']!='activeAssetCtx' or d['coin']!='HYPE':continue
                if waiting:markers.append(dict(known_at=at));waiting=False
                observed.append((at,price_units(d['ctx']['oraclePx'])))
    if waiting:markers.append(dict(known_at=origin(day)+86400000-1))
    return observed,markers


def independent_steps(observed,markers,starts):
    times=[p[0] for p in observed];resets=sorted([m['known_at'] for m in markers]+[b[0] for a,b in zip(observed,observed[1:]) if b[0]-a[0]>8000]);result=[]
    for at in starts:
        end=bisect_left(times,at);last=observed[end-1] if end else None;ri=bisect_left(resets,at)-1;begin=bisect_left(times,resets[ri]) if ri>=0 else 0;since=observed[begin][0] if begin<end else None
        if begin>=end:last=None
        first=max(begin+1,bisect_left(times,at-300000));deltas=[abs(observed[i][1]-observed[i-1][1]) for i in range(first,end) if observed[i][1]!=observed[i-1][1]];step=0
        for d in deltas:step=math.gcd(step,d)
        supported=last is not None and 0<at-last[0]<=8000 and since is not None and at-since>=300000 and len(deltas)>=4 and step>0
        result.append(dict(start=at,step_units=step or None,positive_changes=len(deltas),observed_since=since,last_oracle_at=last[0] if last else None,last_price_units=last[1] if last else None,supported=supported))
    return result


def independent_cap(r,base,step,p):
    width=base['width_ppb'];limit=None;changed=False;reason='unsupported_step'
    if step['supported'] and width is not None:
        minimum=max(1,(10**9+r['entry']-1)//r['entry']);limit=((step['step_units']+1)*10**9-1)//r['entry']
        if limit<minimum:reason='unrepresentable_step_cap'
        else:width=min(width,limit);changed=width<base['width_ppb'];reason='capped' if changed else 'already_narrower'
    result=dict(base)
    if width is not None:
        delta=width*r['entry']//10**9;shadow=r['move']<delta if r['valid'] else None;result.update(width=width/1000,width_ppb=width,barrier_delta_units=delta,shadow=shadow,survived=shadow if base['offered'] else None)
        if p is not None:result['model_survival']=cdf(width,r,p)
    result.update(base_width_ppb=base['width_ppb'],base_barrier_delta_units=base['barrier_delta_units'],base_model_survival=base['model_survival'],observed_step_units=step['step_units'],step_supported=step['supported'],step_cap_ppb=limit,step_cap_applied=changed,step_cap_reason=reason);return result


def summarize(rows,values):
    result={}
    for cohort in ('matched','all_clean'):
        result[cohort]={}
        for g in ('overall','weekday','weekend'):
            ids=[i for i,r in enumerate(rows) if (cohort=='all_clean' or r.get('liquidity') is not None and r['adaptive_features'] is not None) and (g=='overall' or weekend(r)==(g=='weekend'))];part=[rows[i] for i in ids];result[cohort][g]=metrics(part,[values[i] for i in ids],1000)
    return result


def execute(output,auditing=False):
    p=verify_plan(output);parent=Path(p['parent']);flat,joint,_,raw=paths(parent);_,byasset,_,_,binding=previous_inputs(json.loads((flat/'protocol.json').read_text()));rows=byasset['HYPE'];meta=json.loads((parent/'HYPE/research.json').read_text());parent_meta=json.loads((parent/'research.json').read_text())
    if digest(parent/'HYPE/research.json')!=parent_meta['research_sha256']['HYPE'] or digest(parent/'HYPE/predictions.jsonl.gz')!=meta['predictions_sha256']:raise ValueError('HYPE baseline trace changed')
    baseline=[]
    with gzip.open(parent/'HYPE/predictions.jsonl.gz','rt') as stream:
        for line in stream:
            v=json.loads(line)
            if v['period'] in DATES and v['variant']=='joint_online_full':baseline.append(v)
    if len(baseline)!=len(rows):raise ValueError('HYPE baseline population differs')
    steps=[]
    for day in DATES:
        observed,markers=raw_day(raw,day);part=[r for r in rows if r['period']==day];s=(independent_steps if auditing else step_features)(observed,markers,[r['start'] for r in part])
        for r,t in zip(part,s):
            if r['entry'] is not None and t['last_price_units'] is not None and r['entry']!=t['last_price_units']:raise ValueError('HYPE raw/pre-entry oracle differs')
        steps.extend(s);print(json.dumps(dict(day=day,auditing=auditing)),flush=True)
    modelmeta=json.loads((joint/'HYPE/research.json').read_text());models={}
    for item in modelmeta['origins']:
        if item['period'] not in DATES:continue
        path=joint/'HYPE/origins'/(item['period']+'.json.gz')
        if digest(path)!=item['sha256']:raise ValueError('HYPE model binding differs')
        with gzip.open(path,'rt') as s:models[item['period']]=json.load(s)['model']
    records={'baseline':[],'step_cap':[]};diagnosis=[];capped=0
    saved=json.loads((output/'research.json').read_text()) if auditing else None
    if auditing and digest(output/'predictions.jsonl.gz')!=saved['predictions_sha256']:raise ValueError('HYPE capped trace changed')
    with gzip.open(output/'predictions.jsonl.gz','rt' if auditing else 'xt',compresslevel=5) as stream:
        for r,old,step in zip(rows,baseline,steps):
            if (old['period'],old['start'])!=(r['period'],r['start']):raise ValueError('HYPE baseline order differs')
            base={k:v for k,v in old.items() if k not in ('asset','period','start','multiplier','variant','state','reference')};prediction=forecast(r,models[r['period']]) if admissible(r) else None
            corrected=dict(prediction,p0=old['p0'],mu=prediction['mu']-prediction['scale']*math.log(old['tail_odds_factor'])) if prediction is not None else None
            value=(independent_cap if auditing else apply)(r,base,step,corrected)
            if value['offered']!=base['offered'] or value['width_ppb'] is not None and value['width_ppb']>base['width_ppb'] or value['survived'] is True and base['survived'] is not True:raise ValueError('HYPE admission/width/win invariant failed')
            records['baseline'].append(base);records['step_cap'].append(value);capped+=clean(r) and value['offered'] and value['step_cap_applied']
            trace=dict(asset='HYPE',period=r['period'],start=r['start'],step=step,variant='step_cap',**value)
            if auditing:same(json.loads(stream.readline()),trace)
            else:stream.write(json.dumps(trace,separators=(',',':'),allow_nan=False)+'\n')
            if clean(r) and base['offered'] and base['survived']:
                diagnosis.append(dict(start=r['start'],utc=datetime.fromtimestamp(r['start']/1000,timezone.utc).isoformat(),entry=r['entry'],move=r['move'],features=r['adaptive_features'],activity=r['activity_features'],liquidity=r['liquidity'],state=old['state'],base_width_ppb=base['width_ppb'],base_delta=base['barrier_delta_units'],raw_p0=old['raw_p0'],corrected_p0=old['p0'],step=step,capped_width_ppb=value['width_ppb'],capped_delta=value['barrier_delta_units'],survived_after_cap=value['survived']))
        if auditing and stream.readline():raise ValueError('Extra HYPE capped decisions')
    results={v:summarize(rows,values) for v,values in records.items()}
    for cohort in ('matched','all_clean'):
        for g in ('overall','weekday','weekend'):
            same(results['baseline'][cohort][g],{k:v for k,v in meta['results']['trial']['joint_online_full'][cohort][g].items() if k!='offers_with_active_feedback'})
            a=results['baseline'][cohort][g];b=results['step_cap'][cohort][g]
            for x,y in zip(a['daily'],b['daily']):
                if x['period']!=y['period'] or x['offered']!=y['offered'] or x['pre_entry_offered']!=y['pre_entry_offered'] or x['eligible']!=y['eligible']:raise ValueError('HYPE daily availability changed')
    result=dict(protocol_sha256=digest(output/'protocol.json'),bindings=binding,results=results,diagnosis=diagnosis,capped_offers=capped,decisions=len(rows),predictions_sha256=digest(output/'predictions.jsonl.gz'),admission_and_availability_preserved=True,eth_unchanged=True,no_promotion=True)
    if auditing:
        same(saved,result);report=dict(passed=True,research_sha256=digest(output/'research.json'),decisions_independently_replayed=len(rows),raw_step_features_independently_reconstructed=True,admission_and_availability_preserved=True);dump(output/'audit.json',report);return report
    dump(output/'research.json',result);verify_plan(output);return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--parent',type=Path);p.add_argument('--amends',type=Path);p.add_argument('--output',type=Path,required=True);p.add_argument('--declare',action='store_true');p.add_argument('--audit',action='store_true');a=p.parse_args();r=declare(a.parent,a.output,a.amends) if a.declare else execute(a.output,a.audit);print(json.dumps(dict(declared=a.declare,audited=a.audit,passed=r.get('passed'),capped_offers=r.get('capped_offers'))))
