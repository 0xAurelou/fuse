#!/usr/bin/env python3
"""Explicit validation-only research eligibility; no least-bad acceptance."""
import argparse
import json
from pathlib import Path
import shutil

from research_payout_risk import digest,dump

CRITERIA=dict(minimum_daily_availability=.85,minimum_target_expected_wins=20,
              relative_survival_band=[.75,1.25],require_nonnegative_zero_cost_gross=True,
              require_nonempty_each_date=True,
              role='Necessary descriptive research screens only; not production limits, net economics, statistical confidence or promotion',
              selection='Among qualifying validation candidates, prefer worst-day availability, pooled availability, target closeness, then declared candidate order',
              input='Earlier selection summaries only. Later diagnostic outcomes cannot affect eligibility or ranking.')


def assess(candidate,multiplier):
    q=.95/multiplier
    reasons=[]
    if not candidate['offered'] or any(d['offered']==0 for d in candidate['daily']):reasons.append('empty_quote_set')
    if candidate['minimum_daily_availability']<.85:reasons.append('insufficient_quote_availability')
    p=candidate['pooled_survival']
    if p is None or p/q<.75 or p/q>1.25:reasons.append('survival_outside_reference_band')
    if p is None or p>1/multiplier:reasons.append('negative_zero_cost_gross')
    if candidate['offered']*q<20:reasons.append('insufficient_rare_event_evidence')
    return dict(policy=candidate['policy'],eligible=not reasons,reasons=reasons,
                validation_offered=candidate['offered'],validation_eligible=candidate['eligible'],
                validation_survival=p,target=q,target_expected_wins=candidate['offered']*q,
                minimum_daily_availability=candidate['minimum_daily_availability'],
                pooled_availability=candidate['availability'],index=candidate['index'])


def screen(selection,multiplier):
    records=[assess(c,multiplier) for c in selection['ranking']]
    eligible=[c for c in records if c['eligible']]
    eligible.sort(key=lambda r:(-r['minimum_daily_availability'],-r['pooled_availability'],
                                abs(r['validation_survival']/r['target']-1),r['index']))
    return dict(accepted_research_candidate=eligible[0] if eligible else None,
                candidates=len(records),qualifying=len(eligible),assessments=records,
                least_bad_diagnostic=selection['policy'],no_production_promotion=True)


def declare(study,output):
    if output.exists():raise ValueError('preserve earlier screens; use a new directory')
    audit=json.loads((study/'audit.json').read_text())
    if not audit['passed'] or audit['research_sha256']!=digest(study/'research.json'):raise ValueError('matching completed study audit required')
    output.mkdir(parents=True);shutil.copyfile(Path(__file__),output/'screen-source.py')
    protocol=dict(criteria=CRITERIA,study=str(study.resolve()),study_sha256=digest(study/'research.json'),
                  selection_sha256={a:digest(study/a/'selection.json') for a in ('ETH','HYPE')},
                  source_sha256=digest(Path(__file__)),later_results_used=False)
    dump(output/'protocol.json',protocol)
    return protocol


def run(output):
    protocol=json.loads((output/'protocol.json').read_text());study=Path(protocol['study'])
    if digest(study/'research.json')!=protocol['study_sha256'] or digest(output/'screen-source.py')!=protocol['source_sha256'] or digest(Path(__file__))!=protocol['source_sha256']:
        raise ValueError('screen source or study differs')
    results={}
    for asset in ('ETH','HYPE'):
        path=study/asset/'selection.json'
        if digest(path)!=protocol['selection_sha256'][asset]:raise ValueError('selection summary differs')
        selection=json.loads(path.read_text())
        results[asset]={m:screen(selection[m],int(m)) for m in ('100','1000')}
    result=dict(protocol=protocol,results=results,later_results_used=False,no_live_change=True)
    dump(output/'screen.json',result)
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--study',type=Path);parser.add_argument('--output',type=Path,required=True);parser.add_argument('--declare',action='store_true')
    args=parser.parse_args();r=declare(args.study,args.output) if args.declare else run(args.output)
    print(json.dumps({'declared':args.declare,'qualifying':{a:{m:v['qualifying'] for m,v in p.items()} for a,p in r.get('results',{}).items()}},indent=2))
