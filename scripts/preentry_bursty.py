"""Past-only flat-risk admission and conditional bursty corridor research."""
from collections import deque
import math

import numpy as np

from adaptive_corridor import required_width,weighted_quantile
from nonfrozen_pricing import STATES,quantile_grid
from stabilize_adaptive_corridor import balanced_weights

FEATURES=('log_idle','log_changes30','log_changes60','log_changes300','empty_bins',
          'variance_concentration','log_slow_vol','log_fast_slow','efficiency_proxy',
          'directional_strength','idle_cooling')
PRICING=('retained_pool','slow_anchor','conditional_static','conditional_residual')
GATES=(('unchanged',None),('preentry_floor53',.53),('preentry_floor65',.65))
VARIANTS=tuple((p,g) for p in PRICING for g,_ in GATES)
FIT_SPEC=dict(ridge=.03,logistic_steps=30,quantile_steps=60,quantile_huber=.05,
              minimum_child_windows=80,minimum_child_periods=3,scale_clip=5,
              positive_quantile_bounds=(.02,.98))
ONLINE_SPEC=dict(memory=120,maximum_age_ms=3_600_000,half_life_ms=900_000,
    prior_mass=12,step=.05,minimum_correction=.25,maximum_correction=4,
    maturity_delay_ms=30_000,kernel_indices=(0,2,5,7,8),kernel_bandwidth=1.0)


def name(pricing,gate):return pricing+':'+gate


def features(row):
    """Explicit pre-entry allowlist: no movement, validity or outcome labels."""
    a,f=row['activity_features'],row['adaptive_features']
    idle=math.log1p(a['idle_ms']/1000);slow=max(.001,f['vol_300_ppm'])
    ratio=math.log(max(.001,f['vol_60_ppm'])/slow)
    return [idle,math.log1p(a['changes_30']),math.log1p(a['changes_60']),math.log1p(a['changes_300']),
            a['empty_bins_300'],a['largest_variance_share_300'],math.log(slow),ratio,
            min(1,f['directional_strength']/math.sqrt(max(1,a['changes_300']))),
            f['directional_strength'],idle*max(0,-ratio)]


def sigmoid(x):return 1/(1+np.exp(-np.clip(x,-30,30)))


