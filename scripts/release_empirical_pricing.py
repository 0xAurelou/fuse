"""Causal fitted challenger on previously inspected release oracle paths.

Empirical ranks are development estimates, not statistical margin guarantees.
No native admission, live quote service or production policy is changed here.
"""
from bisect import bisect_right
from collections import defaultdict, deque
import hashlib
import json

from release_pricing import Counts, EDGES, PAYOUTS, STRATEGIES, selected

PPB = 1_000_000_000
SPEC = dict(version='release-empirical-cdf-v1', minimum_references=200,
    minimum_dates=3, minimum_empirical_survivors=20, maximum_width_ppb=50_000_000,
    assets=['BTC', 'ETH', 'HYPE'], payouts=PAYOUTS, edge_bps=EDGES,
    fit='Freeze once at UTC day start using strictly earlier matured immediate '
        'healthy reference paths, including paths a previous policy refused.',
    context='Choose one common distribution for all payouts: exact prior activity, '
        'mark gap and quote age; then activity; then global. Each needs 200 '
        'references across three earlier observed dates. No payout-specific fallback.',
    quantile='Largest integer ppb below the first disallowed order statistic; '
        'touches lose. Require at least twenty actual historical survivors at '
        'the final quantized width, not twenty expected or extrapolated events.',
    surface='Higher offered payouts have strictly narrower ppb widths AND integer '
        'price deltas. Refused payouts do not become offers or successful calibration.',
    inference='Empirical counts on nonconsecutive previously inspected dates; '
        'not independent windows, future confidence bounds, demand or approval.')


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def context(row):
    gap = row['mark_gap_ppm']
    return (row['prior_state'], 'unknown' if gap is None else 'low' if gap <= 100 else 'high',
            'fresh' if row['quote_age_ms'] is not None and row['quote_age_ms'] <= 1000 else 'older')


def threshold(row):
    """Minimum ppb width making the observed integer path survive, exactly."""
    if not row['accepted'] or not row['valid'] or row['entry'] <= 0 or row['move'] < 0:
        raise ValueError('clean accepted reference required')
    return ((row['move']+1)*PPB+row['entry']-1)//row['entry']


def reference(row):
    if row['delay_ms'] != 0 or not row['accepted'] or not row['valid'] or row['prior_state'] == 'missing_history':
        return None
    return dict(day=row['day'], maturity=row['expiry']+30_000,
                context=context(row), threshold=threshold(row))


def fit(references, cutoff):
    groups = defaultdict(list)
    for r in references:
        if r['maturity'] >= cutoff:
            continue
        for key in (('exact', *r['context']), ('activity', r['context'][0]), ('global',)):
            groups[key].append(r)
    result = {}
    for key, rows in groups.items():
        values = sorted(r['threshold'] for r in rows)
        dates = sorted({r['day'] for r in rows})
        result[key] = dict(thresholds=values, dates=dates,
            maximum_label_maturity_ms=max(r['maturity'] for r in rows),
            references=len(values), threshold_sha256=digest(values))
    return result


def choose(model, row):
    c = context(row)
    for key in (('exact', *c), ('activity', c[0]), ('global',)):
        d = model.get(key)
        if d and d['references'] >= SPEC['minimum_references'] and len(d['dates']) >= SPEC['minimum_dates']:
            return key, d
    return (), None


def surface(model, row, edge):
    if edge not in EDGES:
        raise ValueError('undeclared target edge')
    key, distribution = choose(model, row)
    common = dict(training_group=list(key), training_references=distribution['references'] if distribution else 0,
        training_dates=distribution['dates'] if distribution else [],
        maximum_label_maturity_ms=distribution['maximum_label_maturity_ms'] if distribution else None,
        threshold_sha256=distribution['threshold_sha256'] if distribution else None)
    previous_width, previous_delta = PPB, None
    offers = {}
    for m in PAYOUTS:
        q = dict(multiplier=m, edge_bps=edge, offered=False, reason='', width_ppb=None,
                 delta=None, training_survivors=None, **common)
        if not row['quote_available'] or row['prior_state'] == 'missing_history':
            q['reason'] = 'unavailable_preentry_context'
        elif distribution is None:
            q['reason'] = 'insufficient_earlier_reference_dates'
        else:
            values = distribution['thresholds']
            rank = len(values)*(10_000-edge)//(10_000*m)
            if rank < SPEC['minimum_empirical_survivors']:
                q['reason'] = 'insufficient_tail_reference_rank'
            else:
                width = min(values[rank]-1, SPEC['maximum_width_ppb'], previous_width-1)
                if previous_delta is not None:
                    width = min(width, (previous_delta*PPB-1)//row['entry'])
                delta = row['entry']*width//PPB
                wins = bisect_right(values, width)
                q['training_survivors'] = wins
                if width <= 0 or delta <= 0:
                    q['reason'] = 'native_minimum_width_exceeds_empirical_budget'
                elif row['entry']+delta > 10**15:
                    q['reason'] = 'native_arithmetic_limit'
                elif wins < SPEC['minimum_empirical_survivors']:
                    q['reason'] = 'insufficient_observed_tail_survivors'
                else:
                    if wins*(10_000*m) > len(values)*(10_000-edge):
                        raise AssertionError('empirical risk budget exceeded')
                    q.update(offered=True, reason='offered', width_ppb=width, delta=delta)
                    previous_width, previous_delta = width, delta
        offers[m] = q
    return offers


def replay(rows, offers, multiplier, edge):
    if len(rows)!=len(offers):
        raise ValueError('complete quote forecast grid required')
    counts = {s: Counts() for s in STRATEGIES}
    pending, last, codes = deque(), None, bytearray()
    reasons = defaultdict(int)
    oracle_available = 0
    for row, q in zip(rows, offers):
        if q['multiplier']!=multiplier or q['edge_bps']!=edge:
            raise ValueError('forecast payout/edge mismatch')
        while pending and pending[0][0] <= row['quote_at']:
            _, last = pending.popleft()
        oracle_available += row['quote_available']
        reasons[q['reason']] += 1
        actual = row if q['offered'] else dict(row, quote_available=False, accepted=False)
        outcome = row['move'] < q['delta'] if q['offered'] and row['accepted'] and row['valid'] else None
        codes.append((3 if outcome else 2) if outcome is not None else 1 if actual['accepted'] else 0)
        for strategy, c in counts.items():
            c.add(actual, selected(strategy, actual, last), outcome)
        if actual['accepted'] and outcome is not None:
            pending.append((row['expiry']+30_000, outcome))
    return counts, codes, dict(reasons), oracle_available
