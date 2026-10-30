#!/usr/bin/env python3
"""Bursty startup/drift comparison, with explicit restart/continuous pairing."""
import argparse
from collections import defaultdict
import gzip
import json
from pathlib import Path
import shutil
from statistics import mean

from bursty_drift import SPECS,reprice
from bursty_pricing import SPECS as OLD_SPECS,reprice as old_reprice
from capture_dataset import file_hash
from investigate_capture import write_csv
from nonfrozen_pricing import fit_prior
from oracle_activity_features import load
from research_activity_calibration import fit,predict,metrics,shadow
from research_flat_pause import ENGINE_SPEC,apply_pause
from research_frozen_pricing import PAUSE,fit_overlay
from research_bursty_pricing import (DEPENDENCIES as OLD_DEPENDENCIES,bases,fit_models,
                                    losses,burst_score)
from research_nonfrozen_pricing import (POLICIES,group,measures,fixed_mask,read_sessions,
                                       selection_components,summarize,verify_raw)
from research_raw_flat_panels import cell
from research_startup_admission import priced,verify_code
from startup_admission import SPECS as RULES,admit

DEPENDENCIES=tuple(dict.fromkeys(('research_bursty_drift.py','bursty_drift.py')+OLD_DEPENDENCIES))


def evaluate(base_values,model,candidate):
    name=candidate['name']
    if candidate['family']=='comparator':
        if name=='floor10_burst_pool120':
            return old_reprice(base_values['engine_floor10'],model,next(c for c in OLD_SPECS if c['name']==name))
        return base_values[name]
    return reprice(base_values['engine_floor10'],model,candidate)


def phases(session,values,candidate):
    result=[]
    for interval in session['intervals']:
        part=[p for p in values if interval['start']<=p['row']['start']<interval['end']
              and p['width_ppm'] is not None and p['row']['activity_state']=='bursty']
        groups=(('first4',part[:4]),('next8',part[4:12]),('first12',part[:12]),
                ('next12',part[12:24]),('after24',part[24:]),('later',part[12:]))
        for phase,part_ in groups:
            result.append(dict(candidate=candidate,case_id=f'{session["id"]}:{interval["hour"]:02}',source=session['source'],
                               period=session['period'],split=session['split'],mode=session['mode'],hour=interval['hour'],
                               phase=phase,**cell(shadow(part_))))
    return result


def phase_score(cells):
    scores=[]
    for phase in ('first12','later'):
        rows=[r for r in cells if r['phase']==phase and r['windows']]
        n=sum(r['windows'] for r in rows)
        if n:scores.append(sum(r['windows']*abs(r['error_pp']) for r in rows)/n)
    return mean(scores) if scores else 0.0


def choose(rows,dates,sessions,overlay_spec):
    ranking_scores,folds,models=defaultdict(list),[],[]
    rule=next(r for r in RULES if r['name']==POLICIES[0])
    for begin,end in ((6,9),(9,12),(12,14)):
        train=[r for r in rows if r['period'] in dates[:begin]]
        engine=fit(train,ENGINE_SPEC)
        overlay=fit_overlay(apply_pause(predict(train,engine),PAUSE),overlay_spec)
        training=priced(train,engine,overlay)
        prior=fit_prior(training)
        model=fit_models(training,engine,prior)['engine_floor10']
        models.append(dict(training_periods=dates[:begin],engine=engine,prior=prior,model=model))
        inputs=[]
        for s in sessions:
            if s['source']=='normalized' and s['period'] in dates[begin:end]:
                v=priced([p['row'] for p in s['values']],engine,overlay)
                inputs.append((s,bases(v,engine,prior),admit(v,rule)))
        baseline_losses=losses([p for _,b,_ in inputs for p in b['baseline']])
        for candidate in SPECS:
            cases,phase_cells,values=[],[],[]
            for session,b,mask in inputs:
                result=evaluate(b,model,candidate);values.extend(result)
                cases.extend(measures(session,fixed_mask(result,mask),candidate['name'],rule['name']))
                phase_cells.extend(phases(session,result,candidate['name']))
            mode_scores={mode:selection_components([r for r in cases if r['mode']==mode])
                         +burst_score([r for r in cases if r['mode']==mode])
                         +.5*phase_score([r for r in phase_cells if r['mode']==mode])
                         for mode in ('restart','continuous')}
            loss=losses(values);penalty=0.0
            for g,b in baseline_losses.items():
                if b['windows']>=20 and b['pinball_ppm']:
                    penalty+=100*max(0,loss[g]['pinball_ppm']/b['pinball_ppm']-1.1)
            score=mean(mode_scores.values())+.25*abs(mode_scores['restart']-mode_scores['continuous'])+penalty
            ranking_scores[candidate['name']].append(score)
            folds.append(dict(candidate=candidate['name'],training_days=begin,scoring_days=dates[begin:end],score=score,
                              mode_scores=mode_scores,phase_score=phase_score(phase_cells),loss_guard_penalty=penalty,
                              full_path_losses=loss,baseline_full_path_losses=baseline_losses))
        print(f'finished startup/drift selection {begin}->{end}',flush=True)
    ranking=sorted((dict(name=c['name'],score=mean(ranking_scores[c['name']]),folds=ranking_scores[c['name']],index=i)
                    for i,c in enumerate(SPECS)),key=lambda r:(r['score'],r['index']))
    return next(c for c in SPECS if c['name']==ranking[0]['name']),ranking,folds,models


