"""Bursty-only residual quantiles with strictly earlier forecast priors."""
from collections import deque
from datetime import datetime, timezone
import math

from adaptive_corridor import required_width, weighted_quantile
from bursty_feedback import VARIANTS as OLD_VARIANTS, all_series as previous_series
from gap_quantile import SPEC as BASE_SPEC, forecast
from nonfrozen_pricing import quantile_grid
from stabilize_adaptive_corridor import balanced_weights

MODES = ('ratio1h_neutral', 'ratio4h_neutral', 'ratio4h_prior', 'ratio4h_fast')
VARIANTS = OLD_VARIANTS + tuple(source + '_' + mode for source in ('timing', 'gap') for mode in MODES)
SPEC = dict(target=.48, prior_mass=12, memory=120, maturity_delay_ms=30000,
            short_age_ms=3600000, short_half_life_ms=900000,
            long_age_ms=14400000, long_half_life_ms=3600000,
            step=.05, fast_step=.20, minimum_correction=.25, maximum_correction=4.,
            minimum_child_windows=80, minimum_child_periods=3, cdf_knots=128,
            prior_initialization='Clipped prior median at reset; neutral factor one when no OOF prior',
            learning='Required width / uncorrected entry forecast, matured clean bursty references only',
            clock='Correct only on supported bursty entries; reset to prior if memory is empty',
            admission='Unchanged; unsupported entries retain benchmark price',
            models='Frozen preceding fits; prior residuals use latest available strictly earlier fitted model')


def fit_prior(records, source, periods, cutoff):
    if len(set(periods)) != len(periods) or any(day >= cutoff for day in periods):
        raise ValueError('unique training dates strictly before cutoff required')
    boundary = int(datetime.fromisoformat(cutoff).replace(tzinfo=timezone.utc).timestamp() * 1000)
    part = [r for r in records if r['source'] == source and r['row']['period'] in periods]
    if len({(r['row']['period'], r['row']['start']) for r in part}) != len(part):
        raise ValueError('duplicate chronological calibration reference')
    for r in part:
        day = r['row']['period']
        if (r['model_cutoff'] > day or any(p >= day for p in r['training_periods'])
                or r['row']['expiry'] + SPEC['maturity_delay_ms'] >= boundary):
            raise ValueError('calibration forecast or label crosses chronological boundary')
        if not math.isfinite(r['ratio']) or r['ratio'] <= 0:
            raise ValueError('positive finite calibration residual required')
    def estimate(values):
        if not values:
            return dict(knots=[1.] * SPEC['cdf_knots'], windows=0, periods=0, neutral_fallback=True)
        w = balanced_weights([r['row'] for r in values])
        return dict(knots=quantile_grid([(r['ratio'], weight) for r, weight in zip(values, w)], SPEC['cdf_knots']),
                    windows=len(values), periods=len({r['row']['period'] for r in values}), neutral_fallback=False)
    parent = estimate(part)
    burst = [r for r in part if r['row']['activity_state'] == 'bursty']
    supported = len(burst) >= SPEC['minimum_child_windows'] and len({r['row']['period'] for r in burst}) >= SPEC['minimum_child_periods']
    child = estimate(burst) if supported else dict(parent)
    child.update(used_parent=not supported, child_windows=len(burst), child_periods=len({r['row']['period'] for r in burst}))
    return dict(source=source, training_periods=periods, cutoff=cutoff, parent=parent, bursty=child)


def series(values, model, prior, mode):
    if mode not in MODES:
        raise ValueError('unknown residual mode')
    short = mode == 'ratio1h_neutral'; learned = mode in ('ratio4h_prior', 'ratio4h_fast')
    age = SPEC['short_age_ms'] if short else SPEC['long_age_ms']
    half = SPEC['short_half_life_ms'] if short else SPEC['long_half_life_ms']
    step = SPEC['fast_step'] if mode == 'ratio4h_fast' else SPEC['step']
    knots = prior['bursty']['knots'] if learned else [1.] * SPEC['cdf_knots']
    prior_factor = max(SPEC['minimum_correction'], min(SPEC['maximum_correction'], weighted_quantile([(x, 1) for x in knots], SPEC['target'])))
    output = []; pending = deque(); pool = deque(); period = previous = None; correction = prior_factor
    for p in values:
        row, at = p['row'], p['row']['start']
        if previous is not None and at < previous:
            raise ValueError('chronological references required')
        previous = at
        if period != row['period']:
            period = row['period']; pending.clear(); pool.clear(); correction = prior_factor
        while pending and pending[0]['mature_at'] <= at:
            old = pending.popleft()
            if old['row']['valid'] and at - old['row']['expiry'] <= age:
                pool.append(dict(expiry=old['row']['expiry'], ratio=required_width(old['row']) / old['forecast']))
        while pool and (len(pool) > SPEC['memory'] or at - pool[0]['expiry'] > age):
            pool.popleft()
        eligible = p['width_ppm'] is not None and row['activity_state'] == 'bursty' and row.get('oracle_gap') is not None
        q = risk = None; requested = prior_factor; mass = effective = 0.; components = []
        result = dict(p)
        if eligible:
            q, risk = forecast(p, model)
            weights = [2 ** (-(at - old['expiry']) / half) for old in pool]
            mass = sum(weights); effective = mass * mass / sum(w * w for w in weights) if mass else 0.
            samples = [(x, SPEC['prior_mass'] / len(knots)) for x in knots]
            samples.extend((old['ratio'], weight) for old, weight in zip(pool, weights))
            requested = max(SPEC['minimum_correction'], min(SPEC['maximum_correction'], weighted_quantile(samples, SPEC['target'])))
            if not pool:
                correction = prior_factor
            correction = min(correction * (1 + step), max(correction * (1 - step), requested))
            raw = q if correction == 1 else math.ceil(q * correction)
            width = max(1, min(BASE_SPEC['maximum_width'], raw))
            hit = row['move'] < row['entry'] * width // 1_000_000 if row['valid'] else None
            result.update(width_ppm=width, shadow_survived=hit, survived=None if p['paused'] else hit,
                          capped=raw > BASE_SPEC['maximum_width'])
            components = [dict(key='bursty_ratio', weight=1., log_correction=math.log(correction), mature=len(pool),
                               requested=requested, prior_factor=prior_factor, mass=mass, effective=effective)]
            pending.append(dict(row=row, forecast=q, mature_at=row['expiry'] + SPEC['maturity_delay_ms']))
        result.update(gap_floor_risk=risk, gap_forecast=q, gap_log_correction=math.log(correction) if eligible else 0.,
                      gap_supported=eligible, gap_controller_weights=[], feedback_components=components,
                      ratio_requested=requested, ratio_mass=mass, ratio_effective=effective)
        output.append(result)
    return output


def all_series(values, models, priors):
    result = previous_series(values, models)
    for source in ('timing', 'gap'):
        for mode in MODES:
            result[source + '_' + mode] = series(values, models[source], priors[source], mode)
    return result
