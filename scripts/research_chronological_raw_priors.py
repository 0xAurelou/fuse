#!/usr/bin/env python3
"""Chronological raw-prior replacement with fixed base engines and admission."""
import argparse
from collections import defaultdict
import gzip
import json
from pathlib import Path
import shutil
from statistics import mean

from chronological_raw_priors import (METHODS, PRIOR_SOURCES, VARIANTS, name,
    fit_bundle, floor_values, replay)
from capture_dataset import file_hash
from investigate_capture import write_csv
from oracle_activity_features import load
from research_activity_calibration import fit, predict
from research_flat_pause import ENGINE_SPEC, apply_pause
from research_frozen_pricing import PAUSE, fit_overlay
from research_bursty_episodes import DEPENDENCIES as OLD_DEPENDENCIES, episode_cells
from bursty_episodes import SPECS, reprice as episode_reprice
from research_bursty_drift import phases, phase_score, paired_cells
from research_bursty_pricing import losses, burst_score
from research_nonfrozen_pricing import (POLICIES, read_sessions, fixed_mask, measures,
    selection_components, summarize, verify_raw)
from research_startup_admission import priced, verify_code
from startup_admission import SPECS as RULES, admit

DEPENDENCIES=tuple(dict.fromkeys(('chronological_raw_priors.py',
    'research_chronological_raw_priors.py','test_chronological_raw_priors.py')+OLD_DEPENDENCIES))


def choose(original, raw_days, dates, sessions, overlay_spec):
    scores, folds, bundles = defaultdict(list), [], []
    rule=next(r for r in RULES if r['name']==POLICIES[0])
    for begin,end in ((6,9),(9,12),(12,14)):
        periods=dates[:begin];cutoff=dates[begin]
        train=[r for r in original if r['period'] in periods]
        engine=fit(train,ENGINE_SPEC)
        overlay=fit_overlay(apply_pause(predict(train,engine),PAUSE),overlay_spec)
        models={s:fit_bundle(original,raw_days,periods,cutoff,engine,overlay,s=='raw_replacement')
                for s in PRIOR_SOURCES}
        bundles.append(dict(training_days=begin,engine=engine,overlay=overlay,priors=models))
        inputs=[]
        for session in sessions:
            if session['source']=='normalized' and session['period'] in dates[begin:end]:
                values=priced([p['row'] for p in session['values']],engine,overlay)
                inputs.append((session,values,floor_values(values,engine),admit(values,rule)))
        baseline=losses([p for _,v,_,_ in inputs for p in v])
        for source,method in VARIANTS:
            candidate=name(source,method);cases=[];pc=[];predictions=[]
            for session,_,base,mask in inputs:
                values=replay(base,models[source]['model'],method);predictions.extend(values)
                cases.extend(measures(session,fixed_mask(values,mask),candidate,rule['name']))
                pc.extend(phases(session,values,candidate))
            ms={m:selection_components([r for r in cases if r['mode']==m])
                +burst_score([r for r in cases if r['mode']==m])
                +.5*phase_score([r for r in pc if r['mode']==m]) for m in ('restart','continuous')}
            loss=losses(predictions)
            penalty=sum(100*max(0,loss[g]['pinball_ppm']/b['pinball_ppm']-1.1)
                        for g,b in baseline.items() if b['windows']>=20 and b['pinball_ppm'])
            score=mean(ms.values())+.25*abs(ms['restart']-ms['continuous'])+penalty
            scores[candidate].append(score)
            folds.append(dict(candidate=candidate,training_days=begin,scoring_days=dates[begin:end],
                score=score,mode_scores=ms,loss_guard_penalty=penalty,full_path_losses=loss))
        print(f'prior selection {begin}->{end} complete',flush=True)
    ranking=sorted((dict(candidate=name(s,m),score=mean(scores[name(s,m)]),
        folds=scores[name(s,m)],index=i) for i,(s,m) in enumerate(VARIANTS)),key=lambda r:(r['score'],r['index']))
    return dict(ranking=ranking,folds=folds,models=bundles,selected=ranking[0]['candidate'])


