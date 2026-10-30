#!/usr/bin/env python3
"""Frozen-model comparison of shared and isolated bursty calibration feedback."""
import argparse
from collections import defaultdict
import gzip
import json
from pathlib import Path
import shutil
from statistics import mean

from adaptive_corridor import required_width
from audit_gap_quantile import cached_context
from bursty_feedback import SPEC, VARIANTS, all_series
from capture_dataset import file_hash
from chronological_raw_priors import floor_values, replay
from investigate_capture import write_csv
from research_bursty_pricing import losses, burst_score
from research_bursty_startup_raw import phase_cells, phase_error, availability_charge, paired
from research_expanded_bursty import context
from research_gap_quantile import DEPENDENCIES as PARENT_DEPENDENCIES, load_inputs_for_gap, risk_cells
from research_nonfrozen_pricing import POLICIES, fixed_mask, measures, selection_components, summarize, verify_raw
from research_preentry_bursty import AVAILABILITY, retention
from research_startup_admission import priced, verify_code
from startup_admission import SPECS as RULES, admit as old_admit

DEPENDENCIES = tuple(dict.fromkeys(('bursty_feedback.py', 'research_bursty_feedback.py',
    'test_bursty_feedback.py', 'audit_bursty_feedback.py') + PARENT_DEPENDENCIES))


def load_cached(previous_dir):
    previous = json.loads((previous_dir / 'research.json').read_text()); verify_code(previous_dir, previous)
    for n, k in (('selection.json', 'selection_sha256'), ('predictions.jsonl.gz', 'predictions_sha256'),
                 ('gap-features.jsonl.gz', 'features_sha256'), ('context-checks.json', 'context_checks_sha256')):
        if file_hash(previous_dir / n) != previous[k]:
            raise ValueError('preceding gap research artifact differs')
    expanded_dir = Path(previous['previous'])
    if file_hash(expanded_dir / 'research.json') != previous['previous_sha256']:
        raise ValueError('expanded ancestor differs')
    expanded, ctx = load_inputs_for_gap(expanded_dir)
    checked_features = cached_context(ctx, previous_dir / 'gap-features.jsonl.gz')
    bindings = json.loads((previous_dir / 'context-checks.json').read_text())['bindings']
    for binding in bindings:
        root = Path(binding['root']); digest = binding['manifest_sha256']
        if file_hash(root / 'download-manifest.json') != digest:
            raise ValueError('context manifest differs')
        if 'monthly-samples' in root.name:
            for f in json.loads((root / 'download-manifest.json').read_text())['files']:
                if file_hash(root / f['path']) != f['sha256']:
                    raise ValueError('normalized context response differs')
        else:
            verify_raw(dict(raw=str(root), raw_manifest_sha256=digest))
    ctx['expanded_selection'] = json.loads((expanded_dir / 'selection.json').read_text())
    return previous, expanded, ctx, checked_features


