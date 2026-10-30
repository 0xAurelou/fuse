#!/usr/bin/env python3
"""Replay actual payout corridors on the audited consecutive oracle/book packet."""
import argparse
from collections import Counter
import gzip
import json
from pathlib import Path
import shutil
import time

from audit_historical_liquidity import manual
from audit_payout_empirical import independent_entry,verify_calibrator,verify_distribution
from audit_payout_walkforward import same
from fetch_tardis_liquidity_trial import ASSETS,DATES,origin
from historical_liquidity import predict
from payout_empirical import EmpiricalPredictor
from payout_risk import required_width,weekend
from payout_walkforward import reference
from research_asset_corridors import source_files
from research_payout_risk import digest,dump
from research_trial_liquidity import fitted,training,trial_manifest,verify_plan as verify_liquidity,warmup
from trial_payout import (MULTIPLIERS,RISKS,SPEC,VARIANTS,available,clean,forecasts,metrics,
                          origin_packet,quote,screen,shipped_width)


def declare(liquidity,output):
    if output.exists():raise ValueError('Use a new payout packet')
    verify_liquidity(liquidity);meta=json.loads((liquidity/'research.json').read_text());audit=json.loads((liquidity/'audit.json').read_text())
    if not audit['passed'] or audit['research_sha256']!=digest(liquidity/'research.json'):raise ValueError('Matching audited oracle/liquidity packet required')
    output.mkdir(parents=True);(output/'source').mkdir()
    paths=sorted(set(source_files()+[Path(__file__).resolve()]))
    for p in paths:shutil.copyfile(p,output/'source'/p.name)
    native=Path(__file__).resolve().parents[1]/'engine/internal/engine/pricing.go'
    vectors=native.parents[2]/'testdata/brownian-pricing-vectors.json'
    shutil.copyfile(native,output/'source/native-pricing.go');shutil.copyfile(vectors,output/'source/native-pricing-vectors.json')
    plan=dict(spec=SPEC,liquidity=str(liquidity.resolve()),liquidity_sha256=digest(liquidity/'research.json'),
        liquidity_audit_sha256=digest(liquidity/'audit.json'),rows_sha256=meta['rows_sha256'],
        sources={p.name:digest(p) for p in paths},native_pricing_sha256=digest(native),native_vectors_sha256=digest(vectors),
        declared_before_payout_replay=True,already_inspected_oracle_and_liquidity_outcomes=True,
        new_data_downloaded=False,live_policy_changed=False,fresh_collector_changed=False,no_promotion=True)
    dump(output/'protocol.json',plan);return plan


def verify_plan(output):
    p=json.loads((output/'protocol.json').read_text());liquidity=Path(p['liquidity'])
    for name,sha in p['sources'].items():
        if digest(output/'source'/name)!=sha or digest(Path(__file__).with_name(name))!=sha:raise ValueError('Payout source changed: '+name)
    for name,key in (('research.json','liquidity_sha256'),('audit.json','liquidity_audit_sha256'),('rows.jsonl.gz','rows_sha256')):
        if digest(liquidity/name)!=p[key]:raise ValueError('Payout input binding changed')
    for name,key in (('native-pricing.go','native_pricing_sha256'),('native-pricing-vectors.json','native_vectors_sha256')):
        if digest(output/'source'/name)!=p[key]:raise ValueError('Native source snapshot changed')
    return p


def inputs(plan):
    root=Path(plan['liquidity']);p=verify_liquidity(root);meta=json.loads((root/'research.json').read_text())
    audit=json.loads((root/'audit.json').read_text())
    if not audit['passed'] or audit['research_sha256']!=digest(root/'research.json'):raise ValueError('Source audit differs')
    raw=Path(p['raw']);manifest=trial_manifest(raw)
    if digest(raw/'download-manifest.json')!=meta['raw_manifest_sha256']:raise ValueError('Raw source changed')
    earlier,binding=warmup(p);rows={a:[] for a in ASSETS}
    with gzip.open(root/'rows.jsonl.gz','rt') as stream:
        for line in stream:
            r=json.loads(line);rows[r['asset']].append(r)
    for a in ASSETS:
        expected=[origin(d)+i*30000 for d in DATES for i in range(2880)]
        if [r['start'] for r in rows[a]]!=expected or any(r['period'] not in DATES for r in rows[a]):raise ValueError('Evaluation grid differs')
    return earlier,rows,p,dict(parent= binding,raw_payloads_verified=len(manifest['files']),raw_manifest_sha256=meta['raw_manifest_sha256'])


