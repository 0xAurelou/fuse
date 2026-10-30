#!/usr/bin/env python3
"""Fit and replay small past-only adaptive corridor research models.

Completed captures are reused as development data. This creates an offline
research artifact, never a deployable policy or a new prospective result.
"""
import argparse
from copy import deepcopy
import json
import math
from pathlib import Path
import shutil

from capture_dataset import file_hash
from investigate_capture import (analyze_run, label, lagged_features,
                                 regime_thresholds, stamp, write_csv)

MILLION = 1_000_000
GRID_MIX = (0.0, 0.5, 1.0)
GRID_TREND = (0.0, 0.5, 1.0, 2.0)
GRID_JUMP = (0.0, 0.5, 1.0, 2.0)
DEPENDENCIES = ('adaptive_corridor.py', 'investigate_capture.py',
                'capture_dataset.py', 'analyze_capture.py', 'prospective_capture.py')


def required_width(row):
    """Smallest integer ppm width surviving this exact discrete oracle path."""
    return ((row['move'] + 1) * MILLION + row['entry'] - 1) // row['entry']


def features(rows, paired, start):
    """Only history strictly before entry; any censored lookback rejects history."""
    short = deepcopy(rows)
    lagged_features(short, paired, start, lookback=60_000)
    lagged_features(rows, paired, start, lookback=300_000)
    for row, recent in zip(rows, short):
        slow, fast = row['lag_features'], recent['lag_features']
        row['adaptive_features'] = None
        if slow is None or fast is None:
            continue
        row['adaptive_features'] = dict(
            vol_60_ppm=fast['vol_bps'] * 100 * math.sqrt(30 / 60),
            vol_300_ppm=slow['vol_bps'] * 100 * math.sqrt(30 / 300),
            trend_60_ppm=abs(fast['net_bps']) * 100 * (30 / 60),
            jump_60_ppm=fast['max_step_bps'] * 100,
            signed_net_60_bps=fast['net_bps'],
            efficiency_60=fast['efficiency'])


def shape(row, model):
    if model['family'] == 'fixed':
        return 1.0
    f = row['adaptive_features']
    if f is None:
        raise ValueError('no clean pre-entry history; do not quote')
    mix = model['fast_weight']
    return max(1.0, mix * f['vol_60_ppm'] + (1 - mix) * f['vol_300_ppm']
               + model['trend_weight'] * f['trend_60_ppm']
               + model['jump_weight'] * f['jump_60_ppm'])


def weighted_quantile(values, q):
    if not 0 < q < 1 or not values or any(w <= 0 for _, w in values):
        raise ValueError('positive weights and a quantile strictly between zero and one required')
    values = sorted(values)
    cutoff = q * sum(w for _, w in values)
    cumulative = 0.0
    for value, weight in values:
        cumulative += weight
        if cumulative >= cutoff:
            return value
    return values[-1][0]


def predict(row, model):
    continuous = model['scale'] * shape(row, model)
    # This integer width is rounded once before the exact integer price barrier.
    raw = max(1, math.ceil(continuous))
    return min(raw, model['maximum_width_ppm']), raw > model['maximum_width_ppm']


def pinball(actual, predicted, q):
    residual = actual - predicted
    return q * residual if residual >= 0 else (q - 1) * residual


def fit_scale(rows, model, q):
    """Exact scalar quantile fit for each shape, before integer/clamp effects.

    loss(y-a*s) = s*loss(y/s-a), so the optimal a is a shape-weighted
    q-quantile of y/s. Structural coefficients use the declared finite grid.
    """
    values = [(required_width(r) / shape(r, model), shape(r, model)) for r in rows]
    model = dict(model, scale=weighted_quantile(values, q), target_survival=q)
    model['training_continuous_pinball_ppm'] = sum(
        pinball(required_width(r), model['scale'] * shape(r, model), q)
        for r in rows) / len(rows)
    return model


