#!/usr/bin/env python3
"""Freeze and run the full release formula rejection grid on retained raw data."""
import argparse
from collections import defaultdict
from copy import deepcopy
from datetime import datetime, timezone
import gzip
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

from release_pricing import (ASSETS, DAY, DELAYS, EDGES, GRID, PAYOUTS, SPEC,
                             STRATEGIES, USDC, OracleTape, Counts, replay, joint)
from trial_payout import brownian_width

ROOT = Path(__file__).resolve().parents[1]
SOURCES = ('scripts/release_pricing.py', 'scripts/research_release_pricing.py',
           'scripts/test_release_pricing.py', 'scripts/trial_payout.py',
           'engine/cmd/fuse-research/main.go', 'engine/cmd/fuse-research/main_test.go',
           'engine/internal/engine/pricing.go', 'engine/internal/engine/types.go',
           'engine/internal/engine/markets.go', 'engine/config/paper.json',
           'engine/go.mod', 'engine/go.sum')
BTC_NAMES = ('tardis-hyperliquid-BTC-8h-admission-controls-v1',
             'tardis-hyperliquid-BTC-bursty-full-days-v1',
             'tardis-hyperliquid-BTC-earlier-bursty-training-v1',
             'tardis-hyperliquid-BTC-expanded-bursty-training-v1',
             'tardis-hyperliquid-BTC-raw-flat-panels-v1',
             'tardis-hyperliquid-BTC-raw-jan2026-v1',
             'tardis-hyperliquid-BTC-temporal-late-v1')
MARKET = ROOT/'.local/market-history'
ETH_HYPE = MARKET/'tardis-hyperliquid-ETH-HYPE-monthly-raw-v1'


def read(path):
    return json.loads(Path(path).read_text())


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1 << 20), b''):
            h.update(block)
    return h.hexdigest()


def write(path, value):
    with Path(path).open('x') as stream:
        json.dump(value, stream, indent=2, allow_nan=False)
        stream.write('\n')


def origin(day):
    return int(datetime.fromisoformat(day).replace(tzinfo=timezone.utc).timestamp())*1000


def child(root, relative):
    root = Path(root).resolve()
    path = (root/relative).resolve()
    path.relative_to(root)
    return path


def complete(files, day):
    cursor = origin(day)
    for f in sorted(files, key=lambda f: f['at_ms']):
        duration = f.get('duration_ms', 60_000)
        if (f.get('status') != 'downloaded' or f['at_ms'] != cursor or
                type(duration) is not int or duration <= 0):
            return False
        cursor += duration
    return cursor == origin(day)+DAY


def inventory(root):
    root = Path(root).resolve()
    protocol, manifest = read(root/'download-protocol.json'), read(root/'download-manifest.json')
    if manifest['protocol_sha256'] != sha(root/'download-protocol.json'):
        raise ValueError('download protocol/manifest binding differs')
    requests = {f['path']: f for f in protocol['requests']}
    files, by_day = manifest['files'], defaultdict(list)
    if len({f['path'] for f in files}) != len(files):
        raise ValueError('duplicate raw slice path')
    for f in files:
        declared = requests.get(f['path'])
        if (declared is None or any(declared.get(k) != f.get(k) for k in
                                    ('day', 'at_ms', 'url')) or
                declared.get('duration_ms', 60_000) != f.get('duration_ms', 60_000)):
            raise ValueError('raw slice differs from its download declaration')
        child(root, f['path'])
        by_day[f['day']].append(f)
    return protocol, dict(by_day), dict(root=str(root),
        protocol_sha256=sha(root/'download-protocol.json'),
        manifest_sha256=sha(root/'download-manifest.json'))


def export_vectors(binary):
    original = read(ROOT/'engine/config/paper.json')
    rows = []
    for edge in EDGES:
        policy = deepcopy(original)
        policy['model']['dnt']['house_edge_bps'] = edge
        for model in policy['markets'].values():
            model['dnt']['house_edge_bps'] = edge
        request = json.dumps(dict(kind='pricing_grid', policy=policy))+'\n'
        out = subprocess.run([str(binary)], input=request, text=True,
                             capture_output=True, check=True, timeout=30)
        value = json.loads(out.stdout)
        if not value['ok']:
            raise ValueError('native formula export failed: '+str(value.get('error')))
        rows.extend(value['value'])
    wanted = {(a, m, e) for a in ASSETS for m in PAYOUTS for e in EDGES}
    got = {(r['asset'], r['multiplier'], r['house_edge_bps']) for r in rows}
    if len(rows) != len(wanted) or got != wanted:
        raise ValueError('native pricing grid is incomplete')
    for r in rows:
        if brownian_width(r['volatility_30s_ppm'], r['multiplier'], r['house_edge_bps']) != r['width_ppb']:
            raise ValueError('Python/native integer width parity failed')
    return rows


