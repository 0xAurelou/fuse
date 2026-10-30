"""Delayed survival feedback on a residual CDF's quantile level.

This bounded research controller does not inherit ACI's long-run guarantee:
prices are discrete, label feedback is delayed, and widths/levels are bounded.
"""
from collections import deque
import math

from adaptive_corridor import required_width, weighted_quantile
from bursty_optimizer import SPEC as BASE_SPEC, replay as baseline, validate

GAINS = dict(slow=.01, medium=.03, fast=.1)
VARIANTS = ('retained_pool', 'optimized', 'cdf_static_relaxed') + tuple(
    'cdf_' + speed + '_' + bounds for bounds in ('bounded', 'relaxed') for speed in GAINS)
SPEC = dict(target=.48, levels=[.02, .98], gains=GAINS,
            maturity_delay_ms=30000, memory=120, maximum_width=50000,
            bounds='bounded: correction .25..4; relaxed: only absolute width 1..50000',
            controller='level += gain * (target - matured shadow survival)',
            anti_windup='no outward level update at absolute width bounds',
            stale='reset level when all reference evidence exceeds the original maximum age',
            feedback='Only matured clean bursty references, including refused quotes',
            guarantee='None for bounded/discrete/delayed/conditional or eight-hour coverage')


def series(values, cached, prior, params, gain, relaxed=False):
    validate(params)
    if gain not in (0., *GAINS.values()) or len(values) != len(cached):
        raise ValueError('declared gain and aligned forecasts required')
    if gain == 0 and not relaxed:
        return baseline(values, cached, prior, params)
    half = params['half_life_minutes'] * 60000
    age = half * params['age_halflives']
    knots = [math.exp(params['learned_weight'] * math.log(x)) for x in prior['bursty']['knots']]
    samples = [(x, params['prior_mass'] / len(knots)) for x in knots]
    def clamp(x):
        return x if relaxed else max(BASE_SPEC['minimum_correction'], min(BASE_SPEC['maximum_correction'], x))
    initial = clamp(weighted_quantile([(x, 1) for x in knots], SPEC['target']))
    pending, pool = deque(), deque()
    period = previous = last_mature = None
    correction, level = initial, SPEC['target']
    output = []
    for p, prediction in zip(values, cached):
        row = p['row']; at = row['start']
        if previous is not None and at < previous:
            raise ValueError('chronological references required')
        previous = at
        if period != row['period']:
            period = row['period']; pending.clear(); pool.clear()
            correction, level, last_mature = initial, SPEC['target'], None
        if last_mature is not None and at - last_mature > age:
            level, last_mature = SPEC['target'], None
        while pending and pending[0][0] <= at:
            _, old, q, old_width = pending.popleft()
            if old['valid'] and at - old['expiry'] <= age:
                actual = required_width(old)
                pool.append((old['expiry'], actual / q))
                hit = old['move'] < old['entry'] * old_width // 1000000
                direction = SPEC['target'] - hit
                blocked = (old_width == 1 and direction < 0 or
                           old_width == SPEC['maximum_width'] and direction > 0)
                if not blocked:
                    level = max(SPEC['levels'][0], min(SPEC['levels'][1], level + gain * direction))
                last_mature = old['expiry']
        while pool and (len(pool) > SPEC['memory'] or at - pool[0][0] > age):
            pool.popleft()
        result = p
        if prediction is not None:
            if p['width_ppm'] is None or row['activity_state'] != 'bursty' or row.get('oracle_gap') is None:
                raise ValueError('cached forecast support differs')
            q, _ = prediction
            if not math.isfinite(q) or q <= 0:
                raise ValueError('positive finite forecast required')
            evidence = [(ratio, 2 ** (-(at - expiry) / half)) for expiry, ratio in pool]
            requested = clamp(weighted_quantile(samples + evidence, level))
            if not pool:
                correction = initial
            correction = min(correction * (1 + params['max_step']),
                             max(correction * (1 - params['max_step']), requested))
            raw = q if correction == 1 else math.ceil(q * correction)
            width = max(1, min(SPEC['maximum_width'], raw))
            hit = row['move'] < row['entry'] * width // 1000000 if row['valid'] else None
            result = dict(p, width_ppm=width, shadow_survived=hit, survived=None if p['paused'] else hit,
                          capped=raw > SPEC['maximum_width'], cdf_level=level,
                          cdf_correction=correction, cdf_requested=requested, cdf_evidence=len(pool),
                          cdf_bound=(not relaxed and (requested <= .25 or requested >= 4.)),
                          cdf_level_bound=level in SPEC['levels'])
            pending.append((row['expiry'] + SPEC['maturity_delay_ms'], row, q, width))
        output.append(result)
    return output


def all_series(values, cached, prior, params):
    out = dict(retained_pool=values, optimized=baseline(values, cached, prior, params),
               cdf_static_relaxed=series(values, cached, prior, params, 0., True))
    for bounds in ('bounded', 'relaxed'):
        for speed, gain in GAINS.items():
            out['cdf_' + speed + '_' + bounds] = series(values, cached, prior, params, gain, bounds == 'relaxed')
    return out
