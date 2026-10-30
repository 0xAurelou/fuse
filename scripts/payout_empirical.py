"""Chronological score calibration and empirical conditional movement tails."""
from bisect import bisect_left, bisect_right
from collections import Counter
import math

import numpy as np

from payout_risk import clean_training, fit_risk, required_width, risk, weights

EDGES = (0., .0005, .002, .01, .05, .2, 1.)
PRIORS = (32, 128)
FAMILIES = ('activity', 'idle_changes')
ANCHORS = ('slow', 'blend')
LEVEL_FACTORS = (.5, .75, 1.)
GATE_FACTORS = (.5, 1.)
SPEC = dict(version='empirical-payout-v1', score_edges=EDGES, calibration_priors=PRIORS,
            calibration_minimum=200, calibration_minimum_dates=3, beta_half_event=.5,
            calibration='Equal date mass within score bin, shrink toward mean OOF forecast plus a half event; weighted monotone pooling across supported bins. Unsupported bins retain raw risk.',
            oof='Frozen preceding template family/ridge; coefficients fit on first 6/9/12 permitted dates and score next 3/3/2 training dates. No own/future-date labels enter those coefficients.',
            width_families=FAMILIES, anchors=ANCHORS, movement_parent_mass=200,
            movement_minimum=200, movement_minimum_dates=3,
            movement='Exact weighted empirical positive CDFs; equal date mass, shrunk toward global positive CDF; no quantile interpolation or smoothed IRLS',
            level_factors=LEVEL_FACTORS, gate_factors=GATE_FACTORS,
            support='Global positive training count times requested positive quantile >=20; not local confidence or independent events',
            minimum_width_ppm=1, maximum_width_ppm=50000,
            selection='Pooled relative error + .25 mean daily relative error + 5 mean lost availability + 20 shortfall below .85 worst-day availability + 2 full-reference width-loss deterioration above 10%. Empty quoted day adds 1000.',
            selection_dates='January-May 2026; repeatedly inspected development dates',
            later_dates='June-October 2026; already inspected development diagnostics',
            guarantee='No independent holdout, conditional calibration or profitability guarantee')


def bin_index(p):
    return min(len(EDGES)-2, max(0, bisect_right(EDGES, p)-1))


def pava(values, masses):
    blocks = []
    for i, (value, mass) in enumerate(zip(values, masses)):
        blocks.append([i, i+1, value*mass, mass])
        while len(blocks) >= 2 and blocks[-2][2]/blocks[-2][3] > blocks[-1][2]/blocks[-1][3]:
            b = blocks.pop(); a = blocks.pop()
            blocks.append([a[0], b[1], a[2]+b[2], a[3]+b[3]])
    result = [0.]*len(values)
    for left, right, total, mass in blocks:
        result[left:right] = [total/mass]*(right-left)
    return result


def out_of_fold(rows, template):
    train = [r for r in rows if r['split'] == 'train']
    dates = sorted({r['period'] for r in train})
    models, records = {}, []
    for begin, finish in ((6,9), (9,12), (12,14)):
        if begin >= len(dates):
            continue
        earlier = [r for r in train if r['period'] in dates[:begin]]
        later = [r for r in train if r['period'] in dates[begin:finish]]
        cutoff = dates[begin]
        model = fit_risk(earlier, template['asset'], cutoff, template['family'], template['ridge'])
        models[str(begin)] = model
        for r in later:
            if not r['valid'] or r['adaptive_features'] is None:
                continue
            p0, pf = risk(r, model)
            records.append(dict(start=r['start'], period=r['period'], expiry=r['expiry'],
                                fold=begin, p0=p0, floor=pf, zero=r['move'] == 0,
                                minimum=required_width(r) <= 1))
    if len(records) < 100:
        raise ValueError('insufficient chronological calibration references')
    return models, records


def fit_calibrator(records, prior):
    if prior not in PRIORS:
        raise ValueError('undeclared calibration prior')
    heads = {}
    for field, label in (('p0','zero'), ('floor','minimum')):
        bins = []
        for i in range(len(EDGES)-1):
            part = [p for p in records if bin_index(p[field]) == i]
            counts = Counter(p['period'] for p in part)
            supported = len(part) >= 200 and len(counts) >= 3
            if part:
                w = [1/counts[p['period']] for p in part]; total = sum(w)
                rate = sum(a*p[label] for a,p in zip(w,part))/total
                mean = sum(a*p[field] for a,p in zip(w,part))/total
                mass = len(part)+prior+1
                probability = (len(part)*rate+prior*mean+.5)/mass
            else:
                rate = mean = probability = None; mass = prior+1
            bins.append(dict(left=EDGES[i], right=EDGES[i+1], n=len(part), dates=sorted(counts),
                             supported=supported, observed=rate, raw_mean=mean,
                             mass=mass, unpooled_probability=probability, probability=probability))
        indexes = [i for i,b in enumerate(bins) if b['supported']]
        fitted = pava([bins[i]['probability'] for i in indexes], [bins[i]['mass'] for i in indexes])
        for i, probability in zip(indexes, fitted):
            bins[i]['probability'] = probability
        heads[field] = bins
    return dict(prior=prior, edges=EDGES, heads=heads, records=len(records),
                periods=sorted({p['period'] for p in records}), spec=SPEC)


