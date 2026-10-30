#!/usr/bin/env python3
"""Audit temporal data provenance, pinned replay and delayed-label isolation."""
import argparse
import gzip
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from capture_dataset import file_hash
from fetch_temporal_raw import PLAN
from full_raw_pipeline import fit_bundle
from research_bursty_optimizer import dump
from research_startup_admission import verify_code
from research_temporal_pricing import replay, make_sessions, evaluate_fold
from temporal_oracle_data import load, late_days, parent_context, complete_day
from temporal_pricing import all_predictions, VARIANTS


def normalized(value):return json.loads(json.dumps(value))


def records(path):
    with gzip.open(path,'rt') as stream:
        for line in stream:yield json.loads(line)


def same_predictions(a,b):
    from itertools import zip_longest
    count=0
    for x,y in zip_longest(records(a),records(b)):
        assert x==y;count+=1
    return count


def audit(root):
    result=json.loads((root/'research.json').read_text());verify_code(root,result)
    for name,key in (('selection.json','selection_sha256'),('models.json','models_sha256'),
                     ('later-predictions.jsonl.gz','later_predictions_sha256')):
        assert file_hash(root/name)==result[key]
    for begin,digest in result['selection_prediction_sha256'].items():
        assert file_hash(root/f'selection-predictions-{begin}.jsonl.gz')==digest
    dataset=Path(result['dataset'])
    assert file_hash(dataset/'dataset.json')==result['dataset_sha256']
    normal,raw,metadata=load(dataset);dates=metadata['dates']
    _,ctx,checked=parent_context(Path(metadata['previous']))
    assert normal==[r for r in ctx['original'] if r['period'] in dates]
    expected=dict(ctx['expanded_rawdays'])
    for day,source in (('2026-01-01','raw'),('2026-08-01','raw_control')):
        session=next(s for s in ctx['sessions'] if s['period']==day and s['source']==source and s['mode']=='continuous')
        expected[day]=[p['row'] for p in session['values']]
    assert expected==raw
    for day,rows in raw.items():complete_day(rows,day)
    choice=json.loads((root/'selection.json').read_text());models=json.loads((root/'models.json').read_text())
    folds=[];predictions=0
    with TemporaryDirectory(prefix='fuse-temporal-audit-') as temp:
        temp=Path(temp)
        for fold in PLAN['folds']:
            begin=fold['training_days'];left,right=fold['scoring_indices'];scoring_dates=dates[left:right]
            path=temp/f'fold-{begin}.jsonl.gz'
            fresh=replay(make_sessions(normal,raw,scoring_dates,'selection'),models[str(begin)],path)
            predictions+=same_predictions(root/f'selection-predictions-{begin}.jsonl.gz',path)
            folds.extend(evaluate_fold(fresh,begin,scoring_dates))
        assert folds==choice['folds']
        ranking=[]
        for candidate in VARIANTS:
            part=[r for r in folds if r['candidate']==candidate]
            ranking.append(dict(candidate=candidate,score=sum(r['score'] for r in part)/len(part),
                folds=[r['score'] for r in part],feasible=all(m['constraints']['feasible'] for r in part for m in r['modes'].values())))
        ranking.sort(key=lambda r:(not r['feasible'],r['score'],VARIANTS.index(r['candidate'])))
        for new,old in zip(ranking,choice['ranking']):
            assert new['candidate']==old['candidate'] and abs(new['score']-old['score'])<1e-10
            assert new['folds']==old['folds'] and new['feasible']==old['feasible']
        late,binding=late_days(Path(result['raw']))
        assert binding==result['later_raw_binding']
        scoring=make_sessions(normal,late,dates[22:24],'later_raw')+make_sessions(normal,{},dates[22:24],'later_normalized')
        fresh=replay(scoring,models['22'],temp/'late.jsonl.gz')
        predictions+=same_predictions(root/'later-predictions.jsonl.gz',temp/'late.jsonl.gz')
        for name in ('cases','phases','regimes','floor_bounds'):
            assert fresh[name]==[r for r in result[name] if r['split'] in ('later_raw','later_normalized')]
    counterfactuals=[]
    for begin in (17,22):
        cutoff=dates[begin]
        modified_normal=[dict(r,move=999999999,valid=False) if r['period']>=cutoff else r for r in normal]
        modified_raw={day:[dict(r,move=999999999,valid=False) if day>=cutoff else r for r in rows] for day,rows in {**raw,**late}.items()}
        actual=fit_bundle(modified_normal,modified_raw,dates[:begin],cutoff,models[str(begin)]['fixed_retained'],'raw_core')
        assert normalized(actual)==models[str(begin)]['expanding_raw_core']
        counterfactuals.append(dict(training_days=begin,own_and_future_dates_excluded=True,model_refit_unchanged=True))
    day='2026-08-01';rows=raw[day][:960];boundary=rows[len(rows)//2]['start']
    changed=[dict(r,move=999999999,valid=False) if r['start']>=boundary else r for r in rows]
    first=all_predictions(rows,models['20']);other=all_predictions(changed,models['20'])
    for candidate in VARIANTS:
        prefix=lambda part:[(p['width_ppm'],p['paused']) for p in part if p['row']['start']<boundary+60000]
        assert prefix(first[candidate])==prefix(other[candidate])
    report=dict(completed=True,temporal_dataset_rebound_to_verified_parents=True,complete_raw_dates_verified=len(raw),
        feature_records_verified=checked,selection_replayed_from_pinned_models=True,prediction_rows_recomputed=predictions,
        later_raw_reparsed_and_replayed=True,counterfactual_model_refits=counterfactuals,
        all_candidate_maturity_boundaries_verified=True,
        audit_source_sha256=file_hash(Path(__file__)),capture_started=False,live_candidate_promoted=False,independent_holdout=False)
    dump(root/'audit.json',report);print(json.dumps(report,indent=2))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True)
    audit(p.parse_args().output)
