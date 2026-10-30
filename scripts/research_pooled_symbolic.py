#!/usr/bin/env python3
"""Expanded symbolic experiment with a shared all-state regime model."""
import argparse
import gzip
import json
from pathlib import Path
import shutil
import time

from capture_dataset import file_hash
from investigate_capture import write_csv
from pooled_symbolic_corridor import SPEC as POOL_SPEC, fit
from research_bursty_optimizer import dump, inputs_for_search
from research_preentry_bursty import AVAILABILITY
from research_startup_admission import verify_code
from research_symbolic_corridor import (DEPENDENCIES as PARENT_DEPENDENCIES, STABILITY, VARIANTS,
    diagnostics, load_inputs as load_optimizer_inputs, select)
from symbolic_corridor import SPEC

DEPENDENCIES=tuple(dict.fromkeys(('pooled_symbolic_corridor.py','research_pooled_symbolic.py',
    'test_pooled_symbolic.py','audit_pooled_symbolic.py')+PARENT_DEPENDENCIES))


def load_inputs(previous_dir):
    first=json.loads((previous_dir/'research.json').read_text()); verify_code(previous_dir,first)
    for name,key in (('selection.json','selection_sha256'),('models.json','models_sha256'),
                     ('symbolic-training.jsonl.gz','training_sha256'),('predictions.jsonl.gz','predictions_sha256')):
        if file_hash(previous_dir/name)!=first[key]: raise ValueError('first symbolic artifact differs')
    optimizer=Path(first['previous'])
    if file_hash(optimizer/'research.json')!=first['previous_sha256']: raise ValueError('optimizer binding differs')
    return load_optimizer_inputs(optimizer)


def run(previous_dir,output):
    if output.exists(): raise ValueError('preserve prior experiment; choose a new output')
    protocol=dict(previous=str(previous_dir.resolve()),previous_sha256=file_hash(previous_dir/'research.json'),
        source_sha256={n:file_hash(Path(__file__).with_name(n)) for n in DEPENDENCIES},spec=SPEC,pooled_spec=POOL_SPEC,
        variants=VARIANTS,stability=STABILITY,availability_constraints=AVAILABILITY,target_survival=.48,band=[.43,.53],
        implementation='Same bounded symbolic grammar and causal online controller; shared non-frozen OOF population and shrunk bursty intercept',
        selection='Chronological structure validation on all-state earlier OOF data. Label-blind date-stratified coefficient-fit sampling. Bursty child intercept from allowed earlier data, in-sample relative to expression fit. Same earlier prefix score/stability objective; later diagnostics excluded.',
        capture_started=False,live_candidate_promoted=False,independent_holdout=False,admission_and_non_bursty_pricing_fixed=True)
    output.mkdir(parents=True);(output/'source').mkdir()
    for n in DEPENDENCIES: shutil.copyfile(Path(__file__).with_name(n),output/'source'/n)
    dump(output/'protocol.json',protocol);started=time.monotonic()
    previous,residual,expanded,ctx,checked,records,residual_dir=load_inputs(previous_dir)
    with gzip.open(output/'symbolic-training.jsonl.gz','wt',compresslevel=5) as stream:
        for row in records: stream.write(json.dumps(row,allow_nan=False)+'\n')
    residual_selection=json.loads((residual_dir/'selection.json').read_text())
    engine_selection=json.loads((ctx['prior_dir']/'selection.json').read_text())
    folds=inputs_for_search(ctx,residual_selection,engine_selection)
    prefixes={}
    for bundle in residual_selection['models']:
        key=str(bundle['training_days']);prefixes[key]=fit(records,bundle['training_periods'],bundle['cutoff'])
        print('pooled symbolic fit prefix '+key,flush=True)
    chosen=select(folds,prefixes,residual_selection,previous,output)
    models={}
    for key,bundle in residual['models'].items():
        models[key]=fit(records,bundle['training_periods'],bundle['cutoff'])
        print('pooled symbolic fit outer '+key,flush=True)
    dump(output/'models.json',models);selected_hash=file_hash(output/'selection.json');models_hash=file_hash(output/'models.json')
    print('pooled symbolic shortlist and models pinned before diagnostics',flush=True)
    diagnostic=diagnostics(ctx,residual,expanded,previous,models,output)
    assert file_hash(output/'selection.json')==selected_hash and file_hash(output/'models.json')==models_hash
    for name,digest in protocol['source_sha256'].items():
        if file_hash(Path(__file__).with_name(name))!=digest: raise ValueError('source changed during experiment')
    result=dict(protocol,selected=chosen['selected'],ranking=chosen['ranking'],models=models,
                selection_sha256=selected_hash,models_sha256=models_hash,training_sha256=file_hash(output/'symbolic-training.jsonl.gz'),
                predictions_sha256=file_hash(output/'predictions.jsonl.gz'),feature_records_verified=checked,
                elapsed_seconds=time.monotonic()-started,**diagnostic)
    dump(output/'research.json',result)
    for name in ('cases','phases','regimes','paired','summary'): write_csv(output/(name+'.csv'),result[name],list(result[name][0]))
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--previous',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();r=run(args.previous,args.output)
    print(json.dumps(dict(selected=r['selected'],ranking=r['ranking'],elapsed_seconds=r['elapsed_seconds']),indent=2))