def calibrated(raw, model):
    if raw[0] is None:
        return dict(p0=None, floor=None, calibrated0=False, calibrated_floor=False)
    result = []
    supported = []
    for value, field in zip(raw, ('p0','floor')):
        leaf = model['heads'][field][bin_index(value)]
        result.append(leaf['probability'] if leaf['supported'] else value)
        supported.append(leaf['supported'])
    return dict(p0=result[0], floor=max(result), calibrated0=supported[0], calibrated_floor=supported[1])


def anchor(row, method):
    f = row['adaptive_features']
    return max(1., f['vol_300_ppm'] if method == 'slow' else .5*(f['vol_60_ppm']+f['vol_300_ppm']))


def key(row, family):
    if family == 'activity':
        return row['activity_state']
    if family != 'idle_changes':
        raise ValueError('undeclared movement family')
    a = row['activity_features']
    idle = bisect_right((1500,3000,10000,30000), a['idle_ms'])
    changes = bisect_right((1,4,11), a['changes_30'])
    return f'idle{idle}:changes{changes}'


def distribution(rows, method):
    positive = [r for r in rows if required_width(r) > 1]
    if not positive:
        return dict(n=0, dates=[], value=[], weight=[])
    w = weights(positive)
    pairs = sorted((required_width(r)/anchor(r,method), float(a)) for r,a in zip(positive,w))
    return dict(n=len(positive), dates=sorted({r['period'] for r in positive}),
                value=[p[0] for p in pairs], weight=[p[1] for p in pairs])


def fit_movement(rows, asset):
    rows = clean_training([r for r in rows if r['split'] == 'train'], asset, '2026-01-01')
    result = dict(asset=asset, cutoff='2026-01-01', training_dates=sorted({r['period'] for r in rows}), anchors={})
    for method in ANCHORS:
        global_dist = distribution(rows,method)
        if global_dist['n'] < 100:
            raise ValueError('at least 100 positive-width training references required')
        families = {}
        for family in FAMILIES:
            groups = {}
            for r in rows:
                groups.setdefault(key(r,family), []).append(r)
            families[family] = {name:distribution(part,method) for name,part in sorted(groups.items())}
        result['anchors'][method] = dict(global_distribution=global_dist, families=families)
    return result


class EmpiricalPredictor:
    def __init__(self, model):
        self.model = model
        self.cache = {}

    def merged(self, row, family, method):
        name = key(row,family)
        cache_key = (family,method,name)
        if cache_key in self.cache:
            return self.cache[cache_key]
        source = self.model['anchors'][method]
        parent = source['global_distribution']
        child = source['families'][family].get(name)
        supported = child is not None and child['n'] >= 200 and len(child['dates']) >= 3
        blend = child['n']/(child['n']+200) if supported else 0.
        values = np.asarray(parent['value']+(child['value'] if blend else []))
        mass = np.asarray([(1-blend)*v for v in parent['weight']]+([blend*v for v in child['weight']] if blend else []))
        indexes = np.argsort(values,kind='stable')
        cumulative = np.cumsum(mass[indexes]); cumulative /= cumulative[-1]
        result = (values[indexes], cumulative, parent['n'], supported)
        self.cache[cache_key] = result
        return result

    def quote(self, row, forecast, multiplier, family, method, level_factor, gate_factor):
        target = .95/multiplier
        floor = forecast['floor']
        if floor is None:
            return dict(width=None, offered=False, reason='missing_history', positive_q=None,
                        tail_mass=0., tail_supported=False, child_supported=False)
        q = (level_factor*target-floor)/max(1e-12,1-floor)
        values, cumulative, n, child = self.merged(row,family,method)
        tail_mass = n*max(0,q)
        supported = q > 0 and q < 1 and tail_mass >= 20
        if q <= 0:
            width = 1
        else:
            index = min(len(values)-1,int(np.searchsorted(cumulative,q,side='left')))
            width = max(2,min(50000,math.ceil(anchor(row,method)*float(values[index]))))
        reasons = []
        if floor > gate_factor*level_factor*target:
            reasons.append('predicted_minimum_width_risk')
        if not supported:
            reasons.append('insufficient_positive_tail_support')
        if row['entry'] is not None and row['entry']*width//1000000 <= 0:
            reasons.append('unrepresentable_barrier')
        return dict(width=width,offered=not reasons,reason=';'.join(reasons),positive_q=q,
                    tail_mass=tail_mass,tail_supported=supported,child_supported=child)


