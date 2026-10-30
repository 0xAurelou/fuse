#!/usr/bin/env python3
"""Activity-aware and pump-drift research; all quotes/captures remain unchanged."""
import argparse
from collections import defaultdict, deque
from copy import deepcopy
import csv
import json
import math
from pathlib import Path
import shutil
from statistics import mean

from adaptive_corridor import required_width, weighted_quantile
from capture_dataset import file_hash
from investigate_capture import write_csv
from oracle_activity_features import load
from stabilize_adaptive_corridor import (ONLINE, balanced_weights, eligible, fit_model,
                                         metrics, period_metrics, predict_sequence,
                                         selection_score, size, static_scale, summarize,
                                         stability)

ACTIVITIES = ('active', 'bursty', 'sparse', 'frozen')
BASE = dict(name='rolling_phase_120', weighting='period', grouping='phase', memory=120)
SPECS = (
    dict(name='previous', activity=False, local=False, wide=False, pump=False, pause=False),
    dict(name='activity', activity=True, local=False, wide=False, pump=False, pause=False),
    dict(name='activity_local', activity=True, local=True, wide=False, pump=False, pause=False),
    dict(name='activity_wide', activity=True, local=False, wide=True, pump=False, pause=False),
    dict(name='activity_local_wide', activity=True, local=True, wide=True, pump=False, pause=False),
    dict(name='activity_pump', activity=True, local=True, wide=False, pump=True, pause=False),
    dict(name='activity_pause', activity=True, local=True, wide=False, pump=True, pause=True),
    dict(name='activity_pause_wide', activity=True, local=True, wide=True, pump=True, pause=True),
)
DEPENDENCIES = ('research_activity_calibration.py', 'oracle_activity_features.py',
                'stabilize_adaptive_corridor.py', 'research_oracle_history.py',
                'research_market_regimes.py', 'adaptive_corridor.py',
                'capture_dataset.py', 'investigate_capture.py', 'analyze_capture.py',
                'prospective_capture.py')


def fit(train, spec, q=.48):
    base = fit_model(train, BASE, q)
    activity = {}
    if spec['activity']:
        for state in ACTIVITIES:
            part = [r for r in train if eligible(r) and r['activity_state'] == state]
            periods = len({r['period'] for r in part})
            weights = balanced_weights(part) if part else []
            floor = sum(w * (required_width(r) <= 1) for w, r in zip(weights, part)) / sum(weights) if weights else 0
            multiplier = 1.0
            if len(part) >= 80 and periods >= 3:
                ratios = [(required_width(r) / (static_scale(r, base) * size(r)), w)
                          for r, w in zip(part, weights)]
                raw = weighted_quantile(ratios, q)
                weight = len(part) / (len(part) + 200)
                multiplier = math.exp(weight * math.log(raw))
            activity[state] = dict(multiplier=multiplier, training_windows=len(part),
                                   training_periods=periods, balanced_floor_survival=floor)
    online = dict(ONLINE)
    if spec['wide']:
        online.update(minimum_correction=.4, maximum_correction=2.0)
    return dict(spec=spec, base=base, activity_scales=activity, online=online,
                target_survival=q, maximum_width_ppm=50_000, memory=120,
                local_minimum=12, local_prior_mass=30,
                gate=dict(training_minimum=200, training_periods=3, training_floor_margin=.10,
                          recent_minimum=30, recent_floor_margin=.15))


def context(row, model):
    if model['spec']['pump'] and row['market_regime'] == 'pump' and row['activity_state'] == 'active':
        return 'pump'
    return row['activity_state']


def quantile_correction(part, q, prior):
    empirical = weighted_quantile([(p['ratio'], 1) for p in part], q)
    return math.exp(len(part) / (len(part) + prior) * math.log(empirical))


