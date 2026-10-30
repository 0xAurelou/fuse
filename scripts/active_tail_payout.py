"""Quote-state risk fitting and native-precision parametric excursion tails."""
from collections import Counter
import math
from statistics import NormalDist

import numpy as np

from flat_aware_payout import veto
from payout_risk import features,logistic,required_width,weights,weekend
from research_trial_liquidity import training
from trial_payout import available,quote as old_quote

VARIANTS=('active_empirical','active_parametric','active_calibrated')
SPEC=dict(version='active-tail-payout-v1',variants=VARIANTS,primary='active_calibrated',
    universe='All matched paths with five-minute history and a pre-entry price change in the previous thirty seconds, known idle age, and idle below thirty seconds. The flat veto is unchanged; the blanket four-change/three-second recovery restriction is replaced by fitted risk.',
    risk='Separate assets; ridge .0001 logistic zero/minimum-ppm heads on market-calendar timing features plus six measured liquidity values, fitted only to the quote-state universe. All admissible references teach, even refused quotes.',
    tail='Date-weighted lognormal regression of positive native required width divided by slow volatility. Ridge .003, residual sigma >=.15; at least 200 positive paths across five earlier dates. Parametric extrapolation, not an empirical rare-tail evidence claim.',
    precision='Integer native ppb; strictly positive representable symmetric barrier, floor width downward. Refuse when estimated minimum-representable-width risk exceeds the calibrated budget.',
    calibration='Full model-CDF scores of all matured admissible out-of-sample paths, including zeros and refused quotes. Equal date mass, identity prior 32; weekday/weekend levels require three dates and twenty target-expected reference events, otherwise global, otherwise raw identity. No current-date scores.',
    support='The empirical control retains twenty positive-tail references. The parametric models use full-distribution fit support instead, explicitly flag whether the old empirical rule would pass. The unchanged evaluated twenty-target-event and availability screens still apply.',
    evidence='Outcome-informed historical development; no untouched holdout, calibration or profitability guarantee; no production promotion.')
NORMAL=NormalDist()


def admissible(row):
    return available(row,'calendar_liquidity') and veto(row,100,False) is None


def vector(row):return features(row,'market_calendar')+row['liquidity']['values']


def fit(rows,asset,cutoff):
    rows=[r for r in training(rows,asset,cutoff) if admissible(r)]
    if len(rows)<200 or len({r['period'] for r in rows})<5:raise ValueError('Insufficient admissible fit support')
    w=weights(rows);raw=np.asarray([vector(r) for r in rows]);center=w@raw;sd=np.maximum(.1,np.sqrt(w@((raw-center)**2)))
    x=np.column_stack((np.ones(len(rows)),np.clip((raw-center)/sd,-5,5)))
    y0=np.asarray([r['move']==0 for r in rows],dtype=float);ym=np.asarray([required_width(r)<=1 for r in rows],dtype=float)
    zero=logistic(x,w,y0,.0001);minimum=zero if np.array_equal(y0,ym) else logistic(x,w,ym,.0001)
    ids=[i for i,r in enumerate(rows) if r['move']>0];positive=[rows[i] for i in ids]
    if len(ids)<200 or len({r['period'] for r in positive})<5:raise ValueError('Insufficient positive parametric fit support')
    wp=weights(positive);xp=x[ids]
    y=np.asarray([math.log((r['move']+1)*1e9/r['entry']/(max(1.,r['adaptive_features']['vol_300_ppm'])*1000)) for r in positive])
    penalty=np.diag([1e-9]+[.003]*(x.shape[1]-1));coef=np.linalg.solve(xp.T@(wp[:,None]*xp)+penalty,xp.T@(wp*y))
    sigma=max(.15,float(np.sqrt(wp@((y-xp@coef)**2))))
    return dict(asset=asset,cutoff=cutoff,training_dates=sorted({r['period'] for r in rows}),rows=len(rows),positive_rows=len(ids),
        positive_dates=sorted({r['period'] for r in positive}),numpy_version=np.__version__,center=center.tolist(),sd=sd.tolist(),zero_coefficients=zero,
        minimum_coefficients=minimum,tail_coefficients=coef.tolist(),tail_sigma=sigma,spec=SPEC)


def forecast(row,model):
    x=[1.]+[max(-5,min(5,(v-m)/s)) for v,m,s in zip(vector(row),model['center'],model['sd'])]
    probabilities=[1/(1+math.exp(-max(-30,min(30,sum(a*b for a,b in zip(x,model[k])))))) for k in ('zero_coefficients','minimum_coefficients')]
    return dict(p0=probabilities[0],floor=max(probabilities),mu=sum(a*b for a,b in zip(x,model['tail_coefficients'])),sigma=model['tail_sigma'])


def cdf(width_ppb,row,p):
    if width_ppb<=0:return 0.
    scale=max(1.,row['adaptive_features']['vol_300_ppm'])*1000
    return p['p0']+(1-p['p0'])*NORMAL.cdf((math.log(width_ppb/scale)-p['mu'])/p['sigma'])