def choose(ctx, previous_selection, engine_selection):
    scores, feasible = defaultdict(list), defaultdict(list); folds = []
    rule = next(r for r in RULES if r['name'] == POLICIES[0])
    for old, ef in zip(previous_selection['models'], engine_selection['models']):
        begin = old['training_days']
        if begin != ef['training_days']:
            raise ValueError('fold alignment differs')
        prefix = next(m for m in ctx['expanded_selection']['models'] if m['training_days'] == begin)
        prior = prefix['sources']['existing']['prior']; engine, overlay = ef['engine'], ef['overlay']
        dates = next(f['scoring_days'] for f in previous_selection['folds'] if f['training_days'] == begin)
        inputs = []
        for s in ctx['sessions']:
            if s['source'] != 'normalized' or s['period'] not in dates:
                continue
            base = priced([p['row'] for p in s['values']], engine, overlay)
            reference = replay(floor_values(base, engine), prior['model'], 'floor10_burst_pool120')
            inputs.append((s, base, old_admit(base, rule), all_series(reference, old['models'])))
        original_loss = losses([p for _, values, _, _ in inputs for p in values])
        for candidate in VARIANTS:
            cases, phases, refs, full = [], [], [], []
            for s, _, mask, alternatives in inputs:
                values = fixed_mask(alternatives[candidate], mask)
                cases.extend(measures(s, values, candidate, rule['name']))
                phases.extend(phase_cells(s, values, candidate, rule['name']))
                refs.extend(measures(s, fixed_mask(alternatives['retained_pool'], mask), 'reference', rule['name']))
                full.extend(alternatives[candidate])
            mode_scores, constraints, charges = {}, {}, {}
            for mode in ('restart', 'continuous'):
                part = [r for r in cases if r['mode'] == mode]; ref = [r for r in refs if r['mode'] == mode]
                constraints[mode] = retention(part, ref); charges[mode] = availability_charge(part, ref)
                mode_scores[mode] = selection_components(part) + burst_score(part) + .5 * phase_error([r for r in phases if r['mode'] == mode]) + charges[mode]
            loss = losses(full)
            guard = sum(100 * max(0, loss[g]['pinball_ppm'] / b['pinball_ppm'] - 1.1)
                        for g, b in original_loss.items() if b['windows'] >= 20 and b['pinball_ppm'])
            score = mean(mode_scores.values()) + .25 * abs(mode_scores['restart'] - mode_scores['continuous']) + guard
            scores[candidate].append(score); feasible[candidate].append(all(r['feasible'] for r in constraints.values()))
            folds.append(dict(candidate=candidate, training_days=begin, scoring_days=dates, score=score,
                              mode_scores=mode_scores, retention=constraints, availability_charge=charges,
                              loss_guard=guard, full_reference_losses=loss))
        print(f'feedback selection {begin}', flush=True)
    ranking = sorted((dict(candidate=c, score=mean(scores[c]), folds=scores[c], availability_feasible=all(feasible[c]), index=i)
                      for i, c in enumerate(VARIANTS)), key=lambda r: (not r['availability_feasible'], r['score'], r['index']))
    for old in previous_selection['ranking']:
        new = next(r for r in ranking if r['candidate'] == old['candidate'])
        if (old['score'], old['folds'], old['availability_feasible']) != (new['score'], new['folds'], new['availability_feasible']):
            raise ValueError('preceding selection differs: ' + old['candidate'])
    return dict(selected=ranking[0]['candidate'], ranking=ranking, models=previous_selection['models'], folds=folds)


