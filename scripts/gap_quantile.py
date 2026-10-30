"""Conditional first-passage quantiles and delayed adaptive quantile tracking."""
from collections import deque
import math
import numpy as np

from adaptive_corridor import required_width
from nonfrozen_pricing import STATES
from preentry_bursty import features as timing_features, sigmoid
from stabilize_adaptive_corridor import balanced_weights

VARIANTS = ('retained_pool', 'timing_static', 'timing_adaptive', 'gap_static', 'gap_adaptive')
SPEC = dict(target=.48, ridge=.03, logistic_steps=30, quantile_steps=60, quantile_huber=.05,
            scale_clip=5, log_scale_clip=3, minimum_width=1, maximum_width=50000,
            positive_quantile_bounds=(.02, .98), maturity_delay_ms=30000,
            initial_learning_rate=.2, gradient_half_life_ms=3600000,
            maximum_age_ms=3600000, child_prior=12, child_memory=120,
            log_correction_bound=math.log(4), initial_gradient_square=1,
            anti_windup=True, admission='unchanged', support='same fresh mark context for timing and gap models')


def features(row, use_gap):
    values = timing_features(row)
    if use_gap:
        values += row['oracle_gap']['values']
    return values


def fit(values, use_gap):
    part = [p for p in values if p['shadow_survived'] is not None and p['row']['activity_state'] in STATES
            and p['row'].get('oracle_gap') is not None]
    if not part:
        raise ValueError('fresh, clean pre-entry market context required for training')
    w = np.asarray(balanced_weights([p['row'] for p in part])); w /= w.sum()
    raw = np.asarray([features(p['row'], use_gap) for p in part])
    center = w @ raw; sd = np.maximum(.1, np.sqrt(w @ ((raw - center) ** 2)))
    x = np.column_stack((np.ones(len(part)), np.clip((raw - center) / sd, -5, 5)))
    y = np.asarray([required_width(p['row']) <= 1 for p in part], dtype=float)
    penalty = np.diag([1e-8] + [SPEC['ridge']] * raw.shape[1])
    coef = np.zeros(x.shape[1]); rate = float(w @ y)
    coef[0] = math.log(max(1e-6, rate) / max(1e-6, 1 - rate))
    for _ in range(SPEC['logistic_steps']):
        p = sigmoid(x @ coef); grad = x.T @ (w * (p - y)) + penalty @ coef
        hess = x.T @ ((w * p * (1 - p))[:, None] * x) + penalty
        delta = np.linalg.solve(hess, grad)
        delta *= min(1, 2 / max(2, float(np.max(np.abs(delta)))))
        coef -= delta
        if np.max(np.abs(delta)) < 1e-8:
            break
    floor = sigmoid(x @ coef); positive = y == 0
    if not positive.any():
        raise ValueError('positive movement references required')
    reference_shape = np.asarray([max(-5, min(5, math.log(p['width_ppm'] / max(.001, p['row']['adaptive_features']['vol_300_ppm'])))) for p in part])
    px = np.column_stack((x, reference_shape))[positive]
    target = np.asarray([math.log(required_width(p['row']) / p['width_ppm']) for p in part])[positive]
    q = np.clip((SPEC['target'] - floor[positive]) / (1 - floor[positive]), *SPEC['positive_quantile_bounds'])
    pw = w[positive]; pw /= pw.sum()
    qp = np.diag([1e-8] + [SPEC['ridge']] * (px.shape[1] - 1)); qc = np.zeros(px.shape[1])
    for _ in range(SPEC['quantile_steps']):
        residual = target - px @ qc
        irls = pw * np.where(residual >= 0, q, 1 - q) / np.maximum(np.abs(residual), SPEC['quantile_huber'])
        updated = np.linalg.solve(px.T @ (irls[:, None] * px) + qp, px.T @ (irls * target))
        if np.max(np.abs(updated - qc)) < 1e-7:
            qc = updated
            break
        qc = updated
    return dict(use_gap=use_gap, center=center.tolist(), sd=sd.tolist(), floor_coefficients=coef.tolist(),
                price_coefficients=qc.tolist(), windows=len(part), periods=len({p['row']['period'] for p in part}),
                bursty_windows=sum(p['row']['activity_state'] == 'bursty' for p in part),
                minimum_width_floor=rate, numpy_version=np.__version__, spec=SPEC)


def forecast(p, model):
    row = p['row']
    z = [1] + [max(-5, min(5, (v - m) / s)) for v, m, s in zip(features(row, model['use_gap']), model['center'], model['sd'])]
    logit = sum(a * b for a, b in zip(z, model['floor_coefficients']))
    risk = 1 / (1 + math.exp(-max(-30, min(30, logit))))
    if risk >= SPEC['target']:
        return 1, risk
    z.append(max(-5, min(5, math.log(p['width_ppm'] / max(.001, row['adaptive_features']['vol_300_ppm'])))))
    log_scale = max(-3, min(3, sum(a * b for a, b in zip(z, model['price_coefficients']))))
    width = max(1, min(SPEC['maximum_width'], math.ceil(p['width_ppm'] * math.exp(log_scale))))
    return width, risk


