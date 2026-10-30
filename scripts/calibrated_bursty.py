"""Chronological risk calibration and evidence-scaled bursty residual pricing."""
from collections import deque
import math
import numpy as np

from adaptive_corridor import required_width,weighted_quantile
from nonfrozen_pricing import STATES,quantile_grid
from preentry_bursty import features,point,risk,FIT_SPEC,sigmoid
from stabilize_adaptive_corridor import balanced_weights

PRICING=('retained_pool','mass_residual','ess6_residual','ess12_residual')
GATES=('unchanged','static_gate','chrono_gate','context_gate')
VARIANTS=tuple((p,g) for p in PRICING for g in GATES)
SPEC=dict(minimum_prefix_periods=2,minimum_child_windows=80,minimum_child_periods=3,
    calibration_intercept_ridge=.02,calibration_slope_ridge=.05,minimum_slope=.25,maximum_slope=4,
    memory=120,maximum_age_ms=3_600_000,half_life_ms=900_000,prior_mass=12,
    maximum_effective_mass=24,minimum_similarity_mass=1,minimum_risk_effective=6,
    kernel_indices=(0,2,5,7,8),step=.05,minimum_correction=.25,maximum_correction=4,
    maturity_delay_ms=30_000,gate_threshold=.53,maximum_width_ppm=50_000)


def name(pricing,gate):return pricing+':'+gate


def fit_floor(values):
    """Same binary fit as the pinned model; independent of any quoted width."""
    part=[p for p in values if p['shadow_survived'] is not None and p['row']['activity_state'] in STATES]
    if not part:raise ValueError('clean training references required')
    w=np.asarray(balanced_weights([p['row'] for p in part]));w/=w.sum()
    raw=np.asarray([features(p['row']) for p in part]);center=w@raw
    sd=np.maximum(.1,np.sqrt(w@((raw-center)**2)))
    x=np.column_stack((np.ones(len(part)),np.clip((raw-center)/sd,-5,5)))
    y=np.asarray([required_width(p['row'])<=1 for p in part],dtype=float)
    penalty=np.diag([1e-8]+[FIT_SPEC['ridge']]*raw.shape[1]);coef=np.zeros(x.shape[1])
    rate=float(w@y);coef[0]=math.log(max(1e-6,rate)/max(1e-6,1-rate))
    for _ in range(FIT_SPEC['logistic_steps']):
        prob=sigmoid(x@coef);grad=x.T@(w*(prob-y))+penalty@coef
        hess=x.T@((w*prob*(1-prob))[:,None]*x)+penalty
        delta=np.linalg.solve(hess,grad);delta*=min(1,2/max(2,float(np.max(np.abs(delta)))))
        coef-=delta
        if np.max(np.abs(delta))<1e-8:break
    return dict(center=center.tolist(),sd=sd.tolist(),floor_coefficients=coef.tolist())


def platt(records,parent=(0,1)):
    if not records:return dict(coefficients=list(parent),windows=0,periods=0,used_parent=True)
    w=np.asarray(balanced_weights([p['row'] for p in records]));w/=w.sum()
    logits=np.asarray([math.log(max(1e-9,p['probability'])/max(1e-9,1-p['probability'])) for p in records])
    x=np.column_stack((np.ones(len(records)),logits));y=np.asarray([p['floor'] for p in records],dtype=float)
    center=np.asarray(parent,dtype=float);coef=center.copy()
    penalty=np.diag([SPEC['calibration_intercept_ridge'],SPEC['calibration_slope_ridge']])
    for _ in range(30):
        pred=sigmoid(x@coef);grad=x.T@(w*(pred-y))+penalty@(coef-center)
        hess=x.T@((w*pred*(1-pred))[:,None]*x)+penalty
        delta=np.linalg.solve(hess,grad);delta*=min(1,1/max(1,float(np.max(np.abs(delta)))))
        coef-=delta;coef[0]=np.clip(coef[0],-4,4);coef[1]=np.clip(coef[1],SPEC['minimum_slope'],SPEC['maximum_slope'])
        if np.max(np.abs(delta))<1e-8:break
    return dict(coefficients=coef.tolist(),windows=len(records),periods=len({p['row']['period'] for p in records}),used_parent=False)


