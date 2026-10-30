#!/usr/bin/env python3
"""Chronological adaptive-corridor development on public exchange-price proxies.

Uses verified Binance one-second OHLC archives. Never manufactures oracle
receipts or mixes exchange envelopes with Hyperliquid prospective validation.
"""
import argparse
from collections import deque
import csv
from datetime import datetime, timezone
from decimal import Decimal
import io
import json
import math
from pathlib import Path
import shutil
import zipfile

from adaptive_corridor import evaluate, fit_models, fit_scale, predict
from capture_dataset import file_hash
from investigate_capture import write_csv

SECOND = 1000
WINDOW = 30_000
LOOKBACK = 300_000
REGIMES = ('range', 'pump', 'dump', 'mixed')
DEPENDENCIES = ('research_market_regimes.py', 'adaptive_corridor.py',
                'capture_dataset.py', 'investigate_capture.py',
                'analyze_capture.py', 'prospective_capture.py')
SOURCES = dict(
    binance='https://github.com/binance/binance-public-data',
    hyperliquid_history='https://hyperliquid.gitbook.io/hyperliquid-docs/historical-data',
    hyperliquid_oracle='https://hyperliquid.gitbook.io/hyperliquid-docs/hypercore/oracle')


def utc(at):
    return datetime.fromtimestamp(at / 1000, timezone.utc).isoformat()


def milliseconds(value):
    value = int(value)
    # Binance spot archive timestamps changed from milliseconds to microseconds
    # in January 2025. Require exact millisecond candle-open representation.
    return value // 1000 if value >= 100_000_000_000_000 else value


def price_units(text):
    value = Decimal(text) * 1_000_000
    if not value.is_finite() or value <= 0 or value != value.to_integral_value():
        raise ValueError('positive price exactly representable in six decimal places required')
    return int(value)


def parse_candle(values):
    if len(values) != 12:
        raise ValueError('expected twelve Binance spot kline columns')
    raw_open = int(values[0])
    if raw_open >= 100_000_000_000_000 and raw_open % 1_000_000:
        raise ValueError('microsecond candle open must align to an exact second')
    at, close_at = milliseconds(values[0]), milliseconds(values[6])
    if at % SECOND or close_at != at + 999:
        raise ValueError('expected complete aligned one-second candle')
    o, h, low, close = (price_units(v) for v in values[1:5])
    if not low <= min(o, close) <= max(o, close) <= h:
        raise ValueError('invalid OHLC envelope')
    return dict(at=at, open=o, high=h, low=low, close=close)


def verify_archive(archive):
    manifest_path = archive.parent / 'download-manifest.json'
    manifest = json.loads(manifest_path.read_text())
    checksum_path = archive.with_name(archive.name + '.CHECKSUM')
    checksum = checksum_path.read_text().split()
    actual = file_hash(archive)
    if (len(checksum) != 2 or checksum[1].lstrip('*') != archive.name
            or actual != checksum[0] or actual != manifest['archive_sha256']):
        raise ValueError('archive provenance/checksum mismatch')
    if (manifest['provider'], manifest['market'], manifest['symbol'], manifest['interval']) != ('Binance', 'spot', 'BTCUSDT', '1s'):
        raise ValueError('only explicitly labeled Binance BTCUSDT spot one-second proxies supported')
    return dict(manifest, local_archive=str(archive.resolve()),
                download_manifest_sha256=file_hash(manifest_path),
                checksum_file_sha256=file_hash(checksum_path))


def candles(archive):
    with zipfile.ZipFile(archive) as bundle:
        names = bundle.namelist()
        expected = archive.name[:-4] + '.csv'
        if names != [expected]:
            raise ValueError('archive must contain exactly its expected CSV; no extraction performed')
        with bundle.open(expected) as raw:
            for values in csv.reader(io.TextIOWrapper(raw, encoding='utf-8')):
                yield parse_candle(values)


