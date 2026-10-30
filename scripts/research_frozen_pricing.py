#!/usr/bin/env python3
"""Frozen-entry pricing research, keeping the retained pause mask fixed."""
import argparse
from collections import defaultdict, deque
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
from research_activity_calibration import fit, metrics, predict, score, shadow
from research_flat_pause import (DEPENDENCIES as PAUSE_DEPENDENCIES, ENGINE_SPEC,
                                 SPECS as PAUSES, apply_pause, diagnostics)
from stabilize_adaptive_corridor import balanced_weights


def spec(name, *, static=False, memory=0, offered=True, idle=False, prior=30, step=.02, hurdle=False, clock=False):
    return dict(name=name, static=static, memory=memory, offered_only=offered,
                idle_groups=idle, prior_mass=prior, step=step, minimum=12, hurdle=hurdle, entry_clock=clock)


SPECS = (
    spec('baseline'),
    spec('frozen_static', static=True),
    spec('all_frozen_120', static=True, memory=120, offered=False),
    spec('offered_frozen_120', static=True, memory=120),
    spec('offered_frozen_60', static=True, memory=60),
    spec('offered_frozen_30', static=True, memory=30),
    spec('offered_idle_120', static=True, memory=120, idle=True),
    spec('offered_frozen_60_fast', static=True, memory=60, prior=12, step=.05),
    spec('hurdle_all_120', memory=120, offered=False, prior=12, hurdle=True),
    spec('hurdle_all_120_fast', memory=120, offered=False, prior=12, step=.05, hurdle=True),
    spec('hurdle_offered_120_fast', memory=120, prior=12, step=.05, hurdle=True),
    spec('hurdle_all_60_fast', memory=60, offered=False, prior=12, step=.05, hurdle=True),
    spec('hurdle_all_120_clock', memory=120, offered=False, prior=12, hurdle=True, clock=True),
    spec('hurdle_offered_120_clock', memory=120, prior=12, hurdle=True, clock=True),
    spec('offered_frozen_60_clock', static=True, memory=60, clock=True),
    spec('all_frozen_120_clock', static=True, memory=120, offered=False, clock=True),
)
PAUSE = next(s for s in PAUSES if s['name'] == 'frozen_floor_53')
DEPENDENCIES = ('research_frozen_pricing.py',) + PAUSE_DEPENDENCIES


def fit_overlay(values, candidate, q=.48):
    part = [p for p in values if p['row']['activity_state'] == 'frozen'
            and p['survived'] is not None]
    periods = len({p['row']['period'] for p in part})
    factor = 1.0
    if candidate['static'] and len(part) >= 80 and periods >= 3:
        weights = balanced_weights([p['row'] for p in part])
        raw = weighted_quantile([(required_width(p['row']) / p['width_ppm'], w)
                                 for p, w in zip(part, weights)], q)
        factor = math.exp(len(part) / (len(part) + 200) * math.log(raw))
    weights = balanced_weights([p['row'] for p in part]) if part else []
    floor = sum(w * (required_width(p['row']) <= 1) for p, w in zip(part, weights)) / sum(weights) if weights else 0
    positive = [(required_width(p['row']) / p['width_ppm'], w)
                for p, w in zip(part, weights) if required_width(p['row']) > 1]
    return dict(spec=candidate, training_windows=len(part), training_periods=periods,
                training_floor=floor, training_positive_ratios=positive if candidate.get('hurdle') else [],
                static_factor=factor, target_survival=q, minimum_correction=.05 if candidate.get('hurdle') else .25,
                maximum_correction=2.0, maximum_width_ppm=50_000,
                maximum_age_ms=4 * 3_600_000, maturity_delay_ms=30_000)