def fit_calibration(values):
    part=[p for p in values if p['shadow_survived'] is not None and p['row']['activity_state'] in STATES]
    dates=sorted({p['row']['period'] for p in part});records=[];folds=[]
    for i in range(SPEC['minimum_prefix_periods'],len(dates)):
        train=[p for p in part if p['row']['period'] in dates[:i]]
        held=[p for p in part if p['row']['period']==dates[i]]
        held_start=min(p['row']['start'] for p in held)
        if any(p['row']['expiry']+SPEC['maturity_delay_ms']>=held_start for p in train):
            raise ValueError('OOF training label not mature before scoring day')
        model=fit_floor(train)
        predictions=[risk(p['row'],model) for p in held]
        for p,probability in zip(held,predictions):records.append(dict(row=p['row'],probability=probability,floor=required_width(p['row'])<=1))
        folds.append(dict(training_periods=dates[:i],scoring_period=dates[i],windows=len(held),
            predicted_sum=sum(predictions),floor_count=sum(required_width(p['row'])<=1 for p in held)))
    parent=platt(records);bursty=[p for p in records if p['row']['activity_state']=='bursty']
    supported=len(bursty)>=SPEC['minimum_child_windows'] and len({p['row']['period'] for p in bursty})>=SPEC['minimum_child_periods']
    child=platt(bursty,parent['coefficients']) if supported else dict(parent,used_parent=True)
    child.update(child_windows=len(bursty),child_periods=len({p['row']['period'] for p in bursty}))
    return dict(parent=parent,bursty=child,folds=folds,identity_fallback=not records)


def fit(values,retained,static):
    if len(values)!=len(retained):raise ValueError('training alignment differs')
    calibration=fit_calibration(values)
    def estimate(part):
        weights=balanced_weights([p['row'] for p in part])
        return dict(knots=quantile_grid([(required_width(p['row'])/p['width_ppm'],w) for p,w in zip(part,weights)]),
            windows=len(part),periods=len({p['row']['period'] for p in part}))
    all_part=[p for p in retained if p['shadow_survived'] is not None and p['row']['activity_state'] in STATES]
    parent=estimate(all_part);bursty=[p for p in all_part if p['row']['activity_state']=='bursty']
    supported=len(bursty)>=80 and len({p['row']['period'] for p in bursty})>=3
    child=estimate(bursty) if supported else dict(parent)
    child.update(used_parent=not supported,child_windows=len(bursty),child_periods=len({p['row']['period'] for p in bursty}))
    return dict(calibration=calibration,residual_parent=parent,residual_bursty=child,
                static=static,spec=SPEC,numpy_version=np.__version__)


def calibrated(probability,row,model):
    leaf=model['calibration']['bursty' if row['activity_state']=='bursty' else 'parent']
    a,b=leaf['coefficients'];logit=math.log(max(1e-9,probability)/max(1e-9,1-probability))
    return 1/(1+math.exp(-max(-30,min(30,a+b*logit))))


def local_samples(pool,current,width_ratio,at):
    samples=[];weights=[]
    for old in pool:
        distance=sum((current[i]-old['point'][i])**2 for i in SPEC['kernel_indices'])
        distance+=(width_ratio-old['width_ratio'])**2
        w=2**(-(at-old['expiry'])/SPEC['half_life_ms'])*math.exp(-.5*distance)
        if w>1e-12:samples.append((old,w));weights.append(w)
    total=sum(weights);effective=total*total/sum(w*w for w in weights) if total else 0
    return samples,total,effective


def effective_mass(total,effective,minimum):
    return min(SPEC['maximum_effective_mass'],effective) if total>=SPEC['minimum_similarity_mass'] and effective>=minimum else 0


def series(values,retained,model,method):
    """Risk and reference-relative price adapters learn only matured paths."""
    if method not in PRICING:raise ValueError('unknown method')
    return _series(values,retained,model,(method,))[method]


def all_series(values,retained,model):
    return _series(values,retained,model,PRICING)


