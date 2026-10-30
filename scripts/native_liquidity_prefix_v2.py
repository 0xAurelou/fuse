"""Read-only finalized receipt prefixes and ETH oracle/book replay rows."""
from collections import Counter
from datetime import datetime,timezone
import gzip
import hashlib
import json

from historical_liquidity import snapshot
from liquidity_archive import canonical,check_row,sha
from oracle_gap_features import attach,positive
from research_market_regimes import price_units
from research_raw_flat_panels import prepare_rows


from native_liquidity_prefix import records,snapshot_index,verify_books


def parse_eth(root,packet):
    observed=[];contexts=[];markers=[];books=[];book=None;joined={};counts=Counter();first=None;last=None;entry=None;previous=None;raw_previous=None
    def emit(at):
        value,why=snapshot(book,at);joined[at]=(value,why)
    for r in records(root,packet):
        at=r['received_at_ns']//1000000;kind=r['kind'];counts[kind]+=1
        if raw_previous is not None and at<raw_previous:counts['raw_receipt_timestamp_backsteps']+=1
        raw_previous=at
        if kind=='websocket':
            m=json.loads(r['payload_text']);channel=m.get('channel');d=m.get('data')
            if channel not in ('activeAssetCtx','l2Book') or not isinstance(d,dict) or d.get('coin')!='ETH':continue
        elif kind not in ('session_start','session_end','connected','disconnect','host_or_clock_gap'):continue
        if previous is not None and at<previous:raise ValueError('Regressing ETH pricing/control receipt requires a separate episode policy')
        previous=at
        if first is None:first=at;entry=(at//30000)*30000
        last=at
        while entry<=at:emit(entry);entry+=30000
        if kind in ('session_start','session_end','connected','disconnect','host_or_clock_gap'):
            book=None;markers.append(dict(known_at=at));books.append((at,None));continue
        if kind!='websocket':continue
        m=json.loads(r['payload_text']);channel=m.get('channel');d=m.get('data')
        if channel not in ('activeAssetCtx','l2Book') or not isinstance(d,dict) or d.get('coin')!='ETH':continue
        counts['ETH:'+channel]+=1
        if channel=='activeAssetCtx':
            c=d['ctx'];px=price_units(c['oraclePx'])
            if px<=0:raise ValueError('Nonpositive native ETH oracle')
            observed.append((at,px));contexts.append((at,px,positive(c.get('markPx')),positive(c.get('midPx'))))
        else:
            book=None if book is not None and d['time']<book[1]['time'] else (at,d)
            books.append((at,book))
    if not observed:raise ValueError('No ETH oracle messages in frozen prefix')
    end=(min(last,observed[-1][0])//30000)*30000;start=(first//30000)*30000;out=[];profiles=[]
    day_start=start//86400000*86400000
    while day_start<end:
        left=max(start,day_start);right=min(end,day_start+86400000);day=datetime.fromtimestamp(day_start/1000,timezone.utc).date().isoformat()
        points=[p for p in observed if left<=p[0]<right];gaps=[m for m in markers if left<=m['known_at']<right]
        if points:
            rows=attach(prepare_rows(points,dict(day=day,fetch_start=left,fetch_end=right),gaps),[p for p in contexts if left<=p[0]<right],left)
        else:
            rows=prepare_rows([],dict(day=day,fetch_start=left,fetch_end=right),gaps)
            for r in rows:r['oracle_gap']=None
        for r in rows:
            b,why=joined[r['start']];r.update(asset='ETH',split='frozen_out_of_time_prefix',liquidity=b,join_reason=why)
        clean=[r for r in rows if r['valid'] and r['adaptive_features'] is not None];profiles.append(dict(period=day,start=left,end=right,grid=len(rows),oracle_messages=len(points),clean=len(clean),matched=sum(r['liquidity'] is not None for r in clean),markers=len(gaps)))
        out.extend(rows);day_start+=86400000
    return out,dict(first_receipt_ms=first,last_receipt_ms=last,evaluation_start_ms=start,evaluation_end_ms=end,complete_utc_days=sum(p['start']%86400000==0 and p['end']-p['start']==86400000 for p in profiles),counts=dict(counts),days=profiles,finalized_segments=len(packet['entries']),last_sequence=packet['last_sequence']),books


