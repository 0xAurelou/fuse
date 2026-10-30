#!/usr/bin/env python3
"""Evaluate causal flat-risk admission and 100x/1000x conditional pricing."""
import argparse
from collections import defaultdict
import csv
import gzip
import hashlib
import json
import math
from pathlib import Path
import shutil
import sys
import time

from payout_risk import (FAMILIES, RIDGES, SPEC, VARIANTS, conditional_width, decision,
                         fit_positive, fit_risk, required_width, risk_series, weekend)

ASSETS = ('ETH', 'HYPE')
MULTIPLIERS = (100, 1000)
PLAN = dict(assets=ASSETS, multipliers=MULTIPLIERS, spec=SPEC, variants=VARIANTS,
            train='All asset training dates ending December 2025; cutoff 2026-01-01',
            selection='January-May 2026 selects risk feature family/ridge using proper binary log loss only; payout outcomes never select gates.',
            later='June-October 2026, already inspected development diagnostics, not untouched holdouts',
            minimum_positive_tail_mass=20, gate_fractions=[.25, .5, 1.],
            quote_availability_screen=.85, target_relative_band=[.75, 1.25],
            screens='Descriptive research references, not production limits or probability confidence',
            reference_updates='All clean external paths, including refused paths, mature after expiry+30s; risk calibration is independent of width, gate and trader entry',
            floor_definitions='Zero oracle movement is the universal floor; one-ppm survival is the separate research minimum-width floor',
            liquidity='No order-book liquidity, volume or spread measurements in this study',
            no_new_capture=True, live_policy_changed=False, no_promotion=True)
FIELDS = ('asset', 'multiplier', 'variant', 'split', 'period', 'axis', 'group',
          'grid', 'pre_entry_predictions', 'pre_entry_offered', 'eligible', 'offered',
          'availability', 'wins', 'shadow_wins', 'survival', 'shadow_survival',
          'target', 'survival_to_target', 'gross_equal_stake_return', 'mean_width_ppm',
          'zero_wins', 'minimum_width_wins', 'predicted_floor_mean', 'realized_floor',
          'target_expected_wins', 'at_least_20_target_expected_wins')


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024*1024), b''):
            h.update(block)
    return h.hexdigest()


def dump(path, value):
    with path.open('x') as stream:
        json.dump(value, stream, indent=2, allow_nan=False)
        stream.write('\n')


def write_csv(path, rows, fields=None):
    if not rows and fields is None:
        raise ValueError('explicit schema needed for empty table')
    with path.open('x', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields or list(rows[0]), extrasaction='raise')
        writer.writeheader(); writer.writerows(rows)


def load_parent(parent):
    meta = json.loads((parent/'research.json').read_text())
    data = json.loads((parent/'dataset.json').read_text())
    if digest(parent/'dataset.json') != meta['dataset_sha256'] or digest(parent/'rows.jsonl.gz') != data['rows_sha256']:
        raise ValueError('parent dataset differs')
    audit = json.loads((parent/'audit.json').read_text())
    if not audit['passed'] or audit['research_sha256'] != digest(parent/'research.json'):
        raise ValueError('a completed matching parent audit is required')
    if digest(parent/'protocol.json') != meta['protocol_sha256']:
        raise ValueError('parent protocol differs')
    for name, sha in meta['plan']['source_sha256'].items():
        if digest(parent/'source'/name) != sha:
            raise ValueError('parent source snapshot differs')
    downloads = Path(meta['plan']['downloads'])
    if digest(downloads/'download-manifest.json') != data['download_manifest_sha256']:
        raise ValueError('original raw manifest differs')
    raw = json.loads((downloads/'download-manifest.json').read_text())
    for item in raw['files']:
        if item['status'] != 'downloaded' or digest(downloads/item['path']) != item['sha256']:
            raise ValueError('original raw payload differs')
    rows = {a: [] for a in ASSETS}
    with gzip.open(parent/'rows.jsonl.gz', 'rt') as stream:
        for line in stream:
            r = json.loads(line)
            rows[r['asset']].append(r)
    baseline = {a: {m: {} for m in MULTIPLIERS} for a in ASSETS}
    for asset in ASSETS:
        directory = parent/asset
        if digest(directory/'research.json') != meta['research_sha256'][asset]:
            raise ValueError('parent asset research differs')
        asset_meta = json.loads((directory/'research.json').read_text())
        if digest(directory/'predictions.jsonl.gz') != asset_meta['predictions_sha256']:
            raise ValueError('parent forecasts differ')
        rowmap = {r['start']: r for r in rows[asset]}
        if len(rowmap) != len(rows[asset]):
            raise ValueError('duplicate asset row')
        with gzip.open(directory/'predictions.jsonl.gz', 'rt') as stream:
            for line in stream:
                p = json.loads(line)
                if p['target_name'] not in ('payout100', 'payout1000') or p['candidate'] != 'activity_hurdle':
                    continue
                multiplier = int(p['target_name'][6:])
                r = rowmap[p['start']]
                if any(p[k] != r[k] for k in ('asset', 'period', 'split', 'entry', 'move', 'valid')):
                    raise ValueError('parent trace and row mismatch')
                baseline[asset][multiplier][r['start']] = p['width_ppm']
        for multiplier in MULTIPLIERS:
            expected = {r['start'] for r in rows[asset] if r['split'] != 'train'}
            if set(baseline[asset][multiplier]) != expected:
                raise ValueError('parent prediction grid incomplete')
    return rows, baseline, dict(parent_sha256=digest(parent/'research.json'),
                               dataset_sha256=digest(parent/'dataset.json'),
                               rows_sha256=digest(parent/'rows.jsonl.gz'), raw_payloads_verified=len(raw['files']))


