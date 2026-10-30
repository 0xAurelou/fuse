"""Expanding-origin payout research with no fitted/selected future coefficients."""
from datetime import datetime, timezone

from payout_empirical import (EmpiricalPredictor, calibrated, distribution,
                              fit_calibrator, key)
from payout_risk import clean_training, fit_risk, required_width, risk
from research_payout_risk import summary, risk_metrics
from screen_payout_candidates import assess, CRITERIA

FAMILIES = ('timing', 'calendar')
VARIANTS = ('minimum_width_floor',) + tuple(
    f'{family}_{mode}_cdf' for family in FAMILIES for mode in ('raw', 'cal32'))
SPEC = dict(version='payout-walkforward-v1', warmup_dates=6, families=FAMILIES,
            ridge=.003, calibration_prior=32, movement_family='activity',
            anchor='slow', level_factor=1., gate_factor=1.,
            minimum_positive_tail_mass=20, multipliers=[100, 1000],
            refit='Every sampled date after six warmup dates; all and only earlier matured asset paths',
            calibration='All clean earlier walk-forward forecasts, including refused paths. No current-date or in-sample forecasts. Unsupported score bins retain raw probabilities.',
            policy_selection='None. Fixed paired timing/calendar, raw/calibrated comparisons; no future-selected template reused.',
            evaluation='Each asset/start once per payout/variant. Prior train/validation/test labels ignored.',
            screen=CRITERIA, no_promotion=True,
            limitations='Previously inspected monthly development archive, not fresh or continuous evidence. Counts are dependent, screens descriptive, no liquidity or net economics measured.')


def schedule(rows, asset):
    if not rows or any(r['asset'] != asset for r in rows):
        raise ValueError('one nonempty asset required')
    if any(a['start'] >= b['start'] for a,b in zip(rows, rows[1:])):
        raise ValueError('unique chronological entries required')
    dates = sorted({r['period'] for r in rows})
    if any(datetime.fromtimestamp(r['start']/1000, timezone.utc).date().isoformat() != r['period'] for r in rows):
        raise ValueError('entry date differs')
    if len(dates) <= SPEC['warmup_dates']:
        raise ValueError('more than six sampled dates required')
    return dates[SPEC['warmup_dates']:]


def fit_origin(rows, asset, cutoff, references):
    # Filtering is explicit, but clean_training still enforces maturity/ordering.
    earlier = [r for r in rows if r['period'] < cutoff]
    clean = clean_training(earlier, asset, cutoff)
    boundary = int(datetime.fromisoformat(cutoff).replace(tzinfo=timezone.utc).timestamp()*1000)
    for family in FAMILIES:
        refs = references[family]
        if any(r['period'] >= cutoff or r['expiry']+30000 >= boundary for r in refs):
            raise ValueError('calibration labels must mature before origin')
        if len({r['start'] for r in refs}) != len(refs):
            raise ValueError('duplicate calibration reference')
    groups = {}
    for r in clean:
        groups.setdefault(key(r, 'activity'), []).append(r)
    movement = dict(asset=asset, cutoff=cutoff,
                    training_dates=sorted({r['period'] for r in clean}),
                    anchors={'slow':dict(global_distribution=distribution(clean,'slow'),
                        families={'activity':{name:distribution(part,'slow') for name,part in sorted(groups.items())}})})
    if movement['anchors']['slow']['global_distribution']['n'] < 100:
        raise ValueError('at least 100 positive training paths required')
    return dict(asset=asset, cutoff=cutoff, movement=movement,
                risk={family:fit_risk(earlier,asset,cutoff,family,SPEC['ridge']) for family in FAMILIES},
                calibrators={family:fit_calibrator(references[family],32) for family in FAMILIES},
                calibration_counts={family:len(references[family]) for family in FAMILIES})


def forecasts(row, packet):
    raw = {family:risk(row,packet['risk'][family]) if row['adaptive_features'] is not None else (None,None)
           for family in FAMILIES}
    result = {}
    for family in FAMILIES:
        result[family+'_raw_cdf'] = dict(p0=raw[family][0],floor=raw[family][1],calibrated0=False,calibrated_floor=False)
        result[family+'_cal32_cdf'] = calibrated(raw[family],packet['calibrators'][family])
    return raw,result