def predict(rows, model):
    if model['spec']['name'] == 'previous':
        values = predict_sequence(rows, model['base'])
        for p in values:
            p.update(shadow_survived=p['survived'], paused=False, local_outcomes=0,
                     predicted_floor=None, floor_reason='')
        return values
    pending, recent = deque(), deque()
    local = defaultdict(deque)
    correction = 1.0
    session = None
    previous_at = None
    output = []
    q, online = model['target_survival'], model['online']
    for row in rows:
        at = row['start']
        if previous_at is not None and at < previous_at:
            raise ValueError('chronological rows required')
        previous_at = at
        if session != row['period']:
            session = row['period']
            pending.clear(); recent.clear(); local.clear()
            correction = 1.0
        while pending and pending[0]['mature_at'] <= at:
            past = pending.popleft()
            if past['row']['valid']:
                item = dict(expiry=past['row']['expiry'],
                            ratio=required_width(past['row']) / past['base'],
                            floor=required_width(past['row']) <= 1)
                recent.append(item)
                local[past['context']].append(item)
        for pool in [recent] + list(local.values()):
            while pool and (len(pool) > model['memory'] or at - pool[0]['expiry'] > online['maximum_outcome_age_ms']):
                pool.popleft()
        if row['adaptive_features'] is None:
            output.append(dict(row=row, width_ppm=None, correction=None, mature_outcomes=len(recent),
                               local_outcomes=0, survived=None, shadow_survived=None,
                               capped=False, paused=False, predicted_floor=None, floor_reason=''))
            continue
        key = context(row, model)
        subgroup = local[key]
        state = row['activity_state']
        factor = model['activity_scales'].get(state, {}).get('multiplier', 1.0)
        base = static_scale(row, model['base']) * size(row) * factor
        requested = 1.0
        if len(recent) >= online['minimum_mature_outcomes']:
            requested = quantile_correction(recent, q, online['prior_mass'])
        if model['spec']['local'] and len(subgroup) >= model['local_minimum']:
            empirical = weighted_quantile([(p['ratio'], 1) for p in subgroup], q)
            weight = len(subgroup) / (len(subgroup) + model['local_prior_mass'])
            requested = math.exp(weight * math.log(empirical) + (1 - weight) * math.log(requested))
        requested = min(online['maximum_correction'], max(online['minimum_correction'], requested))
        step = online['maximum_step_fraction']
        correction = min(correction * (1 + step), max(correction * (1 - step), requested))
        raw = max(1, math.ceil(base * correction))
        width = min(raw, model['maximum_width_ppm'])
        leaf = model['activity_scales'].get(state, {})
        predicted_floor = leaf.get('balanced_floor_survival', 0)
        floor_reason = ''
        gate = model['gate']
        if (leaf.get('training_windows', 0) >= gate['training_minimum'] and leaf.get('training_periods', 0) >= gate['training_periods']
                and predicted_floor > q + gate['training_floor_margin']):
            floor_reason = 'training_minimum_width_floor'
        if len(subgroup) >= gate['recent_minimum']:
            recent_floor = mean(p['floor'] for p in subgroup)
            predicted_floor = recent_floor
            if recent_floor > q + gate['recent_floor_margin']:
                floor_reason = 'matured_recent_minimum_width_floor'
        paused = bool(model['spec']['pause'] and floor_reason)
        shadow = row['move'] < row['entry'] * width // 1_000_000 if row['valid'] else None
        output.append(dict(row=row, width_ppm=width, correction=correction, mature_outcomes=len(recent),
                           local_outcomes=len(subgroup), survived=None if paused else shadow,
                           shadow_survived=shadow, capped=raw > model['maximum_width_ppm'],
                           paused=paused, predicted_floor=predicted_floor, floor_reason=floor_reason if paused else ''))
        # Continue learning external reference paths even when no trade is offered.
        pending.append(dict(row=row, base=base, context=key,
                            mature_at=row['expiry'] + online['maturity_delay_ms']))
    return output


def shadow(values):
    return [dict(p, survived=p['shadow_survived']) for p in values]


def availability(values):
    full = [p for p in values if p['shadow_survived'] is not None]
    quoted = sum(p['survived'] is not None for p in full)
    decisions = [p for p in values if p['width_ppm'] is not None]
    return dict(eligible_outcomes=len(full), quoted_outcomes=quoted,
                paused_eligible_outcomes=len(full) - quoted,
                eligible_quote_fraction=quoted / len(full) if full else None,
                pre_entry_predictions=len(decisions), paused_pre_entry_decisions=sum(p['paused'] for p in decisions))


def score(values, q=.48):
    periods = sorted({p['row']['period'] for p in values if p['shadow_survived'] is not None})
    cov = [availability([p for p in values if p['row']['period'] == day])['eligible_quote_fraction'] for day in periods]
    if any(v == 0 for v in cov):
        return 1000.0
    # Coverage loss always costs score; a day below 85% availability costs more.
    penalty = 25 * (1 - mean(cov)) + 100 * max(0, .85 - min(cov))
    return selection_score(values, q) + penalty


