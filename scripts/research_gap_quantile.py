#!/usr/bin/env python3
"""Fixed five-way ablation of oracle/mark gaps and adaptive quantile tracking."""
import argparse
from collections import defaultdict
import gzip
import json
import math
from pathlib import Path
import shutil
from statistics import mean

from adaptive_corridor import required_width
from capture_dataset import file_hash
from chronological_raw_priors import training_rows, floor_values, replay
from gap_quantile import SPEC, VARIANTS, fit, all_series
from investigate_capture import write_csv
from oracle_gap_features import SPEC as FEATURE_SPEC, load_context, attach
from research_bursty_pricing import losses, burst_score
from research_bursty_startup_raw import phase_cells, phase_error, availability_charge, paired
from research_expanded_bursty import DEPENDENCIES as OLD_DEPENDENCIES, context
from research_nonfrozen_pricing import POLICIES, fixed_mask, measures, selection_components, summarize
from research_preentry_bursty import AVAILABILITY, retention, load_inputs
from research_startup_admission import priced, verify_code
from startup_admission import SPECS as RULES, admit as old_admit

DEPENDENCIES = tuple(dict.fromkeys(('oracle_gap_features.py', 'gap_quantile.py', 'research_gap_quantile.py',
    'test_gap_quantile.py', 'audit_gap_quantile.py') + OLD_DEPENDENCIES))


def load_inputs_for_gap(previous_dir):
    previous = json.loads((previous_dir / 'research.json').read_text()); verify_code(previous_dir, previous)
    for n, k in (('predictions.jsonl.gz', 'predictions_sha256'), ('selection.json', 'selection_sha256'),
                 ('expanded-training-rows.jsonl.gz', 'training_rows_sha256')):
        if file_hash(previous_dir / n) != previous[k]:
            raise ValueError('retained expanded artifact differs')
    parent = previous
    for _ in range(2):
        directory = Path(parent['previous'])
        if file_hash(directory / 'research.json') != parent['previous_sha256']:
            raise ValueError('ancestor differs')
        parent = json.loads((directory / 'research.json').read_text()); verify_code(directory, parent)
    earlier_dir = Path(parent['previous'])
    if file_hash(earlier_dir / 'research.json') != parent['previous_sha256']:
        raise ValueError('earlier ancestor differs')
    ctx = load_inputs(earlier_dir)
    ctx['expanded_rawdays'] = dict(ctx['rawdays'])
    with gzip.open(previous_dir / 'expanded-training-rows.jsonl.gz', 'rt') as stream:
        for line in stream:
            row = json.loads(line)
            ctx['expanded_rawdays'].setdefault(row['period'], []).append(row)
    return previous, ctx


def add_context(ctx, points, output=None):
    """Feature support is fixed before validity, movement or admission is read."""
    records, coverage = [], []
    def one(rows, kind, key, values):
        annotated = attach(rows, values, min(r['start'] for r in rows))
        if output is not None:
            for row in annotated:
                records.append(dict(kind=kind, key=key, start=row['start'], feature=row['oracle_gap']))
        coverage.append(dict(kind=kind, key=key, rows=len(rows), supported=sum(r['oracle_gap'] is not None for r in annotated)))
        return annotated
    grouped = defaultdict(list)
    for row in ctx['original']:
        grouped[row['period']].append(row)
    ctx['original'] = [row for day, rows in grouped.items() for row in one(rows, 'normalized_training', day, points['normalized'].get(day, []))]
    ctx['expanded_rawdays'] = {day: one(rows, 'raw_training', day, points['raw'][day]) for day, rows in ctx['expanded_rawdays'].items()}
    for s in ctx['sessions']:
        if s['source'] in ('normalized', 'normalized_control'):
            values = points['normalized'][s['period']]
        elif s['source'] in ('raw', 'raw_control', 'raw_extended', 'raw_matched'):
            values = points['raw'][s['period']]
        else:
            values = []  # No cross-source substitution for native paired receipts.
        annotated = one([p['row'] for p in s['values']], 'session', s['id'], values)
        s['values'] = [dict(p, row=row) for p, row in zip(s['values'], annotated)]
    if output is not None:
        with gzip.open(output / 'gap-features.jsonl.gz', 'wt', compresslevel=5) as stream:
            for row in records:
                stream.write(json.dumps(row, separators=(',', ':')) + '\n')
    return coverage


