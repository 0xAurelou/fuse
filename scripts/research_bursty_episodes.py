#!/usr/bin/env python3
"""Episode-conditioned bursty research with full-day January/June raw extensions."""
import argparse
from collections import defaultdict
from datetime import datetime,timezone
import gzip
import json
from pathlib import Path
import shutil
from statistics import mean

from bursty_episodes import SPECS,fit_model,reprice
from bursty_drift import SPECS as DRIFT_SPECS,reprice as drift_reprice
from bursty_pricing import SPECS as POOL_SPECS,reprice as pool_reprice
from capture_dataset import file_hash
from investigate_capture import write_csv
from nonfrozen_pricing import fit_prior
from oracle_activity_features import load
from research_activity_calibration import fit,predict,metrics,shadow
from research_flat_pause import ENGINE_SPEC,apply_pause
from research_frozen_pricing import PAUSE,fit_overlay
from research_bursty_pricing import bases,losses,burst_score
from research_bursty_drift import DEPENDENCIES as DRIFT_DEPENDENCIES,phases,phase_score,paired_cells
from research_nonfrozen_pricing import POLICIES,measures,fixed_mask,read_sessions,selection_components,summarize,verify_raw
from research_raw_flat_panels import cell,parse_raw,prepare_rows
from research_oracle_history import observations
from research_startup_admission import priced,verify_code,day_sessions
from startup_admission import SPECS as RULES,admit

DEPENDENCIES=tuple(dict.fromkeys(('research_bursty_episodes.py','bursty_episodes.py','fetch_bursty_full_days.py')+DRIFT_DEPENDENCIES))


def evaluate(base_values,model,candidate):
    name=candidate['name']
    if candidate['comparator']:
        if name=='engine_floor10':return base_values[name]
        if name=='floor10_burst_pool120':return pool_reprice(base_values['engine_floor10'],model,next(c for c in POOL_SPECS if c['name']==name))
        return drift_reprice(base_values['engine_floor10'],model,next(c for c in DRIFT_SPECS if c['name']==name))
    return reprice(base_values['engine_floor10'],model,candidate)


def choose(rows,dates,sessions,overlay_spec):
    ranking_scores,folds,models=defaultdict(list),[],[]
    rule=next(r for r in RULES if r['name']==POLICIES[0])
    for begin,end in ((6,9),(9,12),(12,14)):
        train=[r for r in rows if r['period'] in dates[:begin]]
        engine=fit(train,ENGINE_SPEC)
        overlay=fit_overlay(apply_pause(predict(train,engine),PAUSE),overlay_spec)
        training=priced(train,engine,overlay)
        prior=fit_prior(training)
        model=fit_model(bases(training,engine,prior)['engine_floor10'])
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
        print(f'finished episode selection {begin}->{end}',flush=True)
    ranking=sorted((dict(name=c['name'],score=mean(ranking_scores[c['name']]),folds=ranking_scores[c['name']],index=i)
                    for i,c in enumerate(SPECS)),key=lambda r:(r['score'],r['index']))
    return next(c for c in SPECS if c['name']==ranking[0]['name']),ranking,folds,models



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



def episode_cells(session,values,metadata,candidate):
    starts={};initial={}
    for p in metadata:
        if p['width_ppm'] is not None and p['row']['activity_state']=='bursty':
            eid=p['episode'];starts.setdefault(eid,p['row']['start'])
            initial[p['row']['start']]=p['row']['start']-starts[eid]<60_000
    result=[]
    for interval in session['intervals']:
        part=[p for p in values if interval['start']<=p['row']['start']<interval['end'] and p['row']['start'] in initial]
        for phase in ('initial60s','after60s'):
            group=[p for p in part if initial[p['row']['start']]==(phase=='initial60s')]
            result.append(dict(candidate=candidate,case_id=f'{session["id"]}:{interval["hour"]:02}',source=session['source'],
                               period=session['period'],split=session['split'],mode=session['mode'],hour=interval['hour'],
                               phase=phase,**cell(shadow(group))))
    return result


