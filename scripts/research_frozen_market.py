#!/usr/bin/env python3
"""Matched-support frozen timing versus fresh market/oracle context."""
import argparse
import gzip
import json
import math
from pathlib import Path
import shutil
from statistics import mean
import time

from adaptive_corridor import required_width
from capture_dataset import file_hash
from fetch_temporal_raw import PLAN
from frozen_context_cdf import SPEC, VARIANTS, FAMILIES, fit_prefix, all_series, supported as context_supported
from frozen_market_data import attach_late
from full_raw_pipeline import price, bounds
from investigate_capture import write_csv
from research_bursty_optimizer import dump
from research_bursty_startup_raw import paired
from research_full_raw_pipeline import score, losses
from research_nonfrozen_pricing import group, measures, summarize
from research_raw_flat_panels import cell
from research_startup_admission import verify_code
from research_temporal_pricing import make_sessions, normalized_manifest
from research_frozen_cdf import DEPENDENCIES as PARENT_DEPENDENCIES
from temporal_oracle_data import load, late_days

DEPENDENCIES=tuple(dict.fromkeys(('frozen_context_cdf.py','frozen_market_data.py','research_frozen_market.py',
                                 'test_frozen_context_cdf.py')+PARENT_DEPENDENCIES))


def frozen_phases(s,values,candidate):
    result=[]
    for interval in s['intervals']:
        part=[p for p in values if interval['start']<=p['row']['start']<interval['end']
              and p['width_ppm'] is not None and p['row']['activity_state']=='frozen']
        for phase,rows in (('first12',part[:12]),('later',part[12:])):
            result.append(dict(candidate=candidate,policy=candidate,case_id=f'{s["id"]}:{interval["hour"]:02}',
                source=s['source'],period=s['period'],split=s['split'],mode=s['mode'],axis='frozen',
                hour=interval['hour'],phase=phase,**cell(rows)))
    return result


def frozen_regimes(s,values,candidate):
    result=[]
    for interval in s['intervals']:
        for regime in ('range','mixed','pump','dump'):
            part=[p for p in values if interval['start']<=p['row']['start']<interval['end'] and p['row']['market_regime']==regime]
            for activity in ('all','frozen'):
                rows=part if activity=='all' else [p for p in part if p['row']['activity_state']=='frozen']
                result.append(dict(candidate=candidate,policy=candidate,case_id=f'{s["id"]}:{interval["hour"]:02}',
                    source=s['source'],period=s['period'],split=s['split'],mode=s['mode'],regime=regime,activity=activity,
                    **interval,**cell(rows)))
    return result


def replay(sessions,models,fixed,path):
    cases=[];phases=[];regimes=[];floor_rows=[];risk=[];full={c:[] for c in VARIANTS};saved={c:{} for c in VARIANTS}
    with gzip.open(path,'wt',compresslevel=5) as stream:
        for s in sessions:
            _,reference=price(s['rows'],fixed)
            alternatives=all_series(reference,models)
            for candidate,values in alternatives.items():
                for p,b in zip(values,reference):
                    if (p['width_ppm'] is None,p['shadow_survived'] is None)!=(b['width_ppm'] is None,b['shadow_survived'] is None):
                        raise ValueError('eligibility differs')
                    if b['row']['activity_state']!='frozen' and p['width_ppm']!=b['width_ppm']:
                        raise ValueError('non-frozen pricing differs')
                cases.extend(measures(s,values,candidate,candidate));phases.extend(frozen_phases(s,values,candidate))
                regimes.extend(frozen_regimes(s,values,candidate));full[candidate].extend(values);saved[candidate][s['id']]=values
                for interval in s['intervals']:
                    part=[p for p in values if interval['start']<=p['row']['start']<interval['end'] and p['row']['activity_state']=='frozen']
                    floor_rows.append(dict(candidate=candidate,case_id=f'{s["id"]}:{interval["hour"]:02}',source=s['source'],
                        period=s['period'],split=s['split'],mode=s['mode'],**interval,**bounds(part)))
                    supported=[p for p in part if p['shadow_survived'] is not None and p.get('frozen_floor') is not None]
                    n=len(supported)
                    risk.append(dict(candidate=candidate,period=s['period'],source=s['source'],split=s['split'],mode=s['mode'],
                        hour=interval['hour'],windows=n,predicted=sum(p['frozen_floor'] for p in supported)/n if n else None,
                        observed=sum(required_width(p['row'])<=1 for p in supported)/n if n else None,
                        brier=sum((p['frozen_floor']-(required_width(p['row'])<=1))**2 for p in supported)/n if n else None,
                        log_loss=sum(-math.log(max(1e-9,p['frozen_floor'] if required_width(p['row'])<=1 else 1-p['frozen_floor'])) for p in supported)/n if n else None))
                for p in values:
                    stream.write(json.dumps(dict(candidate=candidate,session=s['id'],start=p['row']['start'],
                        activity=p['row']['activity_state'],width=p['width_ppm'],shadow=p['shadow_survived'],paused=p['paused'],
                        floor=p.get('frozen_floor'),level=p.get('frozen_level'),logit_delta=p.get('frozen_logit_delta'),
                        positive_level=p.get('positive_level'),market_supported=context_supported(p['row']) if p['row']['activity_state']=='frozen' and p['width_ppm'] is not None else None),allow_nan=False)+'\n')
    pairs=[r for c,values in saved.items() for r in paired(sessions,values,c,c)]
    return dict(cases=cases,phases=phases,regimes=regimes,floor_bounds=floor_rows,risk=risk,paired=pairs,
                full_losses={c:losses(values) for c,values in full.items()})


