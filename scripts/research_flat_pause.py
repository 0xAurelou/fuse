#!/usr/bin/env python3
"""Isolate flat-state entry pauses from the retained activity pricing engine.

Offline only. All reference paths, widths and matured calibration updates remain
identical for every pause candidate; current outcome eligibility never gates entry.
"""
import argparse
from collections import defaultdict
import csv
import json
from pathlib import Path
import shutil
from statistics import mean

from capture_dataset import file_hash
from investigate_capture import write_csv
from oracle_activity_features import load
from research_activity_calibration import (DEPENDENCIES as ENGINE_DEPENDENCIES,
    SPECS as ENGINE_SPECS, availability, fit, metrics, predict, score, shadow, summary)


def spec(name, *, previous=True, idle=None, recovery=None, floor=None):
    return dict(name=name, previous=previous, idle_ms=idle,
                recovery_changes=2 if recovery else None, recovery_window=recovery,
                recent_floor=floor, recent_minimum=30)


SPECS = (
    spec('existing'),
    spec('no_pause', previous=False),
    spec('idle_30s', idle=30_000),
    spec('idle_60s', idle=60_000),
    spec('idle_90s', idle=90_000),
    spec('idle_120s', idle=120_000),
    spec('idle_60s_recover_2_in_30s', idle=60_000, recovery='changes_30'),
    spec('idle_60s_recover_2_in_60s', idle=60_000, recovery='changes_60'),
    spec('frozen_floor_53', floor=.53),
    spec('frozen_floor_58', floor=.58),
    spec('frozen_floor_53_idle_60s', floor=.53, idle=60_000),
    spec('frozen_floor_58_idle_60s', floor=.58, idle=60_000),
)
ENGINE_SPEC = next(s for s in ENGINE_SPECS if s['name'] == 'activity_pause_wide')
DEPENDENCIES = ('research_flat_pause.py',) + ENGINE_DEPENDENCIES


def apply_pause(values, candidate):
    """Consume only entry features and already-mature engine floor diagnostics.

    A recovery latch survives missing features and is reset at a period boundary.
    Missing features suppress the underlying width, so are not extra pause decisions.
    The latch releases on distinct observed changes, never unchanged heartbeats.
    """
    result, session, latched, previous_start = [], None, False, None
    for p in values:
        r = p['row']
        if previous_start is not None and r['start'] < previous_start:
            raise ValueError('chronological predictions required')
        previous_start = r['start']
        if session != r['period']:
            session, latched = r['period'], False
        reasons = [p['floor_reason']] if candidate['previous'] and p['paused'] else []
        f = r['activity_features']
        if p['width_ppm'] is not None and f is not None:
            idle = candidate['idle_ms'] is not None and f['idle_ms'] >= candidate['idle_ms']
            if candidate['recovery_window']:
                if idle:
                    latched = True
                elif latched and f[candidate['recovery_window']] >= candidate['recovery_changes']:
                    latched = False
                if latched:
                    reasons.append('idle_recovery_latch')
            elif idle:
                reasons.append('idle_threshold')
            if (candidate['recent_floor'] is not None and r['activity_state'] == 'frozen'
                    and p['local_outcomes'] >= candidate['recent_minimum']
                    and p['predicted_floor'] > candidate['recent_floor']):
                reasons.append('matured_frozen_floor')
        paused = p['width_ppm'] is not None and bool(reasons)
        result.append(dict(p, paused=paused, floor_reason=';'.join(reasons) if paused else '',
                           survived=None if paused else p['shadow_survived']))
    return result


def diagnostics(values, q=.48):
    full = [p for p in values if p['shadow_survived'] is not None]
    paused = [p for p in full if p['paused']]
    decisions = [p for p in values if p['width_ppm'] is not None]
    offered = sum(not p['paused'] for p in decisions)
    return dict(**metrics(values, q), **availability(values),
                shadow_survival=metrics(shadow(values), q)['survival'],
                full_window_pinball_ppm=metrics(shadow(values), q)['pinball_ppm'],
                paused_shadow_survivors=sum(p['shadow_survived'] for p in paused),
                paused_shadow_failures=sum(not p['shadow_survived'] for p in paused),
                pre_entry_quote_fraction=offered / len(decisions) if decisions else None,
                grid_windows=len(values), offered_pre_entry_decisions=offered,
                grid_quote_fraction=offered / len(values) if values else None)


