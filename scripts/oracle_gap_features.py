"""Receipt-time oracle/mark features with strict entry and restart boundaries."""
from bisect import bisect_left
import csv
from datetime import datetime, timezone
import gzip
import json
import math
from pathlib import Path

from capture_dataset import file_hash
from research_market_regimes import price_units
from research_nonfrozen_pricing import verify_raw

SPEC = dict(freshness_ms=8000, lag_ms=30000, strict_before_entry=True,
            fields=('signed_mark_gap', 'absolute_mark_gap', 'gap_change30', 'mark_move30', 'absolute_mark_move30'),
            normalization='asinh(ppm / max(1, pre-entry slow volatility ppm))',
            primary_market_price='markPx / normalized mark_price; never substitutes for oracle')
RAW_NAMES = ('tardis-hyperliquid-BTC-earlier-bursty-training-v1',
             'tardis-hyperliquid-BTC-bursty-full-days-v1',
             'tardis-hyperliquid-BTC-expanded-bursty-training-v1',
             'tardis-hyperliquid-BTC-8h-admission-controls-v1',
             'tardis-hyperliquid-BTC-raw-jan2026-v1')


def raw_timestamp(timestamp):
    if not timestamp.endswith('Z'):
        raise ValueError('UTC receipt required')
    whole, fraction = timestamp[:-1].split('.')
    if not fraction.isdigit():
        raise ValueError('invalid receipt fraction')
    seconds = datetime.strptime(whole, '%Y-%m-%dT%H:%M:%S').replace(tzinfo=timezone.utc)
    return int(seconds.timestamp()) * 1000 + int((fraction + '000')[:3])


def positive(value):
    if value is None or value == '':
        return None
    result = price_units(str(value))
    if result <= 0:
        raise ValueError('nonpositive market context')
    return result


def load_context(history):
    """Verify retained inputs; retain the last receipt within each millisecond."""
    normal_root = history / 'tardis-hyperliquid-BTC-monthly-samples-v1'
    normal_manifest = normal_root / 'download-manifest.json'
    normalized, raw, bindings = {}, {}, []
    for f in json.loads(normal_manifest.read_text())['files']:
        path = normal_root / f['path']
        if f['status'] != 'downloaded' or file_hash(path) != f['sha256']:
            raise ValueError('normalized context differs')
        part = {}; previous = None
        with gzip.open(path, 'rt', newline='') as stream:
            for row in csv.DictReader(stream):
                if row['exchange'] != 'hyperliquid' or row['symbol'] != 'BTC':
                    raise ValueError('wrong normalized context asset')
                at = int(row['local_timestamp']) // 1000
                if previous is not None and at < previous:
                    raise ValueError('normalized context regressed')
                previous = at
                oracle = positive(row['index_price'])
                if oracle is not None:
                    part[at] = (oracle, positive(row['mark_price']), None)
        normalized[f['date']] = sorted((at, *prices) for at, prices in part.items())
    bindings.append(dict(root=str(normal_root.resolve()), manifest_sha256=file_hash(normal_manifest)))
    for name in RAW_NAMES:
        root = history / name
        digest = file_hash(root / 'download-manifest.json')
        verify_raw(dict(raw=str(root), raw_manifest_sha256=digest))
        files = json.loads((root / 'download-manifest.json').read_text())['files']
        local = {}
        for f in sorted(files, key=lambda f: f['at_ms']):
            part = local.setdefault(f['day'], {})
            for line in gzip.decompress((root / f['path']).read_bytes()).decode().splitlines():
                if not line:
                    continue  # Existing path labels retain disconnect censorship.
                timestamp, payload = line.split(' ', 1)
                at = raw_timestamp(timestamp)
                if not f['at_ms'] <= at < f['at_ms'] + 60000:
                    raise ValueError('raw context outside declared minute')
                message = json.loads(payload)
                if message['channel'] != 'activeAssetCtx' or message['data']['coin'] != 'BTC':
                    raise ValueError('wrong raw context asset')
                c = message['data']['ctx']
                part[at] = (positive(c['oraclePx']), positive(c.get('markPx')), positive(c.get('midPx')))
        for day, points in local.items():
            part = raw.setdefault(day, {})
            for at, values in points.items():
                if at in part and part[at] != values:
                    raise ValueError('overlapping raw context archives disagree')
                part[at] = values
        bindings.append(dict(root=str(root.resolve()), manifest_sha256=digest))
    checks = []
    for day, points in raw.items():
        norm = {at: values for at, *values in normalized[day]}
        common = sorted(set(points) & set(norm))
        oracle_errors = sum(points[at][0] != norm[at][0] for at in common)
        mark_errors = sum(points[at][1] != norm[at][1] for at in common)
        if oracle_errors or mark_errors:
            raise ValueError(f'raw/normalized oracle or mark disagreement on {day}: {oracle_errors}/{mark_errors}')
        checks.append(dict(day=day, raw_receipts=len(points), shared_timestamps=len(common),
                           oracle_mismatches=oracle_errors, mark_mismatches=mark_errors,
                           raw_mid_available=sum(v[2] is not None for v in points.values())))
    raw = {day: sorted((at, *values) for at, values in points.items()) for day, points in raw.items()}
    return dict(normalized=normalized, raw=raw), bindings, checks


def attach(rows, points, left):
    """Changing a receipt at entry or later cannot change entry features."""
    times = [p[0] for p in points]
    result = []
    for row in rows:
        at = row['start']; old = at - SPEC['lag_ms']; feature = None
        i, j = bisect_left(times, at) - 1, bisect_left(times, old) - 1
        if i >= 0 and j >= 0:
            a, b = points[i], points[j]
            if (left <= b[0] <= a[0] and 0 < at - a[0] <= SPEC['freshness_ms']
                    and 0 < old - b[0] <= SPEC['freshness_ms'] and a[2] is not None and b[2] is not None):
                if row['entry'] is not None and row['entry'] != a[1]:
                    raise ValueError('context and quoted entry oracle differ')
                if row['adaptive_features'] is not None:
                    gap = 1e6 * (a[2] / a[1] - 1)
                    laggap = 1e6 * (b[2] / b[1] - 1)
                    move = 1e6 * (a[2] / b[2] - 1)
                    slow = max(1, row['adaptive_features']['vol_300_ppm'])
                    values = [math.asinh(v / slow) for v in (gap, abs(gap), gap - laggap, move, abs(move))]
                    feature = dict(values=values, observed_at=a[0], lag_observed_at=b[0],
                                   mark_gap_ppm=gap, gap_change30_ppm=gap - laggap, mark_move30_ppm=move,
                                   mid_gap_ppm=1e6 * (a[3] / a[1] - 1) if a[3] is not None else None)
        result.append(dict(row, oracle_gap=feature))
    return result