def quote(row, forecast, multiplier, variant, predictor):
    if variant == 'minimum_width_floor':
        width = 1 if row['adaptive_features'] is not None else None
        reasons = ['missing_history'] if width is None else []
        if width is not None and row['entry']*width//1000000 <= 0:
            reasons.append('unrepresentable_barrier')
        result = dict(width=width,offered=not reasons,reason=';'.join(reasons),
                      positive_q=None,tail_mass=None,tail_supported=None,child_supported=None)
    else:
        result = predictor.quote(row,forecast,multiplier,'activity','slow',1.,1.)
    # Outcomes are attached after the quote, never used by the admission rule.
    width = result['width']
    shadow = bool(row['move'] < row['entry']*width//1000000) if row['valid'] and width is not None else None
    return dict(result,p0=forecast['p0'],floor=forecast['floor'],
                calibrated0=forecast['calibrated0'],calibrated_floor=forecast['calibrated_floor'],
                shadow=shadow,survived=shadow if result['offered'] else None)


def reference(row, raw, family):
    return dict(asset=row['asset'], start=row['start'], expiry=row['expiry'], period=row['period'],
                family=family,p0=raw[0],floor=raw[1],zero=row['move']==0,
                minimum=required_width(row)<=1)


def floor_bound(n, wins, multiplier, target=True):
    """Oracle bound: even an omniscient rejection policy cannot keep more paths.

    If K quotes are kept, at least max(0, wins-(n-K)) unavoidable winners remain.
    Exact integer arithmetic prevents rounding a boundary into feasibility.
    """
    if not 0 <= wins <= n or multiplier <= 1:
        raise ValueError('invalid floor cohort or payout')
    numerator,denominator = (19,20*multiplier) if target else (1,multiplier)
    return min(n,(n-wins)*denominator//(denominator-numerator))


def metrics(rows, records, multiplier):
    def summarize(part, values):
        # The minimum-width diagnostic has no fitted probability forecast.
        result = summary(part,[dict(p,floor=p['floor'] if p['floor'] is not None else 0.) for p in values],multiplier)
        known = [p['floor'] for p in values if p['offered'] and p['shadow'] is not None and p['floor'] is not None]
        result['predicted_floor_mean'] = sum(known)/len(known) if known else None
        return result
    pooled = summarize(rows,records)
    days = sorted({r['period'] for r in rows})
    daily = []
    for day in days:
        pairs = [(r,p) for r,p in zip(rows,records) if r['period']==day]
        daily.append(dict(period=day,**summarize([r for r,p in pairs],[p for r,p in pairs])))
    availability = [p['availability'] for p in daily]
    minimum = min(availability, default=0.) if all(v is not None for v in availability) else 0.
    return dict(pooled=pooled,daily=daily,minimum_daily_availability=minimum,
                all_reference_risk=risk_metrics(rows,records))


def research_screen(result, multiplier, variant):
    pooled = result['pooled']
    candidate = dict(policy={'name':variant},index=VARIANTS.index(variant),
        daily=result['daily'],minimum_daily_availability=result['minimum_daily_availability'],
        pooled_survival=pooled['survival'],availability=pooled['availability'],
        offered=pooled['offered'],eligible=pooled['eligible'])
    assessment = assess(candidate,multiplier)
    reasons = list(assessment['reasons'])
    if variant == 'minimum_width_floor':
        reasons.append('lower_bound_diagnostic_only')
    return dict(qualifies=not reasons,reasons=reasons,no_promotion=True,
                target_expected_wins=pooled['target_expected_wins'])


def floor_summary(rows, multiplier):
    clean = [r for r in rows if r['valid'] and r['adaptive_features'] is not None]
    n = len(clean); zero = sum(r['move']==0 for r in clean)
    minimum = sum(required_width(r)<=1 for r in clean)
    return dict(eligible=n,zero_motion=zero,minimum_width_wins=minimum,
                zero_motion_rate=zero/n if n else None,
                universal_maximum_kept_at_target=floor_bound(n,zero,multiplier),
                universal_maximum_kept_at_break_even=floor_bound(n,zero,multiplier,False),
                research_minimum_maximum_kept_at_target=floor_bound(n,minimum,multiplier),
                target_expected_wins_if_all_offered=n*.95/multiplier)