def episodes(values):
    """Contiguous 30-second grid refusal episodes, including invalid outcomes.

    An unpriceable-history row ends an observed pause episode; it does not imply
    the recovery latch cleared. Durations describe sampled decisions, not uptime.
    """
    result, current = [], None
    for p in values:
        r = p['row']
        if (current and (not p['paused'] or r['period'] != current['period']
                         or r['start'] != current['last_start'] + 30_000)):
            result.append(current)
            current = None
        if not p['paused']:
            continue
        if current is None:
            current = dict(period=r['period'], start=r['start'], last_start=r['start'],
                           decisions=0, eligible=0, shadow_survivors=0)
        current['last_start'] = r['start']
        current['decisions'] += 1
        current['eligible'] += p['shadow_survived'] is not None
        current['shadow_survivors'] += p['shadow_survived'] is True
    if current:
        result.append(current)
    for e in result:
        e['grid_duration_ms'] = e['last_start'] - e['start'] + 30_000
    return result


def choose(rows, dates, q=.48):
    """Same earlier expanding folds and availability objective as the engine.

    Engine coefficients are refitted on each prefix. Pause constants are declared
    above, never fitted on outer periods. Exact ties keep the existing gate.
    """
    scores, folds = defaultdict(list), []
    for begin, end in ((6, 9), (9, 12), (12, 14)):
        train = [r for r in rows if r['period'] in dates[:begin]]
        later = [r for r in rows if r['period'] in dates[begin:end]]
        base = predict(later, fit(train, ENGINE_SPEC, q))
        for candidate in SPECS:
            values = apply_pause(base, candidate)
            value = score(values, q)
            scores[candidate['name']].append(value)
            folds.append(dict(model=candidate['name'], training_days=begin,
                              scoring_days=dates[begin:end], selection_score=value,
                              **diagnostics(values, q)))
    ranking = sorted((dict(name=s['name'], score=mean(scores[s['name']]),
                           folds=scores[s['name']], index=i) for i, s in enumerate(SPECS)),
                     key=lambda r: (r['score'], r['index']))
    return next(s for s in SPECS if s['name'] == ranking[0]['name']), ranking, folds