def reprice(values, model):
    """All-floor evidence stays in the original engine; this pool prices entries.

    Offered-only means the entry-time pause mask, not whether a trader entered or
    whether the path survived. Reference eligibility/outcomes are read at maturity.
    Non-frozen widths and every entry pause remain bit-for-bit unchanged.
    """
    s = model['spec']
    if s['name'] == 'baseline':
        return [dict(p, baseline_width_ppm=p['width_ppm'], frozen_correction=1.0,
                     frozen_mature_outcomes=0) for p in values]
    pending, pool, local = deque(), deque(), defaultdict(deque)
    corrections = defaultdict(lambda: 1.0)
    output, session, previous = [], None, None
    for p in values:
        r, at = p['row'], p['row']['start']
        if previous is not None and at < previous:
            raise ValueError('chronological predictions required')
        previous = at
        if session != r['period']:
            session = r['period']
            pending.clear(); pool.clear(); local.clear(); corrections.clear()
        while pending and pending[0]['mature_at'] <= at:
            past = pending.popleft()
            if past['row']['valid'] and (past['offered'] or not s['offered_only']):
                item = dict(expiry=past['row']['expiry'],
                            ratio=required_width(past['row']) / past['base'],
                            floor=required_width(past['row']) <= 1)
                pool.append(item)
                local[past['context']].append(item)
        for part in [pool] + list(local.values()):
            while part and (len(part) > s['memory'] or at - part[0]['expiry'] > model['maximum_age_ms']):
                part.popleft()
        frozen_entry = r['activity_state'] == 'frozen'
        if p['width_ppm'] is None or (not frozen_entry and not s.get('entry_clock')):
            output.append(dict(p, baseline_width_ppm=p['width_ppm'], frozen_correction=None,
                               frozen_mature_outcomes=len(pool)))
            continue
        key = 'long_idle' if s['idle_groups'] and r['activity_features']['idle_ms'] >= 60_000 else 'frozen'
        base = p['width_ppm'] * model['static_factor']
        requested = 1.0
        floor_estimate = None
        if s.get('hurdle') and len(pool) >= s['minimum']:
            # Mixture F(w) = p_floor + (1-p_floor)*F_positive(w), for w>=1.
            # Shrink both components toward training, using a fixed pseudo-count.
            prior = s['prior_mass']
            floor_estimate = (sum(item['floor'] for item in pool) + prior * model['training_floor']) / (len(pool) + prior)
            if floor_estimate >= model['target_survival']:
                requested = 1 / base
            else:
                positive_q = (model['target_survival'] - floor_estimate) / (1 - floor_estimate)
                positive = [(item['ratio'], 1) for item in pool if not item['floor']]
                trained = model['training_positive_ratios']
                mass = sum(weight for _, weight in trained)
                if mass:
                    positive += [(ratio, weight / mass * prior * (1 - model['training_floor']))
                                 for ratio, weight in trained]
                if positive:
                    requested = weighted_quantile(positive, positive_q)
        elif s['memory'] and len(pool) >= s['minimum']:
            empirical = weighted_quantile([(item['ratio'], 1) for item in pool], model['target_survival'])
            requested = math.exp(len(pool) / (len(pool) + s['prior_mass']) * math.log(empirical))
        if s['memory'] and s['idle_groups'] and len(local[key]) >= s['minimum']:
            empirical = weighted_quantile([(item['ratio'], 1) for item in local[key]], model['target_survival'])
            weight = len(local[key]) / (len(local[key]) + s['prior_mass'])
            requested = math.exp(weight * math.log(empirical) + (1 - weight) * math.log(requested))
        requested = max(model['minimum_correction'], min(model['maximum_correction'], requested))
        last = corrections[key]
        factor = min(last * (1 + s['step']), max(last * (1 - s['step']), requested))
        corrections[key] = factor
        if not frozen_entry:
            output.append(dict(p, baseline_width_ppm=p['width_ppm'], frozen_correction=factor,
                               frozen_mature_outcomes=len(pool), frozen_floor_estimate=floor_estimate))
            continue
        raw = max(1, math.ceil(base * factor))
        width = min(model['maximum_width_ppm'], raw)
        survived = r['move'] < r['entry'] * width // 1_000_000 if r['valid'] else None
        output.append(dict(p, width_ppm=width, baseline_width_ppm=p['width_ppm'],
                           frozen_correction=factor, frozen_mature_outcomes=len(pool),
                           frozen_floor_estimate=floor_estimate,
                           shadow_survived=survived, survived=None if p['paused'] else survived,
                           capped=raw > model['maximum_width_ppm']))
        if s['memory']:
            pending.append(dict(row=r, base=base, context=key, offered=not p['paused'],
                                mature_at=r['expiry'] + model['maturity_delay_ms']))
    return output