def pre_entry_features(history, at):
    if len(history) < 301 or history[-1]['at'] != at - SECOND or history[0]['at'] != at - 301 * SECOND:
        return None
    prices = [c['close'] for c in history]
    steps = [math.log(b / a) * 1_000_000 for a, b in zip(prices, prices[1:])]
    slow = math.sqrt(sum(v * v for v in steps))
    fast = math.sqrt(sum(v * v for v in steps[-60:]))
    net = math.log(prices[-1] / prices[0]) * 1_000_000
    net_fast = math.log(prices[-1] / prices[-61]) * 1_000_000
    path = sum(abs(v) for v in steps)
    return dict(vol_60_ppm=fast * math.sqrt(30 / 60),
                vol_300_ppm=slow * math.sqrt(30 / 300),
                trend_60_ppm=abs(net_fast) * (30 / 60),
                jump_60_ppm=max(abs(v) for v in steps[-60:]),
                net_300_bps=net / 100, vol_300_unscaled_bps=slow / 100,
                efficiency_300=abs(net) / path if path else 0,
                directional_strength=abs(net) / slow if slow else 0)


def regime(features):
    if features is None:
        return 'missing_history'
    net = features['net_300_bps']
    strength = features['directional_strength']
    if abs(net) >= 20 and strength >= 1.5:
        return 'pump' if net > 0 else 'dump'
    if abs(net) <= 5 and strength <= .5:
        return 'range'
    return 'mixed'


def windows(stream):
    """Use prior close as entry and all future high/low extrema as outcome.

    At the first second of a 30s bucket, snapshot prior history before admitting
    that candle. A missing second invalidates its outcome bucket and resets the
    history requirement. No candle open/close is substituted for an intrabar high.
    """
    history = deque(maxlen=301)
    current = None
    previous_at = None

    def finished(row):
        row['valid'] = row['bars'] == 30 and row['contiguous'] and row['entry'] is not None
        return row

    for candle in stream:
        at = candle['at']
        if previous_at is not None and at <= previous_at:
            raise ValueError('duplicate or unordered candle timestamp')
        start = at // WINDOW * WINDOW
        if current is not None and start != current['start']:
            yield finished(current)
            missing = current['expiry']
            while missing < start:
                yield dict(start=missing, expiry=missing + WINDOW, entry=None, move=0,
                           valid=False, bars=0, contiguous=False, adaptive_features=None,
                           market_regime='missing_history')
                missing += WINDOW
            current = None
        consecutive = previous_at is not None and at == previous_at + SECOND
        if not consecutive:
            history.clear()
        if current is None:
            f = pre_entry_features(history, start) if at == start else None
            current = dict(start=start, expiry=start + WINDOW,
                           entry=history[-1]['close'] if history and consecutive else None,
                           move=0, bars=0, contiguous=at == start,
                           adaptive_features=f, market_regime=regime(f))
        current['bars'] += 1
        current['contiguous'] = current['contiguous'] and (consecutive or current['bars'] == 1)
        if current['entry'] is not None:
            current['move'] = max(current['move'], abs(candle['high'] - current['entry']),
                                  abs(candle['low'] - current['entry']))
        history.append(candle)
        previous_at = at
    if current is not None:
        yield finished(current)


def episodes(rows):
    """Merge overlapping five-minute contexts per direction, not independent n."""
    result = []
    for direction in ('pump', 'dump'):
        current = None
        for row in rows:
            if row['market_regime'] != direction:
                continue
            begin, end = row['start'] - LOOKBACK, row['expiry']
            if current is not None and begin <= current['end_ms']:
                current['end_ms'] = end
                current['windows'] += 1
            else:
                current = dict(regime=direction, start_ms=begin, end_ms=end, windows=1)
                result.append(current)
    return sorted(result, key=lambda r: r['start_ms'])


def partition(rows, origin):
    # Predeclared calendar blocks: days 1–18, 19–24, then 25–month end.
    train_end, validation_end = origin + 18 * 86_400_000, origin + 24 * 86_400_000
    for row in rows:
        row['split'] = ('train' if row['expiry'] <= train_end else
                        'validation' if row['expiry'] <= validation_end else 'test')
    return dict(training_end_ms=train_end, validation_end_ms=validation_end)