def extend(raw,parent,control,metadata,old_sessions):
    protocol=json.loads((raw/'download-protocol.json').read_text());manifest=json.loads((raw/'download-manifest.json').read_text())
    verify_raw(dict(raw=str(raw),raw_manifest_sha256=file_hash(raw/'download-manifest.json')))
    for name,key in (('candidate-source.py','candidate_source_sha256'),('prepare-source.py','preparer_sha256'),('fetch-source.py','source_sha256')):
        if file_hash(raw/name)!=protocol[key]:raise ValueError('download source snapshot differs')
    if protocol['candidate_source_sha256']!=file_hash(Path(__file__).with_name('bursty_episodes.py')):raise ValueError('pricing changed after raw declaration')
    expected=sorted((r['path'],r['url']) for r in protocol['requests'])
    if sorted((r['path'],r['url']) for r in manifest['files'])!=expected:raise ValueError('raw request list differs')
    upstream=json.loads(Path(metadata['history']).joinpath('research.json').read_text())
    normroot=Path(upstream['source_manifest_path']).parent
    normfiles=json.loads((normroot/'download-manifest.json').read_text())['files']
    output=[];checks=[]
    for panel in protocol['panels']:
        day=panel['day'];origin=panel['start']
        files=[f for f in manifest['files'] if f['day']==day]
        observed,markers=parse_raw(files,raw)
        item=next(f for f in normfiles if f['date']==day)
        normalized,_=observations(normroot/item['path'],origin,origin+86_400_000)
        rawprices=dict(observed);shared=[(at,p) for at,p in normalized if at in rawprices]
        mismatches=sum(rawprices[at]!=p for at,p in shared)
        if mismatches:raise ValueError('raw and normalized oracle differ')
        model=control['models'][day];engine,overlay=model['engine'],model['overlay']
        daily=day_sessions(day,observed,engine,overlay,'raw_extended','extension_diagnostic',markers)
        output.extend(daily)
        old=next(s for s in old_sessions if s['source']=='raw_control' and s['period']==day and s['mode']=='restart')
        interval=old['intervals'][0];left=interval['start']-300_000;end=interval['end']
        subset=[f for f in files if left<=f['at_ms']<end]
        local,cuts=parse_raw(subset,raw)
        rows=prepare_rows(local,dict(day=day,fetch_start=left,fetch_end=end),cuts)
        fresh=priced(rows,engine,overlay)
        if len(fresh)!=len(old['values']):raise ValueError('matched fresh frame length differs')
        for a,b in zip(fresh,old['values']):
            for key in ('width_ppm','shadow_survived','paused','capped'):
                if a[key]!=b[key]:raise ValueError('matched fresh baseline differs: '+key)
            if a['row']!=b['row']:raise ValueError('matched fresh underlying rows differ')
        continuous=next(s for s in daily if s['mode']=='continuous')['values']
        for mode,values in (('restart',fresh),('continuous',continuous)):
            output.append(dict(id=f'raw_matched:{day}:{mode}',source='raw_matched',period=day,split='extension_diagnostic',mode=mode,
                               intervals=[interval],values=values))
        checks.append(dict(day=day,raw_messages=len(observed),disconnect_markers=len(markers),shared_normalized_timestamps=len(shared),
                           mismatches=mismatches,training_periods=model['training_periods'],legacy_fresh_reconstructed=True))
    return output,checks


