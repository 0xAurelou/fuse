#!/usr/bin/env python3
"""Chronological pump-phase and causal rolling-calibration research.

All earlier experiments stay intact. Candidate selection uses expanding folds
inside the original training days only. Previously inspected outer periods and
native recordings remain retrospective diagnostics. No collection/live updates.
"""
import argparse
from collections import defaultdict, deque
from copy import deepcopy
import csv
import json
import math
from pathlib import Path
import shutil
from statistics import mean

from adaptive_corridor import pinball, required_width, weighted_quantile
from capture_dataset import file_hash
from investigate_capture import write_csv
from research_oracle_history import load_capture_rows

TARGET = .48
GROUPS = ('range', 'pump', 'dump', 'mixed')
SPECS = (
    dict(name='frozen_blend', weighting='shape', grouping='all', memory=0),
    dict(name='period_blend', weighting='period', grouping='all', memory=0),
    dict(name='period_regime', weighting='period', grouping='regime', memory=0),
    dict(name='period_phase', weighting='period', grouping='phase', memory=0),
    dict(name='rolling_regime_120', weighting='period', grouping='regime', memory=120),
    dict(name='rolling_phase_60', weighting='period', grouping='phase', memory=60),
    dict(name='rolling_phase_120', weighting='period', grouping='phase', memory=120),
    dict(name='rolling_phase_240', weighting='period', grouping='phase', memory=240),
)
ONLINE = dict(maturity_delay_ms=30_000, prior_mass=30, minimum_correction=.75,
              maximum_correction=4 / 3, maximum_step_fraction=.02,
              maximum_outcome_age_ms=4 * 3_600_000, minimum_mature_outcomes=30,
              prior_method='log-scale shrinkage of empirical quantile toward one',
              missing_features='suppress quote; retain mature valid calibration until age expiry')
DEPENDENCIES = ('stabilize_adaptive_corridor.py', 'research_oracle_history.py',
                'research_market_regimes.py', 'adaptive_corridor.py',
                'investigate_capture.py', 'capture_dataset.py', 'analyze_capture.py',
                'prospective_capture.py')


def size(row):
    f = row['adaptive_features']
    return max(1.0, .5 * f['vol_60_ppm'] + .5 * f['vol_300_ppm'])


def phase(row):
    f = row['adaptive_features']
    ratio = f['vol_60_ppm'] / max(1.0, f['vol_300_ppm'])
    return 'cooling' if ratio < .75 else 'accelerating' if ratio > 1.25 else 'steady'


def group_for(row, grouping):
    kind = row['market_regime']
    return kind + '_' + phase(row) if grouping == 'phase' and kind == 'pump' else kind


def eligible(row):
    return row['valid'] and row['adaptive_features'] is not None


def balanced_weights(rows, directional=False):
    """Equal period mass; within directional periods, equal context-cluster mass."""
    periods = defaultdict(list)
    for i, row in enumerate(rows):
        periods[row['period']].append((i, row))
    weights = [0.0] * len(rows)
    for part in periods.values():
        if not directional:
            for i, _ in part:
                weights[i] = 1 / len(part)
            continue
        clusters = []
        for i, row in sorted(part, key=lambda x: x[1]['start']):
            begin, end = row['start'] - 300_000, row['expiry']
            if clusters and begin <= clusters[-1]['end']:
                clusters[-1]['end'] = end
                clusters[-1]['indices'].append(i)
            else:
                clusters.append(dict(end=end, indices=[i]))
        for cluster in clusters:
            for i in cluster['indices']:
                weights[i] = 1 / (len(clusters) * len(cluster['indices']))
    return weights


def scale_fit(rows, q, weighting, directional=False):
    weights = ([size(r) for r in rows] if weighting == 'shape'
               else balanced_weights(rows, directional))
    return weighted_quantile([(required_width(r) / size(r), w) for r, w in zip(rows, weights)], q)


