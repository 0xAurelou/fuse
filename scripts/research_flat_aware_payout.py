#!/usr/bin/env python3
"""Earlier-only flat-aware formulas with old-month and consecutive-day replays."""
import argparse
import gzip
import json
from pathlib import Path
import shutil
import time

from audit_historical_liquidity import manual
from audit_payout_empirical import independent_entry,verify_distribution
from audit_payout_walkforward import same
from flat_aware_payout import (SPEC,VARIANTS,activity_key,cell_key,build_predictors,
    fit_floor,floor_forecast,movement,quote)
from historical_liquidity import predict
from payout_risk import weekend
from research_asset_corridors import source_files
from research_payout_risk import digest,dump
from research_trial_liquidity import DATES,WARMUP_DATES,training
from research_trial_payout import inputs as previous_inputs,risk_origin,save_gzip,verify_plan as verify_previous
from screen_payout_candidates import assess
from trial_payout import MULTIPLIERS,available,clean,metrics

OOF_DATES=WARMUP_DATES[6:]


def declare(previous,output):
    if output.exists():raise ValueError('Use a new flat-aware research directory')
    verify_previous(previous);audit=json.loads((previous/'audit.json').read_text())
    if not audit['passed'] or audit['research_sha256']!=digest(previous/'research.json'):raise ValueError('Matching completed payout audit required')
    output.mkdir(parents=True);(output/'source').mkdir();paths=sorted(set(source_files()+[Path(__file__).resolve()]))
    for p in paths:shutil.copyfile(p,output/'source'/p.name)
    plan=dict(spec=SPEC,previous=str(previous.resolve()),previous_sha256=digest(previous/'research.json'),
        previous_audit_sha256=digest(previous/'audit.json'),source_sha256={p.name:digest(p) for p in paths},
        earlier_oof_dates=OOF_DATES,trial_dates=DATES,declared_before_new_formula_fits_and_replay=True,
        earlier_trial_outcomes_already_inspected=True,no_variant_selection=True,
        live_policy_changed=False,fresh_collector_changed=False,no_promotion=True)
    dump(output/'protocol.json',plan);return plan


def verify_plan(output):
    plan=json.loads((output/'protocol.json').read_text())
    for n,sha in plan['source_sha256'].items():
        if digest(output/'source'/n)!=sha or digest(Path(__file__).with_name(n))!=sha:raise ValueError('Flat-aware source changed: '+n)
    for name,key in (('research.json','previous_sha256'),('audit.json','previous_audit_sha256')):
        if digest(Path(plan['previous'])/name)!=plan[key]:raise ValueError('Previous payout packet changed')
    return plan


def inputs(plan):
    previous=Path(plan['previous']);p=verify_previous(previous)
    earlier,rows,liquidity_plan,binding=previous_inputs(p)
    return earlier,rows,Path(p['liquidity']),Path(liquidity_plan['monthly']),binding


def prior_risk(asset,day,liquidity,monthly):
    if day in DATES:return risk_origin(liquidity,asset,day)
    meta=json.loads((monthly/'research.json').read_text());path=monthly/asset/'research.json'
    if digest(path)!=meta['research_sha256'][asset]:raise ValueError('Earlier risk metadata differs')
    origins=json.loads(path.read_text())['origins'];expected={o['period']:o['sha256'] for o in origins}
    path=monthly/asset/'origins'/(day+'.json')
    if digest(path)!=expected[day]:raise ValueError('Earlier risk origin differs')
    return json.loads(path.read_text()),dict(path=str(path),sha256=expected[day])


def fit_origin(pool,asset,day,liquidity,monthly):
    train=training(pool,asset,day);risk,binding=prior_risk(asset,day,liquidity,monthly)
    model=risk['models']['calendar_liquidity']
    if model['rows']!=len(train) or model['training_dates']!=sorted({r['period'] for r in train}):raise ValueError('Baseline training population differs')
    return dict(asset=asset,cutoff=day,risk=model,risk_binding=binding,floor=fit_floor(pool,asset,day),
        movement={mode:movement(pool,asset,day,mode) for mode in ('previous','activity','calendar')},spec=SPEC)


def selected(rows,phase,cohort,group):
    return [i for i,r in enumerate(rows) if (r['period'] in DATES)==(phase=='trial')
        and (cohort=='all_clean' or r.get('liquidity') is not None and r['adaptive_features'] is not None)
        and (group=='overall' or weekend(r)==(group=='weekend'))]


def summarize_asset(asset,rows,records,origins):
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
                        ids=selected(rows,phase,cohort,group)
                        part=[rows[i] for i in ids];values=[records[m,v][i] for i in ids]
                        groups[cohort][group]=metrics(part,values,m)
                        groups[cohort][group]['flat_guard_refusals']=sum(p['flat_guard'] is not None and clean(r) for r,p in zip(part,values))
                s=groups['matched']['overall'];p=s['pooled']
                checked=assess(dict(policy={'name':v},index=VARIANTS.index(v),daily=s['daily'],
                    minimum_daily_availability=s['minimum_daily_availability'],pooled_survival=p['survival'],
                    availability=p['availability'],offered=p['offered'],eligible=p['eligible']),m)
                groups['screen']=dict(qualifies=checked['eligible'],reasons=checked['reasons'],no_promotion=True);variants[v]=groups
            results[phase][str(m)]=dict(variants=variants,qualifying_variants=[v for v in VARIANTS if variants[v]['screen']['qualifies']])
    return dict(asset=asset,origins=origins,grid_entries=len(rows),results=results,no_promotion=True)