def run(previous_dir,output):
    if output.exists():raise ValueError('preserve prior experiments')
    previous=json.loads((previous_dir/'research.json').read_text());verify_code(previous_dir,previous)
    if file_hash(previous_dir/'extension-input-sessions.jsonl.gz')!=previous['extension_inputs_sha256']:
        raise ValueError('extension cache differs')
    if file_hash(previous_dir/'predictions.jsonl.gz')!=previous['predictions_sha256']:
        raise ValueError('benchmark predictions differ')
    parents={}
    for key in ('admission','controls'):
        d=Path(previous[key]);r=json.loads((d/'research.json').read_text());verify_code(d,r)
        if file_hash(d/'research.json')!=previous[key+'_sha256']:raise ValueError('parent differs')
        parents[key]=r
    admission,control=parents['admission'],parents['controls']
    sessions=read_sessions(Path(previous['admission']),admission)+read_sessions(Path(previous['controls']),control)
    with gzip.open(previous_dir/'extension-input-sessions.jsonl.gz','rt') as f:
        extension=[json.loads(line) for line in f]
    sessions+=extension
    raw_days={s['period']:[p['row'] for p in s['values']] for s in extension
              if s['source']=='raw_extended' and s['mode']=='continuous'}
    if sorted(raw_days)!=['2025-01-01','2025-06-01']:raise ValueError('unexpected raw training days')
    verify_raw(dict(raw=previous['raw'],raw_manifest_sha256=previous['raw_manifest_sha256']))
    if file_hash(Path(previous['raw'])/'download-protocol.json')!=previous['raw_protocol_sha256']:
        raise ValueError('raw protocol differs')
    verify_raw(control)
    rawold=json.loads((Path(admission['raw_research'])/'research.json').read_text())
    verify_code(Path(admission['raw_research']),rawold);verify_raw(rawold)
    pricing=json.loads((Path(admission['pricing'])/'research.json').read_text())
    verify_code(Path(admission['pricing']),pricing)
    for key,obj in (('raw_research',rawold),('pricing',pricing)):
        if file_hash(Path(admission[key])/'research.json')!=admission[key+'_sha256']:raise ValueError('pricing ancestor differs')
    drift_dir=Path(previous['previous']);drift=json.loads((drift_dir/'research.json').read_text());verify_code(drift_dir,drift)
    pool_dir=Path(drift['previous']);pool=json.loads((pool_dir/'research.json').read_text());verify_code(pool_dir,pool)
    base_dir=Path(pool['previous']);base=json.loads((base_dir/'research.json').read_text());verify_code(base_dir,base)
    for d,h in ((drift_dir,previous['previous_sha256']),(pool_dir,drift['previous_sha256']),(base_dir,pool['previous_sha256'])):
        if file_hash(d/'research.json')!=h:raise ValueError('benchmark ancestor differs')
    original,data=load(Path(previous['dataset']))
    if file_hash(Path(previous['dataset'])/'dataset.json')!=previous['dataset_sha256']:raise ValueError('dataset differs')
    # Original training days have future-fitted engines. They are not chronological evaluation.
    evaluated=[s for s in sessions if s['source']!='normalized' or s['period'] not in data['dates'][:14]]
    protocol=dict(previous=str(previous_dir.resolve()),previous_sha256=file_hash(previous_dir/'research.json'),
        dataset=previous['dataset'],dataset_sha256=previous['dataset_sha256'],raw=previous['raw'],
        raw_manifest_sha256=previous['raw_manifest_sha256'],extension_inputs_sha256=previous['extension_inputs_sha256'],
        source_sha256={n:file_hash(Path(__file__).with_name(n)) for n in DEPENDENCIES},
        variants=[dict(prior=s,method=m,name=name(s,m)) for s,m in VARIANTS],
        training_rule='same original training dates, replace matching full raw day, equal date mass, strictly before scoring date',
        raw_training_days=sorted(raw_days),engine_frozen=True,frozen_overlay_fixed=True,admission_fixed=POLICIES,
        excluded_future_engine_training_sessions=len(sessions)-len(evaluated),
        evaluated_sessions=len(evaluated),target_survival=.48,band=[.43,.53],
        capture_started=False,live_candidate_promoted=False,independent_holdout=False,
        selection='unchanged three chronological folds, normalized scoring only; raw replacement allowed only inside training prefix',
        expanded_raw_excluded_from_scoring_selection=True,repeated_inspected_periods=True)
    output.mkdir(parents=True);(output/'source').mkdir()
    for n in DEPENDENCIES:shutil.copyfile(Path(__file__).with_name(n),output/'source'/n)
    (output/'protocol.json').write_text(json.dumps(protocol,indent=2)+'\n')
    selection=choose(original,raw_days,data['dates'],sessions,pricing['models']['hurdle_all_120']['spec'])
    (output/'selection.json').write_text(json.dumps(selection,indent=2)+'\n')
    cases=[];pc=[];ep=[];models={};availability={};saved={name(s,m):{} for s,m in VARIANTS}
    references={(r['candidate'],r['policy'],r['case_id'],r['activity']):r for r in previous['cases']}
    checks=0
    def context(session):
        if session['source'] in ('raw_control','normalized_control','raw_extended','raw_matched'):
            key=session['period'];overlay=control['models'][key]['overlay']
        elif session['source']=='raw':
            key='raw_january';overlay=rawold['models'][session['period']]['overlays']['frozen_floor_53']['hurdle_all_120']
        else:key='original_final';overlay=pricing['models']['hurdle_all_120']
        return key,overlay
    with gzip.open(output/'predictions.jsonl.gz','wt',compresslevel=5) as stream:
        for index,session in enumerate(evaluated):
            key,overlay=context(session);bm=base['models'][key];engine=bm['engine']
            cutoff=min(b['start'] for b in session['intervals'])
            if key not in models:
                # Cutoff is a calendar date; native run labels have no hyphens.
                day=session['period'] if session['source']!='native' else '2026-10-26'
                models[key]={source:fit_bundle(original,raw_days,bm['training_periods'],day,
                    engine,overlay,source=='raw_replacement') for source in PRIOR_SOURCES}
                if models[key]['normalized']['model']!=previous['models'][key]['model']:
                    raise ValueError('normalized prior failed benchmark reconstruction')
            if any(r>=session['period'] for r in bm['training_periods']):raise ValueError('future training date')
            if any(p['expiry']+30_000>=cutoff for p in original if p['period'] in bm['training_periods']):
                raise ValueError('training outcome not mature before scoring')
            floor=floor_values(session['values'],engine)
            meta=episode_reprice(floor,models[key]['normalized']['model'],next(c for c in SPECS if c['name']=='episode_cdf'))
            masks={p:admit(session['values'],next(r for r in RULES if r['name']==p)) for p in POLICIES}
            for source,method in VARIANTS:
                candidate=name(source,method);values=replay(floor,models[key][source]['model'],method)
                for p,b in zip(values,floor):
                    if (p['width_ppm'] is None,p['shadow_survived'] is None,p['paused'])!=(b['width_ppm'] is None,b['shadow_survived'] is None,b['paused']):
                        raise ValueError('eligibility changed')
                    if b['row']['activity_state']!='bursty' and (p['width_ppm'],p['shadow_survived'])!=(b['width_ppm'],b['shadow_survived']):
                        raise ValueError('non-bursty changed')
                for policy,mask in masks.items():
                    rows=measures(session,fixed_mask(values,mask),candidate,policy)
                    for r in rows:
                        k=(r['case_id'],r['activity'],policy)
                        counts=tuple(r[n] for n in ('windows','eligible_outcomes','pre_entry_predictions','offered_pre_entry_decisions','grid_windows'))
                        if k in availability and availability[k]!=counts:raise ValueError('availability differs')
                        availability[k]=counts
                        if source=='normalized':
                            ref=references[(method,policy,r['case_id'],r['activity'])]
                            for n in ('windows','survived','full_window_pinball_ppm','mean_width_ppm'):
                                if ref[n]!=r[n]:raise ValueError('benchmark differs '+n)
                            checks+=1
                    cases.extend(rows)
                pc.extend(phases(session,values,candidate));ep.extend(episode_cells(session,values,meta,candidate))
                saved[candidate][session['id']]=[p for p in values if p['row']['activity_state']=='bursty' and p['shadow_survived'] is not None]
                for p in values:
                    stream.write(json.dumps(dict(candidate=candidate,session=session['id'],start=p['row']['start'],
                        width=p['width_ppm'],shadow=p['shadow_survived']),separators=(',',':'))+'\n')
            if index%10==0:print(f'prior replay {index+1}/{len(evaluated)}',flush=True)
    paired=[r for c in saved for r in paired_cells(evaluated,saved[c],c)]
    result=dict(protocol,selected=selection['selected'],ranking=selection['ranking'],models=models,
        cases=cases,phases=pc,episode_phases=ep,paired=paired,summary=summarize(cases),
        checks=dict(benchmark_cells_reconstructed=checks,non_bursty_and_frozen_invariant=True,
            eligibility_and_availability_invariant=True,identical_paired_paths=True,strict_chronological_prior_training=True),
        predictions_sha256=file_hash(output/'predictions.jsonl.gz'),selection_sha256=file_hash(output/'selection.json'))
    for n,h in protocol['source_sha256'].items():
        if file_hash(Path(__file__).with_name(n))!=h:raise ValueError('source changed during replay')
    (output/'research.json').write_text(json.dumps(result,indent=2)+'\n')
    for key in ('cases','phases','episode_phases','paired','summary'):
        write_csv(output/(key.replace('_','-')+'.csv'),result[key],list(result[key][0]))
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--previous',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();r=run(a.previous,a.output)
    print(json.dumps(dict(selected=r['selected'],ranking=r['ranking'],checks=r['checks']),indent=2))
