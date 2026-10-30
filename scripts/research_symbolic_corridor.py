#!/usr/bin/env python3
"""Discover bounded regime expressions on earlier OOF data; pin before diagnostics."""
import argparse
import gzip
import json
from pathlib import Path
import shutil
from statistics import mean
import time

from adaptive_corridor import required_width
from bursty_feedback import series as binary_series
from bursty_optimizer import cache_forecasts, replay as optimizer_series
from capture_dataset import file_hash
from chronological_raw_priors import floor_values, replay
from investigate_capture import write_csv
from research_bursty_optimizer import DEPENDENCIES as PARENT_DEPENDENCIES, dump, inputs_for_search
from research_bursty_pricing import losses, burst_score
from research_bursty_residual import load_cached
from research_bursty_startup_raw import phase_cells, phase_error, availability_charge, paired
from research_expanded_bursty import context
from research_nonfrozen_pricing import POLICIES, fixed_mask, measures, selection_components, summarize
from research_preentry_bursty import AVAILABILITY, retention
from research_raw_flat_panels import cell
from research_startup_admission import verify_code
from startup_admission import SPECS as RULES, admit
from symbolic_corridor import SPEC, FEATURES, features, fit, series

VARIANTS = ('retained_pool','gap_bursty','optimized','symbolic_static','symbolic_adaptive','constant_static','constant_adaptive')
STABILITY = dict(worst_fold=.25,fold_range=.25,complexity=.02)
DEPENDENCIES = tuple(dict.fromkeys(('symbolic_corridor.py','research_symbolic_corridor.py',
                                  'test_symbolic_corridor.py','audit_symbolic_corridor.py')+PARENT_DEPENDENCIES))


def load_inputs(previous_dir):
    previous=json.loads((previous_dir/'research.json').read_text()); verify_code(previous_dir,previous)
    for name,key in (('selection.json','selection_sha256'),('trials.jsonl','trials_sha256'),('predictions.jsonl.gz','predictions_sha256')):
        if file_hash(previous_dir/name)!=previous[key]: raise ValueError('optimizer artifact differs')
    residual_dir=Path(previous['previous'])
    if file_hash(residual_dir/'research.json')!=previous['previous_sha256']: raise ValueError('residual binding differs')
    residual=json.loads((residual_dir/'research.json').read_text()); verify_code(residual_dir,residual)
    for name,key in (('selection.json','selection_sha256'),('oof-residuals.jsonl.gz','oof_sha256'),
                     ('oof-bindings.json','oof_bindings_sha256'),('predictions.jsonl.gz','predictions_sha256')):
        if file_hash(residual_dir/name)!=residual[key]: raise ValueError('residual artifact differs')
    feedback_dir=Path(residual['previous'])
    if file_hash(feedback_dir/'research.json')!=residual['previous_sha256']: raise ValueError('feedback binding differs')
    feedback,expanded,ctx,checked=load_cached(feedback_dir)
    if residual['models']!=feedback['models']: raise ValueError('frozen models differ')
    with gzip.open(residual_dir/'oof-residuals.jsonl.gz','rt') as stream: records=[json.loads(line) for line in stream]
    rowmap={}
    for day in ctx['data']['dates'][:14]:
        rows=ctx['expanded_rawdays'].get(day,[r for r in ctx['original'] if r['period']==day])
        for row in rows: rowmap[(day,row['start'])]=row
    enriched=[]
    for r in records:
        if r['source']!='gap': continue
        row=rowmap[(r['row']['period'],r['row']['start'])]
        if (row['expiry'],row['activity_state'],required_width(row))!=(r['row']['expiry'],r['row']['activity_state'],r['required_width']):
            raise ValueError('OOF features and outcomes not bound to same path')
        enriched.append(dict(r,features=features(row),regime=row['market_regime']))
    return previous,residual,expanded,ctx,checked,enriched,residual_dir


