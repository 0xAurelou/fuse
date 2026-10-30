#!/usr/bin/env python3
"""Verify symbolic training boundaries, reproducible formulas, and saved controls."""
import argparse
import gzip
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from bursty_optimizer import cache_forecasts
from capture_dataset import file_hash
from chronological_raw_priors import floor_values, replay
from research_bursty_optimizer import inputs_for_search, dump
from research_expanded_bursty import context
from research_startup_admission import verify_code
from research_symbolic_corridor import load_inputs, select, VARIANTS
from symbolic_corridor import fit, series


def normalized(value): return json.loads(json.dumps(value))


def audit(root):
    r=json.loads((root/'research.json').read_text()); verify_code(root,r)
    for name,key in (('selection.json','selection_sha256'),('models.json','models_sha256'),
                     ('symbolic-training.jsonl.gz','training_sha256'),('predictions.jsonl.gz','predictions_sha256')):
        if file_hash(root/name)!=r[key]: raise ValueError('artifact differs: '+name)
    previous_dir=Path(r['previous'])
    assert file_hash(previous_dir/'research.json')==r['previous_sha256']
    previous,residual,expanded,ctx,checked,records,residual_dir=load_inputs(previous_dir)
    with gzip.open(root/'symbolic-training.jsonl.gz','rt') as stream:
        assert records==[json.loads(line) for line in stream]
    residual_selection=json.loads((residual_dir/'selection.json').read_text())
    selected=json.loads((root/'selection.json').read_text())
    prefixes={}
    for bundle in residual_selection['models']:
        key=str(bundle['training_days']); prefixes[key]=fit(records,bundle['training_periods'],bundle['cutoff'])
        assert normalized(prefixes[key])==selected['prefix_models'][key]
    for key,bundle in residual['models'].items():
        assert normalized(fit(records,bundle['training_periods'],bundle['cutoff']))==r['models'][key]
    folds=inputs_for_search(ctx,residual_selection,json.loads((ctx['prior_dir']/'selection.json').read_text()))
    with TemporaryDirectory(prefix='fuse-symbolic-audit-') as temp:
        fresh=select(folds,prefixes,residual_selection,previous,Path(temp))
        assert normalized(fresh)==selected
    counterfactuals=[]
    for day in ('2025-01-01','2025-06-01'):
        changed=[dict(p,ratio=999999.,features=[99.]*7) if p['row']['period']>=day else p for p in records]
        bundle=residual['models'][day]
        assert normalized(fit(changed,bundle['training_periods'],bundle['cutoff']))==r['models'][day]
        s=next(s for s in ctx['sessions'] if s['source']=='raw_matched' and s['period']==day and s['mode']=='restart')
        key,engine,_=context(ctx,s)
        ref=replay(floor_values(s['values'],engine),expanded['models'][key]['existing']['prior']['model'],'floor10_burst_pool120')
        gap_model={'gap':residual['models'][key]['models']['gap']}
        model=r['models'][key]
        for constant in (False,True):
            run=lambda values: series(values,cache_forecasts(values,gap_model)['gap'],model,True,constant)
            actual=run(ref)
            changed=[dict(p,row=dict(p['row'],move=0)) if p['row']['activity_state'] in ('active','sparse') else p for p in ref]
            altered=run(changed)
            assert [(p['width_ppm'],p.get('symbolic_total')) for p in actual]==[(p['width_ppm'],p.get('symbolic_total')) for p in altered]
            boundary=ref[len(ref)//2]['row']['start']
            changed=[dict(p,row=dict(p['row'],move=999999999,valid=False)) if p['row']['start']>=boundary else p for p in ref]
            altered=run(changed)
            assert [(p['width_ppm'],p.get('symbolic_total')) for p in actual if p['row']['start']<boundary+60000]==[
                (p['width_ppm'],p.get('symbolic_total')) for p in altered if p['row']['start']<boundary+60000]
        counterfactuals.append(dict(day=day,own_and_future_training_excluded=True,matured_labels_only=True,
                                    other_state_corrections_isolated_given_fixed_references=True))
    controls={}
    with gzip.open(previous_dir/'predictions.jsonl.gz','rt') as stream:
        for line in stream:
            p=json.loads(line); controls[tuple(p[k] for k in ('candidate','policy','session','start'))]=p
    verified=0
    with gzip.open(root/'predictions.jsonl.gz','rt') as stream:
        for line in stream:
            p=json.loads(line)
            if p['candidate'] in VARIANTS[:3]:
                old=controls.pop(tuple(p[k] for k in ('candidate','policy','session','start')))
                assert all(p[k]==old[k] for k in ('width','shadow','paused')); verified+=1
    assert not controls
    cells={(p['candidate'],p['policy'],p['case_id'],p['activity']):p for p in r['cases']}
    for p in r['cases']:
        b=cells[('retained_pool',p['policy'],p['case_id'],p['activity'])]
        for f in ('windows','eligible_outcomes','pre_entry_predictions','grid_windows','offered_pre_entry_decisions'): assert p[f]==b[f]
        if p['activity'] in ('active','sparse','frozen'):
            for f in ('survived','mean_width_ppm','full_window_pinball_ppm'): assert p[f]==b[f]
    report=dict(completed=True,training_records_rebound=len(records),feature_records_verified=checked,
                formula_models_recomputed=len(prefixes)+len(r['models']),selection_recomputed_exactly=True,
                previous_prediction_rows_verified=verified,counterfactuals=counterfactuals,
                admission_and_other_prices_fixed=True,capture_started=False,live_candidate_promoted=False,independent_holdout=False)
    dump(root/'audit.json',report); print(json.dumps(report,indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__); parser.add_argument('--output',type=Path,required=True)
    audit(parser.parse_args().output)
