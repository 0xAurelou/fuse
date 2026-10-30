#!/usr/bin/env python3
"""Download matched, public, native 20-level ETH/HYPE first-of-month books."""
import argparse
from concurrent.futures import ThreadPoolExecutor,as_completed
from datetime import datetime,timezone
import gzip
import json
from pathlib import Path
import shutil
import time
from urllib.parse import urlencode
from urllib.request import Request,urlopen

from capture_dataset import file_hash

ASSETS=('ETH','HYPE')
DATES=tuple([f'2025-{m:02d}-01' for m in range(1,13)]+[f'2026-{m:02d}-01' for m in range(1,11)])


def dump(path,value):
    temporary=path.with_suffix(path.suffix+'.tmp')
    temporary.write_text(json.dumps(value,indent=2,allow_nan=False)+'\n');temporary.replace(path)


def prepare(root,metadata):
    if root.exists():raise ValueError('use a new download directory')
    source=json.loads(metadata.read_text());symbols={s['id']:s for s in source['availableSymbols']}
    if 'l2Book' not in source['availableChannels'] or any(symbols[a]['availableSince'][:10]>DATES[0] for a in ASSETS):
        raise ValueError('native book or asset coverage missing')
    requests=[]
    for day in DATES:
        at=int(datetime.fromisoformat(day).replace(tzinfo=timezone.utc).timestamp()*1000)
        for offset in range(0,1440,10):
            query=urlencode({
                'from':day+'T00:00:00.000Z','offset':offset,'sliceSize':10,
                'filters':json.dumps([dict(channel='l2Book',symbols=ASSETS)],separators=(',',':'))})
            requests.append(dict(day=day,at_ms=at+offset*60000,duration_ms=600000,
                path=f'{day}/{offset:04d}.bin',url='https://api.tardis.dev/v1/data-feeds/hyperliquid?'+query))
    root.mkdir(parents=True);shutil.copyfile(metadata,root/'exchange-metadata.json')
    shutil.copyfile(__file__,root/'fetch-source.py')
    protocol=dict(assets=ASSETS,dates=DATES,channel='l2Book',requests=requests,workers=12,
        maximum_compressed_bytes=3000000,maximum_decoded_bytes=20000000,
        source_sha256=file_hash(Path(__file__)),metadata_sha256=file_hash(metadata),authentication='none',
        sampling='Every full UTC first-of-month day January 2025 through October 2026; both assets, no outcome-selected times.',
        depth='Raw native slow up-to-20-level snapshots. Never normalized book_snapshot_25 or fastBook.',
        documentation='https://docs.tardis.dev/historical-data-details/hyperliquid',
        limitations='Monthly sampled historical development evidence, not consecutive days or an independent holdout')
    dump(root/'download-protocol.json',protocol);return protocol


def fetch(root):
    protocol=json.loads((root/'download-protocol.json').read_text())
    if file_hash(Path(__file__))!=protocol['source_sha256'] or file_hash(root/'fetch-source.py')!=protocol['source_sha256'] or file_hash(root/'exchange-metadata.json')!=protocol['metadata_sha256']:
        raise ValueError('download implementation or metadata changed')
    manifest=root/'download-manifest.json';old=json.loads(manifest.read_text()) if manifest.exists() else {}
    if old and old['protocol_sha256']!=file_hash(root/'download-protocol.json'):raise ValueError('protocol changed')
    retained={p['path']:p for p in old.get('files',[]) if p['status']=='downloaded'}
    def one(item):
        path=root/item['path'];path.parent.mkdir(exist_ok=True)
        if item['path'] in retained:
            p=retained[item['path']]
            if file_hash(path)!=p['sha256'] or item['url']!=p['url']:raise ValueError('retained slice differs')
            return p
        for attempt in range(3):
            try:
                if path.exists():body=path.read_bytes()
                else:
                    with urlopen(Request(item['url'],headers={'Accept-Encoding':'gzip','User-Agent':'fuse-historical-liquidity/1.0'}),timeout=30) as response:
                        body=response.read(protocol['maximum_compressed_bytes']+1)
                if len(body)>protocol['maximum_compressed_bytes']:raise ValueError('compressed bound exceeded')
                decoded=gzip.decompress(body)
                if len(decoded)>protocol['maximum_decoded_bytes']:raise ValueError('decoded bound exceeded')
                if not path.exists():
                    temp=path.with_suffix('.partial');temp.write_bytes(body);temp.replace(path)
                return dict(item,status='downloaded',bytes=len(body),decoded_bytes=len(decoded),sha256=file_hash(path),retrieved_at_ms=time.time_ns()//1000000)
            except Exception as exc:
                if attempt==2:return dict(item,status='error',error=str(exc))
                time.sleep(attempt+1)
    files=[]
    with ThreadPoolExecutor(max_workers=protocol['workers']) as pool:
        futures=[pool.submit(one,item) for item in protocol['requests']]
        for future in as_completed(futures):
            files.append(future.result())
            if len(files)%48==0 or len(files)==len(futures):
                result=dict(protocol_sha256=file_hash(root/'download-protocol.json'),
                    files=sorted(files,key=lambda p:p['at_ms']),
                    complete=len(files)==len(futures) and all(p['status']=='downloaded' for p in files))
                dump(manifest,result)
                print(json.dumps(dict(processed=len(files),total=len(futures),errors=sum(p['status']!='downloaded' for p in files))),flush=True)
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--directory',type=Path,required=True)
    parser.add_argument('--metadata',type=Path);parser.add_argument('--fetch',action='store_true');args=parser.parse_args()
    result=fetch(args.directory) if args.fetch else prepare(args.directory,args.metadata)
    print(json.dumps(dict(requests=len(result.get('requests',result.get('files',[]))),complete=result.get('complete'))))