def fit_research_models(train, q, maximum):
    models = fit_models(train, q, maximum)
    global_model = models['volatility']
    groups = {}
    for name in REGIMES:
        part = [r for r in train if r['market_regime'] == name]
        model = global_model
        if len(part) >= 200:
            model = fit_scale(part, dict(global_model), q)
        weight = len(part) / (len(part) + 200) if len(part) >= 200 else 0
        groups[name] = dict(model, scale=weight * model['scale'] + (1 - weight) * global_model['scale'],
                            training_windows=len(part), shrinkage_weight=weight)
    models['regime_volatility'] = dict(family='regime_volatility', fallback=global_model,
                                     groups=groups, shrinkage_pseudocount=200,
                                     minimum_group_training_windows=200)
    return models


def model_for(row, model):
    if model['family'] == 'regime_volatility':
        return model['groups'].get(row['market_regime'], model['fallback'])
    return model


def evaluate_research(rows, model, q):
    # Score each regime with its frozen model, then aggregate weighted metrics.
    parts = []
    for name in REGIMES:
        part = [r for r in rows if r['market_regime'] == name]
        if part:
            parts.append(evaluate(part, model_for(part[0], model), q))
    n = sum(p['windows'] for p in parts)
    wins = sum(p['survived'] for p in parts)
    return dict(windows=n, survived=wins, survival=wins / n if n else None,
                error_pp=100 * (wins / n - q) if n else None,
                pinball_ppm=sum(p['pinball_ppm'] * p['windows'] for p in parts) / n if n else None,
                mean_width_ppm=sum(p['mean_width_ppm'] * p['windows'] for p in parts) / n if n else None,
                minimum_width_ppm=min((p['minimum_width_ppm'] for p in parts), default=None),
                maximum_width_ppm=max((p['maximum_width_ppm'] for p in parts), default=None),
                capped_windows=sum(p['capped_windows'] for p in parts))


def compare(rows, models, q):
    output = []
    for split in ('train', 'validation', 'test'):
        part = [r for r in rows if r['split'] == split and r['valid'] and r['adaptive_features'] is not None]
        for group in ('all',) + REGIMES:
            group_rows = part if group == 'all' else [r for r in part if r['market_regime'] == group]
            if not group_rows:
                continue
            for name, model in models.items():
                output.append(dict(split=split, group=group, model=name,
                                   **evaluate_research(group_rows, model, q)))
    return output


