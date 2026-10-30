#!/usr/bin/env python3
"""Pre-entry flat-risk admission and conditional June-drift pricing research."""
import argparse
from collections import defaultdict
import gzip
import json
from pathlib import Path
import shutil
from statistics import mean

from adaptive_corridor import required_width
from preentry_bursty import (FIT_SPEC,ONLINE_SPEC,PRICING,GATES,VARIANTS,name,fit,reprice,admit)
from capture_dataset import file_hash
from chronological_raw_priors import training_rows,floor_values,replay
from investigate_capture import write_csv
from oracle_activity_features import load
from research_bursty_pricing import losses,burst_score
from research_bursty_startup_raw import (DEPENDENCIES as OLD_DEPENDENCIES,phase_cells,phase_error,
                                       availability_charge,paired)
from research_nonfrozen_pricing import POLICIES,read_sessions,fixed_mask,measures,selection_components,summarize,verify_raw
from research_startup_admission import priced,verify_code
from startup_admission import SPECS as RULES,admit as old_admit

DEPENDENCIES=tuple(dict.fromkeys(('preentry_bursty.py','research_preentry_bursty.py','test_preentry_bursty.py','test_preentry_research.py')+OLD_DEPENDENCIES))
AVAILABILITY=dict(minimum_pooled_bursty_retention=.95,minimum_populated_case_retention=.90)


def retention(cases,reference):
    before={(r['case_id'],r['activity']):r for r in reference}
    part=[r for r in cases if r['activity']=='bursty'];n=sum(before[(r['case_id'],'bursty')]['windows'] for r in part)
    pooled=sum(r['windows'] for r in part)/n if n else 1
    ratios=[r['windows']/before[(r['case_id'],'bursty')]['windows'] for r in part
            if before[(r['case_id'],'bursty')]['windows']>=20]
    minimum=min(ratios,default=1)
    return dict(pooled=pooled,minimum_populated=minimum,
        feasible=pooled>=AVAILABILITY['minimum_pooled_bursty_retention'] and minimum>=AVAILABILITY['minimum_populated_case_retention'])


def fit_prefix(original,rawdays,bundle,engine,overlay):
    rows,provenance=training_rows(original,rawdays,bundle['training_periods'],bundle['cutoff'],True)
    values=floor_values(priced(rows,engine,overlay),engine)
    return dict(training_periods=bundle['training_periods'],cutoff=bundle['cutoff'],provenance=provenance,model=fit(values))


def choose(original,rawdays,sessions,oldselection,engine_selection):
    scores=defaultdict(list);feasible=defaultdict(list);folds=[];models=[]
    rule=next(r for r in RULES if r['name']==POLICIES[0])
    for old,enginefold in zip(oldselection['models'],engine_selection['models']):
        if old['training_days']!=enginefold['training_days']:raise ValueError('fold engine differs')
        engine,overlay=enginefold['engine'],enginefold['overlay'];prior=old['priors']['raw_earlier']
        fitted=fit_prefix(original,rawdays,prior,engine,overlay);model=fitted['model']
        models.append(dict(training_days=old['training_days'],**fitted))
        dates=next(r['scoring_days'] for r in oldselection['folds'] if r['training_days']==old['training_days'])
        inputs=[]
        for s in sessions:
            if s['source']=='normalized' and s['period'] in dates:
                base=priced([p['row'] for p in s['values']],engine,overlay);floor=floor_values(base,engine)
                retained=replay(floor,prior['model'],'floor10_burst_pool120');mask=old_admit(base,rule)
                alternatives={method:reprice(floor,retained,model,method) for method in PRICING}
                ref=measures(s,fixed_mask(retained,mask),'reference',rule['name'])
                inputs.append((s,base,mask,alternatives,ref))
        original_loss=losses([p for _,v,_,_,_ in inputs for p in v])
        for method,gate in VARIANTS:
            candidate=name(method,gate);cases=[];pc=[];refs=[];full=[]
            for s,_,mask,alternatives,ref in inputs:
                v=admit(fixed_mask(alternatives[method],mask),gate)
                cases.extend(measures(s,v,candidate,rule['name']));pc.extend(phase_cells(s,v,candidate,rule['name']))
                refs.extend(ref);full.extend(alternatives[method])
            mode_scores={};constraints={};charges={}
            for mode in ('restart','continuous'):
                part=[r for r in cases if r['mode']==mode];ref=[r for r in refs if r['mode']==mode]
                constraints[mode]=retention(part,ref);charges[mode]=availability_charge(part,ref)
                mode_scores[mode]=(selection_components(part)+burst_score(part)+.5*phase_error([r for r in pc if r['mode']==mode])+charges[mode])
            loss=losses(full)
            penalty=sum(100*max(0,loss[g]['pinball_ppm']/b['pinball_ppm']-1.1)
                for g,b in original_loss.items() if b['windows']>=20 and b['pinball_ppm'])
            score=mean(mode_scores.values())+.25*abs(mode_scores['restart']-mode_scores['continuous'])+penalty
            scores[candidate].append(score);feasible[candidate].append(all(r['feasible'] for r in constraints.values()))
            folds.append(dict(candidate=candidate,training_days=old['training_days'],scoring_days=dates,score=score,
                mode_scores=mode_scores,availability_charge=charges,retention=constraints,loss_guard=penalty,full_reference_losses=loss))
        print(f'pre-entry selection fold {old["training_days"]}',flush=True)
    ranking=sorted((dict(candidate=name(m,g),score=mean(scores[name(m,g)]),folds=scores[name(m,g)],
        availability_feasible=all(feasible[name(m,g)]),index=i) for i,(m,g) in enumerate(VARIANTS)),
        key=lambda r:(not r['availability_feasible'],r['score'],r['index']))
    expected=next(r['score'] for r in oldselection['ranking'] if r['candidate']=='raw_earlier:unchanged')
    actual=next(r['score'] for r in ranking if r['candidate']=='retained_pool:unchanged')
    if expected!=actual:raise ValueError('earlier retained baseline score differs')
    return dict(selected=ranking[0]['candidate'],ranking=ranking,folds=folds,models=models)


