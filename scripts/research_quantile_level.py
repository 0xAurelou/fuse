#!/usr/bin/env python3
"""Pin an earlier-fold choice before testing residual-CDF survival feedback."""
import argparse
import gzip
import json
from pathlib import Path
import shutil
from statistics import mean
import time

from adaptive_corridor import required_width
from bursty_optimizer import cache_forecasts
from capture_dataset import file_hash
from chronological_raw_priors import floor_values, replay
from investigate_capture import write_csv
from quantile_level_control import SPEC, VARIANTS, all_series
from research_bursty_optimizer import dump, inputs_for_search
from research_bursty_pricing import losses, burst_score
from research_bursty_startup_raw import phase_cells, phase_error, availability_charge, paired
from research_expanded_bursty import context
from research_nonfrozen_pricing import POLICIES, fixed_mask, measures, selection_components, summarize
from research_pooled_symbolic import load_inputs, DEPENDENCIES as PARENT_DEPENDENCIES
from research_preentry_bursty import AVAILABILITY, retention
from research_symbolic_corridor import regime_cells
from startup_admission import SPECS as RULES, admit

DEPENDENCIES = tuple(dict.fromkeys(('quantile_level_control.py','research_quantile_level.py',
                                  'test_quantile_level_control.py')+PARENT_DEPENDENCIES))


def select(folds, params, residual_selection, previous, output):
    details = []
    for fold in folds:
        cases = {c:[] for c in VARIANTS}; phases = {c:[] for c in VARIANTS}
        full = {c:[] for c in VARIANTS}; refs = []
        for item in fold['inputs']:
            refs.extend(item['refs'])
            alternatives = all_series(item['reference'],item['forecasts'][params['source']],
                                      fold['priors'][params['source']],params)
            for candidate,values in alternatives.items():
                masked = fixed_mask(values,item['mask']); s = item['session']
                cases[candidate].extend(measures(s,masked,candidate,POLICIES[0]))
                phases[candidate].extend(phase_cells(s,masked,candidate,POLICIES[0]))
                full[candidate].extend(values)
        for candidate in VARIANTS:
            mode_scores, constraints = {}, {}
            for mode in ('restart','continuous'):
                part = [r for r in cases[candidate] if r['mode']==mode]
                ref = [r for r in refs if r['mode']==mode]
                constraints[mode] = retention(part,ref)
                mode_scores[mode] = (selection_components(part)+burst_score(part)+
                    .5*phase_error([r for r in phases[candidate] if r['mode']==mode])+availability_charge(part,ref))
            loss = losses(full[candidate])
            guard = sum(100*max(0,loss[g]['pinball_ppm']/b['pinball_ppm']-1.1)
                        for g,b in fold['baseline_loss'].items() if b['windows']>=20 and b['pinball_ppm'])
            score = mean(mode_scores.values())+.25*abs(mode_scores['restart']-mode_scores['continuous'])+guard
            details.append(dict(candidate=candidate,training_days=fold['training_days'],scoring_days=fold['scoring_days'],
                score=score,mode_scores=mode_scores,retention=constraints,loss_guard=guard,full_reference_losses=loss))
        print('CDF level selection fold '+str(fold['training_days']),flush=True)
    ranking = []
    for candidate in VARIANTS:
        rows = [r for r in details if r['candidate']==candidate]
        scores = [r['score'] for r in rows]
        ranking.append(dict(candidate=candidate,score=mean(scores),folds=scores,worst_fold=max(scores),
            feasible=all(x['feasible'] for r in rows for x in r['retention'].values())))
        expected = (previous['best_trial']['folds'] if candidate=='optimized' else None)
        if expected is not None and any(abs(a-b['score'])>1e-10 for a,b in zip(scores,expected)):
            raise ValueError('previous Bayesian fold score differs')
        if candidate=='retained_pool':
            expected = next(r for r in residual_selection['ranking'] if r['candidate']==candidate)
            if abs(ranking[-1]['score']-expected['score'])>1e-10:
                raise ValueError('retained selection score differs')
    ranking.sort(key=lambda r:(not r['feasible'],r['score'],VARIANTS.index(r['candidate'])))
    result = dict(selected=ranking[0]['candidate'],ranking=ranking,folds=details,
                  params=params,later_diagnostics_excluded=True,independent_holdout=False)
    dump(output/'selection.json',result)
    return result


