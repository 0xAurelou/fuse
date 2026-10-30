#!/usr/bin/env python3
"""Consecutive-day 30-second oracle/liquidity development study and replay audit."""
import argparse
from datetime import datetime,timezone
import gzip
import json
from pathlib import Path
import shutil
import time

from audit_historical_liquidity import manual
from audit_payout_walkforward import same
from fetch_tardis_liquidity_trial import ASSETS,CHANNELS,DATES,origin
from historical_liquidity import (SPEC as OLD_SPEC,VARIANTS,depth_group,fit,predict,
                                 summarize,paired_result,weighted_terciles)
from payout_risk import clean_training
from research_historical_liquidity import book_manifest,sources
from research_payout_risk import digest,dump,load_parent
from trial_liquidity import parse_day

SPEC=dict(OLD_SPEC,version='consecutive-trial-liquidity-v2',warmup_dates=20,
    fitting='Separate assets. Twenty earlier first-of-month dates January 2025 through August 2026 warm up; score all September 1–10 dates once, adding only strictly earlier matured matched paths. Equal training mass per date; ridge .003; no selection on trial outcomes.',
    uncertainty='Seeded 2000-resample equal-day bootstrap, descriptive only: ten consecutive dates with two weekend dates are neither independent trials nor a causal test.',
    limitations='Historical development, previously inspected monthly parent and September 1 oracle outcomes; daily context resets, one venue/provider, only two weekend dates; no production or profitability claim.',
    implementation_amendment='Version 2 filters candidates to expiry plus 30 seconds strictly before the next origin before calling the existing training validator. The initial declaration is retained in the sibling v1 packet; no model selection or feature change.')
WARMUP_DATES=tuple('%04d-%02d-01'%(year,month) for year in (2025,2026)
                   for month in range(1,13) if (year,month)<=(2026,8))


def declare(parent,monthly,raw,output,amends=None):
    if output.exists():raise ValueError('Use a new study directory')
    p=json.loads((raw/'download-protocol.json').read_text())
    if p['dates']!=list(DATES) or p['assets']!=list(ASSETS) or p['channels']!=list(CHANNELS):raise ValueError('Wrong trial universe')
    output.mkdir(parents=True);(output/'source').mkdir()
    paths=sorted(set(sources()+[Path(__file__).resolve()]))
    for path in paths:shutil.copyfile(path,output/'source'/path.name)
    plan=dict(spec=SPEC,parent=str(parent.resolve()),monthly=str(monthly.resolve()),raw=str(raw.resolve()),
        parent_sha256=digest(parent/'research.json'),monthly_sha256=digest(monthly/'research.json'),
        monthly_audit_sha256=digest(monthly/'audit.json'),raw_protocol_sha256=digest(raw/'download-protocol.json'),
        source_sha256={p.name:digest(p) for p in paths},evaluation_dates=DATES,warmup_dates=WARMUP_DATES,
        declared_before_trial_parse_or_fit=True,data_role='historical development, not an untouched holdout',
        primary='Calendar versus calendar plus liquidity, paired equal-day zero-motion log loss on identical valid oracle paths with strictly prior fresh books.',
        no_hyperparameter_selection=True,no_promotion=True,live_policy_changed=False,fresh_collector_changed=False)
    if amends:
        plan['previous_implementation_declaration']=dict(directory=str(amends.resolve()),protocol_sha256=digest(amends/'protocol.json'))
    dump(output/'protocol.json',plan);return plan


def verify_plan(output):
    plan=json.loads((output/'protocol.json').read_text())
    for name,sha in plan['source_sha256'].items():
        if digest(output/'source'/name)!=sha or digest(Path(__file__).with_name(name))!=sha:raise ValueError('Declared source changed: '+name)
    for folder,filename,key in (('parent','research.json','parent_sha256'),('monthly','research.json','monthly_sha256'),
        ('monthly','audit.json','monthly_audit_sha256'),('raw','download-protocol.json','raw_protocol_sha256')):
        if digest(Path(plan[folder])/filename)!=plan[key]:raise ValueError('Declared source binding changed')
    if plan['evaluation_dates']!=list(DATES) or plan['warmup_dates']!=list(WARMUP_DATES):raise ValueError('Date universe changed')
    if plan.get('previous_implementation_declaration'):
        previous=plan['previous_implementation_declaration']
        if digest(Path(previous['directory'])/'protocol.json')!=previous['protocol_sha256']:raise ValueError('Previous declaration changed')
    return plan


