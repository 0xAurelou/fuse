#!/usr/bin/env python3
"""Bounded anonymous raw BTC oracle samples; no credentials or paid endpoints."""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import gzip
import json
from pathlib import Path
import shutil
import time
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from capture_dataset import file_hash
from oracle_activity_features import load

DAY = 86_400_000


def prepare(dataset, output, full_day=None):
    if output.exists():
        raise ValueError('output exists; use --fetch to resume the pinned request list')
    rows, _ = load(dataset)
    panels = []
    # Dates and controls declared before downloading raw data. Dense windows use
    # only entry-time features, never movement, survival or future eligibility.
    for day in ('2025-01-01', '2025-07-01', '2026-05-01', '2025-06-01', '2026-01-01'):
        part = [r for r in rows if r['period'] == day]
        origin = int(datetime.fromisoformat(day).replace(tzinfo=timezone.utc).timestamp() * 1000)
        if day in ('2025-06-01', '2026-01-01'):
            begin, reason = origin + 6 * 3_600_000, 'fixed 06–10 UTC control on a heavily excluded normalized day'
        else:
            choices = [(sum(r['activity_state'] == 'frozen' for r in part[i:i + 480]), -i)
                       for i in range(30, len(part) - 479, 30)]
            _, negative_index = max(choices)
            begin = part[-negative_index]['start']
            reason = 'most pre-entry frozen features in a 4h window, 15min start grid; earliest tie'
        panels.append(dict(day=day, start=begin, end=begin + 4 * 3_600_000,
                           fetch_start=begin - 300_000, fetch_end=begin + 4 * 3_600_000,
                           selection=reason))
    if full_day:
        if full_day != '2026-01-01':
            raise ValueError('only the declared January follow-up day is supported')
        origin = int(datetime.fromisoformat(full_day).replace(tzinfo=timezone.utc).timestamp() * 1000)
        panels = [dict(day=full_day, start=origin, end=origin + DAY, fetch_start=origin,
                       fetch_end=origin + DAY,
                       selection='Complete January day after new high-floor discovery; developmental follow-up, no outcome-based interval removal')]
    requests = []
    for panel in panels:
        day = panel['day']
        origin = int(datetime.fromisoformat(day).replace(tzinfo=timezone.utc).timestamp() * 1000)
        for at in range(panel['fetch_start'], panel['fetch_end'], 60_000):
            query = urlencode(dict(**{'from': day + 'T00:00:00.000Z'}, offset=(at - origin) // 60_000,
                                   filters=json.dumps([dict(channel='activeAssetCtx', symbols=['BTC'])], separators=(',', ':'))))
            requests.append(dict(day=day, at_ms=at, path=f"{day}/{(at-origin)//60_000:04d}.bin",
                                 url='https://api.tardis.dev/v1/data-feeds/hyperliquid?' + query))
    protocol = dict(dataset=str(dataset.resolve()), dataset_sha256=file_hash(dataset / 'dataset.json'),
                    source_sha256=file_hash(Path(__file__)), panels=panels, requests=requests,
                    authentication='none', maximum_bytes_per_response=200_000, workers=8,
                    documentation='https://docs.tardis.dev/api/http-api-reference',
                    source_role='Separate raw historical single-stream panels; not new calendar days, native paired receipts, or independent holdouts',
                    capture_started=False, live_candidate_promoted=False)
    output.mkdir(parents=True)
    (output / 'download-protocol.json').write_text(json.dumps(protocol, indent=2) + '\n')
    shutil.copyfile(Path(__file__), output / 'fetch-source.py')
    return protocol


def fetch(output):
    protocol = json.loads((output / 'download-protocol.json').read_text())
    if file_hash(output / 'fetch-source.py') != protocol['source_sha256'] or file_hash(Path(__file__)) != protocol['source_sha256']:
        raise ValueError('fetch code differs from pinned protocol')
    manifest = output / 'download-manifest.json'
    old = json.loads(manifest.read_text())['files'] if manifest.exists() else []
    retained = {r['path']: r for r in old if r['status'] == 'downloaded'}

    def one(item):
        path = output / item['path']
        if item['path'] in retained:
            previous = retained[item['path']]
            if file_hash(path) != previous['sha256'] or item['url'] != previous['url']:
                raise ValueError('retained raw minute changed')
            return previous
        if path.exists():
            raise ValueError('unbound raw minute exists; never replace it')
        path.parent.mkdir(exist_ok=True)
        for attempt in range(3):
            try:
                request = Request(item['url'], headers={'Accept-Encoding': 'gzip', 'User-Agent': 'fuse-flat-research/1.0'})
                with urlopen(request, timeout=20) as response:
                    body = response.read(protocol['maximum_bytes_per_response'] + 1)
                    if len(body) > protocol['maximum_bytes_per_response']:
                        raise ValueError('raw minute exceeds download bound')
                    decoded = gzip.decompress(body)  # Validate CRC before retention.
                    if len(decoded) > 2_000_000:
                        raise ValueError('raw minute exceeds decompressed bound')
                    path.write_bytes(body)
                    return dict(item, status='downloaded', bytes=len(body), sha256=file_hash(path),
                                content_encoding=response.headers.get('Content-Encoding'),
                                retrieved_at_ms=time.time_ns() // 1_000_000)
            except Exception as error:
                if attempt == 2:
                    return dict(item, status='error', error=str(error))
                time.sleep(attempt + 1)

    files = []
    with ThreadPoolExecutor(max_workers=protocol['workers']) as pool:
        futures = [pool.submit(one, item) for item in protocol['requests']]
        for future in as_completed(futures):
            files.append(future.result())
            if len(files) % 50 == 0 or len(files) == len(futures):
                result = dict(protocol_sha256=file_hash(output / 'download-protocol.json'),
                              files=sorted(files, key=lambda r: r['at_ms']),
                              complete=len(files) == len(futures) and all(r['status'] == 'downloaded' for r in files))
                manifest.write_text(json.dumps(result, indent=2) + '\n')
                print(json.dumps(dict(processed=len(files), total=len(futures), errors=sum(r['status'] != 'downloaded' for r in files))), flush=True)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--fetch', action='store_true')
    parser.add_argument('--full-day')
    args = parser.parse_args()
    result = fetch(args.output) if args.fetch else prepare(args.dataset, args.output, args.full_day)
    if not args.fetch:
        print(json.dumps(dict(panels=result['panels'], requests=len(result['requests'])), indent=2))


if __name__ == '__main__':
    main()