def fit(values):
    part=[p for p in values if p['shadow_survived'] is not None and p['row']['activity_state'] in STATES]
    if not part:raise ValueError('clean non-frozen training references required')
    weights=np.asarray(balanced_weights([p['row'] for p in part]));weights/=weights.sum()
    raw=np.asarray([features(p['row']) for p in part]);center=weights@raw
    sd=np.maximum(.1,np.sqrt(weights@((raw-center)**2)))
    z=np.clip((raw-center)/sd,-FIT_SPEC['scale_clip'],FIT_SPEC['scale_clip'])
    x=np.column_stack((np.ones(len(part)),z))
    floor=np.asarray([required_width(p['row'])<=1 for p in part],dtype=float)
    penalty=np.diag([1e-8]+[FIT_SPEC['ridge']]*len(FEATURES))
    coef=np.zeros(x.shape[1]);rate=float(weights@floor)
    coef[0]=math.log(max(1e-6,rate)/max(1e-6,1-rate))
    for _ in range(FIT_SPEC['logistic_steps']):
        prob=sigmoid(x@coef);gradient=x.T@(weights*(prob-floor))+penalty@coef
        hessian=x.T@((weights*prob*(1-prob))[:,None]*x)+penalty
        delta=np.linalg.solve(hessian,gradient)
        # Damping bounds each Newton parameter update on thin early prefixes.
        delta*=min(1,2/max(2,float(np.max(np.abs(delta)))))
        coef-=delta
        if np.max(np.abs(delta))<1e-8:break
    floor_probability=sigmoid(x@coef)
    positive=floor==0
    if not positive.any():raise ValueError('positive-width training paths required')
    # The price feature encodes the current engine's private correction, rather
    # than attributing changing denominators to the oracle's entry features.
    base_ratio=np.asarray([math.log(p['width_ppm']/max(.001,p['row']['adaptive_features']['vol_300_ppm'])) for p in part])
    px=np.column_stack((x,np.clip(base_ratio,-5,5)))
    y=np.asarray([math.log(required_width(p['row'])/p['width_ppm']) for p in part])[positive]
    q=np.clip((.48-floor_probability[positive])/(1-floor_probability[positive]),*FIT_SPEC['positive_quantile_bounds'])
    pw=weights[positive];pw/=pw.sum();design=px[positive]
    qc=np.zeros(design.shape[1]);qp=np.diag([1e-8]+[FIT_SPEC['ridge']]*(design.shape[1]-1))
    for _ in range(FIT_SPEC['quantile_steps']):
        residual=y-design@qc
        irls=pw*np.where(residual>=0,q,1-q)/np.maximum(np.abs(residual),FIT_SPEC['quantile_huber'])
        updated=np.linalg.solve(design.T@(irls[:,None]*design)+qp,design.T@(irls*y))
        if np.max(np.abs(updated-qc))<1e-7:qc=updated;break
        qc=updated
    model=dict(features=FEATURES,fit_spec=FIT_SPEC,online_spec=ONLINE_SPEC,
        center=center.tolist(),sd=sd.tolist(),floor_coefficients=coef.tolist(),price_coefficients=qc.tolist(),
        windows=len(part),periods=len({p['row']['period'] for p in part}),minimum_width_floor=rate,
        numpy_version=np.__version__,maximum_width_ppm=50_000)
    cooling=[p for p in part if p['row']['activity_state']=='bursty' and
             p['row']['adaptive_features']['vol_60_ppm']/max(.001,p['row']['adaptive_features']['vol_300_ppm'])<.75]
    supported=len(cooling)>=80 and len({p['row']['period'] for p in cooling})>=3
    anchor=cooling if supported else part
    aw=balanced_weights([p['row'] for p in anchor])
    model['slow_anchor']=dict(factor=weighted_quantile([(required_width(p['row'])/max(1,p['row']['adaptive_features']['vol_300_ppm']),w)
        for p,w in zip(anchor,aw)],.48),windows=len(anchor),child_windows=len(cooling),
        child_periods=len({p['row']['period'] for p in cooling}),used_parent=not supported)
    forecasts=[conditional(p,model) for p in part]
    model['residual_prior']=quantile_grid([(required_width(p['row'])/forecast,w) for p,forecast,w in zip(part,forecasts,weights)])
    model['training_floor_brier']=float(weights@((floor_probability-floor)**2))
    return model


def point(row,model):
    return [max(-5,min(5,(v-m)/s)) for v,m,s in zip(features(row),model['center'],model['sd'])]


def risk(row,model):
    z=[1]+point(row,model)
    logit=sum(a*b for a,b in zip(z,model['floor_coefficients']))
    return 1/(1+math.exp(-max(-30,min(30,logit))))


def conditional(p,model):
    r=p['row'];base=p['width_ppm'];z=[1]+point(r,model)
    z.append(max(-5,min(5,math.log(base/max(.001,r['adaptive_features']['vol_300_ppm'])))))
    log_scale=sum(a*b for a,b in zip(z,model['price_coefficients']))
    return min(model['maximum_width_ppm'],max(1,math.ceil(base*math.exp(max(-3,min(3,log_scale))))))


