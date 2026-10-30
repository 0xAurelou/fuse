#!/usr/bin/env python3
"""Replay non-frozen pricing alternatives on hash-bound retained 8h sessions."""
import argparse
from collections import defaultdict
import gzip
import json
from pathlib import Path
import shutil
from statistics import mean

from capture_dataset import file_hash
from investigate_capture import write_csv
from nonfrozen_pricing import SPECS, STATES, fit_prior, reprice
from oracle_activity_features import load
from research_activity_calibration import fit, metrics, shadow
from research_flat_pause import ENGINE_SPEC
from research_frozen_pricing import fit_overlay
from research_startup_admission import (DEPENDENCIES as PARENT_DEPENDENCIES,
                                       priced, verify_code)
from research_raw_flat_panels import cell
from startup_admission import SPECS as RULES, admit

DEPENDENCIES = tuple(dict.fromkeys(('research_nonfrozen_pricing.py', 'nonfrozen_pricing.py',
                                   'validate_admission_controls.py') + PARENT_DEPENDENCIES))
POLICIES = ('previous_floor_53', 'warm12_floor30')
GROUPS = ('all', 'non_frozen', 'frozen', 'active', 'sparse', 'bursty', 'pump', 'dump')


def group(values, name):
    if name == 'all':
        return values
    if name == 'non_frozen':
        return [p for p in values if p['row']['activity_state'] in STATES]
    if name in ('pump', 'dump'):
        return [p for p in values if p['row']['market_regime'] == name]
    return [p for p in values if p['row']['activity_state'] == name]


def fixed_mask(values, masked):
    if len(values) != len(masked):
        raise ValueError('mask alignment differs')
    return [dict(p, paused=b['paused'], floor_reason=b['floor_reason'],
                 survived=None if b['paused'] else p['shadow_survived']) for p, b in zip(values, masked)]


def measures(session, values, candidate, policy):
    result = []
    for interval in session['intervals']:
        part = [p for p in values if interval['start'] <= p['row']['start'] < interval['end']]
        for activity in GROUPS:
            result.append(dict(candidate=candidate, policy=policy, case_id=f'{session["id"]}:{interval["hour"]:02}',
                               source=session['source'], period=session['period'], split=session['split'],
                               mode=session['mode'], activity=activity, **interval, **cell(group(part, activity))))
    return result


def selection_components(cases):
    def errors(activity):
        return [abs(r['error_pp']) for r in cases if r['activity'] in activity and r['windows'] >= 20]
    overall, nf = errors(('all',)), errors(('non_frozen',))
    conditional, directional = errors(STATES), errors(('pump', 'dump'))
    if not overall or not nf:
        raise ValueError('no earlier selection cases')
    return (mean(overall) + .25 * max(overall) + mean(nf) + .25 * max(nf)
            + .5 * (mean(conditional) if conditional else 0)
            + .5 * (mean(directional) if directional else 0))


def loss_by_group(values):
    return {g: metrics(shadow(group(values, g))) for g in ('non_frozen', 'pump', 'dump')}


