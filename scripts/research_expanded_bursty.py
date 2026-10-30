#!/usr/bin/env python3
"""Controlled expanded-raw ablation of the pinned bursty formulas."""
import argparse
from collections import Counter, defaultdict
import gzip
import json
from pathlib import Path
import shutil
from statistics import mean

from adaptive_corridor import required_width
from calibrated_bursty import SPEC, VARIANTS, all_series, admit, fit, fit_floor, name
from capture_dataset import file_hash
from chronological_raw_priors import training_rows, floor_values, replay, fit_bundle
from fetch_expanded_bursty_training import DAYS
from investigate_capture import write_csv
from research_bursty_pricing import losses, burst_score
from research_bursty_startup_raw import phase_cells, phase_error, availability_charge, paired
from research_calibrated_bursty import DEPENDENCIES as OLD_DEPENDENCIES, risk_cells
from research_nonfrozen_pricing import POLICIES, fixed_mask, measures, selection_components, summarize, verify_raw
from research_oracle_history import observations
from research_preentry_bursty import AVAILABILITY, retention, load_inputs
from research_raw_flat_panels import parse_raw, prepare_rows
from research_startup_admission import priced, verify_code
from startup_admission import SPECS as RULES, admit as old_admit

SOURCES = ('existing', 'expanded')
DEPENDENCIES = tuple(dict.fromkeys(('research_expanded_bursty.py', 'fetch_expanded_bursty_training.py', 'summarize_expanded_bursty.py', 'audit_expanded_bursty.py',
                                    'test_expanded_bursty.py') + OLD_DEPENDENCIES))


def candidate(source, method, gate):
    return source + ':' + name(method, gate)


def expanded_bundle(ctx, bundle, engine, overlay):
    """Only matching earlier training dates can be replaced, never added twice."""
    periods, cutoff = bundle['training_periods'], bundle['cutoff']
    prior = fit_bundle(ctx['original'], ctx['expanded_rawdays'], periods, cutoff, engine, overlay, True)
    rows, provenance = training_rows(ctx['original'], ctx['expanded_rawdays'], periods, cutoff, True)
    values = floor_values(priced(rows, engine, overlay), engine)
    reference = replay(values, prior['model'], 'floor10_burst_pool120')
    return dict(training_periods=periods, cutoff=cutoff, provenance=provenance, prior=prior,
                model=fit(values, reference, fit_floor(values)))


def load_expansion(ctx, raw, previous_dir):
    protocol = json.loads((raw / 'download-protocol.json').read_text())
    if protocol['previous_sha256'] != file_hash(previous_dir / 'research.json'):
        raise ValueError('download parent differs')
    if protocol['dataset_sha256'] != ctx['previous']['dataset_sha256']:
        raise ValueError('download dataset differs')
    if protocol['spec'] != json.loads(json.dumps(SPEC)) or protocol['variants'] != json.loads(json.dumps(VARIANTS)):
        raise ValueError('formula changed after download declaration')
    for filename, key in (('fetch-source.py', 'source_sha256'), ('prepare-source.py', 'preparer_sha256')):
        if file_hash(raw / filename) != protocol[key]:
            raise ValueError('download source snapshot differs')
    verify_raw(dict(raw=str(raw), raw_manifest_sha256=file_hash(raw / 'download-manifest.json')))
    manifest = json.loads((raw / 'download-manifest.json').read_text())
    if sorted((r['path'], r['url']) for r in manifest['files']) != sorted((r['path'], r['url']) for r in protocol['requests']):
        raise ValueError('download requests differ')
    if tuple(p['day'] for p in protocol['panels']) != DAYS:
        raise ValueError('declared training dates differ')
    upstream = json.loads((Path(ctx['data']['history']) / 'research.json').read_text())
    normroot = Path(upstream['source_manifest_path']).parent
    normfiles = json.loads((normroot / 'download-manifest.json').read_text())['files']
    added, checks = {}, []
    for panel in protocol['panels']:
        day = panel['day']
        files = sorted((f for f in manifest['files'] if f['day'] == day), key=lambda f: f['at_ms'])
        if len(files) != 1440 or [f['at_ms'] for f in files] != list(range(panel['start'], panel['end'], 60_000)):
            raise ValueError('full raw day missing minutes')
        observed, markers = parse_raw(files, raw)
        rows = prepare_rows(observed, panel, markers)
        added[day] = rows
        normalfile = next(f for f in normfiles if f['date'] == day)
        normalized, _ = observations(normroot / normalfile['path'], panel['start'], panel['end'])
        prices = dict(observed)
        common = [(at, price) for at, price in normalized if at in prices]
        mismatches = sum(prices[at] != price for at, price in common)
        if not common or mismatches:
            raise ValueError('raw/normalized oracle crosscheck failed')
        norm = [r for r in ctx['original'] if r['period'] == day]
        def profile(values):
            part = [r for r in values if r['valid'] and r['activity_state'] == 'bursty']
            return dict(rows=len(values), valid=sum(r['valid'] for r in values), bursty=len(part),
                        floor_survivors=sum(required_width(r) <= 1 for r in part),
                        market_regimes=dict(Counter(r['market_regime'] for r in part)),
                        activity_states=dict(Counter(r['activity_state'] for r in values if r['valid'])))
        checks.append(dict(day=day, minutes=len(files), messages=len(observed), disconnect_markers=len(markers),
                           shared_timestamps=len(common), mismatches=mismatches, raw=profile(rows), normalized=profile(norm)))
    ctx['expanded_rawdays'] = dict(ctx['rawdays'], **added)
    return added, checks