def declare(output, binary, btc_roots=None, other=ETH_HYPE):
    output, binary, other = Path(output), Path(binary).resolve(), Path(other).resolve()
    if output.exists():
        raise FileExistsError('preserve previous research; choose a new packet')
    roots = btc_roots or [MARKET/n for n in BTC_NAMES]
    catalogs, btc, excluded = [], {}, []
    for directory in roots:
        _, days, binding = inventory(directory)
        catalogs.append(binding)
        for day, files in sorted(days.items()):
            if complete(files, day):
                if day in btc:
                    # Deterministic declared-root order, without reading prices.
                    excluded.append(dict(day=day, root=str(directory), reason='duplicate_complete_BTC_day'))
                else:
                    btc[day] = str(Path(directory).resolve())
            else:
                excluded.append(dict(day=day, root=str(directory), reason='not_a_complete_raw_UTC_day'))
    other_protocol, other_days, other_binding = inventory(other)
    catalogs.append(other_binding)
    days = []
    for day in sorted(btc):
        available = all(other_protocol['available_since'][a][:10] <= day for a in ('ETH', 'HYPE'))
        if available and day in other_days and complete(other_days[day], day):
            days.append(day)
        else:
            excluded.append(dict(day=day, reason='no_full_declared_ETH_HYPE_coverage'))
    if not days:
        raise ValueError('no common complete raw dates')
    vectors = export_vectors(binary)
    sources = {n: sha(ROOT/n) for n in SOURCES}
    output.mkdir(parents=True)
    (output/'source').mkdir()
    for name in SOURCES:
        target = output/'source'/name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT/name, target)
    write(output/'native-vectors.json', vectors)
    plan = dict(spec=SPEC, days=days, btc_by_day={d: btc[d] for d in days},
        eth_hype=str(other), catalogs=catalogs, excluded=excluded,
        native_binary=str(binary), native_binary_sha256=sha(binary),
        native_vectors_sha256=sha(output/'native-vectors.json'), source_sha256=sources,
        declared_before_this_grid_replay=True, previously_inspected_development_data=True,
        market_paths_prospective=False, native_admission_replayed=False,
        paired_receivers_synthesized=False, live_policy_changed=False,
        production_pricing_validated=False, goal_complete=False)
    write(output/'protocol.json', plan)
    write(output/'freeze.json', dict(protocol_sha256=sha(output/'protocol.json')))
    return plan


def verify_plan(output, require_current_sources=True):
    output = Path(output)
    plan = read(output/'protocol.json')
    if sha(output/'protocol.json') != read(output/'freeze.json')['protocol_sha256']:
        raise ValueError('research protocol changed')
    for name, expected in plan['source_sha256'].items():
        if (require_current_sources and sha(ROOT/name) != expected) or sha(output/'source'/name) != expected:
            raise ValueError('research source changed: '+name)
    for binding in plan['catalogs']:
        root = Path(binding['root'])
        if (sha(root/'download-protocol.json') != binding['protocol_sha256'] or
                sha(root/'download-manifest.json') != binding['manifest_sha256']):
            raise ValueError('raw catalog changed')
    if (sha(plan['native_binary']) != plan['native_binary_sha256'] or
            sha(output/'native-vectors.json') != plan['native_vectors_sha256']):
        raise ValueError('native binary or vectors changed')
    return plan


def price(value):
    if not isinstance(value, str):
        raise ValueError('oracle price must be an exact decimal string')
    parts = value.split('.')
    if (len(parts) > 2 or not parts[0] or not parts[0].isascii() or not parts[0].isdigit() or
            (len(parts) == 2 and (not 1 <= len(parts[1]) <= 6 or not parts[1].isascii() or not parts[1].isdigit()))):
        raise ValueError('invalid native decimal price')
    n = int(parts[0])*USDC + (int(parts[1].ljust(6, '0')) if len(parts) == 2 else 0)
    if not 0 < n <= 10**15:
        raise ValueError('oracle price outside native envelope')
    return n


