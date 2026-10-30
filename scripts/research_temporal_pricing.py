#!/usr/bin/env python3
"""Select on later chronological development, then open pinned later raw data."""
import argparse
import gzip
import json
from pathlib import Path
import shutil
from statistics import mean
import time

from capture_dataset import file_hash
from fetch_temporal_raw import PLAN
from full_raw_pipeline import fit_bundle, bounds
from investigate_capture import write_csv
from research_bursty_optimizer import dump
from research_bursty_startup_raw import phase_cells, paired
from research_full_raw_pipeline import score, losses, DEPENDENCIES as PARENT_DEPENDENCIES
from research_nonfrozen_pricing import group, measures, summarize
from research_oracle_history import observations
from research_raw_flat_panels import parse_raw
from research_startup_admission import verify_code
from research_symbolic_corridor import regime_cells
from temporal_oracle_data import load, late_days, profile
from temporal_pricing import STAGES, POLICIES, VARIANTS, sessions, date_rows, all_predictions

DEPENDENCIES=tuple(dict.fromkeys(('fetch_temporal_raw.py','temporal_oracle_data.py','temporal_pricing.py',
    'research_temporal_pricing.py','test_temporal_research.py')+PARENT_DEPENDENCIES))


def make_sessions(normalized,raw,dates,split):
    return [s for day,rows,source in date_rows(normalized,raw,dates) for s in sessions(day,rows,source,split)]


def replay(scoring,models,path):
    cases=[];phases=[];regimes=[];floor_bounds=[];full={stage:[] for stage in STAGES}
    saved={c:{} for c in VARIANTS}
    with gzip.open(path,'wt',compresslevel=5) as stream:
        for s in scoring:
            alternatives=all_predictions(s['rows'],models)
            for candidate,values in alternatives.items():
                stage,policy=candidate.split(':')
                if policy==POLICIES[0]:full[stage].extend(values)
                cases.extend(measures(s,values,candidate,policy));phases.extend(phase_cells(s,values,candidate,policy))
                regimes.extend(regime_cells(s,values,candidate,policy));saved[candidate][s['id']]=values
                for interval in s['intervals']:
                    for activity in ('all','frozen','bursty','pump','dump'):
                        part=group([p for p in values if interval['start']<=p['row']['start']<interval['end']],activity)
                        floor_bounds.append(dict(candidate=candidate,policy=policy,case_id=f'{s["id"]}:{interval["hour"]:02}',
                            source=s['source'],period=s['period'],mode=s['mode'],split=s['split'],activity=activity,**interval,**bounds(part)))
                for p in values:
                    stream.write(json.dumps(dict(candidate=candidate,session=s['id'],start=p['row']['start'],
                        activity=p['row']['activity_state'],regime=p['row']['market_regime'],width=p['width_ppm'],
                        shadow=p['shadow_survived'],paused=p['paused'],floor_reason=p['floor_reason']),allow_nan=False)+'\n')
    pairs=[r for c,values in saved.items() for r in paired(scoring,values,c,c.split(':')[1])]
    return dict(cases=cases,phases=phases,regimes=regimes,floor_bounds=floor_bounds,paired=pairs,
                full_losses={stage:losses(values) for stage,values in full.items()})


def evaluate_fold(result,begin,dates):
    ref=result['full_losses']['fixed_retained'];rows=[]
    for stage in STAGES:
        loss=result['full_losses'][stage]
        guard=sum(100*max(0,loss[g]['pinball_ppm']/v['pinball_ppm']-1.1) for g,v in ref.items()
                  if v['windows']>=20 and v['pinball_ppm'])
        for policy in POLICIES:
            candidate=stage+':'+policy;modes={}
            for mode in ('restart','continuous'):
                modes[mode]=score([r for r in result['cases'] if r['candidate']==candidate and r['mode']==mode],
                    [r for r in result['phases'] if r['candidate']==candidate and r['mode']==mode])
            value=mean(r['score'] for r in modes.values())+.25*abs(modes['restart']['score']-modes['continuous']['score'])+guard
            rows.append(dict(candidate=candidate,training_days=begin,scoring_days=dates,score=value,modes=modes,
                             loss_guard=guard,full_reference_losses=loss))
    return rows


