"""Context-conditioned minimum-width mass and positive-width quantiles.

Offline research only. Entry inputs are an explicit past-only allowlist. The
optional calibration learns refused reference paths after expiry plus 30s.
"""
from collections import deque
import math

import numpy as np

from adaptive_corridor import required_width
from chronological_raw_priors import training_rows
from preentry_bursty import features as timing_features, FEATURES as TIMING_NAMES, sigmoid
from stabilize_adaptive_corridor import balanced_weights

FEATURES=TIMING_NAMES+('idle_lower_bound','signed_drift')
LEVELS=(.01,.05,.1,.2,.35,.5,.65,.8,.95,.99)
WEIGHTINGS=('period','path')
METHODS=(('static_open',False,None),('online_open',True,None),
         ('static_gate53',False,.53),('online_gate53',True,.53),('online_gate65',True,.65))
VARIANTS=('retained_open',)+tuple(w+':'+name for w in WEIGHTINGS for name,_,_ in METHODS)
SPEC=dict(features=FEATURES,positive_levels=LEVELS,ridge=.03,logistic_steps=30,quantile_steps=60,
    quantile_huber=.05,standardized_clip=5,minimum_width=1,maximum_width=50000,target=.48,
    maturity_delay_ms=30000,online_floor_gain=.1,online_level_gain=.03,logit_bound=3.,level_bounds=[.02,.98],
    online_age_ms=4*3600000,training='Clean frozen paths only, including refused reference outcomes',
    positive_target='log(required integer ppm / max(1, pre-entry slow volatility ppm))',
    quantile_crossing='Sort predicted positive log-widths before interpolation',
    admission='Replace only frozen admission. Non-frozen quotes stay open with retained widths.',
    anti_windup='Do not push coverage level outward at absolute width bounds',
    guarantee='No finite-period or conditional coverage guarantee')


def features(row):
    a,f=row['activity_features'],row['adaptive_features']
    return timing_features(row)+[float(a['idle_is_lower_bound']),math.tanh(f['net_300_bps']/20)]


def fit(rows,weighting):
    if weighting not in WEIGHTINGS:raise ValueError('declared weighting required')
    part=[r for r in rows if r['valid'] and r['adaptive_features'] is not None and r['activity_state']=='frozen']
    if len(part)<50:raise ValueError('at least fifty clean frozen training paths required')
    w=np.asarray(balanced_weights(part) if weighting=='period' else [1.]*len(part));w/=w.sum()
    raw=np.asarray([features(r) for r in part]);center=w@raw
    sd=np.maximum(.1,np.sqrt(w@((raw-center)**2)))
    x=np.column_stack((np.ones(len(part)),np.clip((raw-center)/sd,-5,5)))
    y=np.asarray([required_width(r)<=1 for r in part],dtype=float)
    penalty=np.diag([1e-8]+[SPEC['ridge']]*len(FEATURES));coef=np.zeros(x.shape[1])
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
    return dict(weighting=weighting,features=FEATURES,center=center.tolist(),sd=sd.tolist(),
        floor_coefficients=coef.tolist(),positive_coefficients=coefficients,positive_levels=LEVELS,spec=SPEC,
        windows=len(part),periods=len({r['period'] for r in part}),positive_windows=int(positive.sum()),
        training_floor=rate,numpy_version=np.__version__)


def fit_prefix(normalized,rawdays,dates,cutoff,weighting):
    rows,provenance=training_rows(normalized,rawdays,dates,cutoff,True)
    return dict(model=fit(rows,weighting),training_periods=sorted(dates),cutoff=cutoff,provenance=provenance)


def forecast(row,model,logit_delta=0.,level=.48):
    z=[1.]+[max(-5,min(5,(v-m)/s)) for v,m,s in zip(features(row),model['center'],model['sd'])]
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


def series(values,model,online,gate):
    if gate not in (None,.53,.65):raise ValueError('declared gate required')
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
                if not blocked:
                    level=max(SPEC['level_bounds'][0],min(SPEC['level_bounds'][1],
                        level+SPEC['online_level_gain']*direction))
                last_mature=r['expiry']
        # Current validity and movement affect scoring only, never prediction.
        supported=p['width_ppm'] is not None and row['activity_state']=='frozen'
        result=dict(p,paused=False,floor_reason='',survived=p['shadow_survived'])
        if supported:
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
    for weighting in WEIGHTINGS:
        for name,online,gate in METHODS:output[weighting+':'+name]=series(values,models[weighting]['model'],online,gate)
    return output
