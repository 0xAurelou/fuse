#!/usr/bin/env python3
"""Chronologically calibrated January risk and retained-price June adapters."""
import argparse
from collections import defaultdict
import gzip
import json
import math
from pathlib import Path
import shutil
from statistics import mean

from adaptive_corridor import required_width
from calibrated_bursty import SPEC,PRICING,GATES,VARIANTS,name,fit,all_series,admit
from capture_dataset import file_hash
from chronological_raw_priors import training_rows,floor_values,replay
from investigate_capture import write_csv
from research_bursty_pricing import losses,burst_score
from research_bursty_startup_raw import phase_cells,phase_error,availability_charge,paired
from research_nonfrozen_pricing import POLICIES,fixed_mask,measures,selection_components,summarize
from research_preentry_bursty import DEPENDENCIES as PREVIOUS_DEPENDENCIES,AVAILABILITY,retention,load_inputs
from research_startup_admission import priced,verify_code
from startup_admission import SPECS as RULES,admit as old_admit

DEPENDENCIES=tuple(dict.fromkeys(('calibrated_bursty.py','research_calibrated_bursty.py','test_calibrated_bursty.py')+PREVIOUS_DEPENDENCIES))


def fit_prefix(ctx,static_bundle,prior,engine,overlay):
    rows,provenance=training_rows(ctx['original'],ctx['rawdays'],static_bundle['training_periods'],static_bundle['cutoff'],True)
    base=floor_values(priced(rows,engine,overlay),engine)
    reference=replay(base,prior['model'],'floor10_burst_pool120')
    return dict(training_periods=static_bundle['training_periods'],cutoff=static_bundle['cutoff'],provenance=provenance,
                model=fit(base,reference,static_bundle['model']))


def risk_cells(session,values):
    out=[]
    for interval in session['intervals']:
        allpart=[p for p in values if interval['start']<=p['row']['start']<interval['end'] and p['risk_static'] is not None]
        burst=[p for p in allpart if p['row']['activity_state']=='bursty']
        for group,phase,raw in (('non_frozen','all',allpart),('bursty','all',burst),('bursty','first12',burst[:12]),('bursty','later',burst[12:])):
            part=[p for p in raw if p['shadow_survived'] is not None];n=len(part)
            for mode in ('static','chrono','context'):
                key='risk_'+mode
                out.append(dict(source=session['source'],period=session['period'],split=session['split'],mode=session['mode'],hour=interval['hour'],
                    risk_model=mode,activity=group,phase=phase,windows=n,
                    predicted=sum(p[key] for p in part)/n if n else None,
                    observed=sum(required_width(p['row'])<=1 for p in part)/n if n else None,
                    brier=sum((p[key]-(required_width(p['row'])<=1))**2 for p in part)/n if n else None,
                    log_loss=sum(-math.log(max(1e-9,p[key] if required_width(p['row'])<=1 else 1-p[key])) for p in part)/n if n else None,
                    over53=sum(p[key]>.53 for p in part)))
    return out


