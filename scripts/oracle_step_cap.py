"""Past-only observed oracle step GCD and a quote-preserving width cap."""
from collections import deque
import math

from joint_x1000 import cdf

SPEC=dict(version='hype-observed-step-cap-v1',asset='HYPE',primary='step_cap',variants=('baseline','step_cap'),
    diagnosis='Five inspected September HYPE X1000 wins: two zero-motion paths and three excursions of 500 native price units. This targeted revision is outcome-informed development.',
    estimator='GCD of positive oracle price changes in preceding 300 seconds, strictly before entry. At least four changes, 300 seconds observed since last reset, last oracle within eight seconds. Reset on declared disconnect or >8s oracle gap; no cross-day history.',
    cap='If representable, cap ppb width at the largest integer whose symmetric price delta is no larger than one observed step. Touch loses. Unsupported estimates leave the base width unchanged; no new offer or refusal, no broader barrier.',
    limitation='Observed step GCD is not an exchange tick rule or a guarantee of future precision. Flat paths still win at every positive width. No p0, model coefficient, feedback parameter or ETH change.',
    availability='Every pre-entry offer/refusal decision must equal the audited baseline, including unresolved quotes. Retain common daily/weekend/all-clean denominators. No live promotion.')


def step_features(observed,markers,starts):
    events=sorted([(at,1,px) for at,px in observed]+[(m['known_at'],0,None) for m in markers]);i=0;last=None;since=None;changes=deque();out=[]
    for at in starts:
        while i<len(events) and events[i][0]<at:
            t,kind,px=events[i];i+=1
            if kind==0:last=None;since=None;changes.clear();continue
            if last is None or t-last[0]>8000:
                since=t;changes.clear()
            elif px!=last[1]:changes.append((t,abs(px-last[1])))
            last=(t,px)
        while changes and changes[0][0]<at-300000:changes.popleft()
        step=0
        for _,d in changes:step=math.gcd(step,d)
        support=last is not None and 0<at-last[0]<=8000 and since is not None and at-since>=300000 and len(changes)>=4 and step>0
        out.append(dict(start=at,step_units=step or None,positive_changes=len(changes),observed_since=since,last_oracle_at=last[0] if last else None,last_price_units=last[1] if last else None,supported=support))
    return out


def apply(r,base,step,p=None):
    value=dict(base);width=base['width_ppb'];limit=None;applied=False;reason='unsupported_step'
    if step['supported'] and width is not None:
        limit=((step['step_units']+1)*10**9-1)//r['entry'];minimum=max(1,-(-10**9//r['entry']))
        if limit<minimum:reason='unrepresentable_step_cap'
        else:
            width=min(width,limit);applied=width<base['width_ppb'];reason='capped' if applied else 'already_narrower'
    if width is not None:
        delta=r['entry']*width//10**9;shadow=r['move']<delta if r['valid'] else None
        value.update(width=width/1000,width_ppb=width,barrier_delta_units=delta,shadow=shadow,survived=shadow if base['offered'] else None)
        if p is not None:value['model_survival']=cdf(width,r,p)
    value.update(base_width_ppb=base['width_ppb'],base_barrier_delta_units=base['barrier_delta_units'],base_model_survival=base['model_survival'],observed_step_units=step['step_units'],step_supported=step['supported'],step_cap_ppb=limit,step_cap_applied=applied,step_cap_reason=reason)
    if value['offered']!=base['offered'] or width is not None and width>base['width_ppb'] or value['offered'] and value['barrier_delta_units']<=0 or value['survived'] is True and base['survived'] is not True:raise ValueError('Step cap changed admission, broadened a barrier or added a win')
    return value
