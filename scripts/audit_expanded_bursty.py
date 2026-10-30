#!/usr/bin/env python3
"""Reverify raw lineage and outer-date causality of expanded training fits."""
import argparse
import gzip
import json
import math
from pathlib import Path

from capture_dataset import file_hash
from research_expanded_bursty import expanded_bundle, load_expansion
from research_preentry_bursty import load_inputs
from research_startup_admission import verify_code


def equivalent(a, b):
    if isinstance(a, dict):
        return a.keys() == b.keys() and all(equivalent(a[k], b[k]) for k in a)
    if isinstance(a, list):
        return len(a) == len(b) and all(equivalent(x, y) for x, y in zip(a, b))
    if isinstance(a, (int, float)) and not isinstance(a, bool):
        return math.isclose(a, b, rel_tol=1e-10, abs_tol=1e-10)
    return a == b


def audit(root):
    r = json.loads((root / 'research.json').read_text())
    verify_code(root, r)
    for n, k in (('predictions.jsonl.gz', 'predictions_sha256'), ('selection.json', 'selection_sha256'),
                 ('expanded-training-rows.jsonl.gz', 'training_rows_sha256')):
        assert file_hash(root / n) == r[k]
    previous_dir = Path(r['previous'])
    previous = json.loads((previous_dir / 'research.json').read_text())
    verify_code(previous_dir, previous)
    assert file_hash(previous_dir / 'research.json') == r['previous_sha256']
    static = json.loads((Path(previous['previous']) / 'research.json').read_text())
    ctx = load_inputs(Path(static['previous']))
    _, raw_checks = load_expansion(ctx, Path(r['raw']), previous_dir)
    assert raw_checks == r['raw_checks']
    changed_days = []
    for day in ('2025-01-01', '2025-06-01'):
        changed = dict(ctx)
        changed['original'] = [dict(row, valid=False, move=999999999) if row['period'] >= day else row for row in ctx['original']]
        changed['expanded_rawdays'] = {date: [dict(row, valid=False, move=999999999) if date >= day else row for row in rows]
                                       for date, rows in ctx['expanded_rawdays'].items()}
        model = expanded_bundle(changed, r['models'][day]['existing'], ctx['base']['models'][day]['engine'],
                                ctx['control']['models'][day]['overlay'])
        assert equivalent(json.loads(json.dumps(model)), r['models'][day]['expanded'])
        changed_days.append(day)
    for bundles in r['models'].values():
        for bundle in bundles.values():
            assert all(day < bundle['cutoff'] for day in bundle['training_periods'])
            assert len(set(bundle['training_periods'])) == len(bundle['training_periods'])
            for fold in bundle['model']['calibration']['folds']:
                assert max(fold['training_periods']) < fold['scoring_period'] < bundle['cutoff']
    maxima = {source: {k: 0 for k in ('static', 'chrono', 'context')} for source in ('existing', 'expanded')}
    jan = {source: [] for source in maxima}
    refused = {c: 0 for c in r['variants']}
    with gzip.open(root / 'predictions.jsonl.gz', 'rt') as stream:
        for line in stream:
            p = json.loads(line)
            source, method, gate = p['candidate'].split(':')
            if p['width'] is not None:
                for k in maxima[source]:
                    maxima[source][k] = max(maxima[source][k], p[k])
                refused[p['candidate']] += p['paused']
            if p['policy'] == 'previous_floor_53' and method == 'retained_pool' and gate == 'unchanged' and p['session'] == 'raw:2026-01-01:restart:08' and p['width'] is not None:
                jan[source].append(p)
    assert all(sum(p['minimum_width_survived'] for p in part[:12]) == 8 for part in jan.values())
    comparison = json.loads((root / 'comparison.json').read_text())
    assert all(x['case_paths'] == 25 and x['maximum_refusals_at90pct'] == 2 and x['best_possible_startup_survival'] == .6
               for x in comparison['feasibility_bound'])
    checks = dict(raw_and_input_hashes_reverified=True, numeric_models_unchanged_under_own_and_future_label_mutations=changed_days,
                  tolerance=1e-10, oof_dates_strictly_precede_scoring=True, no_duplicate_training_dates=True,
                  existing_case_cells_reconstructed=r['checks']['existing_case_cells_reconstructed'],
                  existing_selection_reconstructed=r['checks']['existing_selection_reconstructed'],
                  january_finite_subset_bound_verified=True, max_bursty_floor_risk=maxima, paused_bursty_rows=refused,
                  comparison_invariants=comparison['checks'])
    (root / 'audit.json').write_text(json.dumps(checks, indent=2) + '\n')
    print(json.dumps(checks, indent=2))
    return checks


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', type=Path, required=True)
    audit(p.parse_args().output)