def fit_models(train, q, maximum):
    if len(train) < 50 or not 0 < q < 1 or maximum < 1:
        raise ValueError('at least 50 training windows, a valid quantile and positive width limit required')
    common = dict(maximum_width_ppm=maximum, fast_weight=0.0,
                  trend_weight=0.0, jump_weight=0.0)
    fixed = fit_scale(train, dict(common, family='fixed'), q)
    slow = fit_scale(train, dict(common, family='volatility'), q)
    candidates = [fit_scale(train, dict(common, family='adaptive', fast_weight=m,
                                       trend_weight=t, jump_weight=j), q)
                  for m in GRID_MIX for t in GRID_TREND for j in GRID_JUMP]
    adaptive = min(candidates, key=lambda c: (
        c['training_continuous_pinball_ppm'], c['trend_weight'] + c['jump_weight'],
        c['fast_weight'], c['trend_weight'], c['jump_weight']))
    return dict(fixed=fixed, volatility=slow, adaptive=adaptive)


def evaluate(rows, model, q):
    widths = [predict(r, model) for r in rows]
    n = len(rows)
    wins = sum(r['move'] < r['entry'] * w // MILLION
               for r, (w, _) in zip(rows, widths))
    return dict(windows=n, survived=wins, survival=wins / n if n else None,
                target_survival=q,
                error_pp=100 * (wins / n - q) if n else None,
                pinball_ppm=sum(pinball(required_width(r), w, q)
                                for r, (w, _) in zip(rows, widths)) / n if n else None,
                mean_width_ppm=sum(w for w, _ in widths) / n if n else None,
                minimum_width_ppm=min((w for w, _ in widths), default=None),
                maximum_width_ppm=max((w for w, _ in widths), default=None),
                capped_windows=sum(capped for _, capped in widths))


def fit_and_evaluate(runs, q, maximum):
    healthy = [r for r in runs[0]['rows'] if r['valid']]
    a, b = int(len(healthy) * .6), int(len(healthy) * .8)
    if not 0 < a < b < len(healthy):
        raise ValueError('first recording is too small for chronological 60/20/20')
    training_end, validation_end = healthy[a - 1]['expiry'], healthy[b - 1]['expiry']
    thresholds = regime_thresholds(runs[0]['rows'])
    partitions = {}
    for i, run in enumerate(runs):
        for row in run['rows']:
            row['regimes'] = label(row, thresholds)
            row['split'] = ('train' if row['expiry'] <= training_end else
                            'validation' if row['expiry'] <= validation_end else 'test') if i == 0 else 'later_recording'
            if row['valid'] and row['adaptive_features'] is not None:
                partitions.setdefault((run['name'], row['split']), []).append(row)
    models = fit_models(partitions[(runs[0]['name'], 'train')], q, maximum)
    metrics = []
    for (run, split), rows in partitions.items():
        groups = {('all', 'all'): rows}
        for axis in ('volatility', 'trend', 'jump'):
            for row in rows:
                groups.setdefault((axis, row['regimes'][axis]), []).append(row)
        for name, model in models.items():
            for (axis, group), part in groups.items():
                metrics.append(dict(run=run, split=split, model=name,
                                    group_axis=axis, group=group, **evaluate(part, model, q)))
    return dict(models=models, metrics=metrics, regime_thresholds=thresholds,
                training_end_ms=training_end, validation_end_ms=validation_end,
                structural_grid=dict(fast_weight=GRID_MIX, trend_weight=GRID_TREND,
                                     jump_weight=GRID_JUMP, combinations=48),
                selection='All coefficients selected only on the first 60% of healthy windows of the first recording, further restricted to clean pre-entry history; minimize training continuous pinball loss. Validation, test and later recording never select coefficients. No live candidate promoted.')