def fit_prefix(ctx, prior, engine, overlay):
    rows, provenance = training_rows(ctx['original'], ctx['expanded_rawdays'], prior['training_periods'], prior['cutoff'], True)
    values = floor_values(priced(rows, engine, overlay), engine)
    reference = replay(values, prior['model'], 'floor10_burst_pool120')
    models = dict(timing=fit(reference, False), gap=fit(reference, True))
    if models['timing']['windows'] != models['gap']['windows']:
        raise ValueError('feature ablation training support differs')
    return dict(training_periods=prior['training_periods'], cutoff=prior['cutoff'], provenance=provenance, models=models)


def risk_cells(session, values, candidate):
    result = []
    for interval in session['intervals']:
        allpart = [p for p in values if interval['start'] <= p['row']['start'] < interval['end']
                   and p['width_ppm'] is not None and p['row']['activity_state'] == 'bursty']
        for phase, group in (('all', allpart), ('first12', allpart[:12]), ('later', allpart[12:])):
            part = [p for p in group if p['shadow_survived'] is not None and p['gap_floor_risk'] is not None]
            n = len(part)
            result.append(dict(candidate=candidate, source=session['source'], period=session['period'], split=session['split'],
                mode=session['mode'], hour=interval['hour'], phase=phase, windows=n,
                predicted=sum(p['gap_floor_risk'] for p in part) / n if n else None,
                observed=sum(required_width(p['row']) <= 1 for p in part) / n if n else None,
                brier=sum((p['gap_floor_risk'] - (required_width(p['row']) <= 1)) ** 2 for p in part) / n if n else None,
                log_loss=sum(-math.log(max(1e-9, p['gap_floor_risk'] if required_width(p['row']) <= 1 else 1 - p['gap_floor_risk'])) for p in part) / n if n else None))
    return result


def choose(ctx, previous_selection, engine_selection):
    scores, feasible = defaultdict(list), defaultdict(list); models, folds = [], []
    rule = next(r for r in RULES if r['name'] == POLICIES[0])
    for old, ef in zip(previous_selection['models'], engine_selection['models']):
        begin = old['training_days']
        if begin != ef['training_days']:
            raise ValueError('fold alignment differs')
        prior = old['sources']['existing']['prior']; engine, overlay = ef['engine'], ef['overlay']
        bundle = fit_prefix(ctx, prior, engine, overlay)
        models.append(dict(training_days=begin, **bundle))
        dates = next(f['scoring_days'] for f in previous_selection['folds'] if f['training_days'] == begin)
        inputs = []
        for s in ctx['sessions']:
            if s['source'] != 'normalized' or s['period'] not in dates:
                continue
            base = priced([p['row'] for p in s['values']], engine, overlay)
            reference = replay(floor_values(base, engine), prior['model'], 'floor10_burst_pool120')
            inputs.append((s, base, old_admit(base, rule), all_series(reference, bundle['models'])))
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
        print(f'gap selection {begin}', flush=True)
    ranking = sorted((dict(candidate=c, score=mean(scores[c]), folds=scores[c], availability_feasible=all(feasible[c]), index=i)
                      for i, c in enumerate(VARIANTS)), key=lambda r: (not r['availability_feasible'], r['score'], r['index']))
    old = next(r for r in previous_selection['ranking'] if r['candidate'] == 'existing:retained_pool:unchanged')
    new = next(r for r in ranking if r['candidate'] == 'retained_pool')
    if (old['score'], old['folds']) != (new['score'], new['folds']):
        raise ValueError('earlier benchmark did not reconstruct')
    return dict(selected=ranking[0]['candidate'], ranking=ranking, models=models, folds=folds)