def normalized_manifest(metadata):
    dataset=json.loads((Path(metadata['source_dataset'])/'dataset.json').read_text())
    history=json.loads((Path(dataset['history'])/'research.json').read_text())
    path=Path(history['source_manifest_path'])
    if file_hash(path)!=history['source_manifest_sha256']:raise ValueError('normalized archive binding differs')
    return path


def crosscheck_late(rawdir,normalmanifest):
    m=json.loads((rawdir/'download-manifest.json').read_text())
    normal=json.loads(normalmanifest.read_text());checks=[]
    protocol=json.loads((rawdir/'download-protocol.json').read_text())
    for panel in protocol['panels']:
        item=next(f for f in normal['files'] if f['date']==panel['day'])
        if file_hash(normalmanifest.parent/item['path'])!=item['sha256']:raise ValueError('normalized raw crosscheck file differs')
        norm,_=observations(normalmanifest.parent/item['path'],panel['start'],panel['end'])
        raw,_=parse_raw(sorted([f for f in m['files'] if f['day']==panel['day']],key=lambda f:f['at_ms']),rawdir)
        rawmap=dict(raw);common=[(at,price) for at,price in norm if at in rawmap]
        mismatch=sum(rawmap[at]!=price for at,price in common)
        if not common or mismatch:raise ValueError('late raw oracle crosscheck failed')
        checks.append(dict(day=panel['day'],raw_messages=len(raw),normalized_messages=len(norm),
            shared_timestamps=len(common),oracle_mismatches=mismatch))
    return checks


