#!/usr/bin/env python3
"""Independent ETH/HYPE corridor fits on pinned raw monthly oracle days."""
import argparse
from collections import Counter, defaultdict
from copy import deepcopy
from fractions import Fraction
import gzip
import json
import math
from pathlib import Path
import shutil
from statistics import mean
import time

from adaptive_corridor import evaluate, fit_scale, predict as simple_predict, required_width
from capture_dataset import file_hash
from chronological_raw_priors import training_rows
from fetch_asset_oracles import ASSETS, DATES, dump, origin
from frozen_context_cdf import fit as fit_context, series as context_series
from full_raw_pipeline import fit_bundle, price
from investigate_capture import write_csv
from oracle_gap_features import attach, positive, raw_timestamp
from research_activity_calibration import fit, predict, shadow
from research_flat_pause import ENGINE_SPEC
from research_frozen_pricing import SPECS as OVERLAYS, fit_overlay, reprice
from research_market_regimes import price_units
from research_raw_flat_panels import prepare_rows

PAYOUTS = (2, 5, 10, 25, 50, 100, 250, 1000, 10000)
TARGETS = (('legacy48', .48, None),) + tuple((f'payout{m}', .95 / m, m) for m in PAYOUTS)
OVERLAY = next(s for s in OVERLAYS if s['name'] == 'hurdle_all_120')
CANDIDATES = ('volatility', 'activity_hurdle', 'full_core', 'timing_priceable', 'market_priceable')
PLAN = dict(assets=ASSETS, target_definitions=TARGETS, candidates=CANDIDATES,
            train_end='2025-12-01', validation_dates=list(DATES[14:19]), test_dates=list(DATES[19:]),
            selection='Choose legacy48 family per asset using validation only. Mean daily absolute error + 0.5 mean populated activity/regime error + 0.25 worst daily error, in percentage points; declared candidate order breaks ties.',
            payout_fits='Separate activity+hurdle fit for each .95/M target; no reuse of the legacy48 probability. Full-core and conditional-CDF families are legacy48-only because their retained update rules fix .48.',
            all_quotes_open=True, maturity_delay_ms=30000, width_bounds_ppm=[1, 50000],
            raw_only=True, native_capture=False, live_policy_changed=False,
            period_reset='Reset online state each monthly sample day; no history or state interpolated between dates',
            evidence='Retrospective first-of-month historical development evidence; no prospective certification or net LP economics',
            primary_band=[.43, .53], minimum_descriptive_cell=20)


def split(day):
    return 'train' if day <= PLAN['train_end'] else 'validation' if day <= '2026-05-01' else 'test'


def source_files():
    """Snapshot the actual local Python import closure, excluding test/runtime libs."""
    import sys
    root = Path(__file__).resolve().parent
    paths = {Path(__file__).resolve(), root / 'fetch_asset_oracles.py'}
    for module in list(sys.modules.values()):
        name = getattr(module, '__file__', None)
        if name:
            path = Path(name).resolve()
            if path.parent == root and path.suffix == '.py':
                paths.add(path)
    return sorted(paths)


def declare(downloads, output):
    if output.exists():
        raise ValueError('preserve previous research; use a new directory')
    protocol = json.loads((downloads / 'download-protocol.json').read_text())
    if tuple(protocol['assets']) != ASSETS or tuple(protocol['dates']) != DATES:
        raise ValueError('unexpected download universe')
    output.mkdir(parents=True)
    (output / 'source').mkdir()
    sources = source_files()
    for path in sources:
        shutil.copyfile(path, output / 'source' / path.name)
    plan = dict(PLAN, downloads=str(downloads.resolve()),
                download_protocol_sha256=file_hash(downloads / 'download-protocol.json'),
                source_sha256={p.name: file_hash(p) for p in sources})
    dump(output / 'protocol.json', plan)
    return plan


