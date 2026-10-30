"""Joint volatility/activity/liquidity hurdle and native X1000 lower tail."""
from bisect import bisect_right
import math

import numpy as np

from active_tail_payout import vector as base_vector
from conditional_tail_payout import calibration
from fetch_tardis_liquidity_trial import origin
from flat_aware_payout import veto
from payout_risk import logistic,weights,weekend
from research_trial_liquidity import training

TARGET=.00095
VARIANTS=('joint_raw','joint_global','joint_local')
SPEC=dict(version='joint-x1000-v1',variants=VARIANTS,primary='joint_local',multiplier=1000,target=TARGET,
    fit='Separate assets, last ten observed earlier admissible dates; equal date weights. Minimum 200 fit paths and 200 positive paths across at least five dates. Native book freshness and flat veto retained.',
    features='Existing calendar, oracle/market activity and six book features plus idle/activity hinges and nine volatility/activity/idle by spread/minimum-side-depth/imbalance interactions. No current outcome or date identifier.',
    risk='Ridge .0003 logistic zero-motion head; positive log normalized required native width ridge .01 location with logistic residual scale = weighted residual SD * sqrt(3)/pi, minimum .08. Log-logistic positive tail replaces the old single lognormal; a distribution assumption, not empirical rare-tail evidence.',
    grouping='Four zero-risk rank groups using exact date-weighted training-only p0 quartiles. Rank combines all signals through fitted coefficients; no hard volatility quartile exclusion.',
    calibration='Conditional wins/offers at 81 fixed budgets .00095*2**(k/8), k=-48..32. Date-balanced references on last ten observed matching dates; identity prior 32, at least 200 offered references across three earlier dates. Highest passing budget. Local calendar/risk group -> risk group -> calendar -> global -> raw identity. All admissible matured OOF outcomes teach, including refusals.',
    global_ablation='Same joint model and tail, same conditional calibration but calendar -> global -> identity; raw ablation uses .00095 directly.',
    native='Integer ppb, downward rounding, strictly positive representable symmetric price delta, maximum 50,000 ppm, touch loses. Refuse if modeled risk at smallest representable width exceeds budget; never force a zero-width offer.',
    evidence='Previously inspected historical development. Original all-entry availability and twenty-target-expected-evaluated-wins screens unchanged. Parametric fit and 200 calibration references do not replace rare-event evidence. No live promotion.')


def guard(r):
    if r['adaptive_features'] is None:return 'missing_history'
    b=r.get('liquidity')
    if b is None:return 'missing_liquidity'
    if not 0<r['start']-b['received_at_ms']<=5000 or not -2000<=r['start']-b['exchange_at_ms']<=5000:return 'stale_liquidity'
    return veto(r,100,False)


def admissible(r):return guard(r) is None


def vector(r):
    a=r['activity_features'];f=r['adaptive_features'];b=r['liquidity']
    lv=math.log(max(.001,f['vol_60_ppm']));la=math.log1p(a['changes_30']);li=math.log1p(a['idle_ms']/1000)
    ld=math.log1p(min(b['top5_bid_usd'],b['top5_ask_usd'])/1000);ls=math.log1p(b['spread_bps'])
    hinges=[max(0,li-math.log1p(k)) for k in (1,3,10)]+[max(0,la-math.log1p(k)) for k in (4,11)]
    interactions=[lv*la,li*la,la*ls,la*ld,lv*ls,lv*ld,li*ls,li*ld,abs(b['values'][3])*li]
    values=base_vector(r)+hinges+interactions
    if not all(math.isfinite(x) for x in values):raise ValueError('Nonfinite joint entry feature')
    return values


def sigmoid(z):
    if z>=0:return 1/(1+math.exp(-min(745,z)))
    t=math.exp(max(-745,z));return t/(1+t)


