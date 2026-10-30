#!/usr/bin/env python3
"""Bursty overlays versus simple engine floors and prior feedback on retained 8h paths."""
import argparse
from collections import defaultdict
import gzip
import json
from pathlib import Path
import shutil
from statistics import mean

from bursty_pricing import SPECS, fit_model, reprice
from capture_dataset import file_hash
from investigate_capture import write_csv
from nonfrozen_pricing import SPECS as BASES, reprice as base_reprice
from oracle_activity_features import load
from research_activity_calibration import fit, metrics, predict, shadow
from research_flat_pause import ENGINE_SPEC, apply_pause
from research_frozen_pricing import PAUSE, fit_overlay
from research_nonfrozen_pricing import (DEPENDENCIES as PRIOR_DEPENDENCIES, POLICIES, fixed_mask,
    group, measures, read_sessions, selection_components, summarize, verify_raw)
from research_startup_admission import priced, verify_code
from startup_admission import SPECS as RULES, admit

DEPENDENCIES = tuple(dict.fromkeys(('research_bursty_pricing.py', 'bursty_pricing.py') + PRIOR_DEPENDENCIES))
BASE_NAMES = ('baseline', 'engine_floor20', 'engine_floor10', 'feedback_state_fast')


def bases(values, engine, prior):
    return {name: base_reprice(values, prior, next(s for s in BASES if s['name'] == name), engine)
            for name in BASE_NAMES}


def fit_models(values, engine, prior):
    return {name: fit_model(base_reprice(values, prior, next(s for s in BASES if s['name'] == name), engine))
            for name in ('baseline', 'engine_floor10')}


def evaluate(values, base_values, models, candidate):
    return reprice(base_values[candidate['base']], models.get(candidate['base']), candidate)


def losses(values):
    return {g: metrics(shadow(group(values, g))) for g in ('non_frozen', 'bursty', 'pump', 'dump')}


def burst_score(cases):
    errors = [abs(r['error_pp']) for r in cases if r['activity'] == 'bursty' and r['windows'] >= 20]
    return mean(errors) + .25 * max(errors) if errors else 0.0


def choose(rows, dates, sessions, overlay_spec):
    scores, folds, inner_models = defaultdict(list), [], []
    rule = next(r for r in RULES if r['name'] == POLICIES[0])
    from nonfrozen_pricing import fit_prior
    for begin, end in ((6, 9), (9, 12), (12, 14)):
        training = [r for r in rows if r['period'] in dates[:begin]]
        engine = fit(training, ENGINE_SPEC)
        overlay = fit_overlay(apply_pause(predict(training, engine), PAUSE), overlay_spec)
        train_values = priced(training, engine, overlay)
        prior = fit_prior(train_values)
        models = fit_models(train_values, engine, prior)
        inputs = []
        for s in sessions:
            if s['source'] == 'normalized' and s['mode'] == 'restart' and s['period'] in dates[begin:end]:
                v = priced([p['row'] for p in s['values']], engine, overlay)
                inputs.append((s, v, bases(v, engine, prior), admit(v, rule)))
        baseline_losses = losses([p for _, v, _, _ in inputs for p in v])
        inner_models.append(dict(training_periods=dates[:begin], engine=engine, models=models))
        for candidate in SPECS:
            cases, predictions = [], []
            for session, values, base_values, mask in inputs:
                result = evaluate(values, base_values, models, candidate)
                predictions.extend(result)
                cases.extend(measures(session, fixed_mask(result, mask), candidate['name'], rule['name']))
            loss, penalty = losses(predictions), 0.0
            for g, b in baseline_losses.items():
                if b['windows'] >= 20 and b['pinball_ppm']:
                    penalty += 100 * max(0, loss[g]['pinball_ppm'] / b['pinball_ppm'] - 1.1)
            original = selection_components(cases)
            score = original + burst_score(cases) + penalty
            scores[candidate['name']].append(score)
            folds.append(dict(candidate=candidate['name'], training_days=begin, scoring_days=dates[begin:end],
                              score=score, prior_objective_without_loss_guard=original,
                              burst_component=burst_score(cases), loss_guard_penalty=penalty,
                              full_path_losses=loss, baseline_full_path_losses=baseline_losses))
        print(f'finished burst selection fold {begin}->{end}', flush=True)
    ranking = sorted((dict(name=c['name'], score=mean(scores[c['name']]), folds=scores[c['name']], index=i)
                      for i, c in enumerate(SPECS)), key=lambda r: (r['score'], r['index']))
    return next(c for c in SPECS if c['name'] == ranking[0]['name']), ranking, folds, inner_models


