#!/usr/bin/env python3
"""Retain provider coverage metadata for the declared ETH/HYPE book window."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import time
from urllib.parse import urlencode
from urllib.request import Request, build_opener

from probe_oxarchive_liquidity import ASSETS, BASE, NoRedirect, decode_payload, dump, load_key


def fetch(root):
    protocol=json.loads((root/'protocol.json').read_text())
    query={'from':protocol['start_ms'],'to':protocol['end_ms']}
    directory=root/'provider-quality';directory.mkdir(exist_ok=True)
    key=load_key();opener=build_opener(NoRedirect());results=[]
    for asset in ASSETS:
        route='/v1/data-quality/coverage/hyperliquid/'+asset
        request=Request(BASE+route+'?'+urlencode(query),headers={
            'X-API-Key':key,'0xArchive-Version':'2026-10-01','Accept-Encoding':'gzip',
            'User-Agent':'fuse-liquidity-coverage/1.0'})
        try:
            with opener.open(request,timeout=30) as response:
                raw=decode_payload(response.read(8000001),response.headers.get('Content-Encoding',''))
            payload=json.loads(raw)
            if payload.get('success') is not True:raise ValueError('Provider did not confirm success')
            path=directory/(asset+'.json.gz');path.write_bytes(gzip.compress(raw,mtime=0))
            results.append(dict(asset=asset,route=route,query=query,path=str(path.relative_to(root)),
                sha256=hashlib.sha256(path.read_bytes()).hexdigest(),request_id=payload.get('meta',{}).get('request_id'),
                success=True))
        except Exception as exc:
            # Never print headers or raw authentication errors.
            results.append(dict(asset=asset,route=route,query=query,success=False,error_type=type(exc).__name__))
        time.sleep(.5)
    dump(directory/'manifest.json',dict(source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        results=results,interpretation='Provider metadata is supplementary. Raw native-venue timestamps determine gaps; metadata may summarize other book sources.'))
    return results


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--directory',type=Path,required=True)
    args=parser.parse_args();print(json.dumps(fetch(args.directory)))