def score(row,p):
    return p['p0'] if row['move']==0 else cdf((row['move']+1)*1e9/row['entry'],row,p)


def calibration_level(refs,multiplier,group):
    target=.95/multiplier
    part=[r for r in refs if group=='global' or r['weekend']==(group=='weekend')]
    n=len(part);dates=sorted({r['period'] for r in part});supported=n*target>=20 and len(dates)>=3
    if not supported:return dict(level=target,supported=False,n=n,dates=dates,reference_target_events=n*target)
    counts=Counter(r['period'] for r in part);pairs=sorted((r['score'],1/counts[r['period']]/len(counts)) for r in part)
    values=np.asarray([p[0] for p in pairs]);cumulative=np.cumsum([p[1] for p in pairs]);cumulative/=cumulative[-1]
    left=0.;right=1.
    for _ in range(64):
        mid=(left+right)/2;index=int(np.searchsorted(values,mid,side='right'));empirical=float(cumulative[index-1]) if index else 0.
        probability=(n*empirical+32*mid)/(n+32)
        if probability<=target:left=mid
        else:right=mid
    return dict(level=left,supported=True,n=n,dates=dates,reference_target_events=n*target)


def levels(refs,cutoff):
    from fetch_tardis_liquidity_trial import origin
    if any(r['period']>=cutoff for r in refs) or len({r['start'] for r in refs})!=len(refs):raise ValueError('Future or duplicate calibration references')
    mature=[r for r in refs if r['expiry']+30000<origin(cutoff)]
    return {str(m):{g:calibration_level(mature,m,g) for g in ('global','weekday','weekend')} for m in (100,1000)}


def budget(packet,row,multiplier,variant):
    if variant!='active_calibrated':return .95/multiplier,'identity'
    group='weekend' if weekend(row) else 'weekday';local=packet['levels'][str(multiplier)][group]
    if local['supported']:return local['level'],group
    parent=packet['levels'][str(multiplier)]['global']
    return (parent['level'],'global') if parent['supported'] else (.95/multiplier,'identity')


def quote(row,multiplier,variant,packet,predictor,p=None):
    why='missing_history' if row['adaptive_features'] is None else 'missing_liquidity' if row.get('liquidity') is None else veto(row,100,False)
    p=p if p is not None else forecast(row,packet['model']) if why is None else None
    target,source=budget(packet,row,multiplier,variant)
    if variant=='active_empirical':
        values=dict(p0=p['p0'],floor=p['floor'],calibrated0=False,calibrated_floor=False) if p is not None else dict(p0=None,floor=None,calibrated0=False,calibrated_floor=False)
        result=old_quote(row,values,multiplier,'calendar_liquidity_raw_cdf',predictor)
        if why:result.update(offered=False,survived=None,reason=why)
        return dict(result,flat_guard=why,level=target,calibration_source=source,parametric=False,old_tail_supported=result['tail_supported'],model_survival=None)
    width=None;positive_q=None;empirical_support=False;probability=None
    if why is None:
        positive_q=(target-p['p0'])/(1-p['p0'])
        if not 0<positive_q<1:why='predicted_flat_risk'
        else:
            old_q=(target-p['floor'])/(1-p['floor'])
            old_n=packet['empirical']['anchors']['slow']['global_distribution']['n']
            empirical_support=0<old_q<1 and old_n*old_q>=20
            minimum=max(1,(10**9+row['entry']-1)//row['entry'])
            if cdf(minimum,row,p)>target:why='minimum_width_budget'
            else:
                log_width=math.log(max(1.,row['adaptive_features']['vol_300_ppm'])*1000)+p['mu']+p['sigma']*NORMAL.inv_cdf(positive_q)
                width=max(minimum,min(50000000,math.floor(math.exp(min(30,log_width)))))
                while width>minimum and cdf(width,row,p)>target+1e-12:width-=1
                probability=cdf(width,row,p)
                if probability>target+1e-10:why='native_width_budget'
    delta=row['entry']*width//10**9 if width is not None else None
    shadow=row['move']<delta if row['valid'] and delta is not None else None
    return dict(width=width/1000 if width is not None else None,width_ppb=width,barrier_delta_units=delta,offered=why is None,reason=why or '',
        positive_q=positive_q,tail_mass=packet['model']['positive_rows']*max(0,positive_q or 0),tail_supported=None,child_supported=None,
        p0=p['p0'] if p is not None else None,floor=p['p0'] if p is not None else None,calibrated0=False,calibrated_floor=False,
        shadow=shadow,survived=shadow if why is None else None,flat_guard=why if why in ('flat_oracle_veto','missing_history','missing_liquidity') else None,
        level=target,calibration_source=source,parametric=True,old_tail_supported=empirical_support,model_survival=probability)