def evaluation_rows(earlier,rows):return [r for r in earlier if r['period'] in OOF_DATES]+rows


def study_asset(asset,earlier,rows,liquidity,monthly,output):
    directory=output/asset;directory.mkdir();(directory/'origins').mkdir()
    pool=earlier+[r for r in rows if clean(r) and r.get('liquidity') is not None];later=evaluation_rows(earlier,rows)
    records={(m,v):[] for m in MULTIPLIERS for v in VARIANTS};origins=[]
    with gzip.open(directory/'predictions.jsonl.gz','xt',compresslevel=5) as stream:
        for day in OOF_DATES+DATES:
            packet=fit_origin(pool,asset,day,liquidity,monthly);path=directory/'origins'/(day+'.json.gz');save_gzip(path,packet)
            origins.append(dict(period=day,sha256=digest(path)));predictors=build_predictors(packet)
            for r in (r for r in later if r['period']==day):
                baseline=dict(predict(r,packet['risk']),calibrated0=False,calibrated_floor=False) if available(r,'calendar_liquidity') else dict(p0=None,floor=None,calibrated0=False,calibrated_floor=False)
                for m in MULTIPLIERS:
                    for v in VARIANTS:
                        p=quote(r,m,v,packet,predictors,baseline);records[m,v].append(p)
                        stream.write(json.dumps(dict(asset=asset,period=day,start=r['start'],multiplier=m,variant=v,**p),separators=(',',':'),allow_nan=False)+'\n')
            print(json.dumps(dict(asset=asset,origin=day,phase='trial' if day in DATES else 'earlier_oof',training_paths=packet['floor']['rows'])),flush=True)
    result=summarize_asset(asset,later,records,origins);result['predictions_sha256']=digest(directory/'predictions.jsonl.gz')
    dump(directory/'research.json',result);return result


def check_baseline(asset,result,previous):
    old=json.loads((previous/asset/'research.json').read_text())
    for m in ('100','1000'):
        p=result['results']['trial'][m]['variants']['previous_formula'];q=old['results'][m]['variants']['calendar_liquidity_raw_cdf']
        for cohort in ('matched','all_clean'):
            for group in ('overall','weekday','weekend'):
                actual={k:v for k,v in p[cohort][group].items() if k!='flat_guard_refusals'}
                same(actual,q[cohort][group])


def run(output):
    started=time.monotonic();plan=verify_plan(output);earlier,rows,liquidity,monthly,binding=inputs(plan);results=[]
    for a in ('ETH','HYPE'):
        r=study_asset(a,earlier[a],rows[a],liquidity,monthly,output);check_baseline(a,r,Path(plan['previous']));results.append(r)
    verify_plan(output);result=dict(protocol_sha256=digest(output/'protocol.json'),bindings=binding,
        research_sha256={a:digest(output/a/'research.json') for a in ('ETH','HYPE')},
        qualifying_variants={r['asset']:{phase:{m:v['qualifying_variants'] for m,v in pp.items()} for phase,pp in r['results'].items()} for r in results},
        elapsed_seconds=time.monotonic()-started,baseline_exactly_reproduced=True,live_policy_changed=False,no_promotion=True)
    dump(output/'research.json',result);return result


def manual_floor(row,model,calendar):
    a=row['activity_features'];change=str(sum(a['changes_30']>=x for x in (1,4,11)))
    key=change+':'+str(sum(a['idle_ms']>=x for x in (1500,3000,10000,30000,60000)))
    value=model['global_cell'];value=model['changes'].get(change,value);value=model['activity'].get(key,value)
    if calendar:value=model['calendar'].get(key+':'+str(int(weekend(row))),value)
    return value['p0'],max(value['p0'],value['floor'])