def run(dataset,rawdir,previous_dir,output):
    if output.exists():raise ValueError('preserve earlier experiment; choose a new output')
    started=time.monotonic()
    download=json.loads((rawdir/'download-protocol.json').read_text())
    if download['plan']!=PLAN:raise ValueError('study differs from declaration before raw download')
    protocol=dict(previous=str(previous_dir.resolve()),previous_sha256=file_hash(previous_dir/'research.json'),
        dataset=str(dataset.resolve()),dataset_sha256=file_hash(dataset/'dataset.json'),
        raw=str(rawdir.resolve()),raw_manifest_sha256=file_hash(rawdir/'download-manifest.json'),
        raw_protocol_sha256=file_hash(rawdir/'download-protocol.json'),plan=PLAN,
        source_sha256={n:file_hash(Path(__file__).with_name(n)) for n in DEPENDENCIES},
        target_survival=.48,band=[.43,.53],capture_started=False,live_candidate_promoted=False,independent_holdout=False,
        comparison='Fixed preceding retained benchmark versus expanding complete raw core. Same predeclared full-state score and availability screens. Open later raw outcomes only after selection and all models are pinned.')
    output.mkdir(parents=True);(output/'source').mkdir()
    for n in DEPENDENCIES:shutil.copyfile(Path(__file__).with_name(n),output/'source'/n)
    dump(output/'protocol.json',protocol)
    previous=json.loads((previous_dir/'research.json').read_text());verify_code(previous_dir,previous)
    if download['previous_sha256']!=protocol['previous_sha256']:raise ValueError('download parent differs')
    if file_hash(previous_dir/'models.json')!=previous['models_sha256']:raise ValueError('fixed benchmark binding differs')
    fixed=json.loads((previous_dir/'models.json').read_text())['original_final']['retained']
    normalized,raw,metadata=load(dataset);dates=metadata['dates']
    if len(dates)!=24:raise ValueError('the declared 24-date universe is required')
    if any(day>=dates[22] for day in raw):raise ValueError('later raw outcomes must not enter initial selection data')
    models={};folds=[];selection_results=[]
    for fold in PLAN['folds']:
        begin=fold['training_days'];left,right=fold['scoring_indices'];scoring_dates=dates[left:right]
        fitted=fit_bundle(normalized,raw,dates[:begin],scoring_dates[0],fixed,'raw_core')
        models[str(begin)]=dict(fixed_retained=fixed,expanding_raw_core=fitted)
        dump(output/f'models-{begin}.json',models[str(begin)])
        result=replay(make_sessions(normalized,raw,scoring_dates,'selection'),models[str(begin)],output/f'selection-predictions-{begin}.jsonl.gz')
        folds.extend(evaluate_fold(result,begin,scoring_dates));selection_results.append(result)
        print('Temporal selection '+str(begin)+' -> '+','.join(scoring_dates),flush=True)
    ranking=[]
    for candidate in VARIANTS:
        part=[r for r in folds if r['candidate']==candidate]
        ranking.append(dict(candidate=candidate,score=mean(r['score'] for r in part),folds=[r['score'] for r in part],
            feasible=all(m['constraints']['feasible'] for r in part for m in r['modes'].values())))
    ranking.sort(key=lambda r:(not r['feasible'],r['score'],VARIANTS.index(r['candidate'])))
    choice=dict(selected=ranking[0]['candidate'],ranking=ranking,folds=folds,later_raw_excluded=True,
                earlier_dates=dates[:22],later_dates=dates[22:24],independent_holdout=False)
    dump(output/'selection.json',choice)
    # This final fit includes August's already-retained raw data, and no later day.
    models['22']=dict(fixed_retained=fixed,expanding_raw_core=fit_bundle(normalized,raw,dates[:22],dates[22],fixed,'raw_core'))
    dump(output/'models-22.json',models['22']);dump(output/'models.json',models)
    pinned={name:file_hash(output/name) for name in ('selection.json','models.json')}
    print('Temporal choice and models pinned; opening later raw comparisons',flush=True)
    later,binding=late_days(rawdir)
    if sorted(later)!=dates[22:24]:raise ValueError('later dates differ from the declared diagnostic block')
    checks=crosscheck_late(rawdir,normalized_manifest(metadata))
    # Preserve both source formats for diagnostics, using the same frozen models.
    raw_scoring=make_sessions(normalized,later,dates[22:24],'later_raw')
    normalized_scoring=make_sessions(normalized,{},dates[22:24],'later_normalized')
    late=replay(raw_scoring+normalized_scoring,models['22'],output/'later-predictions.jsonl.gz')
    for name,digest in pinned.items():
        if file_hash(output/name)!=digest:raise ValueError('selection or model changed after later raw opened')
    for name,digest in protocol['source_sha256'].items():
        if file_hash(Path(__file__).with_name(name))!=digest:raise ValueError('source changed during study')
    result=dict(protocol,selected=choice['selected'],ranking=ranking,selection_sha256=pinned['selection.json'],
        models_sha256=pinned['models.json'],later_predictions_sha256=file_hash(output/'later-predictions.jsonl.gz'),
        selection_prediction_sha256={str(f['training_days']):file_hash(output/f'selection-predictions-{f["training_days"]}.jsonl.gz') for f in PLAN['folds']},
        later_raw_binding=binding,late_crosschecks=checks,later_raw_profiles={day:profile(rows) for day,rows in later.items()},
        elapsed_seconds=time.monotonic()-started,
        **{name:[r for part in selection_results+[late] for r in part[name]] for name in ('cases','phases','regimes','floor_bounds','paired')})
    result['summary']=summarize(result['cases']);dump(output/'research.json',result)
    for name in ('cases','phases','regimes','floor_bounds','paired','summary'):
        write_csv(output/(name+'.csv'),result[name],list(result[name][0]))
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--dataset',type=Path,required=True)
    p.add_argument('--raw',type=Path,required=True);p.add_argument('--previous',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    args=p.parse_args();r=run(args.dataset,args.raw,args.previous,args.output)
    print(json.dumps(dict(selected=r['selected'],ranking=r['ranking'],late_crosschecks=r['late_crosschecks'],elapsed_seconds=r['elapsed_seconds']),indent=2))