def choose(ctx,static_selection,prior_selection,engine_selection):
    scores=defaultdict(list);feasible=defaultdict(list);folds=[];models=[];risk_report=[]
    oldrule=next(r for r in RULES if r['name']==POLICIES[0])
    for sf,pf,ef in zip(static_selection['models'],prior_selection['models'],engine_selection['models']):
        begin=sf['training_days']
        if begin!=pf['training_days'] or begin!=ef['training_days']:raise ValueError('fold alignment differs')
        engine,overlay=ef['engine'],ef['overlay'];prior=pf['priors']['raw_earlier']
        bundle=fit_prefix(ctx,sf,prior,engine,overlay);model=bundle['model']
        models.append(dict(training_days=begin,**bundle))
        dates=next(r['scoring_days'] for r in static_selection['folds'] if r['training_days']==begin)
        inputs=[]
        for session in ctx['sessions']:
            if session['source']=='normalized' and session['period'] in dates:
                base=priced([p['row'] for p in session['values']],engine,overlay);floor=floor_values(base,engine)
                reference=replay(floor,prior['model'],'floor10_burst_pool120');mask=old_admit(base,oldrule)
                alternatives=all_series(floor,reference,model)
                ref=measures(session,fixed_mask(reference,mask),'reference',oldrule['name'])
                inputs.append((session,base,mask,alternatives,ref))
                risk_report.extend(dict(r,training_days=begin) for r in risk_cells(session,alternatives['retained_pool']))
        original_losses=losses([p for _,v,_,_,_ in inputs for p in v])
        for method,gate in VARIANTS:
            candidate=name(method,gate);cases=[];phases=[];refs=[];full=[]
            for s,_,mask,alternatives,ref in inputs:
                values=admit(fixed_mask(alternatives[method],mask),gate)
                cases.extend(measures(s,values,candidate,oldrule['name']));phases.extend(phase_cells(s,values,candidate,oldrule['name']))
                refs.extend(ref);full.extend(alternatives[method])
            mode_scores={};constraints={};charges={}
            for mode in ('restart','continuous'):
                part=[r for r in cases if r['mode']==mode];ref=[r for r in refs if r['mode']==mode]
                constraints[mode]=retention(part,ref);charges[mode]=availability_charge(part,ref)
                mode_scores[mode]=selection_components(part)+burst_score(part)+.5*phase_error([r for r in phases if r['mode']==mode])+charges[mode]
            loss=losses(full)
            guard=sum(100*max(0,loss[g]['pinball_ppm']/b['pinball_ppm']-1.1)
                for g,b in original_losses.items() if b['windows']>=20 and b['pinball_ppm'])
            score=mean(mode_scores.values())+.25*abs(mode_scores['restart']-mode_scores['continuous'])+guard
            scores[candidate].append(score);feasible[candidate].append(all(x['feasible'] for x in constraints.values()))
            folds.append(dict(candidate=candidate,training_days=begin,scoring_days=dates,score=score,mode_scores=mode_scores,
                retention=constraints,availability_charge=charges,loss_guard=guard,full_reference_losses=loss))
        print(f'calibrated selection {begin}',flush=True)
    ranking=sorted((dict(candidate=name(m,g),score=mean(scores[name(m,g)]),folds=scores[name(m,g)],
        availability_feasible=all(feasible[name(m,g)]),index=i) for i,(m,g) in enumerate(VARIANTS)),
        key=lambda x:(not x['availability_feasible'],x['score'],x['index']))
    before=next(r['score'] for r in static_selection['ranking'] if r['candidate']=='retained_pool:unchanged')
    after=next(r['score'] for r in ranking if r['candidate']=='retained_pool:unchanged')
    if before!=after:raise ValueError('baseline selection failed reconstruction')
    return dict(selected=ranking[0]['candidate'],ranking=ranking,folds=folds,models=models,risk_report=risk_report)


