#!/usr/bin/env python3
"""Offline descriptive coverage for a hash-verified prospective receipt capture.

Regime labels and autocorrelation ESS are diagnostics, never launch approval.
This does not evaluate trading strategies or independent upstream correctness.
"""
import argparse
import json
import time
from pathlib import Path
import subprocess
from collections import Counter
from decimal import Decimal

ROOT = Path(__file__).resolve().parent.parent


def effective_size(values):
    n = len(values)
    if not n:
        return 0.0
    mean = sum(values) / n
    variance = sum((x-mean)**2 for x in values)
    if not variance:
        return 1.0  # Constant outcomes cannot establish independent tail evidence.
    if n < 3:
        return float(n)
    correlations = []
    for lag in range(1, min(100, n//4)+1):
        rho = sum((values[i]-mean)*(values[i-lag]-mean) for i in range(lag, n)) / variance
        if rho <= 0:
            break
        correlations.append(rho)
    return max(1.0, n/(1+2*sum(correlations)))


def windows(receipts, policy, start_ms=None, end_ms=None):
    feeds, mismatch, current, window = {}, None, None, None
    if start_ms is not None:
        window = dict(start=start_ms, expiry=start_ms+30000, entry=None,
                      last=None, move=0, step=0, valid=False)
    def healthy(at):
        return len(feeds) == 2 and all(0 <= at-v[0] <= policy['max_gap_ms'] for v in feeds.values()) and feeds['a'][1] == feeds['b'][1]
    def gap(at):
        return len(feeds) < 2 or any(at-v[0] > policy['max_gap_ms'] for v in feeds.values()) or (mismatch is not None and at-mismatch >= policy['disagreement_ms'])
    for record in receipts:
        at, source = record['at'], record['source']
        # Just as in the reducer, the prior receipt state adjudicates expiry.
        if window is not None:
            while at >= window['expiry']:
                window['valid'] &= not gap(window['expiry']) and healthy(window['expiry'])
                yield window
                boundary = window['expiry']
                window = dict(start=boundary, expiry=boundary+30000, entry=current,
                              last=current, move=0, step=0, valid=healthy(boundary))
            window['valid'] &= not gap(at)
        price = int(Decimal(record['raw']['data']['ctx']['oraclePx'])*1_000_000)
        feeds[source] = (at, price)
        if len(feeds) == 2 and feeds['a'][1] != feeds['b'][1]:
            if mismatch is None:
                mismatch = at
        else:
            mismatch = None
        if not healthy(at):
            continue
        current = price
        if window is None:
            window = dict(start=at, expiry=at+30000, entry=price,
                          last=price, move=0, step=0, valid=True)
        if window['entry'] is None:
            continue
        window['move'] = max(window['move'], abs(price-window['entry']))
        window['step'] = max(window['step'], abs(price-window['last']))
        window['last'] = price
    # A declared horizon includes unobserved initial and terminal outages.
    # This advances health only; it never invents a price or fills an outage.
    while window is not None and end_ms is not None and window['expiry'] <= end_ms:
        window['valid'] &= not gap(window['expiry']) and healthy(window['expiry'])
        yield window
        boundary = window['expiry']
        window = dict(start=boundary, expiry=boundary+30000, entry=current,
                      last=current, move=0, step=0, valid=healthy(boundary))
    # Partial windows are excluded; no synthetic terminal price.


def describe(rows, width_ppm):
    counts, outcomes, regimes = Counter(), [], {}
    total = 0
    for row in rows:
        total += 1
        if not row['valid']:
            counts['censored'] += 1
            continue
        delta = row['entry']*width_ppm//1_000_000
        if delta <= 0:
            raise ValueError('rounded corridor is zero')
        if row['move'] == 0:
            regime = 'flat_oracle'
        elif row['step'] >= delta:
            regime = 'jumping'
        elif row['move'] >= delta:
            regime = 'volatile'
        elif abs(row['last']-row['entry'])*2 >= delta:
            regime = 'trending'
        else:
            regime = 'quiet'
        survived = int(row['move'] < delta)
        counts[regime] += 1
        outcomes.append(survived)
        regimes.setdefault(regime, []).append(survived)
    return {'completed_windows': total, 'healthy_windows': len(outcomes),
            'coverage': len(outcomes)/total if total else 0,
            'regime_windows': dict(counts), 'survived_windows': sum(outcomes),
            'descriptive_effective_windows': effective_size(outcomes),
            'descriptive_regime_effective_windows': {k: effective_size(v) for k, v in regimes.items()},
            'research_minimum_met': len(outcomes) >= 400,
            'production_approved': False,
            'limits': 'Regimes are descriptive corridor-relative labels, not approved market classifications. ESS uses initial positive autocorrelations through lag min(100,n/4), ignores dependence across censored windows and is not a safety bound. No strategy, demand or cost evidence.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    parser.add_argument('--verifier', type=Path, required=True, help='built fuse-capture binary; verifies the frozen hash chain before analysis')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    verified = json.loads(subprocess.check_output([str(args.verifier.resolve()), '-verify', '-output', str(args.directory.resolve())], text=True))
    manifest, head = verified['manifest'], verified['head']
    policy = manifest['policy']
    width = policy['model'].get('base_width_ppm', 0)
    if width <= 0:
        parser.error('coverage analysis requires a frozen fixed fractional-width policy')
    last = [None]
    def receipts():
        with (args.directory/'receipts.jsonl').open() as stream:
            for line in stream:
                last[0] = json.loads(line)
                yield last[0]
    end_ms = manifest['frozen_at_ms']+manifest['duration_ms']
    result = describe(windows(receipts(), policy, manifest['frozen_at_ms'], end_ms), width)
    if (last[0] or {}).get('hash') != head['hash']:
        raise ValueError('capture changed after verification; stop recording before analysis')
    result.update(collection_deadline_elapsed=time.time_ns()//1_000_000 >= end_ms,
                  frozen_at_ms=manifest['frozen_at_ms'], receipt_hash=head['hash'],
                  planned_end_ms=manifest['frozen_at_ms']+manifest['duration_ms'],
                  observed_through_ms=head['at'])
    rendered = json.dumps(result, indent=2)+'\n'
    if args.output:
        with args.output.open('x') as stream:
            stream.write(rendered)
    else:
        print(rendered, end='')


if __name__ == '__main__':
    main()