def trial_manifest(raw):
    p=json.loads((raw/'download-protocol.json').read_text());m=json.loads((raw/'download-manifest.json').read_text())
    if not m['complete'] or m['protocol_sha256']!=digest(raw/'download-protocol.json') or digest(raw/'fetch-source.py')!=p['fetcher_sha256']:
        raise ValueError('Complete matching trial download required')
    expected={r['path']:r for r in p['requests']}
    if len(m['files'])!=len(expected) or {r['path'] for r in m['files']}!=set(expected):raise ValueError('Trial population differs')
    for r in m['files']:
        if r['status']!='downloaded' or any(r[k]!=v for k,v in expected[r['path']].items()) or digest(raw/r['path'])!=r['sha256']:
            raise ValueError('Trial payload or request differs')
    return m


def warmup(plan):
    monthly=Path(plan['monthly']);meta=json.loads((monthly/'research.json').read_text())
    audit=json.loads((monthly/'audit.json').read_text())
    if not audit['passed'] or audit['research_sha256']!=digest(monthly/'research.json') or digest(monthly/'joined.jsonl.gz')!=meta['joined_sha256']:
        raise ValueError('Matching audited monthly liquidity study required')
    if meta['protocol']['parent']!=plan['parent']:raise ValueError('Warmup oracle parent differs')
    books=Path(meta['protocol']['books']);book_manifest(books)
    if digest(books/'download-manifest.json')!=meta['book_manifest_sha256']:raise ValueError('Warmup book manifest differs')
    rows,_,binding=load_parent(Path(plan['parent']));maps={a:{r['start']:r for r in rows[a]} for a in ASSETS}
    kept={a:[] for a in ASSETS};seen=set()
    with gzip.open(monthly/'joined.jsonl.gz','rt') as stream:
        for line in stream:
            b=json.loads(line);a=b['asset'];key=(a,b['start'])
            if key in seen:raise ValueError('Duplicate warmup entry')
            seen.add(key)
            if b['period'] not in WARMUP_DATES:continue
            r=maps[a][b['start']]
            if r['period']!=b['period']:raise ValueError('Warmup oracle date differs')
            if r['valid'] and r['adaptive_features'] is not None and b['liquidity'] is not None:
                if not b['liquidity']['received_at_ms']<r['start']:raise ValueError('Non-prior warmup book')
                kept[a].append(dict(r,liquidity=b['liquidity']))
    for a in ASSETS:
        if sorted({r['period'] for r in kept[a]})!=list(WARMUP_DATES):raise ValueError('Twenty earlier warmup dates required')
    return kept,binding


def fitted(train,asset,day,variant):
    return dict(fit(train,asset,day,variant),spec=SPEC)


def training(rows,asset,day):
    boundary=origin(day)
    return clean_training([r for r in rows if r['period']<day and r['expiry']+30000<boundary],asset,day)