def timestamp(value):
    if not value.endswith('Z') or '.' not in value:
        raise ValueError('raw UTC timestamp required')
    seconds, fraction = value[:-1].split('.')
    if not fraction.isascii() or not fraction.isdigit():
        raise ValueError('raw fractional timestamp invalid')
    dt = datetime.strptime(seconds, '%Y-%m-%dT%H:%M:%S').replace(tzinfo=timezone.utc)
    return int(dt.timestamp())*1000+int((fraction+'000')[:3])


def load_day(root, day, assets):
    _, days, _ = inventory(root)
    files = sorted(days[day], key=lambda f: f['at_ms'])
    if not complete(files, day):
        raise ValueError('full raw day no longer complete')
    points = {a: [] for a in assets}
    breaks, previous, waiting = [], None, False
    for item in files:
        path = child(root, item['path'])
        if sha(path) != item['sha256']:
            raise ValueError('raw slice hash changed: '+str(path))
        for line in gzip.decompress(path.read_bytes()).decode().splitlines():
            if not line:
                waiting = True
                continue
            stamp, payload = line.split(' ', 1)
            at = timestamp(stamp)
            if (not item['at_ms'] <= at < item['at_ms']+item.get('duration_ms', 60_000) or
                    (previous is not None and at < previous)):
                raise ValueError('raw receipt order or slice horizon invalid')
            if waiting:
                breaks.append((previous if previous is not None else origin(day), at))
                waiting = False
            previous = at
            message = json.loads(payload)
            if message['channel'] != 'activeAssetCtx' or message['data']['coin'] not in assets:
                raise ValueError('wrong raw channel or asset')
            asset, ctx = message['data']['coin'], message['data']['ctx']
            mark = price(ctx['markPx']) if ctx.get('markPx') else None
            points[asset].append((at, price(ctx['oraclePx']), mark))
    if waiting:
        breaks.append((previous if previous is not None else origin(day), origin(day)+DAY))
    return {a: OracleTape(points[a], origin(day), origin(day)+DAY, breaks) for a in assets}


def run(output):
    output = Path(output)
    plan = verify_plan(output)
    if any((output/n).exists() for n in ('result.json', 'cases.jsonl', 'paths.jsonl.gz', 'joint.jsonl')):
        raise FileExistsError('preserve completed or interrupted evidence; declare a new packet')
    widths = {(r['asset'], r['multiplier'], r['house_edge_bps']): r['width_ppb']
              for r in read(output/'native-vectors.json')}
    totals = defaultdict(Counts)
    ncases = njoint = npaths = 0
    with (output/'cases.jsonl').open('x') as cases, (output/'joint.jsonl').open('x') as portfolios, \
            gzip.open(output/'paths.jsonl.gz', 'xt', compresslevel=5) as paths:
        for day in plan['days']:
            tapes = load_day(Path(plan['btc_by_day'][day]), day, ('BTC',))
            tapes.update(load_day(Path(plan['eth_hype']), day, ('ETH', 'HYPE')))
            outcomes = {}
            for asset in ASSETS:
                for delay in DELAYS:
                    envelopes = [tapes[asset].envelope(q, delay)
                                 for q in range(origin(day), origin(day)+DAY, GRID)]
                    for row in envelopes:
                        paths.write(json.dumps(dict(asset=asset, day=day, delay_ms=delay, **row),
                                               separators=(',', ':'), allow_nan=False)+'\n')
                    npaths += len(envelopes)
                    for edge in EDGES:
                        for multiplier in PAYOUTS:
                            counts, strata, codes = replay(envelopes, widths[asset, multiplier, edge], multiplier, edge)
                            outcomes[asset, multiplier, edge, delay] = codes
                            for strategy, count in counts.items():
                                totals[asset, multiplier, edge, delay, strategy].merge(count)
                                row = dict(day=day, asset=asset, multiplier=multiplier, edge_bps=edge,
                                           delay_ms=delay, strategy=strategy, **count.result(multiplier, edge),
                                           strata=[dict(axis=axis, group=group, **s.result(multiplier, edge))
                                                   for (axis, group), s in sorted(strata.items())]
                                           if strategy == 'all_offered' else [])
                                cases.write(json.dumps(row, separators=(',', ':'), allow_nan=False)+'\n')
                                ncases += 1
            for edge in EDGES:
                for multiplier in PAYOUTS:
                    for delay in DELAYS:
                        row = dict(day=day, edge_bps=edge, multiplier=multiplier, delay_ms=delay,
                            **joint([outcomes[a, multiplier, edge, delay] for a in ASSETS], multiplier))
                        portfolios.write(json.dumps(row, separators=(',', ':'), allow_nan=False)+'\n')
                        njoint += 1
            print(json.dumps(dict(day=day, complete_assets=3, cases=ncases, paths=npaths)), flush=True)
    verify_plan(output)
    summary = [dict(asset=a, multiplier=m, edge_bps=e, delay_ms=d, strategy=s, **c.result(m, e))
               for (a, m, e, d, s), c in sorted(totals.items())]
    result = dict(protocol_sha256=sha(output/'protocol.json'), complete_common_dates=plan['days'],
        unique_grid_opportunities=len(plan['days'])*len(ASSETS)*DAY//GRID,
        path_envelopes=npaths, daily_strategy_cases=ncases, daily_joint_cases=njoint,
        repeated_paths_are_independent=False, summary=summary,
        artifacts_sha256={n: sha(output/n) for n in ('cases.jsonl', 'joint.jsonl', 'paths.jsonl.gz', 'native-vectors.json')},
        native_formula_vectors_verified=len(widths), native_admission_replayed=False,
        funded_liabilities_or_rewards_evaluated=False, new_market_data=False,
        production_pricing_validated=False, goal_complete=False)
    write(output/'result.json', result)
    report(output, result)
    return result


