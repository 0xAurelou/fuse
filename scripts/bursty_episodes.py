"""Causal feature matching and episode resets for bursty pricing research."""
from collections import deque
from copy import deepcopy
import math

from adaptive_corridor import required_width, weighted_quantile
from bursty_pricing import fit_model as base_fit
from nonfrozen_pricing import STATES,quantile_grid
from stabilize_adaptive_corridor import balanced_weights


def spec(name, *, comparator=False, episodes=False, kernel=False, reset='none',
         conditional=False, step=.05, guard=False):
    return dict(name=name,comparator=comparator,episodes=episodes,kernel=kernel,reset=reset,
                conditional=conditional,maximum_step=step,directional_guard=guard,
                episode_gap_ms=300_000,volatility_reset_ratio=2.0,reset_half_life_ms=300_000,
                memory=60,leaf_memory=30,maximum_age_ms=3_600_000,half_life_ms=1_800_000,
                prior_mass=12,parent_mass=12,minimum_parent=12,maturity_delay_ms=30_000,
                minimum_correction=.05,maximum_correction=2.0,
                kernel_bandwidths=(math.log(2),math.log(2),1.0,1.0))


SPECS=(
    spec('engine_floor10',comparator=True),
    spec('floor10_burst_pool120',comparator=True),
    spec('burst_clock120',comparator=True),
    spec('burst_cdf60',comparator=True),
    spec('episode_cdf',episodes=True,reset='full'),
    spec('kernel_cdf',kernel=True),
    spec('episode_kernel',episodes=True,kernel=True,reset='full'),
    spec('episode_kernel_soft',episodes=True,kernel=True,reset='decay'),
    spec('episode_kernel_fast',episodes=True,kernel=True,reset='full',step=.15),
    spec('episode_kernel_prior',episodes=True,kernel=True,reset='full',conditional=True),
    spec('episode_kernel_guard',episodes=True,kernel=True,reset='full',guard=True),
)


def coordinates(row):
    f,a=row['adaptive_features'],row['activity_features']
    slow=max(.001,f['vol_300_ppm'])
    return (math.log(slow),math.log(max(.001,f['vol_60_ppm'])/slow),
            math.log1p(a['idle_ms']/1000),math.log1p(a['changes_60']))


def context(row):
    f,a=row['adaptive_features'],row['activity_features']
    ratio=f['vol_60_ppm']/max(.001,f['vol_300_ppm'])
    shape='cooling' if ratio<.75 else 'balanced' if ratio<1.5 else 'fresh'
    return shape+(':recent' if a['idle_ms']<5000 else ':idle')


def fit_model(values):
    model=base_fit(values);leaves={}
    for shape in ('cooling','balanced','fresh'):
        for idle in ('recent','idle'):
            key=f'{shape}:{idle}'
            part=[p for p in values if p['shadow_survived'] is not None
                  and p['row']['activity_state']=='bursty' and context(p['row'])==key]
            periods=len({p['row']['period'] for p in part})
            leaf=deepcopy(model['states']['bursty'])
            fallback=len(part)<80 or periods<3
            if not fallback:
                weights=balanced_weights([p['row'] for p in part]);total=sum(weights)
                floor=sum(w*(required_width(p['row'])<=1) for p,w in zip(part,weights))/total
                ratios=[(required_width(p['row'])/p['width_ppm'],w) for p,w in zip(part,weights)]
                raw=weighted_quantile(ratios,model['target_survival']);weight=len(part)/(len(part)+200)
                factor=math.exp(weight*math.log(raw)+(1-weight)*math.log(leaf['static_factor']))
                positive=[(ratio,w) for (ratio,w),p in zip(ratios,part) if required_width(p['row'])>1]
                leaf.update(minimum_width_floor=floor,positive_ratios=quantile_grid(positive),static_factor=factor)
            leaf.update(context_windows=len(part),context_periods=periods,used_state_parent=fallback)
            leaves[key]=leaf
    model['episode_contexts']=leaves
    return model


def similarity(a,b,candidate):
    if not candidate['kernel']:return 1.0
    distance=sum(((x-y)/scale)**2 for x,y,scale in zip(a,b,candidate['kernel_bandwidths']))
    return math.exp(-.5*distance)


