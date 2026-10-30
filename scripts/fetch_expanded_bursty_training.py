#!/usr/bin/env python3
"""Pin complete February–May 2025 raw days before inspecting their outcomes."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
from urllib.parse import urlencode

import fetch_flat_samples
from calibrated_bursty import SPEC, VARIANTS
from capture_dataset import file_hash
from research_startup_admission import verify_code

DAYS = ('2025-02-01', '2025-03-01', '2025-04-01', '2025-05-01')


def prepare(previous, output):
    if output.exists():
        raise ValueError('preserve pinned downloads; --fetch resumes the exact request list')
    metadata = json.loads((previous / 'research.json').read_text())
    verify_code(previous, metadata)
    panels, requests = [], []
    for day in DAYS:
        origin = int(datetime.fromisoformat(day).replace(tzinfo=timezone.utc).timestamp() * 1000)
        panels.append(dict(day=day, start=origin, end=origin + 86_400_000,
                           fetch_start=origin, fetch_end=origin + 86_400_000,
                           selection='All four missing consecutive monthly raw training dates between existing January and June 2025 days; complete UTC days, no outcome-based intervals'))
        for offset in range(1440):
            query = urlencode({'from': day + 'T00:00:00.000Z', 'offset': offset,
                               'filters': json.dumps([dict(channel='activeAssetCtx', symbols=['BTC'])], separators=(',', ':'))})
            requests.append(dict(day=day, at_ms=origin + offset * 60_000,
                                 path=f'{day}/{offset:04d}.bin',
                                 url='https://api.tardis.dev/v1/data-feeds/hyperliquid?' + query))
    protocol = dict(previous=str(previous.resolve()), previous_sha256=file_hash(previous / 'research.json'),
                    dataset=metadata['dataset'], dataset_sha256=metadata['dataset_sha256'],
                    panels=panels, requests=requests, spec=SPEC, variants=VARIANTS,
                    source_sha256=file_hash(Path(fetch_flat_samples.__file__)),
                    preparer_sha256=file_hash(Path(__file__)), authentication='none',
                    maximum_bytes_per_response=200_000, workers=8,
                    comparison='Existing versus expanded raw replacements; same formulas, engines, masks, chronological folds, objective and 95% pooled / 90% populated-case bursty retention. Training dates are unchanged; replace normalized rows only before each fit cutoff. Evaluated dates and raw outcomes excluded from selection.',
                    source_role='Full raw replacements on existing training dates; neither new calendar-day samples nor independent holdouts',
                    capture_started=False, live_candidate_promoted=False)
    output.mkdir(parents=True)
    (output / 'download-protocol.json').write_text(json.dumps(protocol, indent=2) + '\n')
    shutil.copyfile(Path(fetch_flat_samples.__file__), output / 'fetch-source.py')
    shutil.copyfile(Path(__file__), output / 'prepare-source.py')
    return dict(days=list(DAYS), requests=len(requests))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--previous', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(prepare(args.previous, args.output), indent=2))