def independent_quote(r,m,v,packet,cache):
    supported=available(r,'calendar_liquidity');mode='previous';row=r;guard=None
    if v in ('activity_hurdle','calendar_hurdle'):
        mode='calendar' if v=='calendar_hurdle' else 'activity'
        raw=manual_floor(r,packet['floor'],mode=='calendar') if supported else (None,None)
        if supported:
            a=r['activity_features'];key=str(sum(a['changes_30']>=x for x in (1,4,11)))+':'+str(sum(a['idle_ms']>=x for x in (1500,3000,10000,30000,60000)))
            if mode=='calendar':key+=':'+str(int(weekend(r)))
            row=dict(r,activity_state=key)
    else:
        raw0=manual(r,packet['risk']) if supported else dict(p0=None,floor=None);raw=(raw0['p0'],raw0['floor'])
    identity=dict(heads={field:[dict(supported=False)]*6 for field in ('p0','floor')})
    policy=dict(name=v,kind='empirical',prior=32,family='activity',anchor='slow',level=1.,gate=1.)
    p=independent_entry(row,m,policy,raw,{'32':identity},None,None,packet['movement'][mode],cache[mode])
    if not supported and r['adaptive_features'] is not None:p['reason']='missing_liquidity'
    p.update(width_ppb=p['width']*1000 if p['width'] is not None else None,
        barrier_delta_units=r['entry']*p['width']//1000000 if p['width'] is not None else None)
    if supported and v!='previous_formula':
        a=r['activity_features']
        if a['idle_is_lower_bound'] or a['idle_ms']>=30000 or a['changes_30']==0:guard='flat_oracle_veto'
        elif v in ('activity_hurdle','calendar_hurdle') and m==1000 and (a['idle_ms']>=3000 or a['changes_30']<4):guard='insufficient_recent_oracle_activity'
    if guard:p.update(offered=False,survived=None,reason=';'.join(filter(None,(p['reason'],guard))))
    return dict(p,flat_guard=guard,estimated_zero_probability=raw[0],estimated_minimum_probability=raw[1])


def audit_asset(asset,earlier,rows,liquidity,monthly,directory):
    meta=json.loads((directory/'research.json').read_text());pool=earlier+[r for r in rows if clean(r) and r.get('liquidity') is not None]
    later=evaluation_rows(earlier,rows);records={(m,v):[] for m in MULTIPLIERS for v in VARIANTS};count=0
    if [o['period'] for o in meta['origins']]!=list(OOF_DATES+DATES) or digest(directory/'predictions.jsonl.gz')!=meta['predictions_sha256']:raise ValueError('Flat-aware trace binding differs')
    with gzip.open(directory/'predictions.jsonl.gz','rt') as stream:
        for item in meta['origins']:
            day=item['period'];path=directory/'origins'/(day+'.json.gz')
            if digest(path)!=item['sha256']:raise ValueError('Flat-aware origin binding differs')
            with gzip.open(path,'rt') as model_stream:packet=json.load(model_stream)
            same(packet['floor'],fit_floor(pool,asset,day));risk,binding=prior_risk(asset,day,liquidity,monthly)
            same(packet['risk'],risk['models']['calendar_liquidity']);same(packet['risk_binding'],binding)
            train=training(pool,asset,day)
            for mode,data in packet['movement'].items():
                if data['asset']!=asset or data['cutoff']!=day or data['training_dates']!=sorted({r['period'] for r in train}):raise ValueError('Movement origin contamination')
                source=data['anchors']['slow'];verify_distribution(source['global_distribution'],train,'slow');groups={}
                for r in train:
                    key=r['activity_state'] if mode=='previous' else cell_key(r,mode=='calendar');groups.setdefault(key,[]).append(r)
                if set(groups)!=set(source['families']['activity']):raise ValueError('Conditional movement partition differs')
                for key,part in groups.items():verify_distribution(source['families']['activity'][key],part,'slow')
            cache={k:{} for k in packet['movement']}
            for r in (r for r in later if r['period']==day):
                for m in MULTIPLIERS:
                    for v in VARIANTS:
                        p=independent_quote(r,m,v,packet,cache);count+=1
                        same(json.loads(stream.readline()),dict(asset=asset,period=day,start=r['start'],multiplier=m,variant=v,**p));records[m,v].append(p)
        if stream.readline():raise ValueError('Extra flat-aware decisions')
    result=summarize_asset(asset,later,records,meta['origins']);result['predictions_sha256']=meta['predictions_sha256'];same(meta,result)
    return dict(asset=asset,origins=len(OOF_DATES+DATES),floor_models_refit=len(OOF_DATES+DATES),
        decisions_independently_replayed=count,positive_cdf_points_verified=True,all_cohort_and_calendar_metrics_reconciled=True)


def audit(output):
    plan=verify_plan(output);meta=json.loads((output/'research.json').read_text())
    if digest(output/'protocol.json')!=meta['protocol_sha256']:raise ValueError('Flat-aware protocol differs')
    earlier,rows,liquidity,monthly,binding=inputs(plan);same(binding,meta['bindings']);reports=[]
    for a in ('ETH','HYPE'):
        if digest(output/a/'research.json')!=meta['research_sha256'][a]:raise ValueError('Flat-aware asset metadata differs')
        reports.append(audit_asset(a,earlier[a],rows[a],liquidity,monthly,output/a));check_baseline(a,json.loads((output/a/'research.json').read_text()),Path(plan['previous']))
    verify_plan(output);result=dict(passed=True,research_sha256=digest(output/'research.json'),auditor_sha256=digest(Path(__file__)),assets=reports,previous_baseline_reconciled=True)
    dump(output/'audit.json',result);return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--previous',type=Path);parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--declare',action='store_true');parser.add_argument('--audit',action='store_true');args=parser.parse_args()
    r=declare(args.previous,args.output) if args.declare else audit(args.output) if args.audit else run(args.output)
    print(json.dumps(dict(declared=args.declare,audited=args.audit,passed=r.get('passed'),qualifying=r.get('qualifying_variants')),indent=2))