def monthly_references(asset,earlier,monthly,independent=False):
    meta=json.loads((monthly/'research.json').read_text());path=monthly/asset/'research.json'
    if digest(path)!=meta['research_sha256'][asset]:raise ValueError('Monthly asset binding differs')
    m=json.loads(path.read_text());pred=monthly/asset/'predictions.jsonl.gz'
    if digest(pred)!=m['predictions_sha256']:raise ValueError('Monthly OOF forecast binding differs')
    maps={r['start']:r for r in earlier};refs={f:[] for f in RISKS};seen={f:set() for f in RISKS};models={}
    origins={v['period']:v['sha256'] for v in m['origins']}
    with gzip.open(pred,'rt') as stream:
        for line in stream:
            v=json.loads(line);f=v['variant']
            if v['period']>=DATES[0]:continue
            r=maps[v['start']]
            if f not in RISKS or v['start'] in seen[f] or r['period']!=v['period']:raise ValueError('Monthly reference population differs')
            seen[f].add(v['start']);raw=dict(p0=v['p0'],floor=v['floor'])
            if independent:
                day=v['period']
                if day not in models:
                    path=monthly/asset/'origins'/(day+'.json')
                    if digest(path)!=origins[day]:raise ValueError('Monthly risk model binding differs')
                    models[day]=json.loads(path.read_text())
                same(raw,manual(r,models[day]['models'][f]))
            refs[f].append(reference(r,(raw['p0'],raw['floor']),f))
    expected={r['start'] for r in earlier if r['period']>='2025-07-01'}
    if any(seen[f]!=expected for f in RISKS):raise ValueError('Incomplete earlier OOF reference set')
    return refs


def risk_origin(root,asset,day):
    path=root/asset/'research.json';meta=json.loads(path.read_text());top=json.loads((root/'research.json').read_text())
    if digest(path)!=top['research_sha256'][asset]:raise ValueError('Daily risk metadata changed')
    expected={r['period']:r['sha256'] for r in meta['origins']};path=root/asset/'origins'/(day+'.json')
    if digest(path)!=expected[day]:raise ValueError('Daily risk origin changed')
    return json.loads(path.read_text()),dict(path=str(path),sha256=expected[day])


def summarize_asset(asset,rows,records,origins):
    results={}
    for m in MULTIPLIERS:
        variants={}
        for v in VARIANTS:
            groups={}
            for cohort in ('matched','all_clean'):
                groups[cohort]={}
                for group in ('overall','weekday','weekend'):
                    ids=[i for i,r in enumerate(rows) if (cohort=='all_clean' or r.get('liquidity') is not None and r['adaptive_features'] is not None)
                         and (group=='overall' or weekend(r)==(group=='weekend'))]
                    part=[rows[i] for i in ids];values=[records[m,v][i] for i in ids]
                    groups[cohort][group]=metrics(part,values,m)
            groups['screen']=screen(groups['matched']['overall'],m,v);variants[v]=groups
        results[str(m)]=dict(variants=variants,qualifying_variants=[v for v in VARIANTS if variants[v]['screen']['qualifies']])
    return dict(asset=asset,evaluated_dates=list(DATES),grid_entries=len(rows),origins=origins,
        matched_clean_paths=sum(clean(r) and r.get('liquidity') is not None for r in rows),
        all_clean_paths=sum(clean(r) for r in rows),results=results,no_promotion=True)


def save_gzip(path,value):
    with gzip.open(path,'xt',compresslevel=5) as stream:json.dump(value,stream,separators=(',',':'),allow_nan=False)


