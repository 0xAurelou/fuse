#!/usr/bin/env python3
"""Admission-only research across retained eight-hour starts and continuous runs."""
import argparse
from collections import defaultdict
from datetime import datetime, timezone
import gzip
import json
from pathlib import Path
import shutil
from statistics import mean

from capture_dataset import file_hash
from investigate_capture import write_csv
from oracle_activity_features import load
from research_activity_calibration import fit, metrics, predict
from research_flat_pause import ENGINE_SPEC, apply_pause, episodes
from research_frozen_pricing import PAUSE, fit_overlay, reprice
from research_raw_flat_panels import (DEPENDENCIES as RAW_DEPENDENCIES, cell,
                                     parse_raw, prepare_rows)
from research_oracle_history import observations
from startup_admission import SPECS, admit

DAY, HOUR = 86_400_000, 3_600_000
DEPENDENCIES = ('research_startup_admission.py', 'startup_admission.py') + RAW_DEPENDENCIES


def verify_code(directory, metadata):
    for name, digest in metadata['source_sha256'].items():
        if file_hash(directory / 'source' / name) != digest or file_hash(Path(__file__).with_name(name)) != digest:
            raise ValueError('retained source differs: ' + name)


def priced(rows, engine, overlay):
    return reprice(apply_pause(predict(rows, engine), PAUSE), overlay)


def day_sessions(day, observed, engine, overlay, source, split, markers=(), continuous=True):
    origin = int(datetime.strptime(day, '%Y-%m-%d').replace(tzinfo=timezone.utc).timestamp() * 1000)
    intervals = [dict(start=origin + h * HOUR, end=origin + (h + 8) * HOUR, hour=h) for h in (0, 8, 16)]
    full = None
    output = []
    if continuous:
        rows = prepare_rows(observed, dict(day=day, fetch_start=origin, fetch_end=origin + DAY), markers)
        full = priced(rows, engine, overlay)
        output.append(dict(id=f'{source}:{day}:continuous', source=source, period=day,
                           split=split, mode='continuous', intervals=intervals, values=full))
    for interval in intervals:
        begin, end = interval['start'], interval['end']
        if interval['hour'] == 0 and full is not None:
            values = [p for p in full if p['row']['start'] < end]
        else:
            left = max(origin, begin - 300_000)
            rows = prepare_rows([(at, price) for at, price in observed if left <= at < end],
                                dict(day=day, fetch_start=left, fetch_end=end),
                                [m for m in markers if left <= m['known_at'] < end])
            values = priced(rows, engine, overlay)
        output.append(dict(id=f'{source}:{day}:restart:{interval["hour"]:02}', source=source,
                           period=day, split=split, mode='restart', intervals=[interval], values=values))
    return output


def measures(session, values, policy):
    output = []
    for interval in session['intervals']:
        part = [p for p in values if interval['start'] <= p['row']['start'] < interval['end']]
        for activity in ('all', 'frozen'):
            group = part if activity == 'all' else [p for p in part if p['row']['activity_state'] == activity]
            runs = episodes(group if activity == 'all' else part)
            output.append(dict(policy=policy, case_id=f'{session["id"]}:{interval["hour"]:02}',
                               source=session['source'], period=session['period'], split=session['split'],
                               mode=session['mode'], activity=activity, **interval, **cell(group),
                               warmup_decisions=sum(p.get('admission_warmup', False) for p in group),
                               warmup_eligible=sum(p.get('admission_warmup', False) and p['shadow_survived'] is not None for p in group),
                               grid_pause_episodes=len(runs),
                               longest_grid_pause_ms=max((e['grid_duration_ms'] for e in runs), default=0)))
    return output