def alternatives(reference,cached,prior,params,model,binary=None):
    out=dict(retained_pool=reference,
             optimized=optimizer_series(reference,cached,prior,params))
    if binary is not None: out['gap_bursty']=binary
    for candidate in VARIANTS[3:]:
        out[candidate]=series(reference,cached,model,adaptive=candidate.endswith('adaptive'),constant=candidate.startswith('constant'))
    return out


def select(folds,prefix_models,residual_selection,previous,output):
    scores={c:[] for c in VARIANTS}; feasible={c:[] for c in VARIANTS}; details=[]
    for fold in folds:
        begin=fold['training_days']; model=prefix_models[str(begin)]; cases={c:[] for c in VARIANTS}
        phases={c:[] for c in VARIANTS}; full={c:[] for c in VARIANTS}; refs=[]
        oldbundle=next(b for b in residual_selection['models'] if b['training_days']==begin)
        for item in fold['inputs']:
            ref=item['reference']; cache=item['forecasts']['gap']
            prices=alternatives(ref,cache,fold['priors']['gap'],previous['best_trial']['params'],model,
                                binary_series(ref,oldbundle['models']['gap'],'bursty'))
            refs.extend(item['refs'])
            for candidate,values in prices.items():
                masked=fixed_mask(values,item['mask']); s=item['session']
                cases[candidate].extend(measures(s,masked,candidate,POLICIES[0]))
                phases[candidate].extend(phase_cells(s,masked,candidate,POLICIES[0])); full[candidate].extend(values)
        for candidate in VARIANTS:
            mode_scores={}; constraints={}
            for mode in ('restart','continuous'):
                part=[r for r in cases[candidate] if r['mode']==mode]; ref=[r for r in refs if r['mode']==mode]
                constraints[mode]=retention(part,ref)
                mode_scores[mode]=(selection_components(part)+burst_score(part)+
                    .5*phase_error([r for r in phases[candidate] if r['mode']==mode])+availability_charge(part,ref))
            loss=losses(full[candidate])
            guard=sum(100*max(0,loss[g]['pinball_ppm']/b['pinball_ppm']-1.1)
                      for g,b in fold['baseline_loss'].items() if b['windows']>=20 and b['pinball_ppm'])
            score=mean(mode_scores.values())+.25*abs(mode_scores['restart']-mode_scores['continuous'])+guard
            scores[candidate].append(score); feasible[candidate].append(all(c['feasible'] for c in constraints.values()))
            details.append(dict(candidate=candidate,training_days=begin,scoring_days=fold['scoring_days'],
                                score=score,mode_scores=mode_scores,retention=constraints,loss_guard=guard,full_reference_losses=loss))
        for candidate in VARIANTS[:3]:
            expected=(previous['best_trial']['folds'][len(scores[candidate])-1]['score'] if candidate=='optimized' else
                      next(r for r in residual_selection['ranking'] if r['candidate']==candidate)['folds'][len(scores[candidate])-1])
            if abs(scores[candidate][-1]-expected)>1e-10: raise ValueError('preceding fold score differs: '+candidate)
        print('symbolic selection fold '+str(begin),flush=True)
    ranking=[]
    for index,candidate in enumerate(VARIANTS):
        complexity=mean(m.get('complexity',0) for m in prefix_models.values()) if candidate.startswith('symbolic') else 0.
        legacy=mean(scores[candidate]); worst=max(scores[candidate]); spread=worst-min(scores[candidate])
        score=legacy+STABILITY['worst_fold']*worst+STABILITY['fold_range']*spread+STABILITY['complexity']*complexity
        ranking.append(dict(candidate=candidate,score=score,legacy_score=legacy,worst_fold=worst,fold_range=spread,
                            mean_complexity=complexity,folds=scores[candidate],feasible=all(feasible[candidate]),index=index))
    ranking.sort(key=lambda r:(not r['feasible'],r['score'],r['index']))
    result=dict(selected=ranking[0]['candidate'],ranking=ranking,folds=details,prefix_models=prefix_models,
                stability=STABILITY,independent_holdout=False,later_diagnostics_excluded=True)
    dump(output/'selection.json',result)
    return result


