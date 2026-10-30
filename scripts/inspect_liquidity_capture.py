#!/usr/bin/env python3
"""Read-only collection quality report; does not score forward price outcomes."""
import argparse
from collections import Counter
from datetime import datetime,timezone
import gzip
import hashlib
import json
from pathlib import Path
import time

from collect_liquidity import verify_plan
from liquidity_archive import canonical, check_row, sha
from liquidity_features import ASSETS


def inspect(root):
    plan,genesis=verify_plan(root)
    sequence=0;head=genesis;previous_index=genesis;first_ns=last_ns=None
    channels={a:Counter() for a in ASSETS};events=Counter();daily={};gap_events=[]
    indexed=[];expected={};paths=[]
    index=(root/'segments.jsonl').read_bytes() if (root/'segments.jsonl').exists() else b''
    if index and not index.endswith(b'\n'):raise ValueError('index being flushed; retry')
    for line in index.splitlines():
        e=json.loads(line);digest=e.pop('index_hash')
        if e['previous_index_hash']!=previous_index or hashlib.sha256(canonical(e)).hexdigest()!=digest:
            raise ValueError('index digest differs')
        p=root/e['path']
        if not p.resolve().is_relative_to(root.resolve()) or sha(p)!=e['sha256']:raise ValueError('segment binding differs')
        indexed.append(e['path']);paths.append(p);expected[str(p)]=e;previous_index=digest
    for p in sorted(root.glob('data/*/*.open')):
        if str(p.with_suffix('.jsonl.gz').relative_to(root)) not in indexed:paths.append(p)
    for path in paths:
        try:stream=gzip.open(path,'rb') if path.suffix=='.gz' else path.open('rb')
        except FileNotFoundError:raise ValueError('archive rotated during prefix read; retry')
        # A live raw segment is bounded before reading; ignore only a partial final line.
        boundary=path.stat().st_size if path.suffix=='.open' else None
        total=0;count=0;uncompressed=hashlib.sha256();segment_previous=head;segment_first=sequence+1
        with stream:
            while True:
                line=stream.readline((boundary-total) if boundary is not None else -1)
                if not line:break
                total+=len(line)
                if not line.endswith(b'\n'):
                    if boundary is None:raise ValueError('incomplete finalized record')
                    break
                sequence,head=check_row(line,sequence,head);count+=1;uncompressed.update(line)
                r=json.loads(line)['record'];at=r['received_at_ns']
                if first_ns is None:first_ns=at
                last_ns=at
                if r['kind']=='websocket':
                    try:
                        v=json.loads(r['payload_text']);channel=v.get('channel');d=v.get('data')
                        if channel=='trades' and d:asset=d[0]['coin']
                        elif channel in ('activeAssetCtx','l2Book','bbo'):asset=d['coin']
                        else:continue
                    except (ValueError,KeyError,TypeError,AttributeError,IndexError):
                        events['unparsed_websocket_messages']+=1;continue
                    if asset not in channels:events['unsubscribed_asset_messages']+=1;continue
                    channels[asset][channel]+=1
                elif r['kind']=='features':
                    s=r['values'];day=datetime.fromtimestamp(at/10**9,timezone.utc).date().isoformat()
                    part=daily.setdefault((day,s['asset']),dict(samples=0,joint_fresh=0,oracle_fresh=0,
                        book_fresh=0,spread_observed=0,trade_window_transport_covered=0,
                        depth1_both_sides_covered=0,depth5_both_sides_covered=0))
                    part['samples']+=1
                    for key in ('joint_fresh','oracle_fresh','book_fresh','trade_window_transport_covered'):part[key]+=bool(s[key])
                    part['spread_observed']+=s.get('spread_bps') is not None
                    for band in ('1','5'):
                        b=s['book'];coverage=b['depth'][band] if b else None
                        part[f'depth{band}_both_sides_covered']+=bool(coverage and coverage['bid_band_covered'] and coverage['ask_band_covered'])
                else:
                    events[r['kind']]+=1
                    if r['kind'] in ('disconnect','host_or_clock_gap','session_start','session_end'):
                        gap_events.append({k:v for k,v in r.items() if k not in ('previous_status',)})
        if str(path) in expected:
            e=expected[str(path)]
            if (segment_first,segment_previous,sequence,head,count,uncompressed.hexdigest())!=(e['first_sequence'],e['first_previous_hash'],e['last_sequence'],e['last_hash'],e['records'],e['uncompressed_sha256']):
                raise ValueError('segment metadata differs from receipts')
    return dict(collection_root=str(root),plan_sha256=genesis,role=plan['role'],
        checked_at_ms=time.time_ns()//1000000,verified_prefix_sequence=sequence,last_hash=head,
        first_receipt_ns=first_ns,last_receipt_ns=last_ns,
        finalized_segments=len(indexed),active_prefix=any(p.suffix=='.open' for p in paths),
        messages={a:dict(c) for a,c in channels.items()},events=dict(events),gap_and_session_events=gap_events,
        daily_feature_quality=[dict(utc_day=day,asset=asset,**values) for (day,asset),values in sorted(daily.items())],
        interpretation='Receipt integrity and sampled collection quality only. Sample cadence is approximate; counts are not continuous-window coverage, feed completeness, pricing validation or a liquidity-effect estimate.',
        forward_price_outcomes_inspected=False)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--directory',type=Path,required=True)
    parser.add_argument('--output',type=Path);args=parser.parse_args();result=inspect(args.directory.resolve())
    if args.output:
        with args.output.open('x') as stream:json.dump(result,stream,indent=2);stream.write('\n')
    else:print(json.dumps(result,indent=2))
