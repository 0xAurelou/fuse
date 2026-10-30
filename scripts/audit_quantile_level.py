#!/usr/bin/env python3
"""Recompute selection and test actual-data isolation for residual CDF control."""
import argparse
import gzip
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from bursty_optimizer import cache_forecasts
from capture_dataset import file_hash
from chronological_raw_priors import floor_values, replay
from quantile_level_control import all_series, VARIANTS
from research_bursty_optimizer import dump, inputs_for_search
from research_expanded_bursty import context
from research_pooled_symbolic import load_inputs
from research_quantile_level import select
from research_startup_admission import verify_code


def audit(root):
    result=json.loads((root/'research.json').read_text());verify_code(root,result)
    for filename,key in (('selection.json','selection_sha256'),('predictions.jsonl.gz','predictions_sha256')):
        assert file_hash(root/filename)==result[key]
    previous_dir=Path(result['previous'])
    assert file_hash(previous_dir/'research.json')==result['previous_sha256']
    previous,residual,expanded,ctx,checked,_,residual_dir=load_inputs(previous_dir)
    params=result['params'];assert params==previous['best_trial']['params']
    selection=json.loads((residual_dir/'selection.json').read_text())
    folds=inputs_for_search(ctx,selection,json.loads((ctx['prior_dir']/'selection.json').read_text()))
    with TemporaryDirectory(prefix='fuse-cdf-audit-') as temp:
        recomputed=select(folds,params,selection,previous,Path(temp))
        assert recomputed==json.loads((root/'selection.json').read_text())
    counterfactuals=[]
    for day in ('2025-01-01','2025-06-01'):
        s=next(s for s in ctx['sessions'] if s['source']=='raw_matched' and s['period']==day and s['mode']=='restart')
        key,engine,_=context(ctx,s)
        ref=replay(floor_values(s['values'],engine),expanded['models'][key]['existing']['prior']['model'],'floor10_burst_pool120')
        model={params['source']:residual['models'][key]['models'][params['source']]}
        prior=residual['residual_priors'][key][params['source']]
        run=lambda values:all_series(values,cache_forecasts(values,model)[params['source']],prior,params)
        actual=run(ref)
        changed=[dict(p,row=dict(p['row'],move=0)) if p['row']['activity_state'] in ('active','sparse') else p for p in ref]
        altered=run(changed)
        refused=run([dict(p,paused=True,survived=None) for p in ref])
        boundary=ref[len(ref)//2]['row']['start']
        future=run([dict(p,row=dict(p['row'],move=999999999,valid=False)) if p['row']['start']>=boundary else p for p in ref])
        for candidate in VARIANTS[1:]:
            keyvals=lambda part:[(p['width_ppm'],p.get('cdf_level'),p.get('cdf_correction')) for p in part]
            assert keyvals(actual[candidate])==keyvals(altered[candidate])
            assert keyvals(actual[candidate])==keyvals(refused[candidate])
            assert keyvals([p for p in actual[candidate] if p['row']['start']<boundary+60000])==keyvals([
                p for p in future[candidate] if p['row']['start']<boundary+60000])
        counterfactuals.append(dict(day=day,candidates_verified=len(VARIANTS)-1,
            matured_labels_only=True,other_state_labels_isolated_given_fixed_references=True,
            admission_does_not_select_learning=True))
    cells={(r['candidate'],r['policy'],r['case_id'],r['activity']):r for r in result['cases']}
    for r in result['cases']:
        base=cells[('retained_pool',r['policy'],r['case_id'],r['activity'])]
        for f in ('windows','eligible_outcomes','pre_entry_predictions','grid_windows','offered_pre_entry_decisions'):
            assert r[f]==base[f]
        if r['activity'] in ('active','sparse','frozen'):
            for f in ('survived','mean_width_ppm','full_window_pinball_ppm'):assert r[f]==base[f]
    optimizer_dir=Path(json.loads((previous_dir/'research.json').read_text())['previous'])
    controls={}
    with gzip.open(optimizer_dir/'predictions.jsonl.gz','rt') as stream:
        for line in stream:
            p=json.loads(line)
            if p['candidate'] in ('retained_pool','optimized'):
                controls[tuple(p[k] for k in ('candidate','policy','session','start'))]=p
    predictions=0;verified=0
    with gzip.open(root/'predictions.jsonl.gz','rt') as stream:
        for line in stream:
            p=json.loads(line);predictions+=1
            if p['candidate'] in ('retained_pool','optimized'):
                old=controls.pop(tuple(p[k] for k in ('candidate','policy','session','start')))
                assert all(p[k]==old[k] for k in ('width','shadow','paused'));verified+=1
            if p['width'] is not None:assert 1<=p['width']<=50000
            if p['level'] is not None:assert .02<=p['level']<=.98
    assert not controls
    report=dict(completed=True,selection_recomputed_exactly=True,feature_records_verified=checked,
        prediction_rows_checked=predictions,previous_control_predictions_verified=verified,
        counterfactuals=counterfactuals,admission_and_non_bursty_prices_fixed=True,
        audit_source_sha256=file_hash(Path(__file__)),capture_started=False,live_candidate_promoted=False,
        independent_holdout=False)
    dump(root/'audit.json',report);print(json.dumps(report,indent=2))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True)
    audit(p.parse_args().output)