def report(output, result):
    lines = ['# Release pricing rejection controls', '', '**Production pricing validated: NO.**', '',
        f"Dates: {', '.join(result['complete_common_dates'])}. "
        f"{result['unique_grid_opportunities']:,} distinct asset/grid opportunities; "
        f"{result['native_formula_vectors_verified']} exact native formula vectors. "
        'Every edge, payout, delay and strategy reuses these paths.', '',
        'Previously inspected raw single-stream history. No native paired admission, '
        'bankroll, demand, fees, rewards or fresh prospective validation is claimed.', '',
        '## Immediate all-offered control', '',
        'Player wins are full-path outcomes; unresolved accepted tickets stay in the '
        'cash bounds. An edge setting is a target, not observed profit.', '',
        '| Asset | Payout | Edge | Accepted | Censored | Player wins / resolved | LP gross, refunds ($) | LP best case for censored ($) |',
        '| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |']
    for r in result['summary']:
        if r['delay_ms'] == 0 and r['strategy'] == 'all_offered':
            lines.append(f"| {r['asset']} | {r['multiplier']} | {r['edge_bps']/100:g}% | "
                         f"{r['accepted']} | {r['censored']} | {r['wins']} / {r['resolved']} | "
                         f"{r['gross_lp_refund_usdc_units']/USDC:,.0f} | "
                         f"{r['gross_lp_if_censored_all_fail_usdc_units']/USDC:,.0f} |")
    lines += ['', 'All delayed/public-strategy cases, natural staleness/jump strata and '
        'contemporaneous three-asset win patterns are retained in the JSON artifacts. '
        'The 2,000 ms acceptance boundary is a deliberate rejection control. '
        'No best-looking rule, edge or asset is selected or promoted.', '',
        'These are unfitted Brownian controls, not the adaptive challenger. '
        'The single-stream freshness/sequence analogue is not dual-receiver engine '
        'execution. Censoring rules are deliberately conservative and not actual '
        'contract refunds. Software tests separately cover staleness, sequence '
        'round trips, touches, deadline and label-maturity boundaries.', '']
    (output/'report.md').write_text('\n'.join(lines))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--binary', type=Path)
    parser.add_argument('--declare', action='store_true')
    args = parser.parse_args()
    if args.declare:
        if args.binary is None:
            parser.error('--binary is required for declaration')
        result = declare(args.output, args.binary)
        print(json.dumps(dict(declared=True, days=result['days'], production_pricing_validated=False)))
    else:
        result = run(args.output)
        print(json.dumps(dict(completed=True, daily_cases=result['daily_strategy_cases'],
                              production_pricing_validated=False)))