def report(result):
    def pct(value):
        return 'no quotes' if value is None else f'{value:.2%}'
    selected = result['selected_spec']['name']
    lines = ['# Flat-state pause comparison', '',
             '**Offline research only; no capture or live change.**', '',
             f'Earlier-fold selection: **{selected}**. The retained activity_pause_wide '
             'pricing engine, widths and mature shadow updates are fixed across pause rules. '
             'Expanding 6/9/12-day prefixes fit the engine and score the next 3/3/2 '
             'within the original 14 training days. The existing availability penalty '
             'applies; ties keep the existing gate. Identical full-window losses need '
             'no additional loss guard. Outer/native observations never choose a rule.', '',
             'All days have already been inspected in development. Thresholds are '
             'declared research alternatives, not independently validated parameters. '
             'The target remains the legacy 48% reference, band 43–53%.', '',
             'Every added rule keeps the existing gate. Idle rules refuse at 30/60/90/120 '
             'seconds since the last observed change. Recovery variants latch after '
             '60 seconds idle until two distinct price changes occur in the prior '
             '30/60 seconds. Floor variants require a frozen entry, 30 mature context '
             'outcomes and a minimum-width empirical survival floor above 53%/58%. '
             'No-pause is an ablation. Entry features are strictly past; floor outcomes '
             'are delayed 30 seconds after expiry. Missing history never becomes a quote; '
             'a lower-bound idle age can trigger a pause. The recovery latch persists '
             'through missing features and resets per day/run.', '',
             '## August tradeoff (all 2,324 eligible paths retained)', '',
             '| Rule | Offered survival | Eligible availability | Refused | Refused shadow survivors / failures | Smallest outer-day availability |',
             '| --- | ---: | ---: | ---: | ---: | ---: |']
    for s in SPECS:
        r = next(v for v in result['daily'] if v['model'] == s['name'] and v['period'] == '2026-08-01')
        outer = [v for v in result['daily'] if v['model'] == s['name'] and v['period'] in result['dates'][14:]]
        lines.append(f"| {s['name']} | {pct(r['survival'])} | {pct(r['eligible_quote_fraction'])} | {r['paused_eligible_outcomes']} | {r['paused_shadow_survivors']} / {r['paused_shadow_failures']} | {pct(min(v['eligible_quote_fraction'] for v in outer))} |")
    lines += ['', 'August full-window shadow survival and loss are identical for all rules: '
              f"{pct(r['shadow_survival'])}, {r['full_window_pinball_ppm']:.4f} ppm. "
              'Refused shadow outcomes are descriptive reference outcomes, not trades or profit. '
              'Improving offered-only calibration by removing paths does not repair full-window pricing.', '',
              '## Earlier-fold ranking', '', '| Rule | Mean score | Fold scores |', '| --- | ---: | --- |']
    for r in result['ranking']:
        lines.append(f"| {r['name']} | {r['score']:.6f} | {', '.join(f'{v:.4f}' for v in r['folds'])} |")
    lines += ['', 'All daily, regime/activity, pre-entry decision and native denominators '
              'are retained in CSVs. Eligible availability uses only original clean-history '
              'outcome-eligible paths. Pre-entry availability instead includes decisions '
              'whose later outcome is censored. Grid availability also counts missing-history '
              'windows and is not measured continuous capture uptime.', '',
              'Episodes describe consecutive refused decisions on the 30-second research grid, '
              'not independent market episodes or production pause durations. The original '
              'capture reliability/deadline issues remain unresolved. Historical samples '
              'remain third-party first-of-month snapshots, not paired native evidence. '
              'This comparison does not justify a live promotion or a new capture.']
    return '\n'.join(lines) + '\n'


