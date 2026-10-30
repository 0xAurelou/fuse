#!/usr/bin/env python3
"""Replay adaptive research on third-party recorded Hyperliquid oracle samples.

Normalized index_price is mapped from oraclePx by the provider. This is neither
a fabricated pair of receivers nor a native prospective capture verification.
"""
import argparse
from collections import Counter
import csv
from datetime import datetime, timezone
from decimal import Decimal
import gzip
import json
import math
from pathlib import Path
import shutil

from adaptive_corridor import features, predict
from capture_dataset import file_hash
from investigate_capture import analyze_run, reconstruct, write_csv
from research_market_regimes import (compare, episodes, evaluate_research,
                                     fit_research_models, model_for, price_units,
                                     regime, utc)

DAY = 86_400_000
FRESHNESS = 8000
DEPENDENCIES = ('research_oracle_history.py', 'research_market_regimes.py',
                'adaptive_corridor.py', 'investigate_capture.py', 'capture_dataset.py',
                'analyze_capture.py', 'prospective_capture.py', 'fetch_regime_history.py')


def observations(path, start, end):
    result = []
    missing = 0
    previous = None
    with gzip.open(path, 'rt', newline='') as stream:
        for row in csv.DictReader(stream):
            if row['exchange'] != 'hyperliquid' or row['symbol'] != 'BTC':
                raise ValueError('unexpected exchange or symbol in historical oracle file')
            at = int(row['local_timestamp']) // 1000
            if not start <= at < end or (previous is not None and at < previous):
                raise ValueError('out-of-horizon or regressing provider receipt timestamp')
            previous = at
            if not row['index_price']:
                missing += 1
                continue
            # Never substitute mark_price or last_price for oraclePx/index_price.
            result.append((at, price_units(row['index_price'])))
    if not result:
        raise ValueError('no recorded oracle values in sample')
    return result, missing


def recorded_windows(observed, start, end, freshness=FRESHNESS):
    """Thirty-second first-passage paths with a single-stream freshness screen."""
    if end <= start or (end - start) % 30_000:
        raise ValueError('complete 30-second horizon required')
    rows = []
    last_at = None
    last_price = None
    window = dict(start=start, expiry=start + 30_000, entry=None, move=0, valid=False)

    def fresh(at):
        return last_at is not None and 0 <= at - last_at <= freshness

    def finish():
        window['valid'] = window['valid'] and fresh(window['expiry'])
        rows.append(dict(window))
        at = window['expiry']
        return dict(start=at, expiry=at + 30_000, entry=last_price, move=0, valid=fresh(at))

    for at, price in observed:
        if not start <= at < end or (last_at is not None and at < last_at):
            raise ValueError('invalid historical observation order/horizon')
        while at >= window['expiry']:
            window = finish()
        if last_at is not None and not fresh(at):
            window['valid'] = False
        if window['entry'] is not None:
            window['move'] = max(window['move'], abs(price - window['entry']))
        last_at, last_price = at, price
    while window['expiry'] <= end:
        window = finish()
    features(rows, observed, start)
    add_regimes(rows)
    return rows


def add_regimes(rows):
    for row in rows:
        f, lag = row['adaptive_features'], row['lag_features']
        if f is not None:
            f.update(net_300_bps=lag['net_bps'],
                     directional_strength=abs(lag['net_bps']) / lag['vol_bps'] if lag['vol_bps'] else 0,
                     vol_300_unscaled_bps=lag['vol_bps'])
        row['market_regime'] = regime(f)


def load_capture_rows(directory):
    run = analyze_run(directory, [])
    with (directory / 'receipts.jsonl').open() as stream:
        raw = [json.loads(line) for line in stream]
    records = [dict(at=r['at'], source=r['source'],
                    price=int(Decimal(r['raw']['data']['ctx']['oraclePx']) * 1_000_000)) for r in raw]
    start = run['manifest']['frozen_at_ms']
    _, paired = reconstruct(records, run['manifest']['policy'], start,
                            start + run['manifest']['duration_ms'])
    features(run['rows'], paired, start)
    add_regimes(run['rows'])
    return run