def load_inputs(previous_dir):
    previous=json.loads((previous_dir/'research.json').read_text());verify_code(previous_dir,previous)
    for n,key in (('predictions.jsonl.gz','predictions_sha256'),('selection.json','selection_sha256'),('earlier-training-rows.jsonl.gz','training_rows_sha256')):
        if file_hash(previous_dir/n)!=previous[key]:raise ValueError('previous artifact differs')
    prior_dir=Path(previous['previous']);prior=json.loads((prior_dir/'research.json').read_text());verify_code(prior_dir,prior)
    if file_hash(prior_dir/'research.json')!=previous['previous_sha256']:raise ValueError('prior ancestor differs')
    episode_dir=Path(prior['previous']);episode=json.loads((episode_dir/'research.json').read_text());verify_code(episode_dir,episode)
    if file_hash(episode_dir/'research.json')!=prior['previous_sha256']:raise ValueError('episode ancestor differs')
    parents={}
    for key in ('admission','controls'):
        d=Path(episode[key]);m=json.loads((d/'research.json').read_text());verify_code(d,m)
        if file_hash(d/'research.json')!=episode[key+'_sha256']:raise ValueError('input parent differs')
        parents[key]=m
    sessions=read_sessions(Path(episode['admission']),parents['admission'])+read_sessions(Path(episode['controls']),parents['controls'])
    if file_hash(episode_dir/'extension-input-sessions.jsonl.gz')!=episode['extension_inputs_sha256']:raise ValueError('extension cache differs')
    with gzip.open(episode_dir/'extension-input-sessions.jsonl.gz','rt') as f:extension=[json.loads(line) for line in f]
    sessions+=extension
    rawdays={s['period']:[p['row'] for p in s['values']] for s in extension if s['source']=='raw_extended' and s['mode']=='continuous'}
    with gzip.open(previous_dir/'earlier-training-rows.jsonl.gz','rt') as f:
        for line in f:
            row=json.loads(line);rawdays.setdefault(row['period'],[]).append(row)
    verify_raw(previous);verify_raw(dict(raw=episode['raw'],raw_manifest_sha256=episode['raw_manifest_sha256']))
    original,data=load(Path(previous['dataset']))
    if file_hash(Path(previous['dataset'])/'dataset.json')!=previous['dataset_sha256']:raise ValueError('dataset differs')
    admission,control=parents['admission'],parents['controls'];verify_raw(control)
    rawold_dir=Path(admission['raw_research']);rawold=json.loads((rawold_dir/'research.json').read_text());verify_code(rawold_dir,rawold);verify_raw(rawold)
    pricing_dir=Path(admission['pricing']);pricing=json.loads((pricing_dir/'research.json').read_text());verify_code(pricing_dir,pricing)
    for d,h in ((rawold_dir,admission['raw_research_sha256']),(pricing_dir,admission['pricing_sha256'])):
        if file_hash(d/'research.json')!=h:raise ValueError('pricing ancestor differs')
    base=episode
    for _ in range(3):
        d=Path(base['previous']);m=json.loads((d/'research.json').read_text());verify_code(d,m)
        if file_hash(d/'research.json')!=base['previous_sha256']:raise ValueError('engine ancestor differs')
        base=m
    return dict(previous=previous,prior_dir=prior_dir,original=original,data=data,sessions=sessions,rawdays=rawdays,
        control=control,rawold=rawold,pricing=pricing,base=base)