def fit_model(train, spec, q=TARGET, maximum=50_000):
    rows = [r for r in train if eligible(r)]
    if len(rows) < 50:
        raise ValueError('at least 50 eligible training rows required')
    global_scale = scale_fit(rows, q, spec['weighting'])
    scales = {}
    if spec['grouping'] != 'all':
        for kind in GROUPS:
            part = [r for r in rows if r['market_regime'] == kind]
            periods = len({r['period'] for r in part})
            if len(part) >= 80 and periods >= 3:
                fitted = scale_fit(part, q, spec['weighting'], kind in ('pump', 'dump'))
                weight = len(part) / (len(part) + 200)
                scale = math.exp(weight * math.log(fitted) + (1 - weight) * math.log(global_scale))
            else:
                scale, weight = global_scale, 0
            scales[kind] = dict(scale=scale, training_windows=len(part), training_periods=periods,
                                shrinkage_weight=weight, parent='global')
        if spec['grouping'] == 'phase':
            for p in ('cooling', 'steady', 'accelerating'):
                part = [r for r in rows if r['market_regime'] == 'pump' and phase(r) == p]
                periods = len({r['period'] for r in part})
                parent = scales['pump']['scale']
                if len(part) >= 80 and periods >= 3:
                    fitted = scale_fit(part, q, spec['weighting'], True)
                    weight = len(part) / (len(part) + 200)
                    scale = math.exp(weight * math.log(fitted) + (1 - weight) * math.log(parent))
                else:
                    scale, weight = parent, 0
                scales['pump_' + p] = dict(scale=scale, training_windows=len(part),
                                          training_periods=periods, shrinkage_weight=weight, parent='pump')
    return dict(spec, global_scale=global_scale, scales=scales, target_survival=q,
                maximum_width_ppm=maximum, online=ONLINE if spec['memory'] else None)


def static_scale(row, model):
    return model['scales'].get(group_for(row, model['grouping']), {}).get('scale', model['global_scale'])


def predict_sequence(rows, model):
    """Only mature past reference-window outcomes may update a future quote.

    Current/future outcome eligibility never gates a prediction. History features
    are pre-entry; scored outcome eligibility is applied later, after prediction.
    The reference grid updates without assuming any trader chose to enter.
    """
    pending, recent = deque(), deque()
    correction = 1.0
    session = None
    previous_start = None
    output = []
    memory = model['memory']
    online = model['online']
    for row in rows:
        if previous_start is not None and row['start'] < previous_start:
            raise ValueError('rows must be chronological')
        previous_start = row['start']
        if row['period'] != session:
            session = row['period']
            pending.clear()
            recent.clear()
            correction = 1.0
        at = row['start']
        if memory:
            while pending and pending[0]['mature_at'] <= at:
                resolved = pending.popleft()
                # valid is read only at the declared maturity, never at entry.
                if resolved['row']['valid']:
                    recent.append((resolved['row']['expiry'], required_width(resolved['row']) / resolved['base']))
            while recent and (len(recent) > memory or at - recent[0][0] > online['maximum_outcome_age_ms']):
                recent.popleft()
        f = row['adaptive_features']
        if f is None:
            # Missing input blocks quoting. It does not invalidate completed
            # earlier paths; those calibration observations expire by wall age.
            output.append(dict(row=row, width_ppm=None, correction=None,
                               mature_outcomes=len(recent), survived=None, capped=False))
            continue
        base = static_scale(row, model) * size(row)
        if memory:
            requested = 1.0
            if len(recent) >= online['minimum_mature_outcomes']:
                empirical = weighted_quantile([(v, 1) for _, v in recent], model['target_survival'])
                weight = len(recent) / (len(recent) + online['prior_mass'])
                requested = math.exp(weight * math.log(empirical))
            requested = min(online['maximum_correction'], max(online['minimum_correction'], requested))
            step = online['maximum_step_fraction']
            correction = min(correction * (1 + step), max(correction * (1 - step), requested))
        raw = max(1, math.ceil(base * correction))
        width = min(raw, model['maximum_width_ppm'])
        # Scoring is separate from the prediction/update state.
        won = row['move'] < row['entry'] * width // 1_000_000 if row['valid'] else None
        output.append(dict(row=row, width_ppm=width, correction=correction,
                           mature_outcomes=len(recent), survived=won,
                           capped=raw > model['maximum_width_ppm']))
        if memory:
            pending.append(dict(row=row, base=base,
                                mature_at=row['expiry'] + online['maturity_delay_ms']))
    return output


