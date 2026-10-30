"""Matched timing/market frozen CDFs with explicit quote-time priceability."""
from collections import deque
import math

import numpy as np

from adaptive_corridor import required_width
from chronological_raw_priors import training_rows
from preentry_bursty import sigmoid
from frozen_conditional_cdf import features as timing_features, FEATURES as TIMING_NAMES

MARKET_NAMES=('signed_mark_gap','absolute_mark_gap','gap_change30','mark_move30','absolute_mark_move30',
              'idle_x_gap','empty_bins_x_gap')
LEVELS=(.01,.05,.1,.2,.35,.5,.65,.8,.95,.99)
FAMILIES=('timing','market')
METHODS=(('static_open','static',None),('reference_open','reference',None),
         ('priceable_open','priceable',None),('static_gate53','static',.53),
         ('priceable_gate53','priceable',.53),('priceable_gate65','priceable',.65))
VARIANTS=('retained_open',)+tuple(f+':'+name for f in FAMILIES for name,_,_ in METHODS)
SPEC=dict(timing_features=TIMING_NAMES,market_features=MARKET_NAMES,positive_levels=LEVELS,ridge=.03,logistic_steps=30,quantile_steps=60,
    quantile_huber=.05,standardized_clip=5,minimum_width=1,maximum_width=50000,target=.48,
    maturity_delay_ms=30000,online_floor_gain=.1,online_level_gain=.03,logit_bound=3.,level_bounds=[.02,.98],
    online_age_ms=4*3600000,training='Matched clean frozen paths with fresh market context, path weighting, including refused reference outcomes',
    positive_target='log(required integer ppm / max(1, pre-entry slow volatility ppm))',
    quantile_crossing='Sort predicted positive log-widths before interpolation',
    admission='Replace only frozen admission. Non-frozen quotes stay open with retained widths.',
    anti_windup='Do not push coverage level outward at absolute width bounds',
    priceable_feedback='Floor model learns every supported clean label. Coverage level learns only forecasts whose saved floor is below .48; the decision is made at quote time, independent of refusal or outcome.',
    guarantee='No finite-period or conditional coverage guarantee')


def supported(row):
    g=row.get('oracle_gap');at=row['start']
    return bool(g is not None and len(g['values'])==5 and all(math.isfinite(v) for v in g['values'])
        and 0<at-g['observed_at']<=8000 and 0<at-30000-g['lag_observed_at']<=8000
        and g['lag_observed_at']<=g['observed_at'])


def features(row,use_market):
    values=timing_features(row)
    if use_market:
        if not supported(row):raise ValueError('fresh pre-entry context required')
        g=row['oracle_gap']['values'];a=row['activity_features']
        values+=g+[math.log1p(a['idle_ms']/1000)*g[1],a['empty_bins_300']*g[1]]
    return values


def fit(rows,family):
    if family not in FAMILIES:raise ValueError('declared feature family required')
    use_market=family=='market'
    part=[r for r in rows if r['valid'] and r['adaptive_features'] is not None and r['activity_state']=='frozen' and supported(r)]
    if len(part)<50:raise ValueError('at least fifty clean frozen training paths required')
    w=np.ones(len(part));w/=w.sum()
    raw=np.asarray([features(r,use_market) for r in part]);center=w@raw
    sd=np.maximum(.1,np.sqrt(w@((raw-center)**2)))
    x=np.column_stack((np.ones(len(part)),np.clip((raw-center)/sd,-5,5)))
    y=np.asarray([required_width(r)<=1 for r in part],dtype=float)
    penalty=np.diag([1e-8]+[SPEC['ridge']]*raw.shape[1]);coef=np.zeros(x.shape[1])
    rate=float(w@y);coef[0]=math.log(max(1e-6,rate)/max(1e-6,1-rate))
    for _ in range(SPEC['logistic_steps']):
        prob=sigmoid(x@coef);gradient=x.T@(w*(prob-y))+penalty@coef
        hessian=x.T@((w*prob*(1-prob))[:,None]*x)+penalty
        step=np.linalg.solve(hessian,gradient);step*=min(1,2/max(2,float(np.max(np.abs(step)))))
        coef-=step
        if np.max(np.abs(step))<1e-8:break
    positive=y==0
    if not positive.any():raise ValueError('positive-movement references required')
    px=x[positive];pw=w[positive];pw/=pw.sum()
    target=np.asarray([math.log(required_width(r)/max(1,r['adaptive_features']['vol_300_ppm'])) for r in part])[positive]
    coefficients=[]
    for q in LEVELS:
        qc=np.zeros(px.shape[1])
        for _ in range(SPEC['quantile_steps']):
            residual=target-px@qc
            irls=pw*np.where(residual>=0,q,1-q)/np.maximum(np.abs(residual),SPEC['quantile_huber'])
            updated=np.linalg.solve(px.T@(irls[:,None]*px)+penalty,px.T@(irls*target))
            if np.max(np.abs(updated-qc))<1e-7:qc=updated;break
            qc=updated
        coefficients.append(qc.tolist())
    return dict(weighting='path',family=family,features=TIMING_NAMES+(MARKET_NAMES if use_market else ()),center=center.tolist(),sd=sd.tolist(),
        floor_coefficients=coef.tolist(),positive_coefficients=coefficients,positive_levels=LEVELS,spec=SPEC,
        windows=len(part),periods=len({r['period'] for r in part}),positive_windows=int(positive.sum()),
        training_floor=rate,numpy_version=np.__version__)