def joint_checks(cases):
    result = []
    for c in SPECS:
        for policy in POLICIES:
            rows = [r for r in cases if r['candidate'] == c['name'] and r['policy'] == policy
                    and r['mode'] == 'restart' and r['source'] in ('raw', 'raw_control')]
            grouped = defaultdict(dict)
            for r in rows:
                grouped[r['case_id']][r['activity']] = r
            def passed(r):
                return r['windows'] >= 20 and abs(r['error_pp']) <= 5
            result.append(dict(candidate=c['name'], policy=policy, cases=len(grouped),
                               overall_pass=sum(passed(r['all']) for r in grouped.values()),
                               non_frozen_pass=sum(passed(r['non_frozen']) for r in grouped.values()),
                               frozen_pass=sum(passed(r['frozen']) for r in grouped.values()),
                               bursty_relevant=sum(r['bursty']['eligible_outcomes'] >= 20 for r in grouped.values()),
                               bursty_pass=sum(passed(r['bursty']) for r in grouped.values()),
                               all_three_pass=sum(all(passed(r[g]) for g in ('all','non_frozen','frozen')) for r in grouped.values())))
    return result


def startup_cells(session, values, candidate):
    output = []
    for interval in session['intervals']:
        part = [p for p in values if interval['start'] <= p['row']['start'] < interval['end']
                and p['row']['activity_state'] == 'bursty']
        # Rank pre-entry predictions, including paths later censored, never only healthy paths.
        predicted = [p for p in part if p['width_ppm'] is not None]
        for label, group_ in (('first12_decisions', predicted[:12]), ('later_decisions', predicted[12:])):
            m = metrics(shadow(group_))
            output.append(dict(candidate=candidate, case_id=f'{session["id"]}:{interval["hour"]:02}',
                               source=session['source'], period=session['period'], split=session['split'],
                               mode=session['mode'], phase=label, pre_entry_decisions=len(group_), **m))
    return output


