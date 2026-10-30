#!/usr/bin/env python3
"""Run a bounded automatic search; freeze the shortlist before later diagnostics."""
import argparse
import gzip
import json
from pathlib import Path
import shutil
from statistics import mean
import time

from bursty_feedback import series as binary_series
from bursty_optimizer import SPACE, SPEC, BayesianSearch, anchors, cache_forecasts, replay as optimize_replay
from capture_dataset import file_hash
from chronological_raw_priors import floor_values, replay
from investigate_capture import write_csv
from research_bursty_residual import DEPENDENCIES as PARENT_DEPENDENCIES, load_cached
from research_bursty_pricing import losses, burst_score
from research_bursty_startup_raw import phase_cells, phase_error, availability_charge, paired
from research_expanded_bursty import context
from research_nonfrozen_pricing import POLICIES, fixed_mask, measures, selection_components, summarize
from research_preentry_bursty import AVAILABILITY, retention
from research_startup_admission import priced, verify_code
from startup_admission import SPECS as RULES, admit

DEPENDENCIES = tuple(dict.fromkeys(('bursty_optimizer.py', 'research_bursty_optimizer.py',
                                  'test_bursty_optimizer.py') + PARENT_DEPENDENCIES))


def dump(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + '\n')


def inputs_for_search(ctx, selection, engine_selection):
    folds = []
    rule = next(r for r in RULES if r['name'] == POLICIES[0])
    for bundle, ef in zip(selection['models'], engine_selection['models']):
        begin = bundle['training_days']
        if begin != ef['training_days']:
            raise ValueError('fold alignment differs')
        prefix = next(m for m in ctx['expanded_selection']['models'] if m['training_days'] == begin)
        prior = prefix['sources']['existing']['prior']
        dates = next(f['scoring_days'] for f in selection['folds'] if f['training_days'] == begin)
        if any(day >= min(dates) for day in bundle['training_periods']):
            raise ValueError('forecast fit crosses scoring boundary')
        inputs = []; baseline = []
        for s in ctx['sessions']:
            if s['source'] != 'normalized' or s['period'] not in dates:
                continue
            base = priced([p['row'] for p in s['values']], ef['engine'], ef['overlay'])
            ref = replay(floor_values(base, ef['engine']), prior['model'], 'floor10_burst_pool120')
            mask = admit(base, rule)
            inputs.append(dict(session={k: v for k, v in s.items() if k != 'values'}, reference=ref,
                               mask=mask, forecasts=cache_forecasts(ref, bundle['models']),
                               refs=measures(s, fixed_mask(ref, mask), 'reference', rule['name'])))
            baseline.extend(base)
        folds.append(dict(training_days=begin, scoring_days=dates, inputs=inputs,
                          priors=selection['residual_priors'][str(begin)], baseline_loss=losses(baseline)))
        print('cached search fold ' + str(begin), flush=True)
    return folds


def evaluate(params, folds):
    results = []
    for fold in folds:
        cases, phases, refs, full = [], [], [], []
        for item in fold['inputs']:
            prices = optimize_replay(item['reference'], item['forecasts'][params['source']],
                                     fold['priors'][params['source']], params)
            values = fixed_mask(prices, item['mask']); s = item['session']
            cases.extend(measures(s, values, 'trial', POLICIES[0]))
            phases.extend(phase_cells(s, values, 'trial', POLICIES[0]))
            refs.extend(item['refs']); full.extend(prices)
        mode_scores, constraints = {}, {}
        for mode in ('restart', 'continuous'):
            part = [r for r in cases if r['mode'] == mode]; ref = [r for r in refs if r['mode'] == mode]
            constraints[mode] = retention(part, ref)
            mode_scores[mode] = (selection_components(part) + burst_score(part)
                + .5 * phase_error([r for r in phases if r['mode'] == mode]) + availability_charge(part, ref))
        loss = losses(full)
        guard = sum(100 * max(0, loss[g]['pinball_ppm'] / b['pinball_ppm'] - 1.1)
                    for g, b in fold['baseline_loss'].items() if b['windows'] >= 20 and b['pinball_ppm'])
        score = mean(mode_scores.values()) + .25 * abs(mode_scores['restart'] - mode_scores['continuous']) + guard
        results.append(dict(training_days=fold['training_days'], scoring_days=fold['scoring_days'],
                            score=score, mode_scores=mode_scores, retention=constraints, loss_guard=guard,
                            full_reference_losses=loss))
    return dict(score=mean(r['score'] for r in results), folds=results,
                feasible=all(c['feasible'] for r in results for c in r['retention'].values()))


