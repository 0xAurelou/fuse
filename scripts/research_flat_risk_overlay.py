#!/usr/bin/env python3
"""Test the conservative overlay using fixed models from flat-aware v1."""
import argparse
import gzip
import json
from pathlib import Path
import shutil
import time

from audit_historical_liquidity import manual
from audit_payout_empirical import independent_entry
from audit_payout_walkforward import same
from flat_aware_payout import build_predictors
from flat_risk_overlay import SPEC,quote
from historical_liquidity import predict
from research_asset_corridors import source_files
from research_flat_aware_payout import (inputs as parent_inputs,evaluation_rows,manual_floor,
    selected,verify_plan as verify_parent)
from research_payout_risk import digest,dump
from screen_payout_candidates import assess
from trial_payout import MULTIPLIERS,available,metrics


def declare(parent,output):
    if output.exists():raise ValueError('Use a new overlay packet')
    verify_parent(parent);output.mkdir(parents=True);(output/'source').mkdir()
    paths=sorted(set(source_files()+[Path(__file__).resolve()]))
    for p in paths:shutil.copyfile(p,output/'source'/p.name)
    plan=dict(spec=SPEC,parent=str(parent.resolve()),parent_sha256=digest(parent/'research.json'),
        source_sha256={p.name:digest(p) for p in paths},declared_before_overlay_replay=True,
        parent_outcomes_inspected=True,live_policy_changed=False,no_promotion=True)
    dump(output/'protocol.json',plan);return plan


def verify_plan(output):
    plan=json.loads((output/'protocol.json').read_text())
    for n,s in plan['source_sha256'].items():
        if digest(output/'source'/n)!=s or digest(Path(__file__).with_name(n))!=s:raise ValueError('Overlay source changed: '+n)
    parent=Path(plan['parent'])
    if digest(parent/'research.json')!=plan['parent_sha256']:raise ValueError('Overlay parent differs')
    verify_parent(parent);return plan


def summarize(rows,records):
    results={}
    for phase in ('earlier_oof','trial'):
        results[phase]={}
        for m in MULTIPLIERS:
            groups={}
            for cohort in ('matched','all_clean'):
                groups[cohort]={}
                for group in ('overall','weekday','weekend'):
                    ids=selected(rows,phase,cohort,group)
                    groups[cohort][group]=metrics([rows[i] for i in ids],[records[m][i] for i in ids],m)
            s=groups['matched']['overall'];p=s['pooled']
            checked=assess(dict(policy={'name':SPEC['name']},index=0,daily=s['daily'],minimum_daily_availability=s['minimum_daily_availability'],
                pooled_survival=p['survival'],availability=p['availability'],offered=p['offered'],eligible=p['eligible']),m)
            groups['screen']=dict(qualifies=checked['eligible'],reasons=checked['reasons']);results[phase][str(m)]=groups
    return results


