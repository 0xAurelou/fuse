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


def snapshot_index(root,genesis):
    raw=(root/'segments.jsonl').read_bytes()
    if not raw or not raw.endswith(b'\n'):raise ValueError('Finalized index unavailable or being flushed; retry')
    previous=genesis;sequence=0;head=genesis;entries=[]
    for line in raw.splitlines():
        e=json.loads(line);h=e['index_hash'];value={k:v for k,v in e.items() if k!='index_hash'};path=root/e['path']
        if e['previous_index_hash']!=previous or hashlib.sha256(canonical(value)).hexdigest()!=h:raise ValueError('Frozen index chain differs')
        if not path.resolve().is_relative_to(root.resolve()) or sha(path)!=e['sha256']:raise ValueError('Frozen segment path/hash differs')
        if e['first_sequence']!=sequence+1 or e['first_previous_hash']!=head or e['records']!=e['last_sequence']-sequence:raise ValueError('Frozen segment range differs')
        previous=h;sequence=e['last_sequence'];head=e['last_hash'];entries.append(e)
    return dict(genesis=genesis,index_prefix_bytes=len(raw),index_prefix_sha256=hashlib.sha256(raw).hexdigest(),entries=entries,last_sequence=sequence,last_hash=head)


def records(root,packet):
    prefix=(root/'segments.jsonl').read_bytes()[:packet['index_prefix_bytes']]
    if hashlib.sha256(prefix).hexdigest()!=packet['index_prefix_sha256']:raise ValueError('Capture prefix changed')
    seq=0;head=packet['genesis']
    for e in packet['entries']:
        path=root/e['path']
        if not path.resolve().is_relative_to(root.resolve()) or sha(path)!=e['sha256']:raise ValueError('Capture segment changed')
        first=seq+1;old=head;count=0;h=hashlib.sha256()
        with gzip.open(path,'rb') as stream:
            for line in stream:
                if not line.endswith(b'\n'):raise ValueError('Incomplete finalized receipt')
                seq,head=check_row(line,seq,head);h.update(line);count+=1
                yield json.loads(line)['record']
        if (first,old,seq,head,count,h.hexdigest())!=(e['first_sequence'],e['first_previous_hash'],e['last_sequence'],e['last_hash'],e['records'],e['uncompressed_sha256']):raise ValueError('Capture receipt metadata differs')
    if seq!=packet['last_sequence'] or head!=packet['last_hash']:raise ValueError('Capture terminal hash differs')


def parse_eth(root,packet):
    observed=[];contexts=[];markers=[];books=[];book=None;joined={};counts=Counter();first=None;last=None;entry=None;previous=None
    def emit(at):
        value,why=snapshot(book,at);joined[at]=(value,why)
    for r in records(root,packet):
        at=r['received_at_ns']//1000000
        if previous is not None and at<previous:raise ValueError('Regressing native wall clock needs a separate episode policy')
        previous=at
        if first is None:first=at;entry=(at//30000)*30000
        last=at
        while entry<=at:emit(entry);entry+=30000
        kind=r['kind'];counts[kind]+=1
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


def verify_books(rows,books):
    from bisect import bisect_left
    times=[at for at,_ in books]
    for r in rows:
        i=bisect_left(times,r['start'])-1;state=books[i][1] if i>=0 else None
        value,why=snapshot(state,r['start'])
        if (r['liquidity'],r['join_reason'])!=(value,why):raise ValueError('Independent strict native book join differs')