def report(result, runs):
    model = result['models']['adaptive']
    q = result['target_survival']
    lines = ['# Adaptive corridor research replay', '',
             'Saved receipts are development data. This is retrospective research, not a new prospective test. No live policy changed and no capture started.', '',
             f'Target survival: **{q:.2%}**. All widths below are half-widths in ppm.', '',
             'The fitted formula is:', '', '```text',
             f"v = {model['fast_weight']:g} * vol60 + {1-model['fast_weight']:g} * vol300",
             f"shape = max(1, v + {model['trend_weight']:g} * trend60 + {model['jump_weight']:g} * jump60)",
             f"width_ppm = clamp(ceil({model['scale']:.12g} * shape), 1, {model['maximum_width_ppm']})",
             'lower = entry - floor(entry * width_ppm / 1_000_000)',
             'upper = entry + floor(entry * width_ppm / 1_000_000)', '```', '',
             '`vol60` and `vol300` are square roots of summed squared log returns, rescaled to a 30-second horizon and expressed in ppm. `trend60` is the absolute preceding one-minute log return, scaled by 30/60, in ppm. `jump60` is the largest preceding one-minute absolute log price step, in ppm. These are observable features, not claims that diffusion scaling or recent drift forecasts the future.', '',
             'All feature observations precede entry strictly. Startup and any five-minute lookback touching a censored window have no prediction; missing history is never interpolated. Features update for each new entry. An accepted corridor stays fixed throughout its 30-second lifetime. The candidate trend feature treats pumping and dumping symmetrically through move magnitude; its fitted weight can be zero.', '',
             result['selection'], '',
             'The volatility baseline uses only the preceding five-minute variation; the fixed baseline uses one constant. Every model is fitted and scored on the same clean-history windows. Width caps, ties, exact integer barriers and touch failures are included in replay.', '',
             '| Recording / split | Windows | Fixed survival | Volatility survival | Adaptive survival |',
             '| --- | ---: | ---: | ---: | ---: |']
    totals = [m for m in result['metrics'] if m['group_axis'] == 'all']
    keys = list(dict.fromkeys((m['run'], m['split']) for m in totals))
    for run, split in keys:
        cells = {m['model']: m for m in totals if m['run'] == run and m['split'] == split}
        lines.append(f"| {run} / {split} | {cells['fixed']['windows']} | " +
                     ' | '.join(f"{cells[n]['survival']:.2%}" for n in ('fixed', 'volatility', 'adaptive')) + ' |')
    lines += ['', '## Data eligibility', '',
              '| Recording | Total windows | Healthy windows | Healthy with clean history |',
              '| --- | ---: | ---: | ---: |']
    for run in runs:
        healthy = [r for r in run['rows'] if r['valid']]
        clean = sum(r['adaptive_features'] is not None for r in healthy)
        lines.append(f"| {run['name']} | {len(run['rows'])} | {len(healthy)} | {clean} |")
    lines += ['', '## Later-recording regimes', '',
              'Regime thresholds use the first recording training portion only and are independent of the tested corridor. These are the same clean-history rows for both models.', '',
              '| Prior five-minute volatility | Windows | Fixed survival | Adaptive survival | Adaptive mean half-width |',
              '| --- | ---: | ---: | ---: | ---: |']
    for regime in ('quiet', 'normal', 'volatile'):
        cells = {m['model']: m for m in result['metrics']
                 if m['run'] == runs[-1]['name'] and m['group_axis'] == 'volatility' and m['group'] == regime}
        if cells:
            lines.append(f"| {regime} | {cells['adaptive']['windows']} | {cells['fixed']['survival']:.2%} | "
                         f"{cells['adaptive']['survival']:.2%} | {cells['adaptive']['mean_width_ppm']:.1f} ppm |")
    lines += ['',
              f"The selected research fit has fast-volatility weight {model['fast_weight']:g}, trend weight {model['trend_weight']:g}, and jump weight {model['jump_weight']:g}. Zero weights mean the declared training search did not find an improvement from those additions; they do not show that trend or jumps never matter. The model has not established separate pumping/dumping calibration."]
    lines += ['', '## Interpretation and next test', '',
              'Survival near the target in training does not establish calibration later or within every regime. The CSV retains pinball loss, width ranges, cap counts and regime denominators so a pooled average cannot hide failures. Adjacent observations are correlated; no independent-window confidence claim is made. Gap exclusions are nonrandom, and replay cannot recover missing price paths.', '',
              'Both recordings and their regimes were already inspected before this model was proposed. Later chronological slices are useful diagnostic comparisons, not untouched holdouts. Trend and jump examples remain limited. A small fitted coefficient or an improved replay does not establish that a feature will work in new markets.', '',
              'This target defaults to the legacy 48% reference experiment. For payout multiplier M and target gross house edge h, the intended pre-cost survival is (1-h)/M; one 48% target cannot price every payout. This script accepts another target but does not validate rare-event pricing, the entire multiplier surface, fees or LP economics.', '',
              'Before a prospective experiment: choose and freeze the full research rule, target, history/freshness gates, rounding, width limits and regime scoring; repair capture continuity/deadline handling; then run a new reliable recording. Freeze coefficients while allowing their declared past-only inputs to change. Online coefficient learning would require its own frozen update rule.', '',
              'Original frozen captures and evaluations remain unchanged. Research models here are not wired into the quote engine or collector policy.']
    return '\n'.join(lines) + '\n'


