#!/usr/bin/env python3
"""Verify saved consecutive native books and report descriptive calendar liquidity."""
import argparse
from collections import defaultdict
from datetime import datetime, timezone
import gzip
import hashlib
import json
import math
from pathlib import Path
import statistics

from fetch_oxarchive_liquidity import DAY, digest
from probe_oxarchive_liquidity import ASSETS, dump, next_cursor, quality, stamp
from liquidity_features import book_metrics


def verify_day(root, saved):
    asset=saved['asset'];start=saved['start_ms'];end=start+DAY
    cursor=None;times=[];previous=None;duplicates=0;pages=saved['pages']
    totals={k:0. for k in ('spread_bps','minimum_top5_side_usd','minimum_top20_side_usd')}
    counts={k:0 for k in totals}
    if not pages:raise ValueError('No pages for day')
    for index,item in enumerate(pages):
        path=root/item['path']
        if digest(path)!=item['sha256'] or path.stat().st_size!=item['bytes']:
            raise ValueError('Raw page hash or size differs')
        query=dict(start=start,end=end,limit=1000,depth=20,source='venue')
        if cursor is not None:query['cursor']=cursor
        if item['query']!=query or item['route']!='/v1/hyperliquid/orderbook/'+asset+'/history':
            raise ValueError('Saved query is not the complete chronological cursor chain')
        raw=gzip.decompress(path.read_bytes());payload=json.loads(raw)
        if len(raw)!=item['decoded_bytes'] or payload.get('success') is not True:
            raise ValueError('Raw response size or status differs')
        if payload['meta']['request_id']!=item['request_id']:
            raise ValueError('Provider request ID differs')
        rows=payload['data']
        if not isinstance(rows,list) or len(rows)>1000:raise ValueError('Invalid page size')
        if payload['meta'].get('count')!=len(rows):raise ValueError('Provider row count differs')
        for row in rows:
            at=stamp(row['timestamp'])
            identity=hashlib.sha256(json.dumps(row,sort_keys=True,separators=(',',':')).encode()).hexdigest()
            if row.get('symbol',row.get('coin'))!=asset or row.get('coin',asset)!=asset or row.get('source')!='venue':
                raise ValueError('Wrong market or source')
            if not start<=at<=end or previous and at<previous[0]:raise ValueError('Regressing or out-of-window source time')
            if previous and at==previous[0]:
                if identity!=previous[1]:raise ValueError('Conflicting duplicate')
                duplicates+=1;continue
            previous=(at,identity)
            if at<end:
                times.append(at)
                bid=float(row['bids'][0]['px']);ask=float(row['asks'][0]['px'])
                values=dict(spread_bps=(ask-bid)/((ask+bid)/2)*10000,
                    minimum_top5_side_usd=min(sum(float(l['px'])*float(l['sz']) for l in row[side][:5]) for side in ('bids','asks')))
                if len(row['bids'])==len(row['asks'])==20:
                    values['minimum_top20_side_usd']=min(sum(float(l['px'])*float(l['sz']) for l in row[side]) for side in ('bids','asks'))
                for name,value in values.items():totals[name]+=value;counts[name]+=1
        # Recompute price/depth validity at both ends of every retained page.
        for row in ([rows[0],rows[-1]] if rows else []):
            m=book_metrics(dict(levels=[row['bids'],row['asks']]))
            if min(m['bid_levels'],m['ask_levels'])<5:raise ValueError('Too few actual levels')
        cursor=next_cursor(payload,cursor)
        if (cursor is None)!=(index==len(pages)-1):raise ValueError('Pagination completion differs')
    computed=quality(times,start,end,5000)
    if computed!=saved['quality'] or duplicates!=saved['duplicate_rows']:
        raise ValueError('Source cadence/grid statistics differ from raw pages')
    gaps=[dict(start_ms=a,end_ms=b,duration_ms=b-a) for a,b in zip([start]+times,times+[end]) if b-a>10000]
    if gaps!=saved['gaps_over_10s']:raise ValueError('Retained gap intervals differ')
    if counts!=saved['mean_denominators']:raise ValueError('Calendar mean denominators differ')
    for name in totals:
        value=totals[name]/counts[name] if counts[name] else None
        stored=saved['observed_snapshot_means'][name]
        if (value is None)!=(stored is None) or value is not None and not math.isclose(value,stored,rel_tol=1e-8,abs_tol=1e-8):
            raise ValueError('Calendar feature means differ from raw books')
    return dict(asset=asset,day=saved['day'],raw_pages=len(pages),unique_books=len(times),
                boundary_book_checks=2*len(pages),gaps_over_10s=len(gaps))


