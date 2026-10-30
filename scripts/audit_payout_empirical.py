#!/usr/bin/env python3
"""Audit OOF calibration, empirical training CDFs and frozen policy replay."""
import argparse
from bisect import bisect_right
from collections import Counter
from datetime import datetime,timezone
import csv
import gzip
import json
import math
from pathlib import Path

import numpy as np

from audit_payout_risk import close, manual_positive, manual_risk, width_needed
from payout_empirical import CONTROLS, EDGES
from research_payout_empirical import inputs, select
from research_payout_risk import MULTIPLIERS, digest, dump, grouped_metrics


def group_key(r,family):
    if family=='activity':return r['activity_state']
    a=r['activity_features']
    idle=sum(a['idle_ms']>=v for v in (1500,3000,10000,30000))
    count=sum(a['changes_30']>=v for v in (1,4,11))
    return f'idle{idle}:changes{count}'


def verify_distribution(saved,rows,method):
    rows=[r for r in rows if width_needed(r)>1]
    counts=Counter(r['period'] for r in rows)
    if saved['n']!=len(rows) or saved['dates']!=sorted(counts):raise ValueError('CDF support differs')
    expected=[]
    for r in rows:
        f=r['adaptive_features'];scale=max(1.,f['vol_300_ppm'] if method=='slow' else (f['vol_60_ppm']+f['vol_300_ppm'])/2)
        expected.append((width_needed(r)/scale,1/counts[r['period']]/len(counts)))
    expected.sort()
    if len(saved['value'])!=len(expected) or len(saved['weight'])!=len(expected):raise ValueError('CDF drops or duplicates paths')
    if expected and (not np.allclose(saved['value'],[p[0] for p in expected],rtol=1e-12,atol=1e-12)
                     or not np.allclose(saved['weight'],[p[1] for p in expected],rtol=1e-10,atol=1e-12)):
        raise ValueError('CDF values/date weights differ')


def verify_calibrator(calibrator,records):
    prior=calibrator['prior']
    for field,label in (('p0','zero'),('floor','minimum')):
        fitted=[]
        for i,bin in enumerate(calibrator['heads'][field]):
            part=[p for p in records if min(len(EDGES)-2,bisect_right(EDGES,p[field])-1)==i]
            counts=Counter(p['period'] for p in part)
            if bin['n']!=len(part) or bin['dates']!=sorted(counts):raise ValueError('calibration support differs')
            supported=len(part)>=200 and len(counts)>=3
            if supported!=bin['supported']:raise ValueError('calibration support screen differs')
            if part:
                raw=sum(p[field]/counts[p['period']] for p in part)/len(counts)
                observed=sum(p[label]/counts[p['period']] for p in part)/len(counts)
                value=(len(part)*observed+prior*raw+.5)/(len(part)+prior+1)
                close(bin['raw_mean'],raw);close(bin['observed'],observed);close(bin['unpooled_probability'],value)
            else:value=None
            if supported:fitted.append([i,value,len(part)+prior+1])
        # Independent weighted monotonic pooling across supported score bins.
        blocks=[]
        for index,value,mass in fitted:
            blocks.append(([index],value*mass,mass))
            while len(blocks)>1 and blocks[-2][1]/blocks[-2][2]>blocks[-1][1]/blocks[-1][2]:
                b=blocks.pop();a=blocks.pop();blocks.append((a[0]+b[0],a[1]+b[1],a[2]+b[2]))
        for indexes,total,mass in blocks:
            for index in indexes:close(calibrator['heads'][field][index]['probability'],total/mass)


def calibrate(raw,model):
    if raw[0] is None:return dict(p0=None,floor=None,calibrated0=False,calibrated_floor=False)
    values=[];flags=[]
    for field,value in zip(('p0','floor'),raw):
        leaf=model['heads'][field][min(len(EDGES)-2,bisect_right(EDGES,value)-1)]
        values.append(leaf['probability'] if leaf['supported'] else value);flags.append(leaf['supported'])
    return dict(p0=values[0],floor=max(values),calibrated0=flags[0],calibrated_floor=flags[1])


