"""Past-only native book joins and original oracle-path labels for the trial."""
from collections import Counter
import gzip
import json
import statistics

from fetch_tardis_liquidity_trial import ASSETS,CHANNELS,digest,origin
from historical_liquidity import snapshot
from oracle_gap_features import attach,positive,raw_timestamp
from research_market_regimes import price_units
from research_raw_flat_panels import prepare_rows


def parse_day(files,root,day):
    start=origin(day);end=start+86400000;entry=start;previous=None
    observed={a:[] for a in ASSETS};contexts={a:[] for a in ASSETS}
    markers={a:[] for a in ASSETS};waiting={a:False for a in ASSETS}
    book_times={a:[] for a in ASSETS};book_levels={a:Counter() for a in ASSETS}
    states={a:None for a in ASSETS};joined={a:[] for a in ASSETS};counts=Counter()
    def emit(at):
        for asset in ASSETS:
            value,reason=snapshot(states[asset],at)
            joined[asset].append(dict(asset=asset,period=day,start=at,liquidity=value,join_reason=reason))
    for item in sorted(files,key=lambda r:r['at_ms']):
        if item['day']!=day or item['status']!='downloaded' or digest(root/item['path'])!=item['sha256']:
            raise ValueError('Trial raw slice identity or hash differs')
        with gzip.open(root/item['path'],'rt') as stream:
            for line in stream:
                if not line.strip():
                    states={a:None for a in ASSETS};waiting={a:True for a in ASSETS}
                    counts['disconnect_markers']+=1;continue
                timestamp,payload=line.rstrip('\n').split(' ',1);at=raw_timestamp(timestamp)
                if not item['at_ms']<=at<item['at_ms']+item['duration_ms'] or previous is not None and at<previous:
                    raise ValueError('Trial raw receipt outside slice or regresses')
                previous=at
                while entry<=at and entry<end:emit(entry);entry+=30000
                message=json.loads(payload);channel=message['channel'];data=message['data'];asset=data.get('coin')
                if channel not in CHANNELS or asset not in ASSETS:
                    raise ValueError('Unexpected trial channel or market')
                counts[asset+':'+channel]+=1
                if channel=='l2Book':
                    if data.get('fast',False):raise ValueError('Fast five-level books are not native twenty-level history')
                    book_times[asset].append(at)
                    book_levels[asset][str(tuple(len(side) for side in data['levels']))]+=1
                    if states[asset] and data['time']<states[asset][1]['time']:
                        states[asset]=None;counts[asset+':book_clock_resets']+=1
                    else:states[asset]=(at,data)
                else:
                    ctx=data['ctx'];px=price_units(ctx['oraclePx'])
                    if px<=0:raise ValueError('Invalid oracle price')
                    if waiting[asset]:markers[asset].append(dict(known_at=at));waiting[asset]=False
                    observed[asset].append((at,px))
                    contexts[asset].append((at,px,positive(ctx.get('markPx')),positive(ctx.get('midPx'))))
    while entry<end:emit(entry);entry+=30000
    rows={};profiles=[]
    for asset in ASSETS:
        if not observed[asset]:raise ValueError('Missing oracle history for selected asset/day')
        if waiting[asset]:markers[asset].append(dict(known_at=end-1))
        panel=dict(day=day,fetch_start=start,fetch_end=end)
        part=attach(prepare_rows(observed[asset],panel,markers[asset]),contexts[asset],start)
        if len(part)!=2880 or [r['start'] for r in part]!=list(range(start,end,30000)):
            raise ValueError('Trial thirty-second grid differs')
        for r,b in zip(part,joined[asset]):
            if r['start']!=b['start']:raise ValueError('Oracle/book entry grids differ')
            r.update(asset=asset,split='consecutive_development',liquidity=b['liquidity'],join_reason=b['join_reason'])
        rows[asset]=part
        clean=[r for r in part if r['valid'] and r['adaptive_features'] is not None]
        matched=[r for r in clean if r['liquidity'] is not None]
        gaps=[b[0]-a[0] for a,b in zip(observed[asset],observed[asset][1:])]
        book_gaps=[b-a for a,b in zip(book_times[asset],book_times[asset][1:])]
        profiles.append(dict(asset=asset,day=day,grid=2880,oracle_messages=len(observed[asset]),
            oracle_price_changes=sum(a[1]!=b[1] for a,b in zip(observed[asset],observed[asset][1:])),
            oracle_gap_median_ms=statistics.median(gaps) if gaps else None,
            oracle_gap_max_ms=max(gaps,default=None),oracle_gaps_over_8s=sum(g>8000 for g in gaps),
            book_messages=len(book_times[asset]),book_gap_median_ms=statistics.median(book_gaps) if book_gaps else None,
            book_gap_max_ms=max(book_gaps,default=None),book_visible_levels=dict(book_levels[asset]),
            disconnect_markers=len(markers[asset]),clean_oracle_paths=len(clean),matched_paths=len(matched),
            matched_zero_motion=sum(r['move']==0 for r in matched),
            book_unavailability=dict(Counter(r['join_reason'] for r in clean if r['liquidity'] is None)),
            raw_counts=dict(counts)))
    return rows,profiles