def run(parent_directory, output):
    if output.exists():
        raise ValueError('preserve archived experiments')
    previous = json.loads((parent_directory / 'research.json').read_text())
    verify_code(parent_directory, previous)
    if file_hash(parent_directory / 'predictions.jsonl.gz') != previous['predictions_sha256']:
        raise ValueError('prior predictions differ')
    admission, controls = Path(previous['admission']), Path(previous['controls'])
    parents = []
    for name, directory in (('admission', admission), ('controls', controls)):
        if file_hash(directory / 'research.json') != previous[name+'_sha256']:
            raise ValueError('prior metadata differs')
        m = json.loads((directory / 'research.json').read_text())
        verify_code(directory, m)
        parents.append(m)
    parent, control = parents
    if control['admission_sha256'] != previous['admission_sha256']:
        raise ValueError('control/admission binding differs')
    original, metadata = load(Path(previous['dataset']))
    if file_hash(Path(previous['dataset']) / 'dataset.json') != previous['dataset_sha256']:
        raise ValueError('original features differ')
    raw_old = json.loads(Path(parent['raw_research']).joinpath('research.json').read_text())
    if file_hash(Path(parent['raw_research']) / 'research.json') != parent['raw_research_sha256']:
        raise ValueError('raw research binding differs')
    verify_code(Path(parent['raw_research']), raw_old)
    verify_raw(control); verify_raw(raw_old)
    pricing_directory = Path(parent['pricing'])
    old = json.loads((pricing_directory / 'research.json').read_text())
    if file_hash(pricing_directory / 'research.json') != parent['pricing_sha256']:
        raise ValueError('frozen pricing binding differs')
    verify_code(pricing_directory, old)
    sessions = read_sessions(admission, parent) + read_sessions(controls, control)
    protocol = dict(previous=str(parent_directory.resolve()), previous_sha256=file_hash(parent_directory / 'research.json'),
                    admission=str(admission), admission_sha256=previous['admission_sha256'],
                    controls=str(controls), controls_sha256=previous['controls_sha256'],
                    dataset=previous['dataset'], dataset_sha256=previous['dataset_sha256'],
                    input_session_hashes=previous['input_session_hashes'], specs=SPECS, fixed_admission=POLICIES,
                    source_sha256={n:file_hash(Path(__file__).with_name(n)) for n in DEPENDENCIES},
                    target_survival=.48, band=(.43,.53),
                    selection='Same original 6/9/12 prefixes and next 3/3/2 dates, fresh 8h cases. Prior objective plus bursty mean+quarter-worst absolute error. Same-path non-frozen/bursty/pump/dump loss penalty beyond 10%. Equal folds, declared-order ties.',
                    raw_and_failure_2026_august_excluded_from_selection=True,
                    repeated_inspected_periods=True, independent_holdout=False,
                    capture_started=False, live_candidate_promoted=False)
    output.mkdir(parents=True); (output / 'source').mkdir()
    (output / 'protocol.json').write_text(json.dumps(protocol, indent=2)+'\n')
    for name in DEPENDENCIES:
        shutil.copyfile(Path(__file__).with_name(name), output / 'source' / name)
    chosen, ranking, folds, inner_models = choose(original, metadata['dates'], sessions, old['models']['hurdle_all_120']['spec'])
    (output / 'selection.json').write_text(json.dumps(dict(selected_spec=chosen, ranking=ranking, folds=folds, models=inner_models), indent=2)+'\n')
    models = {}
    def model_key(s):
        return s['period'] if s['source'] in ('raw_control','normalized_control') else 'raw_january' if s['source']=='raw' else 'original_final'
    def overlay_for(s):
        if s['source'] in ('raw_control','normalized_control'):
            return control['models'][s['period']]['overlay']
        if s['source'] == 'raw':
            return raw_old['models'][s['period']]['overlays']['frozen_floor_53']['hurdle_all_120']
        return old['models']['hurdle_all_120']
    cases, startup = [], []
    references = {(r['candidate'], r['policy'], r['case_id'], r['activity']):r for r in previous['cases'] if r['candidate'] in BASE_NAMES}
    availability = {}
    with gzip.open(output / 'predictions.jsonl.gz', 'wt', compresslevel=5) as stream:
        for index, session in enumerate(sessions):
            key = model_key(session)
            original_model = previous['models'][key]
            engine, prior = original_model['engine'], original_model['prior']
            values = session['values']
            if key not in models:
                training = [r for r in original if r['period'] in original_model['training_periods']]
                models[key] = dict(training_periods=original_model['training_periods'],
                                   models=fit_models(priced(training, engine, overlay_for(session)), engine, prior))
            base_values = bases(values, engine, prior)
            masks = {name:admit(values, next(r for r in RULES if r['name']==name)) for name in POLICIES}
            for candidate in SPECS:
                result = evaluate(values, base_values, models[key]['models'], candidate)
                for p,b in zip(result,base_values[candidate['base']]):
                    if (p['width_ppm'] is None, p['shadow_survived'] is None, p['paused']) != (b['width_ppm'] is None, b['shadow_survived'] is None, b['paused']):
                        raise ValueError('eligibility or pause changed')
                    if b['row']['activity_state'] != 'bursty' and (p['width_ppm'],p['shadow_survived']) != (b['width_ppm'],b['shadow_survived']):
                        raise ValueError('overlay changed another activity state')
                    if candidate['directional_guard'] and b['row']['market_regime'] in ('pump','dump') and (p['width_ppm'],p['shadow_survived']) != (b['width_ppm'],b['shadow_survived']):
                        raise ValueError('guarded directional forecast changed')
                for policy,mask in masks.items():
                    cells = measures(session,fixed_mask(result,mask),candidate['name'],policy)
                    for r in cells:
                        availability_key=(r['case_id'],policy,r['activity'])
                        count=tuple(r[k] for k in ('windows','eligible_outcomes','pre_entry_predictions','offered_pre_entry_decisions','grid_windows'))
                        if availability_key in availability and availability[availability_key]!=count:
                            raise ValueError('availability changed')
                        availability[availability_key]=count
                        if candidate['family']=='comparator':
                            ref=references[(candidate['name'],policy,r['case_id'],r['activity'])]
                            for k in ('windows','survived','eligible_outcomes','full_window_pinball_ppm','mean_width_ppm'):
                                if r[k]!=ref[k]:raise ValueError(f'comparator reconstruction differs: {k}')
                    cases.extend(cells)
                startup.extend(startup_cells(session,result,candidate['name']))
                for i,p in enumerate(result):
                    stream.write(json.dumps(dict(candidate=candidate['name'],session=session['id'],start=p['row']['start'],
                                                 width=p['width_ppm'],shadow=p['shadow_survived'],
                                                 correction=p['burst_correction'],mature=p['burst_mature'],parent_mature=p['burst_parent_mature'],
                                                 paused={name:mask[i]['paused'] for name,mask in masks.items()}),separators=(',',':'))+'\n')
            if index%10==0:print(f'replayed {index+1}/{len(sessions)} burst sessions',flush=True)
    combined=[dict(r,source='combined_raw',split='raw_diagnostic') for r in cases if r['source'] in ('raw','raw_control')]
    result=dict(protocol,selected_spec=chosen,ranking=ranking,folds=folds,models=models,cases=cases,startup=startup,
                summary=summarize(cases),combined_raw_summary=summarize(combined),joint_checks=joint_checks(cases),
                predictions_sha256=file_hash(output / 'predictions.jsonl.gz'),
                checks=dict(all_four_comparators_reconstructed=True,non_bursty_overlay_invariance=True,
                            frozen_forecast_invariance=True,eligibility_masks_and_availability_unchanged=True,
                            raw_originals_and_native_receipts_reverified=True,later_cases_excluded_from_selection=True))
    for n,digest in protocol['source_sha256'].items():
        if file_hash(Path(__file__).with_name(n))!=digest:raise ValueError('source changed during replay')
    (output/'research.json').write_text(json.dumps(result,indent=2)+'\n')
    for name in ('cases','startup','summary','combined_raw_summary','joint_checks'):
        write_csv(output/(name.replace('_','-')+'.csv'),result[name],list(result[name][0]))
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--previous',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    result=run(args.previous,args.output)
    print(json.dumps(dict(selected=result['selected_spec'],ranking=result['ranking'],joint_checks=result['joint_checks']),indent=2))