def metrics(asset,later,values,groups,origins):
    daily={}
    for day in DATES:
        ids=[i for i,r in enumerate(later) if r['period']==day]
        daily[day]={v:summarize([later[i] for i in ids],[values[v][i] for i in ids]) for v in VARIANTS}
    strata={}
    for name in ('weekday','weekend','low','middle','high'):
        ids=[i for i,r in enumerate(later) if (datetime.fromtimestamp(r['start']/1000,timezone.utc).weekday()>=5)==(name=='weekend')]
        if name in ('low','middle','high'):ids=[i for i,g in enumerate(groups) if g==name]
        strata[name]={v:summarize([later[i] for i in ids],[values[v][i] for i in ids]) for v in VARIANTS}
        days=sorted({later[i]['period'] for i in ids})
        # Equal-day liquidity means avoid weighting a day by its retained path count.
        strata[name]['liquidity_summary']=dict(dates=days,**{key:sum(
            sum(fn(later[i]['liquidity']) for i in ids if later[i]['period']==d)/sum(later[i]['period']==d for i in ids)
            for d in days)/len(days) if days else None for key,fn in (
            ('equal_day_spread_bps',lambda b:b['spread_bps']),
            ('equal_day_minimum_top5_side_usd',lambda b:min(b['top5_bid_usd'],b['top5_ask_usd'])))})
    return dict(asset=asset,evaluated_dates=list(DATES),unique_matched_evaluated_paths=len(later),origins=origins,
        pooled={v:summarize(later,values[v]) for v in VARIANTS},daily=daily,strata=strata,
        paired_primary=paired_result(daily),paired_activity=paired_result(daily,'activity','activity_liquidity'),
        paired_floor=paired_result(daily,head='floor'),no_promotion=True)


def study_asset(asset,rows,output):
    directory=output/asset;directory.mkdir();(directory/'origins').mkdir()
    later=[];values={v:[] for v in VARIANTS};groups=[];origins=[]
    with gzip.open(directory/'predictions.jsonl.gz','xt',compresslevel=5) as stream:
        for day in DATES:
            train=training(rows,asset,day)
            scored=[r for r in rows if r['period']==day]
            if not scored:raise ValueError('Empty evaluation date')
            edges=weighted_terciles(train);packet=dict(asset=asset,cutoff=day,depth_tercile_edges=edges,
                models={v:fitted(train,asset,day,v) for v in VARIANTS})
            path=directory/'origins'/(day+'.json');dump(path,packet);origins.append(dict(period=day,sha256=digest(path)))
            for r in scored:
                group=depth_group(r,edges);later.append(r);groups.append(group)
                for v in VARIANTS:
                    p=predict(r,packet['models'][v]);values[v].append(p)
                    stream.write(json.dumps(dict(asset=asset,period=day,start=r['start'],variant=v,depth_group=group,**p),separators=(',',':'))+'\n')
            print(json.dumps(dict(asset=asset,origin=day,training_dates=len(packet['models']['calendar']['training_dates']),train=len(train),scored=len(scored))),flush=True)
    result=metrics(asset,later,values,groups,origins);result['predictions_sha256']=digest(directory/'predictions.jsonl.gz')
    dump(directory/'research.json',result);return result


def build(plan,output=None,compare=None):
    rows,binding=warmup(plan);raw=Path(plan['raw']);manifest=trial_manifest(raw);coverage=[];count=0
    stream=gzip.open(output/'rows.jsonl.gz','xt',compresslevel=5) if output else None
    retained=gzip.open(compare/'rows.jsonl.gz','rt') if compare else None
    try:
        for day in DATES:
            part,profiles=parse_day([f for f in manifest['files'] if f['day']==day],raw,day);coverage+=profiles
            for a in ASSETS:
                for r in part[a]:
                    if stream:stream.write(json.dumps(r,separators=(',',':'),allow_nan=False)+'\n')
                    if retained:same(json.loads(retained.readline()),r)
                    count+=1
                    if r['valid'] and r['adaptive_features'] is not None and r['liquidity'] is not None:rows[a].append(r)
            print(json.dumps(dict(parsed_day=day,matched={p['asset']:p['matched_paths'] for p in profiles})),flush=True)
        if retained and retained.readline():raise ValueError('Extra oracle/book grid rows')
    finally:
        if stream:stream.close()
        if retained:retained.close()
    return rows,coverage,binding,manifest,count


def run(output):
    started=time.monotonic();plan=verify_plan(output);rows,coverage,binding,manifest,count=build(plan,output)
    dump(output/'coverage.json',coverage);results=[study_asset(a,rows[a],output) for a in ASSETS];verify_plan(output)
    result=dict(protocol_sha256=digest(output/'protocol.json'),bindings=binding,
        raw_manifest_sha256=digest(Path(plan['raw'])/'download-manifest.json'),raw_payloads=len(manifest['files']),
        rows_sha256=digest(output/'rows.jsonl.gz'),coverage_sha256=digest(output/'coverage.json'),grid_rows=count,
        research_sha256={a:digest(output/a/'research.json') for a in ASSETS},
        paired_primary={r['asset']:r['paired_primary'] for r in results},elapsed_seconds=time.monotonic()-started,
        live_policy_changed=False,fresh_collector_changed=False,no_promotion=True)
    dump(output/'research.json',result);return result