def bucket(row):
    if row['activity_state'] != 'bursty':
        return None
    f = row['adaptive_features']; ratio = f['vol_60_ppm'] / max(.001, f['vol_300_ppm'])
    return 'cooling' if ratio < .75 else 'balanced' if ratio < 1.5 else 'fresh'


class Tracker:
    """Discounted AdaGrad on quantile loss; learns all clean reference paths."""
    def __init__(self):
        self.states = {}

    def state(self, key, at):
        s = self.states.setdefault(key, dict(delta=0., square=SPEC['initial_gradient_square'], last=None, times=deque()))
        if s['last'] is not None and at - s['last'] > SPEC['maximum_age_ms']:
            s.update(delta=0., square=SPEC['initial_gradient_square'], last=None, times=deque())
        while s['times'] and (len(s['times']) > SPEC['child_memory'] or at - s['times'][0] > SPEC['maximum_age_ms']):
            s['times'].popleft()
        return s

    def correction(self, row, at):
        parent = self.state('parent', at); key = bucket(row)
        if key is None:
            return parent['delta'], [('parent', 1.)]
        child = self.state(key, at); count = len(child['times']); weight = count / (count + SPEC['child_prior'])
        return (1 - weight) * parent['delta'] + weight * child['delta'], [('parent', 1 - weight), (key, weight)]

    def learn(self, past):
        row = past['row']; at = past['mature_at']
        hit = row['move'] < row['entry'] * past['width'] // 1_000_000
        error = float(hit) - SPEC['target']
        for key, weight in past['weights']:
            s = self.state(key, at)
            elapsed = at - s['last'] if s['last'] is not None else 0
            s['square'] *= 2 ** (-elapsed / SPEC['gradient_half_life_ms'])
            gradient = weight * error
            blocked = ((past['width'] == 1 and gradient > 0)
                       or (past['width'] >= SPEC['maximum_width'] and gradient < 0)
                       or (s['delta'] <= -SPEC['log_correction_bound'] and gradient > 0)
                       or (s['delta'] >= SPEC['log_correction_bound'] and gradient < 0))
            if not blocked:
                s['square'] += gradient * gradient
                step = SPEC['initial_learning_rate'] / math.sqrt(max(SPEC['initial_gradient_square'], s['square']))
                s['delta'] = max(-SPEC['log_correction_bound'], min(SPEC['log_correction_bound'], s['delta'] - step * gradient))
            s['last'] = at; s['times'].append(row['expiry'])


def series(values, model, adaptive):
    output = []; pending = deque(); tracker = Tracker(); period = previous = None
    for p in values:
        row, at = p['row'], p['row']['start']
        if previous is not None and at < previous:
            raise ValueError('chronological references required')
        previous = at
        if period != row['period']:
            period = row['period']; pending.clear(); tracker = Tracker()
        while pending and pending[0]['mature_at'] <= at:
            old = pending.popleft()
            if old['row']['valid'] and at - old['row']['expiry'] <= SPEC['maximum_age_ms']:
                tracker.learn(old)
        eligible = p['width_ppm'] is not None and row['activity_state'] in STATES and row.get('oracle_gap') is not None
        q, risk, delta, weights = None, None, 0., []
        width = p['width_ppm']; result = dict(p)
        if eligible:
            q, risk = forecast(p, model)
            if adaptive:
                delta, weights = tracker.correction(row, at)
            raw = q if delta == 0 else math.ceil(q * math.exp(delta))
            width = max(1, min(SPEC['maximum_width'], raw))
            if row['activity_state'] == 'bursty':
                hit = row['move'] < row['entry'] * width // 1_000_000 if row['valid'] else None
                result.update(width_ppm=width, shadow_survived=hit, survived=None if p['paused'] else hit,
                              capped=raw > SPEC['maximum_width'])
            if adaptive:
                pending.append(dict(row=row, width=width, weights=weights, mature_at=row['expiry'] + SPEC['maturity_delay_ms']))
        result.update(gap_floor_risk=risk, gap_forecast=q, gap_log_correction=delta,
                      gap_supported=eligible, gap_controller_weights=weights)
        output.append(result)
    return output


def all_series(values, models):
    result = dict(retained_pool=[dict(p, gap_floor_risk=None, gap_forecast=None, gap_log_correction=0.,
                                    gap_supported=False, gap_controller_weights=[]) for p in values])
    for source in ('timing', 'gap'):
        for mode in ('static', 'adaptive'):
            result[source + '_' + mode] = series(values, models[source], mode == 'adaptive')
    return result
