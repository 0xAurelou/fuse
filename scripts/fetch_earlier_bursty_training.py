#!/usr/bin/env python3
"""Pin anonymous full raw days preceding the January 2025 diagnostic."""
import argparse
from datetime import datetime,timezone
import json
from pathlib import Path
import shutil
from urllib.parse import urlencode

import fetch_flat_samples
from bursty_startup_admission import SPECS
from capture_dataset import file_hash
from research_startup_admission import verify_code


def prepare(previous,output):
    if output.exists():raise ValueError('preserve pinned downloads; fetch resumes its exact request list')
    metadata=json.loads((previous/'research.json').read_text());verify_code(previous,metadata)
    panels=[];requests=[]
    for day in ('2024-11-01','2024-12-01'):
        origin=int(datetime.fromisoformat(day).replace(tzinfo=timezone.utc).timestamp()*1000)
        panels.append(dict(day=day,start=origin,end=origin+86_400_000,fetch_start=origin,fetch_end=origin+86_400_000,
                           selection='Complete original monthly training day strictly preceding January 2025; no outcome-selected intervals'))
        for offset in range(1440):
            query=urlencode(dict(**{'from':day+'T00:00:00.000Z'},offset=offset,
                filters=json.dumps([dict(channel='activeAssetCtx',symbols=['BTC'])],separators=(',',':'))))
            requests.append(dict(day=day,at_ms=origin+offset*60_000,path=f'{day}/{offset:04d}.bin',
                url='https://api.tardis.dev/v1/data-feeds/hyperliquid?'+query))
    protocol=dict(previous=str(previous.resolve()),previous_sha256=file_hash(previous/'research.json'),
        dataset=metadata['dataset'],dataset_sha256=metadata['dataset_sha256'],panels=panels,requests=requests,
        admission_specs=SPECS,pricing_method='floor10_burst_pool120',
        admission_source_sha256=file_hash(Path(__file__).with_name('bursty_startup_admission.py')),
        source_sha256=file_hash(Path(fetch_flat_samples.__file__)),preparer_sha256=file_hash(Path(__file__)),
        authentication='none',maximum_bytes_per_response=200_000,workers=8,
        source_role='Earlier raw training coverage on existing monthly dates, not independent holdouts',
        capture_started=False,live_candidate_promoted=False)
    output.mkdir(parents=True)
    (output/'download-protocol.json').write_text(json.dumps(protocol,indent=2)+'\n')
    for source,target in ((Path(fetch_flat_samples.__file__),'fetch-source.py'),(Path(__file__),'prepare-source.py'),
                          (Path(__file__).with_name('bursty_startup_admission.py'),'admission-source.py')):
        shutil.copyfile(source,output/target)
    return dict(days=[p['day'] for p in panels],requests=len(requests))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--previous',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();print(json.dumps(prepare(a.previous,a.output),indent=2))