def independent_quote(r,m,packet,cache):
    supported=available(r,'calendar_liquidity');raw0=manual(r,packet['risk']) if supported else dict(p0=None,floor=None)
    raw=(raw0['p0'],raw0['floor']);guard=None
    if supported:
        empirical=manual_floor(r,packet['floor'],True);raw=(max(raw[0],empirical[0]),max(raw[1],empirical[1],raw[0],empirical[0]))
    identity=dict(heads={f:[dict(supported=False)]*6 for f in ('p0','floor')});policy=dict(name=SPEC['name'],kind='empirical',prior=32,family='activity',anchor='slow',level=1.,gate=1.)
    p=independent_entry(r,m,policy,raw,{'32':identity},None,None,packet['movement']['previous'],cache)
    old=independent_entry(r,m,policy,(raw0['p0'],raw0['floor']),{'32':identity},None,None,packet['movement']['previous'],cache)
    if not supported and r['adaptive_features'] is not None:p['reason']='missing_liquidity'
    p.update(width_ppb=p['width']*1000 if p['width'] is not None else None,barrier_delta_units=r['entry']*p['width']//1000000 if p['width'] is not None else None)
    if supported:
        a=r['activity_features']
        if a['idle_is_lower_bound'] or a['idle_ms']>=30000 or a['changes_30']==0:guard='flat_oracle_veto'
        elif m==1000 and (a['idle_ms']>=3000 or a['changes_30']<4):guard='insufficient_recent_oracle_activity'
    if guard:p.update(offered=False,survived=None,reason=';'.join(filter(None,(p['reason'],guard))))
    if p['offered'] and (not old['offered'] or p['width']>old['width']):raise ValueError('Audit conservative invariant failed')
    return dict(p,flat_guard=guard,estimated_zero_probability=raw[0],estimated_minimum_probability=raw[1],previous_offered=old['offered'],previous_width_ppm=old['width'])


def execute(output,auditing=False):
    started=time.monotonic();plan=verify_plan(output);parent=Path(plan['parent']);parent_meta=json.loads((parent/'research.json').read_text())
    # Declaration can precede the parent audit; execution requires its success.
    audit=json.loads((parent/'audit.json').read_text())
    if not audit['passed'] or audit['research_sha256']!=plan['parent_sha256']:raise ValueError('Matching parent audit required')
    earlier,rows,_,_,binding=parent_inputs(json.loads((parent/'protocol.json').read_text()));reports=[]
    if auditing:
        top=json.loads((output/'research.json').read_text())
        if digest(output/'protocol.json')!=top['protocol_sha256'] or digest(parent/'audit.json')!=top['parent_audit_sha256']:raise ValueError('Overlay provenance differs')
        same(binding,top['bindings'])
    for a in ('ETH','HYPE'):
        path=parent/a/'research.json'
        if digest(path)!=parent_meta['research_sha256'][a]:raise ValueError('Overlay input asset changed')
        meta=json.loads(path.read_text());later=evaluation_rows(earlier[a],rows[a]);directory=output/a;records={m:[] for m in MULTIPLIERS};count=0
        if not auditing:directory.mkdir()
        saved=json.loads((directory/'research.json').read_text()) if auditing else None
        if auditing and digest(directory/'predictions.jsonl.gz')!=saved['predictions_sha256']:raise ValueError('Overlay trace changed')
        with gzip.open(directory/'predictions.jsonl.gz','rt' if auditing else 'xt',compresslevel=5) as stream:
            for item in meta['origins']:
                day=item['period'];path=parent/a/'origins'/(day+'.json.gz')
                if digest(path)!=item['sha256']:raise ValueError('Overlay origin changed')
                with gzip.open(path,'rt') as models:packet=json.load(models)
                predictors=build_predictors(packet) if not auditing else None;cache={}
                for r in (r for r in later if r['period']==day):
                    base=(dict(predict(r,packet['risk']),calibrated0=False,calibrated_floor=False) if available(r,'calendar_liquidity') else dict(p0=None,floor=None,calibrated0=False,calibrated_floor=False)) if not auditing else None
                    for m in MULTIPLIERS:
                        p=independent_quote(r,m,packet,cache) if auditing else quote(r,m,packet,predictors,base);records[m].append(p);count+=1
                        trace=dict(asset=a,period=day,start=r['start'],multiplier=m,variant=SPEC['name'],**p)
                        if auditing:same(json.loads(stream.readline()),trace)
                        else:stream.write(json.dumps(trace,separators=(',',':'),allow_nan=False)+'\n')
                print(json.dumps(dict(asset=a,origin=day,auditing=auditing)),flush=True)
            if auditing and stream.readline():raise ValueError('Extra overlay decisions')
        result=dict(asset=a,results=summarize(later,records),origins=meta['origins'],decisions=count,predictions_sha256=digest(directory/'predictions.jsonl.gz'),conservative_invariant_checked=True)
        if auditing:same(saved,result)
        else:dump(directory/'research.json',result)
        reports.append(dict(asset=a,decisions=count))
    verify_plan(output)
    if auditing:
        meta=json.loads((output/'research.json').read_text())
        for a,sha in meta['research_sha256'].items():
            if digest(output/a/'research.json')!=sha:raise ValueError('Overlay report changed')
        result=dict(passed=True,research_sha256=digest(output/'research.json'),auditor_sha256=digest(Path(__file__)),assets=reports,conservative_invariant_verified=True)
        dump(output/'audit.json',result)
    else:
        result=dict(protocol_sha256=digest(output/'protocol.json'),parent_audit_sha256=digest(parent/'audit.json'),bindings=binding,
            research_sha256={a:digest(output/a/'research.json') for a in ('ETH','HYPE')},elapsed_seconds=time.monotonic()-started,live_policy_changed=False,no_promotion=True)
        dump(output/'research.json',result)
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--parent',type=Path);parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--declare',action='store_true');parser.add_argument('--audit',action='store_true');a=parser.parse_args()
    r=declare(a.parent,a.output) if a.declare else execute(a.output,a.audit)
    print(json.dumps(dict(declared=a.declare,audited=a.audit,passed=r.get('passed'))))
