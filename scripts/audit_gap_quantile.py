#!/usr/bin/env python3
"""Verify immutable context lineage, pre-entry features and causal model fits."""
import argparse
import gzip
import json
from pathlib import Path

from audit_expanded_bursty import equivalent
from capture_dataset import file_hash
from research_gap_quantile import load_inputs_for_gap, fit_prefix, context
from research_nonfrozen_pricing import verify_raw
from research_startup_admission import verify_code


def cached_context(ctx, path):
    data = {}
    with gzip.open(path, 'rt') as stream:
        for line in stream:
            r = json.loads(line); data[(r['kind'], r['key'], r['start'])] = r['feature']
            if r['feature'] is not None:
                assert r['feature']['observed_at'] < r['start']
                assert r['feature']['lag_observed_at'] < r['start'] - 30000
    ctx['original'] = [dict(r, oracle_gap=data[('normalized_training', r['period'], r['start'])]) for r in ctx['original']]
    ctx['expanded_rawdays'] = {day: [dict(r, oracle_gap=data[('raw_training', day, r['start'])]) for r in rows]
                               for day, rows in ctx['expanded_rawdays'].items()}
    for s in ctx['sessions']:
        left = min(p['row']['start'] for p in s['values'])
        for p in s['values']:
            g = data[('session', s['id'], p['row']['start'])]
            if g is not None:
                assert left <= g['lag_observed_at'] <= g['observed_at']
            p['row'] = dict(p['row'], oracle_gap=g)
    return len(data)


def audit(root):
    r = json.loads((root / 'research.json').read_text()); verify_code(root, r)
    for n, k in (('selection.json', 'selection_sha256'), ('predictions.jsonl.gz', 'predictions_sha256'),
                 ('gap-features.jsonl.gz', 'features_sha256'), ('context-checks.json', 'context_checks_sha256')):
        assert file_hash(root / n) == r[k]
    previous, ctx = load_inputs_for_gap(Path(r['previous']))
    assert file_hash(Path(r['previous']) / 'research.json') == r['previous_sha256']
    checks = json.loads((root / 'context-checks.json').read_text())
    for binding in checks['bindings']:
        directory = Path(binding['root']); digest = binding['manifest_sha256']
        assert file_hash(directory / 'download-manifest.json') == digest
        if 'monthly-samples' in directory.name:
            for f in json.loads((directory / 'download-manifest.json').read_text())['files']:
                assert file_hash(directory / f['path']) == f['sha256']
        else:
            verify_raw(dict(raw=str(directory), raw_manifest_sha256=digest))
    count = cached_context(ctx, root / 'gap-features.jsonl.gz')
    tested = []
    for day in ('2025-01-01', '2025-06-01'):
        changed = dict(ctx)
        changed['original'] = [dict(row, move=999999999, valid=False) if row['period'] >= day else row for row in ctx['original']]
        changed['expanded_rawdays'] = {date: [dict(row, move=999999999, valid=False) if date >= day else row for row in rows]
                                       for date, rows in ctx['expanded_rawdays'].items()}
        session = next(s for s in ctx['sessions'] if s['source'] == 'raw_matched' and s['period'] == day)
        key, engine, overlay = context(ctx, session)
        bundle = fit_prefix(changed, previous['models'][key]['existing']['prior'], engine, overlay)
        assert equivalent(json.loads(json.dumps(bundle)), r['models'][key])
        tested.append(day)
    bycase = {(v['candidate'], v['policy'], v['case_id'], v['activity']): v for v in r['cases']}
    for v in r['cases']:
        baseline = bycase[('retained_pool', v['policy'], v['case_id'], v['activity'])]
        for field in ('eligible_outcomes', 'pre_entry_predictions', 'grid_windows', 'windows', 'offered_pre_entry_decisions'):
            assert v[field] == baseline[field]
        if v['activity'] in ('active', 'sparse', 'frozen'):
            for field in ('survived', 'mean_width_ppm', 'full_window_pinball_ppm'):
                assert v[field] == baseline[field]
    result = dict(completed=True, feature_records_verified=count, all_context_source_hashes_verified=True,
                  features_strictly_before_entry_and_restart_boundaries=True, shared_training_support=True,
                  own_and_future_label_mutations_preserve_numeric_models=tested, tolerance=1e-10,
                  fixed_availability_and_non_bursty_prices=True, capture_started=False, live_candidate_promoted=False)
    (root / 'audit.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__); p.add_argument('--output', type=Path, required=True)
    audit(p.parse_args().output)