def calendar_summary(days):
    result={}
    for asset in ASSETS:
        selected=sorted((r for r in days if r['asset']==asset),key=lambda r:r['day'])
        cross_day_gaps=[b['quality']['first_ms']-a['quality']['last_ms'] for a,b in zip(selected,selected[1:])
                        if b['quality'].get('first_ms') is not None and a['quality'].get('last_ms') is not None]
        groups=defaultdict(list)
        for r in selected:
            weekend=datetime.fromisoformat(r['day']).weekday()>=5
            groups['weekend' if weekend else 'weekday'].append(r)
        grouped={}
        for name,rows in groups.items():
            grouped[name]=dict(days=len(rows),books=sum(r['quality']['rows'] for r in rows),
                mean_daily_spread_bps=statistics.mean(r['observed_snapshot_means']['spread_bps'] for r in rows),
                mean_daily_minimum_top5_side_usd=statistics.mean(r['observed_snapshot_means']['minimum_top5_side_usd'] for r in rows),
                mean_daily_source_fresh_fraction=statistics.mean(r['quality']['prior_source_fresh_grid_fraction'] for r in rows))
        ratios={}
        if 'weekend' in grouped and 'weekday' in grouped:
            for key in ('mean_daily_spread_bps','mean_daily_minimum_top5_side_usd'):
                ratios[key+'_weekend_change_pct']=100*(grouped['weekend'][key]/grouped['weekday'][key]-1)
        result[asset]=dict(asset_days=len(selected),books=sum(r['quality']['rows'] for r in selected),
            raw_pages=sum(len(r['pages']) for r in selected),minimum_actual_levels=min(r['minimum_levels'] for r in selected),
            maximum_source_gap_ms=max([r['quality']['max_gap_ms'] for r in selected]+cross_day_gaps),
            gaps_over_10s=sum(len(r['gaps_over_10s']) for r in selected),
            mean_daily_source_fresh_fraction=statistics.mean(r['quality']['prior_source_fresh_grid_fraction'] for r in selected),
            groups=grouped,weekend_changes=ratios)
    return result


def check(root):
    p=json.loads((root/'protocol.json').read_text());m=json.loads((root/'manifest.json').read_text())
    if not m['complete'] or m['errors'] or m['protocol_sha256']!=digest(root/'protocol.json'):
        raise ValueError('Download is incomplete or declaration differs')
    expected={(asset,start) for start in range(p['start_ms'],p['end_ms'],DAY) for asset in ASSETS}
    actual={(r['asset'],r['start_ms']) for r in m['days']}
    if actual!=expected or len(m['days'])!=len(expected):raise ValueError('Consecutive asset/date universe differs')
    if any(r['quality']['rows']<2 for r in m['days']):raise ValueError('One or more complete date requests contain insufficient books')
    for name,sha in p['source_sha256'].items():
        if digest(root/name)!=sha:raise ValueError('Frozen downloader source differs')
    if 'transport_change' in p:
        change=p['transport_change'];old=root/change['previous_sources']
        if digest(old/'protocol.json')!=change['previous_protocol_sha256']:
            raise ValueError('Transport change declaration has no matching prior protocol')
        prior=json.loads((old/'protocol.json').read_text())
        for name,sha in prior['source_sha256'].items():
            if digest(old/name)!=sha:raise ValueError('Prior downloader source differs')
    audit=[]
    for saved in m['days']:
        audit.append(verify_day(root,saved))
    result=dict(verified=True,protocol_sha256=digest(root/'protocol.json'),manifest_sha256=digest(root/'manifest.json'),
        first_utc_day=datetime.fromtimestamp(p['start_ms']/1000,timezone.utc).date().isoformat(),
        last_utc_day=datetime.fromtimestamp((p['end_ms']-DAY)/1000,timezone.utc).date().isoformat(),
        total_raw_pages=sum(r['raw_pages'] for r in audit),total_books=sum(r['unique_books'] for r in audit),
        compressed_bytes=sum(page['bytes'] for r in m['days'] for page in r['pages']),
        source_sha256=digest(Path(__file__)),assets=calendar_summary(m['days']),audit=audit,
        scope='All raw pages hashed and parsed; cursor chains, source identity, cadence, duplicates, gaps and feature means reconstructed. Book metrics validity rechecked at each page boundary; full per-row metrics were checked by the downloader. Feature means independently reconciled in float arithmetic to the Decimal-derived downloader means at 1e-8 relative/absolute tolerance.',
        interpretation='Equal-day averages of observed native snapshots, conditional on captured books. No causal identification, interpolation, full-market depth, execution-cost or thirty-second corridor win claim.',
        oracle_limitation='Authenticated oracle context samples have approximately one-minute cadence. They cannot reconstruct thirty-second oracle path extrema.')
    dump(root/'checks.json',result)
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--directory',type=Path,required=True)
    args=parser.parse_args();r=check(args.directory)
    print(json.dumps({k:v for k,v in r.items() if k not in ('audit',)}))