def fit_history(rows, dates, q, maximum):
    if len(dates) < 5:
        raise ValueError('at least five nonconsecutive sample days required')
    a, b = int(len(dates) * .6), int(len(dates) * .8)
    day_splits = {date: ('train' if i < a else 'validation' if i < b else 'test')
                  for i, date in enumerate(dates)}
    for row in rows:
        row['split'] = day_splits[row['date']]
    clean = [r for r in rows if r['valid'] and r['adaptive_features'] is not None]
    models = fit_research_models([r for r in clean if r['split'] == 'train'], q, maximum)
    return models, compare(clean, models, q), day_splits


def make_report(result):
    lines = ['# Historical Hyperliquid oracle research', '',
             '**Third-party normalized oracle history, distinct from native paired-receiver captures. No live candidate promoted or collection started.**', '',
             'Tardis records the activeAssetCtx stream. Its archived public normalizer maps `ctx.oraclePx` to `index_price`. Files were downloaded anonymously from the documented free first-of-month samples. Gzip CRCs were checked and local SHA-256 hashes pinned; these are locally computed hashes, not published provider checksum attestations.', '',
             f"Downloaded **{len(result['samples'])}** sample days from **{result['dates'][0]}** through **{result['dates'][-1]}**, containing **{sum(s['observations'] for s in result['samples'])}** normalized oracle observations. These are sampled days, not a continuous recording between those dates.", '',
             '## Data qualification', '',
             'Use provider arrival timestamps and exact integer prices; grid each sample day into nonoverlapping 30-second paths. Entry is the last observation strictly before entry, and touches fail. An eight-second observation-gap screen excludes incomplete paths and any five-minute feature history touching an excluded path. No gap or gap between months is interpolated.', '',
             'The provider normalizer emits when a tracked field changes, and snapshots can carry the previous index value. Missing normalized rows are not a proven feed outage; received rows are not proof of complete upstream observations or two-source agreement. The freshness screen is conservative research eligibility, not equivalence to the native oracle admission policy. Daily boundaries reset history.', '',
             '| Day | Observations | Freshness-eligible paths | Clean-history eligible paths | Gap intervals >8s |',
             '| --- | ---: | ---: | ---: | ---: |']
    for s in result['samples']:
        lines.append(f"| {s['date']} | {s['observations']} | {s['eligible_windows']} | {s['clean_windows']} | {s['gaps_over_8s']} |")
    lines += ['', '## Pump/dump development evidence', '',
              'Use the same pre-entry research definitions as the exchange-proxy iteration: preceding five-minute absolute log return ≥20 bps and absolute return / realized log-return variation ≥1.5; sign separates pump and dump. Range means absolute return ≤5 bps and this ratio ≤0.5; other histories are mixed. This differs from the original efficiency ≥0.6 taxonomy.', '',
              '| Slice | Pump windows / clusters | Dump windows / clusters | Range windows |',
              '| --- | ---: | ---: | ---: |']
    for split, count in result['regime_counts'].items():
        lines.append(f"| {split} | {count['pump']} / {count['pump_clusters']} | {count['dump']} / {count['dump_clusters']} | {count['range']} |")
    lines += ['', 'Clusters merge overlapping same-direction five-minute lookback plus 30-second outcome contexts. They are not claimed statistically independent; opposite-direction contexts may overlap.', '',
              '## Chronological formula comparison', '',
              f"Target **{result['target_survival']:.2%}**, the legacy reference experiment. First 60% of sample days train all coefficients; next 20% and final 20% only score them. Exact day assignments and frozen coefficients are retained in `research.json`. No formula is promoted from favorable retrospective cells.", '',
              '| Slice | Model | Windows | Survival | Quantile loss (ppm) |',
              '| --- | --- | ---: | ---: | ---: |']
    for r in result['comparison']:
        if r['group'] == 'all':
            lines.append(f"| {r['split']} | {r['model']} | {r['windows']} | {r['survival']:.2%} | {r['pinball_ppm']:.2f} |")
    lines += ['', 'Final sample-day slice by regime:', '',
              '| Regime | Windows | Global volatility | Fast/slow shape | Regime volatility |',
              '| --- | ---: | ---: | ---: | ---: |']
    for group in ('range', 'pump', 'dump', 'mixed'):
        cells = {r['model']: r for r in result['comparison'] if r['split'] == 'test' and r['group'] == group}
        if cells:
            lines.append(f"| {group} | {cells['volatility']['windows']} | " +
                         ' | '.join(f"{cells[name]['survival']:.2%}" for name in ('volatility', 'adaptive', 'regime_volatility')) + ' |')
    if result['capture_transfer']:
        lines += ['', '## Transfer to the existing native recordings', '',
                  'Models are fitted on the historical sample training days only; native recordings never refit their parameters. Each native source passes its existing frozen-artifact/native hash-chain checks. Score only paths with complete native eligibility and clean pre-entry history.', '',
                  '| Native recording | Model | Windows | Survival |', '| --- | --- | ---: | ---: |']
        for r in result['capture_transfer']:
            if r['group'] == 'all':
                lines.append(f"| {r['run']} | {r['model']} | {r['windows']} | {r['survival']:.2%} |")
    lines += ['', '## Interpretation', '',
              'This supplies directly relevant historical oracle observations for directional-regime research. Sampled first-of-month days have selection bias; they omit many known crashes and cannot establish all-regime coverage or population frequencies. Historical, provider-normalized data and previously inspected native captures remain development evidence, not a fresh prospective experiment.', '',
              'Compare overall and per-regime survival, quantile loss, sample denominators, time gaps and width tails. Good pooled survival does not imply calibrated pump/dump probabilities. The four declared models are fixed-width, global slow-volatility, the 48-shape training search, and four regime-specific volatility scales with fixed shrinkage toward the global scale. More complexity is a hypothesis to test, not a guaranteed improvement.', '',
              'Retain separate source roles. Before live research, freeze the rule and its freshness/history/rounding/width bounds, fix native capture continuity/deadline handling, and evaluate on fresh oracle receipts. Production payout targets are `(1-h)/M`, not one 48% probability for every multiplier. No model here is wired into live quotes.', '',
              'Sources: [provider coverage and free samples](https://docs.tardis.dev/historical-data-details/hyperliquid), [public normalization mapping](https://github.com/tardis-dev/tardis-node/blob/master/src/mappers/hyperliquid.ts), [Hyperliquid oracle](https://hyperliquid.gitbook.io/hyperliquid-docs/hypercore/oracle).']
    return '\n'.join(lines) + '\n'


