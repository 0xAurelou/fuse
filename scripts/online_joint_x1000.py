"""Delayed flat/tail odds feedback on the frozen joint X1000 distribution."""
from collections import deque
import math

from joint_x1000 import TARGET,cdf,quote as native_quote,sigmoid

VARIANTS=('joint_static','joint_online_flat','joint_online_full')
SPEC=dict(version='online-joint-x1000-v1',variants=VARIANTS,primary='joint_online_full',
    distribution='Frozen earlier-only joint volatility/activity/liquidity model and native log-logistic tail from joint-x1000-v1; no model refit or regime-budget loosening.',
    feedback='All healthy admissible settled reference paths, including refused quotes. Flat odds factor (1 + observed zero paths)/(1 + sum entry-time raw p0), clipped .1..10; at least 60 matured references.',
    tail='Among positive paths, compare raw positive-CDF native required-width score to fixed .01 anchor. Positive-tail odds factor (1 + observed scores <= .01)/(1 + .01*positive count), clipped .25..4; at least 100 positive references.',
    memory='Most recent 480 matured admissible valid references, maximum six-hour expiry age; no future-health admission gate. Carry state across consecutive dates, age out monthly gaps. Strict maturity expiry + thirty seconds < current entry.',
    formula='Correct p0 odds by flat factor. Positive-CDF odds correction is equivalent to mu_corrected = mu - tail_scale*log(tail_factor). Invert the resulting mixture at .00095 with unchanged native rounding, flat veto and book requirements.',
    ablations='Static exactly reproduces parent joint_raw. Flat-only changes p0, full additionally adjusts positive-CDF odds. Both reference predictors remain frozen raw model forecasts, not their own corrected probabilities.',
    evidence='Outcome-informed historical development, not independent confidence. A one-event prior prevents a zero probability estimate; it is not a confidence bound. Original availability and rare-event screens unchanged. No live promotion.')


def reference(r,p):
    if not r['valid']:return dict(asset=r['asset'],start=r['start'],expiry=r['expiry'],valid=False,zero=None,p0=p['p0'],positive_score=None)
    required=max(1,-(-(r['move']+1)*10**9//r['entry']))
    z=(math.log(required/(max(1.,r['adaptive_features']['vol_300_ppm'])*1000))-p['mu'])/p['scale']
    return dict(asset=r['asset'],start=r['start'],expiry=r['expiry'],valid=r['valid'],zero=r['move']==0,p0=p['p0'],positive_score=sigmoid(z) if r['move']>0 else None)


class Feedback:
    def __init__(self,asset):
        self.asset=asset;self.pending=deque();self.recent=deque();self.previous=None

    def advance(self,at):
        if self.previous is not None and at<=self.previous:raise ValueError('Unique chronological online entries required')
        self.previous=at
        while self.pending and self.pending[0]['expiry']+30000<at:
            r=self.pending.popleft()
            if r['valid']:self.recent.append(r)
        while self.recent and (len(self.recent)>480 or at-self.recent[0]['expiry']>21600000):self.recent.popleft()
        part=list(self.recent);positive=[r for r in part if not r['zero']];n=len(part);np=len(positive)
        flat=max(.1,min(10.,(1+sum(r['zero'] for r in part))/(1+sum(r['p0'] for r in part)))) if n>=60 else 1.
        tail=max(.25,min(4.,(1+sum(r['positive_score']<=.01 for r in positive))/(1+.01*np))) if np>=100 else 1.
        return dict(references=n,positive_references=np,zero_events=sum(r['zero'] for r in part),raw_zero_sum=sum(r['p0'] for r in part),positive_anchor_events=sum(r['positive_score']<=.01 for r in positive),flat_factor=flat,tail_factor=tail)

    def push(self,ref):
        if ref['asset']!=self.asset or ref['start']!=self.previous or self.pending and ref['start']<=self.pending[-1]['start']:raise ValueError('Wrong online reference identity')
        self.pending.append(ref)


def quote(r,variant,packet,p,state):
    corrected=None;flat=state['flat_factor'] if variant!='joint_static' else 1.;tail=state['tail_factor'] if variant=='joint_online_full' else 1.
    if p is not None:
        adjusted=p['p0'] if flat==1 else p['p0']*flat/(1-p['p0']+p['p0']*flat);corrected=dict(p,p0=adjusted,mu=p['mu'] if tail==1 else p['mu']-p['scale']*math.log(tail))
    value=native_quote(r,'joint_raw',packet,corrected)
    return dict(value,raw_p0=p['p0'] if p is not None else None,flat_odds_factor=flat,tail_odds_factor=tail,matured_references=state['references'],matured_positive_references=state['positive_references'])