def diagnostics(ctx,residual,expanded,previous,params,output):
    cases,phases,regimes,bounds = [],[],[],[]
    saved = {c:{p:{} for p in POLICIES} for c in VARIANTS}
    old = {(r['candidate'],r['policy'],r['case_id'],r['activity']):r for r in previous['cases']}
    evaluated = [s for s in ctx['sessions'] if s['source']!='normalized' or s['period'] not in ctx['data']['dates'][:14]]
    reconstructed = 0
    with gzip.open(output/'predictions.jsonl.gz','wt',compresslevel=5) as stream:
        for index,s in enumerate(evaluated):
            key,engine,_ = context(ctx,s)
            reference = replay(floor_values(s['values'],engine),expanded['models'][key]['existing']['prior']['model'],'floor10_burst_pool120')
            cache = cache_forecasts(reference,{params['source']:residual['models'][key]['models'][params['source']]})[params['source']]
            alternatives = all_series(reference,cache,residual['residual_priors'][key][params['source']],params)
            for policy in POLICIES:
                mask = admit(s['values'],next(r for r in RULES if r['name']==policy))
                for candidate,prices in alternatives.items():
                    values = fixed_mask(prices,mask)
                    for p,b,m in zip(values,reference,mask):
                        if (p['width_ppm'] is None,p['shadow_survived'] is None,p['paused']) != (b['width_ppm'] is None,b['shadow_survived'] is None,m['paused']):
                            raise ValueError('eligibility/admission changed')
                        if b['row']['activity_state']!='bursty' and (p['width_ppm'],p['shadow_survived'])!=(b['width_ppm'],b['shadow_survived']):
                            raise ValueError('non-bursty prices changed')
                    cells = measures(s,values,candidate,policy)
                    if candidate in ('retained_pool','optimized'):
                        for cell in cells:
                            prior = old[(candidate,policy,cell['case_id'],cell['activity'])]
                            if any(cell[f]!=prior[f] for f in ('windows','survived','eligible_outcomes','mean_width_ppm','full_window_pinball_ppm')):
                                raise ValueError('preceding control differs')
                            reconstructed += 1
                    cases.extend(cells);phases.extend(phase_cells(s,values,candidate,policy))
                    regimes.extend(regime_cells(s,values,candidate,policy))
                    saved[candidate][policy][s['id']] = [p for p in values if p['row']['activity_state']=='bursty' and p['shadow_survived'] is not None]
                    for p,q in zip(values,cache):
                        if p['row']['activity_state']!='bursty':continue
                        stream.write(json.dumps(dict(candidate=candidate,policy=policy,session=s['id'],start=p['row']['start'],
                            width=p['width_ppm'],shadow=p['shadow_survived'],paused=p['paused'],
                            level=p.get('cdf_level'),correction=p.get('cdf_correction',p.get('optimizer_correction')),
                            evidence=p.get('cdf_evidence',p.get('optimizer_evidence')),
                            correction_bound=p.get('cdf_bound'),level_bound=p.get('cdf_level_bound'),
                            forecast=q[0] if q is not None else None,
                            required=required_width(p['row']) if p['row']['valid'] else None),allow_nan=False)+'\n')
            # These are hindsight bounds on price reachability, never predictors.
            for interval in s['intervals']:
                part = [(p,q) for p,q in zip(reference,cache) if interval['start']<=p['row']['start']<interval['end']
                        and p['width_ppm'] is not None and p['row']['activity_state']=='bursty']
                for phase,group in (('all',part),('first12',part[:12]),('later',part[12:])):
                    rows = [(p,q) for p,q in group if p['row']['valid'] and q is not None]
                    bounds.append(dict(source=s['source'],period=s['period'],mode=s['mode'],hour=interval['hour'],phase=phase,
                        supported=len(rows),minimum_width_survivors=sum(required_width(p['row'])<=1 for p,q in rows),
                        forecast_at_minimum=sum(q[0]==1 for p,q in rows),
                        reachable_at_fourfold=sum(required_width(p['row'])<=min(50000,4*q[0]) for p,q in rows)))
            if index%10==0:print(f'CDF level diagnostics {index+1}/{len(evaluated)}',flush=True)
    pairs = [r for c,policies in saved.items() for p,values in policies.items() for r in paired(evaluated,values,c,p)]
    return dict(cases=cases,phases=phases,regimes=regimes,reachability=bounds,paired=pairs,
                summary=summarize(cases),evaluated_sessions=len(evaluated),reconstructed_control_cells=reconstructed)