def fit_prefix(normalized,rawdays,dates,cutoff,family):
    rows,provenance=training_rows(normalized,rawdays,dates,cutoff,True)
    return dict(model=fit(rows,family),training_periods=sorted(dates),cutoff=cutoff,provenance=provenance)


def forecast(row,model,logit_delta=0.,level=.48):
    z=[1.]+[max(-5,min(5,(v-m)/s)) for v,m,s in zip(features(row,model['family']=='market'),model['center'],model['sd'])]
    logit=sum(a*b for a,b in zip(z,model['floor_coefficients']))+logit_delta
    floor=1/(1+math.exp(-max(-30,min(30,logit))))
    logs=sorted(sum(a*b for a,b in zip(z,coef)) for coef in model['positive_coefficients'])
    q=max(LEVELS[0],min(LEVELS[-1],(level-floor)/max(1e-12,1-floor)))
    if floor>=level:return 1,floor,False,q
    adjustment=float(np.interp(q,LEVELS,logs))
    log_width=math.log(max(1,row['adaptive_features']['vol_300_ppm']))+adjustment
    capped=log_width>math.log(SPEC['maximum_width'])
    width=math.ceil(math.exp(min(math.log(SPEC['maximum_width']),max(math.log(2),log_width))))
    return max(2,min(SPEC['maximum_width'],width)),floor,capped,q


def series(values,model,mode,gate):
    if gate not in (None,.53,.65):raise ValueError('declared gate required')
    if mode not in ('static','reference','priceable'):raise ValueError('declared update mode required')
    online=mode!='static'
    pending=deque();period=previous=last_mature=None
    delta=0.;level=SPEC['target'];output=[]
    for p in values:
        row=p['row'];at=row['start']
        if previous is not None and at<previous:raise ValueError('chronological references required')
        previous=at
        if period!=row['period']:
            period=row['period'];pending.clear();delta=0.;level=SPEC['target'];last_mature=None
        if last_mature is not None and at-last_mature>SPEC['online_age_ms']:
            delta=0.;level=SPEC['target'];last_mature=None
        while pending and pending[0]['mature_at']<=at:
            old=pending.popleft();r=old['row']
            if online and r['valid'] and at-r['expiry']<=SPEC['online_age_ms']:
                floor=float(required_width(r)<=1)
                delta=max(-SPEC['logit_bound'],min(SPEC['logit_bound'],
                    delta+SPEC['online_floor_gain']*(floor-old['floor'])))
                hit=r['move']<r['entry']*old['width']//1000000
                direction=SPEC['target']-hit
                blocked=old['width']==1 and direction<0 or old['width']==SPEC['maximum_width'] and direction>0
                if not blocked and (mode=='reference' or old['floor']<SPEC['target']):
                    level=max(SPEC['level_bounds'][0],min(SPEC['level_bounds'][1],
                        level+SPEC['online_level_gain']*direction))
                last_mature=r['expiry']
        # Current validity and movement affect scoring only, never prediction.
        eligible=p['width_ppm'] is not None and row['activity_state']=='frozen' and supported(row)
        result=dict(p,paused=False,floor_reason='',survived=p['shadow_survived'])
        if eligible:
            width,floor,capped,positive_q=forecast(row,model,delta,level)
            paused=gate is not None and floor>gate
            hit=row['move']<row['entry']*width//1000000 if row['valid'] else None
            result.update(width_ppm=width,shadow_survived=hit,survived=None if paused else hit,paused=paused,capped=capped,
                floor_reason='conditional_frozen_floor' if paused else '',frozen_floor=floor,frozen_level=level,
                frozen_logit_delta=delta,positive_level=positive_q)
            pending.append(dict(row=row,width=width,floor=floor,mature_at=row['expiry']+SPEC['maturity_delay_ms']))
        output.append(result)
    return output


def all_series(values,models):
    output=dict(retained_open=[dict(p,paused=False,floor_reason='',survived=p['shadow_survived']) for p in values])
    for family in FAMILIES:
        for name,mode,gate in METHODS:output[family+':'+name]=series(values,models[family]['model'],mode,gate)
    return output