def risk_metrics(rows, forecasts):
    scored = [(r, p) for r, p in zip(rows, forecasts) if r['valid'] and p['floor'] is not None]
    n = len(scored)
    output = dict(n=n)
    for name, key, label in (('zero', 'p0', lambda r: r['move'] == 0),
                             ('floor', 'floor', lambda r: required_width(r) <= 1)):
        if not n:
            output.update({name+'_'+field: None for field in ('predicted', 'observed', 'brier', 'log_loss')})
            continue
        actual = [float(label(r)) for r, _ in scored]
        probability = [max(1e-12, min(1-1e-12, p[key])) for _, p in scored]
        output.update({name+'_predicted': sum(probability)/n, name+'_observed': sum(actual)/n,
                       name+'_brier': sum((p-y)**2 for p, y in zip(probability, actual))/n,
                       name+'_log_loss': sum(-y*math.log(p)-(1-y)*math.log(1-p) for p, y in zip(probability, actual))/n})
    return output


def choose_risk(rows, asset):
    train = [r for r in rows if r['split'] == 'train']
    validation = [r for r in rows if r['split'] == 'validation']
    dates = sorted({r['period'] for r in validation})
    models, rankings, records = {}, [], []
    for family in FAMILIES:
        for ridge in RIDGES:
            name = f'{family}:ridge{ridge}'
            model = fit_risk(train, asset, '2026-01-01', family, ridge)
            models[name] = model
            values = risk_series(validation, model, False)
            losses = []
            for day in dates:
                indexes = [i for i, r in enumerate(validation) if r['period'] == day]
                m = risk_metrics([validation[i] for i in indexes], [values[i] for i in indexes])
                records.append(dict(asset=asset, candidate=name, period=day, split='validation', mode='static', **m))
                if not m['n']:
                    raise ValueError('empty validation date')
                losses.append((m['zero_log_loss']+m['floor_log_loss'])/2)
            rankings.append(dict(name=name, score=sum(losses)/len(losses), order=len(rankings)))
    rankings.sort(key=lambda r: (r['score'], r['order']))
    return models, rankings, records


def summary(rows, records, multiplier):
    if len(rows) != len(records):
        raise ValueError('prediction length differs')
    eligible = [(r, p) for r, p in zip(rows, records) if p['shadow'] is not None]
    offered = [(r, p) for r, p in eligible if p['offered']]
    n, k = len(eligible), len(offered)
    wins = sum(p['survived'] for _, p in offered)
    shadow = sum(p['shadow'] for _, p in eligible)
    target = .95/multiplier
    return dict(grid=len(rows), pre_entry_predictions=sum(p['width'] is not None for p in records),
                pre_entry_offered=sum(p['offered'] for p in records), eligible=n, offered=k,
                availability=k/n if n else None, wins=wins, shadow_wins=shadow,
                survival=wins/k if k else None, shadow_survival=shadow/n if n else None,
                target=target, survival_to_target=wins/k/target if k else None,
                gross_equal_stake_return=1-multiplier*wins/k if k else None,
                mean_width_ppm=sum(p['width'] for _, p in offered)/k if k else None,
                zero_wins=sum(r['move'] == 0 and p['survived'] for r, p in offered),
                minimum_width_wins=sum(required_width(r) <= 1 and p['survived'] for r, p in offered),
                predicted_floor_mean=sum(p['floor'] for _, p in offered)/k if k else None,
                realized_floor=sum(required_width(r) <= 1 for r, _ in offered)/k if k else None,
                target_expected_wins=k*target, at_least_20_target_expected_wins=k*target >= 20)


