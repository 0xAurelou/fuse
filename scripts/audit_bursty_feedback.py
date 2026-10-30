#!/usr/bin/env python3
"""Audit frozen fits, exact controls and correction-layer counterfactuals."""
import argparse
import gzip
import json
from pathlib import Path

from bursty_feedback import MODES, all_series
from capture_dataset import file_hash
from chronological_raw_priors import floor_values, replay
from research_bursty_feedback import load_cached
from research_expanded_bursty import context
from research_startup_admission import verify_code


def audit(root):
    r = json.loads((root / 'research.json').read_text()); verify_code(root, r)
    for name, key in (('selection.json', 'selection_sha256'), ('predictions.jsonl.gz', 'predictions_sha256')):
        assert file_hash(root / name) == r[key]
    assert file_hash(Path(r['feature_cache'])) == r['features_sha256']
    assert file_hash(Path(r['context_checks'])) == r['context_checks_sha256']
    previous_dir = Path(r['previous'])
    assert file_hash(previous_dir / 'research.json') == r['previous_sha256']
    previous, expanded, ctx, features = load_cached(previous_dir)
    assert r['models'] == previous['models']
    old_selection = json.loads((previous_dir / 'selection.json').read_text())
    selection = json.loads((root / 'selection.json').read_text())
    assert selection['models'] == old_selection['models']
    old_candidates = set(previous['variants']); checked = 0
    with gzip.open(previous_dir / 'predictions.jsonl.gz', 'rt') as old, gzip.open(root / 'predictions.jsonl.gz', 'rt') as new:
        for line in new:
            p = json.loads(line)
            if p['candidate'] not in old_candidates:
                continue
            p.pop('components')
            assert p == json.loads(next(old)), 'preceding per-entry control differs'
            checked += 1
        assert not old.readline()
    counterfactuals = []
    for day in ('2025-01-01', '2025-06-01'):
        s = next(s for s in ctx['sessions'] if s['source'] == 'raw_matched' and s['period'] == day and s['mode'] == 'restart')
        key, engine, _ = context(ctx, s)
        prior = expanded['models'][key]['existing']['prior']
        ref = replay(floor_values(s['values'], engine), prior['model'], 'floor10_burst_pool120')
        model = previous['models'][key]['models']; actual = all_series(ref, model)
        changed = [dict(p, row=dict(p['row'], move=0)) if p['row']['valid'] and p['row']['activity_state'] in ('active', 'sparse') else p for p in ref]
        altered = all_series(changed, model)
        for source in ('timing', 'gap'):
            for mode in MODES:
                c = source + '_' + mode
                assert [(p['width_ppm'], p['gap_log_correction']) for p in actual[c] if p['row']['activity_state'] == 'bursty'] == [
                    (p['width_ppm'], p['gap_log_correction']) for p in altered[c] if p['row']['activity_state'] == 'bursty']
        shared_changes = sum(a['width_ppm'] != b['width_ppm'] for a, b in zip(actual['gap_adaptive'], altered['gap_adaptive'])
                             if a['row']['activity_state'] == 'bursty')
        assert shared_changes > 0
        boundary = ref[len(ref) // 2]['row']['start']
        changed = [dict(p, row=dict(p['row'], move=999999999, valid=False)) if p['row']['start'] >= boundary else p for p in ref]
        altered = all_series(changed, model)
        for c in r['variants']:
            assert [(p['width_ppm'], p['gap_log_correction']) for p in actual[c] if p['row']['start'] < boundary + 60000] == [
                (p['width_ppm'], p['gap_log_correction']) for p in altered[c] if p['row']['start'] < boundary + 60000]
        counterfactuals.append(dict(day=day, shared_control_width_changes_under_other_state_label_mutation=shared_changes,
                                    isolated_corrections_unchanged=True, future_labels_wait_for_maturity=True,
                                    scope='Correction layer only; retained-reference forecasts and fitted models held fixed'))
    bycase = {(p['candidate'], p['policy'], p['case_id'], p['activity']): p for p in r['cases']}
    for p in r['cases']:
        baseline = bycase[('retained_pool', p['policy'], p['case_id'], p['activity'])]
        for field in ('windows', 'eligible_outcomes', 'pre_entry_predictions', 'grid_windows', 'offered_pre_entry_decisions'):
            assert p[field] == baseline[field]
        if p['activity'] in ('active', 'sparse', 'frozen'):
            for field in ('survived', 'mean_width_ppm', 'full_window_pinball_ppm'):
                assert p[field] == baseline[field]
    result = dict(completed=True, exact_preceding_prediction_rows=checked, feature_records_reverified=features,
                  fitted_models_and_selection_prefix_models_exactly_unchanged=True, input_and_context_hashes_reverified=True,
                  counterfactuals=counterfactuals, admission_and_non_bursty_prices_fixed=True,
                  capture_started=False, live_candidate_promoted=False)
    (root / 'audit.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__); p.add_argument('--output', type=Path, required=True)
    audit(p.parse_args().output)
