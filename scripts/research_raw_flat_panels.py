#!/usr/bin/env python3
"""Separate raw historical flat panels, with matched normalized controls."""
import argparse
from datetime import datetime, timezone
import gzip
import json
from pathlib import Path
import shutil

from adaptive_corridor import features, required_width
from capture_dataset import file_hash
from investigate_capture import write_csv
from oracle_activity_features import annotate, load, state
from research_activity_calibration import fit, predict
from research_flat_pause import ENGINE_SPEC, SPECS as PAUSES, apply_pause, diagnostics
from research_frozen_pricing import (DEPENDENCIES as PRICING_DEPENDENCIES, SPECS,
                                     fit_overlay, reprice)
from research_oracle_history import add_regimes, observations, recorded_windows
from research_market_regimes import price_units

DEPENDENCIES = ('research_raw_flat_panels.py', 'fetch_flat_samples.py') + PRICING_DEPENDENCIES


def parse_raw(files, root):
    observed, markers, waiting, previous = [], [], [], None
    for item in files:
        path = root / item['path']
        if item['status'] != 'downloaded' or file_hash(path) != item['sha256']:
            raise ValueError('raw minute missing or changed')
        for line in gzip.decompress(path.read_bytes()).decode().splitlines():
            if not line:
                waiting.append(dict(minute_at=item['at_ms'], previous_at=previous))
                continue
            timestamp, payload = line.split(' ', 1)
            # Provider timestamps have seven fractional digits; Python 3.9's
            # fromisoformat rejects them. Floor exactly to integer milliseconds.
            if not timestamp.endswith('Z'):
                raise ValueError('UTC raw timestamp required')
            whole, fraction = timestamp[:-1].split('.')
            if not fraction.isdigit():
                raise ValueError('invalid raw timestamp fraction')
            seconds = datetime.strptime(whole, '%Y-%m-%dT%H:%M:%S').replace(tzinfo=timezone.utc)
            at = int(seconds.timestamp()) * 1000 + int((fraction + '000')[:3])
            if not item['at_ms'] <= at < item['at_ms'] + 60_000 or (previous is not None and at < previous):
                raise ValueError('raw timestamp outside minute or regressing')
            message = json.loads(payload)
            if message['channel'] != 'activeAssetCtx' or message['data']['coin'] != 'BTC':
                raise ValueError('wrong raw channel or asset')
            price = price_units(message['data']['ctx']['oraclePx'])
            if price <= 0:
                raise ValueError('nonpositive raw oracle')
            for marker in waiting:
                markers.append(dict(marker, known_at=at))
            waiting.clear()
            observed.append((at, price))
            previous = at
    for marker in waiting:
        markers.append(dict(marker, known_at=files[-1]['at_ms'] + 59_999))
    return observed, markers


def prepare_rows(observed, panel, markers=()):
    rows = recorded_windows(observed, panel['fetch_start'], panel['fetch_end'])
    # Untimestamped disconnect markers become known at the next timestamped raw
    # message. Censor that outcome window; the usual >8s gap screen also applies.
    # Do not retroactively remove pre-entry history using a future disconnect.
    for marker in markers:
        for r in rows:
            if r['start'] <= marker['known_at'] < r['expiry']:
                r['valid'] = False
    if markers:
        features(rows, observed, panel['fetch_start'])
        add_regimes(rows)
    annotate(rows, observed)
    for r in rows:
        r.update(period=panel['day'], split='raw_diagnostic', activity_state=state(r))
    return rows


def flat_stretches(observed, markers=()):
    """Conservative observed equal-price spans, split by >8s gaps/disconnects."""
    cuts = sorted(m['known_at'] for m in markers)
    runs, current, previous, cut_index = [], None, None, 0
    for at, price in observed:
        disconnected = False
        while cut_index < len(cuts) and cuts[cut_index] <= at:
            disconnected = True
            cut_index += 1
        if current is None or price != current['price'] or at - previous > 8000 or disconnected:
            if current and current['last'] - current['start'] >= 30_000:
                runs.append(current)
            current = dict(start=at, last=at, price=price, messages=0)
        current['last'] = at
        current['messages'] += 1
        previous = at
    if current and current['last'] - current['start'] >= 30_000:
        runs.append(current)
    return [dict(r, duration_ms=r['last'] - r['start']) for r in runs]


def cell(values):
    result = diagnostics(values)
    full = [p for p in values if p['shadow_survived'] is not None]
    kept = [p for p in full if not p['paused']]
    result.update(minimum_width_survival=sum(required_width(p['row']) <= 1 for p in full) / len(full) if full else None,
                  offered_minimum_width_survival=sum(required_width(p['row']) <= 1 for p in kept) / len(kept) if kept else None)
    return result