def regime_cells(session,values,candidate,policy):
    out=[]
    for interval in session['intervals']:
        for regime in ('range','mixed','pump','dump'):
            part=[p for p in values if interval['start']<=p['row']['start']<interval['end'] and p['row']['market_regime']==regime]
            for activity in ('all','bursty'):
                rows=part if activity=='all' else [p for p in part if p['row']['activity_state']=='bursty']
                out.append(dict(candidate=candidate,policy=policy,case_id=f'{session["id"]}:{interval["hour"]:02}',
                                source=session['source'],period=session['period'],split=session['split'],mode=session['mode'],
                                regime=regime,activity=activity,**interval,**cell(rows)))
    return out


def diagnostics(ctx,residual,expanded,previous,models,output):
    cases=[]; phases=[]; regimes=[]
    saved={c:{p:{} for p in POLICIES} for c in VARIANTS}
    evaluated=[s for s in ctx['sessions'] if s['source']!='normalized' or s['period'] not in ctx['data']['dates'][:14]]
    old={(r['candidate'],r['policy'],r['case_id'],r['activity']):r for r in previous['cases']}
    reconstructed=0
    with gzip.open(output/'predictions.jsonl.gz','wt',compresslevel=5) as stream:
        for index,s in enumerate(evaluated):
            key,engine,_=context(ctx,s)
            ref=replay(floor_values(s['values'],engine),expanded['models'][key]['existing']['prior']['model'],'floor10_burst_pool120')
            cached=cache_forecasts(ref,{'gap':residual['models'][key]['models']['gap']})['gap']
            prices=alternatives(ref,cached,residual['residual_priors'][key]['gap'],previous['best_trial']['params'],models[key],
                                binary_series(ref,residual['models'][key]['models']['gap'],'bursty'))
            for policy in POLICIES:
                mask=admit(s['values'],next(r for r in RULES if r['name']==policy))
                for candidate,values in prices.items():
                    masked=fixed_mask(values,mask)
                    for p,b,m in zip(masked,ref,mask):
                        if (p['width_ppm'] is None,p['shadow_survived'] is None,p['paused'])!=(b['width_ppm'] is None,b['shadow_survived'] is None,m['paused']):
                            raise ValueError('eligibility or admission changed')
                        if b['row']['activity_state']!='bursty' and (p['width_ppm'],p['shadow_survived'])!=(b['width_ppm'],b['shadow_survived']):
                            raise ValueError('non-bursty pricing changed')
                    cells=measures(s,masked,candidate,policy)
                    if candidate in VARIANTS[:3]:
                        for x in cells:
                            b=old[(candidate,policy,x['case_id'],x['activity'])]
                            if any(x[f]!=b[f] for f in ('windows','survived','eligible_outcomes','mean_width_ppm','full_window_pinball_ppm')):
                                raise ValueError('preceding comparison changed')
                            reconstructed+=1
                    cases.extend(cells); phases.extend(phase_cells(s,masked,candidate,policy)); regimes.extend(regime_cells(s,masked,candidate,policy))
                    saved[candidate][policy][s['id']]=[p for p in masked if p['row']['activity_state']=='bursty' and p['shadow_survived'] is not None]
                    for p in masked:
                        if p['row']['activity_state']=='bursty':
                            stream.write(json.dumps(dict(candidate=candidate,policy=policy,session=s['id'],start=p['row']['start'],
                                width=p['width_ppm'],shadow=p['shadow_survived'],paused=p['paused'],
                                static=p.get('symbolic_static'),total=p.get('symbolic_total'),online=p.get('symbolic_online'),mature=p.get('symbolic_mature')),
                                allow_nan=False)+'\n')
            if index%10==0: print(f'symbolic diagnostics {index+1}/{len(evaluated)}',flush=True)
    pairs=[r for c,policies in saved.items() for p,values in policies.items() for r in paired(evaluated,values,c,p)]
    return dict(cases=cases,phases=phases,regimes=regimes,paired=pairs,summary=summarize(cases),
                evaluated_sessions=len(evaluated),evaluated_intervals=sum(len(s['intervals']) for s in evaluated),
                preceding_comparison_cells_reconstructed=reconstructed)


