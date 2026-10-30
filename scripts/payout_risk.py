"""Past-only all-state flat-risk and payout-specific lower-tail corridor model.

Historical research only. Width, admission and probability forecasts never read
the current outcome. Even refused external reference paths teach the delayed
calibrator; changing admission cannot improve its information set.
"""
from collections import deque
from datetime import datetime, timezone
import math

import numpy as np

FAMILIES = ('timing', 'calendar', 'market_calendar')
RIDGES = (.0001, .003)
LEVELS = (.0001, .0003, .001, .003, .01, .03, .1, .3, .5, .8)
TIMING = ('log_idle', 'log_changes30', 'log_changes60', 'log_changes300',
          'empty_bins', 'variance_concentration', 'log_slow_vol', 'fast_slow',
          'signed_drift', 'directional_strength', 'idle_cooling', 'idle_lower_bound')
CALENDAR = ('weekend_utc', 'hour_sin_utc', 'hour_cos_utc')
MARKET = ('signed_mark_gap', 'absolute_mark_gap', 'gap_change30', 'mark_move30',
          'absolute_mark_move30', 'missing_fresh_context')
SPEC = dict(version='payout-flat-risk-v1', families=FAMILIES, ridges=RIDGES,
            positive_levels=LEVELS, positive_ridge=.001, quantile_huber=.05,
            logistic_steps=40, quantile_steps=50, standardized_clip=5,
            minimum_width_ppm=1, maximum_width_ppm=50000, positive_training='All permitted positive-width references, with equal date weights',
            online_memory=240, online_max_age_ms=14400000, online_prior_events=1.,
            online_odds_bounds=[.1, 10.], maturity_delay_ms=30000,
            selection='Static zero-motion and one-ppm-floor mean daily log loss on January-May 2026; equal label weights. Candidate order breaks exact ties.',
            support='At least 20 global weighted positive-tail training references; this is a descriptive support screen, not conditional confidence or independent events.',
            guarantee='No conditional probability, profitability or future availability guarantee')
GATES = (('25', .25), ('50', .5), ('100', 1.))
VARIANTS = (('parent_open', 'parent', False, None, False),
            ('parent_weekdays', 'parent', False, None, True)) + tuple(
    (f'parent_{mode}_gate{name}', 'parent', online, fraction, False)
    for mode, online in (('static', False), ('online', True)) for name, fraction in GATES) + tuple(
    (f'conditional_{mode}_{name}', 'conditional', online, fraction, False)
    for mode, online in (('static', False), ('online', True))
    for name, fraction in (('open', None),) + tuple(('gate'+n, f) for n, f in GATES))


def required_width(row):
    return ((row['move'] + 1)*1000000 + row['entry'] - 1)//row['entry']


def weekend(row):
    return datetime.fromtimestamp(row['start']/1000, timezone.utc).weekday() >= 5


def feature_names(family):
    if family not in FAMILIES:
        raise ValueError('unknown feature family')
    return TIMING + (CALENDAR if family != 'timing' else ()) + (MARKET if family == 'market_calendar' else ())


def features(row, family):
    """Allowlisted quote-time features; excludes date ID, move and validity."""
    feature_names(family)
    a, f = row['activity_features'], row['adaptive_features']
    idle = math.log1p(a['idle_ms']/1000)
    ratio = math.log(max(.001, f['vol_60_ppm'])/max(.001, f['vol_300_ppm']))
    values = [idle, math.log1p(a['changes_30']), math.log1p(a['changes_60']),
              math.log1p(a['changes_300']), a['empty_bins_300'], a['largest_variance_share_300'],
              math.log(max(.001, f['vol_300_ppm'])), ratio,
              math.tanh(f['net_300_bps']/20), min(10, f['directional_strength']),
              idle*max(0, -ratio), float(a['idle_is_lower_bound'])]
    if family != 'timing':
        dt = datetime.fromtimestamp(row['start']/1000, timezone.utc)
        hour = dt.hour + dt.minute/60 + dt.second/3600
        values += [float(dt.weekday() >= 5), math.sin(hour*math.pi/12), math.cos(hour*math.pi/12)]
    if family == 'market_calendar':
        g, at = row.get('oracle_gap'), row['start']
        supported = bool(g is not None and len(g['values']) == 5
                         and all(math.isfinite(v) for v in g['values'])
                         and 0 < at-g['observed_at'] <= 8000
                         and 0 < at-30000-g['lag_observed_at'] <= 8000
                         and g['lag_observed_at'] <= g['observed_at'])
        values += list(g['values'])+[0.] if supported else [0.]*5+[1.]
    if any(not math.isfinite(v) for v in values):
        raise ValueError('nonfinite entry feature')
    return values