def choose(rows, dates, q=.48):
    scores = defaultdict(list)
    folds = []
    for begin, end in ((6, 9), (9, 12), (12, 14)):
        train = [r for r in rows if r['period'] in dates[:begin]]
        later = [r for r in rows if r['period'] in dates[begin:end]]
        baseline_loss = None
        for spec in SPECS:
            values = predict(later, fit(train, spec, q))
            loss = metrics(shadow(values), q)['pinball_ppm']
            if baseline_loss is None:
                baseline_loss = loss
            penalty = 100 * max(0, loss / baseline_loss - 1.1)
            value = score(values, q) + penalty
            scores[spec['name']].append(value)
            folds.append(dict(training_days=begin, scoring_days=dates[begin:end], model=spec['name'],
                              selection_score=value, full_window_pinball_ppm=loss,
                              loss_guard_penalty=penalty, **availability(values)))
    # Prefer earlier/simpler declared candidates for exact ties.
    ranking = sorted((dict(name=s['name'], score=mean(scores[s['name']]), folds=scores[s['name']], index=i)
                      for i, s in enumerate(SPECS)), key=lambda r: (r['score'], r['index']))
    return next(deepcopy(s) for s in SPECS if s['name'] == ranking[0]['name']), ranking, folds


def summary(values, name, q=.48):
    result = []
    for split in dict.fromkeys(p['row']['split'] for p in values):
        part = [p for p in values if p['row']['split'] == split]
        for axis, groups in (('regime', ('all', 'range', 'pump', 'dump', 'mixed')),
                             ('activity', ACTIVITIES)):
            for group in groups:
                group_values = part if group == 'all' else [p for p in part if p['row']['market_regime' if axis == 'regime' else 'activity_state'] == group]
                if not any(p['shadow_survived'] is not None for p in group_values):
                    continue
                result.append(dict(model=name, split=split, axis=axis, group=group,
                                   **metrics(group_values, q), **availability(group_values),
                                   shadow_survival=metrics(shadow(group_values), q)['survival']))
    return result


