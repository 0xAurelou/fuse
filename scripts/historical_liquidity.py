"""Strict historical book joins and expanding-origin liquidity-effect models."""
from collections import Counter
from datetime import datetime,timezone
import gzip
import hashlib
import json
import math

import numpy as np

from liquidity_features import book_metrics
from oracle_gap_features import raw_timestamp
from payout_risk import clean_training, features, logistic, required_width, weights

VARIANTS=('activity','calendar','activity_liquidity','calendar_liquidity')
LIQUIDITY_NAMES=('log_spread','log_top5_bid','log_top5_ask','top5_imbalance','log_top20_bid','log_top20_ask')
SPEC=dict(version='historical-liquidity-effect-v1',warmup_dates=6,variants=VARIANTS,ridge=.003,
    book_freshness_ms=5000,exchange_future_tolerance_ms=2000,
    join='Latest native l2Book receipt strictly before the fixed UTC 30-second entry; five-second receipt and exchange freshness, never post-entry book. Disconnect markers clear both books.',
    book_features=LIQUIDITY_NAMES,
    depth='Native visible top5 and top20 bid/ask USD notional; no claim of full-band or whole-book depth. Require at least five visible levels on both sides.',
    primary='Paired equal-date zero-motion log-loss difference: calendar_liquidity versus calendar on exactly the same complete-case paths',
    secondary='Brier score, one-ppm-floor probability and past-defined depth tercile diagnostics. No quote-price or profitability claim.',
    fitting='Each asset separately; six full sampled days warm up, each later date scored once, all strictly earlier matured matched paths for coefficients and standardization. Equal date training mass, standardized clip +/-5.',
    uncertainty='Seeded 2000-resample day-block bootstrap of mean paired daily log-loss improvement. Descriptive monthly-development interval, not independent-trial confidence or causal identification.',
    depth_terciles='Weighted training-only terciles of log minimum top5 side notional; no current/future-label thresholds.',
    bootstrap_seed=20261029,bootstrap_replicates=2000,
    limitations='First-of-month development samples, previously inspected oracle outcomes, one venue/provider, limited weekend dates. Association and prediction only.',
    no_promotion=True)


def snapshot(state, start):
    if state is None:return None,'no_prior_book'
    received,data=state
    age=start-received;source=data.get('time')
    if not 0<age<=5000:return None,'stale_receipt'
    if isinstance(source,bool) or not isinstance(source,int) or not -2000<=start-source<=5000:
        return None,'stale_exchange_or_clock'
    if data.get('fast',False):raise ValueError('fastBook must not substitute for native 20-level history')
    try:
        b=book_metrics(data)
        if min(b['bid_levels'],b['ask_levels'])<5:return None,'insufficient_visible_levels'
        bid,ask=b['top5_bid_usd'],b['top5_ask_usd']
        values=[math.log1p(b['spread_bps']),math.log1p(bid/1000),math.log1p(ask/1000),
                (bid-ask)/(bid+ask),math.log1p(b['top20_bid_usd']/1000),math.log1p(b['top20_ask_usd']/1000)]
        if not all(math.isfinite(x) for x in values):raise ValueError('nonfinite book summary')
    except (ValueError,KeyError,TypeError):return None,'invalid_book'
    return dict(received_at_ms=received,exchange_at_ms=source,age_ms=age,
        source_payload_sha256=hashlib.sha256(json.dumps(data,sort_keys=True,separators=(',',':')).encode()).hexdigest(),
        spread_bps=b['spread_bps'],top5_bid_usd=bid,top5_ask_usd=ask,
        top20_bid_usd=b['top20_bid_usd'],top20_ask_usd=b['top20_ask_usd'],
        bid_levels=b['bid_levels'],ask_levels=b['ask_levels'],
        depth1=b['depth']['1'],depth5=b['depth']['5'],values=values),None


def join_day(root, files, day):
    start=int(datetime.fromisoformat(day).replace(tzinfo=timezone.utc).timestamp()*1000)
    end=start+86400000;entry=start;states={a:None for a in ('ETH','HYPE')}
    joined={a:[] for a in states};counts=Counter();previous=None
    def emit(at):
        for asset in states:
            value,reason=snapshot(states[asset],at)
            joined[asset].append(dict(asset=asset,period=day,start=at,liquidity=value,join_reason=reason))
            counts[asset+':'+(reason or 'joined')]+=1
    for item in sorted(files,key=lambda p:p['at_ms']):
        if item['day']!=day or item['status']!='downloaded':raise ValueError('wrong day or failed slice')
        with gzip.open(root/item['path'],'rt') as stream:
            for line in stream:
                if not line.strip():
                    states={a:None for a in states};counts['disconnect_markers']+=1;continue
                stamp,payload=line.rstrip('\n').split(' ',1);at=raw_timestamp(stamp)
                if not item['at_ms']<=at<item['at_ms']+item['duration_ms'] or previous is not None and at<previous:
                    raise ValueError('raw book receipt is outside slice or regresses')
                previous=at
                while entry<=at and entry<end:emit(entry);entry+=30000
                value=json.loads(payload)
                if value['channel']!='l2Book' or value['data']['coin'] not in states:
                    raise ValueError('unexpected raw book channel/asset')
                asset=value['data']['coin'];data=value['data'];counts[asset+':messages']+=1
                if states[asset] and data['time']<states[asset][1]['time']:
                    states[asset]=None;counts[asset+':regressing_exchange_resets']+=1
                else:states[asset]=(at,data)
    while entry<end:emit(entry);entry+=30000
    if any(len(v)!=2880 for v in joined.values()):raise ValueError('entry grid differs')
    return joined,dict(counts)