def clean_training(rows, asset, cutoff):
    boundary = int(datetime.fromisoformat(cutoff).replace(tzinfo=timezone.utc).timestamp()*1000)
    if not rows or any(r['asset'] != asset for r in rows):
        raise ValueError('asset-specific training required')
    if any(r['period'] >= cutoff or r['expiry']+30000 >= boundary for r in rows):
        raise ValueError('training labels must mature strictly before cutoff')
    if any(a['start'] >= b['start'] for a, b in zip(rows, rows[1:])):
        raise ValueError('unique chronological training entries required')
    result = [r for r in rows if r['valid'] and r['adaptive_features'] is not None]
    if len(result) < 100:
        raise ValueError('at least 100 clean training references required')
    return result


def weights(rows):
    counts = {}
    for r in rows:
        counts[r['period']] = counts.get(r['period'], 0)+1
    w = np.asarray([1/counts[r['period']] for r in rows]); w /= w.sum()
    return w


def sigmoid(x):
    return 1/(1+np.exp(-np.clip(x, -30, 30)))


def design(rows, family):
    w = weights(rows)
    raw = np.asarray([features(r, family) for r in rows])
    center = w@raw
    sd = np.maximum(.1, np.sqrt(w@((raw-center)**2)))
    x = np.column_stack((np.ones(len(rows)), np.clip((raw-center)/sd, -5, 5)))
    return x, w, center, sd


def logistic(x, w, y, ridge):
    penalty = np.diag([1e-9]+[ridge]*(x.shape[1]-1))
    rate = float(w@y)
    coef = np.zeros(x.shape[1]); coef[0] = math.log(max(1e-8, rate)/max(1e-8, 1-rate))
    for _ in range(SPEC['logistic_steps']):
        probability = sigmoid(x@coef)
        gradient = x.T@(w*(probability-y))+penalty@coef
        hessian = x.T@((w*probability*(1-probability))[:, None]*x)+penalty
        step = np.linalg.solve(hessian, gradient)
        step *= min(1, 2/max(2, float(np.max(np.abs(step)))))
        coef -= step
        if np.max(np.abs(step)) < 1e-8:
            break
    return coef.tolist()


def fit_risk(rows, asset, cutoff, family, ridge):
    if ridge not in RIDGES:
        raise ValueError('undeclared ridge')
    rows = clean_training(rows, asset, cutoff)
    x, w, center, sd = design(rows, family)
    zero = np.asarray([r['move'] == 0 for r in rows], dtype=float)
    floor = np.asarray([required_width(r) <= 1 for r in rows], dtype=float)
    c0 = logistic(x, w, zero, ridge)
    cf = c0 if np.array_equal(zero, floor) else logistic(x, w, floor, ridge)
    return dict(version=SPEC['version'], asset=asset, family=family, ridge=ridge,
                feature_names=feature_names(family), center=center.tolist(), sd=sd.tolist(),
                zero_coefficients=c0, floor_coefficients=cf, cutoff=cutoff,
                training_dates=sorted({r['period'] for r in rows}), windows=len(rows),
                zero_windows=int(zero.sum()), floor_windows=int(floor.sum()),
                period_balanced_zero=float(w@zero), period_balanced_floor=float(w@floor),
                numpy_version=np.__version__, spec=SPEC)


def risk(row, model):
    z = [1.]+[max(-5, min(5, (v-m)/s)) for v, m, s in zip(features(row, model['family']), model['center'], model['sd'])]
    out = []
    for key in ('zero_coefficients', 'floor_coefficients'):
        logit = sum(a*b for a, b in zip(z, model[key]))
        out.append(1/(1+math.exp(-max(-30, min(30, logit)))))
    return out[0], max(out)


def risk_series(rows, model, online):
    """Period resets; all clean reference outcomes enter only after maturity."""
    pending, recent = deque(), deque()
    period = previous = None
    output = []
    for row in rows:
        at = row['start']
        if row['asset'] != model['asset'] or previous is not None and at <= previous:
            raise ValueError('asset-specific unique chronological prediction entries required')
        previous = at
        if period != row['period']:
            period = row['period']; pending.clear(); recent.clear()
        while pending and pending[0]['mature_at'] <= at:
            old = pending.popleft()
            if old['row']['valid']:
                recent.append(dict(expiry=old['row']['expiry'], zero=old['row']['move'] == 0,
                                   floor=required_width(old['row']) <= 1, p0=old['p0'], pf=old['pf']))
        while recent and (len(recent) > SPEC['online_memory'] or at-recent[0]['expiry'] > SPEC['online_max_age_ms']):
            recent.popleft()
        if row['adaptive_features'] is None:
            output.append(dict(p0=None, floor=None, base_p0=None, base_floor=None, mature=len(recent)))
            continue
        p0, pf = risk(row, model)
        base0, basef = p0, pf
        if online and recent:
            mass = SPEC['online_prior_events']
            def adjust(prob, label, key):
                factor = (mass+sum(r[label] for r in recent))/(mass+sum(r[key] for r in recent))
                factor = max(.1, min(10., factor))
                return prob*factor/(1-prob+prob*factor)
            p0, pf = adjust(p0, 'zero', 'p0'), adjust(pf, 'floor', 'pf')
            pf = max(p0, pf)
        output.append(dict(p0=p0, floor=pf, base_p0=base0, base_floor=basef, mature=len(recent)))
        pending.append(dict(row=row, p0=base0, pf=basef, mature_at=row['expiry']+30000))
    return output