def parse_day(files, root, day, assets):
    """Split actual raw streams by asset; no synthetic pairs or mark substitution."""
    observed = {a: [] for a in assets}
    context = {a: [] for a in assets}
    markers = {a: [] for a in assets}
    waiting = {a: False for a in assets}
    previous = None
    for item in files:
        path = root / item['path']
        if item['status'] != 'downloaded' or file_hash(path) != item['sha256']:
            raise ValueError('raw slice missing or changed')
        for line in gzip.decompress(path.read_bytes()).decode().splitlines():
            if not line:
                waiting = {a: True for a in assets}
                continue
            stamp, payload = line.split(' ', 1)
            at = raw_timestamp(stamp)
            if not item['at_ms'] <= at < item['at_ms'] + item['duration_ms'] or (previous is not None and at < previous):
                raise ValueError('raw timestamp outside slice or regressing')
            previous = at
            message = json.loads(payload)
            if message['channel'] != 'activeAssetCtx' or message['data']['coin'] not in assets:
                raise ValueError('wrong raw channel or asset')
            asset = message['data']['coin']
            ctx = message['data']['ctx']
            px = price_units(ctx['oraclePx'])
            if px <= 0:
                raise ValueError('nonpositive oracle price')
            if waiting[asset]:
                markers[asset].append(dict(known_at=at))
                waiting[asset] = False
            observed[asset].append((at, px))
            context[asset].append((at, px, positive(ctx.get('markPx')), positive(ctx.get('midPx'))))
    result, profiles = {}, []
    for asset in assets:
        if not observed[asset]:
            raise ValueError(f'no actual oracle observations for declared available {asset} {day}')
        if waiting[asset]:
            markers[asset].append(dict(known_at=origin(day) + 86400000 - 1))
        panel = dict(day=day, fetch_start=origin(day), fetch_end=origin(day) + 86400000)
        rows = attach(prepare_rows(observed[asset], panel, markers[asset]), context[asset], origin(day))
        for r in rows:
            r.update(asset=asset, split=split(day))
        if len(rows) != 2880 or [r['start'] for r in rows] != list(range(origin(day), origin(day) + 86400000, 30000)):
            raise ValueError('complete unmodified day grid required')
        result[asset] = rows
        clean = [r for r in rows if r['valid'] and r['adaptive_features'] is not None]
        profiles.append(dict(asset=asset, day=day, split=split(day), grid=len(rows),
                             observations=len(observed[asset]), disconnect_markers=len(markers[asset]),
                             healthy=sum(r['valid'] for r in rows), clean=len(clean),
                             zero_motion=sum(r['move'] == 0 for r in clean),
                             minimum_width_survivors=sum(required_width(r) <= 1 for r in clean),
                             activities=dict(Counter(r['activity_state'] for r in clean)),
                             regimes=dict(Counter(r['market_regime'] for r in clean))))
    return result, profiles


def build_data(downloads, output, plan):
    protocol_path = downloads / 'download-protocol.json'
    if file_hash(protocol_path) != plan['download_protocol_sha256']:
        raise ValueError('download declaration changed')
    protocol = json.loads(protocol_path.read_text())
    manifest_path = downloads / 'download-manifest.json'
    manifest = json.loads(manifest_path.read_text())
    if (not manifest['complete'] or manifest['protocol_sha256'] != file_hash(protocol_path)
            or file_hash(downloads / 'exchange-metadata.json') != protocol['metadata_sha256']
            or file_hash(downloads / 'fetch-source.py') != protocol['fetcher_sha256']):
        raise ValueError('download provenance incomplete')
    keys = ('day', 'at_ms', 'duration_ms', 'assets', 'path', 'url')
    expected = [{k: r[k] for k in keys} for r in protocol['requests']]
    actual = [{k: r[k] for k in keys} for r in manifest['files']]
    if expected != actual:
        raise ValueError('download requests differ from pinned declaration')
    by_asset = {a: {} for a in ASSETS}
    profiles = []
    for day in DATES:
        files = [f for f in manifest['files'] if f['day'] == day]
        if len(files) != 144 or [f['at_ms'] for f in files] != list(range(origin(day), origin(day) + 86400000, 600000)):
            raise ValueError('missing or duplicate raw slices')
        available = files[0]['assets']
        parts, profile = parse_day(files, downloads, day, available)
        profiles.extend(profile)
        for asset, rows in parts.items():
            by_asset[asset][day] = rows
        print(json.dumps(dict(stage='parse', day=day, assets=available)), flush=True)
    with gzip.open(output / 'rows.jsonl.gz', 'wt', compresslevel=5) as stream:
        for asset in ASSETS:
            for day in by_asset[asset]:
                for row in by_asset[asset][day]:
                    stream.write(json.dumps(row, separators=(',', ':'), allow_nan=False) + '\n')
    dump(output / 'dataset.json', dict(download_manifest_sha256=file_hash(manifest_path),
                                      rows_sha256=file_hash(output / 'rows.jsonl.gz'), profiles=profiles))
    return by_asset, profiles


def open_values(values):
    return [dict(p, paused=False, floor_reason='', survived=p['shadow_survived']) for p in values]


def fit_target(rows, q):
    engine = fit(rows, ENGINE_SPEC, q)
    overlay = fit_overlay(shadow(predict(rows, engine)), OVERLAY, q)
    return dict(engine=engine, overlay=overlay)


def target_series(rows, bundle):
    return open_values(reprice(predict(rows, bundle['engine']), bundle['overlay']))


