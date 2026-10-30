"""Compare fixed formulas under existing and expanded raw training coverage."""
import csv
import json
import math
from pathlib import Path
from statistics import mean

import argparse
p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True)
root=p.parse_args().output
r=json.loads((root/'research.json').read_text())
def panel(row):
    if row['source'] in ('raw','raw_control'):return 'original_raw'
    if row['source']=='raw_extended':return 'canonical_raw'
    if row['source']=='raw_matched':return 'shifted_raw'
    if row['source']=='normalized':return 'normalized_'+row['split']
    return row['source']
bycase={(x['candidate'],x['policy'],x['case_id'],x['activity']):x for x in r['cases']}
groups={}
for x in r['cases']:
    source,method,gate=x['candidate'].split(':');base=bycase[(source+':'+method+':unchanged',x['policy'],x['case_id'],x['activity'])]
    for key in ('eligible_outcomes','pre_entry_predictions','grid_windows','shadow_survival','full_window_pinball_ppm'):
        assert x[key]==base[key],('admission changed reference evidence',key)
    assert x['windows']<=base['windows']
    if x['activity'] in ('active','sparse','frozen'):
        original=bycase[('existing:retained_pool:unchanged',x['policy'],x['case_id'],x['activity'])]
        for key in ('windows','survived','mean_width_ppm','full_window_pinball_ppm','offered_pre_entry_decisions'):
            assert x[key]==original[key],('non-bursty changed',key)
    key=(x['candidate'],x['policy'],panel(x),x['mode'],x['activity']);groups.setdefault(key,[]).append(x)
aggregates=[]
for (candidate,policy,part,mode,activity),values in groups.items():
    n=sum(x['windows'] for x in values);eligible=sum(x['eligible_outcomes'] for x in values)
    relevant=[x for x in values if x['eligible_outcomes']>=20];offered=[x for x in values if x['windows']>=20]
    decisions=sum(x['pre_entry_predictions'] for x in values);grid=sum(x['grid_windows'] for x in values)
    issued=sum(x['offered_pre_entry_decisions'] for x in values)
    aggregates.append(dict(candidate=candidate,policy=policy,panel=part,mode=mode,activity=activity,cases=len(values),
        populated=len(relevant),offered_populated=len(offered),passes=sum(abs(x['error_pp'])<=5 for x in offered),
        too_small=sum(x['windows']<20 for x in relevant),zero_quotes=sum(not x['windows'] for x in relevant),
        eligible=eligible,quoted=n,availability=n/eligible if eligible else None,
        survival=sum(x['survived'] for x in values)/n if n else None,
        full_survival=sum(x['shadow_survival']*x['eligible_outcomes'] for x in values if x['eligible_outcomes'])/eligible if eligible else None,
        full_loss=sum(x['full_window_pinball_ppm']*x['eligible_outcomes'] for x in values if x['eligible_outcomes'])/eligible if eligible else None,
        offered_loss=sum(x['pinball_ppm']*x['windows'] for x in values if x['windows'])/n if n else None,
        minimum_availability=min((x['eligible_quote_fraction'] for x in values if x['eligible_outcomes']),default=None),
        mean_case_error=mean(abs(x['error_pp']) for x in offered) if offered else None,
        pre_entry_predictions=decisions,offered_decisions=issued,grid=grid,
        pre_entry_availability=issued/decisions if decisions else None,grid_availability=issued/grid if grid else None))
focus=[x for x in r['phases'] if x['policy']=='previous_floor_53' and
       (x['source']=='raw_matched' or (x['source']=='raw' and x['hour']==8))]
riskgroups={}
for x in r['risk_report']:
    k=(x['source_model'],panel(x),x['mode'],x['activity'],x['phase'],x['risk_model']);riskgroups.setdefault(k,[]).append(x)
risks=[]
for (source_model,part,mode,activity,phase,model),values in riskgroups.items():
    n=sum(x['windows'] for x in values)
    if n:
        risks.append(dict(source_model=source_model,panel=part,mode=mode,activity=activity,phase=phase,risk_model=model,windows=n,
            **{k:sum(x[k]*x['windows'] for x in values if x['windows'])/n for k in ('predicted','observed','brier','log_loss')},
            over53=sum(x['over53'] for x in values)))
bound=[]
for mode in ('restart','continuous'):
    c=next(x for x in r['cases'] if x['source']=='raw' and x['hour']==8 and x['activity']=='bursty'
           and x['mode']==mode and x['candidate']=='existing:retained_pool:unchanged' and x['policy']=='previous_floor_53')
    p=next(x for x in focus if x['source']=='raw' and x['hour']==8 and x['mode']==mode
           and x['candidate']=='existing:retained_pool:unchanged' and x['phase']=='first12')
    n=p['eligible_outcomes'];floors=round(n*p['minimum_width_survival']);allowed=c['windows']-math.ceil(.9*c['windows'])
    drop=min(allowed,floors,n-1)
    bound.append(dict(mode=mode,case_paths=c['windows'],startup_paths=n,minimum_width_survivors=floors,
        maximum_refusals_at90pct=allowed,best_possible_startup_survival=(floors-drop)/(n-drop),
        constraint_applies_to='finite observed subset, not a population probability'))
comparison=dict(aggregates=aggregates,focus_phases=focus,risk_calibration=risks,feasibility_bound=bound,
    checks=dict(reference_and_grid_denominators_fixed=True,non_bursty_pricing_and_admission_fixed=True,
        pricing_full_reference_loss_invariant_under_admission=True))
(root/'comparison.json').write_text(json.dumps(comparison,indent=2)+'\n')
for key,values in (('aggregate-comparison',aggregates),('focus-phases',focus),('risk-calibration',risks),('feasibility-bound',bound)):
    with (root/(key+'.csv')).open('w') as f:
        w=csv.DictWriter(f,fieldnames=list(values[0]));w.writeheader();w.writerows(values)
print(json.dumps(dict(selected=r['selected'],checks=comparison['checks'],bound=bound),indent=2))
