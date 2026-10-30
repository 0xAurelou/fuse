#!/usr/bin/env python3
"""Test historical measured liquidity beyond oracle activity and UTC calendar."""
import argparse
from collections import Counter
from datetime import datetime,timezone
import gzip
import json
from pathlib import Path
import shutil
import sys
import time

from fetch_historical_liquidity import ASSETS,DATES
from historical_liquidity import (SPEC,VARIANTS,depth_group,fit,join_day,paired_result,
    predict,summarize,weighted_terciles)
from payout_risk import clean_training
from research_payout_risk import digest,dump,load_parent


def sources():
    root=Path(__file__).resolve().parent;paths={Path(__file__).resolve()}
    for module in list(sys.modules.values()):
        name=getattr(module,'__file__',None)
        if name:
            p=Path(name).resolve()
            if p.parent==root and p.suffix=='.py':paths.add(p)
    return sorted(paths)


def declare(parent,books,output):
    if output.exists():raise ValueError('use a new research directory')
    p=json.loads((books/'download-protocol.json').read_text())
    if p['dates']!=list(DATES) or p['assets']!=list(ASSETS) or p['channel']!='l2Book':raise ValueError('wrong book universe')
    output.mkdir(parents=True);(output/'source').mkdir()
    paths=sources()
    for path in paths:shutil.copyfile(path,output/'source'/path.name)
    plan=dict(spec=SPEC,parent=str(parent.resolve()),books=str(books.resolve()),
        parent_sha256=digest(parent/'research.json'),book_protocol_sha256=digest(books/'download-protocol.json'),
        source_sha256={p.name:digest(p) for p in paths},dates=DATES,
        declared_before_join_or_fit=True,live_policy_changed=False,
        data_role='Matched historical development study, distinct from the ongoing fresh collection. Does not change or stop that recorder.')
    dump(output/'protocol.json',plan);return plan


def verify_plan(output):
    plan=json.loads((output/'protocol.json').read_text())
    for name,sha in plan['source_sha256'].items():
        if digest(output/'source'/name)!=sha or digest(Path(__file__).with_name(name))!=sha:raise ValueError('declared implementation differs: '+name)
    if digest(Path(plan['parent'])/'research.json')!=plan['parent_sha256'] or digest(Path(plan['books'])/'download-protocol.json')!=plan['book_protocol_sha256']:
        raise ValueError('source declaration differs')
    return plan


def book_manifest(root):
    manifest=json.loads((root/'download-manifest.json').read_text());protocol=json.loads((root/'download-protocol.json').read_text())
    if not manifest['complete'] or manifest['protocol_sha256']!=digest(root/'download-protocol.json'):
        raise ValueError('complete matching book download required')
    expected={p['path']:p for p in protocol['requests']}
    if len(expected)!=len(manifest['files']) or {p['path'] for p in manifest['files']}!=set(expected):raise ValueError('book slice population differs')
    if digest(root/'fetch-source.py')!=protocol['source_sha256'] or digest(root/'exchange-metadata.json')!=protocol['metadata_sha256']:
        raise ValueError('book fetch provenance differs')
    for p in manifest['files']:
        if p['status']!='downloaded' or any(p[k]!=v for k,v in expected[p['path']].items()) or digest(root/p['path'])!=p['sha256']:
            raise ValueError('book raw payload or URL differs')
    return manifest


def build(rows,books,manifest,output):
    joined={a:[] for a in ASSETS};coverage=[]
    rowmap={a:{r['start']:r for r in rows[a]} for a in ASSETS}
    with gzip.open(output/'joined.jsonl.gz','xt',compresslevel=5) as stream:
        for day in DATES:
            part,counts=join_day(books,[p for p in manifest['files'] if p['day']==day],day)
            for asset in ASSETS:
                clean=matched=zero=0;reasons=Counter()
                for p in part[asset]:
                    original=rowmap[asset][p['start']]
                    if original['period']!=day:raise ValueError('oracle row date differs')
                    stream.write(json.dumps(p,separators=(',',':'),allow_nan=False)+'\n')
                    if original['valid'] and original['adaptive_features'] is not None:
                        clean+=1;zero+=original['move']==0
                        if p['liquidity'] is not None:
                            joined[asset].append(dict(original,liquidity=p['liquidity']));matched+=1
                        else:reasons[p['join_reason']]+=1
                coverage.append(dict(asset=asset,period=day,clean_oracle_paths=clean,matched_paths=matched,
                    match_rate=matched/clean if clean else None,all_clean_zero_motion=zero,
                    unavailable_book_reasons=dict(reasons),raw_counts=counts))
            print(json.dumps(dict(joined_day=day,matched={a:sum(r['period']==day for r in joined[a]) for a in ASSETS})),flush=True)
    dump(output/'coverage.json',coverage);return joined