def _series(values,retained,model,methods):
    if len(values)!=len(retained):raise ValueError('prediction alignment differs')
    pool=deque();pending=deque();previous=None;period=None
    corrections={m:1.0 for m in methods};out={m:[] for m in methods}
    for base,reference in zip(values,retained):
        r,at=base['row'],base['row']['start']
        if at!=reference['row']['start']:raise ValueError('reference timestamps differ')
        if previous is not None and at<previous:raise ValueError('chronological predictions required')
        previous=at
        if period!=r['period']:
            period=r['period'];pool.clear();pending.clear();corrections={m:1.0 for m in methods}
        while pending and pending[0]['mature_at']<=at:
            old=pending.popleft()
            if old['row']['valid'] and at-old['row']['expiry']<=SPEC['maximum_age_ms']:
                pool.append(dict(expiry=old['row']['expiry'],point=old['point'],width_ratio=old['width_ratio'],
                    ratio=required_width(old['row'])/old['width'],floor=required_width(old['row'])<=1))
        while pool and (len(pool)>SPEC['memory'] or at-pool[0]['expiry']>SPEC['maximum_age_ms']):pool.popleft()
        eligible=base['width_ppm'] is not None and r['activity_state'] in STATES
        static=chrono=contextual=None;total=effective=mass=0;requested=1.0
        if eligible:
            current=point(r,model['static']);ratio=math.log(reference['width_ppm']/max(.001,r['adaptive_features']['vol_300_ppm']))
            static=risk(r,model['static']);chrono=calibrated(static,r,model)
            samples,total,effective=local_samples(pool,current,ratio,at)
            mass=effective_mass(total,effective,SPEC['minimum_risk_effective'])
            local_floor=sum(w*old['floor'] for old,w in samples)/total if total else 0
            contextual=(SPEC['prior_mass']*chrono+mass*local_floor)/(SPEC['prior_mass']+mass)
        for method in methods:
            p=dict(reference);correction=corrections[method];requested=1.0
            if eligible and method!='retained_pool':
                prior=model['residual_bursty'] if r['activity_state']=='bursty' else model['residual_parent']
                minimum=6 if method=='ess6_residual' else 12
                evidence=total if method=='mass_residual' else effective_mass(total,effective,minimum)
                knots=prior['knots'];qvalues=[(v,SPEC['prior_mass']/len(knots)) for v in knots]
                if total and evidence:qvalues.extend((old['ratio'],evidence*w/total) for old,w in samples)
                requested=weighted_quantile(qvalues,.48)
                requested=max(SPEC['minimum_correction'],min(SPEC['maximum_correction'],requested))
                step=SPEC['step'];correction=min(correction*(1+step),max(correction*(1-step),requested))
                corrections[method]=correction
                if r['activity_state']=='bursty':
                    # Preserve exact integer no-ops, including the comparator.
                    raw=reference['width_ppm'] if correction==1 else math.ceil(reference['width_ppm']*correction)
                    width=max(1,min(SPEC['maximum_width_ppm'],raw))
                    hit=r['move']<r['entry']*width//1_000_000 if r['valid'] else None
                    p.update(width_ppm=width,capped=raw>SPEC['maximum_width_ppm'],shadow_survived=hit,
                        survived=None if reference['paused'] else hit)
            p.update(risk_static=static,risk_chrono=chrono,risk_context=contextual,local_mass=total,
                local_effective=effective,risk_effective_mass=mass,price_correction=correction,price_requested=requested)
            out[method].append(p)
        if eligible:
            pending.append(dict(row=r,width=reference['width_ppm'],point=current,width_ratio=ratio,
                mature_at=r['expiry']+SPEC['maturity_delay_ms']))
    return out


def admit(values,gate):
    key={'unchanged':None,'static_gate':'risk_static','chrono_gate':'risk_chrono','context_gate':'risk_context'}[gate]
    out=[]
    for p in values:
        extra=(key is not None and p['width_ppm'] is not None and p['row']['activity_state']=='bursty'
               and p[key]>SPEC['gate_threshold'])
        paused=p['paused'] or extra
        out.append(dict(p,paused=paused,survived=None if paused else p['shadow_survived'],calibrated_refusal=bool(extra and not p['paused']),
            floor_reason=';'.join(v for v in (p.get('floor_reason',''),'calibrated_flat_risk' if extra else '') if v)))
    return out