def vector(row, variant):
    if variant not in VARIANTS:raise ValueError('unknown paired variant')
    out=features(row,'calendar' if variant.startswith('calendar') else 'timing')
    if variant.endswith('_liquidity'):
        if row.get('liquidity') is None:raise ValueError('matched liquidity required')
        out+=row['liquidity']['values']
    return out


def fit(rows,asset,cutoff,variant):
    rows=clean_training(rows,asset,cutoff)
    if any(r.get('liquidity') is None for r in rows):raise ValueError('same matched cohort required')
    w=weights(rows);raw=np.asarray([vector(r,variant) for r in rows]);center=w@raw
    sd=np.maximum(.1,np.sqrt(w@((raw-center)**2)))
    x=np.column_stack((np.ones(len(rows)),np.clip((raw-center)/sd,-5,5)))
    y0=np.asarray([r['move']==0 for r in rows],dtype=float)
    yf=np.asarray([required_width(r)<=1 for r in rows],dtype=float)
    zero=logistic(x,w,y0,.003);floor=zero if np.array_equal(y0,yf) else logistic(x,w,yf,.003)
    return dict(asset=asset,cutoff=cutoff,variant=variant,training_dates=sorted({r['period'] for r in rows}),
        rows=len(rows),center=center.tolist(),sd=sd.tolist(),zero_coefficients=zero,floor_coefficients=floor,
        spec=SPEC)


def predict(row,model):
    x=[1.]+[max(-5,min(5,(v-m)/s)) for v,m,s in zip(vector(row,model['variant']),model['center'],model['sd'])]
    p=[1/(1+math.exp(-max(-30,min(30,sum(a*b for a,b in zip(x,model[k])))))) for k in ('zero_coefficients','floor_coefficients')]
    return dict(p0=p[0],floor=max(p))


def weighted_terciles(rows):
    w=weights(rows);pairs=sorted((math.log1p(min(r['liquidity']['top5_bid_usd'],r['liquidity']['top5_ask_usd'])/1000),float(a)) for r,a in zip(rows,w))
    values=np.asarray([v for v,w in pairs]);cdf=np.cumsum([w for v,w in pairs]);cdf/=cdf[-1]
    return [float(values[min(len(values)-1,int(np.searchsorted(cdf,q)))]) for q in (1/3,2/3)]


def depth_group(row,edges):
    value=math.log1p(min(row['liquidity']['top5_bid_usd'],row['liquidity']['top5_ask_usd'])/1000)
    return ('low','middle','high')[sum(value>edge for edge in edges)]


def loss(y,p):
    p=max(1e-12,min(1-1e-12,p))
    return -y*math.log(p)-(1-y)*math.log(1-p)


def summarize(rows,predictions):
    n=len(rows)
    if n!=len(predictions):raise ValueError('paired population differs')
    out=dict(n=n,dates=sorted({r['period'] for r in rows}))
    for head,label in (('p0',lambda r:r['move']==0),('floor',lambda r:required_width(r)<=1)):
        ys=[int(label(r)) for r in rows];ps=[p[head] for p in predictions]
        out[head]=dict(observed=sum(ys)/n if n else None,predicted=sum(ps)/n if n else None,
            wins=sum(ys),log_loss=sum(loss(y,p) for y,p in zip(ys,ps))/n if n else None,
            brier=sum((y-p)**2 for y,p in zip(ys,ps))/n if n else None)
    return out


def paired_result(daily, baseline='calendar', augmented='calendar_liquidity', head='p0'):
    differences=[v[baseline][head]['log_loss']-v[augmented][head]['log_loss'] for v in daily.values()]
    if not differences:return dict(dates=0,mean_improvement=None,bootstrap_interval=None)
    rng=np.random.default_rng(SPEC['bootstrap_seed']);a=np.asarray(differences)
    boot=np.mean(a[rng.integers(0,len(a),size=(SPEC['bootstrap_replicates'],len(a)))],axis=1)
    lo,hi=np.quantile(boot,[.025,.975])
    return dict(dates=len(a),baseline=baseline,augmented=augmented,head=head,
        mean_improvement=float(np.mean(a)),bootstrap_interval=[float(lo),float(hi)],
        improved_dates=sum(v>0 for v in differences),daily_improvements=dict(zip(daily,differences)),
        interpretation='Positive improvement means lower augmented-model loss. Day-block development diagnostic, not a causal or prospective finding.')