def metrics(predictions, q=TARGET):
    scored = [p for p in predictions if p['survived'] is not None]
    n = len(scored)
    wins = sum(p['survived'] for p in scored)
    return dict(windows=n, survived=wins, survival=wins / n if n else None,
                error_pp=100 * (wins / n - q) if n else None,
                pinball_ppm=mean(pinball(required_width(p['row']), p['width_ppm'], q) for p in scored) if n else None,
                mean_width_ppm=mean(p['width_ppm'] for p in scored) if n else None,
                maximum_width_ppm=max((p['width_ppm'] for p in scored), default=None),
                capped_windows=sum(p['capped'] for p in scored))


def period_metrics(predictions, q=TARGET):
    groups = defaultdict(list)
    for p in predictions:
        if p['survived'] is not None:
            row = p['row']
            groups[(row['period'], 'all')].append(p)
            groups[(row['period'], row['market_regime'])].append(p)
            if row['market_regime'] == 'pump':
                groups[(row['period'], 'pump_' + phase(row))].append(p)
    return [dict(period=period, group=group, **metrics(part, q)) for (period, group), part in groups.items()]


def selection_score(predictions, q=TARGET):
    rows = period_metrics(predictions, q)
    daily = [abs(r['error_pp']) for r in rows if r['group'] == 'all']
    directional = [abs(r['error_pp']) for r in rows if r['group'] in ('pump', 'dump') and r['windows'] >= 20]
    if not daily:
        raise ValueError('no scored periods')
    return mean(daily) + .5 * (mean(directional) if directional else 0) + .25 * max(daily)


def select_spec(rows, dates, q=TARGET):
    """Expanding folds contained entirely inside the first 14 sample days."""
    training_dates = dates[:int(len(dates) * .6)]
    if len(training_dates) < 14:
        raise ValueError('fourteen original training days required for declared folds')
    folds = ((6, 9), (9, 12), (12, 14))
    scores = defaultdict(list)
    diagnostics = []
    for begin, end in folds:
        train = [r for r in rows if r['period'] in training_dates[:begin]]
        evaluate = [r for r in rows if r['period'] in training_dates[begin:end]]
        baseline_loss = None
        for spec in SPECS:
            model = fit_model(train, spec, q)
            predictions = predict_sequence(evaluate, model)
            scored = metrics(predictions, q)
            if baseline_loss is None:
                baseline_loss = scored['pinball_ppm']
            score = selection_score(predictions, q)
            # Penalize >10% deterioration in path-width quantile loss.
            penalty = 100 * max(0, scored['pinball_ppm'] / baseline_loss - 1.1)
            scores[spec['name']].append(score + penalty)
            diagnostics.append(dict(fold_training_days=begin, fold_scoring_days=training_dates[begin:end],
                                    model=spec['name'], score=score + penalty,
                                    loss_guard_penalty=penalty, **scored))
    ranking = sorted((dict(name=name, mean_inner_score=mean(values), fold_scores=values)
                      for name, values in scores.items()), key=lambda r: (r['mean_inner_score'], r['name']))
    selected = next(deepcopy(s) for s in SPECS if s['name'] == ranking[0]['name'])
    return selected, ranking, diagnostics


def load_history(directory):
    result = json.loads((directory / 'research.json').read_text())
    manifest_path = Path(result['source_manifest_path'])
    if file_hash(manifest_path) != result['source_manifest_sha256']:
        raise ValueError('historical download manifest changed')
    manifest = json.loads(manifest_path.read_text())
    for f in manifest['files']:
        if file_hash(manifest_path.parent / f['path']) != f['sha256']:
            raise ValueError('retained historical oracle sample changed')
    for name, digest in result['source_sha256'].items():
        if file_hash(directory / 'source' / name) != digest:
            raise ValueError('archived feature-generation code changed')
    rows = []
    with (directory / 'predictions.csv').open() as stream:
        for r in csv.DictReader(stream):
            f = None
            if r['vol_300_ppm']:
                f = {k: float(r[k]) for k in ('vol_60_ppm', 'vol_300_ppm', 'net_300_bps', 'directional_strength')}
            rows.append(dict(period=r['date'], split=r['split'], start=int(r['start']), expiry=int(r['expiry']),
                             entry=int(r['entry']) if r['entry'] else None, move=int(r['move']),
                             valid=r['valid'] == 'True', market_regime=r['market_regime'], adaptive_features=f))
    return rows, result


