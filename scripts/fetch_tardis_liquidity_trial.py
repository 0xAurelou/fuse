#!/usr/bin/env python3
"""Fetch the user-selected September 1–10 raw ETH/HYPE oracle/book trial."""
import argparse
from concurrent.futures import ThreadPoolExecutor,as_completed
from datetime import datetime,timezone
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import threading
import time
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler,Request,build_opener

ASSETS=('ETH','HYPE')
DATES=tuple('2026-09-%02d'%day for day in range(1,11))
CHANNELS=('activeAssetCtx','l2Book')
KEY_FILE=Path(__file__).resolve().parents[1]/'.local/secrets/tardis.env'


def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def dump(path,value):
    temp=path.with_suffix(path.suffix+'.tmp')
    temp.write_text(json.dumps(value,indent=2,allow_nan=False)+'\n');temp.replace(path)


def origin(day):return int(datetime.fromisoformat(day).replace(tzinfo=timezone.utc).timestamp()*1000)


def load_key(path=KEY_FILE):
    value=os.environ.get('TARDIS_API_KEY') or os.environ.get('TARDIS_DATA_API_KEY')
    if not value and path.exists():
        for line in path.read_text().splitlines():
            name,sep,candidate=line.partition('=')
            if sep and name.strip()=='TARDIS_API_KEY':value=candidate.strip().strip('\"\'')
    if not value or value=='your_key' or any(c.isspace() for c in value):
        raise ValueError('A valid locally saved TARDIS_API_KEY is required')
    return value


def request_url(day,offset,size=10):
    filters=[dict(channel=c,symbols=ASSETS) for c in CHANNELS]
    query=urlencode({'from':day+'T00:00:00.000Z','offset':offset,'sliceSize':size,
                    'filters':json.dumps(filters,separators=(',',':'))})
    return 'https://api.tardis.dev/v1/data-feeds/hyperliquid?'+query


def declare(root):
    if root.exists():raise ValueError('Use a new trial directory')
    root.mkdir(parents=True);shutil.copyfile(__file__,root/'fetch-source.py')
    requests=[dict(day=day,at_ms=origin(day)+offset*60000,duration_ms=600000,
                   path=day+'/%04d.bin'%offset,url=request_url(day,offset))
              for day in DATES for offset in range(0,1440,10)]
    p=dict(assets=ASSETS,dates=DATES,channels=CHANNELS,requests=requests,workers=12,
        maximum_encoded_slice_bytes=4000000,maximum_decoded_slice_bytes=25000000,
        maximum_dataset_encoded_bytes=8*1024**3,maximum_dataset_decoded_bytes=16*1024**3,
        fetcher_sha256=digest(Path(__file__)),authentication='Bearer header only; no key archived',
        access='User selected the free trial covering September 1–10 when started in October 2026. No upgrade, purchase or date substitution.',
        source='Unmodified Hyperliquid activeAssetCtx and native 20-level l2Book, with Tardis receipt timestamps and disconnect markers.',
        timing='Data availability and completeness must be checked before fitting. Missing windows never become flat wins.',
        reuse='Existing monthly studies and live recorder remain separate and unchanged.')
    dump(root/'download-protocol.json',p);return p


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):return None


def decode(body,limit):
    with gzip.GzipFile(fileobj=io.BytesIO(body)) as stream:raw=stream.read(limit+1)
    if len(raw)>limit:raise ValueError('Decoded slice exceeded bound')
    return raw