def make_report(result):
    lines = ['# Historical market-regime development', '',
             '**Exchange-price proxy research. No Hyperliquid oracle validation, live policy update or new capture.**', '',
             f"Source: complete {result['source']['period']} Binance BTCUSDT spot one-second archive, SHA-256 `{result['source']['archive_sha256']}`.", '',
             'The full month was deliberately selected to add stressful directional conditions, not as a representative or untouched market sample. Candles were validated and the archive checked against its published SHA-256 checksum. No missing second was interpolated.', '',
             f"Read **{result['candles']}** one-second candles; **{result['windows']}** 30-second grid windows, **{result['healthy_windows']}** complete outcome windows and **{result['clean_history_windows']}** with both complete outcomes and five-minute pre-entry history.", '',
             'A proxy entry uses the last completed one-second close. Each outcome uses the full high/low envelope of all 30 subsequent one-second candles, including wicks. Features use only completed candles before entry. These exchange trade extrema are not the three-second, weighted-median Hyperliquid oracle process, and have no paired receiver-health evidence.', '',
             '## Directional episodes', '',
             'A pump/dump label at entry requires an absolute preceding five-minute return of at least 20 bps and absolute return / square-root realized variation of at least 1.5; sign chooses pump or dump. Range requires absolute return at most 5 bps and this ratio at most 0.5. Everything else is mixed. These fixed exploratory definitions differ from the earlier five-minute directional-efficiency ≥0.6 taxonomy; their counts must not be presented as a direct increase under an identical label.', '',
             '| Split | Pump windows / context clusters | Dump windows / context clusters | Range windows |',
             '| --- | ---: | ---: | ---: |']
    for split in ('train', 'validation', 'test'):
        count = result['regime_counts'][split]
        lines.append(f"| {split} | {count['pump']} / {count['pump_clusters']} | {count['dump']} / {count['dump_clusters']} | {count['range']} |")
    lines += ['',
              'Clusters merge overlapping five-minute lookback plus 30-second outcome intervals within each direction. They are descriptive groups, not statistically independent episodes. Opposite-direction contexts and boundary contexts can overlap. `episodes.csv` retains their spans; `comparison.csv` retains all denominators.', '',
              '## Frozen chronological replay', '',
              f"Target survival **{result['target_survival']:.2%}**, continuing the legacy reference experiment. Train on days 1–18 only, inspect validation on days 19–24 and final diagnostics on days 25–month end. All coefficients and the 48-combination shape search use training only; no model is reselected on later scores. Later slices remain retrospective proxy development, not a prospective gate.", '',
              'Fixed: constant trained width. Volatility: one global trained scale times past-five-minute variation. Shape: trained mixture of fast/slow volatility with nonnegative recent directional-move/jump terms. Regime: separate scales for range, pump, dump and mixed, shrunk toward the global volatility scale with 200 pseudo-observations; groups below 200 training windows use the global scale.', '',
              '| Slice | Model | Windows | Survival | Error versus target | Quantile loss (ppm) |',
              '| --- | --- | ---: | ---: | ---: | ---: |']
    for row in result['comparison']:
        if row['group'] == 'all':
            lines.append(f"| {row['split']} | {row['model']} | {row['windows']} | {row['survival']:.2%} | {row['error_pp']:+.2f} pp | {row['pinball_ppm']:.2f} |")
    lines += ['', 'Final-slice per-regime comparison:', '',
              '| Regime | Windows | Volatility survival | Regime-model survival |',
              '| --- | ---: | ---: | ---: |']
    for group in REGIMES:
        cells = {r['model']: r for r in result['comparison'] if r['split'] == 'test' and r['group'] == group}
        if cells:
            lines.append(f"| {group} | {cells['volatility']['windows']} | {cells['volatility']['survival']:.2%} | {cells['regime_volatility']['survival']:.2%} |")
    shape_model = result['models']['adaptive']
    lines += ['',
              f"Shape fit: fast weight {shape_model['fast_weight']:g}, trend weight {shape_model['trend_weight']:g}, jump weight {shape_model['jump_weight']:g}, scale {shape_model['scale']:.8g}.", '',
              'Regime formula: `width_ppm = clamp(ceil(scale[pre_entry_regime] * max(1, vol300_ppm)), 1, maximum_width_ppm)`; exact fitted scales are in `research.json`. The width for a given entry is fixed throughout its 30 seconds. No coefficients learn online.', '',
              '## Limits and next evidence', '',
              'This adds real historical directional contexts for testing ideas. It cannot establish oracle barrier probabilities, recover capture gaps, validate all payout multipliers, or prove that future pumps are identifiable before their first move. One-second trade high/low paths and oracle receipt paths must retain separate provenance and calibration.', '',
              'The official Hyperliquid archive documents asset contexts and requester-paid access. Anonymous access to a sample object returned 403 in this investigation. No billed archive access was attempted. Archived schema, cadence and completeness still need inspection before treating it as suitable for 30-second first-passage analysis. The info API candle endpoint starts at one minute and is insufficient to reconstruct those paths.', '',
              'Keep collecting complete oracle observations for independent evaluation. Use the proxy findings to propose, then freeze, a small research rule; assess it on the oracle recordings separately and on fresh reliable captures. Preserve chronological blocks and check direction-specific error and clustered uncertainty. The legacy 48% target must be replaced by multiplier-specific `(1-h)/M` targets for the payout product.', '',
              'Sources: ' + ', '.join(f'[{name}]({url})' for name, url in SOURCES.items()) + '.']
    return '\n'.join(lines) + '\n'


