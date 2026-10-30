#!/usr/bin/env python3
"""Independently reconcile saved asset traces, coefficients and source bindings."""
import argparse
from collections import defaultdict
import csv
from fractions import Fraction
import gzip
import json
import math
from pathlib import Path

from capture_dataset import file_hash
from research_asset_corridors import (ASSETS, CANDIDATES, PLAN, TARGETS, baseline_series,
    open_values, price, context_series, target_series, training_rows)
from stabilize_adaptive_corridor import size
from fetch_asset_oracles import dump


def close(a, b):
    if not math.isclose(a, b, rel_tol=1e-11, abs_tol=1e-10):
        raise ValueError(f'numeric reconciliation failed: {a} != {b}')


def independent_global_scale(rows, q):
    parts = defaultdict(list)
    for row in rows:
        if row['valid'] and row['adaptive_features'] is not None:
            parts[row['period']].append(row)
    ratios = []
    for part in parts.values():
        for r in part:
            width = ((r['move'] + 1) * 1000000 + r['entry'] - 1) // r['entry']
            ratios.append((width / size(r), 1 / len(part)))
    ratios.sort()
    threshold = q * sum(w for _, w in ratios)
    mass = 0
    for value, weight in ratios:
        mass += weight
        if mass >= threshold:
            return value