def choose(rows, dates, sessions, overlay_spec):
    """Only original first fourteen days and fresh cached feature frames enter selection."""
    scores, folds, models = defaultdict(list), [], []
    rule = next(r for r in RULES if r['name'] == POLICIES[0])
    for begin, end in ((6, 9), (9, 12), (12, 14)):
        training = [r for r in rows if r['period'] in dates[:begin]]
        engine = fit(training, ENGINE_SPEC)
        # fit_overlay's hurdle prior uses all eligible references, matching the retained experiment.
        from research_activity_calibration import predict
        from research_flat_pause import apply_pause
        from research_frozen_pricing import PAUSE
        overlay = fit_overlay(apply_pause(predict(training, engine), PAUSE), overlay_spec)
        prior = fit_prior(priced(training, engine, overlay))
        models.append(dict(training_days=begin, training_periods=dates[:begin], engine=engine, prior=prior))
        inputs = [dict(s, values=priced([p['row'] for p in s['values']], engine, overlay))
                  for s in sessions if s['source'] == 'normalized' and s['mode'] == 'restart'
                  and s['period'] in dates[begin:end]]
        base_losses = loss_by_group([p for s in inputs for p in s['values']])
        for candidate in SPECS:
            cases, predictions = [], []
            for session in inputs:
                values = reprice(session['values'], prior, candidate, engine)
                cases.extend(measures(session, fixed_mask(values, admit(session['values'], rule)),
                                      candidate['name'], rule['name']))
                predictions.extend(values)
            losses = loss_by_group(predictions)
            penalty = 0.0
            for g, baseline in base_losses.items():
                if baseline['windows'] >= 20 and baseline['pinball_ppm'] and baseline['pinball_ppm'] > 0:
                    penalty += 100 * max(0, losses[g]['pinball_ppm'] / baseline['pinball_ppm'] - 1.1)
            score = selection_components(cases) + penalty
            scores[candidate['name']].append(score)
            folds.append(dict(candidate=candidate['name'], training_days=begin, scoring_days=dates[begin:end],
                              score=score, loss_guard_penalty=penalty, full_path_losses=losses,
                              baseline_full_path_losses=base_losses))
        print(f'finished earlier selection fold {begin}->{end}', flush=True)
    ranking = sorted((dict(name=s['name'], score=mean(scores[s['name']]), folds=scores[s['name']], index=i)
                      for i, s in enumerate(SPECS)), key=lambda r: (r['score'], r['index']))
    return next(s for s in SPECS if s['name'] == ranking[0]['name']), ranking, folds, models


def summarize(cases):
    groups = defaultdict(list)
    for r in cases:
        groups[tuple(r[k] for k in ('candidate', 'policy', 'source', 'split', 'mode', 'activity'))].append(r)
    result = []
    for key, rows in groups.items():
        eligible, n = sum(r['eligible_outcomes'] for r in rows), sum(r['windows'] for r in rows)
        full_loss = sum(r['eligible_outcomes'] * (r['full_window_pinball_ppm'] or 0) for r in rows)
        relevant = [r for r in rows if r['eligible_outcomes'] >= 20]
        measured = [r for r in relevant if r['windows'] >= 20]
        result.append(dict(zip(('candidate', 'policy', 'source', 'split', 'mode', 'activity'), key),
                           cases=len(rows), eligible_outcomes=eligible, quoted_outcomes=n,
                           survival=sum(r['survived'] for r in rows) / n if n else None,
                           eligible_quote_fraction=n / eligible if eligible else None,
                           full_window_pinball_ppm=full_loss / eligible if eligible else None,
                           cases_original_at_least20=len(relevant),
                           cases_pass_with_at_least20=sum(abs(r['error_pp']) <= 5 for r in measured),
                           mean_case_error_pp=mean(abs(r['error_pp']) for r in measured) if measured else None,
                           worst_case_error_pp=max((abs(r['error_pp']) for r in measured), default=None),
                           minimum_case_availability=min((r['eligible_quote_fraction'] for r in relevant), default=None)))
    return result


def joint_checks(cases):
    output = []
    for candidate in SPECS:
        for policy in POLICIES:
            selected = [r for r in cases if r['candidate'] == candidate['name'] and r['policy'] == policy
                        and r['mode'] == 'restart' and r['source'] in ('raw', 'raw_control')]
            by_case = defaultdict(dict)
            for r in selected:
                by_case[r['case_id']][r['activity']] = r
            def passed(r):
                return r['windows'] >= 20 and abs(r['error_pp']) <= 5
            output.append(dict(candidate=candidate['name'], policy=policy, cases=len(by_case),
                               overall_pass=sum(passed(c['all']) for c in by_case.values()),
                               non_frozen_pass=sum(passed(c['non_frozen']) for c in by_case.values()),
                               frozen_pass=sum(passed(c['frozen']) for c in by_case.values()),
                               overall_and_non_frozen_pass=sum(all(passed(c[g]) for g in ('all', 'non_frozen'))
                                                              for c in by_case.values()),
                               all_three_pass=sum(all(passed(c[g]) for g in ('all', 'non_frozen', 'frozen'))
                                                  for c in by_case.values())))
    return output


def read_sessions(directory, metadata):
    path = directory / 'input-sessions.jsonl.gz'
    if file_hash(path) != metadata['input_sessions_sha256']:
        raise ValueError('retained inputs differ')
    with gzip.open(path, 'rt') as stream:
        return [json.loads(line) for line in stream]


