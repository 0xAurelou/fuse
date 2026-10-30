#!/usr/bin/env python3
"""Verify chronological residual priors and the unchanged preceding controls."""
import argparse
import gzip
import json
from pathlib import Path

from bursty_residual import MODES, all_series
from capture_dataset import file_hash
from chronological_raw_priors import floor_values, replay
from research_bursty_residual import load_cached, build_oof, fit_priors
from research_expanded_bursty import context
from research_startup_admission import verify_code


def audit(root):
    r = json.loads((root / 'research.json').read_text()); verify_code(root, r)
    for name, key in (('selection.json', 'selection_sha256'), ('predictions.jsonl.gz', 'predictions_sha256'),
                      ('oof-residuals.jsonl.gz', 'oof_sha256'), ('oof-bindings.json', 'oof_bindings_sha256')):
        assert file_hash(root / name) == r[key]
    previous_dir = Path(r['previous']); assert file_hash(previous_dir / 'research.json') == r['previous_sha256']
    previous, expanded, ctx, features = load_cached(previous_dir)
    assert r['models'] == previous['models']
    selection = json.loads((root / 'selection.json').read_text())
    previous_selection = json.loads((previous_dir / 'selection.json').read_text())
    assert selection['models'] == previous_selection['models']
    records, bindings = build_oof(ctx, previous, expanded, previous_selection,
                                  json.loads((ctx['prior_dir'] / 'selection.json').read_text()))
    with gzip.open(root / 'oof-residuals.jsonl.gz', 'rt') as stream:
        assert records == [json.loads(line) for line in stream]
    assert bindings == json.loads((root / 'oof-bindings.json').read_text())
    old_candidates = set(previous['variants']); checked = 0
    with gzip.open(previous_dir / 'predictions.jsonl.gz', 'rt') as old, gzip.open(root / 'predictions.jsonl.gz', 'rt') as new:
        for line in new:
            p = json.loads(line)
            if p['candidate'] in old_candidates:
                assert p == json.loads(next(old)), 'preceding prediction changed'
                checked += 1
        assert not old.readline()
    counterfactuals = []
    for day in ('2025-01-01', '2025-06-01'):
        changed_records = [dict(p, ratio=999999.) if p['row']['period'] >= day else p for p in records]
        assert fit_priors(changed_records, previous['models'][day]) == r['residual_priors'][day]
        s = next(s for s in ctx['sessions'] if s['source'] == 'raw_matched' and s['period'] == day and s['mode'] == 'restart')
        key, engine, _ = context(ctx, s)
        ref = replay(floor_values(s['values'], engine), expanded['models'][key]['existing']['prior']['model'], 'floor10_burst_pool120')
        models, priors = previous['models'][key]['models'], r['residual_priors'][key]
        actual = all_series(ref, models, priors)
        changed = [dict(p, row=dict(p['row'], move=0)) if p['row']['valid'] and p['row']['activity_state'] in ('active', 'sparse') else p for p in ref]
        altered = all_series(changed, models, priors)
        for source in ('timing', 'gap'):
            for mode in MODES:
                c = source + '_' + mode
                assert [(p['width_ppm'], p['gap_log_correction']) for p in actual[c] if p['row']['activity_state'] == 'bursty'] == [
                    (p['width_ppm'], p['gap_log_correction']) for p in altered[c] if p['row']['activity_state'] == 'bursty']
        boundary = ref[len(ref) // 2]['row']['start']
        changed = [dict(p, row=dict(p['row'], move=999999999, valid=False)) if p['row']['start'] >= boundary else p for p in ref]
        altered = all_series(changed, models, priors)
        for c in r['variants']:
            assert [(p['width_ppm'], p['gap_log_correction']) for p in actual[c] if p['row']['start'] < boundary + 60000] == [
                (p['width_ppm'], p['gap_log_correction']) for p in altered[c] if p['row']['start'] < boundary + 60000]
        counterfactuals.append(dict(day=day, prior_unchanged_under_own_and_future_residual_mutation=True,
                                    online_correction_ignores_other_state_labels_given_fixed_references=True,
                                    current_and_future_labels_wait_for_maturity=True))
    bycase = {(p['candidate'], p['policy'], p['case_id'], p['activity']): p for p in r['cases']}
    for p in r['cases']:
        baseline = bycase[('retained_pool', p['policy'], p['case_id'], p['activity'])]
        for field in ('windows', 'eligible_outcomes', 'pre_entry_predictions', 'grid_windows', 'offered_pre_entry_decisions'):
            assert p[field] == baseline[field]
        if p['activity'] in ('active', 'sparse', 'frozen'):
            for field in ('survived', 'mean_width_ppm', 'full_window_pinball_ppm'):
                assert p[field] == baseline[field]
    result = dict(completed=True, exact_preceding_prediction_rows=checked, exact_oof_residual_records=len(records),
                  frozen_models_and_selection_prefixes_unchanged=True, chronological_forecast_bindings_recomputed=True,
                  input_hashes_and_feature_records_reverified=features, counterfactuals=counterfactuals,
                  admission_and_non_bursty_prices_fixed=True, capture_started=False, live_candidate_promoted=False)
    (root / 'audit.json').write_text(json.dumps(result, indent=2) + '\n'); print(json.dumps(result, indent=2))


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__); p.add_argument('--output', type=Path, required=True)
    audit(p.parse_args().output)
