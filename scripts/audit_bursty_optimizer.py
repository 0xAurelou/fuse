#!/usr/bin/env python3
"""Audit saved search proposals, selected score, controls, and actual-data causality."""
import argparse
import gzip
import json
from pathlib import Path

from bursty_optimizer import BayesianSearch, cache_forecasts, replay as optimize_replay
from capture_dataset import file_hash
from chronological_raw_priors import floor_values, replay
from research_bursty_optimizer import dump, evaluate, inputs_for_search
from research_bursty_residual import load_cached
from research_expanded_bursty import context
from research_startup_admission import verify_code


def audit(root):
    result = json.loads((root / 'research.json').read_text()); verify_code(root, result)
    for filename, key in (('selection.json', 'selection_sha256'), ('trials.jsonl', 'trials_sha256'),
                          ('predictions.jsonl.gz', 'predictions_sha256')):
        assert file_hash(root / filename) == result[key]
    previous_dir = Path(result['previous'])
    assert file_hash(previous_dir / 'research.json') == result['previous_sha256']
    previous = json.loads((previous_dir / 'research.json').read_text())
    parent = Path(previous['previous'])
    assert file_hash(parent / 'research.json') == previous['previous_sha256']
    for filename, key in (('selection.json', 'selection_sha256'), ('predictions.jsonl.gz', 'predictions_sha256'),
                          ('oof-residuals.jsonl.gz', 'oof_sha256'), ('oof-bindings.json', 'oof_bindings_sha256')):
        assert file_hash(previous_dir / filename) == previous[key]
    verify_code(previous_dir, previous)
    selection = json.loads((root / 'selection.json').read_text())
    trials = [json.loads(line) for line in (root / 'trials.jsonl').read_text().splitlines()]
    assert len(trials) == result['trials']
    optimizer = BayesianSearch(result['seed'])
    for i, trial in enumerate(trials):
        assert trial['trial'] == i and trial['params'] == optimizer.ask()
        optimizer.tell(trial['params'], trial['score'] if trial['feasible'] else 1000000.)
    best = min(trials, key=lambda r: (not r['feasible'], r['score'], r['trial']))
    assert best == result['best_trial'] == selection['best_trial']
    _, expanded, ctx, checked = load_cached(parent)
    folds = inputs_for_search(ctx, json.loads((previous_dir / 'selection.json').read_text()),
                              json.loads((ctx['prior_dir'] / 'selection.json').read_text()))
    recalculated = evaluate(best['params'], folds)
    assert recalculated == {k: best[k] for k in ('score', 'folds', 'feasible')}
    counterfactuals = []
    for day in ('2025-01-01', '2025-06-01'):
        s = next(s for s in ctx['sessions'] if s['source'] == 'raw_matched' and s['period'] == day and s['mode'] == 'restart')
        key, engine, _ = context(ctx, s)
        ref = replay(floor_values(s['values'], engine), expanded['models'][key]['existing']['prior']['model'], 'floor10_burst_pool120')
        source = best['params']['source']; model = {source: previous['models'][key]['models'][source]}
        prior = previous['residual_priors'][key][source]
        run = lambda v: optimize_replay(v, cache_forecasts(v, model)[source], prior, best['params'])
        actual = run(ref)
        changed = [dict(p, row=dict(p['row'], move=0)) if p['row']['activity_state'] in ('active', 'sparse') else p for p in ref]
        altered = run(changed)
        assert [(p['width_ppm'], p.get('optimizer_correction')) for p in actual] == [(p['width_ppm'], p.get('optimizer_correction')) for p in altered]
        boundary = ref[len(ref) // 2]['row']['start']
        changed = [dict(p, row=dict(p['row'], move=999999999, valid=False)) if p['row']['start'] >= boundary else p for p in ref]
        altered = run(changed)
        assert [(p['width_ppm'], p.get('optimizer_correction')) for p in actual if p['row']['start'] < boundary + 60000] == [
            (p['width_ppm'], p.get('optimizer_correction')) for p in altered if p['row']['start'] < boundary + 60000]
        counterfactuals.append(dict(day=day, matured_labels_only=True, other_state_labels_isolated_given_fixed_references=True))
    controls = {}
    with gzip.open(previous_dir / 'predictions.jsonl.gz', 'rt') as stream:
        for line in stream:
            p = json.loads(line)
            if p['candidate'] in ('retained_pool', 'gap_bursty'):
                controls[tuple(p[k] for k in ('candidate', 'policy', 'session', 'start'))] = p
    verified = 0
    with gzip.open(root / 'predictions.jsonl.gz', 'rt') as stream:
        for line in stream:
            p = json.loads(line)
            if p['candidate'] != 'optimized':
                old = controls.pop(tuple(p[k] for k in ('candidate', 'policy', 'session', 'start')))
                assert all(p[k] == old[k] for k in ('width', 'shadow', 'paused'))
                verified += 1
    assert not controls
    cells = {(r['candidate'], r['policy'], r['case_id'], r['activity']): r for r in result['cases']}
    for cell in result['cases']:
        baseline = cells[('retained_pool', cell['policy'], cell['case_id'], cell['activity'])]
        for field in ('windows', 'eligible_outcomes', 'pre_entry_predictions', 'grid_windows', 'offered_pre_entry_decisions'):
            assert cell[field] == baseline[field]
        if cell['activity'] in ('active', 'sparse', 'frozen'):
            for field in ('survived', 'mean_width_ppm', 'full_window_pinball_ppm'):
                assert cell[field] == baseline[field]
    report = dict(completed=True, deterministic_trial_proposals_verified=len(trials), selected_score_recomputed_exactly=True,
                  previous_prediction_rows_verified=verified, feature_records_verified=checked,
                  counterfactuals=counterfactuals, admission_and_other_prices_fixed=True,
                  capture_started=False, live_candidate_promoted=False, independent_holdout=False)
    dump(root / 'audit.json', report)
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument('--output', type=Path, required=True)
    audit(parser.parse_args().output)