def research(directory, output, captures=(), q=.48, maximum=50_000):
    if output.exists():
        raise ValueError('output already exists; preserve retained research')
    if not 0 < q < 1 or maximum < 1:
        raise ValueError('invalid target or width limit')
    manifest = json.loads((directory / 'download-manifest.json').read_text())
    files = manifest['files']
    if any(f['status'] != 'downloaded' for f in files):
        raise ValueError('sample downloads incomplete; retain missing days explicitly before changing protocol')
    dates = [f['date'] for f in files]
    if dates != sorted(set(dates)) or dates != manifest['dates']:
        raise ValueError('download dates differ from the predeclared chronological sample list')
    normalizer = directory / 'normalizer-hyperliquid.ts'
    if (file_hash(normalizer) != manifest['normalizer_sha256']
            or 'updateIndexPrice(Number(message.data.ctx.oraclePx))' not in normalizer.read_text()
            or file_hash(directory / 'exchange-metadata.json') != manifest['metadata_sha256']):
        raise ValueError('provider source mapping/metadata differs from the retained download')
    for f in files:
        if file_hash(directory / f['path']) != f['sha256']:
            raise ValueError('historical sample differs from its retained hash')
    code_hashes = {name: file_hash(Path(__file__).with_name(name)) for name in DEPENDENCIES}
    protocol = dict(source_manifest_path=str((directory / 'download-manifest.json').resolve()),
                    source_manifest_sha256=file_hash(directory / 'download-manifest.json'),
                    source_sha256=code_hashes, dates=dates, target_survival=q,
                    maximum_width_ppm=maximum, freshness_ms=FRESHNESS,
                    source_role='Third-party normalized historical oracle research, not paired native receipts',
                    splits='First 60% of sample days train, next 20% validation, last 20% test',
                    source_mapping='oraclePx -> normalized index_price',
                    native_capture_paths=[str(p.resolve()) for p in captures])
    output.mkdir(parents=True)
    (output / 'protocol.json').write_text(json.dumps(protocol, indent=2) + '\n')
    (output / 'source').mkdir()
    for name in DEPENDENCIES:
        shutil.copyfile(Path(__file__).with_name(name), output / 'source' / name)
    rows, samples = [], []
    for f in files:
        start = int(datetime.strptime(f['date'], '%Y-%m-%d').replace(tzinfo=timezone.utc).timestamp() * 1000)
        observed, missing = observations(directory / f['path'], start, start + DAY)
        part = recorded_windows(observed, start, start + DAY)
        for row in part:
            row['date'] = f['date']
        rows.extend(part)
        gaps = [b[0] - a[0] for a, b in zip(observed, observed[1:]) if b[0] - a[0] > FRESHNESS]
        samples.append(dict(date=f['date'], observations=len(observed), missing_index_rows=missing,
                            eligible_windows=sum(r['valid'] for r in part),
                            clean_windows=sum(r['valid'] and r['adaptive_features'] is not None for r in part),
                            gaps_over_8s=len(gaps), longest_gap_ms=max(gaps, default=0),
                            source_sha256=f['sha256']))
    models, metrics, splits = fit_history(rows, dates, q, maximum)
    counts, contexts = {}, []
    for split in ('train', 'validation', 'test'):
        part = [r for r in rows if r['split'] == split and r['valid'] and r['adaptive_features'] is not None]
        groups = episodes(part)
        counts[split] = {name: sum(r['market_regime'] == name for r in part) for name in ('range', 'pump', 'dump', 'mixed')}
        counts[split].update({name + '_clusters': sum(e['regime'] == name for e in groups) for name in ('pump', 'dump')})
        contexts.extend(dict(split=split, **e) for e in groups)
    transfer, native_sources = [], []
    for path in captures:
        run = load_capture_rows(path)
        clean = [r for r in run['rows'] if r['valid'] and r['adaptive_features'] is not None]
        native_sources.append(run['source'])
        for group in ('all', 'range', 'pump', 'dump', 'mixed'):
            part = clean if group == 'all' else [r for r in clean if r['market_regime'] == group]
            if part:
                for name, model in models.items():
                    transfer.append(dict(run=run['name'], group=group, model=name,
                                         **evaluate_research(part, model, q)))
    result = dict(protocol, models=models, comparison=metrics, samples=samples,
                  day_splits=splits, regime_counts=counts, capture_transfer=transfer,
                  native_sources=native_sources, production_approved=False,
                  fresh_prospective_validation=False, live_candidate_promoted=False)
    (output / 'research.json').write_text(json.dumps(result, indent=2) + '\n')
    write_csv(output / 'comparison.csv', metrics, list(metrics[0]))
    if contexts:
        write_csv(output / 'episodes.csv', contexts, list(contexts[0]))
    if transfer:
        write_csv(output / 'capture-transfer.csv', transfer, list(transfer[0]))
    fields = ['date', 'start', 'expiry', 'split', 'valid', 'market_regime', 'entry', 'move']
    fields += ['vol_60_ppm', 'vol_300_ppm', 'net_300_bps', 'directional_strength']
    fields += [name + suffix for name in models for suffix in ('_width_ppm', '_survived')]
    with (output / 'predictions.csv').open('x', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            item = {k: row[k] for k in fields[:8]}
            f = row['adaptive_features']
            if f is not None:
                item.update({k: f[k] for k in fields[8:12]})
                for name, model in models.items():
                    w, _ = predict(row, model_for(row, model))
                    item[name + '_width_ppm'] = w
                    if row['valid']:
                        item[name + '_survived'] = row['move'] < row['entry'] * w // 1_000_000
            writer.writerow(item)
    (output / 'report.md').write_text(make_report(result))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--samples', type=Path, required=True)
    parser.add_argument('--captures', type=Path, nargs='*', default=[])
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--target-survival', type=float, default=.48)
    args = parser.parse_args()
    result = research(args.samples, args.output, args.captures, args.target_survival)
    print(json.dumps(dict(output=str(args.output), regime_counts=result['regime_counts'],
                          models=result['models'], comparison=[r for r in result['comparison'] if r['group'] == 'all'],
                          transfer=[r for r in result['capture_transfer'] if r['group'] == 'all']), indent=2))


if __name__ == '__main__':
    main()