def search(folds, previous_selection, trials, seed, output):
    optimizer = BayesianSearch(seed); records = []
    with (output / 'trials.jsonl').open('x') as stream:
        for i in range(trials):
            params = optimizer.ask(); started = time.monotonic()
            result = evaluate(params, folds)
            if i < len(anchors()):
                name = params['source'] + ('_ratio4h_prior' if params['learned_weight'] else '_ratio4h_neutral')
                old = next(r for r in previous_selection['ranking'] if r['candidate'] == name)
                if abs(result['score'] - old['score']) > 1e-10 or any(abs(r['score'] - v) > 1e-10 for r, v in zip(result['folds'], old['folds'])):
                    raise ValueError('cached anchor failed reconstruction: ' + name)
            optimizer.tell(params, result['score'] if result['feasible'] else 1000000.)
            record = dict(trial=i, params=params, **result, elapsed_seconds=time.monotonic() - started)
            stream.write(json.dumps(record, allow_nan=False) + '\n'); stream.flush(); records.append(record)
            print(f'trial {i + 1}/{trials}: {result["score"]:.6f}', flush=True)
    ranking = sorted(records, key=lambda r: (not r['feasible'], r['score'], r['trial']))
    champion = previous_selection['ranking'][0]
    best = ranking[0]
    selected = 'optimized' if best['feasible'] and best['score'] < champion['score'] else champion['candidate']
    result = dict(selected=selected, best_trial=best, retained_champion=champion,
                  ranking=[dict(trial=r['trial'], score=r['score'], feasible=r['feasible'], params=r['params']) for r in ranking],
                  diagnostic_shortlist=['retained_pool', 'gap_bursty', 'optimized'],
                  later_diagnostics_cannot_change_ranking=True, independent_holdout=False)
    dump(output / 'selection.json', result)
    return result


def diagnostics(ctx, previous, expanded, best, output):
    cases, phases = [], []; saved = {c: {p: {} for p in POLICIES} for c in ('retained_pool', 'gap_bursty', 'optimized')}
    evaluated = [s for s in ctx['sessions'] if s['source'] != 'normalized' or s['period'] not in ctx['data']['dates'][:14]]
    old_cells = {(r['candidate'], r['policy'], r['case_id'], r['activity']): r for r in previous['cases']}
    reconstructed = 0
    with gzip.open(output / 'predictions.jsonl.gz', 'wt', compresslevel=5) as stream:
        for index, s in enumerate(evaluated):
            key, engine, _ = context(ctx, s)
            prior = expanded['models'][key]['existing']['prior']
            ref = replay(floor_values(s['values'], engine), prior['model'], 'floor10_burst_pool120')
            models = previous['models'][key]['models']
            cached = cache_forecasts(ref, {best['source']: models[best['source']]})
            alternatives = dict(retained_pool=ref, gap_bursty=binary_series(ref, models['gap'], 'bursty'),
                                optimized=optimize_replay(ref, cached[best['source']], previous['residual_priors'][key][best['source']], best))
            for policy in POLICIES:
                mask = admit(s['values'], next(r for r in RULES if r['name'] == policy))
                for candidate, prices in alternatives.items():
                    values = fixed_mask(prices, mask)
                    for p, b, m in zip(values, ref, mask):
                        if (p['width_ppm'] is None, p['shadow_survived'] is None, p['paused']) != (b['width_ppm'] is None, b['shadow_survived'] is None, m['paused']):
                            raise ValueError('eligibility or admission changed')
                        if b['row']['activity_state'] != 'bursty' and (p['width_ppm'], p['shadow_survived']) != (b['width_ppm'], b['shadow_survived']):
                            raise ValueError('non-bursty prices changed')
                    cells = measures(s, values, candidate, policy)
                    if candidate != 'optimized':
                        for cell in cells:
                            old = old_cells[(candidate, policy, cell['case_id'], cell['activity'])]
                            for field in ('windows', 'survived', 'eligible_outcomes', 'mean_width_ppm', 'full_window_pinball_ppm'):
                                if cell[field] != old[field]:
                                    raise ValueError('retained outer comparison differs: ' + field)
                            reconstructed += 1
                    cases.extend(cells); phases.extend(phase_cells(s, values, candidate, policy))
                    saved[candidate][policy][s['id']] = [p for p in values if p['row']['activity_state'] == 'bursty' and p['shadow_survived'] is not None]
                    for p in values:
                        if p['row']['activity_state'] == 'bursty':
                            stream.write(json.dumps(dict(candidate=candidate, policy=policy, session=s['id'],
                                start=p['row']['start'], width=p['width_ppm'], shadow=p['shadow_survived'], paused=p['paused'],
                                correction=p.get('optimizer_correction'), evidence=p.get('optimizer_evidence')), allow_nan=False) + '\n')
            if index % 10 == 0:
                print(f'optimizer diagnostics {index + 1}/{len(evaluated)}', flush=True)
    pairs = [r for c, policies in saved.items() for p, values in policies.items() for r in paired(evaluated, values, c, p)]
    return dict(cases=cases, phases=phases, paired=pairs, summary=summarize(cases),
                evaluated_sessions=len(evaluated), reconstructed_comparison_cells=reconstructed)


