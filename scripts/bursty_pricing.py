"""Bursty-only causal overlays, leaving the base's other activity states intact."""
from collections import deque
import math

from adaptive_corridor import required_width, weighted_quantile
from nonfrozen_pricing import STATES, fit_prior
from stabilize_adaptive_corridor import balanced_weights


def spec(name, *, base='engine_floor10', family='hierarchy', memory=60, age_hours=1,
         minimum=4, conditional=False, guard=False):
    return dict(name=name, base=base, family=family, memory=memory, leaf_memory=memory // 2,
                maximum_age_ms=int(age_hours * 3_600_000), minimum_leaf=minimum,
                minimum_parent=12, prior_mass=12, maximum_step=.05, gain=.1,
                minimum_correction=.05, maximum_correction=2.0,
                conditional=conditional, directional_guard=guard, maturity_delay_ms=30_000)


SPECS = (
    spec('baseline', base='baseline', family='comparator'),
    spec('engine_floor20', base='engine_floor20', family='comparator'),
    spec('engine_floor10', family='comparator'),
    spec('feedback_state_fast', base='feedback_state_fast', family='comparator'),
    spec('floor10_burst_static', family='static'),
    spec('floor10_burst_feedback4', family='feedback'),
    spec('floor10_burst_feedback1', family='feedback', minimum=1),
    spec('floor10_burst_pool120', memory=120, age_hours=4),
    spec('floor10_burst_pool60'),
    spec('floor10_burst_shape60', conditional=True),
    spec('floor10_burst_shape60_guard', conditional=True, guard=True),
    spec('baseline_burst_shape60', base='baseline', conditional=True),
)


def shape(row):
    """Past-only fast/slow variance ratio: cooling, balanced or fresh shock."""
    f = row['adaptive_features']
    ratio = f['vol_60_ppm'] / max(.001, f['vol_300_ppm'])
    return 'cooling' if ratio < .75 else 'balanced' if ratio < 1.5 else 'fresh'


def fit_model(values):
    model = fit_prior(values)
    leaves = {}
    for state in STATES:
        for bucket in ('cooling', 'balanced', 'fresh'):
            part = [p for p in values if p['shadow_survived'] is not None
                    and p['row']['activity_state'] == state and shape(p['row']) == bucket]
            periods = len({p['row']['period'] for p in part})
            factor = model['states'][state]['static_factor']
            fallback = len(part) < 80 or periods < 3
            if not fallback:
                weights = balanced_weights([p['row'] for p in part])
                ratio = weighted_quantile([(required_width(p['row']) / p['width_ppm'], w)
                                           for p, w in zip(part, weights)], model['target_survival'])
                weight = len(part) / (len(part) + 200)
                factor = math.exp(weight * math.log(ratio) + (1-weight) * math.log(factor))
            leaves[f'{state}:{bucket}'] = dict(factor=factor, windows=len(part), periods=periods,
                                               used_state_parent=fallback)
    model['shape_leaves'] = leaves
    return model


def scale(row, model, candidate):
    if candidate['conditional']:
        return model['shape_leaves'][f"{row['activity_state']}:{shape(row)}"]['factor']
    return model['states'][row['activity_state']]['static_factor']


def reprice(values, model, candidate):
    if candidate['family'] == 'comparator':
        return [dict(p, burst_correction=None, burst_mature=0, burst_parent_mature=0) for p in values]
    pending, parent, leaf = deque(), deque(), deque()
    output, session, previous = [], None, None
    correction, theta, last_feedback = 1.0, 0.0, None
    q, age = model['target_survival'], candidate['maximum_age_ms']
    family = candidate['family']
    for p in values:
        r, at = p['row'], p['row']['start']
        if previous is not None and at < previous:
            raise ValueError('chronological predictions required')
        previous = at
        if r['period'] != session:
            session = r['period']
            pending.clear(); parent.clear(); leaf.clear()
            correction, theta, last_feedback = 1.0, 0.0, None
        while pending and pending[0]['mature_at'] <= at:
            past = pending.popleft()
            old = past['row']
            # Stale pending observations cannot affect the fresh feedback accumulator.
            if not old['valid'] or at - old['expiry'] > age:
                continue
            item = dict(expiry=old['expiry'], ratio=required_width(old) / past['denominator'])
            parent.append(item)
            if old['activity_state'] == 'bursty':
                leaf.append(item)
                if family == 'feedback':
                    if last_feedback is None or old['expiry'] - last_feedback > age:
                        theta = 0.0
                    hit = old['move'] < old['entry'] * past['width'] // 1_000_000
                    theta -= candidate['gain'] * (hit-q)
                    theta = max(math.log(candidate['minimum_correction']),
                                min(math.log(candidate['maximum_correction']), theta))
                    last_feedback = old['expiry']
        for pool, limit in ((parent, candidate['memory']), (leaf, candidate['leaf_memory'])):
            while pool and (len(pool) > limit or at - pool[0]['expiry'] > age):
                pool.popleft()
        eligible = p['width_ppm'] is not None and r['activity_state'] in STATES
        requested = 1.0
        if family == 'feedback' and len(leaf) >= candidate['minimum_leaf']:
            requested = math.exp(theta)
        elif family == 'hierarchy':
            if len(parent) >= candidate['minimum_parent']:
                requested = weighted_quantile([(v['ratio'], 1) for v in parent], q)
                requested = math.exp(len(parent) / (len(parent) + candidate['prior_mass']) * math.log(requested))
            if len(leaf) >= candidate['minimum_leaf']:
                empirical = weighted_quantile([(v['ratio'], 1) for v in leaf], q)
                weight = len(leaf) / (len(leaf) + candidate['prior_mass'])
                requested = math.exp(weight * math.log(empirical) + (1-weight) * math.log(requested))
        requested = min(candidate['maximum_correction'], max(candidate['minimum_correction'], requested))
        guarded = candidate['directional_guard'] and r['market_regime'] in ('pump', 'dump')
        if eligible and r['activity_state'] == 'bursty' and not guarded:
            step = candidate['maximum_step']
            correction = min(correction*(1+step), max(correction*(1-step), requested))
            raw = max(1, math.ceil(p['width_ppm'] * scale(r, model, candidate) * correction))
            width = min(model['maximum_width_ppm'], raw)
            hit = r['move'] < r['entry'] * width // 1_000_000 if r['valid'] else None
            result = dict(p, width_ppm=width, capped=raw > model['maximum_width_ppm'], shadow_survived=hit,
                          survived=None if p['paused'] else hit, burst_correction=correction,
                          burst_mature=len(leaf), burst_parent_mature=len(parent))
        else:
            result = dict(p, burst_correction=None, burst_mature=len(leaf), burst_parent_mature=len(parent))
        output.append(result)
        if eligible and family != 'static':
            # All non-frozen references learn; admission and later validity never select the entry.
            pending.append(dict(row=r, width=result['width_ppm'],
                                denominator=p['width_ppm'] * scale(r, model, candidate),
                                mature_at=r['expiry'] + candidate['maturity_delay_ms']))
    return output