def research(archive, output, q=.48, maximum=50_000):
    if output.exists():
        raise ValueError('output already exists; never overwrite retained research')
    if not 0 < q < 1 or maximum < 1:
        raise ValueError('invalid target or width bound')
    source = verify_archive(archive)
    origin = int(datetime.strptime(source['period'], '%Y-%m').replace(tzinfo=timezone.utc).timestamp() * 1000)
    output.mkdir(parents=True)
    code_hashes = {name: file_hash(Path(__file__).with_name(name)) for name in DEPENDENCIES}
    protocol = dict(source=source, source_sha256=code_hashes, target_survival=q,
                    maximum_width_ppm=maximum, splits='days 1–18 train, 19–24 validation, 25–end test',
                    regime_definition=dict(directional_minimum_abs_return_bps=20, directional_minimum_strength=1.5,
                                           range_maximum_abs_return_bps=5, range_maximum_strength=.5),
                    training_only=True, no_live_candidate_promotion=True,
                    data_role='Retrospective exchange-price proxy development; never oracle receipts')
    (output / 'protocol.json').write_text(json.dumps(protocol, indent=2) + '\n')
    (output / 'source').mkdir()
    for name in DEPENDENCIES:
        shutil.copyfile(Path(__file__).with_name(name), output / 'source' / name)
    rows = list(windows(candles(archive)))
    if not rows or rows[0]['start'] != origin:
        raise ValueError('archive does not start at the declared calendar month boundary')
    year, month = (int(v) for v in source['period'].split('-'))
    next_month = datetime(year + (month == 12), month % 12 + 1, 1, tzinfo=timezone.utc)
    if rows[-1]['expiry'] != int(next_month.timestamp() * 1000) or rows[-1]['bars'] != 30:
        raise ValueError('archive does not end at the declared calendar month boundary')
    boundaries = partition(rows, origin)
    clean = [r for r in rows if r['valid'] and r['adaptive_features'] is not None]
    models = fit_research_models([r for r in clean if r['split'] == 'train'], q, maximum)
    metrics = compare(clean, models, q)
    counts = {}
    all_episodes = []
    for split in ('train', 'validation', 'test'):
        part = [r for r in clean if r['split'] == split]
        groups = episodes(part)
        counts[split] = {name: sum(r['market_regime'] == name for r in part) for name in REGIMES}
        counts[split].update({name + '_clusters': sum(e['regime'] == name for e in groups) for name in ('pump', 'dump')})
        all_episodes.extend(dict(split=split, start_utc=utc(e['start_ms']), end_utc=utc(e['end_ms']), **e) for e in groups)
    result = dict(protocol, models=models, comparison=metrics, regime_counts=counts,
                  windows=len(rows), candles=sum(r['bars'] for r in rows),
                  healthy_windows=sum(r['valid'] for r in rows), clean_history_windows=len(clean),
                  fresh_prospective_validation=False, production_approved=False, **boundaries)
    if file_hash(archive) != source['archive_sha256']:
        raise ValueError('source archive changed during research')
    (output / 'research.json').write_text(json.dumps(result, indent=2) + '\n')
    write_csv(output / 'comparison.csv', metrics, list(metrics[0]))
    if all_episodes:
        write_csv(output / 'episodes.csv', all_episodes, list(all_episodes[0]))
    with (output / 'predictions.csv').open('x', newline='') as stream:
        fields = ['start_ms', 'split', 'healthy', 'clean_history', 'regime', 'entry', 'move']
        fields += ['vol_300_ppm', 'net_300_bps', 'directional_strength']
        fields += [name + suffix for name in models for suffix in ('_width_ppm', '_survived')]
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            f = row['adaptive_features']
            prediction = dict(start_ms=row['start'], split=row['split'], healthy=row['valid'],
                              clean_history=f is not None, regime=row['market_regime'],
                              entry=row['entry'], move=row['move'])
            if f is not None:
                prediction.update({k: f[k] for k in ('vol_300_ppm', 'net_300_bps', 'directional_strength')})
                for name, model in models.items():
                    w, _ = predict(row, model_for(row, model))
                    prediction[name + '_width_ppm'] = w
                    if row['valid']:
                        prediction[name + '_survived'] = row['move'] < row['entry'] * w // 1_000_000
            writer.writerow(prediction)
    (output / 'report.md').write_text(make_report(result))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--target-survival', type=float, default=.48)
    parser.add_argument('--maximum-width-ppm', type=int, default=50_000)
    args = parser.parse_args()
    result = research(args.archive, args.output, args.target_survival, args.maximum_width_ppm)
    print(json.dumps(dict(output=str(args.output), regime_counts=result['regime_counts'],
                          models=result['models'], comparison=[r for r in result['comparison'] if r['group'] == 'all']), indent=2))


if __name__ == '__main__':
    main()