def run(previous_dir, output, trials=32, seed=20261028):
    if output.exists() or not 4 <= trials <= 256:
        raise ValueError('new output directory and 4..256 trials required')
    previous = json.loads((previous_dir / 'research.json').read_text()); verify_code(previous_dir, previous)
    for filename, key in (('selection.json', 'selection_sha256'), ('predictions.jsonl.gz', 'predictions_sha256'),
                          ('oof-residuals.jsonl.gz', 'oof_sha256'), ('oof-bindings.json', 'oof_bindings_sha256')):
        if file_hash(previous_dir / filename) != previous[key]:
            raise ValueError('preceding residual artifact differs: ' + filename)
    parent_dir = Path(previous['previous'])
    if file_hash(parent_dir / 'research.json') != previous['previous_sha256']:
        raise ValueError('parent metadata differs')
    protocol = dict(previous=str(previous_dir.resolve()), previous_sha256=file_hash(previous_dir / 'research.json'),
        source_sha256={n: file_hash(Path(__file__).with_name(n)) for n in DEPENDENCIES},
        search_space=SPACE, spec=SPEC, trials=trials, seed=seed, availability_constraints=AVAILABILITY,
        capture_started=False, live_candidate_promoted=False, independent_holdout=False,
        fitted_models_unchanged=True, frozen_and_non_bursty_pricing_and_admission_fixed=True,
        selection='Existing 6/9/12-date prefix comparisons and unchanged objective. Every trial scores every fold; no outcome-dependent pruning. Cached pre-entry forecasts, fixed OOF priors, only matured clean bursty labels. Repeatedly inspected later panels are diagnostics, excluded from search. Sparse earlier cases limit inference.')
    output.mkdir(parents=True); (output / 'source').mkdir()
    for n in DEPENDENCIES:
        shutil.copyfile(Path(__file__).with_name(n), output / 'source' / n)
    dump(output / 'protocol.json', protocol)
    started = time.monotonic()
    _, expanded, ctx, checked = load_cached(parent_dir)
    selection = json.loads((previous_dir / 'selection.json').read_text())
    engine_selection = json.loads((ctx['prior_dir'] / 'selection.json').read_text())
    folds = inputs_for_search(ctx, selection, engine_selection)
    dump(output / 'cache-manifest.json', dict(feature_records_verified=checked,
        folds=[dict(training_days=f['training_days'], scoring_days=f['scoring_days'],
                    sessions=[i['session']['id'] for i in f['inputs']],
                    supported_forecasts=sum(sum(p is not None for p in i['forecasts']['gap']) for i in f['inputs'])) for f in folds]))
    chosen = search(folds, selection, trials, seed, output)
    frozen_hash = file_hash(output / 'selection.json')
    print('search complete; shortlist pinned before later diagnostics', flush=True)
    diagnostic = diagnostics(ctx, previous, expanded, chosen['best_trial']['params'], output)
    if file_hash(output / 'selection.json') != frozen_hash:
        raise ValueError('selection changed during diagnostics')
    for n, digest in protocol['source_sha256'].items():
        if file_hash(Path(__file__).with_name(n)) != digest:
            raise ValueError('source changed during search')
    result = dict(protocol, selected=chosen['selected'], best_trial=chosen['best_trial'],
                  retained_champion=chosen['retained_champion'], **diagnostic,
                  selection_sha256=frozen_hash, trials_sha256=file_hash(output / 'trials.jsonl'),
                  predictions_sha256=file_hash(output / 'predictions.jsonl.gz'), elapsed_seconds=time.monotonic() - started)
    dump(output / 'research.json', result)
    for name in ('cases', 'phases', 'paired', 'summary'):
        write_csv(output / (name + '.csv'), result[name], list(result[name][0]))
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--previous', type=Path, required=True); parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--trials', type=int, default=32); parser.add_argument('--seed', type=int, default=20261028)
    args = parser.parse_args()
    result = run(args.previous, args.output, args.trials, args.seed)
    print(json.dumps({k: result[k] for k in ('selected', 'best_trial', 'elapsed_seconds')}, indent=2))