def grouped_metrics(asset, rows, records, multiplier, variant):
    output = []
    for part in ('validation', 'test'):
        dates = sorted({r['period'] for r in rows if r['split'] == part})
        for period in ('pooled', *dates):
            indexes = [i for i, r in enumerate(rows) if r['split'] == part and (period == 'pooled' or r['period'] == period)]
            a, b = [rows[i] for i in indexes], [records[i] for i in indexes]
            groups = [('overall', 'all', list(range(len(a))))]
            for axis, names in (('activity_state', ('active', 'sparse', 'bursty', 'frozen')),
                                ('market_regime', ('range', 'mixed', 'pump', 'dump')),
                                ('calendar', ('weekday', 'weekend'))):
                for name in names:
                    selected = [i for i, r in enumerate(a) if ('weekend' if weekend(r) else 'weekday') == name] if axis == 'calendar' else [i for i, r in enumerate(a) if r[axis] == name]
                    groups.append((axis, name, selected))
            for axis, name, indexes in groups:
                output.append(dict(asset=asset, multiplier=multiplier, variant=variant, split=part,
                                   period=period, axis=axis, group=name,
                                   **summary([a[i] for i in indexes], [b[i] for i in indexes], multiplier)))
    return output


def reliability(rows, forecasts, asset, mode):
    boundaries = (0, .0001, .0005, .00095, .005, .0095, .05, .2, .5, 1.)
    output = []
    for split in ('validation', 'test'):
        for left, right in zip(boundaries, boundaries[1:]):
            indexes = [i for i, (r, p) in enumerate(zip(rows, forecasts)) if r['split'] == split
                       and r['valid'] and p['floor'] is not None and left <= p['floor'] < right]
            output.append(dict(asset=asset, mode=mode, split=split, lower=left, upper=right,
                               **risk_metrics([rows[i] for i in indexes], [forecasts[i] for i in indexes])))
    return output


