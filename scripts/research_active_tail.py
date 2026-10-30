#!/usr/bin/env python3
"""Pre-entry admissible-state risk, positive tails and causal CDF calibration."""
import argparse
import gzip
import json
import math
from pathlib import Path
import shutil
import time
from statistics import NormalDist

from active_tail_payout import (SPEC,VARIANTS,admissible,budget,cdf,fit,forecast,levels,quote,score,vector)
from audit_payout_walkforward import same
from flat_aware_payout import movement
from payout_empirical import EmpiricalPredictor
from research_asset_corridors import source_files
from research_flat_aware_payout import OOF_DATES,inputs as previous_inputs,selected,verify_plan as verify_previous
from payout_risk import weekend
from research_payout_risk import digest,dump
from research_trial_liquidity import DATES,training
from research_trial_payout import save_gzip
from screen_payout_candidates import assess
from trial_payout import MULTIPLIERS,clean,metrics


def declare(parent,comparison,output):
    if output.exists():raise ValueError('Use a new active-tail packet')
    verify_previous(parent)
    for root in (parent,comparison):
        audit=json.loads((root/'audit.json').read_text())
        if not audit['passed'] or audit['research_sha256']!=digest(root/'research.json'):raise ValueError('Matching audited input required')
    output.mkdir(parents=True);(output/'source').mkdir();paths=sorted(set(source_files()+[Path(__file__).resolve()]))
    for p in paths:shutil.copyfile(p,output/'source'/p.name)
    plan=dict(spec=SPEC,parent=str(parent.resolve()),comparison=str(comparison.resolve()),
        parent_sha256=digest(parent/'research.json'),parent_audit_sha256=digest(parent/'audit.json'),
        comparison_sha256=digest(comparison/'research.json'),comparison_audit_sha256=digest(comparison/'audit.json'),
        source_sha256={p.name:digest(p) for p in paths},trial_dates=DATES,earlier_dates=OOF_DATES,
        declared_before_new_fits_and_replay=True,already_inspected_development=True,live_policy_changed=False,no_promotion=True)
    dump(output/'protocol.json',plan);return plan


def verify_plan(output):
    p=json.loads((output/'protocol.json').read_text())
    for name,sha in p['source_sha256'].items():
        if digest(output/'source'/name)!=sha or digest(Path(__file__).with_name(name))!=sha:raise ValueError('Active-tail source changed: '+name)
    for root,key in (('parent','parent'),('comparison','comparison')):
        for name,suffix in (('research.json','_sha256'),('audit.json','_audit_sha256')):
            if digest(Path(p[root])/name)!=p[key+suffix]:raise ValueError('Active-tail input differs')
    verify_previous(Path(p['parent']));return p


def summarize(rows,records):
    results={}
    for phase in ('earlier_oof','trial'):
        results[phase]={}
        for m in MULTIPLIERS:
            variants={}
            for v in VARIANTS:
                groups={}
                for cohort in ('matched','all_clean'):
                    groups[cohort]={}
                    for group in ('overall','weekday','weekend'):
                        ids=selected(rows,phase,cohort,group);part=[rows[i] for i in ids];values=[records[m,v][i] for i in ids]
                        result=metrics(part,values,m)
                        result['parametric_offers_failing_old_tail_rule']=sum(clean(r) and p['offered'] and p['parametric'] and not p['old_tail_supported'] for r,p in zip(part,values))
                        result['admissible_paths']=sum(clean(r) and admissible(r) for r in part)
                        groups[cohort][group]=result
                s=groups['matched']['overall'];p=s['pooled'];a=assess(dict(policy={'name':v},index=VARIANTS.index(v),daily=s['daily'],
                    minimum_daily_availability=s['minimum_daily_availability'],pooled_survival=p['survival'],availability=p['availability'],offered=p['offered'],eligible=p['eligible']),m)
                groups['screen']=dict(qualifies=a['eligible'],reasons=a['reasons']);variants[v]=groups
            results[phase][str(m)]=variants
    return results


def reference(row,u):return dict(asset=row['asset'],start=row['start'],expiry=row['expiry'],period=row['period'],weekend=weekend(row),score=u)


def evaluation_rows(earlier,rows):return [r for r in earlier if r['period'] in OOF_DATES]+rows


