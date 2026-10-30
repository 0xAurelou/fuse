#!/usr/bin/env python3
"""Paired volatility-open gate replay of two frozen payout formulas."""
import argparse
from collections import Counter
import gzip
import json
from math import lcm
from pathlib import Path
import shutil
import time

import numpy as np

from active_tail_payout import admissible
from audit_payout_walkforward import same
from research_active_tail import evaluation_rows,verify_plan as verify_active
from research_asset_corridors import source_files
from research_conditional_tail import verify_plan as verify_conditional
from research_flat_aware_payout import inputs as previous_inputs,selected
from research_payout_risk import digest,dump
from research_trial_liquidity import training
from screen_payout_candidates import assess
from trial_payout import metrics
from volatility_open_gate import BASES,GATES,SPEC,apply,fit


def declare(active,conditional,output):
    if output.exists():raise ValueError('Use a new volatility-gate packet')
    for p,verify in ((active,verify_active),(conditional,verify_conditional)):
        verify(p);a=json.loads((p/'audit.json').read_text())
        if not a['passed'] or a['research_sha256']!=digest(p/'research.json'):raise ValueError('Matching parent audit required')
    output.mkdir(parents=True);(output/'source').mkdir();paths=sorted(set(source_files()+[Path(__file__).resolve()]))
    for p in paths:shutil.copyfile(p,output/'source'/p.name)
    plan=dict(spec=SPEC,active=str(active.resolve()),conditional=str(conditional.resolve()),input_sha256={name:{f:digest(root/f) for f in ('research.json','audit.json')} for name,root in (('active',active),('conditional',conditional))},source_sha256={p.name:digest(p) for p in paths},declared_before_gate_replay=True,historical_outcomes_inspected=True,live_policy_changed=False,no_promotion=True)
    dump(output/'protocol.json',plan);return plan


def verify_plan(output):
    p=json.loads((output/'protocol.json').read_text())
    for n,sha in p['source_sha256'].items():
        if digest(output/'source'/n)!=sha or digest(Path(__file__).with_name(n))!=sha:raise ValueError('Volatility gate source changed: '+n)
    for name,verify in (('active',verify_active),('conditional',verify_conditional)):
        verify(Path(p[name]))
        for f,sha in p['input_sha256'][name].items():
            if digest(Path(p[name])/f)!=sha:raise ValueError('Volatility gate input changed')
    return p


def predictions(root,asset,rows,wanted):
    meta=json.loads((root/'research.json').read_text());path=root/asset/'research.json'
    if digest(path)!=meta['research_sha256'][asset]:raise ValueError('Gate parent asset differs')
    meta=json.loads(path.read_text());path=root/asset/'predictions.jsonl.gz'
    if digest(path)!=meta['predictions_sha256']:raise ValueError('Gate parent trace differs')
    result={100:[],1000:[]}
    with gzip.open(path,'rt') as stream:
        for line in stream:
            r=json.loads(line);m=r['multiplier']
            if r['variant']!=wanted[m]:continue
            i=len(result[m]);row=rows[i]
            if (r['asset'],r['period'],r['start'])!=(asset,row['period'],row['start']):raise ValueError('Gate population/order differs')
            result[m].append({k:r[k] for k in ('width','offered','shadow','survived','reason')})
    if any(len(x)!=len(rows) for x in result.values()):raise ValueError('Gate missing source decisions')
    return result


