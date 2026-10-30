"""Startup/drift refinements for bursty quotes; pure causal research overlays."""
from collections import deque
import math

from adaptive_corridor import required_width, weighted_quantile
from nonfrozen_pricing import STATES


def spec(name, *, family='cdf', memory=60, age_hours=1, half_life=30,
         prior=12, parent_mass=12, guard=False, step=.05):
    return dict(name=name, family=family, memory=memory, leaf_memory=memory//2,
                maximum_age_ms=int(age_hours*3_600_000), half_life_ms=half_life*60_000,
                prior_mass=prior, parent_mass=parent_mass, minimum_parent=12, minimum_leaf=4,
                maximum_step=step, minimum_correction=.05, maximum_correction=2.0,
                maturity_delay_ms=30_000, gain=.1, directional_guard=guard)


SPECS = (
    spec('engine_floor10', family='comparator'),
    spec('feedback_state_fast', family='comparator'),
    spec('floor10_burst_pool120', family='comparator'),
    spec('burst_clock120', family='clock', memory=120, age_hours=4, half_life=0),
    spec('burst_clock60', family='clock', half_life=0),
    spec('burst_feedback_leaky', family='feedback'),
    spec('burst_cdf120', memory=120, age_hours=4, half_life=0),
    spec('burst_cdf60'),
    spec('burst_cdf60_own', parent_mass=0),
    spec('burst_cdf60_prior4', prior=4, parent_mass=4),
    spec('burst_cdf60_guard', guard=True),
    spec('burst_cdf60_fast', step=.15),
)


def mixture_quantile(parent, leaf, trained, denominator, at, candidate, q):
    """Blend full distributions; floor atoms always survive at the current 1-ppm width."""
    minimum = 1 / denominator
    static = trained['static_factor']
    floor, mass = trained['minimum_width_floor'], candidate['prior_mass']
    values = []
    if floor > 0:
        values.append((minimum, mass*floor))
    positives = trained['positive_ratios']
    if positives and floor < 1:
        values.extend((max(minimum,v/static),mass*(1-floor)/len(positives)) for v in positives)
    def weight(item):
        half = candidate['half_life_ms']
        return 2**(-(at-item['expiry'])/half) if half else 1.0
    if candidate['parent_mass'] and len(parent)>=candidate['minimum_parent']:
        weights=[weight(v) for v in parent]
        total=sum(weights)
        values.extend((minimum if v['floor'] else max(minimum,v['ratio']),
                       candidate['parent_mass']*w/total) for v,w in zip(parent,weights))
    values.extend((minimum if v['floor'] else max(minimum,v['ratio']),weight(v)) for v in leaf)
    return weighted_quantile(values,q)


def reprice(values, model, candidate):
    if candidate['family']=='comparator':
        raise ValueError('comparators must use their pinned original implementation')
    pending,parent,leaf=deque(),deque(),deque()
    previous,session=None,None
    correction,theta=1.0,0.0
    q,age=model['target_survival'],candidate['maximum_age_ms']
    trained=model['states']['bursty']
    output=[]
    for p in values:
        r,at=p['row'],p['row']['start']
        if previous is not None and at<previous:
            raise ValueError('chronological predictions required')
        if session!=r['period']:
            session=r['period'];pending.clear();parent.clear();leaf.clear()
            correction,theta=1.0,0.0;previous=None
        if candidate['family']=='feedback' and previous is not None:
            theta*=2**(-(at-previous)/candidate['half_life_ms'])
        previous=at
        while pending and pending[0]['mature_at']<=at:
            past=pending.popleft();old=past['row']
            if not old['valid'] or at-old['expiry']>age:
                continue
            actual=required_width(old)
            item=dict(expiry=old['expiry'],ratio=actual/past['denominator'],floor=actual<=1)
            if old['activity_state']=='bursty':
                leaf.append(item)
                if candidate['family']=='feedback':
                    hit=old['move']<old['entry']*past['width']//1_000_000
                    # Age each scheduled update if several mature outcomes arrive after a gap.
                    theta-=candidate['gain']*(hit-q)*2**(-(at-past['mature_at'])/candidate['half_life_ms'])
                    theta=min(math.log(candidate['maximum_correction']),max(math.log(candidate['minimum_correction']),theta))
            # Preserve the previous hierarchy's parent for the clock-only ablations.
            if candidate['family']=='clock' or old['activity_state']!='bursty':
                parent.append(item)
        for pool,limit in ((parent,candidate['memory']),(leaf,candidate['leaf_memory'])):
            while pool and (len(pool)>limit or at-pool[0]['expiry']>age):pool.popleft()
        eligible=p['width_ppm'] is not None and r['activity_state'] in STATES
        requested=1.0
        if candidate['family']=='clock':
            if len(parent)>=candidate['minimum_parent']:
                empirical=weighted_quantile([(v['ratio'],1) for v in parent],q)
                requested=math.exp(len(parent)/(len(parent)+candidate['prior_mass'])*math.log(empirical))
            if len(leaf)>=candidate['minimum_leaf']:
                empirical=weighted_quantile([(v['ratio'],1) for v in leaf],q)
                weight=len(leaf)/(len(leaf)+candidate['prior_mass'])
                requested=math.exp(weight*math.log(empirical)+(1-weight)*math.log(requested))
        elif candidate['family']=='feedback':
            requested=math.exp(theta)
        elif eligible and r['activity_state']=='bursty':
            requested=mixture_quantile(parent,leaf,trained,p['width_ppm']*trained['static_factor'],at,candidate,q)
        requested=max(candidate['minimum_correction'],min(candidate['maximum_correction'],requested))
        # Clock-only/feedback targets are meaningful on every clean non-frozen entry.
        # CDF floor atoms depend on the current burst denominator, so tick only on burst entries.
        if eligible and (candidate['family']!='cdf' or r['activity_state']=='bursty'):
            step=candidate['maximum_step']
            correction=min(correction*(1+step),max(correction*(1-step),requested))
        guarded=candidate['directional_guard'] and r['market_regime'] in ('pump','dump')
        if eligible and r['activity_state']=='bursty' and not guarded:
            raw=max(1,math.ceil(p['width_ppm']*trained['static_factor']*correction))
            width=min(model['maximum_width_ppm'],raw)
            hit=r['move']<r['entry']*width//1_000_000 if r['valid'] else None
            result=dict(p,width_ppm=width,capped=raw>model['maximum_width_ppm'],shadow_survived=hit,
                        survived=None if p['paused'] else hit)
        else:result=dict(p)
        result.update(drift_correction=correction if eligible and r['activity_state']=='bursty' else None,
                      drift_leaf_mature=len(leaf),drift_parent_mature=len(parent),drift_requested=requested)
        output.append(result)
        if eligible:
            pending.append(dict(row=r,width=result['width_ppm'],
                                denominator=p['width_ppm']*model['states'][r['activity_state']]['static_factor'],
                                mature_at=r['expiry']+candidate['maturity_delay_ms']))
    return output
