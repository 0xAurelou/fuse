#!/usr/bin/env python3
"""Freeze the ETH global policy before scoring an uninspected native prefix."""
import argparse
import gzip
import json
from pathlib import Path
import shutil
import time

from audit_payout_walkforward import same
from collect_liquidity import verify_plan as verify_capture
from fetch_tardis_liquidity_trial import origin
from joint_x1000 import admissible,fit,forecast,levels,quote
from native_liquidity_prefix_v2 import parse_eth,snapshot_index,verify_books
from research_asset_corridors import source_files
from research_flat_aware_payout import inputs as previous_inputs
from research_joint_x1000 import independent_quote,manual_forecast,verify_levels,verify_plan as verify_parent
from research_payout_risk import digest,dump
from research_trial_payout import save_gzip
from payout_risk import weekend
from trial_payout import clean,metrics
from freeze_eth_x1000 import verify_plan as verify_original

SPEC=dict(version='frozen-eth-global-x1000-v2',asset='ETH',variant='joint_global',
    frozen='Same joint_global recipe, coefficients and calibration fitted once using only the audited historical inputs. No native prefix data used in fit or calibration; no refit after viewing prefix outcomes.',
    role='First out-of-time formula replay of a previously unscored finalized native prefix. Data already existed before this declaration; this is not pre-event recorded prediction or a complete-day prospective validation.',
    collection='Read-only finalized index prefix; open segment excluded. Preserve the live collector and its original final-seven-day holdout. Analyze ETH only, never build fresh HYPE outcomes.',
    eligibility='Same oracle path features, strict prior native books, gaps censored, UTC daily resets. Include capture outages in separate grid coverage; never count silence as a flat winning path.',no_promotion=True)


def declare(frozen_parent,output):
    if output.exists():raise ValueError('Use a new ETH parser-amendment packet')
    original=verify_original(frozen_parent);frozen=json.loads((frozen_parent/'freeze.json').read_text())
    if (frozen_parent/'research.json').exists():raise ValueError('Parser amendment expects the original unscored failed prefix')
    if digest(frozen_parent/'candidate.json.gz')!=frozen['candidate_sha256']:raise ValueError('Original frozen candidate changed')
    output.mkdir(parents=True);(output/'source').mkdir();sources=sorted(set(source_files()+[Path(__file__).resolve()]))
    for p in sources:shutil.copyfile(p,output/'source'/p.name)
    plan=dict(original,spec=SPEC,source_sha256={p.name:digest(p) for p in sources},frozen_parent=str(frozen_parent.resolve()),original_protocol_sha256=digest(frozen_parent/'protocol.json'),original_freeze_sha256=digest(frozen_parent/'freeze.json'),declared_at_ns=time.time_ns(),model_and_capture_prefix_unchanged=True,parser_amendment='All receipts remain hash-verified; only ETH oracle/book and reset control receipts advance the pricing timeline. Two backsteps among unrelated WebSocket receipts must not reject a strictly ordered ETH pricing stream. No sorting or dropping of required ETH price messages.')
    dump(output/'protocol.json',plan);shutil.copyfile(frozen_parent/'candidate.json.gz',output/'candidate.json.gz')
    dump(output/'freeze.json',dict(candidate_sha256=frozen['candidate_sha256'],protocol_sha256=digest(output/'protocol.json'),frozen_at_ns=time.time_ns(),original_frozen_at_ns=frozen['frozen_at_ns'],native_outcomes_inspected=False))
    return plan


def verify_plan(output):
    p=json.loads((output/'protocol.json').read_text());original=Path(p['frozen_parent']);verify_original(original)
    if digest(original/'protocol.json')!=p['original_protocol_sha256'] or digest(original/'freeze.json')!=p['original_freeze_sha256']:raise ValueError('Original ETH freeze binding differs')
    for name,sha in p['source_sha256'].items():
        if digest(output/'source'/name)!=sha or digest(Path(__file__).with_name(name))!=sha:raise ValueError('ETH frozen source changed: '+name)
    parent=Path(p['parent']);verify_parent(parent)
    if digest(parent/'research.json')!=p['parent_sha256'] or digest(parent/'audit.json')!=p['parent_audit_sha256']:raise ValueError('ETH frozen parent changed')
    _,genesis=verify_capture(Path(p['capture']))
    if genesis!=p['capture_plan_sha256']:raise ValueError('ETH capture plan differs')
    return p


def inputs(plan):
    parent=Path(plan['parent']);p=json.loads((parent/'protocol.json').read_text());a=json.loads((Path(p['active'])/'protocol.json').read_text());earlier,rows,_,_,binding=previous_inputs(json.loads((Path(a['parent'])/'protocol.json').read_text()));meta=json.loads((parent/'research.json').read_text());path=parent/'ETH/research.json'
    if digest(path)!=meta['research_sha256']['ETH']:raise ValueError('ETH reference metadata changed')
    meta=json.loads(path.read_text());path=parent/'ETH/predictions.jsonl.gz'
    if digest(path)!=meta['predictions_sha256']:raise ValueError('ETH reference trace changed')
    refs=[]
    with gzip.open(path,'rt') as s:
        for line in s:
            r=json.loads(line)
            if r['variant']=='joint_raw' and r['reference'] is not None:refs.append(r['reference'])
    pool=earlier['ETH']+[r for r in rows['ETH'] if clean(r) and r.get('liquidity') is not None]
    return pool,refs,binding


