#!/usr/bin/env python3
"""Earlier raw priors and startup admission, with full and offered-path evidence."""
import argparse
from collections import defaultdict
import gzip
import json
from pathlib import Path
import shutil
from statistics import mean

from bursty_startup_admission import SPECS,admit
from capture_dataset import file_hash
from chronological_raw_priors import fit_bundle,floor_values,replay
from investigate_capture import write_csv
from oracle_activity_features import load
from research_activity_calibration import metrics,shadow
from research_bursty_pricing import losses,burst_score
from research_chronological_raw_priors import DEPENDENCIES as PRIOR_DEPENDENCIES
from research_nonfrozen_pricing import POLICIES,read_sessions,fixed_mask,measures,selection_components,summarize,verify_raw
from research_oracle_history import observations
from research_raw_flat_panels import parse_raw,prepare_rows,cell
from research_startup_admission import priced,verify_code
from startup_admission import SPECS as OLD_RULES,admit as old_admit

PRICING='floor10_burst_pool120'
VARIANTS=tuple((source,rule['name']) for source in ('normalized','raw_earlier') for rule in SPECS)+(('raw_two','unchanged'),)
DEPENDENCIES=tuple(dict.fromkeys(('bursty_startup_admission.py','research_bursty_startup_raw.py',
    'test_bursty_startup_admission.py','test_bursty_startup_raw_research.py','fetch_earlier_bursty_training.py')+PRIOR_DEPENDENCIES))


def name(source,rule):return source+':'+rule


def phase_cells(session,values,candidate,policy):
    """Entry-rank groups stay fixed when paths become refused or censored."""
    output=[]
    for interval in session['intervals']:
        part=[p for p in values if interval['start']<=p['row']['start']<interval['end']
              and p['width_ppm'] is not None and p['row']['activity_state']=='bursty']
        for phase,group in (('first12',part[:12]),('later',part[12:])):
            output.append(dict(candidate=candidate,policy=policy,case_id=f'{session["id"]}:{interval["hour"]:02}',
                source=session['source'],period=session['period'],split=session['split'],mode=session['mode'],
                hour=interval['hour'],phase=phase,**cell(group)))
    return output


def phase_error(cells):
    result=[]
    for phase in ('first12','later'):
        rows=[r for r in cells if r['phase']==phase and r['eligible_outcomes']]
        n=sum(r['eligible_outcomes'] for r in rows)
        if n:result.append(sum(r['eligible_outcomes']*(abs(r['error_pp']) if r['windows'] else 52)
                               for r in rows)/n)
    return mean(result) if result else 0.0


def availability_charge(cases,reference):
    """Charge incremental refusals and cells that become too small to assess."""
    baseline={(r['case_id'],r['activity']):r for r in reference}
    reductions=defaultdict(list);small=[]
    for r in cases:
        if r['activity'] not in ('all','bursty'):continue
        b=baseline[(r['case_id'],r['activity'])]
        if b['windows']:
            reductions[r['activity']].append(1-r['windows']/b['windows'])
        if r['activity']=='bursty' and b['windows']>=20:small.append(r['windows']<20)
    all_drop=reductions['all'];burst_drop=reductions['bursty']
    return (25*(mean(all_drop) if all_drop else 0)+25*(mean(burst_drop) if burst_drop else 0)
        +100*max(0,max(all_drop,default=0)-.15)+50*(mean(small) if small else 0))