def replay(captures, output, q=.48, maximum=50_000):
    if output.exists():
        raise ValueError('output already exists; never overwrite a retained experiment')
    if len(captures) < 2 or not 0 < q < 1 or maximum < 1:
        raise ValueError('at least two completed captures, a valid quantile and positive width limit required')
    captures = [p.resolve() for p in captures]
    if len(set(captures)) != len(captures):
        raise ValueError('duplicate capture')
    runs = []
    previous_end = None
    reference_policy = None
    policy_fields = ('duration_ms', 'max_gap_ms', 'disagreement_ms', 'void_delay_ms', 'gap_rule', 'admission')
    for directory in captures:
        run = analyze_run(directory, [])
        manifest = run['manifest']
        policy = manifest['policy']
        if reference_policy is not None and any(policy[k] != reference_policy[k] for k in policy_fields):
            raise ValueError('incompatible observation/window policies')
        start = manifest['frozen_at_ms']
        if previous_end is not None and start < previous_end:
            raise ValueError('captures must be chronological and nonoverlapping')
        reference_policy = policy
        previous_end = start + manifest['duration_ms']
        # Reconstruct again to obtain the canonical paired observations; analyze_run
        # already checked every eligibility/path field against the frozen analyzer.
        from decimal import Decimal
        from investigate_capture import reconstruct
        with (directory / 'receipts.jsonl').open() as stream:
            receipts = [json.loads(line) for line in stream]
        records = [dict(at=r['at'], source=r['source'],
                        price=int(Decimal(r['raw']['data']['ctx']['oraclePx']) * MILLION))
                   for r in receipts]
        _, paired = reconstruct(records, policy, start, previous_end)
        features(run['rows'], paired, start)
        runs.append(run)
    result = fit_and_evaluate(runs, q, maximum)
    result.update(target_survival=q,
                  sources=[dict(r['source'], data_role='Previously inspected completed recording reused for adaptive-model development; not a fresh holdout.') for r in runs],
                  fresh_prospective_validation=False, production_approved=False,
                  live_candidate_promoted=False,
                  formula_version='past-only-shape-quantile-research-v1',
                  source_sha256={name: file_hash(Path(__file__).with_name(name)) for name in DEPENDENCIES})
    # Verify source receipt bytes remained unchanged during the replay.
    for run in runs:
        if file_hash(Path(run['source']['path']) / 'receipts.jsonl') != run['source']['sha256']:
            raise ValueError('source recording changed during replay')
    output.mkdir(parents=True)
    (output / 'source').mkdir()
    for name in DEPENDENCIES:
        shutil.copyfile(Path(__file__).with_name(name), output / 'source' / name)
    with (output / 'research-models.json').open('x') as stream:
        json.dump(result, stream, indent=2)
        stream.write('\n')
    write_csv(output / 'comparison.csv', result['metrics'], list(result['metrics'][0]))
    predictions = []
    for run in runs:
        for row in run['rows']:
            clean = row['adaptive_features'] is not None
            for name, model in result['models'].items():
                width, capped = predict(row, model) if clean else (None, None)
                predictions.append(dict(run=run['name'], split=row['split'], start_ms=row['start'],
                                        start_wita=stamp(row['start']), healthy=row['valid'],
                                        clean_pre_entry_history=clean, model=name, width_ppm=width,
                                        capped=capped, survived=(row['move'] < row['entry'] * width // MILLION)
                                        if row['valid'] and clean else None,
                                        **row['regimes'], **(row['adaptive_features'] or {})))
    fields = list(dict.fromkeys(k for row in predictions for k in row))
    write_csv(output / 'predictions.csv', predictions, fields)
    (output / 'report.md').write_text(report(result, runs))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--captures', type=Path, nargs='+', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--target-survival', type=float, default=.48)
    parser.add_argument('--maximum-width-ppm', type=int, default=50_000)
    args = parser.parse_args()
    result = replay(args.captures, args.output, args.target_survival, args.maximum_width_ppm)
    print(json.dumps(dict(output=str(args.output), models=result['models'],
                          comparison=[m for m in result['metrics'] if m['group_axis'] == 'all']), indent=2))


if __name__ == '__main__':
    main()