def frozen_score(values, q=.48):
    errors = []
    for day in dict.fromkeys(p['row']['period'] for p in values):
        part = [p for p in values if p['row']['period'] == day and p['row']['activity_state'] == 'frozen']
        m = metrics(part, q)
        if m['windows'] >= 20:
            errors.append(abs(m['error_pp']))
    return score(values, q) + (mean(errors) + .25 * max(errors) if errors else 0)


def choose(rows, dates, q=.48):
    scores, folds = defaultdict(list), []
    for begin, end in ((6, 9), (9, 12), (12, 14)):
        train = [r for r in rows if r['period'] in dates[:begin]]
        later = [r for r in rows if r['period'] in dates[begin:end]]
        engine = fit(train, ENGINE_SPEC, q)
        train_values = apply_pause(predict(train, engine), PAUSE)
        later_values = apply_pause(predict(later, engine), PAUSE)
        old_loss = metrics(shadow(later_values), q)['pinball_ppm']
        for candidate in SPECS:
            values = reprice(later_values, fit_overlay(train_values, candidate, q))
            loss = metrics(shadow(values), q)['pinball_ppm']
            penalty = (100 * max(0, loss / old_loss - 1.1) if old_loss
                       else 100.0 if loss else 0.0)
            value = frozen_score(values, q) + penalty
            scores[candidate['name']].append(value)
            folds.append(dict(model=candidate['name'], training_days=begin,
                              scoring_days=dates[begin:end], score=value, loss_guard_penalty=penalty,
                              **diagnostics(values, q)))
    ranking = sorted((dict(name=s['name'], score=mean(scores[s['name']]),
                           folds=scores[s['name']], index=i) for i, s in enumerate(SPECS)),
                     key=lambda r: (r['score'], r['index']))
    return next(s for s in SPECS if s['name'] == ranking[0]['name']), ranking, folds


def tables(values, name, q=.48):
    daily, groups = [], []
    for period in dict.fromkeys(p['row']['period'] for p in values):
        part = [p for p in values if p['row']['period'] == period]
        daily.append(dict(model=name, period=period, split=part[0]['row']['split'], **diagnostics(part, q)))
        for axis, kinds in (('activity_state', ('active', 'bursty', 'sparse', 'frozen')),
                            ('market_regime', ('range', 'pump', 'dump', 'mixed'))):
            for kind in kinds:
                cell = [p for p in part if p['row'][axis] == kind]
                if any(p['shadow_survived'] is not None for p in cell):
                    groups.append(dict(model=name, period=period, split=part[0]['row']['split'],
                                       axis=axis, group=kind, **diagnostics(cell, q)))
    return daily, groups


