#!/usr/bin/env python3
"""Refit raw-oracle engine/overlays with explicit frozen-state availability."""
import argparse
from collections import defaultdict
from datetime import datetime, timezone
import gzip
import json
from pathlib import Path
import shutil
from statistics import mean
import time

from capture_dataset import file_hash
from full_raw_pipeline import STAGES, POLICIES, VARIANTS, SPEC, AVAILABILITY, fit_bundle, price, mask, availability, bounds
from investigate_capture import write_csv
from research_activity_calibration import metrics, shadow
from research_bursty_optimizer import dump
from research_bursty_startup_raw import phase_cells, phase_error, paired
from research_expanded_bursty import context
from research_nonfrozen_pricing import measures, summarize, group
from research_pooled_symbolic import load_inputs
from research_quantile_level import DEPENDENCIES as PARENT_DEPENDENCIES
from research_symbolic_corridor import regime_cells

DEPENDENCIES=tuple(dict.fromkeys(('full_raw_pipeline.py','research_full_raw_pipeline.py',
                                 'test_full_raw_pipeline.py')+PARENT_DEPENDENCIES))
SCORE_GROUPS=('all','frozen','active','sparse','bursty','pump','dump')
LOSS_GROUPS=('all','frozen','bursty','pump','dump')
HOUR=3600000


def cached_fit(cache,ctx,periods,cutoff,retained,stage):
    if stage=='retained':return fit_bundle([],{},periods,cutoff,retained,stage)
    # The data universe is immutable within this run. Core fits depend on its
    # date/cutoff and overlay spec; overlay-only fits also depend on the old core.
    binding=dict(stage=stage,periods=periods,cutoff=cutoff,overlay=retained['overlay']['spec'])
    if stage=='raw_overlay':binding['engine']=retained['engine']
    key=json.dumps(binding,sort_keys=True)
    if key not in cache:
        cache[key]=fit_bundle(ctx['original'],ctx['expanded_rawdays'],periods,cutoff,retained,stage)
    return cache[key]


def scoring_sessions(ctx, dates):
    sessions=[]
    for day in dates:
        if day not in ctx['expanded_rawdays']:
            sessions.extend(dict(s,rows=[p['row'] for p in s['values']]) for s in ctx['sessions']
                            if s['source']=='normalized' and s['period']==day)
            continue
        rows=ctx['expanded_rawdays'][day]
        origin=int(datetime.fromisoformat(day).replace(tzinfo=timezone.utc).timestamp()*1000)
        intervals=[dict(start=origin+h*HOUR,end=origin+(h+8)*HOUR,hour=h) for h in (0,8,16)]
        sessions.append(dict(id='raw_selection:'+day+':continuous',source='raw_selection',period=day,
            split='selection',mode='continuous',intervals=intervals,rows=rows))
        for interval in intervals:
            sessions.append(dict(id=f'raw_selection:{day}:restart:{interval["hour"]:02}',source='raw_selection',
                period=day,split='selection',mode='restart',intervals=[interval],
                rows=[r for r in rows if interval['start']<=r['start']<interval['end']]))
    return sessions


def losses(values):
    return {g:metrics(shadow(group(values,g))) for g in LOSS_GROUPS}


def score(cases, phases):
    components={}
    for name in SCORE_GROUPS:
        rows=[r for r in cases if r['activity']==name and r['eligible_outcomes']>=20]
        errors=[abs(r['error_pp']) if r['windows']>=20 else 52. for r in rows]
        if errors:components[name]=mean(errors)+.25*max(errors)
    if 'all' not in components:raise ValueError('no populated overall selection cases')
    overall=[r['eligible_quote_fraction'] for r in cases if r['activity']=='all' and r['eligible_outcomes']]
    frozen=[r['eligible_quote_fraction'] for r in cases if r['activity']=='frozen' and r['eligible_outcomes']>=20]
    constraints=availability(cases)
    penalty=(25*mean(1-v for v in overall)+(25*mean(1-v for v in frozen) if frozen else 0)+
        100*max(0,AVAILABILITY['minimum_overall']-constraints['minimum_overall'])+
        100*max(0,AVAILABILITY['minimum_populated_frozen']-constraints['minimum_populated_frozen']))
    return dict(score=mean(components.values())+.5*phase_error(phases)+penalty,
                calibration_components=components,availability_penalty=penalty,constraints=constraints)


