#!/usr/bin/env python3
"""Compare full-day state with clean restarts, without selecting another rule."""
import argparse
import gzip
import json
from pathlib import Path
import shutil

from capture_dataset import file_hash
from investigate_capture import write_csv
from research_activity_calibration import predict
from research_flat_pause import SPECS as PAUSES, apply_pause
from research_frozen_pricing import reprice
from research_raw_flat_panels import cell, parse_raw, prepare_rows


def run(research, output):
    if output.exists():
        raise ValueError('output exists; retain prior audit')
    prior = json.loads((research / 'research.json').read_text())
    for name, digest in prior['source_sha256'].items():
        if file_hash(research / 'source' / name) != digest or file_hash(Path(__file__).with_name(name)) != digest:
            raise ValueError('raw research code differs from retained source')
    raw = Path(prior['raw'])
    if file_hash(raw / 'download-manifest.json') != prior['raw_manifest_sha256']:
        raise ValueError('raw manifest changed')
    if file_hash(research / 'rows.jsonl.gz') != prior['rows_sha256']:
        raise ValueError('raw research rows changed')
    if len(prior['panels']) != 1:
        raise ValueError('one complete day required')
    panel = prior['panels'][0]
    origin, day = panel['start'], panel['day']
    if origin % 86_400_000 or panel['end'] - origin != 86_400_000:
        raise ValueError('complete UTC day required')
    manifest = json.loads((raw / 'download-manifest.json').read_text())
    observed, markers = parse_raw(manifest['files'], raw)
    with gzip.open(research / 'rows.jsonl.gz', 'rt') as stream:
        full_rows = [r for line in stream for r in [json.loads(line)] if r['source'] == 'raw']
    protocol = dict(research=str(research.resolve()), research_sha256=file_hash(research / 'research.json'),
                    source_sha256=file_hash(Path(__file__)),
                    source_rule='Same fixed prior-day coefficients; six 4h blocks, three 8h blocks and original 06–10 diagnostic; no rule selection',
                    restart_rule='Clear all outcome/correction pools; reconstruct five-minute raw feature history before each block, retaining missing/gap exclusions',
                    capture_started=False, live_candidate_promoted=False)
    output.mkdir(parents=True)
    (output / 'protocol.json').write_text(json.dumps(protocol, indent=2) + '\n')
    shutil.copyfile(Path(__file__), output / 'audit-source.py')
    models = ('baseline', 'hurdle_all_120', 'offered_frozen_60_fast')
    masks = [s for s in PAUSES if s['name'] in ('existing', 'frozen_floor_53')]
    intervals = [(origin + h * 3_600_000, origin + (h + 4) * 3_600_000) for h in (0, 4, 8, 12, 16, 20, 6)]
    intervals += [(origin + h * 3_600_000, origin + (h + 8) * 3_600_000) for h in (0, 8, 16)]
    results = []
    engine = prior['models'][day]['engine']
    for pause in masks:
        base = apply_pause(predict(full_rows, engine), pause)
        for name in models:
            model = prior['models'][day]['overlays'][pause['name']][name]
            continuous = reprice(base, model)
            reference = next(r for r in prior['summary'] if r['source'] == 'raw' and r['pause'] == pause['name']
                             and r['model'] == name and r['activity'] == 'all')
            measured = cell(continuous)
            for key in ('windows', 'survived', 'eligible_outcomes', 'paused_eligible_outcomes'):
                if measured[key] != reference[key]:
                    raise ValueError('full-day replay differs from retained result')
            for begin, end in intervals:
                left = max(origin, begin - 300_000)
                scoped = dict(day=day, fetch_start=left, fetch_end=end)
                rows = prepare_rows([(at, price) for at, price in observed if left <= at < end], scoped,
                                    [m for m in markers if left <= m['known_at'] < end])
                restarted = reprice(apply_pause(predict(rows, engine), pause), model)
                for mode, values in (('continuous', continuous), ('restart', restarted)):
                    values = [p for p in values if begin <= p['row']['start'] < end]
                    for activity in ('all', 'frozen'):
                        part = values if activity == 'all' else [p for p in values if p['row']['activity_state'] == activity]
                        results.append(dict(period=day, begin=begin, end=end, hour=(begin - origin) // 3_600_000,
                                            duration_hours=(end - begin) // 3_600_000,
                                            mode=mode, pause=pause['name'], model=name, activity=activity, **cell(part)))
    result = dict(protocol, full_day_parity_verified=True, summary=results)
    (output / 'audit.json').write_text(json.dumps(result, indent=2) + '\n')
    write_csv(output / 'blocks.csv', results, list(results[0]))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--research', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = run(args.research, args.output)
    print(json.dumps([r for r in result['summary'] if r['model'] == 'hurdle_all_120'
                      and r['pause'] == 'frozen_floor_53'], indent=2))


if __name__ == '__main__':
    main()
