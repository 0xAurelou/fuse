#!/usr/bin/env python3
"""Declare and evaluate one causal empirical challenger on audited raw paths."""
import argparse
from collections import Counter, defaultdict
import gzip
from itertools import groupby
import json
import os
from pathlib import Path
import shutil
import sys

from release_empirical_pricing import SPEC, fit, reference, replay, surface, digest
from release_pricing import ASSETS, DAY, DELAYS, EDGES, GRID, PAYOUTS, STRATEGIES, Counts, joint
from research_release_pricing import ROOT, origin, read, sha, write, verify_plan
from replay_lp_economics import Bridge

SOURCES = ('scripts/release_empirical_pricing.py', 'scripts/research_release_empirical.py',
    'scripts/audit_release_empirical.py', 'scripts/test_release_empirical.py',
    'scripts/release_pricing.py', 'scripts/research_release_pricing.py',
    'scripts/replay_lp_economics.py', 'engine/cmd/fuse-research/main.go',
    'engine/cmd/fuse-research/main_test.go', 'scripts/audit_release_pricing.py',
    'scripts/test_release_pricing.py', 'scripts/trial_payout.py',
    'scripts/contract_lp_model.py', 'scripts/calibrate_pricing.py', 'engine/internal/engine/reducer.go',
    'engine/internal/engine/types.go', 'engine/config/paper.json', 'engine/go.mod', 'engine/go.sum')


def verified_input(directory):
    directory = Path(directory).resolve()
    p = verify_plan(directory, require_current_sources=False)
    result, audit = read(directory/'result.json'), read(directory/'audit.json')
    if (not audit['passed'] or audit['result_sha256'] != sha(directory/'result.json') or
            audit['protocol_sha256'] != sha(directory/'protocol.json') or
            audit['raw_envelopes_reconstructed'] != len(p['days'])*3*5*DAY//GRID):
        raise ValueError('complete source-bound raw envelope audit required')
    for name, h in result['artifacts_sha256'].items():
        if sha(directory/name) != h:
            raise ValueError('audited input artifact changed: '+name)
    return p


def copy_native_binary(source, target):
    """Keep execution permission when sealing the read-only Go bridge."""
    if not os.access(source, os.X_OK):
        raise PermissionError('native research binary is not executable: '+str(source))
    shutil.copy2(source, target)


def declare(output, baseline, binary):
    output, baseline, binary = (Path(p).resolve() for p in (output, baseline, binary))
    if output.exists():
        raise FileExistsError('preserve prior evidence; choose a new directory')
    original = verified_input(baseline)
    names=set(SOURCES)|{str(f.relative_to(ROOT)) for folder in ('engine/internal/engine','engine/cmd/fuse-research') for f in (ROOT/folder).glob('*.go')}
    bindings = {n: sha(ROOT/n) for n in sorted(names)}
    output.mkdir(parents=True)
    for name in bindings:
        target = output/'source'/name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT/name, target)
    copy_native_binary(binary, output/'fuse-research')
    policy = read(ROOT/'engine/config/paper.json')
    write(output/'native-policy.json', policy)
    plan = dict(spec=SPEC, days=original['days'], baseline_directory=str(baseline),
        baseline_bindings={n: sha(baseline/n) for n in ('protocol.json','result.json','audit.json','paths.jsonl.gz')},
        source_sha256=bindings, native_binary_sha256=sha(output/'fuse-research'),
        native_policy_sha256=sha(output/'native-policy.json'),
        python_version=sys.version,
        declaration_before_challenger_results=True, previously_inspected_development_data=True,
        new_independent_holdout=False, paired_native_admission=False, funded_bankroll_replayed=False,
        production_policy_changed=False, production_pricing_validated=False, goal_complete=False)
    write(output/'protocol.json', plan)
    write(output/'freeze.json', dict(protocol_sha256=sha(output/'protocol.json')))
    return plan


