#!/usr/bin/env python3
"""Download only public, unauthenticated historical development samples."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import gzip
import json
from pathlib import Path
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from capture_dataset import file_hash


def fetch(url, path, limit=10_000_000):
    if path.exists():
        return
    partial = path.with_name(path.name + '.partial')
    with urlopen(Request(url, headers={'User-Agent': 'fuse-history-research/1.0'}), timeout=30) as response:
        total = 0
        with partial.open('wb') as stream:
            while True:
                block = response.read(1024 * 1024)
                if not block:
                    break
                total += len(block)
                if total > limit:
                    raise ValueError('public sample exceeds declared download size limit')
                stream.write(block)
    partial.rename(path)


def tardis(output):
    if output.exists():
        raise ValueError('output already exists; preserve retained download manifests')
    output.mkdir(parents=True)
    dates = [f'{year}-{month:02d}-01' for year in (2024, 2025, 2026) for month in range(1, 13)
             if '2024-11-01' <= f'{year}-{month:02d}-01' <= '2026-10-01']
    protocol = dict(provider='Tardis', exchange='hyperliquid', symbol='BTC',
                    data_type='derivative_ticker', dates=dates,
                    selection='All first-of-month free sample days from November 2024 through October 2026; no paid/authenticated requests',
                    role='Third-party normalized historical oracle research; not native paired-receiver receipts',
                    expected_price_field='index_price', max_bytes_per_sample=10_000_000,
                    documentation='https://docs.tardis.dev/historical-data-details/hyperliquid')
    (output / 'download-protocol.json').write_text(json.dumps(protocol, indent=2) + '\n')
    mapping_url = 'https://raw.githubusercontent.com/tardis-dev/tardis-node/master/src/mappers/hyperliquid.ts'
    fetch(mapping_url, output / 'normalizer-hyperliquid.ts', limit=100_000)
    metadata_url = 'https://api.tardis.dev/v1/exchanges/hyperliquid'
    fetch(metadata_url, output / 'exchange-metadata.json', limit=5_000_000)

    def one(date):
        url = f"https://datasets.tardis.dev/v1/hyperliquid/derivative_ticker/{date.replace('-', '/')}/BTC.csv.gz"
        path = output / (date + '-BTC.csv.gz')
        try:
            fetch(url, path)
            # Read through gzip CRC validation; do not silently accept truncated CSV.
            with gzip.open(path, 'rb') as stream:
                header = stream.readline().decode().strip()
                for _ in iter(lambda: stream.read(1024 * 1024), b''):
                    pass
            if 'index_price' not in header.split(','):
                raise ValueError('index_price field missing')
            return dict(date=date, url=url, path=path.name, bytes=path.stat().st_size,
                        sha256=file_hash(path), header=header, status='downloaded',
                        retrieved_at_ms=time.time_ns() // 1_000_000)
        except HTTPError as error:
            return dict(date=date, url=url, status='http_error', http_status=error.code)
        except Exception as error:
            return dict(date=date, url=url, status='error', error=str(error))

    with ThreadPoolExecutor(max_workers=4) as pool:
        files = list(pool.map(one, dates))
    result = dict(protocol, files=files, normalizer_url=mapping_url,
                  normalizer_sha256=file_hash(output / 'normalizer-hyperliquid.ts'),
                  metadata_sha256=file_hash(output / 'exchange-metadata.json'),
                  fetcher_sha256=file_hash(Path(__file__)))
    (output / 'download-manifest.json').write_text(json.dumps(result, indent=2) + '\n')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = tardis(args.output)
    print(json.dumps(dict(output=str(args.output), files=result['files']), indent=2))


if __name__ == '__main__':
    main()
