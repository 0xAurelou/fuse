"""Causal non-frozen price refinements; admission and frozen widths stay fixed."""
from collections import defaultdict, deque
from copy import deepcopy
import math

from adaptive_corridor import required_width, weighted_quantile
from research_activity_calibration import predict
from stabilize_adaptive_corridor import balanced_weights

STATES = ('active', 'sparse', 'bursty')


def spec(name, family, *, quiet=False, memory=120, prior=12, step=.02, floor=.1, gain=.05):
    return dict(name=name, family=family, states=('sparse', 'bursty') if quiet else STATES,
                memory=memory, prior_mass=prior, maximum_step=step, minimum_correction=.05,
                maximum_correction=2.0, minimum_mature=12, maximum_age_ms=4 * 3_600_000,
                engine_floor=floor, feedback_gain=gain, maturity_delay_ms=30_000)


SPECS = (
    spec('baseline', 'baseline'),
    spec('engine_floor20', 'engine', floor=.2),
    spec('engine_floor10', 'engine'),
    spec('engine_floor10_quiet', 'engine', quiet=True),
    spec('static_state', 'static'),
    spec('residual_state120', 'residual'),
    spec('residual_state60', 'residual', memory=60),
    spec('hurdle_state120', 'hurdle'),
    spec('hurdle_state60', 'hurdle', memory=60),
    spec('hurdle_quiet120', 'hurdle', quiet=True),
    spec('hurdle_state120_fast', 'hurdle', step=.05),
    spec('feedback_state', 'feedback'),
    spec('feedback_state_fast', 'feedback', gain=.1, step=.05),
)


def quantile_grid(values, count=128):
    """Midpoint quantiles with equal mass; compress the training positive CDF."""
    if not values:
        return []
    ordered = sorted(values)
    total = sum(w for _, w in ordered)
    if total <= 0 or any(w <= 0 for _, w in ordered):
        raise ValueError('positive quantile weights required')
    index, cumulative = 0, ordered[0][1]
    result = []
    for i in range(count):
        cutoff = (i + .5) / count * total
        while cumulative < cutoff and index + 1 < len(ordered):
            index += 1
            cumulative += ordered[index][1]
        result.append(ordered[index][0])
    return result


def fit_prior(values, q=.48):
    all_part = [p for p in values if p['row']['activity_state'] in STATES
                and p['shadow_survived'] is not None]
    if not all_part:
        raise ValueError('non-frozen training references required')

    def estimate(part):
        weights = balanced_weights([p['row'] for p in part])
        floor = sum(w * (required_width(p['row']) <= 1) for p, w in zip(part, weights)) / sum(weights)
        ratios = [(required_width(p['row']) / p['width_ppm'], w) for p, w in zip(part, weights)]
        positive = [(ratio, w) for (ratio, w), p in zip(ratios, part) if required_width(p['row']) > 1]
        scale = weighted_quantile(ratios, q)
        scale = math.exp(len(part) / (len(part) + 200) * math.log(scale))
        return dict(windows=len(part), periods=len({p['row']['period'] for p in part}),
                    minimum_width_floor=floor, positive_ratios=quantile_grid(positive), static_factor=scale)

    parent = estimate(all_part)
    states = {}
    for state in STATES:
        part = [p for p in all_part if p['row']['activity_state'] == state]
        periods = len({p['row']['period'] for p in part})
        leaf = estimate(part) if len(part) >= 80 and periods >= 3 else dict(parent)
        states[state] = dict(leaf, child_windows=len(part), child_periods=periods,
                             used_parent=len(part) < 80 or periods < 3)
    return dict(target_survival=q, parent=parent, states=states, positive_cdf_knots=128,
                minimum_width_ppm=1, maximum_width_ppm=50_000)


def relaxed_engine(values, engine, candidate):
    model = deepcopy(engine)
    model['online']['minimum_correction'] = candidate['engine_floor']
    other = predict([p['row'] for p in values], model)
    result = []
    for p, alternative in zip(values, other):
        if p['width_ppm'] is not None and p['row']['activity_state'] in candidate['states']:
            width = alternative['width_ppm']
            if width is None:
                raise ValueError('relaxed engine lost pre-entry eligibility')
            result.append(dict(p, width_ppm=width, capped=alternative['capped'],
                               shadow_survived=alternative['shadow_survived'],
                               survived=None if p['paused'] else alternative['shadow_survived'],
                               nonfrozen_correction=alternative['correction'], nonfrozen_mature=alternative['mature_outcomes']))
        else:
            result.append(dict(p, nonfrozen_correction=None, nonfrozen_mature=0))
    return result