def baseline_series(rows, model):
    out = []
    for row in rows:
        width, capped = simple_predict(row, model) if row['adaptive_features'] is not None else (None, False)
        hit = row['move'] < row['entry'] * width // 1000000 if width is not None and row['valid'] else None
        out.append(dict(row=row, width_ppm=width, capped=capped, survived=hit, shadow_survived=hit, paused=False))
    return out


def summary(values, q, multiplier=None):
    scored = [p for p in values if p['survived'] is not None]
    n = len(scored)
    wins = sum(p['survived'] for p in scored)
    return dict(grid=len(values), pre_entry_predictions=sum(p['width_ppm'] is not None for p in values),
                eligible=n, offered=n, wins=wins, survival=wins / n if n else None,
                target=q, error_pp=100 * (wins / n - q) if n else None,
                mean_width_ppm=mean(p['width_ppm'] for p in scored) if n else None,
                at_minimum_width=sum(p['width_ppm'] == 1 for p in scored),
                capped=sum(p['capped'] for p in scored),
                expected_wins_at_target=n*q,
                gross_equal_stake_return=1 - multiplier*wins/n if n and multiplier else None)


def groups(values):
    yield 'overall', 'all', values
    for key, names in (('activity_state', ('active', 'sparse', 'bursty', 'frozen')),
                       ('market_regime', ('range', 'pump', 'dump', 'mixed'))):
        for name in names:
            yield key, name, [p for p in values if p['row'][key] == name]


def selection_score(values):
    daily, conditional = [], []
    for day in sorted({p['row']['period'] for p in values}):
        part = [p for p in values if p['row']['period'] == day]
        for axis, _, rows in groups(part):
            cell = summary(rows, .48)
            if cell['eligible'] >= 20:
                (daily if axis == 'overall' else conditional).append(abs(cell['error_pp']))
    if not daily:
        raise ValueError('no eligible validation periods')
    return mean(daily) + .5 * (mean(conditional) if conditional else 0) + .25 * max(daily)


