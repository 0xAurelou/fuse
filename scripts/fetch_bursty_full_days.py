#!/usr/bin/env python3
"""Pin full-day raw extensions for previously inspected January/June failures."""
import argparse
from datetime import datetime,timezone
import json
from pathlib import Path
import shutil
from urllib.parse import urlencode

from bursty_episodes import SPECS
from capture_dataset import file_hash
import fetch_flat_samples
from research_startup_admission import verify_code


def prepare(previous,parent,output):
    if output.exists():raise ValueError('preserve pinned downloads')
    metadata=json.loads((previous/'research.json').read_text());verify_code(previous,metadata)
    old=json.loads((parent/'download-manifest.json').read_text())
    if not old['complete'] or old['protocol_sha256']!=file_hash(parent/'download-protocol.json'):raise ValueError('parent raw manifest differs')
    days=('2025-01-01','2025-06-01');panels=[];requests=[]
    for day in days:
        origin=int(datetime.fromisoformat(day).replace(tzinfo=timezone.utc).timestamp()*1000)
        panels.append(dict(day=day,start=origin,end=origin+86_400_000,fetch_start=origin,fetch_end=origin+86_400_000,
                           selection='Complete previously inspected failure day; no outcome-based interval removal'))
        for offset in range(1440):
            query=urlencode(dict(**{'from':day+'T00:00:00.000Z'},offset=offset,
                                 filters=json.dumps([dict(channel='activeAssetCtx',symbols=['BTC'])],separators=(',',':'))))
            requests.append(dict(day=day,at_ms=origin+offset*60_000,path=f'{day}/{offset:04d}.bin',
                                 url='https://api.tardis.dev/v1/data-feeds/hyperliquid?'+query))
    protocol=dict(previous=str(previous.resolve()),previous_sha256=file_hash(previous/'research.json'),
                  dataset=metadata['dataset'],dataset_sha256=metadata['dataset_sha256'],panels=panels,requests=requests,
                  specs=SPECS,candidate_source_sha256=file_hash(Path(__file__).with_name('bursty_episodes.py')),
                  source_sha256=file_hash(Path(fetch_flat_samples.__file__)),preparer_sha256=file_hash(Path(__file__)),
                  authentication='none',maximum_bytes_per_response=200_000,workers=8,
                  source_role='Raw extensions of known failure days, not independent holdouts or prospective captures',
                  capture_started=False,live_candidate_promoted=False)
    output.mkdir(parents=True)
    (output/'download-protocol.json').write_text(json.dumps(protocol,indent=2)+'\n')
    shutil.copyfile(Path(fetch_flat_samples.__file__),output/'fetch-source.py')
    shutil.copyfile(Path(__file__),output/'prepare-source.py')
    shutil.copyfile(Path(__file__).with_name('bursty_episodes.py'),output/'candidate-source.py')
    expected={r['path']:r['url'] for r in requests};reused=[]
    for f in old['files']:
        if f['path'] not in expected:continue
        if expected[f['path']]!=f['url'] or file_hash(parent/f['path'])!=f['sha256']:raise ValueError('reused minute differs')
        target=output/f['path'];target.parent.mkdir(exist_ok=True);shutil.copyfile(parent/f['path'],target);reused.append(f)
    (output/'reuse.json').write_text(json.dumps(dict(parent=str(parent.resolve()),manifest_sha256=file_hash(parent/'download-manifest.json'),files=[r['path'] for r in reused]),indent=2)+'\n')
    (output/'download-manifest.json').write_text(json.dumps(dict(protocol_sha256=file_hash(output/'download-protocol.json'),files=reused,complete=False),indent=2)+'\n')
    return dict(requests=len(requests),reused=len(reused),missing=len(requests)-len(reused),days=days)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--previous',type=Path,required=True);p.add_argument('--parent',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();print(json.dumps(prepare(a.previous,a.parent,a.output),indent=2))
