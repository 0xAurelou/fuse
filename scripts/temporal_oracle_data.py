#!/usr/bin/env python3
"""Versioned 24-date oracle cache with complete raw January/August replacements."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import gzip
import json
from pathlib import Path
import shutil

from capture_dataset import file_hash
from chronological_raw_priors import training_rows
from research_bursty_optimizer import dump
from research_nonfrozen_pricing import verify_raw
from research_pooled_symbolic import load_inputs
from research_raw_flat_panels import parse_raw, prepare_rows
from research_startup_admission import verify_code

DAY=86400000


def origin(day):return int(datetime.fromisoformat(day).replace(tzinfo=timezone.utc).timestamp()*1000)


def complete_day(rows,day):
    left=origin(day)
    if len(rows)!=2880 or [r['start'] for r in rows]!=list(range(left,left+DAY,30000)):
        raise ValueError('a complete unmodified UTC grid is required: '+day)
    if any(r['period']!=day or r['expiry']!=r['start']+30000 for r in rows):
        raise ValueError('day/expiry binding differs')


def profile(rows):
    clean=[r for r in rows if r['valid'] and r['adaptive_features'] is not None]
    return dict(rows=len(rows),valid=sum(r['valid'] for r in rows),clean=len(clean),
                activities=dict(Counter(r['activity_state'] for r in clean)),
                regimes=dict(Counter(r['market_regime'] for r in clean)))


def parent_context(previous_dir):
    previous=json.loads((previous_dir/'research.json').read_text());verify_code(previous_dir,previous)
    for name,key in (('selection.json','selection_sha256'),('models.json','models_sha256'),
                     ('inner-models.json','inner_models_sha256'),('predictions.jsonl.gz','predictions_sha256')):
        if file_hash(previous_dir/name)!=previous[key]:raise ValueError('parent artifact differs')
    quantile_dir=Path(previous['previous'])
    if file_hash(quantile_dir/'research.json')!=previous['previous_sha256']:raise ValueError('quantile binding differs')
    quantile=json.loads((quantile_dir/'research.json').read_text());verify_code(quantile_dir,quantile)
    symbolic_dir=Path(quantile['previous'])
    if file_hash(symbolic_dir/'research.json')!=quantile['previous_sha256']:raise ValueError('symbolic binding differs')
    _,_,_,ctx,checked,_,_=load_inputs(symbolic_dir)
    return previous,ctx,checked


def build(previous_dir,output):
    if output.exists():raise ValueError('preserve existing dataset; choose a new output')
    protocol=dict(previous=str(previous_dir.resolve()),previous_sha256=file_hash(previous_dir/'research.json'),
        builder_sha256=file_hash(Path(__file__)),
        rule='Complete raw day replaces normalized day once. Add only full retained January/August 2026 UTC grids. No partial/raw merge or interpolation.',
        role='Chronological development cache across already inspected dates; no prospective result or new calendar-date holdout')
    output.mkdir(parents=True);dump(output/'protocol.json',protocol)
    shutil.copyfile(Path(__file__),output/'builder.py')
    _,ctx,checked=parent_context(previous_dir)
    dates=ctx['data']['dates']
    normalized=[r for r in ctx['original'] if r['period'] in dates]
    raw={day:rows for day,rows in ctx['expanded_rawdays'].items()}
    bindings={day:'earlier complete raw training archive' for day in raw}
    for day,source in (('2026-01-01','raw'),('2026-08-01','raw_control')):
        matches=[s for s in ctx['sessions'] if s['period']==day and s['source']==source and s['mode']=='continuous']
        if len(matches)!=1:raise ValueError('unique retained complete raw session required: '+day)
        rows=[p['row'] for p in matches[0]['values']]
        complete_day(rows,day)
        if day in raw:raise ValueError('duplicate raw date replacement')
        raw[day]=rows;bindings[day]=matches[0]['id']
    provenance=[]
    for day in dates:
        part=[r for r in normalized if r['period']==day];complete_day(part,day)
        if day in raw:complete_day(raw[day],day)
        provenance.append(dict(day=day,normalized=profile(part),raw=profile(raw[day]) if day in raw else None,
                               raw_binding=bindings.get(day)))
    for name,rows in (('normalized',normalized),('raw',[r for day in sorted(raw) for r in raw[day]])):
        with gzip.open(output/(name+'.jsonl.gz'),'wt',compresslevel=5) as stream:
            for r in rows:stream.write(json.dumps(r,separators=(',',':'),allow_nan=False)+'\n')
    result=dict(protocol,dates=dates,provenance=provenance,feature_records_verified=checked,
        normalized_sha256=file_hash(output/'normalized.jsonl.gz'),raw_sha256=file_hash(output/'raw.jsonl.gz'),
        source_dataset=ctx['previous']['dataset'],source_dataset_sha256=ctx['previous']['dataset_sha256'],
        no_candidate_promoted=True,capture_started=False)
    dump(output/'dataset.json',result)
    return result


def load(directory):
    metadata=json.loads((directory/'dataset.json').read_text())
    for name,key in (('normalized.jsonl.gz','normalized_sha256'),('raw.jsonl.gz','raw_sha256'),('builder.py','builder_sha256')):
        if file_hash(directory/name)!=metadata[key]:raise ValueError('temporal dataset artifact differs: '+name)
    previous=Path(metadata['previous'])
    if file_hash(previous/'research.json')!=metadata['previous_sha256']:raise ValueError('temporal parent differs')
    normalized=[];raw={}
    with gzip.open(directory/'normalized.jsonl.gz','rt') as stream:normalized=[json.loads(line) for line in stream]
    with gzip.open(directory/'raw.jsonl.gz','rt') as stream:
        for line in stream:
            r=json.loads(line);raw.setdefault(r['period'],[]).append(r)
    for day in metadata['dates']:
        complete_day([r for r in normalized if r['period']==day],day)
        if day in raw:complete_day(raw[day],day)
    return normalized,raw,metadata


def late_days(directory):
    digest=file_hash(directory/'download-manifest.json')
    verify_raw(dict(raw=str(directory),raw_manifest_sha256=digest))
    protocol=json.loads((directory/'download-protocol.json').read_text())
    if file_hash(directory/'prepare-source.py')!=protocol['preparer_sha256']:raise ValueError('download declaration differs')
    manifest=json.loads((directory/'download-manifest.json').read_text());result={}
    if sorted((p['url'],p['path']) for p in protocol['requests'])!=sorted((p['url'],p['path']) for p in manifest['files']):
        raise ValueError('late raw requests differ from declaration')
    for panel in protocol['panels']:
        files=sorted([f for f in manifest['files'] if f['day']==panel['day']],key=lambda f:f['at_ms'])
        if len(files)!=1440 or [f['at_ms'] for f in files]!=list(range(panel['start'],panel['end'],60000)):
            raise ValueError('complete late raw day missing minutes')
        observed,markers=parse_raw(files,directory)
        rows=prepare_rows(observed,panel,markers);complete_day(rows,panel['day'])
        result[panel['day']]=rows
    return result,dict(directory=str(directory.resolve()),manifest_sha256=digest,
                       protocol_sha256=file_hash(directory/'download-protocol.json'))


def preceding(normalized,raw,dates,cutoff):
    return training_rows(normalized,raw,dates,cutoff,True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--previous',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    args=p.parse_args();r=build(args.previous,args.output)
    print(json.dumps(dict(dates=len(r['dates']),raw_dates=[p['day'] for p in r['provenance'] if p['raw'] is not None],feature_records_verified=r['feature_records_verified']),indent=2))