def run(previous_dir,raw,output):
    if output.exists():raise ValueError('preserve prior experiments')
    previous=json.loads((previous_dir/'research.json').read_text());verify_code(previous_dir,previous)
    if file_hash(previous_dir/'predictions.jsonl.gz')!=previous['predictions_sha256']:raise ValueError('previous predictions differ')
    pooldir=Path(previous['previous']);pool=json.loads((pooldir/'research.json').read_text())
    if file_hash(pooldir/'research.json')!=previous['previous_sha256']:raise ValueError('pool metadata differs')
    verify_code(pooldir,pool)
    basedir=Path(pool['previous']);base=json.loads((basedir/'research.json').read_text())
    if file_hash(basedir/'research.json')!=pool['previous_sha256']:raise ValueError('base metadata differs')
    verify_code(basedir,base)
    parentdirs={n:Path(previous[n]) for n in ('admission','controls')};parents={}
    for n,d in parentdirs.items():
        if file_hash(d/'research.json')!=previous[n+'_sha256']:raise ValueError('parent metadata differs')
        parents[n]=json.loads((d/'research.json').read_text());verify_code(d,parents[n])
    parent,control=parents['admission'],parents['controls']
    original,data=load(Path(previous['dataset']))
    if file_hash(Path(previous['dataset'])/'dataset.json')!=previous['dataset_sha256']:raise ValueError('dataset differs')
    rawdir=Path(parent['raw_research']);rawold=json.loads((rawdir/'research.json').read_text())
    if file_hash(rawdir/'research.json')!=parent['raw_research_sha256']:raise ValueError('old raw research differs')
    verify_code(rawdir,rawold);verify_raw(rawold);verify_raw(control)
    pricingdir=Path(parent['pricing']);pricing=json.loads((pricingdir/'research.json').read_text())
    if file_hash(pricingdir/'research.json')!=parent['pricing_sha256']:raise ValueError('frozen pricing differs')
    verify_code(pricingdir,pricing)
    sessions=read_sessions(parentdirs['admission'],parent)+read_sessions(parentdirs['controls'],control)
    download=json.loads((raw/'download-protocol.json').read_text())
    if download['previous_sha256']!=file_hash(previous_dir/'research.json') or download['dataset_sha256']!=previous['dataset_sha256']:raise ValueError('download/pricing binding differs')
    if download['candidate_source_sha256']!=file_hash(Path(__file__).with_name('bursty_episodes.py')):raise ValueError('candidate source differs from pre-download declaration')
    protocol=dict(previous=str(previous_dir.resolve()),previous_sha256=file_hash(previous_dir/'research.json'),
                  admission=previous['admission'],admission_sha256=previous['admission_sha256'],controls=previous['controls'],controls_sha256=previous['controls_sha256'],
                  dataset=previous['dataset'],dataset_sha256=previous['dataset_sha256'],input_session_hashes=previous['input_session_hashes'],specs=SPECS,
                  raw=str(raw.resolve()),raw_manifest_sha256=file_hash(raw/'download-manifest.json'),raw_protocol_sha256=file_hash(raw/'download-protocol.json'),
                  source_sha256={n:file_hash(Path(__file__).with_name(n)) for n in DEPENDENCIES},fixed_admission=POLICIES,
                  target_survival=.48,band=(.43,.53),capture_started=False,live_candidate_promoted=False,independent_holdout=False,
                  selection=previous['selection'],raw_and_2026_failure_periods_excluded_from_selection=True,
                  repeated_inspected_periods=True,selection_objective_unchanged=True)
    output.mkdir(parents=True);(output/'source').mkdir()
    (output/'protocol.json').write_text(json.dumps(protocol,indent=2)+'\n')
    for n in DEPENDENCIES:shutil.copyfile(Path(__file__).with_name(n),output/'source'/n)
    selected,ranking,folds,inner=choose(original,data['dates'],sessions,pricing['models']['hurdle_all_120']['spec'])
    (output/'selection.json').write_text(json.dumps(dict(selected_spec=selected,ranking=ranking,folds=folds,models=inner),indent=2)+'\n')
    new_sessions,raw_checks=extend(raw,parent,control,data,sessions)
    with gzip.open(output/'extension-input-sessions.jsonl.gz','wt') as f:
        for s in new_sessions:f.write(json.dumps(s,separators=(',',':'))+'\n')
    sessions.extend(new_sessions)
    models={};cases=[];phase_cells=[];episode_phases=[];saved={c['name']:{} for c in SPECS};availability={}
    refs={(r['candidate'],r['policy'],r['case_id'],r['activity']):r for r in previous['cases']}
    def model_key(s):
        return s['period'] if s['source'] in ('raw_control','normalized_control','raw_extended','raw_matched') else 'raw_january' if s['source']=='raw' else 'original_final'
    def overlay_for(s):
        if s['source'] in ('raw_control','normalized_control','raw_extended','raw_matched'):return control['models'][s['period']]['overlay']
        if s['source']=='raw':return rawold['models'][s['period']]['overlays']['frozen_floor_53']['hurdle_all_120']
        return pricing['models']['hurdle_all_120']
    with gzip.open(output/'predictions.jsonl.gz','wt',compresslevel=5) as stream:
        for index,s in enumerate(sessions):
            key=model_key(s);bm=base['models'][key];engine,prior=bm['engine'],bm['prior']
            if key not in models:
                train=[r for r in original if r['period'] in bm['training_periods']]
                model=fit_model(bases(priced(train,engine,overlay_for(s)),engine,prior)['engine_floor10'])
                models[key]=dict(training_periods=bm['training_periods'],model=model)
            model=models[key]['model'];bs=bases(s['values'],engine,prior)
            masks={name:admit(s['values'],next(r for r in RULES if r['name']==name)) for name in POLICIES}
            episode_meta=reprice(bs['engine_floor10'],model,next(c for c in SPECS if c['name']=='episode_cdf'))
            for c in SPECS:
                values=episode_meta if c['name']=='episode_cdf' else evaluate(bs,model,c)
                for p,b in zip(values,bs['engine_floor10']):
                    if (p['width_ppm'] is None,p['shadow_survived'] is None,p['paused'])!=(b['width_ppm'] is None,b['shadow_survived'] is None,b['paused']):raise ValueError('eligibility or mask changed')
                    if b['row']['activity_state']!='bursty' and (p['width_ppm'],p['shadow_survived'])!=(b['width_ppm'],b['shadow_survived']):raise ValueError('non-bursty changed')
                    if c['directional_guard'] and b['row']['market_regime'] in ('pump','dump') and (p['width_ppm'],p['shadow_survived'])!=(b['width_ppm'],b['shadow_survived']):raise ValueError('directional guard changed')
                for policy,mask in masks.items():
                    cells=measures(s,fixed_mask(values,mask),c['name'],policy)
                    for r in cells:
                        k=(r['case_id'],r['activity'],policy);counts=tuple(r[n] for n in ('windows','eligible_outcomes','pre_entry_predictions','offered_pre_entry_decisions','grid_windows'))
                        if k in availability and availability[k]!=counts:raise ValueError('availability changed')
                        availability[k]=counts
                        if c['comparator'] and s['source'] not in ('raw_extended','raw_matched'):
                            ref=refs[(c['name'],policy,r['case_id'],r['activity'])]
                            for n in ('windows','survived','full_window_pinball_ppm','mean_width_ppm'):
                                if r[n]!=ref[n]:raise ValueError('comparator differs: '+n)
                    cases.extend(cells)
                phase_cells.extend(phases(s,values,c['name']));episode_phases.extend(episode_cells(s,values,episode_meta,c['name']))
                saved[c['name']][s['id']]=[p for p in values if p['row']['activity_state']=='bursty' and p['shadow_survived'] is not None]
                for i,p in enumerate(values):
                    stream.write(json.dumps(dict(candidate=c['name'],session=s['id'],start=p['row']['start'],width=p['width_ppm'],shadow=p['shadow_survived'],
                                                 episode=p.get('episode'),boundary=p.get('episode_boundary'),correction=p.get('episode_correction'),
                                                 effective=p.get('parent_effective'),transfer=p.get('parent_mass'),local=p.get('episode_mature'),
                                                 paused={k:v[i]['paused'] for k,v in masks.items()}),separators=(',',':'))+'\n')
            if index%10==0:print(f'replayed {index+1}/{len(sessions)} episode sessions',flush=True)
    paired=[r for c in SPECS for r in paired_cells(sessions,saved[c['name']],c['name'])]
    combined=[dict(r,source='combined_raw',split='raw_diagnostic') for r in cases if r['source'] in ('raw','raw_control')]
    extensions=[]
    for source in ('raw_extended','raw_matched'):
        rows=[dict(r,source='raw') for r in cases if r['source']==source]
        extensions.extend(dict(r,source=source) for r in joint_checks(rows))
    result=dict(protocol,selected_spec=selected,ranking=ranking,folds=folds,models=models,cases=cases,phases=phase_cells,
                episode_phases=episode_phases,paired=paired,summary=summarize(cases),combined_raw_summary=summarize(combined),
                joint_checks=joint_checks(cases),extension_checks=extensions,raw_checks=raw_checks,
                extension_inputs_sha256=file_hash(output/'extension-input-sessions.jsonl.gz'),predictions_sha256=file_hash(output/'predictions.jsonl.gz'),
                checks=dict(four_comparators_reconstructed=True,legacy_raw_restart_frames_reconstructed=True,
                            non_bursty_and_frozen_invariant=True,eligibility_masks_availability_unchanged=True,
                            identical_paired_underlying_paths=True,new_raw_excluded_from_selection=True,
                            raw_originals_and_native_receipts_reverified=True,pricing_pinned_before_raw_download=True))
    for n,h in protocol['source_sha256'].items():
        if file_hash(Path(__file__).with_name(n))!=h:raise ValueError('source changed during replay')
    (output/'research.json').write_text(json.dumps(result,indent=2)+'\n')
    for n in ('cases','phases','episode_phases','paired','summary','combined_raw_summary','joint_checks','extension_checks'):
        write_csv(output/(n.replace('_','-')+'.csv'),result[n],list(result[n][0]))
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--previous',type=Path,required=True);p.add_argument('--raw',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();r=run(a.previous,a.raw,a.output)
    print(json.dumps(dict(selected=r['selected_spec'],ranking=r['ranking'],raw_checks=r['raw_checks'],joint_checks=r['joint_checks'],extension_checks=r['extension_checks']),indent=2))