def independent_entry(row,multiplier,policy,raw,calibrators,parent,positive,movement,cache):
    name=policy['name'];q=.95/multiplier
    prior=policy.get('prior',32 if name=='calibrated32_parent' else 128 if name=='calibrated128_parent' else None)
    p=calibrate(raw,calibrators[str(prior)]) if prior else dict(p0=raw[0],floor=raw[1],calibrated0=False,calibrated_floor=False)
    reasons=[];positive_q=tail_mass=tail_supported=child_supported=None
    if policy['kind']=='empirical':
        if p['floor'] is None:
            width=None;reasons=['missing_history'];tail_mass=0.;tail_supported=child_supported=False
        else:
            family,method=policy['family'],policy['anchor'];key=group_key(row,family)
            token=family,method,key
            if token not in cache:
                data=movement['anchors'][method];g=data['global_distribution'];child=data['families'][family].get(key)
                local=child is not None and child['n']>=200 and len(child['dates'])>=3
                alpha=child['n']/(child['n']+200) if local else 0.
                values=np.asarray(g['value']+(child['value'] if alpha else []))
                weights=np.asarray([(1-alpha)*v for v in g['weight']]+([alpha*v for v in child['weight']] if alpha else []))
                ids=np.argsort(values,kind='stable');cdf=np.cumsum(weights[ids]);cdf/=cdf[-1]
                cache[token]=values[ids],cdf,g['n'],local
            values,cdf,n,child_supported=cache[token]
            positive_q=(q*policy['level']-p['floor'])/(1-p['floor']);tail_mass=n*max(0,positive_q)
            tail_supported=0<positive_q<1 and tail_mass>=20
            f=row['adaptive_features'];scale=max(1.,f['vol_300_ppm'] if method=='slow' else .5*(f['vol_60_ppm']+f['vol_300_ppm']))
            width=1 if positive_q<=0 else max(2,min(50000,math.ceil(scale*float(values[min(len(values)-1,int(np.searchsorted(cdf,positive_q)))]))))
            if p['floor']>policy['gate']*policy['level']*q:reasons.append('predicted_minimum_width_risk')
            if not tail_supported:reasons.append('insufficient_positive_tail_support')
            if row['entry'] is not None and row['entry']*width//1000000<=0:reasons.append('unrepresentable_barrier')
    else:
        old=manual_positive(row,dict(floor=raw[1]),positive,q)
        width=old[0] if name=='v1_conditional_gate100' else parent
        if width is None:reasons.append('missing_history')
        else:
            if name in ('v1_parent_gate100','v1_conditional_gate100','calibrated32_parent','calibrated128_parent') and p['floor']>q:
                reasons.append('predicted_minimum_width_risk')
            if name=='v1_conditional_gate100' and not old[3]:reasons.append('insufficient_positive_tail_support')
            limit={'idle3_parent':3000,'idle10_parent':10000,'idle30_parent':30000}.get(name)
            if limit is not None and row['activity_features']['idle_ms']>=limit:reasons.append('preentry_idle_control')
            if name=='changes3_parent' and row['activity_features']['changes_30']<3:reasons.append('preentry_changes_control')
            if row['entry'] is not None and row['entry']*width//1000000<=0:reasons.append('unrepresentable_barrier')
    shadow=row['move']<row['entry']*width//1000000 if row['valid'] and width is not None else None
    return dict(width=width,offered=not reasons,reason=';'.join(reasons),positive_q=positive_q,tail_mass=tail_mass,
                tail_supported=tail_supported,child_supported=child_supported,**p,shadow=shadow,survived=shadow if not reasons else None)


