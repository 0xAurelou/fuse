"""Fixed 100x/1000x corridor quotes and complete-denominator replay metrics."""
from collections import Counter
import math

from payout_empirical import calibrated,distribution,fit_calibrator,key
from payout_walkforward import quote as empirical_quote
from research_trial_liquidity import training
from screen_payout_candidates import assess,CRITERIA

RISKS=('activity','calendar','activity_liquidity','calendar_liquidity')
VARIANTS=('shipped_formula','minimum_width_floor')+tuple(f'{f}_{mode}_cdf' for f in RISKS for mode in ('raw','cal32'))
MULTIPLIERS=(100,1000)
SPEC=dict(version='consecutive-payout-v1',dates='September 1–10 2026 UTC',multipliers=MULTIPLIERS,
    variants=VARIANTS,primary=['calendar_raw_cdf','calendar_liquidity_raw_cdf'],
    target_edge=.05,shipped_volatility_30s_ppm=dict(ETH=1500,HYPE=3000),
    fitting='Reuse the audited earlier-only daily risk models; fit positive movement CDF and prior-32 calibration separately at every daily origin from strictly earlier matured data. No trial-result model selection.',
    calibration_warmup='Earlier audited monthly out-of-sample raw risk forecasts July 2025 through August 2026, then only matured prior trial forecasts. No in-sample or own-date references.',
    quote='Existing empirical positive CDF, slow volatility anchor, activity grouping, level and gate factors 1; twenty positive-tail references required. Integer research widths 1–50000 ppm. Shipped formula retains exact integer ppb quantization.',
    cohorts='Primary identical clean oracle paths with strictly prior fresh native book; secondary all clean oracle paths. Missing liquidity is a refusal, never removed from the all-clean availability denominator. All grid pre-entry decisions retained.',
    common_gate='All variants require existing five-minute pre-entry research history; this is a formula/path replay, not production canonical-health or underwriting simulation.',
    settlement='Full 30-second observed oracle path; integer symmetric barriers; equality at either barrier loses. Original gaps remain unresolved. M includes returned stake.',
    gross='One stake unit per accepted resolved quote. LP gross = quotes minus M times trader wins; excludes fees, funding, hedging, capital and concurrent liability limits.',
    screen=CRITERIA,historical_development=True,no_promotion=True)


def brownian_width(vol,multiplier,edge=500):
    """Exact positive-integer port of engine/internal/engine/pricing.go."""
    q=10**12;pi=3141592653590;ln2=693147180560
    x=(4*multiplier*q*q)//(pi*(10000-edge)//10000);powers=0
    while x>=2*q:x//=2;powers+=1
    z=(x-q)*q//(x+q);z2=z*z//q;term=z;total=z
    for n in range(3,64,2):term=term*z2//q;total+=term//n
    logarithm=2*total+powers*ln2
    return vol*1000*pi//math.isqrt(8*logarithm*q)


def shipped_width(asset,multiplier):
    return brownian_width(SPEC['shipped_volatility_30s_ppm'][asset],multiplier)


def available(row,family):
    return row['adaptive_features'] is not None and (not family.endswith('_liquidity') or row.get('liquidity') is not None)


def origin_packet(rows,asset,day,risk_packet,references,risk_binding):
    clean=training(rows,asset,day);dates=sorted({r['period'] for r in clean})
    if risk_packet['asset']!=asset or risk_packet['cutoff']!=day:raise ValueError('Wrong risk origin')
    for f in RISKS:
        model=risk_packet['models'][f]
        if model['training_dates']!=dates or model['rows']!=len(clean):raise ValueError('Risk and movement training cohorts differ')
    groups={}
    for r in clean:groups.setdefault(key(r,'activity'),[]).append(r)
    movement=dict(asset=asset,cutoff=day,training_dates=dates,anchors={'slow':dict(
        global_distribution=distribution(clean,'slow'),families={'activity':{k:distribution(v,'slow') for k,v in sorted(groups.items())}})})
    if movement['anchors']['slow']['global_distribution']['n']<100:raise ValueError('Too few positive movement references')
    from fetch_tardis_liquidity_trial import origin
    boundary=origin(day);earlier={}
    for f in RISKS:
        refs=references[f]
        if len({r['start'] for r in refs})!=len(refs) or any(r['asset']!=asset or r['period']>=day for r in refs):raise ValueError('Calibration identity or future contamination')
        earlier[f]=[r for r in refs if r['expiry']+30000<boundary]
    return dict(asset=asset,cutoff=day,risk=risk_packet['models'],risk_binding=risk_binding,movement=movement,
        calibrators={f:fit_calibrator(earlier[f],32) for f in RISKS},
        calibration_counts={f:len(earlier[f]) for f in RISKS},spec=SPEC)


