"""Bounded NumPy Bayesian search and cached, causal residual-controller replay.

The surrogate suggests parameters; it never predicts market outcomes or promotes
a live model. Forecasts must be computed from the frozen pre-entry models.
"""
from collections import deque
import math

import numpy as np

from adaptive_corridor import required_width, weighted_quantile
from gap_quantile import forecast


SPACE = dict(source=['timing', 'gap'], half_life_minutes=[15., 180.],
             age_halflives=[2., 8.], prior_mass=[.25, 24.],
             max_step=[.01, .4], learned_weight=[0., 1.])
NAMES = tuple(k for k in SPACE if k != 'source')
LOG_NAMES = ('half_life_minutes', 'prior_mass', 'max_step')
SPEC = dict(search='Gaussian process, Matern 5/2, sampled expected improvement',
            warmup=10, acquisition_pool=1024, length_scale=.45, noise=1e-5,
            exploration_every=5, memory=120, target=.48, maturity_delay_ms=30000,
            minimum_correction=.25, maximum_correction=4., maximum_width=50000)


def validate(params):
    if set(params) != set(SPACE) or params['source'] not in SPACE['source']:
        raise ValueError('complete bounded parameter declaration required')
    for name in NAMES:
        lo, hi = SPACE[name]
        if not math.isfinite(params[name]) or not lo <= params[name] <= hi:
            raise ValueError('parameter outside declared bounds: ' + name)


def encode(params):
    validate(params)
    x = [float(SPACE['source'].index(params['source']))]
    for name in NAMES:
        lo, hi = SPACE[name]; value = params[name]
        if name in LOG_NAMES:
            lo, hi, value = math.log(lo), math.log(hi), math.log(value)
        x.append((value - lo) / (hi - lo))
    return np.asarray(x)


def decode(x):
    if len(x) != len(SPACE) or not np.all(np.isfinite(x)) or np.any(np.asarray(x) < 0) or np.any(np.asarray(x) > 1):
        raise ValueError('unit search coordinates required')
    params = dict(source=SPACE['source'][int(x[0] >= .5)])
    for value, name in zip(x[1:], NAMES):
        lo, hi = SPACE[name]
        result = math.exp(math.log(lo) + value * math.log(hi / lo)) if name in LOG_NAMES else lo + value * (hi - lo)
        params[name] = float(max(lo, min(hi, result)))
    return params


def anchors():
    return [dict(source=source, half_life_minutes=60., age_halflives=4.,
                 prior_mass=12., max_step=.05, learned_weight=weight)
            for weight in (1., 0.) for source in ('gap', 'timing')]


def kernel(a, b):
    radius = np.sqrt(np.maximum(0., np.sum((a[:, None, :] - b[None, :, :]) ** 2, axis=2))) / SPEC['length_scale']
    r = math.sqrt(5) * radius
    return (1 + r + r * r / 3) * np.exp(-r)


class BayesianSearch:
    """Sequential, reproducible proposals, with one outstanding trial at a time."""
    def __init__(self, seed=20261028):
        self.rng = np.random.default_rng(seed)
        self.x, self.y, self.pending = [], [], None

    def ask(self):
        if self.pending is not None:
            raise ValueError('record the pending trial before requesting another')
        n = len(self.y)
        if n < len(anchors()):
            params = anchors()[n]
        else:
            pool = self.rng.random((SPEC['acquisition_pool'], len(SPACE)))
            pool[:, 0] = self.rng.integers(0, 2, len(pool))
            if n >= SPEC['warmup'] and n % SPEC['exploration_every']:
                incumbent = self.x[int(np.argmin(self.y))]
                half = len(pool) // 2
                pool[:half, 1:] = np.clip(incumbent[1:] + self.rng.normal(0, .15, (half, len(NAMES))), 0, 1)
                x = np.asarray(self.x); y = np.asarray(self.y)
                y = (y - y.mean()) / max(float(y.std()), 1e-8)
                chol = np.linalg.cholesky(kernel(x, x) + SPEC['noise'] * np.eye(n))
                cross = kernel(x, pool)
                mu = cross.T @ np.linalg.solve(chol.T, np.linalg.solve(chol, y))
                v = np.linalg.solve(chol, cross)
                sd = np.sqrt(np.maximum(1e-12, 1 - np.sum(v * v, axis=0)))
                improvement = y.min() - mu - .01
                z = improvement / sd
                cdf = np.asarray([.5 * (1 + math.erf(float(t) / math.sqrt(2))) for t in z])
                acquisition = improvement * cdf + sd * np.exp(-z * z / 2) / math.sqrt(2 * math.pi)
                for old in x:
                    acquisition[np.max(np.abs(pool - old), axis=1) < 1e-9] = -math.inf
                params = decode(pool[int(np.argmax(acquisition))])
            else:
                params = decode(pool[0])
        self.pending = params
        return dict(params)

    def tell(self, params, score):
        if params != self.pending or self.pending is None or not math.isfinite(score):
            raise ValueError('finite result for the pending trial required')
        self.x.append(encode(params)); self.y.append(float(score)); self.pending = None


def cache_forecasts(values, models):
    return {source: [forecast(p, model) if p['width_ppm'] is not None
                    and p['row']['activity_state'] == 'bursty' and p['row'].get('oracle_gap') is not None
                    else None for p in values] for source, model in models.items()}


def replay(values, cached, prior, params):
    """Only already matured clean bursty labels can change a future price."""
    validate(params)
    if len(values) != len(cached):
        raise ValueError('forecast alignment differs')
    half = params['half_life_minutes'] * 60000
    age = half * params['age_halflives']
    knots = (prior['bursty']['knots'] if params['learned_weight'] == 1 else
             [math.exp(params['learned_weight'] * math.log(x)) for x in prior['bursty']['knots']])
    samples = [(x, params['prior_mass'] / len(knots)) for x in knots]
    clamp = lambda x: max(SPEC['minimum_correction'], min(SPEC['maximum_correction'], x))
    initial = clamp(weighted_quantile([(x, 1) for x in knots], SPEC['target']))
    pending, pool = deque(), deque()
    period = previous = None; correction = initial; output = []
    for p, prediction in zip(values, cached):
        row = p['row']; at = row['start']
        if previous is not None and at < previous:
            raise ValueError('chronological references required')
        previous = at
        if period != row['period']:
            period = row['period']; pending.clear(); pool.clear(); correction = initial
        while pending and pending[0][0] <= at:
            _, old, q = pending.popleft()
            if old['valid'] and at - old['expiry'] <= age:
                pool.append((old['expiry'], required_width(old) / q))
        while pool and (len(pool) > SPEC['memory'] or at - pool[0][0] > age):
            pool.popleft()
        result = p
        if prediction is not None:
            q, risk = prediction
            evidence = [(ratio, 2 ** (-(at - expiry) / half)) for expiry, ratio in pool]
            requested = clamp(weighted_quantile(samples + evidence, SPEC['target']))
            if not pool:
                correction = initial
            correction = min(correction * (1 + params['max_step']), max(correction * (1 - params['max_step']), requested))
            raw = q if correction == 1 else math.ceil(q * correction)
            width = max(1, min(SPEC['maximum_width'], raw))
            hit = row['move'] < row['entry'] * width // 1000000 if row['valid'] else None
            result = dict(p, width_ppm=width, shadow_survived=hit, survived=None if p['paused'] else hit,
                          capped=raw > SPEC['maximum_width'], optimizer_correction=correction,
                          optimizer_evidence=len(pool), optimizer_requested=requested)
            pending.append((row['expiry'] + SPEC['maturity_delay_ms'], row, q))
        output.append(result)
    return output