def audit(root):
    result = json.loads((root / 'research.json').read_text())
    plan = result['plan']
    if file_hash(root / 'protocol.json') != result['protocol_sha256']:
        raise ValueError('research protocol differs')
    for name, digest in plan['source_sha256'].items():
        if file_hash(root / 'source' / name) != digest:
            raise ValueError('source snapshot differs')
    if file_hash(root / 'dataset.json') != result['dataset_sha256']:
        raise ValueError('dataset metadata differs')
    data = json.loads((root / 'dataset.json').read_text())
    if file_hash(root / 'rows.jsonl.gz') != data['rows_sha256']:
        raise ValueError('feature rows differ')
    downloads = Path(plan['downloads'])
    if file_hash(downloads / 'download-protocol.json') != plan['download_protocol_sha256']:
        raise ValueError('download protocol differs')
    if file_hash(downloads / 'download-manifest.json') != data['download_manifest_sha256']:
        raise ValueError('download manifest differs')
    raw = json.loads((downloads / 'download-manifest.json').read_text())
    for item in raw['files']:
        path = downloads / item['path']
        if file_hash(path) != item['sha256']:
            raise ValueError('raw source differs')
        gzip.decompress(path.read_bytes())
    rows = {a: {} for a in ASSETS}
    with gzip.open(root / 'rows.jsonl.gz', 'rt') as stream:
        for line in stream:
            r = json.loads(line)
            if r['start'] in rows[r['asset']]:
                raise ValueError('duplicate asset entry timestamp')
            rows[r['asset']][r['start']] = r
    totals = []
    for asset in ASSETS:
        directory = root / asset
        metadata = json.loads((directory / 'research.json').read_text())
        if file_hash(directory / 'research.json') != result['research_sha256'][asset]:
            raise ValueError('asset research differs')
        for name in ('selection', 'models', 'legacy-models', 'predictions', 'metrics', 'feasibility'):
            filename = name + ('.jsonl.gz' if name == 'predictions' else '.csv' if name in ('metrics', 'feasibility') else '.json')
            key = name.replace('-', '_') + '_sha256'
            if file_hash(directory / filename) != metadata[key]:
                raise ValueError('asset artifact differs: ' + filename)
        models = json.loads((directory / 'models.json').read_text())
        legacy = json.loads((directory / 'legacy-models.json').read_text())
        for key in ('asset', 'training_dates', 'training_provenance', 'volatility', 'core', 'context'):
            if models[key] != legacy[key]:
                raise ValueError('legacy model changed after selection')
        if models['targets']['legacy48'] != legacy['targets']['legacy48']:
            raise ValueError('legacy target model changed after selection')
        if models['asset'] != asset or any(d >= '2026-01-01' for d in models['training_dates']):
            raise ValueError('cross-asset or future training')
        days = defaultdict(list)
        for r in rows[asset].values():
            days[r['period']].append(r)
        train, _ = training_rows([], days, models['training_dates'], '2026-01-01', True)
        for name, q, _ in TARGETS:
            model = models['targets'][name]
            close(model['engine']['target_survival'], q)
            close(model['overlay']['target_survival'], q)
            close(model['engine']['base']['global_scale'], independent_global_scale(train, q))
        traces = defaultdict(list)
        buckets = defaultdict(lambda: [0, 0, 0., 0, 0, 0])
        count = 0
        with gzip.open(directory / 'predictions.jsonl.gz', 'rt') as stream:
            for line in stream:
                p = json.loads(line)
                count += 1
                row = rows[asset][p['start']]
                if p['asset'] != asset or p['split'] == 'train' or any(p[k] != row[k] for k in ('entry', 'move', 'valid', 'period', 'split')):
                    raise ValueError('trace/row binding differs')
                traces[p['target_name'], p['candidate']].append(p)
                expected = row['move'] < row['entry']*p['width_ppm']//1000000 if p['width_ppm'] is not None and row['valid'] else None
                if expected != p['survived']:
                    raise ValueError('touch/rounding survival differs')
                for period in ('pooled', row['period']):
                    for axis, group in (('overall', 'all'), ('activity_state', row['activity_state']), ('market_regime', row['market_regime'])):
                        b = buckets[p['target_name'], p['candidate'], row['split'], period, axis, group]
                        b[4] += 1
                        b[5] += p['width_ppm'] is not None
                        if expected is not None:
                            b[0] += 1; b[1] += expected; b[2] += p['width_ppm']; b[3] += p['width_ppm'] == 1
        with (directory / 'metrics.csv').open() as stream:
            for metric in csv.DictReader(stream):
                key = tuple(metric[k] for k in ('target_name', 'candidate', 'split', 'period', 'axis', 'group'))
                n, wins, widths, floor, grid, forecasts = buckets[key]
                for field, value in (('eligible', n), ('offered', n), ('wins', wins), ('at_minimum_width', floor), ('grid', grid), ('pre_entry_predictions', forecasts)):
                    if int(metric[field]) != value:
                        raise ValueError('metric count differs: ' + field)
                q, multiplier = next((q, m) for name, q, m in TARGETS if name == metric['target_name'])
                close(float(metric['expected_wins_at_target']), n*q)
                if n:
                    close(float(metric['survival']), wins/n)
                    close(float(metric['error_pp']), 100*(wins/n-q))
                    close(float(metric['mean_width_ppm']), widths/n)
                    if multiplier:
                        close(float(metric['gross_equal_stake_return']), 1-multiplier*wins/n)
        with (directory / 'feasibility.csv').open() as stream:
            for metric in csv.DictReader(stream):
                cohort = [r for r in days[metric['day']] if r['valid'] and r['adaptive_features'] is not None]
                n = len(cohort)
                z = sum(r['move'] == 0 for r in cohort)
                if n != int(metric['n']) or z != int(metric['zeros']):
                    raise ValueError('feasibility population differs')
                _, multiplier = next((q, m) for name, q, m in TARGETS if name == metric['target_name'])
                for field, upper in (('retention_at_target', Fraction(48,100) if multiplier is None else Fraction(95,100*multiplier)),
                                     ('retention_at_break_even', Fraction(1,multiplier) if multiplier else None)):
                    if upper is not None and n:
                        retained = min(n, (Fraction(n-z)/(1-upper)).numerator // (Fraction(n-z)/(1-upper)).denominator)
                        close(float(metric[field]), retained/n)
        ranking = []
        for i, candidate in enumerate(CANDIDATES):
            key = ('legacy48', candidate)
            if key not in traces:
                continue
            daily, conditional = [], []
            for bucket_key, counts in buckets.items():
                target, family, part, period, axis, group = bucket_key
                if target != 'legacy48' or family != candidate or part != 'validation' or period == 'pooled':
                    continue
                n, wins = counts[:2]
                if n >= 20:
                    (daily if axis == 'overall' else conditional).append(abs(100*(wins/n-.48)))
            score = sum(daily)/len(daily) + .5*(sum(conditional)/len(conditional) if conditional else 0) + .25*max(daily)
            ranking.append((score, i, candidate))
        ranking.sort()
        if ranking[0][2] != metadata['selected']:
            raise ValueError('validation winner differs')
        for actual, saved in zip(ranking, metadata['ranking']):
            if actual[2] != saved['candidate']:
                raise ValueError('validation ranking differs')
            close(actual[0], saved['score'])
        # Replay the selected family's complete test history from frozen models.
        test = [r for r in rows[asset].values() if r['split'] == 'test']
        selected = metadata['selected']
        if selected == 'volatility':
            predicted = baseline_series(test, models['volatility'])
        elif selected == 'activity_hurdle':
            predicted = target_series(test, models['targets']['legacy48'])
        else:
            _, predicted = price(test, models['core'])
            predicted = open_values(predicted)
            if selected != 'full_core':
                family = selected.split('_')[0]
                predicted = context_series(predicted, models['context'][family], 'priceable', None)
        saved = [p for p in traces['legacy48', selected] if p['split'] == 'test']
        if [(p['row']['start'], p['width_ppm'], p['survived']) for p in predicted] != [(p['start'], p['width_ppm'], p['survived']) for p in saved]:
            raise ValueError('frozen-model test replay differs')
        totals.append(dict(asset=asset, raw_days=len(days), feature_rows=len(rows[asset]),
                           trace_rows=count, payout_models=9, selected_test_replay_paths=len(saved),
                           selection=selected, independent_scale_reconciliations=len(TARGETS)))
    report = dict(passed=True, raw_slices=len(raw['files']), assets=totals,
                  audit_source_sha256=file_hash(Path(__file__)),
                  research_sha256=file_hash(root / 'research.json'))
    dump(root / 'audit.json', report)
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--research', type=Path, required=True)
    print(json.dumps(audit(parser.parse_args().research), indent=2))
