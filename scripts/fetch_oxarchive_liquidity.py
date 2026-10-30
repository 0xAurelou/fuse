#!/usr/bin/env python3
"""Download consecutive native ETH/HYPE books on existing free API credits."""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import gzip
import hashlib
import json
from pathlib import Path
import shutil
import threading

from liquidity_features import book_metrics
from probe_oxarchive_liquidity import ASSETS, Client, DAY, dump, load_key, next_cursor, quality, stamp


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sources():
    return {name:digest(Path(__file__).parent/name) for name in
            ('fetch_oxarchive_liquidity.py','probe_oxarchive_liquidity.py','liquidity_features.py')}


def declare(root, days=28, now=None):
    if root.exists() or not 1<=days<=28:
        raise ValueError('Use a new directory and 1–28 completed UTC days')
    now = now or datetime.now(timezone.utc)
    end = int(now.timestamp()*1000)//DAY*DAY
    root.mkdir(parents=True)
    hashes=sources()
    for name in hashes:
        shutil.copyfile(Path(__file__).parent/name,root/name)
    protocol=dict(assets=ASSETS,start_ms=end-days*DAY,end_ms=end,days=days,
        source='venue',depth=20,page_limit=1000,workers=3,max_requests=3000,
        credit_reserve=1000,max_compressed_bytes=10*1024**3,source_sha256=hashes,
        bounds='Every full UTC day in the fixed interval; no outcome-selected windows',
        product='Native visible books only. API source timestamps, not original receipt timestamps.',
        oracle='Sampled oracle contexts were about one minute apart. No 30-second oracle labels or win claims.',
        gaps='Retain source gaps; no interpolation. Complete pagination does not imply uninterrupted data.')
    dump(root/'protocol.json',protocol)
    return protocol


class Budget:
    def __init__(self, protocol):
        self.protocol=protocol
        self.lock=threading.Lock()
        self.calls=0
        self.remaining=None
        self.bytes=0
        self.stop=threading.Event()

    def before(self):
        with self.lock:
            if self.stop.is_set() or self.calls>=self.protocol['max_requests']:
                raise ValueError('Download stopped or request bound reached')
            if self.remaining is not None and self.remaining<self.protocol['credit_reserve']:
                raise ValueError('Credit reserve reached; no upgrade or purchase')
            self.calls+=1

    def account(self, headers, size):
        with self.lock:
            if 'x-credits-remaining' in headers:
                value=int(headers['x-credits-remaining'])
                self.remaining=value if self.remaining is None else min(value,self.remaining)
            self.bytes+=size
            if self.bytes>self.protocol['max_compressed_bytes']:
                raise ValueError('Dataset size bound exceeded')


def page(root, prefix, index, route, query, client, budget):
    path=root/prefix/('%04d.json.gz'%index)
    meta_path=path.with_suffix('.meta.json')
    if meta_path.exists():
        meta=json.loads(meta_path.read_text())
        if meta['query']!=query or meta['route']!=route or digest(path)!=meta['sha256']:
            raise ValueError('Cached page provenance or hash differs')
        raw=gzip.decompress(path.read_bytes())
        payload=json.loads(raw)
        budget.account(meta['headers'],path.stat().st_size)
    else:
        budget.before()
        raw,payload,headers=client.get(route,query)
        body=gzip.compress(raw,mtime=0)
        budget.account(headers,len(body))
        path.parent.mkdir(parents=True,exist_ok=True)
        temp=path.with_suffix('.partial');temp.write_bytes(body);temp.replace(path)
        meta=dict(path=str(path.relative_to(root)),route=route,query=dict(query),
                  sha256=digest(path),bytes=len(body),decoded_bytes=len(raw),headers=headers,
                  request_id=payload.get('meta',{}).get('request_id'))
        dump(meta_path,meta)
    if payload.get('success') is not True:
        raise ValueError('Unsuccessful history response')
    rows=payload['data']
    if not isinstance(rows,list) or len(rows)>1000:
        raise ValueError('Expected no more than 1000 native history rows')
    return rows,payload,meta