def run(previous_dir, output):
    if output.exists():
        raise ValueError('preserve pinned research')
    previous, ctx = load_inputs_for_gap(previous_dir)
    declaration = dict(previous=str(previous_dir.resolve()), previous_sha256=file_hash(previous_dir / 'research.json'),
        dataset=previous['dataset'], dataset_sha256=previous['dataset_sha256'], spec=SPEC, feature_spec=FEATURE_SPEC, variants=VARIANTS,
        source_sha256={n: file_hash(Path(__file__).with_name(n)) for n in DEPENDENCIES}, availability_constraints=AVAILABILITY,
        target_survival=.48, band=[.43, .53], capture_started=False, live_candidate_promoted=False, independent_holdout=False,
        selection='Original earlier chronological folds, engines, objective, loss guard and retention constraints. Same feature support for timing/gap ablation; raw evaluation outcomes excluded from selection. Repeated later days are development comparisons.',
        frozen_and_non_bursty_pricing_and_admission_fixed=True)
    output.mkdir(parents=True); (output / 'source').mkdir()
    for n in DEPENDENCIES:
        shutil.copyfile(Path(__file__).with_name(n), output / 'source' / n)
    (output / 'protocol.json').write_text(json.dumps(declaration, indent=2) + '\n')
    points, bindings, checks = load_context(Path('.local/market-history'))
    coverage = add_context(ctx, points, output)
    del points
    (output / 'context-checks.json').write_text(json.dumps(dict(bindings=bindings, checks=checks, coverage=coverage), indent=2) + '\n')
    selection = choose(ctx, json.loads((previous_dir / 'selection.json').read_text()),
                       json.loads((ctx['prior_dir'] / 'selection.json').read_text()))
    (output / 'selection.json').write_text(json.dumps(selection, indent=2) + '\n')
    evaluated = [s for s in ctx['sessions'] if s['source'] != 'normalized' or s['period'] not in ctx['data']['dates'][:14]]
    models, cases, phases, risks = {}, [], [], []
    saved = {c: {p: {} for p in POLICIES} for c in VARIANTS}
    refs = {(r['policy'], r['case_id'], r['activity']): r for r in previous['cases'] if r['candidate'] == 'existing:retained_pool:unchanged'}
    reconstructed = 0
    with gzip.open(output / 'predictions.jsonl.gz', 'wt', compresslevel=5) as stream:
        for index, s in enumerate(evaluated):
            key, engine, overlay = context(ctx, s)
            prior = previous['models'][key]['existing']['prior']
            if key not in models:
                models[key] = fit_prefix(ctx, prior, engine, overlay)
            reference = replay(floor_values(s['values'], engine), prior['model'], 'floor10_burst_pool120')
            alternatives = all_series(reference, models[key]['models'])
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
                    if candidate == 'retained_pool':
                        for cell in cells:
                            old = refs[(policy, cell['case_id'], cell['activity'])]
                            for field in ('windows', 'survived', 'eligible_outcomes', 'mean_width_ppm', 'full_window_pinball_ppm'):
                                if cell[field] != old[field]:
                                    raise ValueError('retained benchmark differs: ' + field)
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
                                mark_gap_ppm=g['mark_gap_ppm'] if g else None), separators=(',', ':')) + '\n')
            if index % 10 == 0:
                print(f'gap replay {index + 1}/{len(evaluated)}', flush=True)
    pairs = [r for c, policies in saved.items() for p, values in policies.items() for r in paired(evaluated, values, c, p)]
    result = dict(declaration, selected=selection['selected'], ranking=selection['ranking'], models=models,
        evaluated_sessions=len(evaluated), evaluated_intervals=sum(len(s['intervals']) for s in evaluated),
        cases=cases, phases=phases, risk_report=risks, paired=pairs, summary=summarize(cases),
        selection_sha256=file_hash(output / 'selection.json'), predictions_sha256=file_hash(output / 'predictions.jsonl.gz'),
        features_sha256=file_hash(output / 'gap-features.jsonl.gz'), context_checks_sha256=file_hash(output / 'context-checks.json'),
        checks=dict(benchmark_cells_reconstructed=reconstructed, benchmark_selection_reconstructed=True,
                    admission_fixed=True, non_bursty_pricing_fixed=True, identical_paired_paths=True,
                    shared_timing_gap_training_support=True, mark_is_predictor_only=True))
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