def study_asset(asset,earlier,rows,liquidity,monthly,output):
    directory=output/asset;directory.mkdir();(directory/'origins').mkdir()
    refs=monthly_references(asset,earlier,monthly);pool=earlier+[r for r in rows if clean(r) and r.get('liquidity') is not None]
    records={(m,v):[] for m in MULTIPLIERS for v in VARIANTS};origins=[]
    with gzip.open(directory/'predictions.jsonl.gz','xt',compresslevel=5) as stream:
        for day in DATES:
            risk,binding=risk_origin(liquidity,asset,day);packet=origin_packet(pool,asset,day,risk,refs,binding)
            path=directory/'origins'/(day+'.json.gz');save_gzip(path,packet)
            origins.append(dict(period=day,sha256=digest(path)));predictor=EmpiricalPredictor(packet['movement'])
            for r in (r for r in rows if r['period']==day):
                raw,values=forecasts(r,packet,predict)
                for m in MULTIPLIERS:
                    for v in VARIANTS:
                        p=quote(r,values.get(v,dict(p0=None,floor=None,calibrated0=False,calibrated_floor=False)),m,v,predictor)
                        records[m,v].append(p);stream.write(json.dumps(dict(asset=asset,period=day,start=r['start'],multiplier=m,variant=v,**p),separators=(',',':'),allow_nan=False)+'\n')
                if clean(r) and r.get('liquidity') is not None:
                    for f in RISKS:refs[f].append(reference(r,(raw[f]['p0'],raw[f]['floor']),f))
            print(json.dumps(dict(asset=asset,quoted_day=day,positive_training_paths=packet['movement']['anchors']['slow']['global_distribution']['n'],calibration_references=packet['calibration_counts']['calendar'])),flush=True)
    result=summarize_asset(asset,rows,records,origins);result['predictions_sha256']=digest(directory/'predictions.jsonl.gz')
    dump(directory/'research.json',result);return result


def run(output):
    started=time.monotonic();plan=verify_plan(output);earlier,rows,parent,binding=inputs(plan)
    results=[study_asset(a,earlier[a],rows[a],Path(plan['liquidity']),Path(parent['monthly']),output) for a in ASSETS]
    verify_plan(output);result=dict(protocol_sha256=digest(output/'protocol.json'),bindings=binding,
        research_sha256={a:digest(output/a/'research.json') for a in ASSETS},
        qualifying_variants={r['asset']:{m:v['qualifying_variants'] for m,v in r['results'].items()} for r in results},
        elapsed_seconds=time.monotonic()-started,live_policy_changed=False,no_promotion=True)
    dump(output/'research.json',result);return result