def verify_raw(metadata):
    raw = Path(metadata['raw'])
    if file_hash(raw / 'download-manifest.json') != metadata['raw_manifest_sha256']:
        raise ValueError('raw manifest differs')
    manifest = json.loads((raw / 'download-manifest.json').read_text())
    if not manifest['complete'] or file_hash(raw / 'download-protocol.json') != manifest['protocol_sha256']:
        raise ValueError('raw protocol differs or incomplete')
    for f in manifest['files']:
        if file_hash(raw / f['path']) != f['sha256']:
            raise ValueError('raw response differs')


def run(admission, controls, output):
    if output.exists():
        raise ValueError('preserve retained experiments; choose a new output')
    parent = json.loads((admission / 'research.json').read_text())
    control = json.loads((controls / 'research.json').read_text())
    verify_code(admission, parent); verify_code(controls, control)
    if control['admission_sha256'] != file_hash(admission / 'research.json'):
        raise ValueError('control/admission binding differs')
    dataset, pricing = Path(parent['dataset']), Path(parent['pricing'])
    original, metadata = load(dataset)
    old = json.loads((pricing / 'research.json').read_text())
    raw_dir = Path(parent['raw_research'])
    raw_old = json.loads((raw_dir / 'research.json').read_text())
    for directory, digest in ((dataset, parent['dataset_sha256']), (pricing, parent['pricing_sha256']),
                              (raw_dir, parent['raw_research_sha256'])):
        filename = 'dataset.json' if directory == dataset else 'research.json'
        if file_hash(directory / filename) != digest:
            raise ValueError('parent binding differs')
    verify_code(pricing, old); verify_code(raw_dir, raw_old)
    verify_raw(control); verify_raw(raw_old)
    sessions = read_sessions(admission, parent) + read_sessions(controls, control)
    protocol = dict(admission=str(admission.resolve()), admission_sha256=file_hash(admission / 'research.json'),
                    controls=str(controls.resolve()), controls_sha256=file_hash(controls / 'research.json'),
                    dataset=str(dataset), dataset_sha256=parent['dataset_sha256'],
                    source_sha256={n: file_hash(Path(__file__).with_name(n)) for n in DEPENDENCIES},
                    input_session_hashes=[parent['input_sessions_sha256'], control['input_sessions_sha256']],
                    specs=SPECS, fixed_admission=POLICIES, fixed_frozen_pricing='hurdle_all_120',
                    target_survival=.48, band=(.43, .53),
                    selection='Earlier 6/9/12 original training prefixes; next 3/3/2 monthly days; 24 fresh 8h tests. Overall and non-frozen mean+quarter-worst absolute error, half state and directional mean error; same-path non-frozen/pump/dump pinball penalty above 10% deterioration. Equal fold weights; declaration order breaks ties.',
                    capture_started=False, live_candidate_promoted=False, independent_holdout=False,
                    original_eligibility_changed=False, availability_masks_changed=False,
                    raw_or_august_used_for_selection=False)
    output.mkdir(parents=True)
    (output / 'source').mkdir()
    (output / 'protocol.json').write_text(json.dumps(protocol, indent=2) + '\n')
    for name in DEPENDENCIES:
        shutil.copyfile(Path(__file__).with_name(name), output / 'source' / name)
    chosen, ranking, folds, inner_models = choose(original, metadata['dates'], sessions, old['models']['hurdle_all_120']['spec'])
    (output / 'selection.json').write_text(json.dumps(dict(selected_spec=chosen, ranking=ranking, folds=folds,
                                                        models=inner_models), indent=2) + '\n')
    models = {}
    def model_for(session):
        if session['source'] in ('raw_control', 'normalized_control'):
            key = session['period']; m = control['models'][key]
            engine, overlay, periods = m['engine'], m['overlay'], m['training_periods']
        elif session['source'] == 'raw':
            key = 'raw_january'; m = raw_old['models'][session['period']]
            engine, overlay = m['engine'], m['overlays']['frozen_floor_53']['hurdle_all_120']
            periods = [d for d in metadata['dates'][:14] if d < session['period']]
        else:
            key = 'original_final'; engine, overlay = old['frozen_engine'], old['models']['hurdle_all_120']
            periods = metadata['dates'][:14]
        if key not in models:
            train = [r for r in original if r['period'] in periods]
            models[key] = dict(training_periods=periods, engine=engine, prior=fit_prior(priced(train, engine, overlay)))
        return models[key]
    rules = [next(r for r in RULES if r['name'] == name) for name in POLICIES]
    cases = []
    with gzip.open(output / 'predictions.jsonl.gz', 'wt', compresslevel=5) as stream:
        for index, session in enumerate(sessions):
            model = model_for(session)
            baseline = session['values']
            masks = {r['name']: admit(baseline, r) for r in rules}
            # Reconstruct archived baselines, including censored/pre-entry and full-grid counts.
            archived = parent if session['source'] in ('normalized', 'native', 'raw') else control
            for policy, mask in masks.items():
                for measured in measures(session, mask, 'baseline', policy):
                    if measured['activity'] not in ('all', 'frozen'):
                        continue
                    reference = next(r for r in archived['cases'] if r['policy'] == policy
                                     and r['case_id'] == measured['case_id'] and r['activity'] == measured['activity'])
                    for key in ('windows', 'survived', 'eligible_outcomes', 'pre_entry_predictions', 'grid_windows'):
                        if measured[key] != reference[key]:
                            raise ValueError(f'archived baseline differs {session["id"]} {key}')
            for candidate in SPECS:
                values = reprice(baseline, model['prior'], candidate, model['engine'])
                for a, b in zip(values, baseline):
                    if (a['width_ppm'] is None) != (b['width_ppm'] is None) or a['paused'] != b['paused']:
                        raise ValueError('eligibility/mask changed')
                    if (a['shadow_survived'] is None) != (b['shadow_survived'] is None):
                        raise ValueError('outcome eligibility changed')
                    if b['row']['activity_state'] == 'frozen' and (a['width_ppm'], a['shadow_survived']) != (b['width_ppm'], b['shadow_survived']):
                        raise ValueError('frozen forecast changed')
                for policy, mask in masks.items():
                    cases.extend(measures(session, fixed_mask(values, mask), candidate['name'], policy))
                for i, p in enumerate(values):
                    stream.write(json.dumps(dict(candidate=candidate['name'], session=session['id'], start=p['row']['start'],
                                                 width=p['width_ppm'], shadow=p['shadow_survived'],
                                                 correction=p['nonfrozen_correction'], mature=p['nonfrozen_mature'],
                                                 paused={k: v[i]['paused'] for k, v in masks.items()}), separators=(',', ':')) + '\n')
            if index % 10 == 0:
                print(f'replayed {index+1}/{len(sessions)} sessions', flush=True)
    # Availability is equal per case, state, policy and model, not merely pooled.
    counts = {}
    for r in cases:
        key = (r['case_id'], r['activity'], r['policy'])
        value = tuple(r[k] for k in ('windows', 'eligible_outcomes', 'pre_entry_predictions', 'offered_pre_entry_decisions', 'grid_windows'))
        if key in counts and counts[key] != value:
            raise ValueError('quote availability changed')
        counts[key] = value
    combined = [dict(r, source='combined_raw', split='raw_diagnostic') for r in cases if r['source'] in ('raw', 'raw_control')]
    result = dict(protocol, selected_spec=chosen, ranking=ranking, folds=folds, models=models,
                  cases=cases, summary=summarize(cases), combined_raw_summary=summarize(combined),
                  joint_checks=joint_checks(cases), predictions_sha256=file_hash(output / 'predictions.jsonl.gz'),
                  checks=dict(archived_baselines_reconstructed=True, all_frozen_widths_and_outcomes_identical=True,
                              eligibility_and_masks_identical=True, case_group_availability_identical=True,
                              raw_original_files_reverified=True, later_cases_excluded_from_selection=True))
    (output / 'research.json').write_text(json.dumps(result, indent=2) + '\n')
    for name in ('cases', 'summary', 'combined_raw_summary', 'joint_checks'):
        write_csv(output / (name.replace('_', '-') + '.csv'), result[name], list(result[name][0]))
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--admission', type=Path, required=True)
    parser.add_argument('--controls', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = run(args.admission, args.controls, args.output)
    print(json.dumps(dict(selected=result['selected_spec'], ranking=result['ranking'], joint_checks=result['joint_checks']), indent=2))