def risk_cells(session,values):
    result=[]
    for interval in session['intervals']:
        for group in ('non_frozen','bursty'):
            part=[p for p in values if interval['start']<=p['row']['start']<interval['end'] and p['shadow_survived'] is not None
                  and p['preentry_floor_risk'] is not None and (group=='non_frozen' or p['row']['activity_state']=='bursty')]
            for low,high in ((0,.1),(.1,.3),(.3,.53),(.53,.65),(.65,1.000001)):
                rows=[p for p in part if low<=p['preentry_floor_risk']<high]
                n=len(rows)
                result.append(dict(source=session['source'],period=session['period'],mode=session['mode'],hour=interval['hour'],
                    activity=group,bin_low=low,bin_high=high,windows=n,
                    predicted=sum(p['preentry_floor_risk'] for p in rows)/n if n else None,
                    observed=sum(required_width(p['row'])<=1 for p in rows)/n if n else None,
                    brier=sum((p['preentry_floor_risk']-(required_width(p['row'])<=1))**2 for p in rows)/n if n else None))
    return result


def run(previous_dir,output):
    if output.exists():raise ValueError('preserve prior experiments')
    ctx=load_inputs(previous_dir);previous=ctx['previous'];original=ctx['original'];sessions=ctx['sessions']
    evaluated=[s for s in sessions if s['source']!='normalized' or s['period'] not in ctx['data']['dates'][:14]]
    declaration=dict(previous=str(previous_dir.resolve()),previous_sha256=file_hash(previous_dir/'research.json'),
        dataset=previous['dataset'],dataset_sha256=previous['dataset_sha256'],
        source_sha256={n:file_hash(Path(__file__).with_name(n)) for n in DEPENDENCIES},
        fit_spec=FIT_SPEC,online_spec=ONLINE_SPEC,pricing_methods=PRICING,gates=GATES,
        variants=[dict(pricing=m,gate=g,name=name(m,g)) for m,g in VARIANTS],availability_constraints=AVAILABILITY,
        pricing_prior='Earlier raw November/December 2024, January/June 2025 replacing normalized dates; strict preceding date/maturity cutoff',
        selection='Same chronological folds and earlier objective, phase and availability costs; full-reference price loss guard. Admission feasibility requires >=95% pooled bursty retention and >=90% per populated cell, each fold and mode.',
        evaluated_sessions=len(evaluated),target_survival=.48,band=[.43,.53],
        capture_started=False,live_candidate_promoted=False,independent_holdout=False,
        raw_evaluation_excluded_from_selection=True,frozen_and_non_bursty_pricing_and_admission_fixed=True)
    output.mkdir(parents=True);(output/'source').mkdir()
    for n in DEPENDENCIES:shutil.copyfile(Path(__file__).with_name(n),output/'source'/n)
    (output/'protocol.json').write_text(json.dumps(declaration,indent=2)+'\n')
    oldselection=json.loads((previous_dir/'selection.json').read_text())
    engine_selection=json.loads((ctx['prior_dir']/'selection.json').read_text())
    selection=choose(original,ctx['rawdays'],sessions,oldselection,engine_selection)
    (output/'selection.json').write_text(json.dumps(selection,indent=2)+'\n')
    models={};cases=[];pc=[];risk=[];saved={name(m,g):{p:{} for p in POLICIES} for m,g in VARIANTS};reconstructed=0
    refs={(r['candidate'],r['policy'],r['case_id'],r['activity']):r for r in previous['cases']}
    with gzip.open(output/'predictions.jsonl.gz','wt',compresslevel=5) as stream:
        for index,s in enumerate(evaluated):
            if s['source'] in ('raw_control','normalized_control','raw_extended','raw_matched'):
                key=s['period'];overlay=ctx['control']['models'][key]['overlay']
            elif s['source']=='raw':key='raw_january';overlay=ctx['rawold']['models'][s['period']]['overlays']['frozen_floor_53']['hurdle_all_120']
            else:key='original_final';overlay=ctx['pricing']['models']['hurdle_all_120']
            bm=ctx['base']['models'][key];engine=bm['engine'];prior=previous['models'][key]['raw_earlier']
            if key not in models:models[key]=fit_prefix(original,ctx['rawdays'],prior,engine,overlay)
            model=models[key]['model'];floor=floor_values(s['values'],engine)
            retained=replay(floor,prior['model'],'floor10_burst_pool120')
            alternatives={method:reprice(floor,retained,model,method) for method in PRICING}
            risk.extend(risk_cells(s,alternatives['retained_pool']))
            masks={p:old_admit(s['values'],next(r for r in RULES if r['name']==p)) for p in POLICIES}
            for method,gate in VARIANTS:
                candidate=name(method,gate)
                for policy,mask in masks.items():
                    values=admit(fixed_mask(alternatives[method],mask),gate)
                    for a,b in zip(values,retained):
                        if (a['width_ppm'] is None,a['shadow_survived'] is None)!=(b['width_ppm'] is None,b['shadow_survived'] is None):raise ValueError('reference eligibility changed')
                        if b['row']['activity_state']!='bursty' and (a['width_ppm'],a['shadow_survived'])!=(b['width_ppm'],b['shadow_survived']):raise ValueError('non-bursty pricing changed')
                    rows=measures(s,values,candidate,policy)
                    if method=='retained_pool' and gate=='unchanged':
                        for c in rows:
                            ref=refs[('raw_earlier:unchanged',policy,c['case_id'],c['activity'])]
                            for f in ('windows','survived','eligible_outcomes','mean_width_ppm','full_window_pinball_ppm'):
                                if c[f]!=ref[f]:raise ValueError('retained benchmark differs '+f)
                            reconstructed+=1
                    cases.extend(rows);pc.extend(phase_cells(s,values,candidate,policy))
                    saved[candidate][policy][s['id']]=[p for p in values if p['row']['activity_state']=='bursty' and p['shadow_survived'] is not None]
                    for p in values:
                        if p['row']['activity_state']=='bursty':
                            stream.write(json.dumps(dict(candidate=candidate,policy=policy,session=s['id'],start=p['row']['start'],
                                width=p['width_ppm'],shadow=p['shadow_survived'],paused=p['paused'],risk=p['preentry_floor_risk'],
                                forecast=p['conditional_forecast'],correction=p['residual_correction'],effective=p['residual_effective'],
                                mass=p['residual_mass']),separators=(',',':'))+'\n')
            if index%10==0:print(f'pre-entry replay {index+1}/{len(evaluated)}',flush=True)
    pairs=[r for c,policies in saved.items() for p,values in policies.items() for r in paired(evaluated,values,c,p)]
    result=dict(declaration,selected=selection['selected'],ranking=selection['ranking'],models=models,cases=cases,phases=pc,paired=pairs,
        risk_cells=risk,summary=summarize(cases),selection_sha256=file_hash(output/'selection.json'),
        predictions_sha256=file_hash(output/'predictions.jsonl.gz'),
        checks=dict(benchmark_cells_reconstructed=reconstructed,reference_eligibility_fixed=True,
            non_bursty_pricing_fixed=True,identical_paired_paths=True,priors_use_only_mature_preceding_training_dates=True))
    for n,h in declaration['source_sha256'].items():
        if file_hash(Path(__file__).with_name(n))!=h:raise ValueError('source changed during replay')
    (output/'research.json').write_text(json.dumps(result,indent=2)+'\n')
    for n in ('cases','phases','paired','risk_cells','summary'):write_csv(output/(n+'.csv'),result[n],list(result[n][0]))
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--previous',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();r=run(a.previous,a.output)
    print(json.dumps(dict(selected=r['selected'],ranking=r['ranking'],checks=r['checks']),indent=2))
