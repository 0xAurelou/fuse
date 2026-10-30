"""Conservative flat-risk overlay: preserve the old CDF, only tighten or refuse."""
from flat_aware_payout import floor_forecast,quote as base_quote,veto
from trial_payout import available

SPEC=dict(version='flat-risk-overlay-v1',name='conservative_overlay',
    floor='max(previous asset logistic estimate, asset calendar/activity empirical estimate), separately for zero and minimum-width survival; minimum head also dominates zero head.',
    movement='Unchanged previous activity-conditioned positive CDF and slow volatility anchor. No new movement grouping.',
    guard='Same pre-entry flat veto and fixed 1000x recovery gate as flat-aware v1.',
    invariant='Every new offer must have been offered previously, with width no larger than the previous quote. Checked before attaching outcomes.',
    development='Follow-up motivated by already inspected flat-aware development results, including HYPE regression. No pristine holdout or model selection claim.',
    no_promotion=True)


def quote(row,multiplier,packet,predictors,baseline):
    supported=available(row,'calendar_liquidity');forecast=dict(baseline)
    if supported:
        empirical=floor_forecast(row,packet['floor'],True)
        forecast.update(p0=max(baseline['p0'],empirical['p0']),floor=max(baseline['floor'],empirical['floor'],baseline['p0'],empirical['p0']))
    result=base_quote(row,multiplier,'previous_formula',packet,predictors,forecast)
    guard=veto(row,multiplier,True) if supported else None
    if guard:result.update(offered=False,survived=None,flat_guard=guard,reason=';'.join(filter(None,(result['reason'],guard))))
    previous=base_quote(row,multiplier,'previous_formula',packet,predictors,baseline)
    if result['offered'] and (not previous['offered'] or result['width']>previous['width']):raise ValueError('Conservative quote invariant failed')
    return dict(result,previous_offered=previous['offered'],previous_width_ppm=previous['width'])