def fit(rows,asset,cutoff):
    earlier=[r for r in training(rows,asset,cutoff) if admissible(r)];dates=sorted({r['period'] for r in earlier})[-10:];rows=[r for r in earlier if r['period'] in dates]
    if len(rows)<200 or len(dates)<5:raise ValueError('Insufficient joint fit support')
    w=weights(rows);raw=np.asarray([vector(r) for r in rows]);center=w@raw;sd=np.maximum(.1,np.sqrt(w@((raw-center)**2)));x=np.column_stack((np.ones(len(rows)),np.clip((raw-center)/sd,-5,5)))
    y0=np.asarray([r['move']==0 for r in rows],dtype=float);coef=logistic(x,w,y0,.0003)
    ids=[i for i,r in enumerate(rows) if r['move']>0];positive=[rows[i] for i in ids]
    if len(ids)<200 or len({r['period'] for r in positive})<5:raise ValueError('Insufficient joint positive-tail support')
    wp=weights(positive);xp=x[ids];y=np.asarray([math.log((r['move']+1)*1e9/r['entry']/(max(1.,r['adaptive_features']['vol_300_ppm'])*1000)) for r in positive])
    penalty=np.diag([1e-9]+[.01]*(x.shape[1]-1));tail=np.linalg.solve(xp.T@(wp[:,None]*xp)+penalty,xp.T@(wp*y));scale=max(.08,float(np.sqrt(wp@((y-xp@tail)**2)))*math.sqrt(3)/math.pi)
    probability=np.asarray([sigmoid(max(-30,min(30,float(v)))) for v in x@coef]);order=np.argsort(probability,kind='stable');cumulative=np.cumsum(w[order]);cumulative/=cumulative[-1]
    cuts=[float(probability[order[min(len(rows)-1,int(np.searchsorted(cumulative,q,side='left')))]]) for q in (.25,.5,.75)]
    return dict(asset=asset,cutoff=cutoff,training_dates=dates,rows=len(rows),positive_rows=len(ids),positive_dates=sorted({r['period'] for r in positive}),center=center.tolist(),sd=sd.tolist(),zero_coefficients=coef,tail_coefficients=tail.tolist(),tail_scale=scale,risk_cuts=cuts,numpy_version=np.__version__,spec=SPEC)


def forecast(r,model):
    if r['asset']!=model['asset']:raise ValueError('Wrong asset model')
    x=[1.]+[min(5,max(-5,(v-c)/s)) for v,c,s in zip(vector(r),model['center'],model['sd'])]
    p0=sigmoid(max(-30,min(30,sum(a*b for a,b in zip(x,model['zero_coefficients'])))))
    return dict(p0=p0,mu=sum(a*b for a,b in zip(x,model['tail_coefficients'])),scale=model['tail_scale'],bucket=bisect_right(model['risk_cuts'],p0))


def cdf(w,r,p):
    if w<=0:return 0.
    z=(math.log(w/(max(1.,r['adaptive_features']['vol_300_ppm'])*1000))-p['mu'])/p['scale']
    return p['p0']+(1-p['p0'])*sigmoid(z)


def reference(r,p):
    minimum=max(1,-(-10**9//r['entry']));required=max(1,-(-(r['move']+1)*10**9//r['entry']))
    return dict(asset=r['asset'],period=r['period'],start=r['start'],expiry=r['expiry'],weekend=weekend(r),bucket=p['bucket'],p0=p['p0'],admission=cdf(minimum,r,p),win_threshold=cdf(required,r,p) if required<=50000000 else None)


def levels(refs,asset,cutoff):
    if any(r['asset']!=asset or r['period']>=cutoff for r in refs) or len({r['start'] for r in refs})!=len(refs):raise ValueError('Future, cross-asset or duplicate joint reference')
    mature=[r for r in refs if r['expiry']+30000<origin(cutoff)];out={g:calibration(mature,1000,g,True) for g in ('global','weekday','weekend')}
    for bucket in range(4):
        part=[r for r in mature if r['bucket']==bucket]
        for g in ('global','weekday','weekend'):out[g+':risk'+str(bucket)]=calibration(part,1000,g,True)
    return out


def budget(r,p,packet,variant):
    if variant=='joint_raw' or p is None:return TARGET,'identity'
    g='weekend' if weekend(r) else 'weekday';b='risk'+str(p['bucket']);groups=([g+':'+b,'global:'+b] if variant=='joint_local' else [])+[g,'global']
    for key in groups:
        if packet['levels'][key]['supported']:return packet['levels'][key]['level'],key
    return TARGET,'identity'


def quote(r,variant,packet,p=None):
    why=guard(r);p=p if p is not None else forecast(r,packet['model']) if why is None else None;level,source=budget(r,p,packet,variant);width=None;q=None;probability=None
    if why is None:
        q=(level-p['p0'])/(1-p['p0']);minimum=max(1,-(-10**9//r['entry']))
        if not 0<q<1:why='predicted_flat_risk'
        elif cdf(minimum,r,p)>level:why='minimum_width_budget'
        else:
            log_width=math.log(max(1.,r['adaptive_features']['vol_300_ppm'])*1000)+p['mu']+p['scale']*math.log(q/(1-q));width=max(minimum,min(50000000,math.floor(math.exp(min(30,log_width)))))
            while width>minimum and cdf(width,r,p)>level+1e-12:width-=1
            probability=cdf(width,r,p)
            if probability>level+1e-10:why='native_width_budget'
    delta=r['entry']*width//10**9 if width is not None else None;shadow=r['move']<delta if r['valid'] and delta is not None else None
    return dict(width=width/1000 if width is not None else None,width_ppb=width,barrier_delta_units=delta,offered=why is None,reason=why or '',shadow=shadow,survived=shadow if why is None else None,
        p0=p['p0'] if p is not None else None,bucket=p['bucket'] if p is not None else None,level=level,calibration_source=source,positive_q=q,model_survival=probability,parametric=True,empirical_rare_tail_evidence=False)
