#!/usr/bin/env python3
"""Recompute raw-stack selection, prior populations and actual-data causality."""
import argparse
import gzip
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from capture_dataset import file_hash
from full_raw_pipeline import STAGES, POLICIES, fit_bundle, price, mask, floor_bound
from research_bursty_optimizer import dump
from research_expanded_bursty import context
from research_full_raw_pipeline import select
from research_pooled_symbolic import load_inputs
from research_startup_admission import verify_code


def normalized(value):return json.loads(json.dumps(value))


def audit(root):
    result=json.loads((root/'research.json').read_text());verify_code(root,result)
    for name,key in (('selection.json','selection_sha256'),('models.json','models_sha256'),
                     ('inner-models.json','inner_models_sha256'),('predictions.jsonl.gz','predictions_sha256')):
        assert file_hash(root/name)==result[key]
    previous_dir=Path(result['previous'])
    assert file_hash(previous_dir/'research.json')==result['previous_sha256']
    previous=json.loads((previous_dir/'research.json').read_text())
    parent=Path(previous['previous'])
    _,residual,expanded,ctx,checked,_,residual_dir=load_inputs(parent)
    selection=json.loads((root/'selection.json').read_text())
    with TemporaryDirectory(prefix='fuse-full-raw-audit-') as temp:
        chosen,inner=select(ctx,expanded,json.loads((ctx['prior_dir']/'selection.json').read_text()),
                            json.loads((residual_dir/'selection.json').read_text()),Path(temp))
        assert normalized(chosen)==selection
        assert normalized(inner)==json.loads((root/'inner-models.json').read_text())
    models=json.loads((root/'models.json').read_text())
    counts=[]
    for stage_models in list(models.values())+list(inner.values()):
        for stage in ('raw_overlay','raw_core'):
            b=stage_models[stage]
            assert b['overlay']['training_windows']==b['training_frozen']
            assert len({p['period'] for p in b['provenance']})==len(b['training_periods'])
            counts.append(b['training_frozen'])
    counterfactuals=[]
    for day in ('2025-01-01','2025-06-01'):
        s=next(s for s in ctx['sessions'] if s['source']=='raw_matched' and s['period']==day and s['mode']=='restart')
        key,_,_=context(ctx,s);bundle=residual['models'][key]
        changed_original=[dict(r,move=999999999,valid=False) if r['period']>=day else r for r in ctx['original']]
        changed_raw={date:[dict(r,move=999999999,valid=False) if date>=day else r for r in rows]
                     for date,rows in ctx['expanded_rawdays'].items()}
        rows=[p['row'] for p in s['values']];boundary=rows[len(rows)//2]['start']
        changed_rows=[dict(r,move=999999999,valid=False) if r['start']>=boundary else r for r in rows]
        for stage in ('raw_overlay','raw_core'):
            actual=fit_bundle(changed_original,changed_raw,bundle['training_periods'],bundle['cutoff'],models[key]['retained'],stage)
            assert normalized(actual)==models[key][stage]
            base,prices=price(rows,models[key][stage]);altered_base,altered_prices=price(changed_rows,models[key][stage])
            for policy in POLICIES:
                out=mask(prices,base,policy);altered=mask(altered_prices,altered_base,policy)
                values=lambda predictions:[(p['row']['start'],p['width_ppm'],p['paused']) for p in predictions
                                           if p['row']['start']<boundary+60000]
                assert values(out)==values(altered)
        counterfactuals.append(dict(day=day,own_and_future_training_excluded=True,matured_labels_only=True,
                                    all_stages_and_policies_verified=True))
    cells={(r['candidate'],r['case_id'],r['activity']):r for r in result['cases']}
    for r in result['cases']:
        b=cells[('retained:'+r['policy'],r['case_id'],r['activity'])]
        for f in ('eligible_outcomes','pre_entry_predictions','grid_windows'):assert r[f]==b[f]
    checked_bounds=0
    for b in result['floor_bounds']:
        for which,count in (('eligible',b['eligible_outcomes']),('offered',b['windows'])):
            expected=floor_bound(count,b[which+'_floor_survivors'])
            assert all(b[which+'_'+key]==value for key,value in expected.items())
            checked_bounds+=1
    # Every stage's price is computed before its policy-specific mask. Rebind
    # every saved width across policies to catch accidental admission learning.
    prediction_count=0;bindings={}
    with gzip.open(root/'predictions.jsonl.gz','rt') as stream:
        for line in stream:
            p=json.loads(line);prediction_count+=1
            stage,_=p['candidate'].split(':');key=(stage,p['session'],p['start'])
            if key in bindings:assert bindings[key]==p['width']
            else:bindings[key]=p['width']
    report=dict(completed=True,selection_and_inner_models_recomputed_exactly=True,
        new_model_prior_populations_verified=len(counts),frozen_priors_include_all_clean_references=True,
        feature_records_verified=checked,counterfactuals=counterfactuals,
        eligibility_denominators_fixed=True,width_independent_of_admission=True,
        prediction_rows_verified=prediction_count,floor_bounds_recomputed=checked_bounds,
        audit_source_sha256=file_hash(Path(__file__)),capture_started=False,live_candidate_promoted=False,
        independent_holdout=False)
    dump(root/'audit.json',report);print(json.dumps(report,indent=2))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True)
    audit(p.parse_args().output)
