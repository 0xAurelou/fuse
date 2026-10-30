"""Attach receipt-time market context to the retained later raw oracle days."""
import csv
import gzip
import json

from capture_dataset import file_hash
from oracle_gap_features import attach, raw_timestamp, positive
from research_nonfrozen_pricing import verify_raw
from temporal_oracle_data import origin


def attach_late(rawdir,rows_by_day,normalized_manifest):
    digest=file_hash(rawdir/'download-manifest.json')
    verify_raw(dict(raw=str(rawdir),raw_manifest_sha256=digest))
    manifest=json.loads((rawdir/'download-manifest.json').read_text())
    points={day:{} for day in rows_by_day};previous={}
    for item in sorted(manifest['files'],key=lambda f:(f['day'],f['at_ms'])):
        day=item['day']
        if day not in points:continue
        for line in gzip.decompress((rawdir/item['path']).read_bytes()).decode().splitlines():
            if not line:continue  # Outcome rows already retain disconnect censorship.
            timestamp,payload=line.split(' ',1);at=raw_timestamp(timestamp)
            if not item['at_ms']<=at<item['at_ms']+60000 or at<previous.get(day,at):
                raise ValueError('raw market receipt outside minute or regressing')
            previous[day]=at;message=json.loads(payload)
            if message['channel']!='activeAssetCtx' or message['data']['coin']!='BTC':raise ValueError('wrong market context')
            c=message['data']['ctx']
            points[day][at]=(positive(c['oraclePx']),positive(c.get('markPx')),positive(c.get('midPx')))
    normal=json.loads(normalized_manifest.read_text());checks=[];output={}
    for day,rows in rows_by_day.items():
        item=next(f for f in normal['files'] if f['date']==day)
        path=normalized_manifest.parent/item['path']
        if file_hash(path)!=item['sha256']:raise ValueError('normalized market crosscheck changed')
        common=oracle_errors=mark_errors=0
        with gzip.open(path,'rt',newline='') as stream:
            for r in csv.DictReader(stream):
                if r['exchange']!='hyperliquid' or r['symbol']!='BTC':raise ValueError('wrong normalized context')
                at=int(r['local_timestamp'])//1000
                if at not in points[day] or not r['index_price']:continue
                common+=1
                oracle_errors+=positive(r['index_price'])!=points[day][at][0]
                mark_errors+=positive(r['mark_price'])!=points[day][at][1]
        if not common or oracle_errors or mark_errors:raise ValueError('oracle/mark crosscheck failed')
        values=sorted((at,*prices) for at,prices in points[day].items())
        annotated=attach(rows,values,origin(day))
        if any((a['entry'],a['move'],a['valid'],a['activity_state'])!=(b['entry'],b['move'],b['valid'],b['activity_state']) for a,b in zip(rows,annotated)):
            raise ValueError('market features changed oracle paths or eligibility')
        output[day]=annotated
        checks.append(dict(day=day,raw_receipts=len(values),shared_timestamps=common,
            oracle_mismatches=oracle_errors,mark_mismatches=mark_errors,
            frozen_paths=sum(r['valid'] and r['activity_state']=='frozen' for r in rows),
            frozen_supported=sum(r['valid'] and r['activity_state']=='frozen' and r['oracle_gap'] is not None for r in annotated)))
    return output,dict(raw_manifest_sha256=digest,normalized_manifest_sha256=file_hash(normalized_manifest),checks=checks)
