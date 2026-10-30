"""Isolate bursty calibration errors while keeping the quantile models fixed."""
from collections import deque
import math

from gap_quantile import SPEC as BASE_SPEC, Tracker, bucket, forecast
from gap_quantile import all_series as previous_series
from nonfrozen_pricing import STATES

MODES = ('bursty', 'shape', 'shrunk')
VARIANTS = ('retained_pool', 'timing_static', 'timing_adaptive', 'gap_static', 'gap_adaptive') + tuple(
    source + '_' + mode for source in ('timing', 'gap') for mode in MODES)
SPEC = dict(base=BASE_SPEC, modes=MODES, models='Frozen preceding timing and gap fits; no refitting',
            bursty='One controller, matured bursty references only',
            shape='Separate cooling/balanced/fresh controllers, no cross-shape transfer',
            shrunk='Bursty controller with count/(count+12) prediction and gradient weight; neutral prior',
            shared_control='Exact preceding non-frozen parent/bursty-child blend',
            admission='Fixed previous frozen masks; all existing bursty quotes retained')


class BurstyTracker(Tracker):
    def __init__(self, mode):
        super().__init__()
        if mode not in MODES + ('shared',):
            raise ValueError('unknown feedback transfer mode')
        self.mode = mode

    def correction(self, row, at):
        if self.mode == 'shared':
            return super().correction(row, at)
        if row['activity_state'] != 'bursty':
            return 0., []
        key = 'bursty:' + bucket(row) if self.mode == 'shape' else 'bursty'
        state = self.state(key, at)
        weight = 1.
        if self.mode == 'shrunk':
            count = len(state['times'])
            weight = count / (count + BASE_SPEC['child_prior'])
        return weight * state['delta'], [(key, weight)]


def series(values, model, mode):
    output = []; pending = deque(); tracker = BurstyTracker(mode); period = previous = None
    for p in values:
        row, at = p['row'], p['row']['start']
        if previous is not None and at < previous:
            raise ValueError('chronological references required')
        previous = at
        if period != row['period']:
            period = row['period']; pending.clear(); tracker = BurstyTracker(mode)
        while pending and pending[0]['mature_at'] <= at:
            old = pending.popleft()
            if old['row']['valid'] and at - old['row']['expiry'] <= BASE_SPEC['maximum_age_ms']:
                tracker.learn(old)
        eligible = p['width_ppm'] is not None and row['activity_state'] in STATES and row.get('oracle_gap') is not None
        q, risk, delta, weights, components = None, None, 0., [], []
        result = dict(p)
        if eligible:
            q, risk = forecast(p, model)
            delta, weights = tracker.correction(row, at)
            components = [dict(key=key, weight=weight, log_correction=tracker.states[key]['delta'],
                               mature=len(tracker.states[key]['times'])) for key, weight in weights]
            raw = q if delta == 0 else math.ceil(q * math.exp(delta))
            width = max(1, min(BASE_SPEC['maximum_width'], raw))
            if row['activity_state'] == 'bursty':
                hit = row['move'] < row['entry'] * width // 1_000_000 if row['valid'] else None
                result.update(width_ppm=width, shadow_survived=hit, survived=None if p['paused'] else hit,
                              capped=raw > BASE_SPEC['maximum_width'])
            # Empty weights mean there is no learning or transfer from this state.
            if weights:
                pending.append(dict(row=row, width=width, weights=weights,
                                    mature_at=row['expiry'] + BASE_SPEC['maturity_delay_ms']))
        result.update(gap_floor_risk=risk, gap_forecast=q, gap_log_correction=delta,
                      gap_supported=eligible, gap_controller_weights=weights, feedback_components=components)
        output.append(result)
    return output


def all_series(values, models):
    result = previous_series(values, models)
    # Shared replay also records the two contributions without changing outputs.
    for source in ('timing', 'gap'):
        result[source + '_adaptive'] = series(values, models[source], 'shared')
        for mode in MODES:
            result[source + '_' + mode] = series(values, models[source], mode)
    return result