def choose(ctx, previous_selection, engine_selection):
    scores, feasible = defaultdict(list), defaultdict(list)
    folds, models, risks = [], [], []
    rule = next(r for r in RULES if r['name'] == POLICIES[0])
    for old, ef in zip(previous_selection['models'], engine_selection['models']):
        begin = old['training_days']
        if begin != ef['training_days']:
            raise ValueError('fold alignment differs')
        engine, overlay = ef['engine'], ef['overlay']
        oldprior = next(m for m in ctx['prior_selection']['models'] if m['training_days'] == begin)['priors']['raw_earlier']
        fitting = dict(existing=dict(old, prior=oldprior), expanded=expanded_bundle(ctx, old, engine, overlay))
        models.append(dict(training_days=begin, sources=fitting))
        dates = next(f['scoring_days'] for f in previous_selection['folds'] if f['training_days'] == begin)
        inputs = []
        for s in ctx['sessions']:
            if s['source'] != 'normalized' or s['period'] not in dates:
                continue
            base = priced([p['row'] for p in s['values']], engine, overlay)
            floor = floor_values(base, engine)
            mask = old_admit(base, rule)
            alternatives = {}
            for source, bundle in fitting.items():
                ref = replay(floor, bundle['prior']['model'], 'floor10_burst_pool120')
                alternatives[source] = all_series(floor, ref, bundle['model'])
                risks.extend(dict(r, source_model=source, training_days=begin) for r in risk_cells(s, alternatives[source]['retained_pool']))
            reference = measures(s, fixed_mask(alternatives['existing']['retained_pool'], mask), 'reference', rule['name'])
            inputs.append((s, base, mask, alternatives, reference))
        original_loss = losses([p for _, values, _, _, _ in inputs for p in values])
        for source in SOURCES:
            for method, gate in VARIANTS:
                c = candidate(source, method, gate)
                cases, phases, refs, full = [], [], [], []
                for s, _, mask, alternatives, reference in inputs:
                    values = admit(fixed_mask(alternatives[source][method], mask), gate)
                    cases.extend(measures(s, values, c, rule['name']))
                    phases.extend(phase_cells(s, values, c, rule['name']))
                    refs.extend(reference)
                    full.extend(alternatives[source][method])
                mode_scores, constraints, charges = {}, {}, {}
                for mode in ('restart', 'continuous'):
                    part = [r for r in cases if r['mode'] == mode]
                    ref = [r for r in refs if r['mode'] == mode]
                    constraints[mode] = retention(part, ref)
                    charges[mode] = availability_charge(part, ref)
                    mode_scores[mode] = (selection_components(part) + burst_score(part)
                                        + .5 * phase_error([r for r in phases if r['mode'] == mode]) + charges[mode])
                loss = losses(full)
                guard = sum(100 * max(0, loss[g]['pinball_ppm'] / b['pinball_ppm'] - 1.1)
                            for g, b in original_loss.items() if b['windows'] >= 20 and b['pinball_ppm'])
                score = mean(mode_scores.values()) + .25 * abs(mode_scores['restart'] - mode_scores['continuous']) + guard
                scores[c].append(score)
                feasible[c].append(all(r['feasible'] for r in constraints.values()))
                folds.append(dict(candidate=c, training_days=begin, scoring_days=dates, score=score,
                                  mode_scores=mode_scores, retention=constraints, availability_charge=charges,
                                  loss_guard=guard, full_reference_losses=loss))
        print(f'expanded selection {begin}', flush=True)
    ranking = sorted((dict(candidate=c, score=mean(scores[c]), folds=scores[c], availability_feasible=all(feasible[c]), index=i)
                      for i, c in enumerate(candidate(s, m, g) for s in SOURCES for m, g in VARIANTS)),
                     key=lambda r: (not r['availability_feasible'], r['score'], r['index']))
    for old in previous_selection['ranking']:
        actual = next(r for r in ranking if r['candidate'] == 'existing:' + old['candidate'])
        if (actual['score'], actual['folds'], actual['availability_feasible']) != (old['score'], old['folds'], old['availability_feasible']):
            raise ValueError('existing selection did not reconstruct')
    return dict(selected=ranking[0]['candidate'], ranking=ranking, folds=folds, models=models, risk_report=risks)


