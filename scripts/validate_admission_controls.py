#!/usr/bin/env python3
"""Apply the already-pinned admission alternatives to additional raw 8h tests."""
import argparse
from datetime import datetime, timezone
import gzip
import json
from pathlib import Path
import shutil

from capture_dataset import file_hash
from investigate_capture import write_csv
from oracle_activity_features import load
from research_activity_calibration import fit, predict
from research_flat_pause import ENGINE_SPEC, apply_pause
from research_frozen_pricing import PAUSE, fit_overlay
from research_raw_flat_panels import cell, parse_raw, prepare_rows
from research_oracle_history import observations
from research_startup_admission import (DEPENDENCIES as ADMISSION_DEPENDENCIES,
    day_sessions, measures, priced, summarize, verify_code)
from startup_admission import SPECS, admit

DEPENDENCIES = ('validate_admission_controls.py', 'fetch_admission_controls.py') + ADMISSION_DEPENDENCIES
DAY, HOUR = 86_400_000, 3_600_000


def joint_checks(cases):
    output = []
    for rule in SPECS:
        selected = [r for r in cases if r['policy'] == rule['name'] and r['mode'] == 'restart']
        all_cases = [r for r in selected if r['activity'] == 'all' and r['eligible_outcomes']]
        pairs = []
        for a in all_cases:
            f = next(r for r in selected if r['case_id'] == a['case_id'] and r['activity'] == 'frozen')
            pairs.append((a, f))
        output.append(dict(policy=rule['name'], cases=len(pairs),
                           overall_pass=sum(a['windows'] >= 20 and abs(a['error_pp']) <= 5 for a, _ in pairs),
                           frozen_pass=sum(f['windows'] >= 20 and abs(f['error_pp']) <= 5 for _, f in pairs),
                           both_pass=sum(a['windows'] >= 20 and f['windows'] >= 20 and
                                         abs(a['error_pp']) <= 5 and abs(f['error_pp']) <= 5 for a, f in pairs),
                           minimum_overall_availability=min((a['eligible_quote_fraction'] for a, _ in pairs), default=None),
                           all_cases_pass=False if not pairs else all(a['windows'] >= 20 and f['windows'] >= 20 and
                                         abs(a['error_pp']) <= 5 and abs(f['error_pp']) <= 5 for a, f in pairs)))
    return output