def audit_asset(asset,rows,directory):
    meta=json.loads((directory/'research.json').read_text());later=[];values={v:[] for v in VARIANTS};groups=[]
    if digest(directory/'predictions.jsonl.gz')!=meta['predictions_sha256'] or [r['period'] for r in meta['origins']]!=list(DATES):raise ValueError('Forecast binding differs')
    with gzip.open(directory/'predictions.jsonl.gz','rt') as stream:
        for item in meta['origins']:
            day=item['period'];path=directory/'origins'/(day+'.json')
            if digest(path)!=item['sha256']:raise ValueError('Model binding differs')
            packet=json.loads(path.read_text());train=training(rows,asset,day)
            edges=weighted_terciles(train);same(packet['depth_tercile_edges'],edges)
            if packet['asset']!=asset or packet['cutoff']!=day:raise ValueError('Model origin differs')
            for v in VARIANTS:same(packet['models'][v],fitted(train,asset,day,v))
            for r in (r for r in rows if r['period']==day):
                later.append(r);group=depth_group(r,edges);groups.append(group)
                for v in VARIANTS:
                    p=manual(r,packet['models'][v]);stored=json.loads(stream.readline())
                    same(stored,dict(asset=asset,period=day,start=r['start'],variant=v,depth_group=group,**p));values[v].append(p)
        if stream.readline():raise ValueError('Extra predictions')
    expected=metrics(asset,later,values,groups,meta['origins']);expected['predictions_sha256']=meta['predictions_sha256'];same(meta,expected)
    if len({r['start'] for r in later})!=len(later):raise ValueError('Duplicate evaluated path')
    return dict(asset=asset,origins=len(DATES),unique_paths=len(later),models_refit=len(DATES)*len(VARIANTS),predictions_manually_replayed=len(later)*len(VARIANTS))


def audit(output):
    plan=verify_plan(output);meta=json.loads((output/'research.json').read_text())
    for filename,key in (('protocol.json','protocol_sha256'),('rows.jsonl.gz','rows_sha256'),('coverage.json','coverage_sha256')):
        if digest(output/filename)!=meta[key]:raise ValueError('Study binding differs')
    rows,coverage,binding,manifest,count=build(plan,compare=output);same(binding,meta['bindings']);same(coverage,json.loads((output/'coverage.json').read_text()))
    if digest(Path(plan['raw'])/'download-manifest.json')!=meta['raw_manifest_sha256'] or count!=meta['grid_rows']:raise ValueError('Raw population differs')
    reports=[]
    for a in ASSETS:
        if digest(output/a/'research.json')!=meta['research_sha256'][a]:raise ValueError('Asset binding differs')
        reports.append(audit_asset(a,rows[a],output/a))
        same(meta['paired_primary'][a],json.loads((output/a/'research.json').read_text())['paired_primary'])
    verify_plan(output)
    report=dict(passed=True,research_sha256=digest(output/'research.json'),auditor_sha256=digest(Path(__file__)),
                raw_payloads_verified=len(manifest['files']),grid_rows_reconstructed=count,assets=reports)
    dump(output/'audit.json',report);return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--parent',type=Path);parser.add_argument('--monthly',type=Path);parser.add_argument('--raw',type=Path)
    parser.add_argument('--amends',type=Path)
    parser.add_argument('--declare',action='store_true');parser.add_argument('--audit',action='store_true');args=parser.parse_args()
    result=declare(args.parent,args.monthly,args.raw,args.output,args.amends) if args.declare else audit(args.output) if args.audit else run(args.output)
    print(json.dumps(dict(declared=args.declare,audited=args.audit,primary=result.get('paired_primary'),passed=result.get('passed')),indent=2))