def run(previous_dir, output):
    if output.exists():
        raise ValueError('preserve pinned research')
    previous, expanded, ctx, checked_features = load_cached(previous_dir)
    declaration = dict(previous=str(previous_dir.resolve()), previous_sha256=file_hash(previous_dir / 'research.json'),
        dataset=previous['dataset'], dataset_sha256=previous['dataset_sha256'], spec=SPEC, variants=VARIANTS,
        source_sha256={n: file_hash(Path(__file__).with_name(n)) for n in DEPENDENCIES}, availability_constraints=AVAILABILITY,
        feature_cache=str((previous_dir / 'gap-features.jsonl.gz').resolve()), features_sha256=previous['features_sha256'],
        context_checks=str((previous_dir / 'context-checks.json').resolve()), context_checks_sha256=previous['context_checks_sha256'],
        target_survival=.48, band=[.43, .53], capture_started=False, live_candidate_promoted=False, independent_holdout=False,
        selection='Original chronological folds, engines, objective, loss guard and retention constraints. Numerical timing/gap fits and underlying retained-reference pricing remain fixed. Only the new correction layer changes transfer of matured errors. Raw evaluation outcomes excluded from selection; repeated later days remain development comparisons.',
        fitted_models_unchanged=True, frozen_and_non_bursty_pricing_and_admission_fixed=True)
    output.mkdir(parents=True); (output / 'source').mkdir()
    for n in DEPENDENCIES:
        shutil.copyfile(Path(__file__).with_name(n), output / 'source' / n)
    (output / 'protocol.json').write_text(json.dumps(declaration, indent=2) + '\n')
    selection = choose(ctx, json.loads((previous_dir / 'selection.json').read_text()),
                       json.loads((ctx['prior_dir'] / 'selection.json').read_text()))
    (output / 'selection.json').write_text(json.dumps(selection, indent=2) + '\n')
    evaluated = [s for s in ctx['sessions'] if s['source'] != 'normalized' or s['period'] not in ctx['data']['dates'][:14]]
    cases, phases, risks = [], [], []
    saved = {c: {p: {} for p in POLICIES} for c in VARIANTS}
    refs = {(r['candidate'], r['policy'], r['case_id'], r['activity']): r for r in previous['cases']}
    reconstructed = 0
    with gzip.open(output / 'predictions.jsonl.gz', 'wt', compresslevel=5) as stream:
        for index, s in enumerate(evaluated):
            key, engine, _ = context(ctx, s)
            prior = expanded['models'][key]['existing']['prior']
            reference = replay(floor_values(s['values'], engine), prior['model'], 'floor10_burst_pool120')
            alternatives = all_series(reference, previous['models'][key]['models'])
            masks = {p: old_admit(s['values'], next(r for r in RULES if r['name'] == p)) for p in POLICIES}
            for candidate, prices in alternatives.items():
                if candidate != 'retained_pool':
                    risks.extend(risk_cells(s, prices, candidate))
                for policy, mask in masks.items():
                    values = fixed_mask(prices, mask)
                    for a, b, m in zip(values, reference, mask):
                        if (a['width_ppm'] is None, a['shadow_survived'] is None, a['paused']) != (b['width_ppm'] is None, b['shadow_survived'] is None, m['paused']):
                            raise ValueError('eligibility or admission changed')
                        if b['row']['activity_state'] != 'bursty' and (a['width_ppm'], a['shadow_survived']) != (b['width_ppm'], b['shadow_survived']):
                            raise ValueError('non-bursty price changed')
                    cells = measures(s, values, candidate, policy)
                    if candidate in previous['variants']:
                        for cell in cells:
                            old = refs[(candidate, policy, cell['case_id'], cell['activity'])]
                            for field in ('windows', 'survived', 'eligible_outcomes', 'mean_width_ppm', 'full_window_pinball_ppm'):
                                if cell[field] != old[field]:
                                    raise ValueError('preceding candidate differs: ' + candidate + ' / ' + field)
                            reconstructed += 1
                    cases.extend(cells); phases.extend(phase_cells(s, values, candidate, policy))
                    saved[candidate][policy][s['id']] = [p for p in values if p['row']['activity_state'] == 'bursty' and p['shadow_survived'] is not None]
                    for p in values:
                        if p['row']['activity_state'] == 'bursty':
                            g = p['row'].get('oracle_gap')
                            stream.write(json.dumps(dict(candidate=candidate, policy=policy, session=s['id'], start=p['row']['start'],
                                width=p['width_ppm'], shadow=p['shadow_survived'], paused=p['paused'],
                                minimum_width_survived=required_width(p['row']) <= 1 if p['shadow_survived'] is not None else None,
                                risk=p['gap_floor_risk'], forecast=p['gap_forecast'], log_correction=p['gap_log_correction'],
                                supported=p['gap_supported'], observed_at=g['observed_at'] if g else None,
                                mark_gap_ppm=g['mark_gap_ppm'] if g else None,
                                components=p.get('feedback_components', [])), separators=(',', ':')) + '\n')
            if index % 10 == 0:
                print(f'feedback replay {index + 1}/{len(evaluated)}', flush=True)
    pairs = [r for c, policies in saved.items() for p, values in policies.items() for r in paired(evaluated, values, c, p)]
    result = dict(declaration, selected=selection['selected'], ranking=selection['ranking'], models=previous['models'],
        evaluated_sessions=len(evaluated), evaluated_intervals=sum(len(s['intervals']) for s in evaluated),
        cases=cases, phases=phases, risk_report=risks, paired=pairs, summary=summarize(cases),
        selection_sha256=file_hash(output / 'selection.json'), predictions_sha256=file_hash(output / 'predictions.jsonl.gz'),
        checks=dict(preceding_candidate_cells_reconstructed=reconstructed, preceding_selection_reconstructed=True,
                    feature_records_verified=checked_features, fitted_models_unchanged=True, admission_fixed=True,
                    non_bursty_pricing_fixed=True, identical_paired_paths=True))
    for n, digest in declaration['source_sha256'].items():
        if file_hash(Path(__file__).with_name(n)) != digest:
            raise ValueError('source changed during research')
    (output / 'research.json').write_text(json.dumps(result, indent=2) + '\n')
    for n in ('cases', 'phases', 'risk_report', 'paired', 'summary'):
        write_csv(output / (n + '.csv'), result[n], list(result[n][0]))
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--previous', type=Path, required=True); parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(); r = run(args.previous, args.output)
    print(json.dumps(dict(selected=r['selected'], ranking=r['ranking'], checks=r['checks']), indent=2))