def retention_bound(n, zeros, upper):
    if not n:
        return None
    u = Fraction(upper)
    return min(n, ((n - zeros) * u.denominator) // (u.denominator - u.numerator)) / n


def fit_asset(asset, days, output):
    destination = output / asset
    destination.mkdir()
    train_dates = [d for d in days if split(d) == 'train']
    train, provenance = training_rows([], days, train_dates, '2026-01-01', True)
    clean = [r for r in train if r['valid'] and r['adaptive_features'] is not None]
    later = [r for day, rows in days.items() if split(day) != 'train' for r in rows]
    baseline = fit_scale(clean, dict(family='volatility', fast_weight=0., trend_weight=0.,
                                   jump_weight=0., maximum_width_ppm=50000), .48)
    # No BTC model artifacts or fitted coefficients enter any asset's fit.
    core = fit_bundle([], days, train_dates, '2026-01-01', {'overlay': {'spec': OVERLAY}}, 'raw_core')
    context_models = {}
    unavailable = {}
    for family in ('timing', 'market'):
        try:
            context_models[family] = fit_context(train, family)
        except ValueError as error:
            if str(error) not in ('at least fifty clean frozen training paths required', 'positive-movement references required'):
                raise
            unavailable[family + '_priceable'] = str(error)
    models = dict(asset=asset, training_dates=train_dates, training_provenance=provenance,
                  volatility=baseline, core=core, context=context_models, targets={})
    validation = [r for r in later if r['split'] == 'validation']
    _, core_values = price(validation, core)
    core_values = open_values(core_values)
    primary = dict(volatility=baseline_series(validation, baseline), full_core=core_values)
    target48 = fit_target(train, .48)
    primary['activity_hurdle'] = target_series(validation, target48)
    for family, model in context_models.items():
        primary[family + '_priceable'] = context_series(core_values, model, 'priceable', None)
    ranking = sorted((dict(candidate=c, score=selection_score(primary[c]), order=i)
                      for i, c in enumerate(CANDIDATES) if c in primary), key=lambda r: (r['score'], r['order']))
    selected = ranking[0]['candidate']
    # Bind choice and all legacy models before accessing test paths in pricing.
    models['targets']['legacy48'] = target48
    dump(destination / 'selection.json', dict(selected=selected, ranking=ranking, unavailable=unavailable,
                                             validation_dates=PLAN['validation_dates'], plan=PLAN))
    dump(destination / 'legacy-models.json', models)
    selection_hash = file_hash(destination / 'selection.json')
    legacy_hash = file_hash(destination / 'legacy-models.json')
    metrics, feasibility = [], []
    with gzip.open(destination / 'predictions.jsonl.gz', 'wt', compresslevel=5) as stream:
        for name, q, multiplier in TARGETS:
            if name != 'legacy48':
                models['targets'][name] = fit_target(train, q)
            bundle = models['targets'][name]
            values = target_series(later, bundle)
            variants = {'activity_hurdle': values}
            if name == 'legacy48':
                _, values_core = price(later, core)
                values_core = open_values(values_core)
                variants.update(volatility=baseline_series(later, baseline), full_core=values_core)
                for family, model in context_models.items():
                    variants[family + '_priceable'] = context_series(values_core, model, 'priceable', None)
            for candidate, predictions in variants.items():
                for part_name in ('validation', 'test'):
                    part = [p for p in predictions if p['row']['split'] == part_name]
                    for period in ('pooled', *sorted({p['row']['period'] for p in part})):
                        period_values = part if period == 'pooled' else [p for p in part if p['row']['period'] == period]
                        for axis, group, cell in groups(period_values):
                            metrics.append(dict(asset=asset, target_name=name, candidate=candidate, split=part_name,
                                                period=period, axis=axis, group=group, **summary(cell, q, multiplier)))
                for p in predictions:
                    r = p['row']
                    stream.write(json.dumps(dict(asset=asset, target_name=name, candidate=candidate,
                        start=r['start'], period=r['period'], split=r['split'], activity=r['activity_state'],
                        regime=r['market_regime'], valid=r['valid'], entry=r['entry'], move=r['move'],
                        width_ppm=p['width_ppm'], survived=p['survived']), separators=(',', ':'), allow_nan=False) + '\n')
            for day, rows in days.items():
                if split(day) == 'train':
                    continue
                eligible = [r for r in rows if r['valid'] and r['adaptive_features'] is not None]
                n = len(eligible)
                zeros = sum(r['move'] == 0 for r in eligible)
                feasibility.append(dict(asset=asset, target_name=name, day=day, split=split(day), n=n, zeros=zeros,
                    zero_fraction=zeros/n if n else None,
                    retention_at_target=retention_bound(n, zeros, Fraction(48, 100) if multiplier is None else Fraction(95, 100*multiplier)),
                    retention_at_break_even=retention_bound(n, zeros, Fraction(1, multiplier)) if multiplier else None))
            print(json.dumps(dict(stage='fit', asset=asset, target=name, selected=selected)), flush=True)
    if (selection_hash != file_hash(destination / 'selection.json')
            or legacy_hash != file_hash(destination / 'legacy-models.json')):
        raise ValueError('legacy choice/model changed during later scoring')
    dump(destination / 'models.json', models)
    write_csv(destination / 'metrics.csv', metrics, list(metrics[0]))
    write_csv(destination / 'feasibility.csv', feasibility, list(feasibility[0]))
    result = dict(asset=asset, selected=selected, ranking=ranking, unavailable=unavailable,
                  training_dates=train_dates, clean_training_paths=len(clean),
                  selection_sha256=selection_hash, legacy_models_sha256=legacy_hash,
                  models_sha256=file_hash(destination / 'models.json'),
                  predictions_sha256=file_hash(destination / 'predictions.jsonl.gz'),
                  metrics_sha256=file_hash(destination / 'metrics.csv'),
                  feasibility_sha256=file_hash(destination / 'feasibility.csv'),
                  primary_test=[r for r in metrics if r['target_name'] == 'legacy48' and r['candidate'] == selected
                                and r['split'] == 'test' and r['period'] == 'pooled'],
                  payout_test=[r for r in metrics if r['target_name'] != 'legacy48' and r['split'] == 'test'
                               and r['period'] == 'pooled' and r['axis'] == 'overall'])
    dump(destination / 'research.json', result)
    return result


def run(downloads, output):
    plan = json.loads((output / 'protocol.json').read_text())
    for name, digest in plan['source_sha256'].items():
        if file_hash(Path(__file__).with_name(name)) != digest or file_hash(output / 'source' / name) != digest:
            raise ValueError('research source changed after declaration: ' + name)
    if (output / 'dataset.json').exists():
        raise ValueError('preserve existing attempt; create a new declared output')
    start = time.monotonic()
    days, profiles = build_data(downloads, output, plan)
    results = [fit_asset(asset, days[asset], output) for asset in ASSETS]
    result = dict(plan=plan, protocol_sha256=file_hash(output / 'protocol.json'),
                  dataset_sha256=file_hash(output / 'dataset.json'),
                  results=results, seconds=time.monotonic()-start,
                  research_sha256={a: file_hash(output / a / 'research.json') for a in ASSETS},
                  live_policy_changed=False, prospective_validation=False)
    dump(output / 'research.json', result)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--downloads', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--declare', action='store_true')
    args = parser.parse_args()
    result = declare(args.downloads, args.output) if args.declare else run(args.downloads, args.output)
    print(json.dumps(dict(output=str(args.output), declared=args.declare, completed='results' in result)))