def report(result):
    chosen = result['selected_spec']['name']
    lines = ['# Flat/bursty oracle activity and pump drift', '',
             '**Retrospective offline research. No live quote changes, no capture started.**', '',
             'New price-change features count distinct changes in the preceding 30/60/300 seconds, time since the last observed change, empty prior 30-second bins, and the fraction of realized variance from the largest step. Unchanged context/heartbeat duplicates do not create price changes. Every feature excludes observations at entry or later, and preserves the original history/outcome eligibility.', '',
             'States: frozen = no observed change for at least 30 seconds; sparse = at least 30% empty prior 30-second bins or at most three changes/minute; bursty = the largest change contributes at least half of five-minute variation; otherwise active. These are recorded-process research labels, not proof that the true upstream oracle was frozen or complete.', '',
             'Eight declared candidates compare the prior phase/rolling rule, activity-specific scales, conditional rolling corrections, wider bounded corrections, pump-specific rolling pools and explicit pauses. All share the previous base phase model. Activity scales use period-balanced quantiles, shrink toward the parent, and require ≥80 windows across ≥3 training periods. Conditional corrections require ≥12 mature subgroup outcomes and shrink toward the global correction. Both original [0.75,4/3] and wider [0.4,2] bounds keep the 2% per-entry correction limit and the original 30-second post-expiry maturity delay.', '',
             'Pause variants refuse an entry only from training or mature-past minimum-width survival evidence: training ≥200 windows over ≥3 periods with floor >target+10pp, or ≥30 mature subgroup windows with floor >target+15pp. These empirical rules do not establish probabilities or statistical confidence. Paused reference windows continue to be observed for calibration. Quotes and full-window shadow results are both reported.', '',
             '## Earlier-period selection', '',
             f"Inner folds inside the original 14 training days selected **{chosen}**. Expanding prefixes of 6/9/12 days score the next 3/3/2. The objective retains daily/directional/worst-period error, adds an explicit availability penalty and a stronger penalty below 85% daily availability, and guards against >10% deterioration in full-window quantile loss. Outer diagnostics and native recordings do not select coefficients or the rule.", '',
             'All periods were inspected in earlier development. Pre-entry causality and inner-fold isolation do not turn repeated retrospective experiments into fresh validation.', '',
             '## Outer comparisons', '',
             '| Slice / regime | Eligible paths | Previous survival | Chosen quoted survival | Chosen shadow survival | Quote availability |',
             '| --- | ---: | ---: | ---: | ---: | ---: |']
    for split in ('validation', 'test'):
        for group in ('all', 'pump', 'dump'):
            cells = {r['model']: r for r in result['summary'] if r['split'] == split and r['axis'] == 'regime' and r['group'] == group}
            c, old = cells[chosen], cells['previous']
            survival = f"{c['survival']:.2%}" if c['survival'] is not None else 'no quotes'
            lines.append(f"| {split} / {group} | {c['eligible_outcomes']} | {old['survival']:.2%} | {survival} | {c['shadow_survival']:.2%} | {c['eligible_quote_fraction']:.2%} |")
    lines += ['', 'All final diagnostic days remain visible:', '',
              '| Period | Previous | Chosen quoted | Chosen shadow | Quote availability | Minimum-width empirical survival |',
              '| --- | ---: | ---: | ---: | ---: | ---: |']
    for r in result['daily']:
        if r['model'] == chosen and r['period'] >= '2026-06-01':
            old = next(v for v in result['daily'] if v['model'] == 'previous' and v['period'] == r['period'])
            survival = f"{r['survival']:.2%}" if r['survival'] is not None else 'no quotes'
            lines.append(f"| {r['period']} | {old['survival']:.2%} | {survival} | {r['shadow_survival']:.2%} | {r['eligible_quote_fraction']:.2%} | {r['floor_survival']:.2%} |")
    lines += ['', '## Native transfer', '',
              'The feature builder verified the native chains/frozen analyzers; archived input hashes are rechecked here. Base coefficients fit historical training only. Mature reference-window outcomes within each native run update the declared correction. The initial learning period remains in the denominator.', '',
              '| Native run | Model | Eligible paths | Quoted survival | Shadow survival | Availability |',
              '| --- | --- | ---: | ---: | ---: | ---: |']
    for r in result['native_summary']:
        if r['model'] in ('previous', chosen) and r['axis'] == 'regime' and r['group'] == 'all':
            survival = f"{r['survival']:.2%}" if r['survival'] is not None else 'no quotes'
            lines.append(f"| {r['run']} | {r['model']} | {r['eligible_outcomes']} | {survival} | {r['shadow_survival']:.2%} | {r['eligible_quote_fraction']:.2%} |")
    lines += ['', '## Limits and decision', '',
              'No readiness decision should rely on quoted-only survival after excluding difficult paths. Daily tables retain all periods, refused entries, full-window shadow outcomes and minimum-width floors. Inspect activity-specific failures and pump rates, including small groups. A conditional empirical floor above the target means narrowing positive corridors alone cannot achieve that target on those observed paths; it is not a forecast guarantee for a new entry.', '',
              'Third-party normalized index snapshots can carry an unchanged value while other fields change. Flatness can reflect the recorded process, true prices or collection/normalization limitations; these files alone do not distinguish those causes. Source sampling, freshness exclusions and dependence remain as in prior reports. No missing interval is interpolated, no receiver pair is fabricated, and native eligibility is unchanged.', '',
              'The target is the legacy 48% reference. The payout product requires multiplier-specific targets and economic validation. Capture reliability/deadline repairs and fresh prospective evidence remain outstanding. No original artifact, live quote or accepted corridor is changed.']
    return '\n'.join(lines) + '\n'