def independent_quote(r,m,v,raw,packet,cache):
    if v in ('shipped_formula','minimum_width_floor'):
        width=(shipped_width(r['asset'],m) if v=='shipped_formula' else 1000) if r['adaptive_features'] is not None else None
        delta=r['entry']*width//10**9 if width is not None else None
        reason='missing_history' if width is None else 'unrepresentable_barrier' if delta<=0 else ''
        shadow=r['move']<delta if r['valid'] and delta is not None else None
        return dict(width=width/1000 if v=='shipped_formula' and width is not None else 1 if width is not None else None,
            width_ppb=width,barrier_delta_units=delta,offered=not reason,reason=reason,positive_q=None,tail_mass=None,
            tail_supported=None,child_supported=None,p0=None,floor=None,calibrated0=False,calibrated_floor=False,shadow=shadow,survived=shadow if not reason else None)
    mode='cal32' if '_cal32_' in v else 'raw';f=v.removesuffix('_'+mode+'_cdf') if hasattr(v,'removesuffix') else v[:-len('_'+mode+'_cdf')]
    cal=packet['calibrators'][f] if mode=='cal32' else dict(heads={field:[dict(supported=False)]*6 for field in ('p0','floor')})
    policy=dict(name=v,kind='empirical',prior=32,family='activity',anchor='slow',level=1.,gate=1.)
    p=independent_entry(r,m,policy,(raw[f]['p0'],raw[f]['floor']),{'32':cal},None,None,packet['movement'],cache)
    if f.endswith('_liquidity') and r['adaptive_features'] is not None and r.get('liquidity') is None:p['reason']='missing_liquidity'
    return dict(p,width_ppb=p['width']*1000 if p['width'] is not None else None,
        barrier_delta_units=r['entry']*p['width']//1000000 if p['width'] is not None else None)


def audit_asset(asset,earlier,rows,liquidity,monthly,directory):
    meta=json.loads((directory/'research.json').read_text());refs=monthly_references(asset,earlier,monthly,True)
    pool=earlier+[r for r in rows if clean(r) and r.get('liquidity') is not None];origins=meta['origins'];count=0
    if [o['period'] for o in origins]!=list(DATES) or digest(directory/'predictions.jsonl.gz')!=meta['predictions_sha256']:raise ValueError('Payout trace binding differs')
    records={(m,v):[] for m in MULTIPLIERS for v in VARIANTS}
    with gzip.open(directory/'predictions.jsonl.gz','rt') as stream:
        for item in origins:
            day=item['period'];path=directory/'origins'/(day+'.json.gz')
            if digest(path)!=item['sha256']:raise ValueError('Payout model binding differs')
            with gzip.open(path,'rt') as model_stream:packet=json.load(model_stream)
            risk,binding=risk_origin(liquidity,asset,day);same(packet['risk_binding'],binding);same(packet['risk'],risk['models'])
            train=training(pool,asset,day)
            if packet['asset']!=asset or packet['cutoff']!=day or packet['movement']['training_dates']!=sorted({r['period'] for r in train}):raise ValueError('Payout origin contamination')
            for f in RISKS:
                same(packet['risk'][f],fitted(train,asset,day,f))
                mature=[r for r in refs[f] if r['expiry']+30000<origin(day)]
                if packet['calibration_counts'][f]!=len(mature) or any(r['period']>=day for r in mature):raise ValueError('Calibration maturity differs')
                verify_calibrator(packet['calibrators'][f],mature)
            data=packet['movement']['anchors']['slow'];verify_distribution(data['global_distribution'],train,'slow');groups={}
            for r in train:groups.setdefault(r['activity_state'],[]).append(r)
            if set(groups)!=set(data['families']['activity']):raise ValueError('Positive movement groups differ')
            for group,part in groups.items():verify_distribution(data['families']['activity'][group],part,'slow')
            cache={}
            for r in (r for r in rows if r['period']==day):
                raw={f:manual(r,packet['risk'][f]) if available(r,f) else dict(p0=None,floor=None) for f in RISKS}
                for m in MULTIPLIERS:
                    for v in VARIANTS:
                        p=independent_quote(r,m,v,raw,packet,cache);stored=json.loads(stream.readline());count+=1
                        same(stored,dict(asset=asset,period=day,start=r['start'],multiplier=m,variant=v,**p));records[m,v].append(p)
                if clean(r) and r.get('liquidity') is not None:
                    for f in RISKS:refs[f].append(reference(r,(raw[f]['p0'],raw[f]['floor']),f))
        if stream.readline():raise ValueError('Extra payout predictions')
    expected=summarize_asset(asset,rows,records,origins);expected['predictions_sha256']=meta['predictions_sha256'];same(meta,expected)
    return dict(asset=asset,grid_entries=len(rows),decisions_replayed=count,risk_models_refit=len(DATES)*len(RISKS),
        positive_cdf_points_and_calibration_verified=True,all_calendar_and_cohort_metrics_reconciled=True)


def audit(output):
    plan=verify_plan(output);meta=json.loads((output/'research.json').read_text())
    if digest(output/'protocol.json')!=meta['protocol_sha256']:raise ValueError('Payout protocol differs')
    earlier,rows,parent,binding=inputs(plan);same(binding,meta['bindings']);reports=[]
    for a in ASSETS:
        if digest(output/a/'research.json')!=meta['research_sha256'][a]:raise ValueError('Payout asset metadata differs')
        reports.append(audit_asset(a,earlier[a],rows[a],Path(plan['liquidity']),Path(parent['monthly']),output/a))
    verify_plan(output);result=dict(passed=True,research_sha256=digest(output/'research.json'),auditor_sha256=digest(Path(__file__)),assets=reports)
    dump(output/'audit.json',result);return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--liquidity',type=Path);parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--declare',action='store_true');parser.add_argument('--audit',action='store_true');args=parser.parse_args()
    result=declare(args.liquidity,args.output) if args.declare else audit(args.output) if args.audit else run(args.output)
    print(json.dumps(dict(declared=args.declare,audited=args.audit,passed=result.get('passed'),qualifying=result.get('qualifying_variants')),indent=2))