def select(ctx,expanded,engine_selection,residual_selection,output,cache=None):
    cache={} if cache is None else cache
    details=[];models={};session_records=[]
    for old,ef in zip(residual_selection['models'],engine_selection['models']):
        begin=old['training_days']
        if begin!=ef['training_days']:raise ValueError('prefix alignment differs')
        prior=next(m for m in ctx['expanded_selection']['models'] if m['training_days']==begin)['sources']['existing']['prior']['model']
        retained=dict(engine=ef['engine'],overlay=ef['overlay'],prior=prior)
        models[str(begin)]={stage:cached_fit(cache,ctx,old['training_periods'],old['cutoff'],retained,stage) for stage in STAGES}
        dates=next(r['scoring_days'] for r in residual_selection['folds'] if r['training_days']==begin)
        if any(day>=min(dates) for day in old['training_periods']):raise ValueError('training crosses scoring boundary')
        sessions=scoring_sessions(ctx,dates)
        session_records.append(dict(training_days=begin,scoring_days=dates,
            sessions=[dict(id=s['id'],source=s['source'],period=s['period'],mode=s['mode'],rows=len(s['rows'])) for s in sessions]))
        cases={c:[] for c in VARIANTS};phases={c:[] for c in VARIANTS};full={stage:[] for stage in STAGES}
        for s in sessions:
            for stage in STAGES:
                base,prices=price(s['rows'],models[str(begin)][stage]);full[stage].extend(prices)
                for policy in POLICIES:
                    candidate=stage+':'+policy;values=mask(prices,base,policy)
                    cases[candidate].extend(measures(s,values,candidate,policy))
                    phases[candidate].extend(phase_cells(s,values,candidate,policy))
        reference_loss=losses(full['retained'])
        for stage in STAGES:
            loss=losses(full[stage])
            guard=sum(100*max(0,loss[g]['pinball_ppm']/b['pinball_ppm']-1.1) for g,b in reference_loss.items()
                      if b['windows']>=20 and b['pinball_ppm'])
            for policy in POLICIES:
                candidate=stage+':'+policy;modes={}
                for mode in ('restart','continuous'):
                    modes[mode]=score([r for r in cases[candidate] if r['mode']==mode],
                                      [r for r in phases[candidate] if r['mode']==mode])
                value=mean(r['score'] for r in modes.values())+.25*abs(modes['restart']['score']-modes['continuous']['score'])+guard
                details.append(dict(candidate=candidate,training_days=begin,scoring_days=dates,score=value,modes=modes,
                                    loss_guard=guard,full_reference_losses=loss))
        print('Full raw pipeline selection fold '+str(begin),flush=True)
    ranking=[]
    for candidate in VARIANTS:
        rows=[r for r in details if r['candidate']==candidate]
        ranking.append(dict(candidate=candidate,score=mean(r['score'] for r in rows),folds=[r['score'] for r in rows],
            feasible=all(m['constraints']['feasible'] for r in rows for m in r['modes'].values())))
    ranking.sort(key=lambda r:(not r['feasible'],r['score'],VARIANTS.index(r['candidate'])))
    result=dict(selected=ranking[0]['candidate'],ranking=ranking,folds=details,scoring_inputs=session_records,
                later_diagnostics_excluded=True,independent_holdout=False)
    dump(output/'inner-models.json',models);dump(output/'selection.json',result)
    return result,models


def diagnostics(ctx,models,previous,output):
    cases=[];regimes=[];phases=[];bound_rows=[]
    saved={c:{} for c in VARIANTS};prior_cells={(r['policy'],r['case_id'],r['activity']):r for r in previous['cases'] if r['candidate']=='retained_pool'}
    evaluated=[s for s in ctx['sessions'] if s['source']!='normalized' or s['period'] not in ctx['data']['dates'][:14]]
    reconstructed=0
    with gzip.open(output/'predictions.jsonl.gz','wt',compresslevel=5) as stream:
        for index,s in enumerate(evaluated):
            key,_,_=context(ctx,s)
            for stage in STAGES:
                base,prices=price([p['row'] for p in s['values']],models[key][stage])
                for policy in POLICIES:
                    candidate=stage+':'+policy;values=mask(prices,base,policy)
                    cells=measures(s,values,candidate,policy)
                    if stage=='retained' and policy!='no_pause':
                        for r in cells:
                            old=prior_cells[(policy,r['case_id'],r['activity'])]
                            for f in ('windows','survived','eligible_outcomes','mean_width_ppm','full_window_pinball_ppm'):
                                if r[f]!=old[f]:raise ValueError('retained control differs: '+f)
                            reconstructed+=1
                    cases.extend(cells);regimes.extend(regime_cells(s,values,candidate,policy))
                    phases.extend(phase_cells(s,values,candidate,policy));saved[candidate][s['id']]=values
                    for interval in s['intervals']:
                        for activity in ('all','frozen','bursty','pump','dump'):
                            part=group([p for p in values if interval['start']<=p['row']['start']<interval['end']],activity)
                            bound_rows.append(dict(candidate=candidate,policy=policy,case_id=f'{s["id"]}:{interval["hour"]:02}',
                                source=s['source'],period=s['period'],mode=s['mode'],activity=activity,**interval,**bounds(part)))
                    for p in values:
                        stream.write(json.dumps(dict(candidate=candidate,session=s['id'],start=p['row']['start'],
                            activity=p['row']['activity_state'],regime=p['row']['market_regime'],width=p['width_ppm'],
                            shadow=p['shadow_survived'],paused=p['paused'],floor_reason=p['floor_reason']),allow_nan=False)+'\n')
            if index%10==0:print(f'Full raw diagnostics {index+1}/{len(evaluated)}',flush=True)
    pairs=[r for c,values in saved.items() for r in paired(evaluated,values,c,c.split(':')[1])]
    return dict(cases=cases,regimes=regimes,phases=phases,floor_bounds=bound_rows,paired=pairs,
                summary=summarize(cases),evaluated_sessions=len(evaluated),reconstructed_control_cells=reconstructed)