def study_asset(asset, rows, baseline, output):
    destination = output/asset
    destination.mkdir()
    models, ranking, risk_records = choose_risk(rows, asset)
    selected = ranking[0]['name']; model = models[selected]
    train = [r for r in rows if r['split'] == 'train']
    positive = fit_positive(train, asset, '2026-01-01', model['family'])
    dump(destination/'models.json', dict(asset=asset, candidates=models, selected=selected, positive=positive))
    dump(destination/'selection.json', dict(selected=selected, ranking=ranking, selection=SPEC['selection'],
                                          no_gate_or_pricing_selection=True))
    pinned = {name: digest(destination/name) for name in ('models.json', 'selection.json')}
    later = [r for r in rows if r['split'] != 'train']
    forecasts = {online: risk_series(later, model, online) for online in (False, True)}
    calibration = []
    for online, values in forecasts.items():
        mode = 'online' if online else 'static'
        calibration.extend(reliability(later, values, asset, mode))
        for part in ('validation', 'test'):
            dates = sorted({r['period'] for r in later if r['split'] == part})
            for day in ('pooled', *dates):
                if part == 'validation' and day != 'pooled' and not online:
                    continue  # Already retained once in the candidate-selection table.
                indexes = [i for i, r in enumerate(later) if r['split'] == part and (day == 'pooled' or r['period'] == day)]
                risk_records.append(dict(asset=asset, candidate=selected, period=day, split=part, mode=mode,
                                         **risk_metrics([later[i] for i in indexes], [values[i] for i in indexes])))
    constant = [dict(p0=model['period_balanced_zero'], floor=model['period_balanced_floor']) if r['adaptive_features'] is not None else dict(p0=None, floor=None) for r in later]
    for part in ('validation', 'test'):
        indexes = [i for i, r in enumerate(later) if r['split'] == part]
        risk_records.append(dict(asset=asset, candidate='constant_training_rate', period='pooled', split=part, mode='static',
                                 **risk_metrics([later[i] for i in indexes], [constant[i] for i in indexes])))
    metrics = []
    with gzip.open(destination/'predictions.jsonl.gz', 'wt', compresslevel=5) as stream:
        for multiplier in MULTIPLIERS:
            target = .95/multiplier
            widths = {online: [conditional_width(r, p, positive, target) for r, p in zip(later, values)]
                      for online, values in forecasts.items()}
            for variant in VARIANTS:
                name, _, online, _, _ = variant
                records = []
                for i, r in enumerate(later):
                    p, c = forecasts[online][i], widths[online][i]
                    d = decision(r, p, c, baseline[multiplier][r['start']], variant, multiplier)
                    record = dict(asset=asset, multiplier=multiplier, variant=name, start=r['start'],
                        period=r['period'], split=r['split'], **d, **p, positive_q=c['positive_q'],
                        tail_mass=c['tail_mass'], tail_supported=c['supported'])
                    records.append(record)
                    stream.write(json.dumps(record, separators=(',', ':'), allow_nan=False)+'\n')
                metrics.extend(grouped_metrics(asset, later, records, multiplier, name))
            print(json.dumps(dict(asset=asset, multiplier=multiplier, stage='scored', selected_risk=selected)), flush=True)
    for name, sha in pinned.items():
        if digest(destination/name) != sha:
            raise ValueError('pinned models changed during diagnostics')
    write_csv(destination/'metrics.csv', metrics, FIELDS)
    write_csv(destination/'risk-metrics.csv', risk_records)
    write_csv(destination/'risk-reliability.csv', calibration)
    primary = [m for m in metrics if m['split'] == 'test' and m['period'] == 'pooled' and m['axis'] == 'overall']
    screens = []
    for m in primary:
        daily = [x for x in metrics if x['split'] == 'test' and x['period'] != 'pooled' and x['axis'] == 'overall'
                 and x['multiplier'] == m['multiplier'] and x['variant'] == m['variant'] and x['eligible'] >= 20]
        screens.append(dict(multiplier=m['multiplier'], variant=m['variant'],
                            minimum_daily_availability=min(x['availability'] for x in daily),
                            passes_availability_reference=all(x['availability'] >= .85 for x in daily),
                            in_pooled_relative_reference=m['survival_to_target'] is not None and .75 <= m['survival_to_target'] <= 1.25,
                            adequate_expected_wins=m['at_least_20_target_expected_wins'],
                            empty=m['offered'] == 0))
    result = dict(asset=asset, selected_risk=selected, ranking=ranking, primary_test=primary,
                  screens=screens, fit_windows=model['windows'], positive_fit_windows=positive['fitted_windows'],
                  artifact_sha256={p.name: digest(p) for p in destination.iterdir()},
                  prospective=False, live_policy_changed=False)
    dump(destination/'research.json', result)
    return result


def declare(parent, output):
    if output.exists():
        raise ValueError('preserve earlier attempts; choose a new directory')
    output.mkdir(parents=True); (output/'source').mkdir()
    sources = [Path(__file__), Path(__file__).with_name('payout_risk.py')]
    for path in sources:
        shutil.copyfile(path, output/'source'/path.name)
    protocol = dict(PLAN, parent=str(parent.resolve()), parent_sha256=digest(parent/'research.json'),
                    source_sha256={p.name: digest(p) for p in sources},
                    python=sys.version, declared_before_this_experiment=True)
    dump(output/'protocol.json', protocol)
    return protocol


def run(parent, output):
    start = time.monotonic()
    protocol = json.loads((output/'protocol.json').read_text())
    if digest(parent/'research.json') != protocol['parent_sha256']:
        raise ValueError('parent differs from declaration')
    for name, sha in protocol['source_sha256'].items():
        if digest(Path(__file__).with_name(name)) != sha or digest(output/'source'/name) != sha:
            raise ValueError('source changed after declaration')
    rows, baseline, bindings = load_parent(parent)
    results = [study_asset(a, rows[a], baseline[a], output) for a in ASSETS]
    result = dict(protocol=protocol, protocol_sha256=digest(output/'protocol.json'), bindings=bindings,
                  assets=results, elapsed_seconds=time.monotonic()-start,
                  research_sha256={a: digest(output/a/'research.json') for a in ASSETS},
                  no_promotion=True, live_policy_changed=False)
    dump(output/'research.json', result)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--parent', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--declare', action='store_true')
    args = parser.parse_args()
    r = declare(args.parent, args.output) if args.declare else run(args.parent, args.output)
    print(json.dumps(dict(output=str(args.output), completed='assets' in r and 'elapsed_seconds' in r)))