def selection_score(sessions, rule):
    all_errors, frozen_errors, directional, cov, frozen_cov = [], [], [], [], []
    for session in sessions:
        values = admit(session['values'], rule)
        cells = measures(session, values, rule['name'])
        for r in cells:
            if r['eligible_outcomes'] == 0:
                continue
            if r['activity'] == 'all':
                cov.append(r['eligible_quote_fraction'])
                if r['survival'] is None:
                    return 1000.0
                all_errors.append(abs(r['error_pp']))
            elif r['eligible_outcomes'] >= 20:
                frozen_cov.append(r['eligible_quote_fraction'])
                if r['windows'] >= 20:
                    frozen_errors.append(abs(r['error_pp']))
        for interval in session['intervals']:
            for kind in ('pump', 'dump'):
                group = [p for p in values if interval['start'] <= p['row']['start'] < interval['end']
                         and p['row']['market_regime'] == kind]
                m = metrics(group)
                if m['windows'] >= 20:
                    directional.append(abs(m['error_pp']))
    if not all_errors:
        raise ValueError('no eligible scoring cases')
    value = mean(all_errors) + .25 * max(all_errors) + .5 * (mean(directional) if directional else 0)
    if frozen_errors:
        value += mean(frozen_errors) + .25 * max(frozen_errors)
    value += 25 * (1 - mean(cov)) + 100 * max(0, .85 - min(cov))
    # Explicitly charge frozen refusals even when they remove a case from the
    # >=20 offered-path calibration component. No-quotes never counts as a pass.
    if frozen_cov:
        value += 25 * (1 - mean(frozen_cov))
    return value


def choose(rows, dates, observed_by_day, pricing_spec):
    scores, folds = defaultdict(list), []
    for begin, end in ((6, 9), (9, 12), (12, 14)):
        train = [r for r in rows if r['period'] in dates[:begin]]
        engine = fit(train, ENGINE_SPEC)
        overlay = fit_overlay(apply_pause(predict(train, engine), PAUSE), pricing_spec)
        sessions = []
        for day in dates[begin:end]:
            sessions.extend(day_sessions(day, observed_by_day[day], engine, overlay,
                                         'normalized', 'inner', continuous=False))
        for rule in SPECS:
            score = selection_score(sessions, rule)
            scores[rule['name']].append(score)
            cells = [r for session in sessions for r in measures(session, admit(session['values'], rule), rule['name'])
                     if r['activity'] == 'all']
            folds.append(dict(policy=rule['name'], training_days=begin, scoring_days=dates[begin:end],
                              score=score, eligible_outcomes=sum(r['eligible_outcomes'] for r in cells),
                              quoted_outcomes=sum(r['windows'] for r in cells)))
    ranking = sorted((dict(name=s['name'], score=mean(scores[s['name']]), folds=scores[s['name']], index=i)
                      for i, s in enumerate(SPECS)), key=lambda r: (r['score'], r['index']))
    return next(s for s in SPECS if s['name'] == ranking[0]['name']), ranking, folds


def summarize(cases):
    groups = defaultdict(list)
    for r in cases:
        groups[(r['policy'], r['source'], r['split'], r['mode'], r['activity'])].append(r)
    output = []
    for (policy, source, split, mode, activity), rows in groups.items():
        eligible = sum(r['eligible_outcomes'] for r in rows)
        quoted = sum(r['windows'] for r in rows)
        measured = [r for r in rows if r['survival'] is not None]
        relevant = [r for r in rows if r['eligible_outcomes'] >= 20]
        output.append(dict(policy=policy, source=source, split=split, mode=mode, activity=activity,
                           cases=len(rows), eligible_outcomes=eligible, quoted_outcomes=quoted,
                           survival=sum(r['survived'] for r in rows) / quoted if quoted else None,
                           eligible_quote_fraction=quoted / eligible if eligible else None,
                           mean_case_error_pp=mean(abs(r['error_pp']) for r in measured) if measured else None,
                           worst_case_error_pp=max((abs(r['error_pp']) for r in measured), default=None),
                           minimum_case_availability=min((r['eligible_quote_fraction'] for r in rows if r['eligible_outcomes']), default=None),
                           cases_original_at_least20=len(relevant),
                           cases_pass_with_at_least20=sum(r['windows'] >= 20 and abs(r['error_pp']) <= 5 for r in relevant),
                           zero_quote_cases=sum(r['windows'] == 0 for r in relevant),
                           fewer_than20_quote_cases=sum(r['windows'] < 20 for r in relevant)))
    return output