def verify(output, current=True):
    output = Path(output)
    p = read(output/'protocol.json')
    if sys.version!=p['python_version']:raise ValueError('challenger Python runtime changed')
    if sha(output/'protocol.json') != read(output/'freeze.json')['protocol_sha256']:
        raise ValueError('challenger protocol changed')
    if p['spec'] != json.loads(json.dumps(SPEC)):
        raise ValueError('challenger algorithm changed')
    for name, h in p['source_sha256'].items():
        if sha(output/'source'/name) != h or (current and sha(ROOT/name) != h):
            raise ValueError('challenger source changed: '+name)
    for name, h in p['baseline_bindings'].items():
        if sha(Path(p['baseline_directory'])/name) != h:
            raise ValueError('challenger input changed: '+name)
    if sha(output/'fuse-research') != p['native_binary_sha256'] or sha(output/'native-policy.json') != p['native_policy_sha256']:
        raise ValueError('native quantization binding changed')
    if not os.access(output/'fuse-research', os.X_OK):
        raise PermissionError('sealed native research binary is not executable')
    return p


def path_days(path):
    with gzip.open(path, 'rt') as f:
        rows = (json.loads(line) for line in f)
        for day, group in groupby(rows, key=lambda r: r['day']):
            grouped = defaultdict(list)
            for r in group:
                grouped[r['asset'], r['delay_ms']].append(r)
            if set(grouped) != {(a, d) for a in ASSETS for d in DELAYS}:
                raise ValueError('missing source asset/delay')
            for values in grouped.values():
                if [r['quote_at'] for r in values] != list(range(origin(day), origin(day)+DAY, GRID)):
                    raise ValueError('source grid is incomplete/duplicated')
            yield day, grouped


def native_check(output, vectors):
    bridge = Bridge(output/'fuse-research')
    policy = read(output/'native-policy.json')
    total = 0
    try:
        with (output/'native-quantization.jsonl').open('x') as f:
            values = sorted(vectors)
            for start in range(0, len(values), 2048):
                chunk = values[start:start+2048]
                response = bridge.send(dict(kind='quantize_corridors', policy=policy,
                    corridors=[dict(price=p, width_ppb=w) for p,w,d in chunk]))['value']
                if len(response) != len(chunk):
                    raise ValueError('incomplete native arithmetic response')
                for got, (price, width, delta) in zip(response, chunk):
                    if got != dict(price=price, width_ppb=width, delta=delta, valid=True):
                        raise ValueError('native quantization differs from offered corridor')
                    f.write(json.dumps(got, separators=(',', ':'))+'\n')
                    total += 1
    finally:
        bridge.close()
    return total


