#!/usr/bin/env python3
"""Extend retained raw controls under a pinned admission-policy declaration."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
from urllib.parse import urlencode

from capture_dataset import file_hash
import fetch_flat_samples
from oracle_activity_features import load


def prepare(dataset, parent, admission, output):
    if output.exists():
        raise ValueError('output exists; retain the pinned request list')
    load(dataset)
    research = json.loads((admission / 'research.json').read_text())
    if file_hash(Path(__file__).with_name('startup_admission.py')) != research['source_sha256']['startup_admission.py']:
        raise ValueError('admission policies changed since the preceding comparison')
    old = json.loads((parent / 'download-protocol.json').read_text())
    previous = json.loads((parent / 'download-manifest.json').read_text())
    if not previous['complete'] or previous['protocol_sha256'] != file_hash(parent / 'download-protocol.json'):
        raise ValueError('parent raw controls incomplete or changed')
    if old['dataset_sha256'] != file_hash(dataset / 'dataset.json'):
        raise ValueError('original dataset differs')
    panels = []
    for p in old['panels']:
        if p['day'] == '2026-01-01':
            continue  # Complete January already retained; do not duplicate it.
        panels.append(dict(p, end=p['start'] + 8 * 3_600_000, fetch_end=p['start'] + 8 * 3_600_000,
                           selection='Same previously selected start; extend right boundary from four to eight hours'))
    origin = int(datetime(2026, 8, 1, tzinfo=timezone.utc).timestamp() * 1000)
    panels.append(dict(day='2026-08-01', start=origin, end=origin + 86_400_000,
                       fetch_start=origin, fetch_end=origin + 86_400_000,
                       selection='Complete raw version of known normalized August failure; no interval removal'))
    requests = []
    for p in panels:
        origin = p['start'] // 86_400_000 * 86_400_000
        for at in range(p['fetch_start'], p['fetch_end'], 60_000):
            offset = (at - origin) // 60_000
            query = urlencode(dict(**{'from': p['day'] + 'T00:00:00.000Z'}, offset=offset,
                                   filters=json.dumps([dict(channel='activeAssetCtx', symbols=['BTC'])], separators=(',', ':'))))
            requests.append(dict(day=p['day'], at_ms=at, path=f'{p["day"]}/{offset:04d}.bin',
                                 url='https://api.tardis.dev/v1/data-feeds/hyperliquid?' + query))
    protocol = dict(dataset=str(dataset.resolve()), dataset_sha256=file_hash(dataset / 'dataset.json'),
                    admission=str(admission.resolve()), admission_sha256=file_hash(admission / 'research.json'),
                    admission_source_sha256=research['source_sha256']['startup_admission.py'],
                    source_sha256=file_hash(Path(fetch_flat_samples.__file__)),
                    preparer_sha256=file_hash(Path(__file__)), panels=panels, requests=requests,
                    authentication='none', maximum_bytes_per_response=200_000, workers=8,
                    documentation='https://docs.tardis.dev/api/http-api-reference',
                    source_role='Raw historical admission diagnostics; already inspected dates, not independent holdouts',
                    capture_started=False, live_candidate_promoted=False)
    output.mkdir(parents=True)
    (output / 'download-protocol.json').write_text(json.dumps(protocol, indent=2) + '\n')
    shutil.copyfile(Path(fetch_flat_samples.__file__), output / 'fetch-source.py')
    shutil.copyfile(Path(__file__), output / 'prepare-source.py')
    expected = {r['path']: r['url'] for r in requests}
    reused = []
    for f in previous['files']:
        if f['path'] not in expected:
            continue
        if expected[f['path']] != f['url'] or file_hash(parent / f['path']) != f['sha256']:
            raise ValueError('parent raw minute differs')
        destination = output / f['path']
        destination.parent.mkdir(exist_ok=True)
        shutil.copyfile(parent / f['path'], destination)
        reused.append(f)
    (output / 'reuse.json').write_text(json.dumps(dict(parent=str(parent.resolve()),
          parent_manifest_sha256=file_hash(parent / 'download-manifest.json'), files=[r['path'] for r in reused]), indent=2) + '\n')
    (output / 'download-manifest.json').write_text(json.dumps(dict(protocol_sha256=file_hash(output / 'download-protocol.json'),
          files=reused, complete=False), indent=2) + '\n')
    return dict(panels=panels, requests=len(requests), reused=len(reused), new_requests=len(requests) - len(reused))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset', type=Path, required=True)
    parser.add_argument('--parent', type=Path, required=True)
    parser.add_argument('--admission', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(prepare(args.dataset, args.parent, args.admission, args.output), indent=2))


if __name__ == '__main__':
    main()