def paired_cells(sessions,results,candidate):
    """Match originally eligible bursty entry timestamps; do not equate different denominators."""
    parts=defaultdict(dict)
    for s in sessions:
        vs=results[s['id']]
        for interval in s['intervals']:
            key=(s['source'],s['period'],interval['start'],interval['end'])
            parts[key][s['mode']]=[p for p in vs if interval['start']<=p['row']['start']<interval['end']
                                   and p['shadow_survived'] is not None and p['row']['activity_state']=='bursty']
    output=[]
    for (source,period,start,end),modes in parts.items():
        if set(modes)!=set(('restart','continuous')):continue
        by_mode={mode:{p['row']['start']:p for p in values} for mode,values in modes.items()}
        common=sorted(set(by_mode['restart']) & set(by_mode['continuous']))
        for at in common:
            a,b=by_mode['restart'][at]['row'],by_mode['continuous'][at]['row']
            if (a['entry'],a['move'])!=(b['entry'],b['move']):raise ValueError('paired underlying paths differ')
        a,b=([by_mode[mode][at] for at in common] for mode in ('restart','continuous'))
        ma,mb=metrics(shadow(a)),metrics(shadow(b))
        output.append(dict(candidate=candidate,source=source,period=period,start=start,end=end,
                           restart_eligible=len(modes['restart']),continuous_eligible=len(modes['continuous']),common_paths=len(common),
                           restart_survival=ma['survival'],continuous_survival=mb['survival'],
                           restart_loss=ma['pinball_ppm'],continuous_loss=mb['pinball_ppm'],
                           width_disagreements=sum(x['width_ppm']!=y['width_ppm'] for x,y in zip(a,b)),
                           absolute_survival_gap_pp=100*abs(ma['survival']-mb['survival']) if common else None))
    return output


def joint_checks(cases):
    result=[]
    for candidate in SPECS:
        for policy in POLICIES:
            for mode in ('restart','continuous'):
                rows=[r for r in cases if r['candidate']==candidate['name'] and r['policy']==policy and r['source'] in ('raw','raw_control') and r['mode']==mode]
                grouped=defaultdict(dict)
                for r in rows:grouped[r['case_id']][r['activity']]=r
                def passed(r):return r['windows']>=20 and abs(r['error_pp'])<=5
                result.append(dict(candidate=candidate['name'],policy=policy,mode=mode,cases=len(grouped),
                                   overall_pass=sum(passed(r['all']) for r in grouped.values()),
                                   non_frozen_pass=sum(passed(r['non_frozen']) for r in grouped.values()),
                                   frozen_pass=sum(passed(r['frozen']) for r in grouped.values()),
                                   bursty_relevant=sum(r['bursty']['eligible_outcomes']>=20 for r in grouped.values()),
                                   bursty_pass=sum(passed(r['bursty']) for r in grouped.values())))
    return result


