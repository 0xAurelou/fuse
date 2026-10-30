"""Calibrate native corridor risk on the paths a budget would actually quote."""
from collections import Counter
import math

import numpy as np

from active_tail_payout import admissible,cdf,quote as native_quote
from fetch_tardis_liquidity_trial import origin
from payout_risk import weekend

VARIANTS=('conditional_all','conditional_recent')
SPEC=dict(version='conditional-tail-payout-v1',variants=VARIANTS,primary='conditional_recent',
    calibration='For each fixed budget, estimate wins divided by offers, including every admissible matured reference; never divide by refused paths. Native quantization and maximum width apply to calibration outcomes too.',
    grid='81 fixed budgets: (.95/M)*2**(k/8), k=-48..32. Largest supported budget with estimated conditional survival at or below .95/M. Identity prior 32. At least 200 offered references across three dates; unsupported calibration falls back to the raw model, explicitly recorded.',
    recent='Last three observed matching calendar dates for X100; last ten for X1000. If unsupported use the corresponding global window, then identity. All-history ablation uses all matching calendar dates, then all global dates.',
    maturity='Only dates strictly before the entry date and expiry plus thirty seconds strictly before its UTC midnight. Freeze calibration for the day; refused outcomes teach future calibration.',
    native='Unchanged active-tail separate asset fits, ppb precision, flat veto and positive parametric tail. Full-distribution parametric support replaces empirical twenty-tail gate; evaluation screens remain unchanged.',
    evidence='Repeatedly inspected historical development. Calibration support is not twenty rare events or a confidence guarantee. No production changes.')


def reference(r,p):
    minimum=max(1,-(-10**9//r['entry']));required=max(1,-(-(r['move']+1)*10**9//r['entry']))
    return dict(asset=r['asset'],start=r['start'],expiry=r['expiry'],period=r['period'],weekend=weekend(r),p0=p['p0'],
        admission=cdf(minimum,r,p),win_threshold=cdf(required,r,p) if required<=50000000 else None)


def select_references(refs,m,group,recent):
    part=[r for r in refs if group=='global' or r['weekend']==(group=='weekend')]
    dates=sorted({r['period'] for r in part})
    keep=dates[-(3 if m==100 else 10):] if recent else dates
    return [r for r in part if r['period'] in keep]


def calibration(refs,m,group,recent):
    part=select_references(refs,m,group,recent);target=.95/m;counts=Counter(r['period'] for r in part)
    result=dict(level=target,supported=False,n=len(part),dates=sorted(counts),candidates=[],selected=None)
    if not part:return result
    w=np.asarray([1/counts[r['period']]/len(counts) for r in part]);p0=np.asarray([r['p0'] for r in part]);admission=np.asarray([r['admission'] for r in part]);win=np.asarray([r['win_threshold'] if r['win_threshold'] is not None else math.inf for r in part])
    codes=np.asarray([sorted(counts).index(r['period']) for r in part]);choices=[]
    for k in range(-48,33):
        level=target*2**(k/8);offered=(admission<=level)&(p0<level);n=int(offered.sum());date_count=int(np.count_nonzero(np.bincount(codes[offered],minlength=len(counts))))
        mass=float(w@offered);wins=float(w@(offered&(win<=level)));rate=wins/mass if mass else None
        estimate=(n*rate+32*level)/(n+32) if rate is not None else None
        supported=n>=200 and date_count>=3
        cell=dict(level=level,offered=n,offered_dates=date_count,weighted_offer_mass=mass,conditional_survival=rate,smoothed_survival=estimate,supported=supported)
        result['candidates'].append(cell)
        if supported and estimate<=target:choices.append(cell)
    if choices:
        chosen=max(choices,key=lambda c:c['level']);result.update(level=chosen['level'],supported=True,selected=chosen)
    return result


def levels(refs,cutoff,asset):
    if any(r['asset']!=asset or r['period']>=cutoff for r in refs) or len({r['start'] for r in refs})!=len(refs):raise ValueError('Future, cross-asset or duplicate calibration reference')
    mature=[r for r in refs if r['expiry']+30000<origin(cutoff)]
    return {v:{str(m):{g:calibration(mature,m,g,v=='conditional_recent') for g in ('global','weekday','weekend')} for m in (100,1000)} for v in VARIANTS}


def chosen(packet,r,m,v):
    groups=packet['conditional_levels'][v][str(m)];g='weekend' if weekend(r) else 'weekday'
    for group in (g,'global'):
        if groups[group]['supported']:return groups[group]['level'],group
    return .95/m,'identity'


def quote(r,m,v,packet,predictor,p=None):
    level,source=chosen(packet,r,m,v)
    # Reuse the audited native width implementation, with the selected daily budget.
    proxy=dict(packet,levels={str(m):{g:dict(level=level,supported=True) for g in ('global','weekday','weekend')}})
    result=native_quote(r,m,'active_calibrated',proxy,predictor,p)
    result['calibration_source']=source
    return result