def fold_scores(result,begin,dates):
    out=[];ref=result['full_losses']['retained_open']
    for candidate in VARIANTS:
        loss=result['full_losses'][candidate]
        guard=sum(100*max(0,loss[g]['pinball_ppm']/b['pinball_ppm']-1.1) for g,b in ref.items()
                  if b['windows']>=20 and b['pinball_ppm'])
        modes={}
        for mode in ('restart','continuous'):
            modes[mode]=score([r for r in result['cases'] if r['candidate']==candidate and r['mode']==mode],
                             [r for r in result['phases'] if r['candidate']==candidate and r['mode']==mode])
        value=mean(r['score'] for r in modes.values())+.25*abs(modes['restart']['score']-modes['continuous']['score'])+guard
        out.append(dict(candidate=candidate,training_days=begin,scoring_days=dates,score=value,modes=modes,
                        loss_guard=guard,full_reference_losses=loss))
    return out


def run(previous_dir,output):
    if output.exists():raise ValueError('preserve old experiments; choose a new output')
    started=time.monotonic();previous=json.loads((previous_dir/'research.json').read_text());verify_code(previous_dir,previous)
    for name,key in (('selection.json','selection_sha256'),('models.json','models_sha256'),
                     ('later-predictions.jsonl.gz','later_predictions_sha256')):
        if file_hash(previous_dir/name)!=previous[key]:raise ValueError('parent artifact differs')
    protocol=dict(previous=str(previous_dir.resolve()),previous_sha256=file_hash(previous_dir/'research.json'),
        dataset=previous['dataset'],dataset_sha256=previous['dataset_sha256'],raw=previous['raw'],
        raw_manifest_sha256=previous['raw_manifest_sha256'],spec=SPEC,variants=VARIANTS,plan=PLAN,
        source_sha256={n:file_hash(Path(__file__).with_name(n)) for n in DEPENDENCIES},
        target_survival=.48,band=[.43,.53],capture_started=False,live_candidate_promoted=False,independent_holdout=False,
        selection='Same later 14/17/20-date folds, frozen-phase charge, availability screens and full-loss guards. Both feature families use identical fresh market support and path weighting. Reference coverage updates control for the new quote-time priceability restriction. Later dates excluded.',
        no_nonfrozen_pricing_change=True,training='Matched frozen clean earlier references only; no admission filtering. No outcome, validity or date predictors. Later raw dates are already inspected development data.')
    output.mkdir(parents=True);(output/'source').mkdir()
    for n in DEPENDENCIES:shutil.copyfile(Path(__file__).with_name(n),output/'source'/n)
    dump(output/'protocol.json',protocol)
    dataset=Path(previous['dataset'])
    if file_hash(dataset/'dataset.json')!=previous['dataset_sha256']:raise ValueError('dataset binding differs')
    normalized,raw,metadata=load(dataset);dates=metadata['dates']
    temporal_dir=Path(previous['previous'])
    temporal=json.loads((temporal_dir/'research.json').read_text())
    if file_hash(temporal_dir/'research.json')!=previous['previous_sha256'] or file_hash(temporal_dir/'models.json')!=temporal['models_sha256']:
        raise ValueError('fixed temporal benchmark differs')
    fixed=json.loads((temporal_dir/'models.json').read_text())['14']['fixed_retained']
    models={};results=[];folds=[]
    for fold in PLAN['folds']:
        begin=fold['training_days'];left,right=fold['scoring_indices'];scoring_dates=dates[left:right]
        models[str(begin)]={f:fit_prefix(normalized,raw,dates[:begin],scoring_dates[0],f) for f in FAMILIES}
        if models[str(begin)]['timing']['model']['windows']!=models[str(begin)]['market']['model']['windows']:
            raise ValueError('training support differs')
        dump(output/f'models-{begin}.json',models[str(begin)])
        result=replay(make_sessions(normalized,raw,scoring_dates,'selection'),models[str(begin)],fixed,output/f'selection-predictions-{begin}.jsonl.gz')
        folds.extend(fold_scores(result,begin,scoring_dates));results.append(result)
        print('Frozen market CDF selection '+str(begin),flush=True)
    ranking=[]
    for candidate in VARIANTS:
        rows=[r for r in folds if r['candidate']==candidate]
        ranking.append(dict(candidate=candidate,score=mean(r['score'] for r in rows),folds=[r['score'] for r in rows],
            feasible=all(m['constraints']['feasible'] for r in rows for m in r['modes'].values())))
    ranking.sort(key=lambda r:(not r['feasible'],r['score'],VARIANTS.index(r['candidate'])))
    selection=dict(selected=ranking[0]['candidate'],ranking=ranking,folds=folds,later_diagnostics_excluded=True)
    dump(output/'selection.json',selection)
    models['22']={f:fit_prefix(normalized,raw,dates[:22],dates[22],f) for f in FAMILIES}
    dump(output/'models.json',models)
    pinned={n:file_hash(output/n) for n in ('selection.json','models.json')}
    print('Frozen market CDF choice and models pinned before later replay',flush=True)
    rawdir=Path(previous['raw'])
    if file_hash(rawdir/'download-manifest.json')!=previous['raw_manifest_sha256']:raise ValueError('later raw binding differs')
    later,_=late_days(rawdir)
    later,context_binding=attach_late(rawdir,later,normalized_manifest(metadata))
    with gzip.open(output/'later-market-features.jsonl.gz','wt',compresslevel=5) as stream:
        for day,rows in later.items():
            for r in rows:stream.write(json.dumps(dict(period=day,start=r['start'],oracle_gap=r['oracle_gap']),allow_nan=False)+'\n')
    scoring=make_sessions(normalized,later,dates[22:24],'later_raw')+make_sessions(normalized,{},dates[22:24],'later_normalized')
    result=replay(scoring,models['22'],fixed,output/'later-predictions.jsonl.gz');results.append(result)
    for name,digest in pinned.items():
        if file_hash(output/name)!=digest:raise ValueError('pinned choice/model changed')
    for name,digest in protocol['source_sha256'].items():
        if file_hash(Path(__file__).with_name(name))!=digest:raise ValueError('source changed during experiment')
    report=dict(protocol,selected=selection['selected'],ranking=ranking,
        selection_sha256=pinned['selection.json'],models_sha256=pinned['models.json'],
        later_predictions_sha256=file_hash(output/'later-predictions.jsonl.gz'),
        later_market_features_sha256=file_hash(output/'later-market-features.jsonl.gz'),context_binding=context_binding,
        selection_prediction_sha256={str(f['training_days']):file_hash(output/f'selection-predictions-{f["training_days"]}.jsonl.gz') for f in PLAN['folds']},
        elapsed_seconds=time.monotonic()-started,
        **{name:[r for part in results for r in part[name]] for name in ('cases','phases','regimes','floor_bounds','risk','paired')})
    report['summary']=summarize(report['cases']);dump(output/'research.json',report)
    for name in ('cases','phases','regimes','floor_bounds','risk','paired','summary'):
        write_csv(output/(name+'.csv'),report[name],list(report[name][0]))
    return report


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--previous',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    args=p.parse_args();r=run(args.previous,args.output)
    print(json.dumps(dict(selected=r['selected'],ranking=r['ranking'],elapsed_seconds=r['elapsed_seconds']),indent=2))