def paired(sessions,results,candidate,policy):
    parts=defaultdict(dict);output=[]
    for session in sessions:
        for interval in session['intervals']:
            k=(session['source'],session['period'],interval['start'],interval['end'])
            parts[k][session['mode']]={p['row']['start']:p for p in results[session['id']]
                if interval['start']<=p['row']['start']<interval['end']}
    for (source,day,start,end),modes in parts.items():
        if set(modes)!=set(('restart','continuous')):continue
        common=sorted(set(modes['restart']) & set(modes['continuous']))
        a,b=([modes[m][at] for at in common] for m in ('restart','continuous'))
        if any((x['row']['entry'],x['row']['move'])!=(y['row']['entry'],y['row']['move']) for x,y in zip(a,b)):
            raise ValueError('paired underlying paths differ')
        both=[at for at in common if not modes['restart'][at]['paused'] and not modes['continuous'][at]['paused']]
        ma,mb=metrics(a),metrics(b)
        aa,bb=(metrics([modes[m][at] for at in both]) for m in ('restart','continuous'))
        output.append(dict(candidate=candidate,policy=policy,source=source,period=day,start=start,end=end,
            restart_eligible=len(modes['restart']),continuous_eligible=len(modes['continuous']),common_paths=len(common),
            restart_offered_common=ma['windows'],continuous_offered_common=mb['windows'],
            restart_survival=ma['survival'],continuous_survival=mb['survival'],
            both_offered=len(both),restart_both_survival=aa['survival'],continuous_both_survival=bb['survival'],
            pause_disagreements=sum(x['paused']!=y['paused'] for x,y in zip(a,b)),
            width_disagreements=sum(x['width_ppm']!=y['width_ppm'] for x,y in zip(a,b))))
    return output


def choose(original,allraw,sessions,previous_selection):
    scores=defaultdict(list);folds=[];models=[]
    oldrule=next(r for r in OLD_RULES if r['name']==POLICIES[0])
    for index,fold in enumerate(previous_selection['models']):
        engine,overlay=fold['engine'],fold['overlay'];p=fold['priors']['normalized']
        fitting=dict(normalized=p,raw_two=fold['priors']['raw_replacement'],
            raw_earlier=fit_bundle(original,allraw,p['training_periods'],p['cutoff'],engine,overlay,True))
        dates=next(r['scoring_days'] for r in previous_selection['folds'] if r['training_days']==fold['training_days'])
        models.append(dict(training_days=fold['training_days'],priors=fitting))
        inputs=[]
        for s in sessions:
            if s['source']=='normalized' and s['period'] in dates:
                v=priced([p['row'] for p in s['values']],engine,overlay);base=floor_values(v,engine)
                mask=old_admit(v,oldrule)
                prices={source:replay(base,b['model'],PRICING) for source,b in fitting.items()}
                baseline=measures(s,fixed_mask(prices['normalized'],mask),'reference',oldrule['name'])
                inputs.append((s,v,mask,prices,baseline))
        baseline_losses=losses([p for _,v,_,_,_ in inputs for p in v])
        for source,rulename in VARIANTS:
            candidate=name(source,rulename);rule=next(r for r in SPECS if r['name']==rulename)
            cases=[];phases=[];refs=[];full=[]
            for s,_,mask,prices,baseline in inputs:
                values=admit(fixed_mask(prices[source],mask),rule,fitting[source]['model'])
                cases.extend(measures(s,values,candidate,oldrule['name']))
                phases.extend(phase_cells(s,values,candidate,oldrule['name']))
                refs.extend(baseline);full.extend(prices[source])
            mode_scores={};charges={}
            for mode in ('restart','continuous'):
                part=[r for r in cases if r['mode']==mode];ref=[r for r in refs if r['mode']==mode]
                charges[mode]=availability_charge(part,ref)
                mode_scores[mode]=(selection_components(part)+burst_score(part)
                    +.5*phase_error([r for r in phases if r['mode']==mode])+charges[mode])
            loss=losses(full)
            penalty=sum(100*max(0,loss[g]['pinball_ppm']/b['pinball_ppm']-1.1)
                for g,b in baseline_losses.items() if b['windows']>=20 and b['pinball_ppm'])
            score=mean(mode_scores.values())+.25*abs(mode_scores['restart']-mode_scores['continuous'])+penalty
            scores[candidate].append(score)
            folds.append(dict(candidate=candidate,training_days=fold['training_days'],scoring_days=dates,score=score,
                mode_scores=mode_scores,availability_charge=charges,loss_guard=penalty,full_reference_losses=loss))
        print(f'earlier raw admission selection fold {index+1}/3',flush=True)
    ranking=sorted((dict(candidate=name(s,g),score=mean(scores[name(s,g)]),folds=scores[name(s,g)],index=i)
        for i,(s,g) in enumerate(VARIANTS)),key=lambda r:(r['score'],r['index']))
    old=next(r for r in previous_selection['ranking'] if r['candidate']=='normalized:'+PRICING)
    baseline=next(r for r in ranking if r['candidate']=='normalized:unchanged')
    if baseline['score']!=old['score']:raise ValueError('unchanged earlier objective failed reconstruction')
    return dict(selected=ranking[0]['candidate'],ranking=ranking,folds=folds,models=models)


