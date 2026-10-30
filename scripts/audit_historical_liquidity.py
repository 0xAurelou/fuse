#!/usr/bin/env python3
"""Reconstruct matched history and audit earlier-only paired forecasts."""
import argparse
from collections import Counter
from datetime import datetime,timezone
import gzip
import json
import math
from pathlib import Path

from audit_payout_risk import close
from audit_payout_walkforward import same
from fetch_historical_liquidity import ASSETS,DATES
from historical_liquidity import (VARIANTS,depth_group,fit,join_day,paired_result,
                                  summarize,vector,weighted_terciles)
from payout_risk import clean_training
from research_historical_liquidity import book_manifest,verify_plan
from research_payout_risk import digest,dump,load_parent


def manual(row,model):
    values=vector(row,model['variant']);z=[1.]+[min(5,max(-5,(v-m)/s)) for v,m,s in zip(values,model['center'],model['sd'])]
    p=[]
    for key in ('zero_coefficients','floor_coefficients'):
        score=sum(a*b for a,b in zip(z,model[key]));score=max(-30,min(30,score));p.append(1/(1+math.exp(-score)))
    return dict(p0=p[0],floor=max(p))


def audit_asset(asset,rows,directory):
    meta=json.loads((directory/'research.json').read_text())
    if digest(directory/'predictions.jsonl.gz')!=meta['predictions_sha256']:raise ValueError('prediction binding differs')
    if [v['period'] for v in meta['origins']]!=list(DATES[6:]):raise ValueError('origin population differs')
    later=[];forecasts={v:[] for v in VARIANTS};groups=[];total=0
    with gzip.open(directory/'predictions.jsonl.gz','rt') as stream:
        for origin in meta['origins']:
            day=origin['period'];path=directory/'origins'/(day+'.json')
            if digest(path)!=origin['sha256']:raise ValueError('model binding differs')
            packet=json.loads(path.read_text());earlier=clean_training([r for r in rows if r['period']<day],asset,day)
            if packet['asset']!=asset or packet['cutoff']!=day:raise ValueError('origin identity differs')
            edges=weighted_terciles(earlier);same(packet['depth_tercile_edges'],edges)
            for variant in VARIANTS:same(packet['models'][variant],fit(earlier,asset,day,variant))
            for r in (r for r in rows if r['period']==day):
                later.append(r);group=depth_group(r,edges);groups.append(group)
                for variant in VARIANTS:
                    stored=json.loads(stream.readline());total+=1
                    if {k:stored[k] for k in ('asset','start','period','variant','depth_group')}!=dict(asset=asset,start=r['start'],period=day,variant=variant,depth_group=group):raise ValueError('paired evaluation grid differs')
                    p=manual(r,packet['models'][variant]);same({k:stored[k] for k in p},p);forecasts[variant].append(p)
        if stream.readline():raise ValueError('extra predictions')
    if len(later)!=meta['unique_matched_evaluated_paths'] or len({r['start'] for r in later})!=len(later):raise ValueError('duplicate or missing evaluated path')
    for variant in VARIANTS:same(meta['pooled'][variant],summarize(later,forecasts[variant]))
    daily={}
    for day in DATES[6:]:
        ids=[i for i,r in enumerate(later) if r['period']==day]
        daily[day]={v:summarize([later[i] for i in ids],[forecasts[v][i] for i in ids]) for v in VARIANTS}
    same(meta['daily'],daily);same(meta['paired_primary'],paired_result(daily))
    same(meta['paired_activity'],paired_result(daily,'activity','activity_liquidity'))
    same(meta['paired_floor'],paired_result(daily,head='floor'))
    for name in ('weekday','weekend','low','middle','high'):
        ids=[i for i,r in enumerate(later) if (datetime.fromtimestamp(r['start']/1000,timezone.utc).weekday()>=5)==(name=='weekend')]
        if name in ('low','middle','high'):ids=[i for i,g in enumerate(groups) if g==name]
        for variant in VARIANTS:same(meta['strata'][name][variant],summarize([later[i] for i in ids],[forecasts[variant][i] for i in ids]))
    return dict(asset=asset,origins=len(DATES[6:]),trace_rows=total,unique_paths=len(later),
        coefficients_refit_from_earlier_labels=True,paired_metrics_and_bootstrap_reconstructed=True)


def audit(root):
    plan=verify_plan(root);meta=json.loads((root/'research.json').read_text())
    if meta['protocol_sha256']!=digest(root/'protocol.json'):raise ValueError('protocol differs')
    books=Path(plan['books']);manifest=book_manifest(books);rows,_,binding=load_parent(Path(plan['parent']))
    same(binding,meta['bindings'])
    if digest(books/'download-manifest.json')!=meta['book_manifest_sha256'] or digest(root/'joined.jsonl.gz')!=meta['joined_sha256'] or digest(root/'coverage.json')!=meta['coverage_sha256']:
        raise ValueError('source or joined bindings differ')
    maps={a:{r['start']:r for r in rows[a]} for a in ASSETS};matched={a:[] for a in ASSETS};joined_count=0;coverage=[]
    with gzip.open(root/'joined.jsonl.gz','rt') as stream:
        for day in DATES:
            part,counts=join_day(books,[p for p in manifest['files'] if p['day']==day],day)
            for asset in ASSETS:
                clean=kept=zero=0;reasons=Counter()
                for expected in part[asset]:
                    saved=json.loads(stream.readline());same(saved,expected);joined_count+=1
                    r=maps[asset][saved['start']]
                    if r['valid'] and r['adaptive_features'] is not None:
                        clean+=1;zero+=r['move']==0
                        if saved['liquidity'] is not None:
                            if not saved['liquidity']['received_at_ms']<r['start']:raise ValueError('post-entry book leaked')
                            matched[asset].append(dict(r,liquidity=saved['liquidity']));kept+=1
                        else:reasons[saved['join_reason']]+=1
                coverage.append(dict(asset=asset,period=day,clean_oracle_paths=clean,matched_paths=kept,
                    match_rate=kept/clean if clean else None,all_clean_zero_motion=zero,
                    unavailable_book_reasons=dict(reasons),raw_counts=counts))
        if stream.readline():raise ValueError('extra joined rows')
    same(json.loads((root/'coverage.json').read_text()),coverage);reports=[]
    for asset in ASSETS:
        if digest(root/asset/'research.json')!=meta['research_sha256'][asset]:raise ValueError('asset report binding differs')
        reports.append(audit_asset(asset,matched[asset],root/asset))
        same(meta['paired_primary'][asset],json.loads((root/asset/'research.json').read_text())['paired_primary'])
    result=dict(passed=True,research_sha256=digest(root/'research.json'),joined_grid_rows=joined_count,
        book_payloads_verified=len(manifest['files']),assets=reports,auditor_sha256=digest(Path(__file__)))
    dump(root/'audit.json',result);return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--research',type=Path,required=True)
    print(json.dumps(audit(parser.parse_args().research),indent=2))
