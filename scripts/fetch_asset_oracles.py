#!/usr/bin/env python3
"""Pin and fetch public raw ETH/HYPE monthly oracle days without credentials."""
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

ASSETS = ('ETH', 'HYPE')
DATES = tuple(f'{y}-{m:02d}-01' for y in (2024, 2025, 2026) for m in range(1, 13)
              if '2024-11-01' <= f'{y}-{m:02d}-01' <= '2026-10-01')


def dump(path, data):
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(data, indent=2, allow_nan=False) + '\n')
    temporary.replace(path)


def origin(day):
    return int(datetime.fromisoformat(day).replace(tzinfo=timezone.utc).timestamp() * 1000)


def prepare(output, metadata):
    if output.exists():
        raise ValueError('preserve existing downloads; use --fetch to resume')
    available = {r['id']: r['availableSince'] for r in json.loads(metadata.read_text())['availableSymbols']
                 if r['id'] in ASSETS}
    if set(available) != set(ASSETS):
        raise ValueError('asset coverage metadata missing')
    requests = []
    for day in DATES:
        symbols = [a for a in ASSETS if available[a][:10] <= day]
        if not symbols:
            raise ValueError('no available assets for declared date')
        for offset in range(0, 1440, 10):
            query = urlencode({'from': day + 'T00:00:00.000Z', 'offset': offset, 'sliceSize': 10,
                               'filters': json.dumps([dict(channel='activeAssetCtx', symbols=symbols)], separators=(',', ':'))})
            requests.append(dict(day=day, at_ms=origin(day) + offset * 60000, duration_ms=600000,
                                 assets=symbols, path=f'{day}/{offset:04d}.bin',
                                 url='https://api.tardis.dev/v1/data-feeds/hyperliquid?' + query))
    protocol = dict(assets=ASSETS, dates=DATES, available_since=available, requests=requests,
                    authentication='none', workers=12, maximum_bytes=3_000_000,
                    maximum_decoded_bytes=20_000_000,
                    splits={'train': ['2024-11-01', '2025-12-01'],
                            'validation': ['2026-01-01', '2026-05-01'],
                            'test': ['2026-06-01', '2026-10-01']},
                    unavailable='Dates before provider asset coverage are explicitly absent, never synthesized',
                    source_role='Third-party raw single-stream monthly historical research; not native paired receipts',
                    documentation='https://docs.tardis.dev/api/http-api-reference',
                    sampling='All available first-of-month full UTC days in the declared range; no outcome-selected intervals',
                    fetcher_sha256=file_hash(Path(__file__)), metadata_sha256=file_hash(metadata))
    output.mkdir(parents=True)
    shutil.copyfile(metadata, output / 'exchange-metadata.json')
    shutil.copyfile(Path(__file__), output / 'fetch-source.py')
    dump(output / 'download-protocol.json', protocol)
    return protocol


def fetch(output):
    protocol_path = output / 'download-protocol.json'
    protocol = json.loads(protocol_path.read_text())
    if (file_hash(output / 'fetch-source.py') != protocol['fetcher_sha256']
            or file_hash(Path(__file__)) != protocol['fetcher_sha256']
            or file_hash(output / 'exchange-metadata.json') != protocol['metadata_sha256']):
        raise ValueError('download source/metadata changed')
    manifest = output / 'download-manifest.json'
    old = json.loads(manifest.read_text()) if manifest.exists() else {}
    if old and old['protocol_sha256'] != file_hash(protocol_path):
        raise ValueError('download protocol changed')
    retained = {r['path']: r for r in old.get('files', []) if r['status'] == 'downloaded'}

    def one(item):
        path = output / item['path']
        if item['path'] in retained:
            previous = retained[item['path']]
            if file_hash(path) != previous['sha256'] or item['url'] != previous['url']:
                raise ValueError('retained raw slice differs')
            return previous
        if path.exists():
            # A completed slice whose manifest checkpoint was interrupted can
            # be retained after validating gzip; its pinned URL is unchanged.
            body = path.read_bytes()
            gzip.decompress(body)
            return dict(item, status='downloaded', bytes=len(body), sha256=file_hash(path),
                        recovered_without_replacement=True)
        path.parent.mkdir(exist_ok=True)
        for attempt in range(3):
            try:
                with urlopen(Request(item['url'], headers={'Accept-Encoding': 'gzip',
                             'User-Agent': 'fuse-asset-oracle-research/1.0'}), timeout=30) as response:
                    body = response.read(protocol['maximum_bytes'] + 1)
                    if len(body) > protocol['maximum_bytes']:
                        raise ValueError('compressed slice exceeds declared bound')
                    decoded = gzip.decompress(body)
                    if len(decoded) > protocol['maximum_decoded_bytes']:
                        raise ValueError('decoded slice exceeds declared bound')
                temporary = path.with_suffix('.partial')
                temporary.write_bytes(body)
                temporary.replace(path)
                return dict(item, status='downloaded', bytes=len(body), sha256=file_hash(path),
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
            if len(files) % 48 == 0 or len(files) == len(futures):
                result = dict(protocol_sha256=file_hash(protocol_path),
                              files=sorted(files, key=lambda r: r['at_ms']),
                              complete=len(files) == len(futures) and all(r['status'] == 'downloaded' for r in files))
                dump(manifest, result)
                print(json.dumps(dict(processed=len(files), total=len(futures),
                                      errors=sum(r['status'] != 'downloaded' for r in files))), flush=True)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--metadata', type=Path)
    parser.add_argument('--fetch', action='store_true')
    args = parser.parse_args()
    result = fetch(args.output) if args.fetch else prepare(args.output, args.metadata)
    if not args.fetch:
        print(json.dumps(dict(requests=len(result['requests']), assets=result['assets'],
                              available_since=result['available_since']), indent=2))