def run(dataset, previous, output):
    if output.exists():
        raise ValueError('output exists; preserve retained research')
    rows, source = load(dataset)
    old = json.loads((previous / 'research.json').read_text())
    model = old['models']['activity_pause_wide']
    q = model['target_survival']
    for name, digest in old['source_sha256'].items():
        if file_hash(previous / 'source' / name) != digest:
            raise ValueError('archived engine source changed')
        if file_hash(Path(__file__).with_name(name)) != digest:
            raise ValueError('working engine differs from retained engine')
    if file_hash(dataset / 'dataset.json') != old['dataset_sha256']:
        raise ValueError('dataset differs from retained engine input')
    historical = [r for r in rows if r['split'] != 'native']
    native = [r for r in rows if r['split'] == 'native']
    dates = source['dates']
    protocol = dict(dataset=str(dataset.resolve()), dataset_sha256=file_hash(dataset / 'dataset.json'),
                    previous=str(previous.resolve()), previous_sha256=file_hash(previous / 'research.json'),
                    source_sha256={n: file_hash(Path(__file__).with_name(n)) for n in DEPENDENCIES},
                    specs=SPECS, pricing_engine='fixed activity_pause_wide; no width or update changes',
                    target_survival=q, dates=dates, capture_started=False, live_candidate_promoted=False,
                    fresh_prospective_validation=False, production_approved=False,
                    selection='Earlier 6/9/12 prefixes only; same daily/regime/worst error and availability penalty; existing gate wins ties')
    output.mkdir(parents=True)
    (output / 'protocol.json').write_text(json.dumps(protocol, indent=2) + '\n')
    (output / 'source').mkdir()
    for name in DEPENDENCIES:
        shutil.copyfile(Path(__file__).with_name(name), output / 'source' / name)
    selected, ranking, folds = choose(historical, dates, q)
    baseline = predict(historical, model)
    baseline += predict(native, model)
    daily, comparisons, groups, episode_rows = [], [], [], []
    predictions = {}
    for candidate in SPECS:
        name = candidate['name']
        values = apply_pause(baseline, candidate)
        predictions[name] = values
        comparisons.extend(summary(values, name, q))
        for period in dict.fromkeys(p['row']['period'] for p in values):
            part = [p for p in values if p['row']['period'] == period]
            daily.append(dict(model=name, period=period, split=part[0]['row']['split'], **diagnostics(part, q)))
            for axis, kinds in (('market_regime', ('range', 'pump', 'dump', 'mixed')),
                                ('activity_state', ('active', 'bursty', 'sparse', 'frozen'))):
                for kind in kinds:
                    group = [p for p in part if p['row'][axis] == kind]
                    if any(p['shadow_survived'] is not None for p in group):
                        groups.append(dict(model=name, period=period, axis=axis, group=kind,
                                           **diagnostics(group, q)))
        episode_rows.extend(dict(model=name, **e) for e in episodes(values))
    # Reconstruct every original historical day and both native runs, not just totals.
    for r in daily:
        if r['model'] != 'existing':
            continue
        if r['split'] == 'native':
            oldrow = next(v for v in old['native_summary'] if v['run'] == r['period']
                          and v['model'] == ENGINE_SPEC['name'] and v['axis'] == 'regime' and v['group'] == 'all')
        else:
            oldrow = next(v for v in old['daily'] if v['model'] == ENGINE_SPEC['name'] and v['period'] == r['period'])
        for key in ('windows', 'survived', 'eligible_outcomes', 'quoted_outcomes', 'paused_eligible_outcomes'):
            if r[key] != oldrow[key]:
                raise ValueError(f'retained baseline mismatch: {r["period"]} {key}')
    identical = all([(p['width_ppm'], p['correction'], p['shadow_survived']) for p in part] ==
                    [(p['width_ppm'], p['correction'], p['shadow_survived']) for p in baseline]
                    for part in predictions.values())
    if not identical:
        raise ValueError('pause changed pricing or full-path shadow outcomes')
    result = dict(protocol, selected_spec=selected, ranking=ranking, folds=folds,
                  frozen_pricing_model=model, daily=daily, summary=comparisons,
                  period_groups=groups, episodes=episode_rows, native_sources=source['native_sources'],
                  checks=dict(all_widths_corrections_shadow_outcomes_identical=identical,
                              retained_historical_and_native_baseline_exact=True))
    if (file_hash(dataset / 'dataset.json') != protocol['dataset_sha256']
            or file_hash(previous / 'research.json') != protocol['previous_sha256']):
        raise ValueError('source metadata changed during analysis')
    (output / 'research.json').write_text(json.dumps(result, indent=2) + '\n')
    for filename, part in (('summary', comparisons), ('daily', daily), ('period-groups', groups),
                           ('folds', folds), ('episodes', episode_rows)):
        write_csv(output / (filename + '.csv'), part, list(part[0]))
    with (output / 'predictions.csv').open('x', newline='') as stream:
        fields = ['model', 'period', 'start', 'split', 'valid', 'activity', 'idle_ms',
                  'width_ppm', 'correction', 'shadow_survived', 'survived', 'paused', 'floor_reason']
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for name, values in predictions.items():
            for p in values:
                r = p['row']
                writer.writerow(dict(model=name, period=r['period'], start=r['start'], split=r['split'],
                                     valid=r['valid'], activity=r['activity_state'],
                                     idle_ms=r['activity_features']['idle_ms'] if r['activity_features'] else None,
                                     **{k: p[k] for k in fields[7:]}))
    (output / 'report.md').write_text(report(result))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset', type=Path, required=True)
    parser.add_argument('--previous', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = run(args.dataset, args.previous, args.output)
    print(json.dumps(dict(selected=result['selected_spec'], ranking=result['ranking'],
                          august=[r for r in result['daily'] if r['period'] == '2026-08-01'],
                          checks=result['checks']), indent=2))


if __name__ == '__main__':
    main()