def estimate(parent,leaf,trained,denominator,point,at,candidate,q):
    minimum=1/denominator;mass=candidate['prior_mass'];floor=trained['minimum_width_floor']
    values=[(minimum,mass*floor)] if floor else []
    positives=trained['positive_ratios']
    if positives and floor<1:
        values.extend((max(minimum,v/trained['static_factor']),mass*(1-floor)/len(positives)) for v in positives)
    def weight(v):return 2**(-(at-v['expiry'])/candidate['half_life_ms'])*similarity(point,v['point'],candidate)
    effective=0.0;parent_mass=0.0
    if len(parent)>=candidate['minimum_parent']:
        weights=[weight(v) for v in parent];total=sum(weights);squares=sum(w*w for w in weights)
        effective=total*total/squares if squares else 0.0
        # Both similarity/age mass and effective count limit transfer confidence.
        parent_mass=candidate['parent_mass']*min(1,effective/12)*min(1,total/12)
        if total>0 and parent_mass>0:
            values.extend((minimum if v['floor'] else max(minimum,v['ratio']),parent_mass*w/total)
                          for v,w in zip(parent,weights) if w>0)
    for v in leaf:
        w=weight(v)
        if w>0:values.append((minimum if v['floor'] else max(minimum,v['ratio']),w))
    return weighted_quantile(values,q),effective,parent_mass


def reprice(values,model,candidate):
    if candidate['comparator']:raise ValueError('use pinned comparator implementation')
    pending,parent,leaf=deque(),deque(),deque()
    previous,period,last_burst,last_vol=None,None,None,None
    episode,correction=0,1.0
    out=[]
    for p in values:
        r,at=p['row'],p['row']['start']
        if previous is not None and at<previous:raise ValueError('chronological predictions required')
        previous=at
        if period!=r['period']:
            period=r['period'];pending.clear();parent.clear();leaf.clear()
            episode,correction,last_burst,last_vol=0,1.0,None,None
        eligible=p['width_ppm'] is not None and r['activity_state'] in STATES
        burst=eligible and r['activity_state']=='bursty'
        boundary=False
        if burst:
            vol=max(.001,r['adaptive_features']['vol_300_ppm'])
            boundary=(last_burst is None or at-last_burst>=candidate['episode_gap_ms']
                      or max(vol/last_vol,last_vol/vol)>=candidate['volatility_reset_ratio'])
            if boundary:
                episode+=1
                if candidate['reset']=='full':correction=1.0
                elif candidate['reset']=='decay' and last_burst is not None:
                    correction=correction**(2**(-(at-last_burst)/candidate['reset_half_life_ms']))
            last_burst,last_vol=at,vol
        while pending and pending[0]['mature_at']<=at:
            v=pending.popleft();old=v['row']
            if not old['valid'] or at-old['expiry']>candidate['maximum_age_ms']:continue
            actual=required_width(old)
            item=dict(expiry=old['expiry'],ratio=actual/v['denominator'],floor=actual<=1,
                      point=v['point'],episode=v['episode'])
            (leaf if old['activity_state']=='bursty' else parent).append(item)
        for pool,limit in ((parent,candidate['memory']),(leaf,candidate['leaf_memory'])):
            while pool and (len(pool)>limit or at-pool[0]['expiry']>candidate['maximum_age_ms']):pool.popleft()
        requested,effective,transfer=1.0,0.0,0.0
        trained=None
        if burst:
            trained=model['episode_contexts'][context(r)] if candidate['conditional'] else model['states']['bursty']
            local=[v for v in leaf if not candidate['episodes'] or v['episode']==episode]
            requested,effective,transfer=estimate(parent,local,trained,p['width_ppm']*trained['static_factor'],coordinates(r),at,candidate,model['target_survival'])
            requested=max(candidate['minimum_correction'],min(candidate['maximum_correction'],requested))
            step=candidate['maximum_step']
            correction=min(correction*(1+step),max(correction*(1-step),requested))
        guarded=candidate['directional_guard'] and r['market_regime'] in ('pump','dump')
        if burst and not guarded:
            raw=max(1,math.ceil(p['width_ppm']*trained['static_factor']*correction));width=min(model['maximum_width_ppm'],raw)
            hit=r['move']<r['entry']*width//1_000_000 if r['valid'] else None
            result=dict(p,width_ppm=width,capped=raw>model['maximum_width_ppm'],shadow_survived=hit,survived=None if p['paused'] else hit)
        else:result=dict(p)
        result.update(episode=episode,episode_boundary=boundary,episode_correction=correction if burst else None,
                      episode_requested=requested if burst else None,parent_effective=effective,parent_mass=transfer,
                      episode_mature=sum(v['episode']==episode for v in leaf) if burst else 0)
        out.append(result)
        if eligible:
            factor=(trained['static_factor'] if burst else model['states'][r['activity_state']]['static_factor'])
            pending.append(dict(row=r,denominator=p['width_ppm']*factor,point=coordinates(r),episode=episode,
                                mature_at=r['expiry']+candidate['maturity_delay_ms']))
    return out