def run(previous_dir,output):
    if output.exists():raise ValueError('preserve prior experiments')
    previous=json.loads((previous_dir/'research.json').read_text());verify_code(previous_dir,previous)
    for n,k in (('predictions.jsonl.gz','predictions_sha256'),('selection.json','selection_sha256')):
        if file_hash(previous_dir/n)!=previous[k]:raise ValueError('previous artifact differs')
    ctx=load_inputs(Path(previous['previous']))
    if file_hash(Path(previous['previous'])/'research.json')!=previous['previous_sha256']:raise ValueError('previous parent differs')
    evaluated=[s for s in ctx['sessions'] if s['source']!='normalized' or s['period'] not in ctx['data']['dates'][:14]]
    declaration=dict(previous=str(previous_dir.resolve()),previous_sha256=file_hash(previous_dir/'research.json'),
        dataset=previous['dataset'],dataset_sha256=previous['dataset_sha256'],
        source_sha256={n:file_hash(Path(__file__).with_name(n)) for n in DEPENDENCIES},spec=SPEC,
        variants=[dict(pricing=m,gate=g,name=name(m,g)) for m,g in VARIANTS],availability_constraints=AVAILABILITY,
        target_survival=.48,band=[.43,.53],evaluated_sessions=len(evaluated),
        selection='Same chronological folds, objective, full-reference loss guard and 95% pooled / 90% populated-case bursty retention constraints. Calibration learns strictly earlier out-of-fold risk forecasts; online labels mature at expiry+30 seconds.',
        capture_started=False,live_candidate_promoted=False,independent_holdout=False,raw_evaluation_excluded_from_selection=True,
        frozen_and_non_bursty_pricing_and_admission_fixed=True)
    output.mkdir(parents=True);(output/'source').mkdir()
    for n in DEPENDENCIES:shutil.copyfile(Path(__file__).with_name(n),output/'source'/n)
    (output/'protocol.json').write_text(json.dumps(declaration,indent=2)+'\n')
    static_selection=json.loads((previous_dir/'selection.json').read_text())
    prior_selection=json.loads((Path(previous['previous'])/'selection.json').read_text())
    engine_selection=json.loads((ctx['prior_dir']/'selection.json').read_text())
    selection=choose(ctx,static_selection,prior_selection,engine_selection)
    (output/'selection.json').write_text(json.dumps(selection,indent=2)+'\n')
    models={};cases=[];phases=[];risk_report=[];saved={name(m,g):{p:{} for p in POLICIES} for m,g in VARIANTS};reconstructed=0
    refs={(r['candidate'],r['policy'],r['case_id'],r['activity']):r for r in previous['cases']}
    with gzip.open(output/'predictions.jsonl.gz','wt',compresslevel=5) as stream:
        for index,s in enumerate(evaluated):
            if s['source'] in ('raw_control','normalized_control','raw_extended','raw_matched'):
                key=s['period'];overlay=ctx['control']['models'][key]['overlay']
            elif s['source']=='raw':key='raw_january';overlay=ctx['rawold']['models'][s['period']]['overlays']['frozen_floor_53']['hurdle_all_120']
            else:key='original_final';overlay=ctx['pricing']['models']['hurdle_all_120']
            engine=ctx['base']['models'][key]['engine'];prior=ctx['previous']['models'][key]['raw_earlier']
            if key not in models:models[key]=fit_prefix(ctx,previous['models'][key],prior,engine,overlay)
            floor=floor_values(s['values'],engine);reference=replay(floor,prior['model'],'floor10_burst_pool120')
            alternatives=all_series(floor,reference,models[key]['model'])
            risk_report.extend(risk_cells(s,alternatives['retained_pool']))
            masks={p:old_admit(s['values'],next(r for r in RULES if r['name']==p)) for p in POLICIES}
            for method,gate in VARIANTS:
                candidate=name(method,gate)
                for policy,mask in masks.items():
                    values=admit(fixed_mask(alternatives[method],mask),gate)
                    for a,b in zip(values,reference):
                        if (a['width_ppm'] is None,a['shadow_survived'] is None)!=(b['width_ppm'] is None,b['shadow_survived'] is None):raise ValueError('reference eligibility changed')
                        if b['row']['activity_state']!='bursty' and (a['width_ppm'],a['shadow_survived'])!=(b['width_ppm'],b['shadow_survived']):raise ValueError('non-bursty price changed')
                    rows=measures(s,values,candidate,policy)
                    if method=='retained_pool' and gate in ('unchanged','static_gate'):
                        oldgate='unchanged' if gate=='unchanged' else 'preentry_floor53'
                        for c in rows:
                            ref=refs[('retained_pool:'+oldgate,policy,c['case_id'],c['activity'])]
                            for f in ('windows','survived','eligible_outcomes','mean_width_ppm','full_window_pinball_ppm'):
                                if c[f]!=ref[f]:raise ValueError('benchmark differs '+f)
                            reconstructed+=1
                    cases.extend(rows);phases.extend(phase_cells(s,values,candidate,policy))
                    saved[candidate][policy][s['id']]=[p for p in values if p['row']['activity_state']=='bursty' and p['shadow_survived'] is not None]
                    for p in values:
                        if p['row']['activity_state']=='bursty':
                            stream.write(json.dumps(dict(candidate=candidate,policy=policy,session=s['id'],start=p['row']['start'],
                                width=p['width_ppm'],shadow=p['shadow_survived'],paused=p['paused'],
                                minimum_width_survived=required_width(p['row'])<=1 if p['shadow_survived'] is not None else None,
                                static=p['risk_static'],chrono=p['risk_chrono'],context=p['risk_context'],
                                correction=p['price_correction'],requested=p['price_requested'],mass=p['local_mass'],
                                effective=p['local_effective'],risk_mass=p['risk_effective_mass']),separators=(',',':'))+'\n')
            if index%10==0:print(f'calibrated replay {index+1}/{len(evaluated)}',flush=True)
    pairs=[r for c,policies in saved.items() for p,values in policies.items() for r in paired(evaluated,values,c,p)]
    result=dict(declaration,selected=selection['selected'],ranking=selection['ranking'],models=models,cases=cases,phases=phases,
        risk_report=risk_report,paired=pairs,summary=summarize(cases),selection_sha256=file_hash(output/'selection.json'),
        predictions_sha256=file_hash(output/'predictions.jsonl.gz'),
        checks=dict(benchmark_cells_reconstructed=reconstructed,reference_eligibility_fixed=True,non_bursty_pricing_fixed=True,
            identical_paired_paths=True,calibration_prefixes_strictly_precede_their_scoring_day=True))
    for n,h in declaration['source_sha256'].items():
        if file_hash(Path(__file__).with_name(n))!=h:raise ValueError('source changed during replay')
    (output/'research.json').write_text(json.dumps(result,indent=2)+'\n')
    for n in ('cases','phases','risk_report','paired','summary'):write_csv(output/(n+'.csv'),result[n],list(result[n][0]))
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--previous',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();r=run(a.previous,a.output)
    print(json.dumps(dict(selected=r['selected'],ranking=r['ranking'],checks=r['checks']),indent=2))
