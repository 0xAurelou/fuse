#!/usr/bin/env python3
"""Recompute matched timing/market selection and verify prospective causality."""
import argparse
import gzip
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from capture_dataset import file_hash
from fetch_temporal_raw import PLAN
from frozen_context_cdf import FAMILIES, VARIANTS, fit_prefix, series, supported
from frozen_conditional_cdf import fit_prefix as timing_control_fit
from frozen_market_data import attach_late
from full_raw_pipeline import price
from research_bursty_optimizer import dump
from research_frozen_market import replay, fold_scores
from research_startup_admission import verify_code
from research_temporal_pricing import make_sessions, normalized_manifest
from temporal_oracle_data import load, late_days


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
                     ('later-predictions.jsonl.gz','later_predictions_sha256'),
                     ('later-market-features.jsonl.gz','later_market_features_sha256')):
        assert file_hash(root/name)==result[key]
    for begin,digest in result['selection_prediction_sha256'].items():
        assert file_hash(root/f'selection-predictions-{begin}.jsonl.gz')==digest
    previous_dir=Path(result['previous'])
    assert file_hash(previous_dir/'research.json')==result['previous_sha256']
    previous=json.loads((previous_dir/'research.json').read_text());verify_code(previous_dir,previous)
    assert file_hash(previous_dir/'models.json')==previous['models_sha256']
    temporal_dir=Path(previous['previous'])
    assert file_hash(temporal_dir/'research.json')==previous['previous_sha256']
    temporal=json.loads((temporal_dir/'research.json').read_text())
    assert file_hash(temporal_dir/'models.json')==temporal['models_sha256']
    fixed=json.loads((temporal_dir/'models.json').read_text())['14']['fixed_retained']
    normal,raw,metadata=load(Path(result['dataset']));dates=metadata['dates']
    models=json.loads((root/'models.json').read_text());choice=json.loads((root/'selection.json').read_text())
    fits=0
    for begin in (14,17,20,22):
        for family in FAMILIES:
            assert normalized(fit_prefix(normal,raw,dates[:begin],dates[begin],family))==models[str(begin)][family]
            fits+=1
        assert models[str(begin)]['timing']['model']['windows']==models[str(begin)]['market']['model']['windows']
        # Common support is complete on this archive: isolate the market columns
        # from changes to timing training or weighting.
        control=timing_control_fit(normal,raw,dates[:begin],dates[begin],'path')['model']
        for field in ('windows','center','sd','floor_coefficients','positive_coefficients'):
            assert control[field]==models[str(begin)]['timing']['model'][field]
    folds=[];predictions=0
    with TemporaryDirectory(prefix='fuse-frozen-market-audit-') as temp:
        temp=Path(temp)
        for f in PLAN['folds']:
            begin=f['training_days'];left,right=f['scoring_indices'];days=dates[left:right]
            fresh=replay(make_sessions(normal,raw,days,'selection'),models[str(begin)],fixed,temp/f'{begin}.jsonl.gz')
            predictions+=same_predictions(root/f'selection-predictions-{begin}.jsonl.gz',temp/f'{begin}.jsonl.gz')
            folds.extend(fold_scores(fresh,begin,days))
        assert folds==choice['folds']
        ranking=[]
        for candidate in VARIANTS:
            rows=[r for r in folds if r['candidate']==candidate]
            ranking.append(dict(candidate=candidate,score=sum(r['score'] for r in rows)/len(rows),
                folds=[r['score'] for r in rows],feasible=all(m['constraints']['feasible'] for r in rows for m in r['modes'].values())))
        ranking.sort(key=lambda r:(not r['feasible'],r['score'],VARIANTS.index(r['candidate'])))
        assert all(a['candidate']==b['candidate'] and abs(a['score']-b['score'])<1e-10 for a,b in zip(ranking,choice['ranking']))
        later,_=late_days(Path(result['raw']))
        later,binding=attach_late(Path(result['raw']),later,normalized_manifest(metadata))
        assert binding==result['context_binding']
        expected=[dict(period=day,start=r['start'],oracle_gap=r['oracle_gap']) for day,rows in later.items() for r in rows]
        assert expected==list(records(root/'later-market-features.jsonl.gz'))
        sessions=make_sessions(normal,later,dates[22:24],'later_raw')+make_sessions(normal,{},dates[22:24],'later_normalized')
        fresh=replay(sessions,models['22'],fixed,temp/'later.jsonl.gz')
        predictions+=same_predictions(root/'later-predictions.jsonl.gz',temp/'later.jsonl.gz')
    counterfactuals=[]
    for begin in (17,22):
        cutoff=dates[begin]
        changed_normal=[dict(r,move=999999999,valid=False) if r['period']>=cutoff else r for r in normal]
        changed_raw={day:[dict(r,move=999999999,valid=False) if day>=cutoff else r for r in rows] for day,rows in {**raw,**later}.items()}
        for w in FAMILIES:
            assert normalized(fit_prefix(changed_normal,changed_raw,dates[:begin],cutoff,w))==models[str(begin)][w]
        rows=raw['2026-08-01'][:960] if begin==17 else later['2026-09-01'][:960]
        _,reference=price(rows,fixed);boundary=rows[len(rows)//2]['start']
        changed=[dict(p,row=dict(p['row'],move=999999999,valid=False)) if p['row']['start']>=boundary else p for p in reference]
        for w in FAMILIES:
            model=models[str(begin)][w]['model']
            for mode in ('static','reference','priceable'):
                open_=series(reference,model,mode,None);gated=series(reference,model,mode,.53);future=series(changed,model,mode,.53)
                fields=lambda part:[(p['width_ppm'],p.get('frozen_floor'),p.get('frozen_level')) for p in part]
                assert fields(open_)==fields(gated)
                assert [(p['width_ppm'],p['paused']) for p in gated if p['row']['start']<boundary+60000]==[
                    (p['width_ppm'],p['paused']) for p in future if p['row']['start']<boundary+60000]
        counterfactuals.append(dict(training_days=begin,own_and_future_training_excluded=True,matured_labels_only=True,
                                    refused_references_learn=True))
    controls={}
    for begin in (14,17,20):
        for p in records(previous_dir/f'selection-predictions-{begin}.jsonl.gz'):
            if p['candidate']=='retained_open':controls[(p['session'],p['start'])]=p
    for p in records(previous_dir/'later-predictions.jsonl.gz'):
        if p['candidate']=='retained_open':controls[(p['session'],p['start'])]=p
    controls_verified=0
    for path in [root/f'selection-predictions-{n}.jsonl.gz' for n in (14,17,20)]+[root/'later-predictions.jsonl.gz']:
        for p in records(path):
            base=controls[p['session'],p['start']]
            if p['candidate']=='retained_open' or p['activity']!='frozen' or p['market_supported'] is False:
                assert all(p[a]==base[b] for a,b in (('width','width'),('shadow','shadow'),('paused','paused')))
                controls_verified+=1
    report=dict(completed=True,research_sha256=file_hash(root/'research.json'),
        all_models_refitted_exactly=fits,selection_recomputed=True,
        prediction_rows_recomputed=predictions,baseline_and_nonfrozen_records_verified=controls_verified,
        counterfactuals=counterfactuals,matched_training_support=True,timing_fit_matches_parent=True,
        later_features_rebuilt=True,raw_normalized_oracle_and_mark_crosschecks=binding['checks'],
        audit_source_sha256=file_hash(Path(__file__)),
        capture_started=False,live_candidate_promoted=False,independent_holdout=False)
    dump(root/'audit.json',report);print(json.dumps(report,indent=2))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True)
    audit(p.parse_args().output)