def audit_asset(asset,rows,baseline,directory):
    meta=json.loads((directory/'research.json').read_text())
    for name,sha in meta['artifact_sha256'].items():
        if digest(directory/name)!=sha:raise ValueError('asset artifact differs')
    packet=json.loads((directory/'models.json').read_text());choices=json.loads((directory/'selection.json').read_text())
    rowmap={r['start']:r for r in rows};train=[r for r in rows if r['split']=='train' and r['valid'] and r['adaptive_features'] is not None]
    if packet['asset']!=asset or any(r['asset']!=asset or r['period']>='2026-01-01' for r in train):raise ValueError('training contamination')
    dates=sorted({r['period'] for r in train})
    with gzip.open(directory/'oof.jsonl.gz','rt') as stream:records=[json.loads(line) for line in stream]
    if len({p['start'] for p in records})!=len(records):raise ValueError('duplicate OOF outcomes')
    if {p['start'] for p in records}!={r['start'] for r in train if r['period'] in dates[6:14]}:
        raise ValueError('OOF calibration population differs')
    for prefix,model in packet['fold_models'].items():
        cutoff=int(datetime.fromisoformat(model['cutoff']).replace(tzinfo=timezone.utc).timestamp()*1000)
        if model['training_dates']!=dates[:int(prefix)]:raise ValueError('OOF training prefix differs')
        if any(x['expiry']+30000>=cutoff for x in rows if x['period'] in model['training_dates']):
            raise ValueError('OOF maturity crosses cutoff')
    for p in records:
        r=rowmap[p['start']];model=packet['fold_models'][str(p['fold'])]
        if r['split']!='train' or r['period'] in model['training_dates'] or model['training_dates']!=dates[:p['fold']]:
            raise ValueError('OOF own/future labels or training dates differ')
        if any(day>=r['period'] for day in model['training_dates']):raise ValueError('OOF dates cross cutoff')
        p0,pf=manual_risk(r,model);close(p['p0'],p0);close(p['floor'],pf)
        if p['zero']!=(r['move']==0) or p['minimum']!=(width_needed(r)<=1):raise ValueError('OOF labels differ')
    for calibrator in packet['calibrators'].values():verify_calibrator(calibrator,records)
    for method,data in packet['movement']['anchors'].items():
        verify_distribution(data['global_distribution'],train,method)
        for family,leaves in data['families'].items():
            expected={}
            for r in train:expected.setdefault(group_key(r,family),[]).append(r)
            if set(expected)!=set(leaves):raise ValueError('movement groups differ')
            for key,part in expected.items():verify_distribution(leaves[key],part,method)
    if select(rows,baseline,packet)!=choices:raise ValueError('validation policy selection differs')
    later=[r for r in rows if r['split']!='train'];raw=[manual_risk(r,packet['risk']) for r in later]
    metrics=[];total=0;cache={}
    with gzip.open(directory/'predictions.jsonl.gz','rt') as stream:
        for multiplier in MULTIPLIERS:
            variants=[(n,dict(name=n,kind='control')) for n in CONTROLS]+[('selected_policy',choices[str(multiplier)]['policy'])]
            for variant,policy in variants:
                predicted=[]
                for i,r in enumerate(later):
                    saved=json.loads(stream.readline());total+=1
                    if (saved['asset'],saved['start'],saved['multiplier'],saved['variant'],saved['policy'])!=(asset,r['start'],multiplier,variant,policy['name']):
                        raise ValueError('trace grid or selection differs')
                    actual=independent_entry(r,multiplier,policy,raw[i],packet['calibrators'],baseline[multiplier][r['start']],packet['v1_positive'],packet['movement'],cache)
                    for field,value in actual.items():
                        if field in ('p0','floor','positive_q','tail_mass'):close(saved[field],value)
                        elif saved[field]!=value:raise ValueError('entry decision differs: '+field)
                    close(saved['raw_p0'],raw[i][0]);close(saved['raw_floor'],raw[i][1])
                    predicted.append(actual)
                metrics.extend(grouped_metrics(asset,later,predicted,multiplier,variant))
        if stream.readline():raise ValueError('extra traces')
    with (directory/'metrics.csv').open() as stream:
        saved=list(csv.DictReader(stream))
    if len(saved)!=len(metrics):raise ValueError('metric row count differs')
    for actual,stored in zip(metrics,saved):
        for field,value in actual.items():
            if isinstance(value,bool):
                if stored[field]!=str(value):raise ValueError('metric evidence flag differs')
            elif value is None or isinstance(value,(float,int)):
                close(float(stored[field]) if stored[field] else None,value)
            elif stored[field]!=value:raise ValueError('metric identity differs')
    return dict(asset=asset,trace_rows=total,oof_rows=len(records),cdf_training_paths=len(train),
                selection_reconstructed=True,calibration_reconstructed=True,all_positive_cdf_paths_verified=True)


def audit(root):
    meta=json.loads((root/'research.json').read_text())
    if digest(root/'protocol.json')!=meta['protocol_sha256']:raise ValueError('protocol differs')
    for name,sha in meta['protocol']['source_sha256'].items():
        if digest(root/'source'/name)!=sha:raise ValueError('frozen source differs')
    rows,baseline,templates,binding=inputs(Path(meta['protocol']['parent']),Path(meta['protocol']['preceding']))
    if binding!=meta['bindings']:raise ValueError('source bindings differ')
    reports=[]
    for asset in ('ETH','HYPE'):
        if digest(root/asset/'research.json')!=meta['research_sha256'][asset]:raise ValueError('asset binding differs')
        packet=json.loads((root/asset/'models.json').read_text());old=templates[asset]
        if packet['risk']!=old['candidates'][old['selected']] or packet['v1_positive']!=old['positive']:
            raise ValueError('preceding model template differs')
        reports.append(audit_asset(asset,rows[asset],baseline[asset],root/asset))
    result=dict(passed=True,research_sha256=digest(root/'research.json'),assets=reports,auditor_sha256=digest(Path(__file__)))
    dump(root/'audit.json',result)
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--research',type=Path,required=True)
    print(json.dumps(audit(parser.parse_args().research),indent=2))