def run(previous_dir,raw,output):
    if output.exists():raise ValueError('preserve prior experiments')
    previous=json.loads((previous_dir/'research.json').read_text());verify_code(previous_dir,previous)
    if file_hash(previous_dir/'predictions.jsonl.gz')!=previous['predictions_sha256']:raise ValueError('previous predictions differ')
    if file_hash(previous_dir/'selection.json')!=previous['selection_sha256']:raise ValueError('previous selection differs')
    episode_dir=Path(previous['previous']);episodes=json.loads((episode_dir/'research.json').read_text());verify_code(episode_dir,episodes)
    if file_hash(episode_dir/'research.json')!=previous['previous_sha256']:raise ValueError('episode ancestor differs')
    parents={}
    for key in ('admission','controls'):
        d=Path(episodes[key]);m=json.loads((d/'research.json').read_text());verify_code(d,m)
        if file_hash(d/'research.json')!=episodes[key+'_sha256']:raise ValueError('input ancestor differs')
        parents[key]=m
    sessions=read_sessions(Path(episodes['admission']),parents['admission'])+read_sessions(Path(episodes['controls']),parents['controls'])
    if file_hash(episode_dir/'extension-input-sessions.jsonl.gz')!=episodes['extension_inputs_sha256']:raise ValueError('extended cache differs')
    with gzip.open(episode_dir/'extension-input-sessions.jsonl.gz','rt') as f:extension=[json.loads(line) for line in f]
    sessions+=extension
    rawdays={s['period']:[p['row'] for p in s['values']] for s in extension if s['source']=='raw_extended' and s['mode']=='continuous'}
    verify_raw(dict(raw=episodes['raw'],raw_manifest_sha256=episodes['raw_manifest_sha256']))
    protocol=json.loads((raw/'download-protocol.json').read_text())
    if protocol['previous_sha256']!=file_hash(previous_dir/'research.json'):raise ValueError('download ancestor differs')
    if protocol['admission_specs']!=json.loads(json.dumps(SPECS)):raise ValueError('admission changed after declaration')
    for n,k in (('admission-source.py','admission_source_sha256'),('fetch-source.py','source_sha256'),('prepare-source.py','preparer_sha256')):
        if file_hash(raw/n)!=protocol[k]:raise ValueError('download snapshot differs')
    if file_hash(Path(__file__).with_name('bursty_startup_admission.py'))!=protocol['admission_source_sha256']:
        raise ValueError('admission code changed after download declaration')
    verify_raw(dict(raw=str(raw),raw_manifest_sha256=file_hash(raw/'download-manifest.json')))
    manifest=json.loads((raw/'download-manifest.json').read_text())
    if sorted((r['path'],r['url']) for r in manifest['files'])!=sorted((r['path'],r['url']) for r in protocol['requests']):
        raise ValueError('download requests differ')
    original,data=load(Path(previous['dataset']))
    if file_hash(Path(previous['dataset'])/'dataset.json')!=previous['dataset_sha256']:raise ValueError('dataset differs')
    admission,control=parents['admission'],parents['controls']
    verify_raw(control)
    rawold_dir=Path(admission['raw_research']);rawold=json.loads((rawold_dir/'research.json').read_text());verify_code(rawold_dir,rawold);verify_raw(rawold)
    pricing_dir=Path(admission['pricing']);pricing=json.loads((pricing_dir/'research.json').read_text());verify_code(pricing_dir,pricing)
    for d,h in ((rawold_dir,admission['raw_research_sha256']),(pricing_dir,admission['pricing_sha256'])):
        if file_hash(d/'research.json')!=h:raise ValueError('pricing ancestor differs')
    ancestor=episodes
    for _ in range(3):
        d=Path(ancestor['previous']);m=json.loads((d/'research.json').read_text());verify_code(d,m)
        if file_hash(d/'research.json')!=ancestor['previous_sha256']:raise ValueError('engine ancestor differs')
        ancestor=m
    base=ancestor
    evaluated=[s for s in sessions if s['source']!='normalized' or s['period'] not in data['dates'][:14]]
    declaration=dict(previous=str(previous_dir.resolve()),previous_sha256=file_hash(previous_dir/'research.json'),
        dataset=previous['dataset'],dataset_sha256=previous['dataset_sha256'],raw=str(raw.resolve()),
        raw_manifest_sha256=file_hash(raw/'download-manifest.json'),raw_protocol_sha256=file_hash(raw/'download-protocol.json'),
        source_sha256={n:file_hash(Path(__file__).with_name(n)) for n in DEPENDENCIES},
        specs=SPECS,variants=[dict(source=s,rule=g,name=name(s,g)) for s,g in VARIANTS],pricing_method=PRICING,
        prior_sources=dict(normalized='original normalized training dates',raw_two='previous January/June 2025 raw replacements',
                           raw_earlier='November/December 2024 plus January/June 2025 raw replacements'),
        target_survival=.48,band=[.43,.53],policies=POLICIES,evaluated_sessions=len(evaluated),
        capture_started=False,live_candidate_promoted=False,independent_holdout=False,
        selection='Original chronological folds and objective, offered phase error weighted by original eligible paths (empty phase 52pp); incremental availability charge 25*mean all refusal +25*mean burst refusal +100*max(0,worst all refusal-.15) +50*share formerly >=20 bursty cells made too small. Same full-reference pricing loss guard.',
        raw_evaluation_excluded_from_selection=True,admission_declared_before_download=True)
    output.mkdir(parents=True);(output/'source').mkdir()
    for n in DEPENDENCIES:shutil.copyfile(Path(__file__).with_name(n),output/'source'/n)
    (output/'protocol.json').write_text(json.dumps(declaration,indent=2)+'\n')
    upstream=json.loads((Path(data['history'])/'research.json').read_text());normroot=Path(upstream['source_manifest_path']).parent
    normfiles=json.loads((normroot/'download-manifest.json').read_text())['files']
    rawchecks=[];early={}
    for panel in protocol['panels']:
        day=panel['day'];files=sorted((f for f in manifest['files'] if f['day']==day),key=lambda f:f['at_ms'])
        observed,markers=parse_raw(files,raw);rows=prepare_rows(observed,panel,markers)
        early[day]=rows;rawdays[day]=rows
        normalfile=next(f for f in normfiles if f['date']==day)
        normalized,_=observations(normroot/normalfile['path'],panel['start'],panel['end']);prices=dict(observed)
        common=[(at,p) for at,p in normalized if at in prices];mismatch=sum(prices[at]!=p for at,p in common)
        if mismatch:raise ValueError('raw/normalized training oracle differs')
        rawchecks.append(dict(day=day,minutes=len(files),messages=len(observed),disconnect_markers=len(markers),
            shared_timestamps=len(common),mismatches=mismatch,rows=len(rows),
            normalized_bursty=sum(r['period']==day and r['valid'] and r['activity_state']=='bursty' for r in original),
            raw_bursty=sum(r['valid'] and r['activity_state']=='bursty' for r in rows)))
    with gzip.open(output/'earlier-training-rows.jsonl.gz','wt') as f:
        for day in sorted(early):
            for row in early[day]:f.write(json.dumps(row,separators=(',',':'))+'\n')
    oldselection=json.loads((previous_dir/'selection.json').read_text())
    selection=choose(original,rawdays,sessions,oldselection)
    (output/'selection.json').write_text(json.dumps(selection,indent=2)+'\n')
    print('earlier raw checks '+json.dumps(rawchecks),flush=True)
    models={};cases=[];phases=[];saved={name(s,g):{p:{} for p in POLICIES} for s,g in VARIANTS};reconstructed=0
    refs={(r['candidate'],r['policy'],r['case_id'],r['activity']):r for r in previous['cases']}
    rules={r['name']:r for r in SPECS}
    with gzip.open(output/'predictions.jsonl.gz','wt',compresslevel=5) as stream:
        for index,s in enumerate(evaluated):
            if s['source'] in ('raw_control','normalized_control','raw_extended','raw_matched'):
                key=s['period'];overlay=control['models'][key]['overlay']
            elif s['source']=='raw':key='raw_january';overlay=rawold['models'][s['period']]['overlays']['frozen_floor_53']['hurdle_all_120']
            else:key='original_final';overlay=pricing['models']['hurdle_all_120']
            bm=base['models'][key];engine=bm['engine']
            if key not in models:
                oldmodels=previous['models'][key];p=oldmodels['normalized']
                models[key]=dict(normalized=p,raw_two=oldmodels['raw_replacement'],
                    raw_earlier=fit_bundle(original,rawdays,bm['training_periods'],p['cutoff'],engine,overlay,True))
            floor=floor_values(s['values'],engine)
            prices={source:replay(floor,b['model'],PRICING) for source,b in models[key].items()}
            masks={p:old_admit(s['values'],next(r for r in OLD_RULES if r['name']==p)) for p in POLICIES}
            for source,gate in VARIANTS:
                candidate=name(source,gate)
                for policy,mask in masks.items():
                    initial=fixed_mask(prices[source],mask);values=admit(initial,rules[gate],models[key][source]['model'])
                    for a,b in zip(values,initial):
                        if (a['width_ppm'],a['shadow_survived'])!=(b['width_ppm'],b['shadow_survived']):raise ValueError('admission changed prices/outcomes')
                        if b['paused'] and not a['paused']:raise ValueError('existing refusal removed')
                        if b['row']['activity_state']!='bursty' and a['paused']!=b['paused']:raise ValueError('non-bursty admission changed')
                    cells=measures(s,values,candidate,policy)
                    if gate=='unchanged' and source in ('normalized','raw_two'):
                        oldname=('normalized' if source=='normalized' else 'raw_replacement')+':'+PRICING
                        for c in cells:
                            ref=refs[(oldname,policy,c['case_id'],c['activity'])]
                            for field in ('windows','eligible_outcomes','survived','mean_width_ppm','full_window_pinball_ppm'):
                                if c[field]!=ref[field]:raise ValueError('benchmark cell differs '+field)
                            reconstructed+=1
                    cases.extend(cells);phases.extend(phase_cells(s,values,candidate,policy))
                    saved[candidate][policy][s['id']]=[p for p in values if p['row']['activity_state']=='bursty' and p['shadow_survived'] is not None]
                    for p in values:
                        if p['row']['activity_state']=='bursty':
                            stream.write(json.dumps(dict(candidate=candidate,policy=policy,session=s['id'],start=p['row']['start'],
                                width=p['width_ppm'],shadow=p['shadow_survived'],paused=p['paused'],reason=p['burst_admission_reason'],
                                mature=p['burst_admission_mature'],floor=p['burst_admission_floor'],episode=p['burst_admission_episode']),separators=(',',':'))+'\n')
            if index%10==0:print(f'earlier raw admission replay {index+1}/{len(evaluated)}',flush=True)
    pairs=[r for c,policies in saved.items() for p,values in policies.items() for r in paired(evaluated,values,c,p)]
    result=dict(declaration,selected=selection['selected'],ranking=selection['ranking'],raw_checks=rawchecks,models=models,
        cases=cases,phases=phases,paired=pairs,summary=summarize(cases),
        selection_sha256=file_hash(output/'selection.json'),predictions_sha256=file_hash(output/'predictions.jsonl.gz'),
        training_rows_sha256=file_hash(output/'earlier-training-rows.jsonl.gz'),
        checks=dict(benchmark_cells_reconstructed=reconstructed,admission_preserves_all_widths_and_shadow_paths=True,
            non_bursty_admission_fixed=True,refused_paths_remain_in_reference_denominators=True,identical_paired_paths=True,
            earlier_raw_strictly_precedes_fitted_cutoffs=True))
    for n,h in declaration['source_sha256'].items():
        if file_hash(Path(__file__).with_name(n))!=h:raise ValueError('source changed during replay')
    (output/'research.json').write_text(json.dumps(result,indent=2)+'\n')
    for key in ('cases','phases','paired','summary'):
        write_csv(output/(key+'.csv'),result[key],list(result[key][0]))
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--previous',type=Path,required=True)
    p.add_argument('--raw',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();r=run(a.previous,a.raw,a.output)
    print(json.dumps(dict(selected=r['selected'],ranking=r['ranking'],checks=r['checks'],raw_checks=r['raw_checks']),indent=2))