def study_asset(asset,earlier,rows,output):
    root=output/asset;root.mkdir();(root/'origins').mkdir();pool=earlier+[r for r in rows if clean(r) and r.get('liquidity') is not None]
    later=evaluation_rows(earlier,rows);refs=[];records={(m,v):[] for m in MULTIPLIERS for v in VARIANTS};origins=[]
    with gzip.open(root/'predictions.jsonl.gz','xt',compresslevel=5) as stream:
        for day in OOF_DATES+DATES:
            model=fit(pool,asset,day);train=[r for r in training(pool,asset,day) if admissible(r)]
            packet=dict(asset=asset,cutoff=day,model=model,empirical=movement(train,asset,day,'previous'),levels=levels(refs,day),spec=SPEC)
            path=root/'origins'/(day+'.json.gz');save_gzip(path,packet);origins.append(dict(period=day,sha256=digest(path)))
            predictor=EmpiricalPredictor(packet['empirical']);pending=[];counts={v:0 for v in VARIANTS}
            for r in (r for r in later if r['period']==day):
                prediction=forecast(r,model) if admissible(r) else None
                u=score(r,prediction) if clean(r) and prediction is not None else None
                for m in MULTIPLIERS:
                    for v in VARIANTS:
                        p=quote(r,m,v,packet,predictor,prediction);records[m,v].append(p)
                        if m==1000:counts[v]+=p['offered'] and clean(r)
                        stream.write(json.dumps(dict(asset=asset,period=day,start=r['start'],multiplier=m,variant=v,reference_score=u,**p),separators=(',',':'),allow_nan=False)+'\n')
                if u is not None:pending.append(reference(r,u))
            refs.extend(pending)
            print(json.dumps(dict(asset=asset,origin=day,training_paths=model['rows'],x1000_offers=counts)),flush=True)
    save_gzip(root/'calibration-references.json.gz',refs)
    result=dict(asset=asset,origins=origins,results=summarize(later,records),predictions_sha256=digest(root/'predictions.jsonl.gz'),
        references_sha256=digest(root/'calibration-references.json.gz'),no_promotion=True)
    dump(root/'research.json',result);return result


def run(output):
    started=time.monotonic();p=verify_plan(output);earlier,rows,_,_,binding=previous_inputs(json.loads((Path(p['parent'])/'protocol.json').read_text()))
    results=[study_asset(a,earlier[a],rows[a],output) for a in ('ETH','HYPE')];verify_plan(output)
    result=dict(protocol_sha256=digest(output/'protocol.json'),bindings=binding,research_sha256={a:digest(output/a/'research.json') for a in ('ETH','HYPE')},
        elapsed_seconds=time.monotonic()-started,qualifying={r['asset']:{m:[v for v,x in r['results']['trial'][m].items() if x['screen']['qualifies']] for m in ('100','1000')} for r in results},no_promotion=True,live_policy_changed=False)
    dump(output/'research.json',result);return result


def manual_forecast(r,model):
    x=[1.]+[min(5,max(-5,(v-c)/s)) for v,c,s in zip(vector(r),model['center'],model['sd'])]
    probabilities=[]
    for k in ('zero_coefficients','minimum_coefficients'):
        z=max(-30,min(30,sum(a*b for a,b in zip(x,model[k]))));probabilities.append(1/(1+math.exp(-z)))
    return dict(p0=probabilities[0],floor=max(probabilities),mu=sum(a*b for a,b in zip(x,model['tail_coefficients'])),sigma=model['tail_sigma'])


def manual_cdf(w,r,p):
    if w<=0:return 0.
    z=(math.log(w/(max(1.,r['adaptive_features']['vol_300_ppm'])*1000))-p['mu'])/p['sigma']
    return p['p0']+(1-p['p0'])*(.5*(1+math.erf(z/math.sqrt(2))))


