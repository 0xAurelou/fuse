"""Later chronological folds and short-memory frozen-state admission rules."""
from copy import deepcopy
from datetime import datetime, timezone

from fetch_temporal_raw import PLAN
from full_raw_pipeline import price, mask as old_mask
from startup_admission import spec, admit

STAGES=tuple(PLAN['stages'])
POLICIES=tuple(PLAN['policies'])
VARIANTS=tuple(stage+':'+policy for stage in STAGES for policy in POLICIES)
RULES={name:spec(name,warm=6,memory=12 if name=='warm6_floor12' else 30)
       for name in ('warm6_floor12','warm6_floor30')}


def apply_policy(prices,base,policy):
    if policy not in RULES:return old_mask(prices,base,policy)
    decisions=admit(base,RULES[policy])
    if len(prices)!=len(decisions):raise ValueError('quote/decision alignment differs')
    return [dict(p,paused=m['paused'],floor_reason=m['floor_reason'],
                 survived=None if m['paused'] else p['shadow_survived']) for p,m in zip(prices,decisions)]


def sessions(day,rows,source,split):
    origin=int(datetime.fromisoformat(day).replace(tzinfo=timezone.utc).timestamp()*1000)
    intervals=[dict(start=origin+hour*3600000,end=origin+(hour+8)*3600000,hour=hour) for hour in (0,8,16)]
    result=[dict(id=source+':'+day+':continuous',source=source,period=day,split=split,
                 mode='continuous',intervals=intervals,rows=rows)]
    for interval in intervals:
        result.append(dict(id=f'{source}:{day}:restart:{interval["hour"]:02}',source=source,period=day,
            split=split,mode='restart',intervals=[interval],
            rows=[r for r in rows if interval['start']<=r['start']<interval['end']]))
    return result


def date_rows(normalized,raw,dates):
    if len(set(dates))!=len(dates):raise ValueError('unique scoring dates required')
    return [(day,raw[day] if day in raw else [r for r in normalized if r['period']==day],
             'raw_temporal' if day in raw else 'normalized_temporal') for day in dates]


def all_predictions(rows,models):
    result={}
    for stage in STAGES:
        base,prices=price(rows,models[stage])
        for policy in POLICIES:result[stage+':'+policy]=apply_policy(prices,base,policy)
    return result