def diagnostics(rows, baseline, q=TARGET):
    predictions = predict_sequence(rows, baseline)
    return [dict(split=split, group=group, **metrics([p for p in predictions
                 if p['row']['split'] == split and (group == 'all' or p['row']['market_regime'] == 'pump'
                     and ('pump_' + phase(p['row']) == group if p['row']['adaptive_features'] is not None else False))], q))
            for split in ('train', 'validation', 'test')
            for group in ('all', 'pump_cooling', 'pump_steady', 'pump_accelerating')]


def summarize(predictions, model, q=TARGET):
    result = []
    for split in dict.fromkeys(p['row']['split'] for p in predictions):
        part = [p for p in predictions if p['row']['split'] == split]
        for group in ('all',) + GROUPS:
            values = part if group == 'all' else [p for p in part if p['row']['market_regime'] == group]
            result.append(dict(model=model, split=split, group=group, **metrics(values, q)))
    return result


def stability(predictions, q=TARGET):
    by_day = [r for r in period_metrics(predictions, q) if r['group'] == 'all']
    return dict(periods=len(by_day), daily_mean_absolute_error_pp=mean(abs(r['error_pp']) for r in by_day),
                daily_worst_absolute_error_pp=max(abs(r['error_pp']) for r in by_day),
                days_inside_reference_band=sum(abs(r['error_pp']) <= 5 for r in by_day),
                minimum_daily_survival=min(r['survival'] for r in by_day),
                maximum_daily_survival=max(r['survival'] for r in by_day))