def fetch(root,key):
    p=json.loads((root/'download-protocol.json').read_text())
    if digest(Path(__file__))!=p['fetcher_sha256'] or digest(root/'fetch-source.py')!=p['fetcher_sha256']:
        raise ValueError('Declared downloader source changed')
    prior_path=root/'download-manifest.json'
    prior=json.loads(prior_path.read_text()) if prior_path.exists() else {}
    if prior and prior['protocol_sha256']!=digest(root/'download-protocol.json'):
        raise ValueError('Existing manifest belongs to another declaration')
    retained={f['path']:f for f in prior.get('files',[]) if f['status']=='downloaded'}
    stop=threading.Event();lock=threading.Lock();totals=dict(encoded=0,decoded=0,requests=0)
    local=threading.local()
    def network(url):
        if not hasattr(local,'opener'):local.opener=build_opener(NoRedirect())
        if stop.is_set():raise ValueError('Stopped after another failed request')
        with lock:totals['requests']+=1
        req=Request(url,headers={'Authorization':'Bearer '+key,'Accept-Encoding':'gzip',
                                'User-Agent':'fuse-consecutive-liquidity-trial/1.0'})
        try:
            with local.opener.open(req,timeout=30) as response:
                body=response.read(p['maximum_encoded_slice_bytes']+1)
                headers={k.lower():v for k,v in response.headers.items() if k.lower().startswith(('x-ratelimit-','x-tardis-')) or k.lower() in ('x-request-id','content-encoding')}
        except HTTPError as exc:
            raise ValueError('Tardis HTTP %s; stop without changing the account'%exc.code) from None
        if len(body)>p['maximum_encoded_slice_bytes']:raise ValueError('Encoded slice exceeded bound')
        raw=decode(body,p['maximum_decoded_slice_bytes'])
        with lock:
            totals['encoded']+=len(body);totals['decoded']+=len(raw)
            if totals['encoded']>p['maximum_dataset_encoded_bytes'] or totals['decoded']>p['maximum_dataset_decoded_bytes']:
                raise ValueError('Dataset transfer bound exceeded')
        return body,raw,headers
    # Verify a trial-only date before scheduling the full download. September 1
    # alone cannot establish trial access because first-of-month data is public.
    probe=root/'entitlement-probe.bin'
    try:
        body,raw,headers=network(request_url('2026-09-02',0,1));probe.write_bytes(body)
        dump(root/'entitlement-probe.json',dict(url=request_url('2026-09-02',0,1),
             sha256=digest(probe),encoded_bytes=len(body),decoded_bytes=len(raw),headers=headers))
    except Exception as exc:
        dump(root/'access-status.json',dict(authenticated=False,error=str(exc).replace(key,'[redacted]')))
        raise
    dump(root/'access-status.json',dict(authenticated=True,trial_only_date='2026-09-02',no_purchase=True))
    def one(item):
        path=root/item['path']
        try:
            if path.exists():
                body=path.read_bytes();raw=decode(body,p['maximum_decoded_slice_bytes']);headers={}
                if len(body)>p['maximum_encoded_slice_bytes']:raise ValueError('Cached slice exceeds bound')
                if item['path'] in retained:
                    saved=retained[item['path']]
                    if saved['sha256']!=digest(path) or saved['url']!=item['url']:
                        raise ValueError('Cached slice hash or URL changed')
                    headers=saved['headers']
                with lock:
                    totals['encoded']+=len(body);totals['decoded']+=len(raw)
                    if totals['encoded']>p['maximum_dataset_encoded_bytes'] or totals['decoded']>p['maximum_dataset_decoded_bytes']:
                        raise ValueError('Retained dataset exceeds bound')
            else:
                body,raw,headers=network(item['url']);path.parent.mkdir(exist_ok=True)
                temp=path.with_suffix('.partial');temp.write_bytes(body);temp.replace(path)
            return dict(item,status='downloaded',bytes=len(body),decoded_bytes=len(raw),
                        sha256=digest(path),headers=headers)
        except Exception as exc:
            stop.set();return dict(item,status='error',error=str(exc).replace(key,'[redacted]'))
    files=[]
    with ThreadPoolExecutor(max_workers=p['workers']) as pool:
        futures=[pool.submit(one,item) for item in p['requests']]
        for future in as_completed(futures):
            files.append(future.result())
            if len(files)%48==0 or len(files)==len(futures):
                result=dict(protocol_sha256=digest(root/'download-protocol.json'),
                    complete=len(files)==len(futures) and all(f['status']=='downloaded' for f in files),
                    network_totals_this_run=dict(totals),files=sorted(files,key=lambda f:f['at_ms']))
                dump(root/'download-manifest.json',result)
                print(json.dumps(dict(processed=len(files),total=len(futures),errors=sum(f['status']!='downloaded' for f in files))),flush=True)
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--directory',type=Path,required=True)
    parser.add_argument('--declare',action='store_true');args=parser.parse_args()
    try:
        if args.declare:r=declare(args.directory);print(json.dumps(dict(requests=len(r['requests']),dates=r['dates'])))
        else:
            r=fetch(args.directory,load_key());print(json.dumps(dict(complete=r['complete'])))
            raise SystemExit(0 if r['complete'] else 1)
    except Exception as exc:
        print(json.dumps(dict(complete=False,error_type=type(exc).__name__,error='Stopped; see local status or manifest if created')))
        raise SystemExit(1)