def run(previous_dir,output):
    if output.exists():raise ValueError('preserve prior experiments; choose a new output')
    started = time.monotonic()
    protocol = dict(previous=str(previous_dir.resolve()),previous_sha256=file_hash(previous_dir/'research.json'),
        source_sha256={n:file_hash(Path(__file__).with_name(n)) for n in DEPENDENCIES},spec=SPEC,variants=VARIANTS,
        target_survival=.48,band=[.43,.53],availability_constraints=AVAILABILITY,capture_started=False,
        live_candidate_promoted=False,independent_holdout=False,admission_and_non_bursty_prices_fixed=True,
        selection='Same earlier 6/9/12-date prefixes and original score/loss guards. Previous Bayesian parameters frozen. Select gain/bounds on earlier folds, pin before later diagnostics. No later-date retuning.',
        references=['https://arxiv.org/abs/2106.00170','https://arxiv.org/abs/2307.16895'],
        warning='Clipped levels, bounded/discrete widths, delayed labels and regime filtering do not inherit ACI guarantees. Later dates are repeatedly inspected development data.')
    output.mkdir(parents=True);(output/'source').mkdir()
    for name in DEPENDENCIES:shutil.copyfile(Path(__file__).with_name(name),output/'source'/name)
    dump(output/'protocol.json',protocol)
    previous,residual,expanded,ctx,checked,_,residual_dir = load_inputs(previous_dir)
    params = previous['best_trial']['params']
    selection = json.loads((residual_dir/'selection.json').read_text())
    folds = inputs_for_search(ctx,selection,json.loads((ctx['prior_dir']/'selection.json').read_text()))
    chosen = select(folds,params,selection,previous,output)
    pinned = file_hash(output/'selection.json')
    print('CDF level choice pinned before later diagnostics',flush=True)
    diagnostic = diagnostics(ctx,residual,expanded,previous,params,output)
    if file_hash(output/'selection.json')!=pinned:raise ValueError('selection changed')
    for name,digest in protocol['source_sha256'].items():
        if file_hash(Path(__file__).with_name(name))!=digest:raise ValueError('source changed during experiment')
    result = dict(protocol,selected=chosen['selected'],ranking=chosen['ranking'],params=params,
        selection_sha256=pinned,predictions_sha256=file_hash(output/'predictions.jsonl.gz'),
        feature_records_verified=checked,elapsed_seconds=time.monotonic()-started,**diagnostic)
    dump(output/'research.json',result)
    for name in ('cases','phases','regimes','reachability','paired','summary'):
        write_csv(output/(name+'.csv'),result[name],list(result[name][0]))
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--previous',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    args=p.parse_args();r=run(args.previous,args.output)
    print(json.dumps(dict(selected=r['selected'],ranking=r['ranking'],elapsed_seconds=r['elapsed_seconds']),indent=2))