def study_asset(asset,rows,output):
    directory=output/asset;directory.mkdir();(directory/'origins').mkdir()
    later_dates=list(DATES[6:]);later=[];values={v:[] for v in VARIANTS};groups=[];models=[]
    with gzip.open(directory/'predictions.jsonl.gz','xt',compresslevel=5) as stream:
        for day in later_dates:
            train=clean_training([r for r in rows if r['period']<day],asset,day)
            scored=[r for r in rows if r['period']==day]
            if not scored:raise ValueError('empty matched scoring date')
            edges=weighted_terciles(train)
            packet=dict(asset=asset,cutoff=day,depth_tercile_edges=edges,
                        models={v:fit(train,asset,day,v) for v in VARIANTS})
            dump(directory/'origins'/(day+'.json'),packet)
            models.append(dict(period=day,sha256=digest(directory/'origins'/(day+'.json'))))
            for r in scored:
                group=depth_group(r,edges);groups.append(group);later.append(r)
                for variant in VARIANTS:
                    p=predict(r,packet['models'][variant]);values[variant].append(p)
                    stream.write(json.dumps(dict(asset=asset,period=day,start=r['start'],variant=variant,
                        depth_group=group,**p),separators=(',',':'),allow_nan=False)+'\n')
            print(json.dumps(dict(asset=asset,origin=day,train=len(train),scored=len(scored))),flush=True)
    daily={}
    for day in later_dates:
        ids=[i for i,r in enumerate(later) if r['period']==day]
        daily[day]={v:summarize([later[i] for i in ids],[values[v][i] for i in ids]) for v in VARIANTS}
    summaries={v:summarize(later,values[v]) for v in VARIANTS}
    strata={}
    for name in ('weekday','weekend','low','middle','high'):
        ids=[i for i,r in enumerate(later) if
             (datetime.fromtimestamp(r['start']/1000,timezone.utc).weekday()>=5)==(name=='weekend')]
        if name in ('low','middle','high'):ids=[i for i,g in enumerate(groups) if g==name]
        strata[name]={v:summarize([later[i] for i in ids],[values[v][i] for i in ids]) for v in VARIANTS}
        if ids:
            part=[later[i] for i in ids]
            strata[name]['liquidity_summary']=dict(mean_spread_bps=sum(r['liquidity']['spread_bps'] for r in part)/len(part),
                mean_minimum_top5_side_usd=sum(min(r['liquidity']['top5_bid_usd'],r['liquidity']['top5_ask_usd']) for r in part)/len(part))
    result=dict(asset=asset,evaluated_dates=later_dates,unique_matched_evaluated_paths=len(later),
        origins=models,pooled=summaries,daily=daily,strata=strata,
        paired_primary=paired_result(daily),paired_activity=paired_result(daily,'activity','activity_liquidity'),
        paired_floor=paired_result(daily,head='floor'),
        predictions_sha256=digest(directory/'predictions.jsonl.gz'),no_promotion=True)
    dump(directory/'research.json',result);return result


def run(output):
    start=time.monotonic();plan=verify_plan(output);books=Path(plan['books'])
    manifest=book_manifest(books);rows,_,bindings=load_parent(Path(plan['parent']))
    matched=build(rows,books,manifest,output)
    results=[study_asset(a,matched[a],output) for a in ASSETS]
    verify_plan(output)
    result=dict(protocol=plan,protocol_sha256=digest(output/'protocol.json'),bindings=bindings,
        book_manifest_sha256=digest(books/'download-manifest.json'),book_raw_payloads=len(manifest['files']),
        joined_sha256=digest(output/'joined.jsonl.gz'),coverage_sha256=digest(output/'coverage.json'),
        research_sha256={a:digest(output/a/'research.json') for a in ASSETS},
        paired_primary={r['asset']:r['paired_primary'] for r in results},
        elapsed_seconds=time.monotonic()-start,live_policy_changed=False,fresh_collector_changed=False,no_promotion=True)
    dump(output/'research.json',result);return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--parent',type=Path)
    parser.add_argument('--books',type=Path);parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--declare',action='store_true');args=parser.parse_args()
    result=declare(args.parent,args.books,args.output) if args.declare else run(args.output)
    print(json.dumps(dict(completed=not args.declare,primary=result.get('paired_primary'))))