CONTROLS = ('parent_open','v1_parent_gate100','v1_conditional_gate100',
            'idle3_parent','idle10_parent','idle30_parent','changes3_parent',
            'calibrated32_parent','calibrated128_parent')


def policies():
    result = [dict(name=n,kind='control') for n in CONTROLS]
    for prior in PRIORS:
        for family in FAMILIES:
            for method in ANCHORS:
                for level in LEVEL_FACTORS:
                    for gate in GATE_FACTORS:
                        result.append(dict(name=f'cdf:{prior}:{family}:{method}:q{level}:g{gate}',kind='empirical',
                                           prior=prior,family=family,anchor=method,level=level,gate=gate))
    return result


def entry(row, multiplier, policy, raw, forecasts, parent_width, v1_conditional, predictor):
    name = policy['name']; target=.95/multiplier
    forecast = forecasts[policy['prior']] if policy['kind'] == 'empirical' else None
    if name in ('calibrated32_parent','calibrated128_parent'):
        forecast = forecasts[32 if name=='calibrated32_parent' else 128]
    if forecast is None:
        forecast=dict(p0=raw[0],floor=raw[1],calibrated0=False,calibrated_floor=False)
    if policy['kind'] == 'empirical':
        result = predictor.quote(row,forecast,multiplier,policy['family'],policy['anchor'],policy['level'],policy['gate'])
    else:
        width = v1_conditional['width'] if name=='v1_conditional_gate100' else parent_width
        reasons=[]
        if width is None:reasons.append('missing_history')
        if width is not None:
            if name in ('v1_parent_gate100','v1_conditional_gate100','calibrated32_parent','calibrated128_parent') and forecast['floor'] > target:
                reasons.append('predicted_minimum_width_risk')
            if name=='v1_conditional_gate100' and not v1_conditional['supported']:
                reasons.append('insufficient_positive_tail_support')
            idle_limit={'idle3_parent':3000,'idle10_parent':10000,'idle30_parent':30000}.get(name)
            if idle_limit is not None and row['activity_features']['idle_ms'] >= idle_limit:
                reasons.append('preentry_idle_control')
            if name=='changes3_parent' and row['activity_features']['changes_30'] < 3:
                reasons.append('preentry_changes_control')
            if row['entry'] is not None and row['entry']*width//1000000 <= 0:
                reasons.append('unrepresentable_barrier')
        result = dict(width=width,offered=not reasons,reason=';'.join(reasons),positive_q=None,
                      tail_mass=None,tail_supported=None,child_supported=None)
    # Labels are calculated after the entry decision and never change it.
    width = result['width']
    shadow = row['move'] < row['entry']*width//1000000 if row['valid'] and width is not None else None
    result.update(p0=forecast['p0'],floor=forecast['floor'],calibrated0=forecast['calibrated0'],
                  calibrated_floor=forecast['calibrated_floor'],shadow=shadow,
                  survived=shadow if result['offered'] else None)
    return result


def selection_score(rows, records, multiplier, baseline_loss):
    target=.95/multiplier
    daily=[]; n=k=wins=0; loss=0.; denominator=0
    for day in sorted({r['period'] for r in rows}):
        part=[p for r,p in zip(rows,records) if r['period']==day and p['shadow'] is not None]
        kept=[p for p in part if p['offered']]
        if not part:raise ValueError('empty eligible validation day')
        daily.append(dict(day=day,availability=len(kept)/len(part),eligible=len(part),offered=len(kept),
                          wins=sum(p['survived'] for p in kept),
                          relative_error=abs(sum(p['survived'] for p in kept)/len(kept)/target-1) if kept else None))
        n+=len(part);k+=len(kept);wins+=sum(p['survived'] for p in kept)
    for r,p in zip(rows,records):
        if p['shadow'] is None:continue
        residual=required_width(r)-p['width'];loss+=target*residual if residual>=0 else (target-1)*residual;denominator+=1
    loss/=denominator
    minimum=min(d['availability'] for d in daily)
    empty=sum(d['offered']==0 for d in daily)
    relative=abs(wins/k/target-1) if k else 1000.
    error=sum(d['relative_error'] if d['relative_error'] is not None else 1000 for d in daily)/len(daily)
    availability=sum(d['availability'] for d in daily)/len(daily)
    guard=2*max(0,loss/baseline_loss-1.1) if baseline_loss else 0.
    score=relative+.25*error+5*(1-availability)+20*max(0,.85-minimum)+1000*empty+guard
    return dict(score=score,daily=daily,pooled_survival=wins/k if k else None,
                eligible=n,offered=k,wins=wins,availability=k/n if n else None,
                minimum_daily_availability=minimum,full_reference_pinball_ppm=loss,
                loss_guard=guard,meets_availability_reference=minimum>=.85,
                target_expected_wins=k*target,adequate_expected_wins=k*target>=20)