def day(root, protocol, asset, start, client, budget):
    day_name=datetime.fromtimestamp(start/1000,timezone.utc).date().isoformat()
    prefix=Path(day_name)/asset
    route='/v1/hyperliquid/orderbook/'+asset+'/history'
    end=start+DAY
    query=dict(start=start,end=end,limit=1000,depth=20,source='venue')
    cursor=None;seen=set();pages=[];times=[];gaps=[];previous=None;duplicate_rows=0
    totals={k:0. for k in ('spread_bps','minimum_top5_side_usd','minimum_top20_side_usd')}
    counts={k:0 for k in totals}
    min_levels=20
    for index in range(60):
        if cursor is not None:query['cursor']=cursor
        rows,payload,meta=page(root,prefix,index,route,query,client,budget)
        pages.append(meta)
        for row in rows:
            if row.get('symbol',row.get('coin'))!=asset or row.get('coin',asset)!=asset or row.get('source')!='venue':
                raise ValueError('Returned market or native source differs')
            at=stamp(row['timestamp'])
            identity=hashlib.sha256(json.dumps(row,sort_keys=True,separators=(',',':')).encode()).hexdigest()
            if not start<=at<=end or previous and at<previous[0]:
                raise ValueError('Source timestamp outside day or regresses')
            if previous and at==previous[0]:
                if identity!=previous[1]:raise ValueError('Conflicting books at one source timestamp')
                duplicate_rows+=1;continue
            previous=(at,identity)
            metrics=book_metrics(dict(levels=[row['bids'],row['asks']]))
            min_levels=min(min_levels,metrics['bid_levels'],metrics['ask_levels'])
            if min_levels<5:raise ValueError('Insufficient actual levels per side')
            if at==end:continue  # Next day's entry is never used in this day's summaries.
            times.append(at)
            values=dict(spread_bps=metrics['spread_bps'],
                minimum_top5_side_usd=min(metrics['top5_bid_usd'],metrics['top5_ask_usd']))
            if metrics['bid_levels']==metrics['ask_levels']==20:
                values['minimum_top20_side_usd']=min(metrics['top20_bid_usd'],metrics['top20_ask_usd'])
            for name,value in values.items():totals[name]+=value;counts[name]+=1
        cursor=next_cursor(payload,cursor)
        if cursor is None:break
        cursor_id=json.dumps(cursor,sort_keys=True)
        if cursor_id in seen or not rows:raise ValueError('Cursor loop or empty incomplete page')
        seen.add(cursor_id)
    else:raise ValueError('Per-day page bound exceeded')
    boundaries=[start]+times+[end]
    for a,b in zip(boundaries,boundaries[1:]):
        if b-a>10000:gaps.append(dict(start_ms=a,end_ms=b,duration_ms=b-a))
    result=dict(asset=asset,day=day_name,start_ms=start,end_ms=end,pagination_complete=True,
        source='venue',pages=pages,duplicate_rows=duplicate_rows,minimum_levels=min_levels if times else None,
        quality=quality(times,start,end,5000),gaps_over_10s=gaps,
        observed_snapshot_means={k:totals[k]/counts[k] if counts[k] else None for k in totals},
        mean_denominators=counts)
    dump(root/prefix/'day-summary.json',result)
    return result


def fetch(root, key):
    protocol=json.loads((root/'protocol.json').read_text())
    if sources()!=protocol['source_sha256'] or any(digest(root/name)!=sha for name,sha in protocol['source_sha256'].items()):
        raise ValueError('Declared source changed; use a new dataset')
    # Do not silently shift the declared range as Free's rolling window advances.
    if datetime.now(timezone.utc).timestamp()*1000-protocol['start_ms']>=30*DAY:
        raise ValueError('Declared start is outside Free rolling history')
    budget=Budget(protocol);results=[];errors=[]
    jobs=[(asset,start) for start in range(protocol['start_ms'],protocol['end_ms'],DAY) for asset in ASSETS]
    local=threading.local()
    def one(asset,start):
        if not hasattr(local,'client'):local.client=Client(key,max_requests=3000)
        try:return day(root,protocol,asset,start,local.client,budget)
        except Exception:
            budget.stop.set();raise
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures={pool.submit(one,*job):job for job in jobs}
        for future in as_completed(futures):
            asset,start=futures[future]
            try:results.append(future.result())
            except Exception as exc:
                errors.append(dict(asset=asset,start_ms=start,error=str(exc).replace(key,'[redacted]')))
            manifest=dict(protocol_sha256=digest(root/'protocol.json'),complete=len(results)==len(jobs),
                requests_this_run=budget.calls,minimum_reported_credits_remaining=budget.remaining,
                compressed_bytes=budget.bytes,days=sorted(results,key=lambda r:(r['day'],r['asset'])),errors=errors)
            dump(root/'manifest.json',manifest)
            if len(results)%4==0 or errors:
                print(json.dumps(dict(completed_asset_days=len(results),total=len(jobs),
                    requests=budget.calls,errors=len(errors))),flush=True)
    return manifest


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory',type=Path,required=True)
    parser.add_argument('--declare',action='store_true')
    parser.add_argument('--days',type=int,default=28)
    args=parser.parse_args()
    try:
        if args.declare:
            p=declare(args.directory,args.days);print(json.dumps(p))
        else:
            r=fetch(args.directory,load_key())
            print(json.dumps({k:v for k,v in r.items() if k not in ('days','errors')}))
            raise SystemExit(0 if r['complete'] else 1)
    except Exception:
        print(json.dumps(dict(complete=False,error='Download stopped; see local manifest if created')))
        raise SystemExit(1)