def run(previous_dir,output):
    if output.exists(): raise ValueError('preserve prior archives; choose a new output directory')
    if SPEC['source']!='gap': raise ValueError('this protocol binds the preceding gap candidate')
    protocol=dict(previous=str(previous_dir.resolve()),previous_sha256=file_hash(previous_dir/'research.json'),
        source_sha256={n:file_hash(Path(__file__).with_name(n)) for n in DEPENDENCIES},spec=SPEC,
        variants=VARIANTS,stability=STABILITY,availability_constraints=AVAILABILITY,target_survival=.48,band=[.43,.53],
        implementation='Local bounded symbolic basis search with beam mutations and quantile-fitted coefficients; NumPy only, not PySR',
        selection='Earlier OOF bursty residuals only. Inner last-quarter dates select grammar/complexity, coefficients refit on allowed dates. Outer existing prefix scores plus worst-fold/range/complexity penalty. Preceding optimizer parameters fixed as a control. Later panels are repeatedly inspected development diagnostics.',
        capture_started=False,live_candidate_promoted=False,independent_holdout=False,
        admission_and_non_bursty_pricing_fixed=True)
    output.mkdir(parents=True); (output/'source').mkdir()
    for n in DEPENDENCIES: shutil.copyfile(Path(__file__).with_name(n),output/'source'/n)
    dump(output/'protocol.json',protocol); started=time.monotonic()
    previous,residual,expanded,ctx,checked,records,residual_dir=load_inputs(previous_dir)
    if previous['best_trial']['params']['source']!='gap': raise ValueError('control requires gap source')
    with gzip.open(output/'symbolic-training.jsonl.gz','wt',compresslevel=5) as stream:
        for row in records: stream.write(json.dumps(row,allow_nan=False)+'\n')
    residual_selection=json.loads((residual_dir/'selection.json').read_text())
    engine_selection=json.loads((ctx['prior_dir']/'selection.json').read_text())
    folds=inputs_for_search(ctx,residual_selection,engine_selection)
    prefix_models={}
    for bundle in residual_selection['models']:
        begin=str(bundle['training_days']); prefix_models[begin]=fit(records,bundle['training_periods'],bundle['cutoff'])
        print('symbolic structure fit prefix '+begin,flush=True)
    chosen=select(folds,prefix_models,residual_selection,previous,output)
    models={}
    for key,bundle in residual['models'].items():
        models[key]=fit(records,bundle['training_periods'],bundle['cutoff'])
        print('symbolic structure fit outer '+key,flush=True)
    dump(output/'models.json',models)
    pinned=file_hash(output/'selection.json'); model_hash=file_hash(output/'models.json')
    print('symbolic shortlist and models pinned before later diagnostics',flush=True)
    diagnostic=diagnostics(ctx,residual,expanded,previous,models,output)
    if file_hash(output/'selection.json')!=pinned or file_hash(output/'models.json')!=model_hash:
        raise ValueError('selection or formula changed during diagnostics')
    for name,digest in protocol['source_sha256'].items():
        if file_hash(Path(__file__).with_name(name))!=digest: raise ValueError('source changed during experiment')
    result=dict(protocol,selected=chosen['selected'],ranking=chosen['ranking'],models=models,
                selection_sha256=pinned,models_sha256=model_hash,training_sha256=file_hash(output/'symbolic-training.jsonl.gz'),
                predictions_sha256=file_hash(output/'predictions.jsonl.gz'),feature_records_verified=checked,
                elapsed_seconds=time.monotonic()-started,**diagnostic)
    dump(output/'research.json',result)
    for name in ('cases','phases','regimes','paired','summary'): write_csv(output/(name+'.csv'),result[name],list(result[name][0]))
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__); parser.add_argument('--previous',type=Path,required=True); parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args(); r=run(args.previous,args.output)
    print(json.dumps(dict(selected=r['selected'],ranking=r['ranking'],elapsed_seconds=r['elapsed_seconds']),indent=2))