def run(raw, dataset, pricing, output):
    if output.exists():
        raise ValueError('output exists; retain prior diagnostics')
    original, metadata = load(dataset)
    frozen = json.loads((pricing / 'research.json').read_text())
    for name, digest in frozen['source_sha256'].items():
        if file_hash(pricing / 'source' / name) != digest or file_hash(Path(__file__).with_name(name)) != digest:
            raise ValueError('pricing specification changed after freezing')
    protocol_raw = json.loads((raw / 'download-protocol.json').read_text())
    manifest = json.loads((raw / 'download-manifest.json').read_text())
    digest = file_hash(dataset / 'dataset.json')
    if digest != frozen['dataset_sha256'] or digest != protocol_raw['dataset_sha256']:
        raise ValueError('raw selection or pricing used a different original dataset')
    if file_hash(raw / 'fetch-source.py') != protocol_raw['source_sha256']:
        raise ValueError('raw fetch source snapshot changed')
    if not manifest['complete'] or manifest['protocol_sha256'] != file_hash(raw / 'download-protocol.json'):
        raise ValueError('raw requests incomplete or protocol changed')
    if [v['url'] for v in sorted(manifest['files'], key=lambda r: r['path'])] != [v['url'] for v in sorted(protocol_raw['requests'], key=lambda r: r['path'])]:
        raise ValueError('raw request list differs from protocol')
    protocol = dict(raw=str(raw.resolve()), raw_manifest_sha256=file_hash(raw / 'download-manifest.json'),
                    raw_protocol_sha256=file_hash(raw / 'download-protocol.json'), dataset=str(dataset.resolve()),
                    dataset_sha256=file_hash(dataset / 'dataset.json'), pricing=str(pricing.resolve()),
                    pricing_sha256=file_hash(pricing / 'research.json'), selected_pricing_before_raw=frozen['selected_spec'],
                    source_sha256={n: file_hash(Path(__file__).with_name(n)) for n in DEPENDENCIES},
                    coefficient_rule='Fit only earlier original training days; no raw panel refits or model selection',
                    panel_reset='Five-minute left history, then all 480 decisions; no full-day hidden warmup',
                    raw_markers='Censor window containing first timestamped message following disconnect marker; >8s gap screen retained',
                    fresh_independent_holdout=False, capture_started=False, live_candidate_promoted=False)
    output.mkdir(parents=True)
    (output / 'protocol.json').write_text(json.dumps(protocol, indent=2) + '\n')
    (output / 'source').mkdir()
    for name in DEPENDENCIES:
        shutil.copyfile(Path(__file__).with_name(name), output / 'source' / name)
    upstream = json.loads(Path(metadata['history']).joinpath('research.json').read_text())
    archive = Path(upstream['source_manifest_path']).parent
    normalized = json.loads((archive / 'download-manifest.json').read_text())
    results, panels, stretches, models, saved_rows = [], [], [], {}, []
    masks = [s for s in PAUSES if s['name'] in ('no_pause', 'existing', 'frozen_floor_53')]
    for panel in protocol_raw['panels']:
        day = panel['day']
        messages, markers = parse_raw([f for f in manifest['files'] if f['day'] == day], raw)
        day_start = panel['start'] // 86_400_000 * 86_400_000
        source_file = next(f for f in normalized['files'] if f['date'] == day)
        norm_all, _ = observations(archive / source_file['path'], day_start, day_start + 86_400_000)
        norm = [(at, price) for at, price in norm_all if panel['fetch_start'] <= at < panel['fetch_end']]
        samples = dict(raw=prepare_rows(messages, panel, markers), normalized=prepare_rows(norm, panel))
        raw_prices = dict(messages)
        overlap = [(at, price) for at, price in norm if at in raw_prices]
        mismatches = sum(raw_prices[at] != price for at, price in overlap)
        runs = flat_stretches(messages, markers)
        stretches.extend(dict(period=day, **r) for r in runs)
        panels.append(dict(panel, raw_messages=len(messages), normalized_messages=len(norm),
                           markers=markers, same_timestamp_comparisons=len(overlap), oracle_mismatches=mismatches,
                           flat_spans_30s=len(runs), flat_spans_60s=sum(r['duration_ms'] >= 60_000 for r in runs),
                           maximum_observed_flat_ms=max((r['duration_ms'] for r in runs), default=0)))
        train = [r for r in original if r['period'] in metadata['dates'][:14] and r['period'] < day]
        engine = fit(train, ENGINE_SPEC)
        train_predictions = predict(train, engine)
        models[day] = dict(training_periods=sorted({r['period'] for r in train}), engine=engine, overlays={})
        for pause in masks:
            train_masked = apply_pause(train_predictions, pause)
            overlays = {s['name']: fit_overlay(train_masked, s) for s in SPECS}
            models[day]['overlays'][pause['name']] = overlays
            for role, rows in samples.items():
                baseline = apply_pause(predict(rows, engine), pause)
                for name, model in overlays.items():
                    values = [p for p in reprice(baseline, model) if panel['start'] <= p['row']['start'] < panel['end']]
                    for activity in ('all', 'frozen'):
                        part = values if activity == 'all' else [p for p in values if p['row']['activity_state'] == activity]
                        results.append(dict(period=day, source=role, pause=pause['name'], model=name,
                                            activity=activity, **cell(part)))
        for role, rows in samples.items():
            saved_rows.extend(dict(source=role, **r) for r in rows)
    with gzip.open(output / 'rows.jsonl.gz', 'wt') as stream:
        for row in saved_rows:
            stream.write(json.dumps(row, separators=(',', ':')) + '\n')
    result = dict(protocol, panels=panels, models=models, summary=results,
                  rows_sha256=file_hash(output / 'rows.jsonl.gz'), flat_stretches=stretches)
    (output / 'research.json').write_text(json.dumps(result, indent=2) + '\n')
    write_csv(output / 'summary.csv', results, list(results[0]))
    if stretches:
        write_csv(output / 'flat-stretches.csv', stretches, list(stretches[0]))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--raw', type=Path, required=True)
    parser.add_argument('--dataset', type=Path, required=True)
    parser.add_argument('--pricing', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = run(args.raw, args.dataset, args.pricing, args.output)
    print(json.dumps(dict(panels=result['panels'], baseline=[r for r in result['summary']
                            if r['model'] == 'baseline' and r['pause'] in ('no_pause', 'frozen_floor_53')]), indent=2))


if __name__ == '__main__':
    main()