def run(dataset, previous, output, q=.48):
    if output.exists():
        raise ValueError('output exists; never overwrite retained research')
    if not 0 < q < 1:
        raise ValueError('target must be strictly between zero and one')
    rows, source = load(dataset)
    historical = [r for r in rows if r['split'] != 'native']
    native = [r for r in rows if r['split'] == 'native']
    dates = source['dates']
    protocol = dict(dataset=str(dataset.resolve()), dataset_sha256=file_hash(dataset / 'dataset.json'),
                    previous_research_sha256=file_hash(previous / 'research.json'), specs=SPECS,
                    source_sha256={name: file_hash(Path(__file__).with_name(name)) for name in DEPENDENCIES},
                    target_survival=q, selection='Expanding 6/9/12-day training folds within the original first 14 historical days; availability penalty and full-window loss guard',
                    capture_started=False, live_candidate_promoted=False, fresh_prospective_validation=False, production_approved=False)
    output.mkdir(parents=True)
    (output / 'protocol.json').write_text(json.dumps(protocol, indent=2) + '\n')
    (output / 'source').mkdir()
    for name in DEPENDENCIES:
        shutil.copyfile(Path(__file__).with_name(name), output / 'source' / name)
    selected, ranking, folds = choose(historical, dates, q)
    train = [r for r in historical if r['period'] in dates[:14]]
    models = {s['name']: fit(train, s, q) for s in SPECS}
    previous_data = json.loads((previous / 'research.json').read_text())
    comparisons, daily, period_groups, native_summary, predictions = [], [], [], [], {}
    for name, model in models.items():
        values = predict(historical, model)
        predictions[name] = values
        comparisons.extend(summary(values, name, q))
        for period in dates:
            part = [p for p in values if p['row']['period'] == period]
            scored = [p for p in part if p['shadow_survived'] is not None]
            daily.append(dict(model=name, period=period, **metrics(part, q), **availability(part),
                              shadow_survival=metrics(shadow(part), q)['survival'],
                              floor_survival=mean(required_width(p['row']) <= 1 for p in scored)))
            for axis, groups in (('regime', ('pump', 'dump', 'range', 'mixed')), ('activity', ACTIVITIES)):
                for group in groups:
                    values_for_group = [p for p in part if p['row']['market_regime' if axis == 'regime' else 'activity_state'] == group]
                    if any(p['shadow_survived'] is not None for p in values_for_group):
                        period_groups.append(dict(model=name, period=period, axis=axis, group=group,
                                                  **metrics(values_for_group, q), **availability(values_for_group),
                                                  shadow_survival=metrics(shadow(values_for_group), q)['survival']))
    # Exact parity with the previous chosen rule on all three historical slices.
    for split in ('train', 'validation', 'test'):
        a = next(r for r in comparisons if r['model'] == 'previous' and r['axis'] == 'regime' and r['group'] == 'all' and r['split'] == split)
        b = next(r for r in previous_data['summary'] if r['model'] == previous_data['selected_spec']['name'] and r['group'] == 'all' and r['split'] == split)
        if q == previous_data['target_survival'] and (a['windows'], a['survived']) != (b['windows'], b['survived']):
            raise ValueError('previous-rule reconstruction mismatch')
    for period in dict.fromkeys(r['period'] for r in native):
        part = [r for r in native if r['period'] == period]
        for name, model in models.items():
            values = predict(part, model)
            predictions[(period, name)] = values
            native_summary.extend(dict(run=period, **r) for r in summary(values, name, q))
    result = dict(protocol, selected_spec=selected, ranking=ranking, folds=folds,
                  models=models, summary=comparisons, daily=daily, native_summary=native_summary,
                  period_groups=period_groups, native_sources=source['native_sources'])
    selected_outer = [r for r in daily if r['model'] == selected['name'] and r['period'] in dates[14:]]
    result['descriptive_checks'] = dict(
        all_outer_days_within_reference_band=all(r['survival'] is not None and abs(r['error_pp']) <= 5 for r in selected_outer),
        minimum_outer_eligible_quote_availability=min(r['eligible_quote_fraction'] for r in selected_outer),
        selected_outer_mean_daily_error_pp=mean(abs(r['error_pp']) for r in selected_outer if r['survival'] is not None),
        no_prospective_readiness_claim=True)
    if file_hash(dataset / 'dataset.json') != protocol['dataset_sha256'] or file_hash(previous / 'research.json') != protocol['previous_research_sha256']:
        raise ValueError('retained source metadata changed during analysis')
    (output / 'research.json').write_text(json.dumps(result, indent=2) + '\n')
    for filename, part in (('summary', comparisons), ('daily', daily), ('period-groups', period_groups), ('folds', folds), ('native', native_summary)):
        if part:
            write_csv(output / (filename + '.csv'), part, list(part[0]))
    with (output / 'predictions.csv').open('x', newline='') as stream:
        fields = ['source', 'model', 'start', 'split', 'regime', 'activity', 'valid', 'width_ppm',
                  'survived', 'shadow_survived', 'paused', 'floor_reason', 'predicted_floor',
                  'correction', 'mature_outcomes', 'local_outcomes', 'capped']
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for key, part in predictions.items():
            name = key[1] if isinstance(key, tuple) else key
            for p in part:
                r = p['row']
                writer.writerow(dict(source=r['period'], model=name, start=r['start'], split=r['split'],
                                     regime=r['market_regime'], activity=r['activity_state'], valid=r['valid'],
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
    selected = result['selected_spec']['name']
    print(json.dumps(dict(selected=selected, ranking=result['ranking'],
                          summary=[r for r in result['summary'] if r['model'] in ('previous', selected) and r['axis'] == 'regime' and r['split'] != 'train'],
                          daily=[r for r in result['daily'] if r['model'] == selected and r['period'] >= '2026-06-01']), indent=2))


if __name__ == '__main__':
    main()