def run(previous_dir,output):
    if output.exists():raise ValueError('preserve prior experiments')
    old=json.loads((previous_dir/'research.json').read_text());verify_code(previous_dir,old)
    if file_hash(previous_dir/'predictions.jsonl.gz')!=old['predictions_sha256']:raise ValueError('old predictions differ')
    base_dir=Path(old['previous']);base=json.loads((base_dir/'research.json').read_text())
    if file_hash(base_dir/'research.json')!=old['previous_sha256']:raise ValueError('base metadata differs')
    verify_code(base_dir,base)
    parent_dirs={n:Path(old[n]) for n in ('admission','controls')};parents={}
    for n,d in parent_dirs.items():
        if file_hash(d/'research.json')!=old[n+'_sha256']:raise ValueError('parent metadata differs')
        parents[n]=json.loads((d/'research.json').read_text());verify_code(d,parents[n])
    parent,control=parents['admission'],parents['controls']
    original,metadata=load(Path(old['dataset']))
    if file_hash(Path(old['dataset'])/'dataset.json')!=old['dataset_sha256']:raise ValueError('dataset differs')
    rawdir=Path(parent['raw_research']);rawold=json.loads((rawdir/'research.json').read_text())
    if file_hash(rawdir/'research.json')!=parent['raw_research_sha256']:raise ValueError('raw binding differs')
    verify_code(rawdir,rawold);verify_raw(rawold);verify_raw(control)
    pricingdir=Path(parent['pricing']);pricing=json.loads((pricingdir/'research.json').read_text())
    if file_hash(pricingdir/'research.json')!=parent['pricing_sha256']:raise ValueError('pricing differs')
    verify_code(pricingdir,pricing)
    sessions=read_sessions(parent_dirs['admission'],parent)+read_sessions(parent_dirs['controls'],control)
    protocol=dict(previous=str(previous_dir.resolve()),previous_sha256=file_hash(previous_dir/'research.json'),
                  admission=old['admission'],admission_sha256=old['admission_sha256'],controls=old['controls'],controls_sha256=old['controls_sha256'],
                  dataset=old['dataset'],dataset_sha256=old['dataset_sha256'],input_session_hashes=old['input_session_hashes'],specs=SPECS,
                  source_sha256={n:file_hash(Path(__file__).with_name(n)) for n in DEPENDENCIES},fixed_admission=POLICIES,
                  target_survival=.48,band=(.43,.53),capture_started=False,live_candidate_promoted=False,independent_holdout=False,
                  selection='Original 6/9/12 training prefixes, next 3/3/2 dates, both modes. Prior burst objective plus half of phase error: equal first12/later weights, path-weighted absolute case error within each phase. Mean mode score plus quarter absolute mode-score gap. Same-path loss guard above 10% for non-frozen/bursty/pump/dump. Equal folds and declared-order ties.',
                  raw_and_2026_failure_periods_excluded_from_selection=True,repeated_inspected_periods=True)
    output.mkdir(parents=True);(output/'source').mkdir()
    (output/'protocol.json').write_text(json.dumps(protocol,indent=2)+'\n')
    for n in DEPENDENCIES:shutil.copyfile(Path(__file__).with_name(n),output/'source'/n)
    selected,ranking,folds,inner=choose(original,metadata['dates'],sessions,pricing['models']['hurdle_all_120']['spec'])
    (output/'selection.json').write_text(json.dumps(dict(selected_spec=selected,ranking=ranking,folds=folds,models=inner),indent=2)+'\n')
    refs={(r['candidate'],r['policy'],r['case_id'],r['activity']):r for r in old['cases']}
    cases,phase_cells,paired=[],[],[]
    saved={c['name']:{} for c in SPECS}
    availability={}
    with gzip.open(output/'predictions.jsonl.gz','wt',compresslevel=5) as stream:
        for index,s in enumerate(sessions):
            key=s['period'] if s['source'] in ('raw_control','normalized_control') else 'raw_january' if s['source']=='raw' else 'original_final'
            engine,prior=base['models'][key]['engine'],base['models'][key]['prior']
            model=old['models'][key]['models']['engine_floor10']
            bs=bases(s['values'],engine,prior)
            masks={name:admit(s['values'],next(r for r in RULES if r['name']==name)) for name in POLICIES}
            for c in SPECS:
                values=evaluate(bs,model,c)
                for p,b in zip(values,bs['engine_floor10']):
                    if (p['width_ppm'] is None,p['shadow_survived'] is None,p['paused'])!=(b['width_ppm'] is None,b['shadow_survived'] is None,b['paused']):raise ValueError('eligibility or mask changed')
                    if c['family']!='comparator' and b['row']['activity_state']!='bursty' and (p['width_ppm'],p['shadow_survived'])!=(b['width_ppm'],b['shadow_survived']):raise ValueError('non-bursty changed')
                    if b['row']['activity_state']=='frozen' and (p['width_ppm'],p['shadow_survived'])!=(b['width_ppm'],b['shadow_survived']):raise ValueError('frozen changed')
                    if c['directional_guard'] and b['row']['market_regime'] in ('pump','dump') and (p['width_ppm'],p['shadow_survived'])!=(b['width_ppm'],b['shadow_survived']):raise ValueError('directional guard changed')
                for policy,mask in masks.items():
                    cells=measures(s,fixed_mask(values,mask),c['name'],policy)
                    for r in cells:
                        k=(r['case_id'],r['activity'],policy);counts=tuple(r[n] for n in ('windows','eligible_outcomes','pre_entry_predictions','offered_pre_entry_decisions','grid_windows'))
                        if k in availability and availability[k]!=counts:raise ValueError('availability changed')
                        availability[k]=counts
                        if c['family']=='comparator':
                            ref=refs[(c['name'],policy,r['case_id'],r['activity'])]
                            for n in ('windows','survived','full_window_pinball_ppm','mean_width_ppm'):
                                if r[n]!=ref[n]:raise ValueError('comparator differs: '+n)
                    cases.extend(cells)
                phase_cells.extend(phases(s,values,c['name']))
                # Keep only bursty, eligible predictions needed for identical-path pairing.
                saved[c['name']][s['id']]=[p for p in values if p['row']['activity_state']=='bursty' and p['shadow_survived'] is not None]
                for i,p in enumerate(values):
                    stream.write(json.dumps(dict(candidate=c['name'],session=s['id'],start=p['row']['start'],width=p['width_ppm'],shadow=p['shadow_survived'],
                                                 correction=p.get('drift_correction'),requested=p.get('drift_requested'),leaf=p.get('drift_leaf_mature'),parent=p.get('drift_parent_mature'),
                                                 paused={k:v[i]['paused'] for k,v in masks.items()}),separators=(',',':'))+'\n')
            if index%10==0:print(f'replayed {index+1}/{len(sessions)} startup/drift sessions',flush=True)
    for c in SPECS:paired.extend(paired_cells(sessions,saved[c['name']],c['name']))
    combined=[dict(r,source='combined_raw',split='raw_diagnostic') for r in cases if r['source'] in ('raw','raw_control')]
    result=dict(protocol,selected_spec=selected,ranking=ranking,folds=folds,cases=cases,phases=phase_cells,paired=paired,
                summary=summarize(cases),combined_raw_summary=summarize(combined),joint_checks=joint_checks(cases),
                predictions_sha256=file_hash(output/'predictions.jsonl.gz'),
                checks=dict(three_comparators_reconstructed=True,frozen_and_non_bursty_overlay_invariance=True,
                            eligibility_masks_availability_unchanged=True,identical_paired_underlying_paths=True,
                            raw_originals_and_native_receipts_reverified=True,later_and_raw_excluded_from_selection=True))
    for n,h in protocol['source_sha256'].items():
        if file_hash(Path(__file__).with_name(n))!=h:raise ValueError('source changed during replay')
    (output/'research.json').write_text(json.dumps(result,indent=2)+'\n')
    for n in ('cases','phases','paired','summary','combined_raw_summary','joint_checks'):
        write_csv(output/(n.replace('_','-')+'.csv'),result[n],list(result[n][0]))
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--previous',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    args=p.parse_args();r=run(args.previous,args.output)
    print(json.dumps(dict(selected=r['selected_spec'],ranking=r['ranking'],joint_checks=r['joint_checks']),indent=2))
