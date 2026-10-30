#!/usr/bin/env python3
"""Reconcile pre-entry decisions, delayed reference learning and payout metrics."""
import argparse
from collections import defaultdict
import csv
import gzip
import json
import math
from pathlib import Path

import numpy as np

from payout_risk import LEVELS, SPEC, VARIANTS, features, weekend
from research_payout_risk import MULTIPLIERS, digest, dump, load_parent


def close(a, b):
    if a is None or b is None:
        if a is not b:
            raise ValueError('missing numeric value differs')
    elif not math.isclose(float(a), float(b), rel_tol=1e-9, abs_tol=1e-10):
        raise ValueError(f'numeric audit differs: {a} versus {b}')


def width_needed(row):
    return -(-((row['move']+1)*1000000)//row['entry'])


def point(row, model):
    return [1.]+[min(5., max(-5., (value-center)/sd))
                 for value, center, sd in zip(features(row, model['family']), model['center'], model['sd'])]


def manual_risk(row, model):
    if row['adaptive_features'] is None:
        return None, None
    x = point(row, model)
    probabilities = []
    for key in ('zero_coefficients', 'floor_coefficients'):
        logit = min(30., max(-30., sum(a*b for a, b in zip(x, model[key]))))
        probabilities.append(1/(1+math.exp(-logit)))
    return probabilities[0], max(probabilities)


def reference_forecasts(rows, model):
    """Prefix-sum reconstruction, independent of the model's queue implementation."""
    static = [manual_risk(r, model) for r in rows]
    output = {False: [], True: []}
    for day in sorted({r['period'] for r in rows}):
        ids = [i for i, r in enumerate(rows) if r['period'] == day]
        eligible = [i for i in ids if rows[i]['valid'] and static[i][0] is not None]
        maturities = np.asarray([rows[i]['expiry']+30000 for i in eligible])
        expiries = np.asarray([rows[i]['expiry'] for i in eligible])
        sums = [np.concatenate(([0.], np.cumsum(v))) for v in (
            [rows[i]['move'] == 0 for i in eligible], [width_needed(rows[i]) <= 1 for i in eligible],
            [static[i][0] for i in eligible], [static[i][1] for i in eligible])]
        for i in ids:
            at = rows[i]['start']; p0, pf = static[i]
            end = int(np.searchsorted(maturities, at, side='right'))
            begin = max(0, end-240, int(np.searchsorted(expiries, at-14400000, side='left')))
            count = max(0, end-begin)
            for online in (False, True):
                a, b = p0, pf
                if online and count and a is not None:
                    observed0, observedf, expected0, expectedf = (s[end]-s[begin] for s in sums)
                    def adjusted(prob, actual, expected):
                        ratio = min(10., max(.1, (1+actual)/(1+expected)))
                        return ratio*prob/(1-prob+ratio*prob)
                    a, b = adjusted(a, observed0, expected0), adjusted(b, observedf, expectedf)
                    b = max(a, b)
                output[online].append(dict(p0=a, floor=b, base_p0=p0, base_floor=pf, mature=count))
    return output


def proper_loss(rows, forecasts):
    part = [(r, p) for r, p in zip(rows, forecasts) if r['valid'] and p['floor'] is not None]
    n = len(part); output = dict(n=n)
    for name, key, label in (('zero', 'p0', lambda r: r['move'] == 0),
                             ('floor', 'floor', lambda r: width_needed(r) <= 1)):
        values = [(float(label(r)), max(1e-12, min(1-1e-12, p[key]))) for r, p in part]
        output.update({name+'_predicted': sum(p for _, p in values)/n if n else None,
            name+'_observed': sum(y for y, _ in values)/n if n else None,
            name+'_brier': sum((y-p)**2 for y, p in values)/n if n else None,
            name+'_log_loss': sum(-y*math.log(p)-(1-y)*math.log(1-p) for y, p in values)/n if n else None})
    return output


def manual_positive(row, p, model, q):
    if p['floor'] is None:
        return None, None, 0., False
    level = (q-p['floor'])/(1-p['floor'])
    mass = model['fitted_windows']*max(0, level)
    supported = LEVELS[0] <= level <= LEVELS[-1] and mass >= 20
    if level < LEVELS[0]:
        return 1, level, mass, False
    x = point(row, model)
    logs = sorted(sum(a*b for a, b in zip(x, coefs)) for coefs in model['coefficients'])
    value = math.log(max(1, row['adaptive_features']['vol_300_ppm'])) + float(np.interp(level, model['levels'], logs))
    w = math.ceil(math.exp(min(math.log(50000), max(math.log(2), value))))
    return w, level, mass, supported


def audit_asset(asset, all_rows, baseline, directory):
    metadata = json.loads((directory/'research.json').read_text())
    for name, sha in metadata['artifact_sha256'].items():
        if digest(directory/name) != sha:
            raise ValueError('asset artifact differs: '+name)
    models = json.loads((directory/'models.json').read_text())
    selection = json.loads((directory/'selection.json').read_text())
    train = [r for r in all_rows if r['split'] == 'train' and r['valid'] and r['adaptive_features'] is not None]
    if any(r['asset'] != asset or r['period'] >= '2026-01-01' for r in train):
        raise ValueError('asset or training period contamination')
    cutoff = 1767225600000  # 2026-01-01 00:00:00 UTC.
    if any(r['expiry']+30000 >= cutoff for r in train):
        raise ValueError('training label crosses cutoff')
    expected_dates = sorted({r['period'] for r in train})
    for model in models['candidates'].values():
        if model['asset'] != asset or model['training_dates'] != expected_dates or model['windows'] != len(train):
            raise ValueError('training model binding differs')
        if model['zero_windows'] != sum(r['move'] == 0 for r in train) or model['floor_windows'] != sum(width_needed(r) <= 1 for r in train):
            raise ValueError('risk label counts differ')
    positive = models['positive']
    count = sum(width_needed(r) > 1 for r in train)
    if positive['asset'] != asset or positive['fitted_windows'] != count or positive['training_dates'] != expected_dates:
        raise ValueError('positive model training binding differs')
    later = [r for r in all_rows if r['split'] != 'train']
    selected = models['selected']; forecasts = reference_forecasts(later, models['candidates'][selected])
    candidate_forecasts = {}
    ranking = []
    for order, (name, model) in enumerate(models['candidates'].items()):
        values = [dict(zip(('p0', 'floor'), manual_risk(r, model))) for r in later]
        candidate_forecasts[name] = values
        losses = []
        for day in sorted({r['period'] for r in later if r['split'] == 'validation'}):
            ids = [i for i, r in enumerate(later) if r['period'] == day]
            metric = proper_loss([later[i] for i in ids], [values[i] for i in ids])
            losses.append((metric['zero_log_loss']+metric['floor_log_loss'])/2)
        ranking.append((sum(losses)/len(losses), order, name))
    ranking.sort()
    if ranking[0][2] != selected or selected != metadata['selected_risk'] or selected != selection['selected']:
        raise ValueError('risk selection differs')
    for actual, saved in zip(ranking, selection['ranking']):
        if actual[2] != saved['name']:
            raise ValueError('risk ranking differs')
        close(actual[0], saved['score'])

    with (directory/'risk-metrics.csv').open() as stream:
        seen = set()
        for metric in csv.DictReader(stream):
            key = tuple(metric[k] for k in ('candidate', 'period', 'split', 'mode'))
            if key in seen:
                raise ValueError('duplicate risk diagnostic')
            seen.add(key)
            if metric['candidate'] == 'constant_training_rate':
                m = models['candidates'][selected]
                values = [dict(p0=m['period_balanced_zero'], floor=m['period_balanced_floor']) if r['adaptive_features'] is not None else dict(p0=None, floor=None) for r in later]
            else:
                values = forecasts[True] if metric['mode'] == 'online' else candidate_forecasts[metric['candidate']]
            ids = [i for i, r in enumerate(later) if r['split'] == metric['split'] and (metric['period'] == 'pooled' or r['period'] == metric['period'])]
            actual = proper_loss([later[i] for i in ids], [values[i] for i in ids])
            for field, value in actual.items():
                close(float(metric[field]) if metric[field] else None, value)

    buckets = defaultdict(lambda: [0.]*14)
    total = 0
    expected = ((m, variant, i, r) for m in MULTIPLIERS for variant in VARIANTS for i, r in enumerate(later))
    with gzip.open(directory/'predictions.jsonl.gz', 'rt') as stream:
        for multiplier, variant, i, row in expected:
            line = stream.readline()
            if not line:
                raise ValueError('trace ends early')
            saved = json.loads(line); total += 1
            name, source, online, fraction, weekdays = variant
            if (saved['asset'], saved['multiplier'], saved['variant'], saved['start']) != (asset, multiplier, name, row['start']):
                raise ValueError('trace grid or asset binding differs')
            p = forecasts[online][i]
            for field, value in p.items():
                close(saved[field], value)
            conditional, level, mass, supported = manual_positive(row, p, positive, .95/multiplier)
            close(saved['positive_q'], level); close(saved['tail_mass'], mass)
            if supported != saved['tail_supported']:
                raise ValueError('tail support differs')
            width = baseline[multiplier][row['start']] if source == 'parent' else conditional
            reasons = []
            if width is None: reasons.append('missing_history')
            if weekdays and weekend(row): reasons.append('weekend_control')
            if fraction is not None and p['floor'] is not None and p['floor'] > fraction*.95/multiplier:
                reasons.append('predicted_minimum_width_risk')
            if fraction is not None and source == 'conditional' and width is not None and not supported:
                reasons.append('insufficient_positive_tail_support')
            if width is not None and row['entry'] is not None and row['entry']*width//1000000 <= 0:
                reasons.append('unrepresentable_barrier')
            offered = not reasons
            shadow = row['move'] < row['entry']*width//1000000 if row['valid'] and width is not None else None
            outcome = shadow if offered else None
            if (saved['width'], saved['offered'], saved['shadow'], saved['survived'], saved['reason']) != (width, offered, shadow, outcome, ';'.join(reasons)):
                raise ValueError('decision, barrier outcome or refusal differs')
            for period in ('pooled', row['period']):
                for axis, group in (('overall','all'), ('activity_state',row['activity_state']),
                                     ('market_regime',row['market_regime']), ('calendar','weekend' if weekend(row) else 'weekday')):
                    b = buckets[multiplier, name, row['split'], period, axis, group]
                    b[0] += 1; b[1] += width is not None; b[2] += offered
                    if shadow is not None:
                        b[3] += 1; b[6] += shadow
                        if offered:
                            b[4] += 1; b[5] += outcome; b[7] += width
                            b[8] += row['move'] == 0 and outcome
                            b[9] += width_needed(row) <= 1 and outcome
                            b[10] += p['floor']; b[11] += width_needed(row) <= 1
        if stream.readline():
            raise ValueError('unexpected extra trace rows')
    with (directory/'metrics.csv').open() as stream:
        csv_rows = 0
        for metric in csv.DictReader(stream):
            key = (int(metric['multiplier']), *(metric[k] for k in ('variant','split','period','axis','group')))
            b = buckets[key]; n, k, wins = b[3], b[4], b[5]
            q = .95/key[0]
            values = dict(grid=b[0], pre_entry_predictions=b[1], pre_entry_offered=b[2], eligible=n, offered=k,
                          wins=wins, shadow_wins=b[6], zero_wins=b[8], minimum_width_wins=b[9],
                          availability=k/n if n else None, survival=wins/k if k else None,
                          shadow_survival=b[6]/n if n else None, target=q,
                          survival_to_target=wins/k/q if k else None,
                          gross_equal_stake_return=1-key[0]*wins/k if k else None,
                          mean_width_ppm=b[7]/k if k else None, predicted_floor_mean=b[10]/k if k else None,
                          realized_floor=b[11]/k if k else None, target_expected_wins=k*q)
            for field, value in values.items():
                close(float(metric[field]) if metric[field] else None, value)
            if (metric['at_least_20_target_expected_wins'] == 'True') != (k*q >= 20):
                raise ValueError('rare-event evidence screen differs')
            csv_rows += 1
    return dict(asset=asset, trace_rows=total, metric_rows=csv_rows, selected_risk=selected,
                risk_models_checked=len(models['candidates']), decisions_reconstructed=True,
                reference_learning_reconstructed=True, all_positive_training_rows=count)


def audit(root):
    result = json.loads((root/'research.json').read_text())
    if digest(root/'protocol.json') != result['protocol_sha256']:
        raise ValueError('research declaration differs')
    for name, sha in result['protocol']['source_sha256'].items():
        if digest(root/'source'/name) != sha:
            raise ValueError('frozen source differs')
    parent = Path(result['protocol']['parent'])
    rows, baseline, bindings = load_parent(parent)
    if bindings != result['bindings']:
        raise ValueError('parent bindings differ')
    reports = []
    for asset in ('ETH','HYPE'):
        if digest(root/asset/'research.json') != result['research_sha256'][asset]:
            raise ValueError('asset research differs')
        reports.append(audit_asset(asset, rows[asset], baseline[asset], root/asset))
    report = dict(passed=True, research_sha256=digest(root/'research.json'), assets=reports,
                  raw_payloads_verified=bindings['raw_payloads_verified'], auditor_sha256=digest(Path(__file__)))
    dump(root/'audit.json', report)
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--research', type=Path, required=True)
    print(json.dumps(audit(parser.parse_args().research), indent=2))