def reprice(values,retained,model,method):
    """All reference updates mature before use; no admission-based learning."""
    if method not in PRICING:raise ValueError('unknown pricing method')
    pending=deque();pool=deque();output=[];period=None;previous=None;correction=1.0
    for p,b in zip(values,retained):
        r,at=p['row'],p['row']['start']
        if previous is not None and at<previous:raise ValueError('chronological predictions required')
        previous=at
        if period!=r['period']:
            period=r['period'];pending.clear();pool.clear();correction=1
        while pending and pending[0]['mature_at']<=at:
            old=pending.popleft()
            if old['row']['valid'] and at-old['row']['expiry']<=ONLINE_SPEC['maximum_age_ms']:
                pool.append(dict(expiry=old['row']['expiry'],ratio=required_width(old['row'])/old['forecast'],point=old['point']))
        while pool and (len(pool)>ONLINE_SPEC['memory'] or at-pool[0]['expiry']>ONLINE_SPEC['maximum_age_ms']):pool.popleft()
        eligible=p['width_ppm'] is not None and r['activity_state'] in STATES
        forecast=conditional(p,model) if eligible else None
        probability=risk(r,model) if eligible else None
        current=point(r,model) if eligible else None
        requested=1.0;effective=0.0;total=0.0
        if eligible and method=='conditional_residual':
            samples=[];weights=[]
            for old in pool:
                distance=sum((current[i]-old['point'][i])**2 for i in ONLINE_SPEC['kernel_indices'])
                w=2**(-(at-old['expiry'])/ONLINE_SPEC['half_life_ms'])*math.exp(-.5*distance)
                if w>1e-12:samples.append((old['ratio'],w));weights.append(w)
            total=sum(weights);effective=total*total/sum(w*w for w in weights) if total else 0
            # Prior mass remains when local evidence is sparse; no mandatory
            # quote warmup is inferred from an empty or low-confidence pool.
            mass=ONLINE_SPEC['prior_mass'];knots=model['residual_prior']
            samples.extend((x,mass/len(knots)) for x in knots)
            requested=weighted_quantile(samples,.48)
            requested=max(ONLINE_SPEC['minimum_correction'],min(ONLINE_SPEC['maximum_correction'],requested))
            step=ONLINE_SPEC['step'];correction=min(correction*(1+step),max(correction*(1-step),requested))
        result=dict(b)
        if eligible and r['activity_state']=='bursty' and method!='retained_pool':
            if method=='slow_anchor':
                f=r['adaptive_features'];ratio=f['vol_60_ppm']/max(.001,f['vol_300_ppm'])
                blend=max(0,min(1,(.75-ratio)/.25))
                anchor=max(b['width_ppm'],model['slow_anchor']['factor']*f['vol_300_ppm'])
                raw=(b['width_ppm'] if blend==0 or anchor==b['width_ppm'] else
                     math.ceil(math.exp((1-blend)*math.log(b['width_ppm'])+blend*math.log(anchor))))
            else:raw=math.ceil(forecast*(correction if method=='conditional_residual' else 1))
            width=max(1,min(model['maximum_width_ppm'],raw))
            hit=r['move']<r['entry']*width//1_000_000 if r['valid'] else None
            result.update(width_ppm=width,capped=raw>model['maximum_width_ppm'],shadow_survived=hit,
                          survived=None if b['paused'] else hit)
        result.update(preentry_floor_risk=probability,conditional_forecast=forecast,
            residual_correction=correction,residual_requested=requested,residual_effective=effective,residual_mass=total)
        output.append(result)
        if eligible and method=='conditional_residual':
            pending.append(dict(row=r,forecast=forecast,point=current,mature_at=r['expiry']+ONLINE_SPEC['maturity_delay_ms']))
    return output


def admit(values,gate):
    threshold=next(t for n,t in GATES if n==gate)
    output=[]
    for p in values:
        extra=(threshold is not None and p['width_ppm'] is not None and p['row']['activity_state']=='bursty'
               and p['preentry_floor_risk']>threshold)
        paused=p['paused'] or extra
        output.append(dict(p,paused=paused,survived=None if paused else p['shadow_survived'],
            preentry_refusal=bool(extra and not p['paused']),
            floor_reason=';'.join(x for x in (p.get('floor_reason',''),'preentry_flat_risk' if extra else '') if x)))
    return output
