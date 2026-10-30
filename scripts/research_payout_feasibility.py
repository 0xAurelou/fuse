#!/usr/bin/env python3
"""Necessary payout/availability bounds on retained development oracle paths.

No live trial receipts, candidate fitting, quote changes or production verdict.
"""
import argparse
from fractions import Fraction
import json
from pathlib import Path
import shutil

from capture_dataset import file_hash
from investigate_capture import write_csv
from payout_feasibility import retention_bound,target,batch_return,maximum_liability,rare_event_diagnostic
from research_bursty_optimizer import dump
from research_frozen_market import DEPENDENCIES
from temporal_oracle_data import load,late_days,origin

ROOT=Path(__file__).resolve().parent.parent
SOURCES=tuple(dict.fromkeys(tuple('scripts/'+n for n in DEPENDENCIES)+(
    'scripts/payout_feasibility.py','scripts/test_payout_feasibility.py','scripts/research_payout_feasibility.py',
    'engine/internal/engine/accounting.go','engine/internal/engine/pricing.go','src/LPVault.sol',
    'docs/BARRIER_PRICING.md','docs/GO_ENGINE_SPECIFICATION.md')))


def run(dataset,late_raw,policy,output):
    if output.exists():raise ValueError('preserve old experiments; choose a new output')
    selected=json.loads(policy.read_text())
    if selected['product']!='single-stage-v1' or selected['duration_ms']!=30000:
        raise ValueError('single thirty-second total-payout product required')
    multipliers=selected['multipliers'];edge=selected['model']['dnt']['house_edge_bps']
    output.mkdir();(output/'source').mkdir()
    protocol=dict(dataset=str(dataset.resolve()),dataset_sha256=file_hash(dataset/'dataset.json'),
        late_raw=str(late_raw.resolve()),late_manifest_sha256=file_hash(late_raw/'download-manifest.json'),
        policy=str(policy.resolve()),policy_sha256=file_hash(policy),multipliers=multipliers,house_edge_bps=edge,
        source_sha256={n:file_hash(ROOT/n) for n in SOURCES},
        rule='Canonical monthly date uses full raw once when available, otherwise normalized; no cross-format pooling. All outcomes are inspected development data. No live trial inputs.',
        population='Healthy evaluable thirty-second paths with clean pre-entry adaptive history. Keep original grid and healthy counts. Empty/small groups are descriptive. No causal quote policy is implemented.',
        bound='Zero oracle movement is a mandatory survivor for every positive corridor. Grant perfect refusal of flat paths first and losses on all others. This gives a necessary optimistic maximum retained fraction, not achievable causal pricing or estimated probability.',
        targets='Configured gross-margin target, zero-cost break-even, and illustrative 1%/5%-of-stake allocated-cost break-even. Nonnegative reserve fees can only worsen the zero-fee bound.',
        availability='Provisional 85% overall and 50% populated frozen screens; regime comparisons use 85% only as an illustrative reference. Thresholds are not approved product constraints.',
        economics_validated=False,capture_changed=False,live_receipts_read=False,production_approved=False)
    dump(output/'protocol.json',protocol)
    for name in SOURCES:
        path=output/'source'/name;path.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(ROOT/name,path)
    shutil.copyfile(policy,output/'source-policy.json')
    normalized,raw,metadata=load(dataset);later,binding=late_days(late_raw);raw.update(later)
    cases=[];profiles=[]
    for day in metadata['dates']:
        rows=raw.get(day,[r for r in normalized if r['period']==day]);source='raw' if day in raw else 'normalized'
        left=origin(day)
        for hour,hours in ((0,24),(0,8),(8,8),(16,8)):
            part=[r for r in rows if left+hour*3600000<=r['start']<left+(hour+hours)*3600000]
            clean=[r for r in part if r['valid'] and r['adaptive_features'] is not None]
            groups=[('all','all',clean),('activity','frozen',[r for r in clean if r['activity_state']=='frozen'])]
            groups.extend(('regime',regime,[r for r in clean if r['market_regime']==regime]) for regime in ('range','mixed','pump','dump'))
            profiles.append(dict(period=day,source=source,hour=hour,hours=hours,grid_windows=len(part),
                healthy_outcomes=sum(r['valid'] for r in part),clean_outcomes=len(clean)))
            for axis,group,values in groups:
                n=len(values);flat=sum(r['move']==0 for r in values);minimum=Fraction(1,2) if group=='frozen' else Fraction(17,20)
                for multiplier in multipliers:
                    targets=[('configured_gross_target',target(multiplier,edge)),
                        ('zero_cost_break_even',target(multiplier,0)),
                        ('assumed_1pct_cost_break_even',target(multiplier,0,100)),
                        ('assumed_5pct_cost_break_even',target(multiplier,0,500))]
                    for name,q in targets:
                        bound=retention_bound(n,flat,q);kept=bound['maximum_kept']
                        cases.append(dict(period=day,source=source,hour=hour,hours=hours,axis=axis,group=group,
                            clean_outcomes=n,zero_motion_survivors=flat,zero_motion_fraction=flat/n if n else None,
                            multiplier=multiplier,target_kind=name,survival_cap=float(q),
                            target_fraction=str(q),**bound,minimum_reference_availability=float(minimum),
                            reference_availability_compatible=(Fraction(kept,n)>=minimum) if n else None,
                            populated=n>=20,
                            zero_fee_gross_return_upper_per_stake=float(1-multiplier*Fraction(flat,n)) if n else None))
    rare=[dict(multiplier=m,target=float(target(m,edge)),**rare_event_diagnostic(target(m,edge))) for m in multipliers]
    illustrations=[]
    for m in multipliers:
        for cost in (0,100,500):
            for fee in (0,3500):
                ret=batch_return(Fraction(12,25),m,cost,fee)
                illustrations.append(dict(survival=.48,multiplier=m,cost_bps_assumed=cost,
                    positive_batch_profit_allocation_bps_assumed=fee,**{k:float(v) for k,v in ret.items()}))
    liabilities=[dict(stake_usdc=10,multiplier=m,tickets=k,funded_stake_usdc=10,
        maximum_lp_liability_usdc=maximum_liability(10_000_000,m,k)/1e6) for m in multipliers for k in (1,10,100)]
    for name,digest in protocol['source_sha256'].items():
        if file_hash(ROOT/name)!=digest:raise ValueError('source changed during experiment: '+name)
    result=dict(protocol,later_binding=binding,raw_dates=sorted(raw),profiles=profiles,cases=cases,
        rare_event_illustrations=rare,fortyeight_percent_batch_illustrations=illustrations,
        correlated_fully_funded_liability_illustrations=liabilities,
        fee_scope='Flat 0%/35% positive-batch-profit allocation is illustrative, not LPVault high-water/capital/path-dependent execution. Costs are stated scenarios, not measured costs or fee schedules.',
        rare_scope='Independent Bernoulli illustrations ignore serial dependence, censorship and quote refusal; one observed survivor is not probability calibration. Actual eight-hour usable count will be lower than or equal to 960.',
        no_pricing_formula_selected=True,no_forward_survival_claim=True)
    dump(output/'research.json',result)
    for name,values in (('cases',cases),('profiles',profiles),('rare_events',rare),('batch_illustrations',illustrations),('liabilities',liabilities)):
        write_csv(output/(name+'.csv'),values,list(values[0]))
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--dataset',type=Path,required=True)
    p.add_argument('--late-raw',type=Path,required=True);p.add_argument('--policy',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    r=run(a.dataset,a.late_raw,a.policy,a.output)
    print(json.dumps(dict(dates=len(r['profiles'])//4,raw_dates=len(r['raw_dates']),cases=len(r['cases']),economics_validated=False),indent=2))