def run(dataset, pricing, raw_research, startup_audit, output):
    if output.exists():
        raise ValueError('output exists; preserve retained experiments')
    original, data = load(dataset)
    old = json.loads((pricing / 'research.json').read_text())
    raw_old = json.loads((raw_research / 'research.json').read_text())
    audit_old = json.loads((startup_audit / 'audit.json').read_text())
    verify_code(pricing, old); verify_code(raw_research, raw_old)
    if old['dataset_sha256'] != file_hash(dataset / 'dataset.json') or raw_old['dataset_sha256'] != old['dataset_sha256']:
        raise ValueError('original dataset binding differs')
    raw = Path(raw_old['raw'])
    if file_hash(raw / 'download-manifest.json') != raw_old['raw_manifest_sha256']:
        raise ValueError('raw manifest changed')
    if file_hash(raw_research / 'rows.jsonl.gz') != raw_old['rows_sha256']:
        raise ValueError('retained raw rows changed')
    if file_hash(Path(audit_old['research']) / 'research.json') != audit_old['research_sha256']:
        raise ValueError('startup audit input changed')
    protocol = dict(dataset=str(dataset.resolve()), dataset_sha256=file_hash(dataset / 'dataset.json'),
                    pricing=str(pricing.resolve()), pricing_sha256=file_hash(pricing / 'research.json'),
                    raw_research=str(raw_research.resolve()), raw_research_sha256=file_hash(raw_research / 'research.json'),
                    startup_audit=str(startup_audit.resolve()), startup_audit_sha256=file_hash(startup_audit / 'audit.json'),
                    source_sha256={n: file_hash(Path(__file__).with_name(n)) for n in DEPENDENCIES},
                    specs=SPECS, fixed_pricing='hurdle_all_120', target_survival=.48, band=(.43, .53),
                    selection='Earlier 6/9/12 training prefixes, next 3/3/2 sample days; fresh 8h cases only; overall/frozen mean+worst errors, directional errors, prior overall availability penalty and frozen availability cost',
                    capture_started=False, live_candidate_promoted=False, production_approved=False,
                    independent_validation=False, original_eligibility_changed=False)
    output.mkdir(parents=True)
    (output / 'protocol.json').write_text(json.dumps(protocol, indent=2) + '\n')
    (output / 'source').mkdir()
    for name in DEPENDENCIES:
        shutil.copyfile(Path(__file__).with_name(name), output / 'source' / name)
    history = json.loads(Path(data['history']).joinpath('research.json').read_text())
    archive = Path(history['source_manifest_path']).parent
    manifest = json.loads((archive / 'download-manifest.json').read_text())
    observed_by_day = {}
    for f in manifest['files']:
        start = int(datetime.strptime(f['date'], '%Y-%m-%d').replace(tzinfo=timezone.utc).timestamp() * 1000)
        observed_by_day[f['date']], _ = observations(archive / f['path'], start, start + DAY)
    pricing_model = old['models']['hurdle_all_120']
    historical = [r for r in original if r['split'] != 'native']
    chosen, ranking, folds = choose(historical, data['dates'], observed_by_day, pricing_model['spec'])
    sessions = []
    for i, day in enumerate(data['dates']):
        split = 'train' if i < 14 else 'validation' if i < 19 else 'test'
        sessions.extend(day_sessions(day, observed_by_day[day], old['frozen_engine'], pricing_model, 'normalized', split))
    raw_manifest = json.loads((raw / 'download-manifest.json').read_text())
    observed, markers = parse_raw(raw_manifest['files'], raw)
    day = raw_old['panels'][0]['day']
    raw_models = raw_old['models'][day]
    sessions.extend(day_sessions(day, observed, raw_models['engine'],
                                 raw_models['overlays']['frozen_floor_53']['hurdle_all_120'],
                                 'raw', 'raw_diagnostic', markers))
    for period in dict.fromkeys(r['period'] for r in original if r['split'] == 'native'):
        rows = [r for r in original if r['period'] == period]
        sessions.append(dict(id=f'native:{period}', source='native', period=period, split='native', mode='restart',
                             intervals=[dict(start=rows[0]['start'], end=rows[-1]['expiry'], hour=0)],
                             values=priced(rows, old['frozen_engine'], pricing_model)))
    # Before comparing any new guard, reconstruct the retained full-day results.
    for session in sessions:
        if session['mode'] != 'continuous' and session['source'] != 'native':
            continue
        measured = cell(session['values'])
        if session['source'] == 'raw':
            ref = next(r for r in raw_old['summary'] if r['source'] == 'raw' and r['model'] == 'hurdle_all_120'
                       and r['pause'] == 'frozen_floor_53' and r['activity'] == 'all')
        else:
            ref = next(r for r in old['daily'] if r['model'] == 'hurdle_all_120' and r['period'] == session['period'])
        for key in ('windows', 'survived', 'eligible_outcomes', 'paused_eligible_outcomes'):
            if measured[key] != ref[key]:
                raise ValueError(f'full-period baseline differs: {session["id"]} {key}')
    with gzip.open(output / 'input-sessions.jsonl.gz', 'wt') as stream:
        for session in sessions:
            stream.write(json.dumps(session, separators=(',', ':')) + '\n')
    cases = []
    with gzip.open(output / 'predictions.jsonl.gz', 'wt') as stream:
        for rule in SPECS:
            for session in sessions:
                values = admit(session['values'], rule)
                if any((p['width_ppm'], p['shadow_survived'], p['row']['valid']) !=
                       (b['width_ppm'], b['shadow_survived'], b['row']['valid'])
                       for p, b in zip(values, session['values'])):
                    raise ValueError('admission changed widths, shadow outcomes or eligibility')
                cells = measures(session, values, rule['name'])
                cases.extend(cells)
                for p in values:
                    r = p['row']
                    stream.write(json.dumps(dict(policy=rule['name'], session=session['id'], start=r['start'],
                                                 activity=r['activity_state'], width_ppm=p['width_ppm'],
                                                 shadow_survived=p['shadow_survived'], survived=p['survived'],
                                                 paused=p['paused'], reason=p['floor_reason'], mature=p['admission_mature'],
                                                 floor=p['admission_floor'], slow_floor=p['admission_slow_floor'],
                                                 fast_floor=p['admission_fast_floor'], risky=p['admission_risky_entry'],
                                                 shadow_rate=p['admission_shadow_survival']), separators=(',', ':')) + '\n')
    # Same 8h fresh and continuous January cases as the previous startup audit.
    for r in cases:
        if r['policy'] == SPECS[0]['name'] and r['source'] == 'raw':
            ref = next(v for v in audit_old['summary'] if v['duration_hours'] == 8 and v['model'] == 'hurdle_all_120'
                       and v['pause'] == 'frozen_floor_53' and v['hour'] == r['hour']
                       and v['mode'] == r['mode'] and v['activity'] == r['activity'])
            for key in ('windows', 'survived', 'eligible_outcomes', 'paused_eligible_outcomes'):
                if r[key] != ref[key]:
                    raise ValueError('eight-hour January baseline differs from retained audit')
    result = dict(protocol, selected_spec=chosen, ranking=ranking, folds=folds, cases=cases,
                  summary=summarize(cases), input_sessions_sha256=file_hash(output / 'input-sessions.jsonl.gz'),
                  predictions_sha256=file_hash(output / 'predictions.jsonl.gz'),
                  checks=dict(all_widths_and_shadow_outcomes_identical=True,
                              original_full_day_and_native_parity=True, previous_eight_hour_january_parity=True))
    (output / 'research.json').write_text(json.dumps(result, indent=2) + '\n')
    for name, rows in (('cases', cases), ('summary', result['summary']), ('folds', folds)):
        write_csv(output / (name + '.csv'), rows, list(rows[0]))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset', type=Path, required=True)
    parser.add_argument('--pricing', type=Path, required=True)
    parser.add_argument('--raw-research', type=Path, required=True)
    parser.add_argument('--startup-audit', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = run(args.dataset, args.pricing, args.raw_research, args.startup_audit, args.output)
    print(json.dumps(dict(selected=result['selected_spec'], ranking=result['ranking'], checks=result['checks']), indent=2))


if __name__ == '__main__':
    main()