def make_candidate(pool,refs,cutoff):
    return dict(asset='ETH',cutoff=cutoff,model=fit(pool,'ETH',cutoff),levels=levels(refs,'ETH',cutoff),variant='joint_global',native_capture_used_for_training=False)


def summarize(rows,values):
    result={}
    for cohort in ('matched','all_clean'):
        result[cohort]={}
        for g in ('overall','weekday','weekend'):
            ids=[i for i,r in enumerate(rows) if (cohort=='all_clean' or r.get('liquidity') is not None and r['adaptive_features'] is not None) and (g=='overall' or weekend(r)==(g=='weekend'))]
            part=[rows[i] for i in ids];result[cohort][g]=metrics(part,[values[i] for i in ids],1000)
    return result


def score(rows,packet,independent=False):
    if any(r['asset']!='ETH' or r['start']<origin(packet['cutoff']) for r in rows):raise ValueError('ETH validation asset/as-of mismatch')
    values=[]
    for r in rows:
        p=(manual_forecast if independent else forecast)(r,packet['model']) if admissible(r) else None
        value=independent_quote(r,'joint_global',packet,p) if independent else quote(r,'joint_global',packet,p);values.append(value)
    return values,summarize(rows,values)


def execute(output,auditing=False):
    p=verify_plan(output);pool,refs,binding=inputs(p);path=output/'candidate.json.gz'
    if auditing:
        with gzip.open(path,'rt') as f:packet=json.load(f)
        same(packet['model'],fit(pool,'ETH',p['cutoff']));verify_levels(packet['levels'],refs,'ETH',p['cutoff'])
        same({k:v for k,v in packet.items() if k not in ('model','levels')},dict(asset='ETH',cutoff=p['cutoff'],variant='joint_global',native_capture_used_for_training=False))
        frozen=json.loads((output/'freeze.json').read_text())
        if frozen['candidate_sha256']!=digest(path) or frozen['protocol_sha256']!=digest(output/'protocol.json'):raise ValueError('Frozen ETH candidate differs')
    else:
        
        with gzip.open(path,'rt') as f:packet=json.load(f)
        frozen=json.loads((output/'freeze.json').read_text())
        if digest(path)!=frozen['candidate_sha256'] or frozen['protocol_sha256']!=digest(output/'protocol.json'):raise ValueError('Reused ETH freeze differs')
    rows,qc,books=parse_eth(Path(p['capture']),p['capture_prefix']);verify_books(rows,books)
    if not rows or frozen['frozen_at_ns']<p['declared_at_ns']:raise ValueError('ETH freeze timing differs')
    values,results=score(rows,packet,auditing)
    if auditing:
        meta=json.loads((output/'research.json').read_text());same(binding,meta['bindings'])
        if meta['protocol_sha256']!=digest(output/'protocol.json') or meta['freeze_sha256']!=digest(output/'freeze.json') or meta['candidate_sha256']!=digest(path):raise ValueError('ETH research freeze binding differs')
        if digest(output/'predictions.jsonl.gz')!=meta['predictions_sha256'] or digest(output/'rows.jsonl.gz')!=meta['rows_sha256']:raise ValueError('ETH prefix output differs')
        with gzip.open(output/'rows.jsonl.gz','rt') as s:
            for r in rows:same(json.loads(s.readline()),r)
            if s.readline():raise ValueError('Extra ETH prefix rows')
        with gzip.open(output/'predictions.jsonl.gz','rt') as s:
            for r,v in zip(rows,values):same(json.loads(s.readline()),dict(asset='ETH',period=r['period'],start=r['start'],multiplier=1000,variant='frozen_global',**v))
            if s.readline():raise ValueError('Extra ETH prefix predictions')
        same(meta['results'],results);same(meta['quality'],qc)
        result=dict(passed=True,research_sha256=digest(output/'research.json'),candidate_refit_verified=True,strict_native_book_join_verified=True,source_receipts_reconstructed=True,decisions_independently_replayed=len(rows));dump(output/'audit.json',result)
    else:
        with gzip.open(output/'rows.jsonl.gz','xt') as s:
            for r in rows:s.write(json.dumps(r,separators=(',',':'),allow_nan=False)+'\n')
        with gzip.open(output/'predictions.jsonl.gz','xt') as s:
            for r,v in zip(rows,values):s.write(json.dumps(dict(asset='ETH',period=r['period'],start=r['start'],multiplier=1000,variant='frozen_global',**v),separators=(',',':'),allow_nan=False)+'\n')
        result=dict(protocol_sha256=digest(output/'protocol.json'),freeze_sha256=digest(output/'freeze.json'),candidate_sha256=digest(path),bindings=binding,quality=qc,results=results,rows_sha256=digest(output/'rows.jsonl.gz'),predictions_sha256=digest(output/'predictions.jsonl.gz'),evaluation_started_after_freeze=True,native_hype_outcomes_inspected=False,no_promotion=True);dump(output/'research.json',result)
    verify_plan(output);return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--frozen-parent',type=Path);p.add_argument('--output',type=Path,required=True);p.add_argument('--declare',action='store_true');p.add_argument('--audit',action='store_true');a=p.parse_args();r=declare(a.frozen_parent,a.output) if a.declare else execute(a.output,a.audit);print(json.dumps(dict(declared=a.declare,audited=a.audit,passed=r.get('passed'),matched=r.get('results',{}).get('matched',{}).get('overall',{}).get('pooled'))))