def run(dataset, previous, pause_research, output):
    if output.exists():
        raise ValueError('output exists; preserve retained experiments')
    rows, source = load(dataset)
    old = json.loads((previous / 'research.json').read_text())
    for name, digest in old['source_sha256'].items():
        if file_hash(previous / 'source' / name) != digest or file_hash(Path(__file__).with_name(name)) != digest:
            raise ValueError('retained pricing engine source differs')
    if old['dataset_sha256'] != file_hash(dataset / 'dataset.json'):
        raise ValueError('dataset differs from retained pricing engine')
    pause_old = json.loads((pause_research / 'research.json').read_text())
    for name, digest in pause_old['source_sha256'].items():
        if file_hash(pause_research / 'source' / name) != digest or file_hash(Path(__file__).with_name(name)) != digest:
            raise ValueError('retained pause engine source differs')
    q, dates = old['target_survival'], source['dates']
    protocol = dict(dataset=str(dataset.resolve()), dataset_sha256=file_hash(dataset / 'dataset.json'),
                    previous=str(previous.resolve()), previous_sha256=file_hash(previous / 'research.json'),
                    pause_research=str(pause_research.resolve()), pause_sha256=file_hash(pause_research / 'research.json'),
                    source_sha256={n: file_hash(Path(__file__).with_name(n)) for n in DEPENDENCIES},
                    specs=SPECS, pause=PAUSE, dates=dates, target_survival=q,
                    selection='Earlier 6/9/12 prefixes; previous overall objective plus mean/worst frozen-day error for >=20 offered paths; 10% full-loss guard; declaration order breaks ties',
                    additional_raw_samples_used_for_selection=False, capture_started=False,
                    live_candidate_promoted=False, production_approved=False, fresh_validation=False)
    output.mkdir(parents=True)
    (output / 'protocol.json').write_text(json.dumps(protocol, indent=2) + '\n')
    (output / 'source').mkdir()
    for name in DEPENDENCIES:
        shutil.copyfile(Path(__file__).with_name(name), output / 'source' / name)
    historical = [r for r in rows if r['split'] != 'native']
    native = [r for r in rows if r['split'] == 'native']
    chosen, ranking, folds = choose(historical, dates, q)
    engine = old['models'][ENGINE_SPEC['name']]
    hist_base = apply_pause(predict(historical, engine), PAUSE)
    baseline = hist_base + apply_pause(predict(native, engine), PAUSE)
    training = [p for p in hist_base if p['row']['period'] in dates[:14]]
    models = {s['name']: fit_overlay(training, s, q) for s in SPECS}
    daily, groups, comparisons = [], [], []
    with (output / 'predictions.csv').open('x', newline='') as stream:
        fields = ['model', 'period', 'start', 'split', 'activity', 'paused', 'survived',
                  'shadow_survived', 'width_ppm', 'baseline_width_ppm', 'frozen_correction',
                  'frozen_mature_outcomes']
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for name, model in models.items():
            values = reprice(baseline, model)
            if any(p['paused'] != b['paused'] or (b['row']['activity_state'] != 'frozen' and p['width_ppm'] != b['width_ppm'])
                   for p, b in zip(values, baseline)):
                raise ValueError('pricing overlay changed pauses or non-frozen quotes')
            d, g = tables(values, name, q)
            daily.extend(d); groups.extend(g)
            for split in ('train', 'validation', 'test', 'native'):
                part = [p for p in values if p['row']['split'] == split]
                for activity in ('all', 'frozen'):
                    cell = part if activity == 'all' else [p for p in part if p['row']['activity_state'] == activity]
                    comparisons.append(dict(model=name, split=split, activity=activity, **diagnostics(cell, q)))
            for p in values:
                r = p['row']
                writer.writerow(dict(model=name, period=r['period'], start=r['start'], split=r['split'],
                                     activity=r['activity_state'], **{k: p[k] for k in fields[5:]}))
    for r in daily:
        if r['model'] == 'baseline':
            oldrow = next(v for v in pause_old['daily'] if v['model'] == PAUSE['name'] and v['period'] == r['period'])
            for key in ('windows', 'survived', 'quoted_outcomes', 'paused_eligible_outcomes'):
                if r[key] != oldrow[key]:
                    raise ValueError('retained frozen-floor baseline differs')
    result = dict(protocol, frozen_engine=engine, selected_spec=chosen, ranking=ranking,
                  folds=folds, models=models, daily=daily, period_groups=groups, summary=comparisons,
                  checks=dict(pauses_identical=True, non_frozen_widths_identical=True,
                              previous_pause_baseline_exact=True))
    (output / 'research.json').write_text(json.dumps(result, indent=2) + '\n')
    for name, part in (('daily', daily), ('period-groups', groups), ('summary', comparisons), ('folds', folds)):
        write_csv(output / (name + '.csv'), part, list(part[0]))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset', type=Path, required=True)
    parser.add_argument('--previous', type=Path, required=True)
    parser.add_argument('--pause-research', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = run(args.dataset, args.previous, args.pause_research, args.output)
    print(json.dumps(dict(selected=result['selected_spec'], ranking=result['ranking'], models=result['models'],
                          august=[r for r in result['period_groups'] if r['period'] == '2026-08-01' and r['group'] == 'frozen']), indent=2))


if __name__ == '__main__':
    main()