def run(raw, admission, output):
    if output.exists():
        raise ValueError('output exists; retain diagnostics')
    parent = json.loads((admission / 'research.json').read_text())
    verify_code(admission, parent)
    protocol_raw = json.loads((raw / 'download-protocol.json').read_text())
    manifest = json.loads((raw / 'download-manifest.json').read_text())
    if protocol_raw['admission_sha256'] != file_hash(admission / 'research.json'):
        raise ValueError('policies differ from declaration before raw download')
    if protocol_raw['admission_source_sha256'] != file_hash(Path(__file__).with_name('startup_admission.py')):
        raise ValueError('admission rules changed after download declaration')
    if (not manifest['complete'] or manifest['protocol_sha256'] != file_hash(raw / 'download-protocol.json')
            or file_hash(raw / 'fetch-source.py') != protocol_raw['source_sha256']
            or file_hash(raw / 'prepare-source.py') != protocol_raw['preparer_sha256']):
        raise ValueError('raw download bindings incomplete or changed')
    expected = sorted((r['path'], r['url']) for r in protocol_raw['requests'])
    if sorted((r['path'], r['url']) for r in manifest['files']) != expected:
        raise ValueError('raw response list differs from pinned requests')
    dataset = Path(parent['dataset'])
    original, data = load(dataset)
    if file_hash(dataset / 'dataset.json') != parent['dataset_sha256'] or protocol_raw['dataset_sha256'] != parent['dataset_sha256']:
        raise ValueError('original dataset changed')
    pricing = json.loads(Path(parent['pricing']).joinpath('research.json').read_text())
    if file_hash(Path(parent['pricing']) / 'research.json') != parent['pricing_sha256']:
        raise ValueError('fixed pricing changed')
    protocol = dict(raw=str(raw.resolve()), raw_manifest_sha256=file_hash(raw / 'download-manifest.json'),
                    raw_protocol_sha256=file_hash(raw / 'download-protocol.json'),
                    admission=str(admission.resolve()), admission_sha256=file_hash(admission / 'research.json'),
                    source_sha256={n: file_hash(Path(__file__).with_name(n)) for n in DEPENDENCIES},
                    policies_changed=False, selected_policy_before_controls=parent['selected_spec'],
                    candidate_selection_from_controls=False, coefficient_rule='Only preceding original training days; no raw refits',
                    capture_started=False, live_candidate_promoted=False, independent_holdout=False)
    output.mkdir(parents=True)
    (output / 'protocol.json').write_text(json.dumps(protocol, indent=2) + '\n')
    (output / 'source').mkdir()
    for name in DEPENDENCIES:
        shutil.copyfile(Path(__file__).with_name(name), output / 'source' / name)
    upstream = json.loads(Path(data['history']).joinpath('research.json').read_text())
    archive = Path(upstream['source_manifest_path']).parent
    normalized = json.loads((archive / 'download-manifest.json').read_text())
    sessions, models, panels = [], {}, []
    for panel in protocol_raw['panels']:
        day = panel['day']
        observed, markers = parse_raw([f for f in manifest['files'] if f['day'] == day], raw)
        origin = int(datetime.strptime(day, '%Y-%m-%d').replace(tzinfo=timezone.utc).timestamp() * 1000)
        f = next(f for f in normalized['files'] if f['date'] == day)
        norm_all, _ = observations(archive / f['path'], origin, origin + DAY)
        norm = [(at, price) for at, price in norm_all if panel['fetch_start'] <= at < panel['fetch_end']]
        train = [r for r in original if r['period'] in data['dates'][:14] and r['period'] < day]
        engine = fit(train, ENGINE_SPEC)
        overlay = fit_overlay(apply_pause(predict(train, engine), PAUSE), pricing['models']['hurdle_all_120']['spec'])
        models[day] = dict(training_periods=sorted({r['period'] for r in train}), engine=engine, overlay=overlay)
        raw_prices = dict(observed)
        shared = [(at, price) for at, price in norm if at in raw_prices]
        panels.append(dict(panel, messages=len(observed), disconnect_markers=len(markers),
                           normalized_shared_timestamps=len(shared), oracle_mismatches=sum(raw_prices[at] != p for at, p in shared)))
        for source, observations_, cuts in (('raw_control', observed, markers), ('normalized_control', norm, [])):
            if panel['end'] - panel['start'] == DAY:
                sessions.extend(day_sessions(day, observations_, engine, overlay, source, 'control_diagnostic', cuts))
            else:
                rows = prepare_rows(observations_, panel, cuts)
                sessions.append(dict(id=f'{source}:{day}:extended', source=source, period=day,
                                     split='control_diagnostic', mode='restart',
                                     intervals=[dict(start=panel['start'], end=panel['end'], hour=(panel['start']-origin)//HOUR)],
                                     values=priced(rows, engine, overlay)))
    with gzip.open(output / 'input-sessions.jsonl.gz', 'wt') as stream:
        for session in sessions:
            stream.write(json.dumps(session, separators=(',', ':')) + '\n')
    cases = []
    with gzip.open(output / 'predictions.jsonl.gz', 'wt') as stream:
        for rule in SPECS:
            for session in sessions:
                values = admit(session['values'], rule)
                if any((a['width_ppm'], a['shadow_survived']) != (b['width_ppm'], b['shadow_survived'])
                       or (a['row']['activity_state'] != 'frozen' and a['paused'] != b['paused'])
                       for a, b in zip(values, session['values'])):
                    raise ValueError('admission changed forecasts or non-frozen policy')
                rows = measures(session, values, rule['name'])
                for r in rows:
                    if r['activity'] == 'all' and r['grid_windows'] != 960:
                        raise ValueError('complete eight-hour grid required')
                    non_frozen = [p for p in values if r['start'] <= p['row']['start'] < r['end']
                                  and p['row']['activity_state'] != 'frozen']
                    m = cell(non_frozen)
                    r.update(non_frozen_quoted=m['windows'], non_frozen_survival=m['survival'])
                cases.extend(rows)
                for p in values:
                    stream.write(json.dumps(dict(policy=rule['name'], session=session['id'], start=p['row']['start'],
                                                 width=p['width_ppm'], shadow=p['shadow_survived'], paused=p['paused'],
                                                 reason=p['floor_reason'], mature=p['admission_mature'], floor=p['admission_floor']), separators=(',', ':')) + '\n')
    # January's previously scored raw cases and the new controls have disjoint
    # periods. Keep fresh/continuous modes separate; never double-count them.
    combined = [dict(r, source='combined_raw', split='raw_diagnostic') for r in parent['cases'] if r['source'] == 'raw']
    combined += [dict(r, source='combined_raw', split='raw_diagnostic') for r in cases if r['source'] == 'raw_control']
    result = dict(protocol, panels=panels, models=models, cases=cases, summary=summarize(cases),
                  combined_raw_summary=summarize(combined), joint_checks=joint_checks(combined),
                  input_sessions_sha256=file_hash(output / 'input-sessions.jsonl.gz'),
                  predictions_sha256=file_hash(output / 'predictions.jsonl.gz'),
                  checks=dict(all_widths_and_shadow_outcomes_identical=True, policies_unchanged_since_download=True,
                              complete_eight_hour_grids=True, selection_from_new_data=False))
    (output / 'research.json').write_text(json.dumps(result, indent=2) + '\n')
    for name, rows in (('cases', cases), ('summary', result['summary']),
                       ('combined-raw-summary', result['combined_raw_summary']), ('joint-checks', result['joint_checks'])):
        write_csv(output / (name + '.csv'), rows, list(rows[0]))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--raw', type=Path, required=True)
    parser.add_argument('--admission', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = run(args.raw, args.admission, args.output)
    print(json.dumps(dict(panels=result['panels'], joint_checks=result['joint_checks']), indent=2))


if __name__ == '__main__':
    main()