def independent_quote(r,m,v,packet,predictor,p):
    # The empirical comparator is independently implemented by the retained CDF auditor.
    from audit_payout_empirical import independent_entry
    from flat_aware_payout import veto
    why='missing_history' if r['adaptive_features'] is None else 'missing_liquidity' if r.get('liquidity') is None else veto(r,100,False)
    target,source=budget(packet,r,m,v)
    if v=='active_empirical':
        raw=(p['p0'],p['floor']) if p is not None else (None,None)
        identity=dict(heads={f:[dict(supported=False)]*6 for f in ('p0','floor')});policy=dict(name=v,kind='empirical',prior=32,family='activity',anchor='slow',level=1.,gate=1.)
        result=independent_entry(r,m,policy,raw,{'32':identity},None,None,packet['empirical'],predictor)
        result.update(width_ppb=result['width']*1000 if result['width'] is not None else None,barrier_delta_units=r['entry']*result['width']//1000000 if result['width'] is not None else None)
        if why:result.update(offered=False,survived=None,reason=why)
        return dict(result,flat_guard=why,level=target,calibration_source=source,parametric=False,old_tail_supported=result['tail_supported'],model_survival=None)
    width=None;q=None;old_support=False;probability=None
    if why is None:
        q=(target-p['p0'])/(1-p['p0'])
        if not 0<q<1:why='predicted_flat_risk'
        else:
            oq=(target-p['floor'])/(1-p['floor']);old_support=0<oq<1 and packet['empirical']['anchors']['slow']['global_distribution']['n']*oq>=20
            minimum=max(1,-(-10**9//r['entry']))
            if manual_cdf(minimum,r,p)>target:why='minimum_width_budget'
            else:
                z=NormalDist().inv_cdf(q);log_w=math.log(max(1.,r['adaptive_features']['vol_300_ppm'])*1000)+p['mu']+p['sigma']*z
                width=max(minimum,min(50000000,math.floor(math.exp(min(30,log_w)))))
                # Quantization follows the same public numerical CDF; verify it separately.
                while width>minimum and cdf(width,r,p)>target+1e-12:width-=1
                probability=cdf(width,r,p);same(probability,manual_cdf(width,r,p))
                if probability>target+1e-10:why='native_width_budget'
    delta=r['entry']*width//10**9 if width is not None else None;shadow=r['move']<delta if r['valid'] and delta is not None else None
    return dict(width=width/1000 if width is not None else None,width_ppb=width,barrier_delta_units=delta,offered=why is None,reason=why or '',positive_q=q,
        tail_mass=packet['model']['positive_rows']*max(0,q or 0),tail_supported=None,child_supported=None,p0=p['p0'] if p is not None else None,
        floor=p['p0'] if p is not None else None,calibrated0=False,calibrated_floor=False,shadow=shadow,survived=shadow if why is None else None,
        flat_guard=why if why in ('flat_oracle_veto','missing_history','missing_liquidity') else None,level=target,calibration_source=source,parametric=True,
        old_tail_supported=old_support,model_survival=probability)


def audit_asset(asset,earlier,rows,root):
    from audit_payout_empirical import verify_distribution
    meta=json.loads((root/'research.json').read_text());pool=earlier+[r for r in rows if clean(r) and r.get('liquidity') is not None]
    later=evaluation_rows(earlier,rows);refs=[];records={(m,v):[] for m in MULTIPLIERS for v in VARIANTS};count=0
    if digest(root/'predictions.jsonl.gz')!=meta['predictions_sha256'] or [o['period'] for o in meta['origins']]!=list(OOF_DATES+DATES):raise ValueError('Active-tail trace differs')
    with gzip.open(root/'predictions.jsonl.gz','rt') as stream:
        for item in meta['origins']:
            day=item['period'];path=root/'origins'/(day+'.json.gz')
            if digest(path)!=item['sha256']:raise ValueError('Active-tail origin differs')
            with gzip.open(path,'rt') as models:packet=json.load(models)
            same(packet['model'],fit(pool,asset,day));same(packet['levels'],levels(refs,day))
            train=[r for r in training(pool,asset,day) if admissible(r)];data=packet['empirical']['anchors']['slow'];verify_distribution(data['global_distribution'],train,'slow');groups={}
            for r in train:groups.setdefault(r['activity_state'],[]).append(r)
            if set(groups)!=set(data['families']['activity']):raise ValueError('Active-tail empirical groups differ')
            for k,part in groups.items():verify_distribution(data['families']['activity'][k],part,'slow')
            cache={};pending=[]
            for r in (r for r in later if r['period']==day):
                p=manual_forecast(r,packet['model']) if admissible(r) else None;expected_score=(p['p0'] if r['move']==0 else manual_cdf((r['move']+1)*1e9/r['entry'],r,p)) if clean(r) and p is not None else None;stored_score=None
                for m in MULTIPLIERS:
                    for v in VARIANTS:
                        saved=json.loads(stream.readline());u=saved.pop('reference_score');same(u,expected_score)
                        if stored_score is None:stored_score=u
                        else:same(u,stored_score)
                        result=independent_quote(r,m,v,packet,cache,p);same(saved,dict(asset=asset,period=day,start=r['start'],multiplier=m,variant=v,**result));records[m,v].append(result);count+=1
                if expected_score is not None:pending.append(reference(r,stored_score))
            refs.extend(pending);print(json.dumps(dict(audited_asset=asset,origin=day)),flush=True)
        if stream.readline():raise ValueError('Extra active-tail decisions')
    if digest(root/'calibration-references.json.gz')!=meta['references_sha256']:raise ValueError('Active-tail references differ')
    with gzip.open(root/'calibration-references.json.gz','rt') as s:same(json.load(s),refs)
    same(meta,dict(asset=asset,origins=meta['origins'],results=summarize(later,records),predictions_sha256=meta['predictions_sha256'],references_sha256=meta['references_sha256'],no_promotion=True))
    return dict(asset=asset,models_refit=len(meta['origins']),decisions_independently_replayed=count,calibration_maturity_and_population_verified=True)


def audit(output):
    p=verify_plan(output);meta=json.loads((output/'research.json').read_text())
    if digest(output/'protocol.json')!=meta['protocol_sha256']:raise ValueError('Active-tail declaration differs')
    earlier,rows,_,_,binding=previous_inputs(json.loads((Path(p['parent'])/'protocol.json').read_text()));same(binding,meta['bindings'])
    reports=[]
    for a in ('ETH','HYPE'):
        if digest(output/a/'research.json')!=meta['research_sha256'][a]:raise ValueError('Active-tail asset differs')
        reports.append(audit_asset(a,earlier[a],rows[a],output/a))
    verify_plan(output);r=dict(passed=True,research_sha256=digest(output/'research.json'),auditor_sha256=digest(Path(__file__)),assets=reports)
    dump(output/'audit.json',r);return r


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--parent',type=Path);parser.add_argument('--comparison',type=Path);parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--declare',action='store_true');parser.add_argument('--audit',action='store_true');a=parser.parse_args()
    r=declare(a.parent,a.comparison,a.output) if a.declare else audit(a.output) if a.audit else run(a.output)
    print(json.dumps(dict(declared=a.declare,audited=a.audit,passed=r.get('passed'),qualifying=r.get('qualifying'))))