def make_report(result):
    lines = ['# Pump calibration and period stability', '',
             '**Offline retrospective development; no capture started, no live policy changed.**', '',
             'This iteration adds pump-phase calibration, equal-period fitting, and a bounded causal rolling correction. All eight candidate definitions and source hashes were saved in `protocol.json` before scoring. All prior experiments remain unchanged.', '',
             '## Selection uses the original training days only', '',
             'Expanding folds train on the first 6, 9 and 12 sample days and score the next 3, 3 and 2, respectively. All folds are inside the first 14 historical training days. Rank candidates by equal-day absolute calibration error plus half the mean directional daily error (groups with ≥20 windows) plus a quarter of worst daily error. Penalize quantile loss deterioration greater than 10% relative to the frozen-blend baseline. Outer validation, final diagnostic periods and native recordings do not choose the model or its hyperparameters.', '',
             f"The inner-fold choice is **{result['selected_spec']['name']}**. Exact rankings, folds and coefficients are retained in `research.json`.", '',
             'All outer data were already examined in earlier iterations. Excluding them from fitting and selection does not make them untouched holdouts or fresh prospective evidence.', '',
             '## What changes in the formula', '',
             'Base shape is `max(1, (vol60 + vol300)/2)` in ppm. Period-balanced models fit the desired quantile of required surviving width divided by this shape, giving each training day equal mass. Directional fits also balance overlapping-context clusters within each day. This differs from the old shape-weighted loss objective; the baseline reproduces that old objective.', '',
             'Regime scales shrink toward the global scale; pump-phase scales additionally shrink toward the pump parent. Cooling means vol60/vol300 <0.75, accelerating >1.25, otherwise steady. These are pre-entry definitions. A subgroup needs ≥80 training windows across ≥3 days, or uses its parent. Shrinkage uses a fixed 200-window pseudo-count; counts are not claims of statistical independence.', '',
             'For rolling candidates, `width = ceil(base_scale[group] * shape * correction)`, bounded to the declared offline width range. After at least 30 mature observations, take their empirical target quantile of required-width/base-width ratios and shrink its log toward zero by n/(n+30). This avoids the earlier point-mass prior that produced a large calibration dead zone. The correction stays within [0.75, 4/3] and changes by at most 2% per new entry. Models compare 60, 120 and 240 mature-window memories; observations expire after four hours. A window is available to learning only 30 seconds after its expiry. Missing pre-entry features suppress quotes but retain completed valid calibration evidence until age expiry. All calibration state resets at every sample-day/native-run boundary.', '',
             'The update schedule is frozen code, not unrestricted retuning. Each accepted corridor stays fixed. Prediction never uses current/future outcome eligibility. These are reference-window observations independent of trader entry decisions, not assumed realized trader outcomes.', '',
             '## Outer historical diagnostics', '',
             '| Slice / group | Windows | Old blend survival | Inner-selected survival |',
             '| --- | ---: | ---: | ---: |']
    chosen = result['selected_spec']['name']
    for split in ('validation', 'test'):
        for group in ('all', 'pump', 'dump', 'range'):
            cells = {r['model']: r for r in result['summary'] if r['split'] == split and r['group'] == group}
            if cells['frozen_blend']['windows']:
                lines.append(f"| {split} / {group} | {cells['frozen_blend']['windows']} | {cells['frozen_blend']['survival']:.2%} | {cells[chosen]['survival']:.2%} |")
    lines += ['', '| Slice | Model | Mean daily absolute error | Worst daily absolute error | Days within ±5 pp |',
              '| --- | --- | ---: | ---: | ---: |']
    for r in result['stability']:
        if r['model'] in ('frozen_blend', chosen):
            lines.append(f"| {r['split']} | {r['model']} | {r['daily_mean_absolute_error_pp']:.2f} pp | {r['daily_worst_absolute_error_pp']:.2f} pp | {r['days_inside_reference_band']}/{r['periods']} |")
    lines += ['', '## Existing native recordings', '',
              'The historical training days fit the models. Native recordings pass their original frozen-artifact and native chain checks, and never select the rule. Rolling models may learn only from earlier mature eligible windows within the same run, following the declared update schedule. All scored windows, including the initial learning period, remain in the overall denominator.', '',
              '| Native run | Model | Windows | Survival |', '| --- | --- | ---: | ---: |']
    for r in result['native_summary']:
        if r['group'] == 'all' and r['model'] in ('frozen_blend', chosen):
            lines.append(f"| {r['run']} | {r['model']} | {r['windows']} | {r['survival']:.2%} |")
    lines += ['', '## Limits and decision', '',
              'The target remains the legacy 48% research reference, with a descriptive 43–53% band. It is not a universal payout-model probability. Source normalization, first-of-month sampling, nonrandom freshness exclusions and correlated directional contexts remain material limitations. Daily extrema and complete cold-start scores are reported so good pooled survival cannot conceal unstable periods.', '',
              'No prospective readiness claim follows automatically from better averages. Review pump-specific misses, worst periods, width/correction tails and transfer failures before choosing a live research candidate. Native capture continuity/deadline repairs remain separate outstanding work. No coefficients, accepted quotes or original recordings were modified.']
    return '\n'.join(lines) + '\n'


