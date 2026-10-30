"""Prior-only raw replacement; fixed engine, date weights and pricing algorithms."""
from collections import Counter
from datetime import datetime, timezone

from bursty_episodes import SPECS, fit_model
from nonfrozen_pricing import SPECS as BASE_SPECS, reprice
from research_bursty_episodes import evaluate
from research_startup_admission import priced

METHODS = ('engine_floor10', 'floor10_burst_pool120', 'burst_clock120',
           'burst_cdf60', 'episode_kernel')
PRIOR_SOURCES = ('normalized', 'raw_replacement')
VARIANTS = tuple((source, method) for source in PRIOR_SOURCES for method in METHODS
                 if source == 'normalized' or method != 'engine_floor10')


def name(source, method):
    return source + ':' + method


def training_rows(original, raw_days, periods, cutoff, use_raw):
    """Exactly one version of each date, strictly before the scoring date."""
    if len(set(periods)) != len(periods) or any(day >= cutoff for day in periods):
        raise ValueError('training periods must be unique and strictly before cutoff')
    selected, provenance = [], []
    for day in sorted(periods):
        raw = use_raw and day in raw_days
        rows = raw_days[day] if raw else [r for r in original if r['period'] == day]
        if not rows or any(r['period'] != day for r in rows):
            raise ValueError('missing or mislabelled training day')
        rows = sorted(rows, key=lambda r: r['start'])
        if len({r['start'] for r in rows}) != len(rows):
            raise ValueError('duplicate reference entry in training day')
        selected.extend(rows)
        provenance.append(dict(period=day, source='raw' if raw else 'normalized', rows=len(rows)))
    if any(a['start'] >= b['start'] for a, b in zip(selected, selected[1:])):
        raise ValueError('training must be globally chronological')
    boundary=int(datetime.fromisoformat(cutoff).replace(tzinfo=timezone.utc).timestamp()*1000)
    if any(r['expiry']+30_000 >= boundary for r in selected):
        raise ValueError('training outcome must mature before cutoff')
    return selected, provenance


def floor_values(values, engine):
    # This engine family does not read a prior. Always recompute with the target engine.
    return reprice(values, None, next(c for c in BASE_SPECS if c['name']=='engine_floor10'), engine)


def fit_bundle(original, raw_days, periods, cutoff, engine, overlay, use_raw):
    rows, provenance = training_rows(original, raw_days, periods, cutoff, use_raw)
    values = floor_values(priced(rows, engine, overlay), engine)
    model = fit_model(values)
    counts = Counter(p['row']['period'] for p in values if p['shadow_survived'] is not None
                     and p['row']['activity_state']=='bursty')
    return dict(training_periods=sorted(periods), cutoff=cutoff, provenance=provenance,
                bursty_windows_by_period=dict(sorted(counts.items())), model=model)


def replay(base, model, method):
    return evaluate({'engine_floor10':base}, model, next(c for c in SPECS if c['name']==method))
