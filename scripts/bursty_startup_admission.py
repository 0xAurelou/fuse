"""Bursty startup gates; unchanged prices and causal reference-path learning."""
from collections import deque, defaultdict

from adaptive_corridor import required_width
from bursty_episodes import context


def spec(name, *, warm=0, floor=False, scope='state', prior=0, resume=None):
    return dict(name=name,warmup=warm,floor_guard=floor,scope=scope,prior_mass=prior,
                minimum_floor_outcomes=6,memory=30,maximum_age_ms=3_600_000,
                enter_floor=.53,resume_floor=resume,recovery_outcomes=2,
                maturity_delay_ms=30_000,episode_gap_ms=300_000,volatility_reset_ratio=2.0)


SPECS=(
    spec('unchanged'),
    spec('burst_warm6',warm=6),
    spec('burst_warm12',warm=12),
    spec('burst_floor6',floor=True),
    spec('burst_warm6_floor30',warm=6,floor=True),
    spec('burst_warm12_floor30',warm=12,floor=True),
    spec('episode_warm6_floor30',warm=6,floor=True,scope='episode'),
    spec('context_warm6_floor30',warm=6,floor=True,scope='context'),
    spec('burst_warm6_hysteresis',warm=6,floor=True,resume=.43),
    spec('burst_warm6_prior12',warm=6,floor=True,prior=12),
)


def admit(values,rule,model):
    """Learn all valid bursty shadow references only at expiry+30 seconds.

    Current validity/movement never controls admission. Boundaries use pre-entry
    burst gaps and slow volatility only. Scoring-interval boundaries do not reset
    continuous state. Existing masks are preserved and can only gain refusals.
    """
    pending=deque();pools=defaultdict(deque);latched={};since={};total=defaultdict(int)
    output=[];period=None;previous=None;last_burst=None;last_vol=None;episode=0
    for p in values:
        r,at=p['row'],p['row']['start']
        if previous is not None and at<previous:raise ValueError('chronological predictions required')
        previous=at
        if period!=r['period']:
            period=r['period'];pending.clear();pools.clear();latched.clear();since.clear();total.clear()
            last_burst=last_vol=None;episode=0
        burst=p['width_ppm'] is not None and r['activity_state']=='bursty'
        boundary=False;key=None
        if burst:
            vol=max(.001,r['adaptive_features']['vol_300_ppm'])
            boundary=(last_burst is None or at-last_burst>=rule['episode_gap_ms']
                      or max(vol/last_vol,last_vol/vol)>=rule['volatility_reset_ratio'])
            if boundary:episode+=1
            last_burst,last_vol=at,vol
            key=context(r) if rule['scope']=='context' else episode if rule['scope']=='episode' else 'state'
        while pending and pending[0]['mature_at']<=at:
            old=pending.popleft();row=old['row']
            if row['valid']:
                k=old['key'];pools[k].append(dict(expiry=row['expiry'],floor=required_width(row)<=1))
                total[k]+=1
        for k,pool in list(pools.items()):
            while pool and (len(pool)>rule['memory'] or at-pool[0]['expiry']>rule['maximum_age_ms']):pool.popleft()
            if not pool:
                latched.pop(k,None);since.pop(k,None);total.pop(k,None)
                del pools[k]
        # Expired episode keys cannot be revisited. Retain only their pending
        # maturity records, then discard evidence from earlier episodes.
        if rule['scope']=='episode':
            for k in list(pools):
                if k!=episode:
                    del pools[k];latched.pop(k,None);since.pop(k,None);total.pop(k,None)
        pool=pools.get(key,());n=len(pool);floor=None;reasons=[]
        if burst:
            trained=model['episode_contexts'][context(r)] if rule['scope']=='context' else model['states']['bursty']
            mass=rule['prior_mass']
            if n or mass:floor=(sum(x['floor'] for x in pool)+mass*trained['minimum_width_floor'])/(n+mass)
            if n<rule['warmup']:reasons.append('bursty_startup_evidence')
            if rule['floor_guard'] and n>=rule['minimum_floor_outcomes']:
                if rule['resume_floor'] is None:
                    if floor>rule['enter_floor']:reasons.append('bursty_minimum_width_floor')
                else:
                    if not latched.get(key,False) and floor>rule['enter_floor']:
                        latched[key]=True;since[key]=total[key]
                    elif (latched.get(key,False) and floor<=rule['resume_floor']
                          and total[key]-since[key]>=rule['recovery_outcomes']):latched[key]=False
                    if latched.get(key,False):reasons.append('bursty_floor_hysteresis')
        extra=bool(reasons);paused=p['paused'] or extra
        reason=';'.join(x for x in (p.get('floor_reason',''),';'.join(reasons)) if x)
        output.append(dict(p,paused=paused,survived=None if paused else p['shadow_survived'],floor_reason=reason,
            burst_admission_new_pause=extra and not p['paused'],burst_admission_mature=n,
            burst_admission_floor=floor,burst_admission_episode=episode,
            burst_admission_boundary=boundary,burst_admission_reason=';'.join(reasons)))
        if burst:
            pending.append(dict(row=r,key=key,mature_at=r['expiry']+rule['maturity_delay_ms']))
    return output