def run(history, captures, output, q=TARGET):
    if output.exists():
        raise ValueError('output already exists; never overwrite retained research')
    if not 0 < q < 1:
        raise ValueError('invalid target')
    rows, previous = load_history(history)
    dates = previous['dates']
    protocol = dict(target_survival=q, specs=SPECS, online=ONLINE,
                    selection_folds=[[6, 9], [9, 12], [12, 14]],
                    selection_scope='Only expanding folds inside the first 14 original training sample days',
                    history=str(history.resolve()), history_research_sha256=file_hash(history / 'research.json'),
                    history_features_sha256=file_hash(history / 'predictions.csv'),
                    source_sha256={name: file_hash(Path(__file__).with_name(name)) for name in DEPENDENCIES},
                    native_capture_paths=[str(p.resolve()) for p in captures],
                    fresh_prospective_validation=False, production_approved=False,
                    capture_started=False, live_candidate_promoted=False)
    output.mkdir(parents=True)
    (output / 'protocol.json').write_text(json.dumps(protocol, indent=2) + '\n')
    (output / 'source').mkdir()
    for name in DEPENDENCIES:
        shutil.copyfile(Path(__file__).with_name(name), output / 'source' / name)
    chosen, ranking, folds = select_spec(rows, dates, q)
    train = [r for r in rows if r['period'] in dates[:14]]
    models = {s['name']: fit_model(train, s, q) for s in SPECS}
    summaries, daily, stable, predictions = [], [], [], {}
    for name, model in models.items():
        pred = predict_sequence(rows, model)
        predictions[name] = pred
        summaries.extend(summarize(pred, name, q))
        daily.extend(dict(model=name, **r) for r in period_metrics(pred, q))
        for split in ('validation', 'test'):
            part = [p for p in pred if p['row']['split'] == split]
            stable.append(dict(model=name, split=split, **stability(part, q)))
    # Preserve numerical comparability with the archived old-blend evaluation.
    for split in ('train', 'validation', 'test'):
        old = next(r for r in previous['comparison'] if r['model'] == 'adaptive' and r['split'] == split and r['group'] == 'all')
        actual = next(r for r in summaries if r['model'] == 'frozen_blend' and r['split'] == split and r['group'] == 'all')
        if q == previous['target_survival'] and (old['windows'], old['survived']) != (actual['windows'], actual['survived']):
            raise ValueError('old-blend reconstruction differs from the archived evaluation')
    native, native_sources, native_daily = [], [], []
    native_predictions = {}
    for path in captures:
        source = load_capture_rows(path)
        native_sources.append(source['source'])
        native_rows = source['rows']
        for row in native_rows:
            row.update(period=source['name'], split='native')
        for name, model in models.items():
            pred = predict_sequence(native_rows, model)
            native_predictions[(source['name'], name)] = pred
            native.extend(dict(run=source['name'], **r) for r in summarize(pred, name, q))
            # Whole-run plus hourly diagnostics include cold-start windows.
            for hour in range(8):
                start = source['manifest']['frozen_at_ms'] + hour * 3_600_000
                part = [p for p in pred if start <= p['row']['start'] < start + 3_600_000]
                native_daily.append(dict(run=source['name'], hour=hour + 1, model=name, **metrics(part, q)))
    result = dict(protocol, selected_spec=chosen, ranking=ranking, folds=folds, models=models,
                  summary=summaries, period_metrics=daily, stability=stable,
                  native_summary=native, native_hourly=native_daily, native_sources=native_sources,
                  pump_diagnostics=diagnostics(rows, models['frozen_blend'], q))
    for key, path in (('history_research_sha256', history / 'research.json'), ('history_features_sha256', history / 'predictions.csv')):
        if file_hash(path) != protocol[key]:
            raise ValueError('retained history changed during research')
    (output / 'research.json').write_text(json.dumps(result, indent=2) + '\n')
    for name, values in (('summary', summaries), ('period-metrics', daily), ('folds', folds),
                         ('native-summary', native), ('native-hourly', native_daily)):
        if values:
            write_csv(output / (name + '.csv'), values, list(values[0]))
    with (output / 'predictions.csv').open('x', newline='') as stream:
        fields = ['source', 'model', 'start', 'expiry', 'split', 'regime', 'valid',
                  'width_ppm', 'survived', 'correction', 'mature_outcomes', 'capped']
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for name, values in predictions.items():
            for p in values:
                r = p['row']
                writer.writerow(dict(source=r['period'], model=name, start=r['start'], expiry=r['expiry'],
                                     split=r['split'], regime=r['market_regime'], valid=r['valid'],
                                     **{k: p[k] for k in fields[7:]}))
        for (source, name), values in native_predictions.items():
            for p in values:
                r = p['row']
                writer.writerow(dict(source=source, model=name, start=r['start'], expiry=r['expiry'],
                                     split='native', regime=r['market_regime'], valid=r['valid'],
                                     **{k: p[k] for k in fields[7:]}))
    (output / 'report.md').write_text(make_report(result))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--history', type=Path, required=True)
    parser.add_argument('--captures', type=Path, nargs='*', default=[])
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--target-survival', type=float, default=TARGET)
    args = parser.parse_args()
    result = run(args.history, args.captures, args.output, args.target_survival)
    print(json.dumps(dict(output=str(args.output), selected=result['selected_spec'],
                          ranking=result['ranking'], summary=[r for r in result['summary'] if r['model'] in ('frozen_blend', result['selected_spec']['name'])],
                          native=[r for r in result['native_summary'] if r['group'] == 'all']), indent=2))


if __name__ == '__main__':
    main()
