"""Separate flat-event mass from positive movement, with a pre-entry freeze veto."""
from bisect import bisect_right
from collections import Counter

from payout_empirical import EmpiricalPredictor,distribution
from payout_risk import required_width,weekend
from trial_payout import available,quote as original_quote

VARIANTS=('previous_formula','flat_veto','activity_hurdle','calendar_hurdle')
SPEC=dict(version='flat-aware-payout-v1',variants=VARIANTS,primary='calendar_hurdle',
    idle_edges_ms=[1500,3000,10000,30000,60000],change_edges=[1,4,11],
    floor='Two date-balanced empirical heads for zero motion and survival at the one-ppm minimum; global -> changes30 -> changes30/idle -> optional UTC weekend. Each child shrinks toward its parent with mass 32 and a half-event; unsupported leaves fall back to the parent.',
    minimum_cell_paths=200,minimum_cell_dates=3,parent_mass=32,half_event=.5,
    veto='No quote when pre-entry idle age is at least the 30-second horizon, no price change occurred in the last 30 seconds, or idle age is only a lower bound. Applies regardless of fitted probability.',
    recovery='New hurdle models at 1000x additionally require at least four preceding 30-second changes and a last price change less than three seconds before entry. Fixed before replay; no outcome-selected thresholds.',
    movement='Date-weighted positive required-width CDF, same slow-volatility anchor and parent mass/support as previous formula. Local positive CDF groups match the hurdle activity/idle cells, optionally split by UTC weekend.',
    width='q_plus=(.95/M-p_min)/(1-p_min); inverse positive CDF, integer ppm in [1,50000]. Refuse when floor exceeds target or positive-tail training support is below twenty.',
    fitting='Separate assets; all strictly earlier matured matched paths only. Older monthly out-of-sample comparisons and September trial results reported separately. No variant selection or threshold tuning from either replay.',
    evidence='Previously inspected historical development; zero quotes do not demonstrate successful pricing. Same availability and rare-event screens as before; no live promotion.')


def change_key(row):return str(bisect_right(SPEC['change_edges'],row['activity_features']['changes_30']))


def activity_key(row):
    return change_key(row)+':'+str(bisect_right(SPEC['idle_edges_ms'],row['activity_features']['idle_ms']))


def cell_key(row,calendar=False):
    return activity_key(row)+(':'+str(int(weekend(row))) if calendar else '')


def cell(rows,parent=None):
    counts=Counter(r['period'] for r in rows);n=len(rows);supported=n>=200 and len(counts)>=3
    rates={field:sum(label(r)/counts[r['period']] for r in rows)/len(counts) if counts else None
           for field,label in (('p0',lambda r:r['move']==0),('floor',lambda r:required_width(r)<=1))}
    if parent is None:
        if not n:raise ValueError('Nonempty asset training set required')
        values={f:(n*rates[f]+.5)/(n+1) for f in rates}
    else:
        values={f:(n*rates[f]+32*parent[f]+.5)/(n+33) if supported else parent[f] for f in rates}
    return dict(n=n,dates=sorted(counts),supported=supported,rates=rates,**values)


def fit_floor(rows,asset,cutoff):
    from research_trial_liquidity import training
    rows=training(rows,asset,cutoff);global_cell=cell(rows);changes={};activity={};calendar={}
    for fn,target,parent in ((change_key,changes,lambda r:global_cell),
                             (activity_key,activity,lambda r:changes[change_key(r)]),
                             (lambda r:cell_key(r,True),calendar,lambda r:activity[activity_key(r)])):
        groups={}
        for r in rows:groups.setdefault(fn(r),[]).append(r)
        for k,part in sorted(groups.items()):target[k]=cell(part,parent(part[0]))
    return dict(asset=asset,cutoff=cutoff,training_dates=sorted({r['period'] for r in rows}),
        rows=len(rows),global_cell=global_cell,changes=changes,activity=activity,calendar=calendar,spec=SPEC)


def floor_forecast(row,model,calendar=False):
    value=model['global_cell'];value=model['changes'].get(change_key(row),value)
    value=model['activity'].get(activity_key(row),value)
    if calendar:value=model['calendar'].get(cell_key(row,True),value)
    return dict(p0=value['p0'],floor=max(value['p0'],value['floor']),calibrated0=False,calibrated_floor=False)


def movement(rows,asset,cutoff,mode):
    from research_trial_liquidity import training
    rows=training(rows,asset,cutoff);groups={}
    for r in rows:
        k=r['activity_state'] if mode=='previous' else cell_key(r,mode=='calendar')
        groups.setdefault(k,[]).append(r)
    return dict(asset=asset,cutoff=cutoff,training_dates=sorted({r['period'] for r in rows}),
        anchors={'slow':dict(global_distribution=distribution(rows,'slow'),families={'activity':{k:distribution(v,'slow') for k,v in sorted(groups.items())}})})


def veto(row,multiplier,recovery=False):
    a=row['activity_features']
    if a['idle_is_lower_bound'] or a['idle_ms']>=30000 or a['changes_30']==0:return 'flat_oracle_veto'
    if recovery and multiplier==1000 and (a['idle_ms']>=3000 or a['changes_30']<4):return 'insufficient_recent_oracle_activity'
    return None


def build_predictors(packet):return {k:EmpiricalPredictor(v) for k,v in packet['movement'].items()}


def quote(row,multiplier,variant,packet,predictors,baseline_forecast):
    forecast=baseline_forecast;modified=row;mode='previous';reason=None
    supported=available(row,'calendar_liquidity')
    if variant in ('activity_hurdle','calendar_hurdle'):
        mode='calendar' if variant=='calendar_hurdle' else 'activity'
        forecast=floor_forecast(row,packet['floor'],mode=='calendar') if supported else dict(p0=None,floor=None,calibrated0=False,calibrated_floor=False)
        if supported:modified=dict(row,activity_state=cell_key(row,mode=='calendar'))
    p=original_quote(modified,forecast,multiplier,'calendar_liquidity_raw_cdf',predictors[mode])
    if variant!='previous_formula' and supported:reason=veto(row,multiplier,variant in ('activity_hurdle','calendar_hurdle'))
    if reason:
        p=dict(p,offered=False,survived=None,reason=';'.join(filter(None,(p['reason'],reason))))
    return dict(p,flat_guard=reason,estimated_zero_probability=forecast['p0'],estimated_minimum_probability=forecast['floor'])