def run(previous_dir,output):
    if output.exists():raise ValueError('preserve prior research; choose a new output')
    started=time.monotonic()
    previous=json.loads((previous_dir/'research.json').read_text())
    protocol=dict(previous=str(previous_dir.resolve()),previous_sha256=file_hash(previous_dir/'research.json'),
        source_sha256={n:file_hash(Path(__file__).with_name(n)) for n in DEPENDENCIES},spec=SPEC,variants=VARIANTS,
        availability_screens=AVAILABILITY,target_survival=.48,band=[.43,.53],
        score=dict(groups=SCORE_GROUPS,group_mean_plus_worst=.25,phase_weight=.5,availability_weights=[25,25],
                   availability_shortfall_weight=100,full_reference_loss_groups=LOSS_GROUPS,loss_guard_tolerance=.1),
        no_candidate_promoted=True,capture_started=False,independent_holdout=False,
        main_change='Core and frozen overlay may refit on complete preceding raw replacements; admission changes are explicit. No future dates, new downloads, current outcomes or eligibility inputs at entry.',
        scoring_change='Use complete raw scoring dates when already retained, within original earlier scoring dates. Frozen calibration and >=50% populated frozen availability now explicit. Scores are not comparable to preceding normalized-only selection.')
    output.mkdir(parents=True);(output/'source').mkdir()
    for name in DEPENDENCIES:shutil.copyfile(Path(__file__).with_name(name),output/'source'/name)
    dump(output/'protocol.json',protocol)
    # The preceding quantile experiment binds the unchanged parent models/cache.
    from research_startup_admission import verify_code
    verify_code(previous_dir,previous)
    for name,key in (('selection.json','selection_sha256'),('predictions.jsonl.gz','predictions_sha256')):
        if file_hash(previous_dir/name)!=previous[key]:raise ValueError('preceding artifact differs')
    parent=Path(previous['previous'])
    if file_hash(parent/'research.json')!=previous['previous_sha256']:raise ValueError('parent binding differs')
    optimizer,residual,expanded,ctx,checked,_,residual_dir=load_inputs(parent)
    engine_selection=json.loads((ctx['prior_dir']/'selection.json').read_text())
    residual_selection=json.loads((residual_dir/'selection.json').read_text())
    cache={}
    chosen,_=select(ctx,expanded,engine_selection,residual_selection,output,cache)
    models={}
    evaluated=[s for s in ctx['sessions'] if s['source']!='normalized' or s['period'] not in ctx['data']['dates'][:14]]
    for s in evaluated:
        key,engine,overlay=context(ctx,s)
        if key in models:continue
        b=residual['models'][key]
        retained=dict(engine=engine,overlay=overlay,prior=expanded['models'][key]['existing']['prior']['model'])
        models[key]={stage:cached_fit(cache,ctx,b['training_periods'],b['cutoff'],retained,stage) for stage in STAGES}
        print('Full raw outer fits '+key,flush=True)
    dump(output/'models.json',models)
    pinned={name:file_hash(output/name) for name in ('selection.json','models.json','inner-models.json')}
    print('Full raw choices and all models pinned before diagnostics',flush=True)
    diagnostic=diagnostics(ctx,models,previous,output)
    for name,digest in pinned.items():
        if file_hash(output/name)!=digest:raise ValueError('pinned model/selection changed')
    for name,digest in protocol['source_sha256'].items():
        if file_hash(Path(__file__).with_name(name))!=digest:raise ValueError('source changed during run')
    result=dict(protocol,selected=chosen['selected'],ranking=chosen['ranking'],
        selection_sha256=pinned['selection.json'],models_sha256=pinned['models.json'],inner_models_sha256=pinned['inner-models.json'],
        predictions_sha256=file_hash(output/'predictions.jsonl.gz'),feature_records_verified=checked,
        distinct_new_model_fits=len(cache),elapsed_seconds=time.monotonic()-started,**diagnostic)
    dump(output/'research.json',result)
    for name in ('cases','regimes','phases','floor_bounds','paired','summary'):
        write_csv(output/(name+'.csv'),result[name],list(result[name][0]))
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--previous',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    args=p.parse_args();r=run(args.previous,args.output)
    print(json.dumps(dict(selected=r['selected'],ranking=r['ranking'],elapsed_seconds=r['elapsed_seconds']),indent=2))