def fit_positive(rows, asset, cutoff, family):
    rows = clean_training(rows, asset, cutoff)
    rows = [r for r in rows if required_width(r) > 1]
    if len(rows) < 100:
        raise ValueError('at least 100 positive-width references required')
    dates = sorted({r['period'] for r in rows})
    x, w, center, sd = design(rows, family)
    y = np.asarray([math.log(required_width(r)/max(1, r['adaptive_features']['vol_300_ppm'])) for r in rows])
    penalty = np.diag([1e-9]+[SPEC['positive_ridge']]*(x.shape[1]-1))
    coefficients = []
    for q in LEVELS:
        coef = np.zeros(x.shape[1]); coef[0] = float(np.quantile(y, q))
        for _ in range(SPEC['quantile_steps']):
            residual = y-x@coef
            irls = w*np.where(residual >= 0, q, 1-q)/np.maximum(np.abs(residual), SPEC['quantile_huber'])
            updated = np.linalg.solve(x.T@(irls[:, None]*x)+penalty, x.T@(irls*y))
            if np.max(np.abs(updated-coef)) < 1e-7:
                coef = updated; break
            coef = updated
        coefficients.append(coef.tolist())
    return dict(asset=asset, family=family, cutoff=cutoff, training_dates=dates,
                full_positive_windows=len(rows), fitted_windows=len(rows),
                center=center.tolist(), sd=sd.tolist(), levels=LEVELS, coefficients=coefficients,
                sample_rule='All positive-width training rows; equal date weights',
                support_rule='Global fitted count times requested quantile >=20; no local/independent-confidence claim')


def conditional_width(row, probability, model, target):
    floor = probability['floor']
    if floor is None:
        return dict(width=None, positive_q=None, tail_mass=0., supported=False)
    q = (target-floor)/max(1e-12, 1-floor)
    tail_mass = model['fitted_windows']*max(0, q)
    supported = q >= LEVELS[0] and q <= LEVELS[-1] and tail_mass >= 20
    if q <= 0 or q < LEVELS[0]:
        return dict(width=1, positive_q=q, tail_mass=tail_mass, supported=False)
    z = [1.]+[max(-5, min(5, (v-m)/s)) for v, m, s in zip(features(row, model['family']), model['center'], model['sd'])]
    logs = sorted(sum(a*b for a, b in zip(z, coef)) for coef in model['coefficients'])
    adjustment = float(np.interp(q, model['levels'], logs))
    log_width = math.log(max(1, row['adaptive_features']['vol_300_ppm']))+adjustment
    width = math.ceil(math.exp(max(math.log(2), min(math.log(50000), log_width))))
    return dict(width=width, positive_q=q, tail_mass=tail_mass, supported=supported)


def decision(row, forecast, conditional, parent_width, variant, multiplier):
    _, source, _, fraction, weekdays = variant
    target = .95/multiplier
    width = parent_width if source == 'parent' else conditional['width']
    reasons = []
    if width is None:
        reasons.append('missing_history')
    if weekdays and weekend(row):
        reasons.append('weekend_control')
    if fraction is not None and forecast['floor'] is not None and forecast['floor'] > fraction*target:
        reasons.append('predicted_minimum_width_risk')
    if fraction is not None and source == 'conditional' and width is not None and not conditional['supported']:
        reasons.append('insufficient_positive_tail_support')
    if width is not None and row['entry'] is not None and row['entry']*width//1000000 <= 0:
        reasons.append('unrepresentable_barrier')
    # Current validity/movement determine labels only, never the entry decision.
    shadow = row['move'] < row['entry']*width//1000000 if row['valid'] and width is not None else None
    return dict(width=width, offered=not reasons, reason=';'.join(reasons), shadow=shadow,
                survived=shadow if not reasons else None)
