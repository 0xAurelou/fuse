#!/usr/bin/env python3
"""Refit earlier-only coefficients and independently replay every exported quote."""
import argparse
import gzip
import json
from pathlib import Path

from audit_payout_empirical import (independent_entry, verify_calibrator,
                                   verify_distribution)
from audit_payout_risk import close, manual_risk
from payout_risk import fit_risk, weekend
from payout_walkforward import (FAMILIES, SPEC, VARIANTS, floor_summary, metrics,
                               reference, research_screen, schedule)
from research_payout_risk import ASSETS, MULTIPLIERS, digest, dump, load_parent
from research_payout_walkforward import verify_sources


def same(a,b):
    if isinstance(a,dict):
        if set(a)!=set(b):raise ValueError('audit object keys differ')
        for k in a:same(a[k],b[k])
    elif isinstance(a,(list,tuple)):
        if len(a)!=len(b):raise ValueError('audit list length differs')
        for x,y in zip(a,b):same(x,y)
    elif a is None or isinstance(a,(int,float)) and not isinstance(a,bool):close(a,b)
    elif a!=b:raise ValueError(f'audit value differs: {a} versus {b}')


def independent_quote(row, multiplier, variant, raw, packet, cache):
    if variant=='minimum_width_floor':
        width=1 if row['adaptive_features'] is not None else None
        reasons=['missing_history'] if width is None else []
        if width is not None and row['entry']*width//1000000<=0:reasons.append('unrepresentable_barrier')
        shadow=bool(row['move']<row['entry']*width//1000000) if row['valid'] and width is not None else None
        return dict(width=width,offered=not reasons,reason=';'.join(reasons),positive_q=None,
            tail_mass=None,tail_supported=None,child_supported=None,p0=None,floor=None,
            calibrated0=False,calibrated_floor=False,shadow=shadow,survived=shadow if not reasons else None)
    family,mode,_=variant.split('_')
    # An unsupported map is the identity, independently implementing the raw branch.
    identity=dict(heads={field:[dict(supported=False)]*6 for field in ('p0','floor')})
    calibrator=packet['calibrators'][family] if mode=='cal32' else identity
    policy=dict(name=variant,kind='empirical',prior=32,family='activity',anchor='slow',level=1.,gate=1.)
    return independent_entry(row,multiplier,policy,raw[family],{'32':calibrator},
                             None,None,packet['movement'],cache)


def audit_asset(asset, rows, directory):
    meta=json.loads((directory/'research.json').read_text());dates=schedule(rows,asset)
    if meta['evaluated_dates']!=dates:raise ValueError('evaluation schedule differs')
    for name,sha in meta['artifact_sha256'].items():
        if digest(directory/name)!=sha:raise ValueError('artifact differs: '+name)
    if [o['period'] for o in meta['origins']]!=dates:raise ValueError('origin population differs')
    references={family:[] for family in FAMILIES};later=[]
    records={(m,v):[] for m in MULTIPLIERS for v in VARIANTS};count=0
    with gzip.open(directory/'predictions.jsonl.gz','rt') as stream:
        for origin in meta['origins']:
            day=origin['period'];path=directory/'origins'/(day+'.json.gz')
            if digest(path)!=origin['model_sha256']:raise ValueError('origin model binding differs')
            with gzip.open(path,'rt') as model_stream:packet=json.load(model_stream)
            earlier=[r for r in rows if r['period']<day]
            train=[r for r in earlier if r['valid'] and r['adaptive_features'] is not None]
            training_dates=sorted({r['period'] for r in train})
            if packet['asset']!=asset or packet['cutoff']!=day or origin['training_dates']!=training_dates:
                raise ValueError('asset/origin training contamination')
            if packet['movement']['asset']!=asset or packet['movement']['cutoff']!=day or packet['movement']['training_dates']!=training_dates:
                raise ValueError('movement origin differs')
            for family in FAMILIES:
                # Refit verifies that every coefficient/normalizer came only from earlier labels.
                fitted=fit_risk(earlier,asset,day,family,.003)
                same(packet['risk'][family],fitted)
                if packet['calibration_counts'][family]!=len(references[family]):raise ValueError('reference count differs')
                if origin['calibration_counts']!=packet['calibration_counts']:raise ValueError('origin reference binding differs')
                cal=packet['calibrators'][family]
                if cal['prior']!=32 or cal['records']!=len(references[family]) or cal['periods']!=sorted({p['period'] for p in references[family]}):
                    raise ValueError('calibration origin differs')
                verify_calibrator(cal,references[family])
            data=packet['movement']['anchors']['slow']
            verify_distribution(data['global_distribution'],train,'slow')
            groups={}
            for r in train:groups.setdefault(r['activity_state'],[]).append(r)
            if set(groups)!=set(data['families']['activity']):raise ValueError('movement groups differ')
            for name,part in groups.items():verify_distribution(data['families']['activity'][name],part,'slow')
            cache={};pending={family:[] for family in FAMILIES}
            for r in (r for r in rows if r['period']==day):
                later.append(r);raw={f:manual_risk(r,packet['risk'][f]) for f in FAMILIES}
                for m in MULTIPLIERS:
                    for variant in VARIANTS:
                        line=stream.readline()
                        if not line:raise ValueError('missing trace')
                        saved=json.loads(line);count+=1
                        identity={k:saved.pop(k) for k in ('asset','period','start','multiplier','variant')}
                        if identity!=dict(asset=asset,period=day,start=r['start'],multiplier=m,variant=variant):
                            raise ValueError('duplicated, missing or reordered evaluation entry')
                        actual=independent_quote(r,m,variant,raw,packet,cache)
                        same(saved,actual);records[m,variant].append(actual)
                if r['valid'] and r['adaptive_features'] is not None:
                    for family in FAMILIES:pending[family].append(reference(r,raw[family],family))
            for family in FAMILIES:references[family].extend(pending[family])
        if stream.readline():raise ValueError('extra traces')
    if len(later)!=meta['unique_evaluated_entries'] or len({r['start'] for r in later})!=len(later):
        raise ValueError('unique evaluated population differs')
    with gzip.open(directory/'calibration-references.json.gz','rt') as stream:same(json.load(stream),references)
    for m in MULTIPLIERS:
        result=meta['results'][str(m)];qualifying=[]
        same(result['floor'],floor_summary(later,m))
        same(result['daily_floor'],[dict(period=day,**floor_summary([r for r in later if r['period']==day],m)) for day in dates])
        for variant in VARIANTS:
            values=records[m,variant];actual=metrics(later,values,m)
            actual['screen']=research_screen(actual,m,variant)
            actual['calendar_groups']={}
            for group in ('weekday','weekend'):
                pairs=[(r,p) for r,p in zip(later,values) if weekend(r)==(group=='weekend')]
                actual['calendar_groups'][group]=metrics([r for r,p in pairs],[p for r,p in pairs],m)
            same(result['variants'][variant],actual)
            if actual['screen']['qualifies']:qualifying.append(variant)
        if result['qualifying_variants']!=qualifying:raise ValueError('screen differs')
    return dict(asset=asset,origins=len(dates),unique_evaluated_entries=len(later),trace_rows=count,
                coefficients_refit_from_earlier_only=True,calibration_population_reconstructed=True,
                all_positive_training_points_verified=True,quote_replay_and_metrics_verified=True)


def audit(root):
    protocol=verify_sources(root);meta=json.loads((root/'research.json').read_text())
    if digest(root/'protocol.json')!=meta['protocol_sha256']:raise ValueError('protocol differs')
    same(meta['protocol'],protocol)
    rows,_,binding=load_parent(Path(protocol['parent']))
    same(binding,meta['bindings']);reports=[]
    for asset in ASSETS:
        if digest(root/asset/'research.json')!=meta['research_sha256'][asset]:raise ValueError('asset report differs')
        reports.append(audit_asset(asset,rows[asset],root/asset))
    result=dict(passed=True,research_sha256=digest(root/'research.json'),assets=reports,
                auditor_sha256=digest(Path(__file__)))
    dump(root/'audit.json',result);return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--research',type=Path,required=True)
    print(json.dumps(audit(parser.parse_args().research),indent=2))