def run(output):
    output = Path(output)
    plan = verify(output)
    artifacts = ('forecasts.jsonl.gz','models.jsonl.gz','cases.jsonl','joint.jsonl','native-quantization.jsonl')
    if any((output/n).exists() for n in (*artifacts, 'result.json')):
        raise FileExistsError('preserve completed/interrupted challenger evidence')
    refs = {a: [] for a in ASSETS}
    totals = defaultdict(Counts)
    reasons, oracle_totals = defaultdict(Counter), defaultdict(int)
    vectors = set()
    forecasts = daily_cases = joint_cases = 0
    seen = []
    with gzip.open(output/'forecasts.jsonl.gz','xt',compresslevel=2) as trace, \
            gzip.open(output/'models.jsonl.gz','xt',compresslevel=2) as model_file, \
            (output/'cases.jsonl').open('x') as cases, (output/'joint.jsonl').open('x') as portfolios:
        for day, paths in path_days(Path(plan['baseline_directory'])/'paths.jsonl.gz'):
            if day in seen or day != plan['days'][len(seen)]:
                raise ValueError('calendar ordering changed')
            seen.append(day)
            outcomes = {}
            for asset in ASSETS:
                model = fit(refs[asset], origin(day))
                model_record = dict(day=day, asset=asset, cutoff_ms=origin(day),
                    groups=[dict(key=list(k), **v) for k,v in sorted(model.items())])
                model_id = digest(model_record)
                model_file.write(json.dumps(dict(model_id=model_id, **model_record), separators=(',', ':'))+'\n')
                immediate = paths[asset,0]
                for edge in EDGES:
                    predictions = [surface(model, r, edge) for r in immediate]
                    for row, offers in zip(immediate, predictions):
                        first = offers[PAYOUTS[0]]
                        common = {k:first[k] for k in ('training_group','training_references','training_dates','maximum_label_maturity_ms','threshold_sha256')}
                        record = dict(day=day, asset=asset, edge_bps=edge, quote_at=row['quote_at'],
                            entry=row['entry'], model_id=model_id, **common,
                            offers=[{k:q[k] for k in ('multiplier','offered','reason','width_ppb','delta','training_survivors')} for q in offers.values()])
                        trace.write(json.dumps(record, separators=(',', ':'))+'\n')
                        forecasts += len(offers)
                        for q in offers.values():
                            if q['offered']:
                                vectors.add((row['entry'],q['width_ppb'],q['delta']))
                    for multiplier in PAYOUTS:
                        offers = [p[multiplier] for p in predictions]
                        for delay in DELAYS:
                            counts, codes, refused, oracle = replay(paths[asset,delay], offers, multiplier, edge)
                            outcomes[asset,multiplier,edge,delay] = codes
                            for strategy,c in counts.items():
                                key = asset,multiplier,edge,delay,strategy
                                totals[key].merge(c)
                                oracle_totals[key] += oracle
                                if strategy == 'all_offered':
                                    reasons[key].update(refused)
                                row = dict(day=day, asset=asset, multiplier=multiplier, edge_bps=edge,
                                    delay_ms=delay, strategy=strategy, oracle_quote_available=oracle,
                                    refusal_reasons=refused if strategy=='all_offered' else {},
                                    **c.result(multiplier,edge))
                                cases.write(json.dumps(row,separators=(',', ':'))+'\n')
                                daily_cases += 1
                # Learn all eligible immediate reference paths, even if every
                # forecast refused. They enter only a later daily fit.
                refs[asset].extend(r for row in immediate if (r:=reference(row)) is not None)
            for edge in EDGES:
                for multiplier in PAYOUTS:
                    for delay in DELAYS:
                        row = dict(day=day,edge_bps=edge,multiplier=multiplier,delay_ms=delay,
                            **joint([outcomes[a,multiplier,edge,delay] for a in ASSETS],multiplier))
                        portfolios.write(json.dumps(row,separators=(',', ':'))+'\n')
                        joint_cases += 1
            print(json.dumps(dict(day=day, forecasts=forecasts, daily_cases=daily_cases)),flush=True)
    if seen != plan['days']:
        raise ValueError('incomplete challenger calendar')
    native = native_check(output, vectors)
    verify(output)
    summary = [dict(asset=a,multiplier=m,edge_bps=e,delay_ms=d,strategy=s,
        oracle_quote_available=oracle_totals[a,m,e,d,s],
        refusal_reasons=dict(reasons[a,m,e,d,s]), **c.result(m,e))
        for (a,m,e,d,s),c in sorted(totals.items())]
    result = dict(protocol_sha256=sha(output/'protocol.json'), summary=summary,
        complete_common_dates=seen, unique_asset_grid_opportunities=len(seen)*3*DAY//GRID,
        forecasted_asset_payout_edge_opportunities=forecasts, daily_strategy_cases=daily_cases,
        daily_joint_cases=joint_cases, native_quantization_vectors=native,
        artifacts_sha256={n:sha(output/n) for n in artifacts}, previously_inspected_development_data=True,
        native_admission_replayed=False, funded_bankroll_evaluated=False, fresh_holdout=False,
        production_pricing_validated=False, goal_complete=False)
    write(output/'result.json',result)
    lines=['# Causal empirical release challenger','', '**Production pricing validated: NO.**','',
        'Previously inspected, nonconsecutive single-stream raw dates. Every preset, edge, latency and public strategy is retained. '
        'Refusal is not successful calibration. Native checks cover integer arithmetic only.','',
        '| Asset | Payout | Target edge | Offered | Oracle available | Accepted | Wins / resolved | LP gross, refund assumption |',
        '| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |']
    for r in summary:
        if r['delay_ms']==0 and r['strategy']=='all_offered':
            lines.append(f"| {r['asset']} | {r['multiplier']} | {r['edge_bps']/100:g}% | {r['quote_available']} | {r['oracle_quote_available']} | {r['accepted']} | {r['wins']} / {r['resolved']} | {r['gross_lp_refund_usdc_units']/1e6:g} |")
    (output/'report.md').write_text('\n'.join(lines)+'\n')
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--baseline',type=Path)
    p.add_argument('--binary',type=Path)
    p.add_argument('--declare',action='store_true')
    a=p.parse_args()
    if a.declare:
        if a.baseline is None or a.binary is None:p.error('--declare needs --baseline and --binary')
        declare(a.output,a.baseline,a.binary)
    else:run(a.output)