def reprice(values, prior, candidate, engine=None):
    family = candidate['family']
    if family == 'engine':
        if engine is None:
            raise ValueError('parent engine required')
        return relaxed_engine(values, engine, candidate)
    if family == 'baseline':
        return [dict(p, nonfrozen_correction=None, nonfrozen_mature=0) for p in values]
    pending, pools = deque(), defaultdict(deque)
    correction, feedback = defaultdict(lambda: 1.0), defaultdict(float)
    last_mature = {}
    output, session, previous = [], None, None
    q = prior['target_survival']
    for p in values:
        r, at = p['row'], p['row']['start']
        if previous is not None and at < previous:
            raise ValueError('chronological predictions required')
        previous = at
        if session != r['period']:
            session = r['period']
            pending.clear(); pools.clear(); correction.clear(); feedback.clear(); last_mature.clear()
        while pending and pending[0]['mature_at'] <= at:
            past = pending.popleft()
            old, state = past['prediction'], past['state']
            if not old['row']['valid']:
                continue
            actual = required_width(old['row'])
            item = dict(expiry=old['row']['expiry'], ratio=actual / past['base'], floor=actual <= 1)
            pools[state].append(item)
            if family == 'feedback':
                if state not in last_mature or at - last_mature[state] > candidate['maximum_age_ms']:
                    feedback[state] = 0.0
                survived = old['row']['move'] < old['row']['entry'] * past['width'] // 1_000_000
                feedback[state] -= candidate['feedback_gain'] * (survived - q)
                feedback[state] = min(math.log(candidate['maximum_correction']),
                                      max(math.log(candidate['minimum_correction']), feedback[state]))
            last_mature[state] = old['row']['expiry']
        for pool in pools.values():
            while pool and (len(pool) > candidate['memory'] or at - pool[0]['expiry'] > candidate['maximum_age_ms']):
                pool.popleft()
        state = r['activity_state']
        if p['width_ppm'] is None or state not in candidate['states']:
            output.append(dict(p, nonfrozen_correction=None, nonfrozen_mature=0))
            continue
        pool, trained = pools[state], prior['states'][state]
        base = p['width_ppm']
        static = trained['static_factor'] if family in ('static', 'feedback') else 1.0
        requested, estimated_floor = 1.0, None
        if family == 'residual' and len(pool) >= candidate['minimum_mature']:
            raw = weighted_quantile([(v['ratio'], 1) for v in pool], q)
            requested = math.exp(len(pool) / (len(pool) + candidate['prior_mass']) * math.log(raw))
        elif family == 'hurdle' and len(pool) >= candidate['minimum_mature']:
            mass = candidate['prior_mass']
            estimated_floor = (sum(v['floor'] for v in pool) + mass * trained['minimum_width_floor']) / (len(pool) + mass)
            if estimated_floor >= q:
                requested = 1 / base
            else:
                positive_q = (q - estimated_floor) / (1 - estimated_floor)
                positive = [(v['ratio'], 1) for v in pool if not v['floor']]
                knots = trained['positive_ratios']
                if knots:
                    positive += [(v, mass * (1 - trained['minimum_width_floor']) / len(knots)) for v in knots]
                if positive:
                    requested = weighted_quantile(positive, positive_q)
        elif family == 'feedback' and len(pool) >= candidate['minimum_mature']:
            requested = math.exp(feedback[state])
        requested = min(candidate['maximum_correction'], max(candidate['minimum_correction'], requested))
        last, step = correction[state], candidate['maximum_step']
        factor = min(last * (1 + step), max(last * (1 - step), requested))
        correction[state] = factor
        raw_width = max(1, math.ceil(base * static * factor))
        width = min(prior['maximum_width_ppm'], raw_width)
        shadow = r['move'] < r['entry'] * width // 1_000_000 if r['valid'] else None
        output.append(dict(p, width_ppm=width, capped=raw_width > prior['maximum_width_ppm'],
                           shadow_survived=shadow, survived=None if p['paused'] else shadow,
                           nonfrozen_correction=factor, nonfrozen_mature=len(pool), nonfrozen_floor=estimated_floor))
        if family != 'static':
            pending.append(dict(prediction=p, state=state, base=base, width=width,
                                mature_at=r['expiry'] + candidate['maturity_delay_ms']))
    return output