def forecasts(row,packet,predictor):
    raw={f:predictor(row,packet['risk'][f]) if available(row,f) else dict(p0=None,floor=None) for f in RISKS}
    values={}
    for f in RISKS:
        values[f+'_raw_cdf']=dict(raw[f],calibrated0=False,calibrated_floor=False)
        values[f+'_cal32_cdf']=calibrated((raw[f]['p0'],raw[f]['floor']),packet['calibrators'][f])
    return raw,values


def quote(row,forecast,multiplier,variant,predictor):
    if variant=='shipped_formula':
        width=shipped_width(row['asset'],multiplier) if row['adaptive_features'] is not None else None
        delta=row['entry']*width//10**9 if width is not None else None
        reason='missing_history' if width is None else 'unrepresentable_barrier' if delta<=0 else ''
        shadow=row['move']<delta if row['valid'] and delta is not None else None
        return dict(width=width/1000 if width is not None else None,width_ppb=width,barrier_delta_units=delta,
            offered=not reason,reason=reason,positive_q=None,tail_mass=None,tail_supported=None,child_supported=None,
            p0=None,floor=None,calibrated0=False,calibrated_floor=False,shadow=shadow,survived=shadow if not reason else None)
    p=empirical_quote(row,forecast,multiplier,variant,predictor)
    if '_liquidity_' in variant and row['adaptive_features'] is not None and row.get('liquidity') is None:p['reason']='missing_liquidity'
    return dict(p,width_ppb=p['width']*1000 if p['width'] is not None else None,
        barrier_delta_units=row['entry']*p['width']//1000000 if p['width'] is not None else None)


def clean(row):return row['valid'] and row['adaptive_features'] is not None


def summary(rows,records,multiplier):
    if len(rows)!=len(records):raise ValueError('Replay population differs')
    eligible=[(r,p) for r,p in zip(rows,records) if clean(r)]
    offered=[(r,p) for r,p in eligible if p['offered'] and p['shadow'] is not None]
    n=len(eligible);k=len(offered);wins=sum(p['shadow'] for r,p in offered)
    return dict(grid=len(rows),eligible=n,pre_entry_predictions=sum(p['width'] is not None for p in records),
        pre_entry_offered=sum(p['offered'] for p in records),unresolved_offered=sum(p['offered'] and not clean(r) for r,p in zip(rows,records)),
        offered=k,wins=wins,availability=k/n if n else None,survival=wins/k if k else None,
        target=.95/multiplier,break_even=1/multiplier,target_expected_wins=k*.95/multiplier,
        gross_lp_stake_units=k-multiplier*wins,gross_lp_per_stake=1-multiplier*wins/k if k else None,
        mean_width_ppm=sum(p['width'] for r,p in offered)/k if k else None,
        zero_motion_wins=sum(r['move']==0 and p['shadow'] for r,p in offered),
        refusals=dict(Counter(p['reason'] for r,p in eligible if not p['offered'])))


def metrics(rows,records,multiplier):
    pooled=summary(rows,records,multiplier);daily=[]
    for day in sorted({r['period'] for r in rows}):
        pairs=[(r,p) for r,p in zip(rows,records) if r['period']==day]
        daily.append(dict(period=day,**summary([r for r,p in pairs],[p for r,p in pairs],multiplier)))
    return dict(pooled=pooled,daily=daily,minimum_daily_availability=min((d['availability'] or 0 for d in daily),default=0))


def screen(result,multiplier,variant):
    p=result['pooled'];candidate=dict(policy={'name':variant},index=VARIANTS.index(variant),daily=result['daily'],
        minimum_daily_availability=result['minimum_daily_availability'],pooled_survival=p['survival'],
        availability=p['availability'],offered=p['offered'],eligible=p['eligible'])
    checked=assess(candidate,multiplier)
    if variant=='minimum_width_floor':checked['reasons'].append('lower_bound_diagnostic_only');checked['eligible']=False
    return dict(qualifies=checked['eligible'],reasons=checked['reasons'],no_promotion=True)