def manual_fit(rows,asset,day):
    rows=[r for r in training(rows,asset,day) if admissible(r)];dates=sorted({r['period'] for r in rows})[-3:];rows=[r for r in rows if r['period'] in dates];counts=Counter(r['period'] for r in rows);thresholds={}
    for axis,field in (('fast','vol_60_ppm'),('slow','vol_300_ppm')):
        values=np.asarray([r['adaptive_features'][field] for r in rows]);order=np.argsort(values,kind='stable');common=lcm(*counts.values());w=np.asarray([common//counts[r['period']] for r in rows],dtype=np.int64);cumulative=100*np.cumsum(w[order])
        for q in (25,50,75):thresholds[axis+str(q)]=float(values[order[min(len(rows)-1,int(np.searchsorted(cumulative,q*len(counts)*common,side='left'))) ]])
    return dict(asset=asset,cutoff=day,training_dates=dates,rows=len(rows),thresholds=thresholds)


def replay(rows,records,models,auditing=False):
    result={};count=0
    cohorts={(phase,cohort,g):selected(rows,phase,cohort,g) for phase in ('earlier_oof','trial') for cohort in ('matched','all_clean') for g in ('overall','weekday','weekend')}
    for phase in ('earlier_oof','trial'):
        result[phase]={}
        for m in (100,1000):
            result[phase][str(m)]={}
            for base in BASES:
                result[phase][str(m)][base]={}
                for gate in GATES:
                    values=[]
                    for r,p in zip(rows,records[base][m]):
                        if auditing:
                            model=models[r['period']];f=r['adaptive_features'];open_now=gate=='none' or (f is not None and f['vol_60_ppm' if gate[:4]=='fast' else 'vol_300_ppm']>=model['thresholds'][gate]);v=dict(p)
                            if p['offered'] and not open_now:v.update(offered=False,survived=None,reason='volatility_open_gate')
                        else:v=apply(r,p,gate,models[r['period']])
                        if v['offered'] and (not p['offered'] or v['width']!=p['width']):raise ValueError('Gate changed a width or added an offer')
                        values.append(v)
                    groups={}
                    for cohort in ('matched','all_clean'):
                        groups[cohort]={}
                        for g in ('overall','weekday','weekend'):
                            ids=cohorts[phase,cohort,g];groups[cohort][g]=metrics([rows[i] for i in ids],[values[i] for i in ids],m)
                    ids=cohorts[phase,'all_clean','overall'];count+=len(ids)
                    s=groups['matched']['overall'];p=s['pooled'];checked=assess(dict(policy={'name':base+':'+gate},index=GATES.index(gate),daily=s['daily'],minimum_daily_availability=s['minimum_daily_availability'],pooled_survival=p['survival'],availability=p['availability'],offered=p['offered'],eligible=p['eligible']),m)
                    groups['screen']=dict(qualifies=checked['eligible'],reasons=checked['reasons']);result[phase][str(m)][base][gate]=groups
    return result,count


def execute(output,auditing=False):
    started=time.monotonic();p=verify_plan(output);active=Path(p['active']);prior=json.loads((active/'protocol.json').read_text());earlier,rows,_,_,binding=previous_inputs(json.loads((Path(prior['parent'])/'protocol.json').read_text()));reports=[]
    for a in ('ETH','HYPE'):
        later=evaluation_rows(earlier[a],rows[a]);pool=earlier[a]+[r for r in rows[a] if r['valid'] and r['adaptive_features'] is not None and r.get('liquidity') is not None];root=output/a
        if not auditing:root.mkdir()
        models={d:(manual_fit if auditing else fit)(pool,a,d) for d in sorted({r['period'] for r in later})}
        path=root/'origins.json'
        if auditing:same(json.loads(path.read_text()),models)
        else:dump(path,models)
        records=dict(active_hybrid=predictions(active,a,later,{100:'active_empirical',1000:'active_calibrated'}),conditional_recent=predictions(Path(p['conditional']),a,later,{100:'conditional_recent',1000:'conditional_recent'}))
        result,count=replay(later,records,models,auditing);meta=dict(asset=a,results=result,origins_sha256=digest(path),gate_decisions_replayed=count,subset_and_width_invariant=True)
        if auditing:same(json.loads((root/'research.json').read_text()),meta)
        else:dump(root/'research.json',meta)
        reports.append(dict(asset=a,gate_decisions_replayed=count));print(json.dumps(dict(asset=a,auditing=auditing,decisions=count)),flush=True)
    verify_plan(output)
    if auditing:
        meta=json.loads((output/'research.json').read_text());same(meta['bindings'],binding)
        if meta['protocol_sha256']!=digest(output/'protocol.json'):raise ValueError('Gate protocol differs')
        for a,sha in meta['research_sha256'].items():
            if digest(output/a/'research.json')!=sha:raise ValueError('Gate report differs')
        result=dict(passed=True,research_sha256=digest(output/'research.json'),auditor_sha256=digest(Path(__file__)),assets=reports,earlier_only_thresholds_and_paired_gate_decisions_verified=True);dump(output/'audit.json',result)
    else:
        result=dict(protocol_sha256=digest(output/'protocol.json'),bindings=binding,research_sha256={a:digest(output/a/'research.json') for a in ('ETH','HYPE')},elapsed_seconds=time.monotonic()-started,no_promotion=True,live_policy_changed=False);dump(output/'research.json',result)
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--active',type=Path);p.add_argument('--conditional',type=Path);p.add_argument('--output',type=Path,required=True);p.add_argument('--declare',action='store_true');p.add_argument('--audit',action='store_true');a=p.parse_args();r=declare(a.active,a.conditional,a.output) if a.declare else execute(a.output,a.audit);print(json.dumps(dict(declared=a.declare,audited=a.audit,passed=r.get('passed'))))
