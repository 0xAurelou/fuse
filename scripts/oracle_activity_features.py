#!/usr/bin/env python3
"""Past-only price-change activity features, with immutable dataset provenance."""
import argparse
from bisect import bisect_left, bisect_right
from datetime import datetime, timezone
from decimal import Decimal
import gzip
import json
import math
from pathlib import Path
import shutil

from capture_dataset import file_hash
from investigate_capture import reconstruct
from research_oracle_history import observations, load_capture_rows
from stabilize_adaptive_corridor import load_history

DEPENDENCIES = ('oracle_activity_features.py', 'stabilize_adaptive_corridor.py',
                'research_oracle_history.py', 'research_market_regimes.py',
                'adaptive_corridor.py', 'capture_dataset.py', 'investigate_capture.py',
                'analyze_capture.py', 'prospective_capture.py')


def annotate(rows, observed):
    """Ignore unchanged heartbeat duplicates; nothing at entry or later is read.

    The first observation is an anchor, not a fabricated change. If no earlier
    change has been seen, idle age is a lower bound since that anchor.
    """
    if any(b[0] < a[0] for a, b in zip(observed, observed[1:])):
        raise ValueError('observations must be ordered')
    changes = [(b[0], math.log(b[1] / a[1]) ** 2)
               for a, b in zip(observed, observed[1:]) if a[1] != b[1]]
    times = [v[0] for v in changes]
    prefix = [0.0]
    for _, value in changes:
        prefix.append(prefix[-1] + value)
    for row in rows:
        row['activity_features'] = None
        if row['adaptive_features'] is None or not observed:
            continue
        at = row['start']
        end = bisect_left(times, at)
        begin = bisect_left(times, at - 300_000)
        short = bisect_left(times, at - 60_000)
        last30 = bisect_left(times, at - 30_000)
        last_change = times[end - 1] if end else observed[0][0]
        bins = [bisect_left(times, at - offset * 30_000) - bisect_left(times, at - (offset + 1) * 30_000)
                for offset in range(10)]
        variance = max(0, prefix[end] - prefix[begin])
        maximum = max((value for _, value in changes[begin:end]), default=0)
        row['activity_features'] = dict(changes_30=end - last30, changes_60=end - short,
                                        changes_300=end - begin,
                                        idle_ms=max(0, at - last_change),
                                        idle_is_lower_bound=end == 0,
                                        empty_bins_300=sum(v == 0 for v in bins) / 10,
                                        largest_variance_share_300=min(1, maximum / variance) if variance else 0)


def state(row):
    f = row['activity_features']
    if f is None:
        return 'missing_history'
    if f['idle_ms'] >= 30_000:
        return 'frozen'
    if f['empty_bins_300'] >= .3 or f['changes_60'] <= 3:
        return 'sparse'
    if f['largest_variance_share_300'] >= .5:
        return 'bursty'
    return 'active'


def build(history, captures, output):
    if output.exists():
        raise ValueError('output already exists; preserve retained features')
    rows, previous = load_history(history)
    source = json.loads(Path(previous['source_manifest_path']).read_text())
    root = Path(previous['source_manifest_path']).parent
    protocol = dict(history=str(history.resolve()), history_sha256=file_hash(history / 'research.json'),
                    old_features_sha256=file_hash(history / 'predictions.csv'),
                    source_sha256={name: file_hash(Path(__file__).with_name(name)) for name in DEPENDENCIES},
                    native_paths=[str(p.resolve()) for p in captures], dates=previous['dates'],
                    input_rule='Only observed price changes strictly before entry; no resampling/interpolation; keep original outcome eligibility',
                    states='frozen: idle>=30s; sparse: >=30% empty prior 30s bins or <=3 changes/min; bursty: largest step >=50% variance; otherwise active',
                    source_role='Historical normalized oracle observations and separate native paired captures')
    output.mkdir(parents=True)
    (output / 'protocol.json').write_text(json.dumps(protocol, indent=2) + '\n')
    (output / 'source').mkdir()
    for name in DEPENDENCIES:
        shutil.copyfile(Path(__file__).with_name(name), output / 'source' / name)
    by_day = {day: [r for r in rows if r['period'] == day] for day in previous['dates']}
    for item in source['files']:
        day = item['date']
        start = int(datetime.strptime(day, '%Y-%m-%d').replace(tzinfo=timezone.utc).timestamp() * 1000)
        observed, _ = observations(root / item['path'], start, start + 86_400_000)
        annotate(by_day[day], observed)
    native_rows, native_sources = [], []
    for directory in captures:
        run = load_capture_rows(directory)
        start = run['manifest']['frozen_at_ms']
        with (directory / 'receipts.jsonl').open() as stream:
            receipts = [json.loads(line) for line in stream]
        records = [dict(at=r['at'], source=r['source'], price=int(Decimal(r['raw']['data']['ctx']['oraclePx']) * 1_000_000))
                   for r in receipts]
        _, observed = reconstruct(records, run['manifest']['policy'], start, start + run['manifest']['duration_ms'])
        for row in run['rows']:
            row.update(period=run['name'], split='native')
        annotate(run['rows'], observed)
        native_rows.extend(run['rows'])
        native_sources.append(run['source'])
    for row in rows + native_rows:
        row['activity_state'] = state(row)
    with gzip.open(output / 'rows.jsonl.gz', 'wt') as stream:
        for row in rows + native_rows:
            stream.write(json.dumps(row, separators=(',', ':')) + '\n')
    result = dict(protocol, native_sources=native_sources, rows_sha256=file_hash(output / 'rows.jsonl.gz'),
                  historical_rows=len(rows), native_rows=len(native_rows))
    (output / 'dataset.json').write_text(json.dumps(result, indent=2) + '\n')
    return result


def load(directory):
    data = json.loads((directory / 'dataset.json').read_text())
    if file_hash(directory / 'rows.jsonl.gz') != data['rows_sha256']:
        raise ValueError('activity feature dataset changed')
    for name, digest in data['source_sha256'].items():
        if file_hash(directory / 'source' / name) != digest:
            raise ValueError('activity feature source snapshot changed')
    previous = Path(data['history'])
    if file_hash(previous / 'research.json') != data['history_sha256'] or file_hash(previous / 'predictions.csv') != data['old_features_sha256']:
        raise ValueError('upstream historical features changed')
    # Recheck the raw historical archives and native receipts, not only derivatives.
    upstream = json.loads((previous / 'research.json').read_text())
    manifest_path = Path(upstream['source_manifest_path'])
    if file_hash(manifest_path) != upstream['source_manifest_sha256']:
        raise ValueError('historical download manifest changed')
    for source in json.loads(manifest_path.read_text())['files']:
        if file_hash(manifest_path.parent / source['path']) != source['sha256']:
            raise ValueError('raw historical oracle sample changed')
    for source in data['native_sources']:
        if file_hash(Path(source['path']) / 'receipts.jsonl') != source['sha256']:
            raise ValueError('native receipts changed')
    with gzip.open(directory / 'rows.jsonl.gz', 'rt') as stream:
        rows = [json.loads(line) for line in stream]
    return rows, data


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--history', type=Path, required=True)
    parser.add_argument('--captures', type=Path, nargs='*', default=[])
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = build(args.history, args.captures, args.output)
    print(json.dumps(dict(output=str(args.output), historical_rows=result['historical_rows'], native_rows=result['native_rows'])))


if __name__ == '__main__':
    main()
