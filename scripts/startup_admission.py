"""Causal frozen-state entry guards for offline reference-window research."""
from collections import deque
import math
from statistics import mean

from adaptive_corridor import required_width


def spec(name, *, warm=12, memory=120, age=4 * 3_600_000, resume=None,
         recovery=0, shadow=False, idle=None, reset=False, baseline=False,
         fast=None, risky=False, ewma=False):
    return dict(name=name, warmup=warm, memory=memory, maximum_age_ms=age,
                enter_floor=.53, resume_floor=resume, recovery_outcomes=recovery,
                shadow_guard=shadow, shadow_minimum=30, shadow_enter=(.38, .58),
                shadow_resume=(.43, .53), idle_limit_ms=idle, reset_on_missing=reset,
                baseline=baseline, maturity_delay_ms=30_000, fast_memory=fast,
                risky_startup=risky, time_weighted=ewma)


SPECS = (
    spec('previous_floor_53', baseline=True),
    spec('warm12_floor120'),
    spec('warm30_floor120', warm=30),
    spec('warm12_floor60', memory=60),
    spec('warm12_floor30', memory=30),
    spec('warm30_floor30', warm=30, memory=30),
    spec('warm12_floor30_age1h', memory=30, age=3_600_000),
    spec('warm12_hysteresis30', memory=30, resume=.43, recovery=6),
    spec('warm12_hysteresis60', memory=60, resume=.48, recovery=6),
    spec('warm30_hysteresis30', warm=30, memory=30, resume=.43, recovery=6),
    spec('warm12_hysteresis30_recover2', memory=30, resume=.48, recovery=2),
    spec('warm12_shadow30', memory=30, shadow=True, recovery=6),
    spec('warm30_shadow60', warm=30, memory=60, shadow=True, recovery=6),
    spec('warm12_floor30_idle60', memory=30, idle=60_000),
    spec('warm12_floor30_reset', memory=30, reset=True),
    spec('risk_warm12_floor30', memory=30, risky=True),
    spec('warm12_dual30_120', fast=30),
    spec('risk_warm12_dual30_120', fast=30, risky=True),
    spec('risk_warm30_dual30_120', warm=30, fast=30, risky=True),
    spec('risk_warm12_dual30_shadow', fast=30, risky=True, shadow=True, recovery=6),
    spec('risk_warm12_ewma30m', risky=True, ewma=True),
)


def admit(values, rule):
    """Change entry admission only; keep all fixed-price shadow paths learning.

    Outcome validity, movement and survival are inspected only after expiry plus
    30 seconds. Missing pre-entry features never become a quote. All non-frozen
    decisions retain their previous policy. Frozen gates replace the previous
    frozen gate, allowing shorter memories to recover from stale evidence.
    """
    pending, pool = deque(), deque()
    output, session, previous_at = [], None, None
    mature_total = floor_since = shadow_since = 0
    floor_latched = shadow_latched = False
    for p in values:
        r, at = p['row'], p['row']['start']
        if previous_at is not None and at < previous_at:
            raise ValueError('chronological predictions required')
        previous_at = at
        if session != r['period']:
            session = r['period']
            pending.clear(); pool.clear()
            mature_total = floor_since = shadow_since = 0
            floor_latched = shadow_latched = False
        while pending and pending[0]['mature_at'] <= at:
            old = pending.popleft()['prediction']
            if old['row']['valid']:
                pool.append(dict(expiry=old['row']['expiry'],
                                 floor=required_width(old['row']) <= 1,
                                 survived=old['shadow_survived']))
                mature_total += 1
        while pool and (len(pool) > rule['memory'] or at - pool[0]['expiry'] > rule['maximum_age_ms']):
            pool.popleft()
        if p['width_ppm'] is None and rule['reset_on_missing']:
            pending.clear(); pool.clear()
            mature_total = floor_since = shadow_since = 0
            floor_latched = shadow_latched = False
        slow_floor = mean(item['floor'] for item in pool) if pool else None
        if pool and rule['time_weighted']:
            weights = [math.exp(-(at - item['expiry']) / (30 * 60_000)) for item in pool]
            slow_floor = sum(w * item['floor'] for w, item in zip(weights, pool)) / sum(weights)
        fast_pool = list(pool)[-rule['fast_memory']:] if rule['fast_memory'] else list(pool)
        fast_floor = mean(item['floor'] for item in fast_pool) if fast_pool else None
        floor = max(slow_floor, fast_floor) if pool and rule['fast_memory'] else slow_floor
        shadow_rate = mean(item['survived'] for item in fast_pool) if fast_pool else None
        reasons = []
        frozen = p['width_ppm'] is not None and r['activity_state'] == 'frozen'
        risky = frozen and (r['activity_features']['idle_ms'] >= 60_000
                            or r['activity_features']['empty_bins_300'] >= .5)
        if rule['baseline'] or not frozen:
            paused = p['paused']
            reasons = [p['floor_reason']] if paused else []
        else:
            need_warmup = (len(pool) < rule['warmup'] and
                           (not rule['risky_startup'] or risky or floor_latched or shadow_latched))
            if need_warmup:
                reasons.append('frozen_evidence_warmup')
            elif len(pool) >= rule['warmup']:
                if rule['resume_floor'] is None:
                    if floor > rule['enter_floor']:
                        reasons.append('recent_minimum_width_floor')
                else:
                    if not floor_latched and floor > rule['enter_floor']:
                        floor_latched, floor_since = True, mature_total
                    elif (floor_latched and floor <= rule['resume_floor']
                          and mature_total - floor_since >= rule['recovery_outcomes']):
                        floor_latched = False
                    if floor_latched:
                        reasons.append('floor_hysteresis')
            if rule['shadow_guard'] and len(pool) >= rule['shadow_minimum']:
                low, high = rule['shadow_enter']
                if not shadow_latched and not low <= shadow_rate <= high:
                    shadow_latched, shadow_since = True, mature_total
                elif (shadow_latched and rule['shadow_resume'][0] <= shadow_rate <= rule['shadow_resume'][1]
                      and mature_total - shadow_since >= rule['recovery_outcomes']):
                    shadow_latched = False
            if shadow_latched:
                reasons.append('recent_shadow_calibration')
            if (rule['idle_limit_ms'] is not None
                    and r['activity_features']['idle_ms'] >= rule['idle_limit_ms']):
                reasons.append('pre_entry_idle_limit')
            paused = bool(reasons)
        output.append(dict(p, paused=paused, floor_reason=';'.join(reasons),
                           survived=None if paused else p['shadow_survived'],
                           admission_mature=len(pool), admission_floor=floor,
                           admission_slow_floor=slow_floor, admission_fast_floor=fast_floor,
                           admission_risky_entry=risky,
                           admission_shadow_survival=shadow_rate,
                           admission_warmup=frozen and 'frozen_evidence_warmup' in reasons))
        if frozen:
            pending.append(dict(prediction=p, mature_at=r['expiry'] + rule['maturity_delay_ms']))
    return output