def context(ctx, session):
    if session['source'] in ('raw_control', 'normalized_control', 'raw_extended', 'raw_matched'):
        key = session['period']
        overlay = ctx['control']['models'][key]['overlay']
    elif session['source'] == 'raw':
        key = 'raw_january'
        overlay = ctx['rawold']['models'][session['period']]['overlays']['frozen_floor_53']['hurdle_all_120']
    else:
        key = 'original_final'
        overlay = ctx['pricing']['models']['hurdle_all_120']
    return key, ctx['base']['models'][key]['engine'], overlay


def run(previous_dir, raw, output):
    if output.exists():
        raise ValueError('preserve prior experiments')
    previous = json.loads((previous_dir / 'research.json').read_text())
    verify_code(previous_dir, previous)
    for n, k in (('predictions.jsonl.gz', 'predictions_sha256'), ('selection.json', 'selection_sha256')):
        if file_hash(previous_dir / n) != previous[k]:
            raise ValueError('previous artifact differs')
    static_dir = Path(previous['previous'])
    if file_hash(static_dir / 'research.json') != previous['previous_sha256']:
        raise ValueError('static ancestor differs')
    static = json.loads((static_dir / 'research.json').read_text())
    verify_code(static_dir, static)
    ctx = load_inputs(Path(static['previous']))
    if file_hash(Path(static['previous']) / 'research.json') != static['previous_sha256']:
        raise ValueError('prior ancestor differs')
    ctx['prior_selection'] = json.loads((Path(static['previous']) / 'selection.json').read_text())
    added, raw_checks = load_expansion(ctx, raw, previous_dir)
    evaluated = [s for s in ctx['sessions'] if s['source'] != 'normalized' or s['period'] not in ctx['data']['dates'][:14]]
    declaration = dict(previous=str(previous_dir.resolve()), previous_sha256=file_hash(previous_dir / 'research.json'),
                       dataset=previous['dataset'], dataset_sha256=previous['dataset_sha256'], raw=str(raw.resolve()),
                       raw_manifest_sha256=file_hash(raw / 'download-manifest.json'), raw_protocol_sha256=file_hash(raw / 'download-protocol.json'),
                       source_sha256={n: file_hash(Path(__file__).with_name(n)) for n in DEPENDENCIES},
                       spec=SPEC, sources=SOURCES, variants=[candidate(s, m, g) for s in SOURCES for m, g in VARIANTS],
                       availability_constraints=AVAILABILITY, target_survival=.48, band=[.43, .53],
                       evaluated_sessions=len(evaluated), selection='Fixed prior formulas and chronological folds; existing versus four additional complete raw replacements on the same monthly dates. Previous engines, frozen masks, objective, loss guard and retention constraints unchanged.',
                       independent_holdout=False, raw_evaluation_excluded_from_selection=True,
                       frozen_and_non_bursty_pricing_and_admission_fixed=True, capture_started=False, live_candidate_promoted=False)
    output.mkdir(parents=True)
    (output / 'source').mkdir()
    for n in DEPENDENCIES:
        shutil.copyfile(Path(__file__).with_name(n), output / 'source' / n)
    (output / 'protocol.json').write_text(json.dumps(declaration, indent=2) + '\n')
    with gzip.open(output / 'expanded-training-rows.jsonl.gz', 'wt') as stream:
        for day in sorted(added):
            for row in added[day]:
                stream.write(json.dumps(row, separators=(',', ':')) + '\n')
    selection = choose(ctx, json.loads((previous_dir / 'selection.json').read_text()),
                       json.loads((ctx['prior_dir'] / 'selection.json').read_text()))
    (output / 'selection.json').write_text(json.dumps(selection, indent=2) + '\n')
    models, cases, phases, risks = {}, [], [], []
    saved = {c: {p: {} for p in POLICIES} for c in declaration['variants']}
    refs = {(r['candidate'], r['policy'], r['case_id'], r['activity']): r for r in previous['cases']}
    reconstructed, price_changes, refusals = 0, Counter(), Counter()
    with gzip.open(output / 'predictions.jsonl.gz', 'wt', compresslevel=5) as stream:
        for index, s in enumerate(evaluated):
            key, engine, overlay = context(ctx, s)
            if key not in models:
                oldprior = ctx['previous']['models'][key]['raw_earlier']
                models[key] = dict(existing=dict(previous['models'][key], prior=oldprior),
                                   expanded=expanded_bundle(ctx, previous['models'][key], engine, overlay))
            floor = floor_values(s['values'], engine)
            reference = replay(floor, models[key]['existing']['prior']['model'], 'floor10_burst_pool120')
            masks = {p: old_admit(s['values'], next(r for r in RULES if r['name'] == p)) for p in POLICIES}
            for source, bundle in models[key].items():
                retained = replay(floor, bundle['prior']['model'], 'floor10_burst_pool120')
                alternatives = all_series(floor, retained, bundle['model'])
                risks.extend(dict(r, source_model=source) for r in risk_cells(s, alternatives['retained_pool']))
                for method, gate in VARIANTS:
                    c = candidate(source, method, gate)
                    for policy, mask in masks.items():
                        values = admit(fixed_mask(alternatives[method], mask), gate)
                        for a, b, m in zip(values, reference, mask):
                            if (a['width_ppm'] is None, a['shadow_survived'] is None) != (b['width_ppm'] is None, b['shadow_survived'] is None):
                                raise ValueError('reference eligibility changed')
                            if b['row']['activity_state'] != 'bursty' and (a['width_ppm'], a['shadow_survived'], a['paused']) != (b['width_ppm'], b['shadow_survived'], m['paused']):
                                raise ValueError('non-bursty price/admission changed')
                        rows = measures(s, values, c, policy)
                        if source == 'existing':
                            for cell in rows:
                                old = refs[(name(method, gate), policy, cell['case_id'], cell['activity'])]
                                for field in ('windows', 'survived', 'eligible_outcomes', 'mean_width_ppm', 'full_window_pinball_ppm'):
                                    if cell[field] != old[field]:
                                        raise ValueError('existing case did not reconstruct: ' + field)
                                reconstructed += 1
                        cases.extend(rows)
                        phases.extend(phase_cells(s, values, c, policy))
                        saved[c][policy][s['id']] = [p for p in values if p['row']['activity_state'] == 'bursty' and p['shadow_survived'] is not None]
                        for p, b in zip(values, reference):
                            if p['row']['activity_state'] == 'bursty':
                                price_changes[c] += p['width_ppm'] != b['width_ppm']
                                refusals[c] += p['calibrated_refusal']
                                stream.write(json.dumps(dict(candidate=c, policy=policy, session=s['id'], start=p['row']['start'],
                                    width=p['width_ppm'], shadow=p['shadow_survived'], paused=p['paused'],
                                    minimum_width_survived=required_width(p['row']) <= 1 if p['shadow_survived'] is not None else None,
                                    static=p['risk_static'], chrono=p['risk_chrono'], context=p['risk_context'],
                                    correction=p['price_correction'], requested=p['price_requested'], mass=p['local_mass'],
                                    effective=p['local_effective'], risk_mass=p['risk_effective_mass']), separators=(',', ':')) + '\n')
            if index % 10 == 0:
                print(f'expanded replay {index + 1}/{len(evaluated)}', flush=True)
    pairs = [r for c, policies in saved.items() for p, values in policies.items() for r in paired(evaluated, values, c, p)]
    result = dict(declaration, selected=selection['selected'], ranking=selection['ranking'], models=models,
                  raw_checks=raw_checks, cases=cases, phases=phases, risk_report=risks, paired=pairs, summary=summarize(cases),
                  selection_sha256=file_hash(output / 'selection.json'), predictions_sha256=file_hash(output / 'predictions.jsonl.gz'),
                  training_rows_sha256=file_hash(output / 'expanded-training-rows.jsonl.gz'),
                  checks=dict(existing_case_cells_reconstructed=reconstructed, existing_selection_reconstructed=True,
                              price_changes=dict(price_changes), incremental_refusals=dict(refusals),
                              reference_eligibility_fixed=True, identical_paired_paths=True, non_bursty_pricing_fixed=True))
    for n, digest in declaration['source_sha256'].items():
        if file_hash(Path(__file__).with_name(n)) != digest:
            raise ValueError('source changed during replay')
    (output / 'research.json').write_text(json.dumps(result, indent=2) + '\n')
    for n in ('cases', 'phases', 'risk_report', 'paired', 'summary'):
        write_csv(output / (n + '.csv'), result[n], list(result[n][0]))
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--previous', type=Path, required=True)
    parser.add_argument('--raw', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = run(args.previous, args.raw, args.output)
    print(json.dumps(dict(selected=result['selected'], ranking=result['ranking'], raw_checks=result['raw_checks']), indent=2))
