#!/usr/bin/env python3
"""Post-run cross-check of raw envelopes, causal strategies and every cash case.

This software audit is not an independent external pricing/security review.
It does not call the replay's envelope, selection, count or portfolio functions.
"""
import argparse
from bisect import bisect_left, bisect_right
from collections import Counter, defaultdict
import gzip
from itertools import groupby, zip_longest
import json
from pathlib import Path

from release_pricing import ASSETS, DAY, DELAYS, EDGES, GRID, PAYOUTS, STRATEGIES, USDC
from research_release_pricing import (export_vectors, load_day, origin, read,
                                      sha, verify_plan, write)

FIELDS = ('grid', 'quote_available', 'intended', 'accepted', 'rejected', 'resolved', 'wins', 'censored')


def require(ok, message):
    if not ok:
        raise ValueError(message)


def manual_envelope(tape, q, delay):
    points, times, breaks = tape.points, tape.times, tape.disconnects
    qi, ai = bisect_left(times, q)-1, bisect_left(times, q+delay)-1
    entry = points[qi][1] if qi >= 0 else None
    age = q-times[qi] if qi >= 0 else None
    prior_state, mark_gap = 'missing_history', None
    if qi >= 0:
        mark = points[qi][2]
        mark_gap = abs(mark-entry)*1_000_000//entry if mark is not None else None
        j = bisect_left(times, q-GRID)-1
        history = points[j:qi+1] if j >= 0 else []
        known_break = any(a < q and b >= q-GRID and b < q for a, b in breaks)
        if (history and q-GRID-history[0][0] <= 8000 and q-history[-1][0] <= 8000
                and not known_break and all(b[0]-a[0] <= 8000 for a, b in zip(history, history[1:]))):
            if any(abs(b[1]-a[1])*1_000_000 >= 100*a[1] for a, b in zip(history, history[1:])):
                prior_state = 'jump'
            elif all(p[1] == history[0][1] for p in history):
                prior_state = 'flat'
            else:
                prior_state = 'moving'
    row = dict(quote_at=q, accepted_at=q+delay, expiry=q+delay+GRID, entry=entry,
               quote_age_ms=age, quote_available=age is not None and age <= 8000,
               accepted=False, reason='', valid=False, move=None,
               observed_path_jump_100ppm=None, prior_state=prior_state, mark_gap_ppm=mark_gap)
    if not row['quote_available']:
        row['reason'] = 'missing_or_stale_quote_oracle'
    elif delay >= 2000:
        row['reason'] = 'quote_expired'
    elif ai < 0 or q+delay-times[ai] > 8000:
        row['reason'] = 'stale_acceptance_oracle'
    elif any(p[1] != entry for p in points[qi+1:ai+1]):
        row['reason'] = 'oracle_sequence_changed'
    else:
        row['accepted'] = True
    if not row['accepted']:
        return row
    if row['expiry'] > tape.end:
        row['reason'] = 'right_censored_archive'
        return row
    stop = bisect_left(times, row['expiry'])
    path = points[ai:stop]
    row['move'] = max(abs(p[1]-entry) for p in path)
    row['observed_path_jump_100ppm'] = any(
        abs(b[1]-a[1])*1_000_000 >= 100*a[1] for a, b in zip(path, path[1:]))
    row['valid'] = (q+delay-path[0][0] <= 8000 and row['expiry']-path[-1][0] <= 8000
                    and all(b[0]-a[0] <= 8000 for a, b in zip(path, path[1:]))
                    and not any(a < row['expiry'] and b >= q+delay for a, b in breaks))
    if not row['valid']:
        row['reason'] = 'censored_gap_or_disconnect'
    return row


def choose(strategy, row, last):
    if not row['quote_available']:
        return False
    state, gap = row['prior_state'], row['mark_gap_ppm']
    if strategy == 'all_offered': return True
    if strategy == 'prior30_flat': return state == 'flat'
    if strategy == 'prior30_moving': return state in ('moving', 'jump')
    if strategy == 'prior30_jump_100ppm': return state == 'jump'
    if strategy == 'mark_gap_at_most_1bp': return gap is not None and gap <= 100
    if strategy == 'mark_gap_over_1bp': return gap is not None and gap > 100
    if strategy == 'last_matured_survived': return last is True
    if strategy == 'last_matured_failed': return last is False
    raise ValueError('unknown strategy')


def add(counts, row, selected, outcome):
    counts[0] += 1
    counts[1] += int(row['quote_available'])
    counts[2] += int(selected)
    if selected:
        counts[3] += int(row['accepted'])
        counts[4] += int(not row['accepted'])
        counts[5] += int(row['accepted'] and outcome is not None)
        counts[6] += int(row['accepted'] and outcome is True)
        counts[7] += int(row['accepted'] and outcome is None)


def check_cash(row, counts, multiplier, edge):
    expected = dict(zip(FIELDS, counts))
    require(all(row[k] == v for k, v in expected.items()), 'strategy ticket counts differ')
    n, w, c, placed = expected['resolved'], expected['wins'], expected['censored'], expected['accepted']
    gross = (n-w)*USDC-w*(multiplier-1)*USDC
    lower = gross-c*(multiplier-1)*USDC
    upper = gross+c*USDC
    require(row['gross_lp_refund_usdc_units'] == gross and row['gross_player_refund_usdc_units'] == -gross,
            'gross cash differs')
    require(row['gross_lp_if_censored_all_win_usdc_units'] == lower and
            row['gross_lp_if_censored_all_fail_usdc_units'] == upper, 'censoring bounds differ')
    require(row['survival'] == (w/n if n else None), 'survival denominator differs')
    require(row['target_survival'] == (10_000-edge)/(10_000*multiplier), 'target differs')
    require(row['quoted_target_expected_wins'] == n*(10_000-edge)/(10_000*multiplier), 'target count differs')
    require([c['expense_bps'] for c in row['costs']] == [0, 10, 50, 100], 'missing cost case')
    for cost in row['costs']:
        expense = placed*USDC*cost['expense_bps']//10_000
        require(cost['expense_usdc_units'] == expense and cost['net_lp_refund_usdc_units'] == gross-expense
                and cost['net_lp_lower_usdc_units'] == lower-expense
                and cost['net_lp_upper_usdc_units'] == upper-expense, 'expense cash differs')


def check_configuration(envelopes, width, multiplier, edge, cases):
    adjusted, outcomes, codes = [], [], bytearray()
    mature_times, labels = [], []
    for row in envelopes:
        delta = row['entry']*width//10**9 if row['entry'] is not None else 0
        r = row if delta > 0 else dict(row, quote_available=False, accepted=False)
        outcome = r['move'] < delta if r['accepted'] and r['valid'] else None
        adjusted.append(r)
        outcomes.append(outcome)
        codes.append(0 if not r['accepted'] else 1 if outcome is None else 3 if outcome else 2)
        if r['accepted'] and outcome is not None:
            mature_times.append(r['expiry']+30_000)
            labels.append(outcome)
    collected = {}
    for strategy in STRATEGIES:
        counts, strata = [0]*8, defaultdict(lambda: [0]*8)
        for row, outcome in zip(adjusted, outcomes):
            last_index = bisect_right(mature_times, row['quote_at'])-1
            last = labels[last_index] if last_index >= 0 else None
            selected = choose(strategy, row, last)
            add(counts, row, selected, outcome)
            if strategy == 'all_offered':
                age = row['quote_age_ms']
                groups = (('prior_state', row['prior_state']),
                          ('quote_age', 'missing' if age is None else 'at_most_1s' if age <= 1000 else
                           '1_to_8s' if age <= 8000 else 'over_8s'),
                          ('observed_jump', 'unknown' if row['observed_path_jump_100ppm'] is None else
                           'jump' if row['observed_path_jump_100ppm'] else 'no_jump'))
                for group in groups:
                    add(strata[group], row, selected, outcome)
        recorded = cases[strategy]
        check_cash(recorded, counts, multiplier, edge)
        require(len(recorded['strata']) == len(strata), 'stratum coverage differs')
        seen = set()
        for cell in recorded['strata']:
            key = cell['axis'], cell['group']
            require(key in strata and key not in seen, 'missing or duplicate stratum')
            seen.add(key)
            check_cash(cell, strata[key], multiplier, edge)
        collected[strategy] = counts
    return codes, collected


def check_joint(row, codes, multiplier):
    triples = list(zip(*codes))
    accepted = sum(s > 0 for column in codes for s in column)
    resolved = sum(s >= 2 for column in codes for s in column)
    wins = sum(s == 3 for column in codes for s in column)
    censored = accepted-resolved
    require(row['grid'] == len(triples) and row['accepted_tickets'] == accepted
            and row['resolved_tickets'] == resolved and row['trader_wins'] == wins
            and row['censored_tickets'] == censored, 'joint ticket counts differ')
    clean = [v for v in triples if min(v) >= 2]
    patterns = Counter(sum(s == 3 for s in v) for v in clean)
    require(row['coaccepted'] == sum(min(v) > 0 for v in triples) and row['coresolved'] == len(clean)
            and row['clean_coaccepted_win_count_histogram'] == [patterns[k] for k in range(4)],
            'simultaneous win patterns differ')
    for a, b in ((0, 1), (0, 2), (1, 2)):
        pairs = [(v[a] == 3, v[b] == 3) for v in triples if v[a] >= 2 and v[b] >= 2]
        require(row['paired_resolved_counts'][f'{ASSETS[a]}:{ASSETS[b]}'] ==
                [len(pairs), sum(a for a, b in pairs), sum(b for a, b in pairs), sum(a and b for a, b in pairs)],
                'pairwise dependence counts differ')
    gross = (resolved-wins)*USDC-wins*(multiplier-1)*USDC
    require(row['gross_lp_refund_usdc_units'] == gross and
            row['gross_lp_lower_usdc_units'] == gross-censored*(multiplier-1)*USDC and
            row['gross_lp_upper_usdc_units'] == gross+censored*USDC, 'joint cash differs')
    require(row['one_wallet_per_asset_net_maximum_obligation_usdc_units'] == 3*(multiplier-1)*USDC,
            'joint maximum obligation differs')
    scaled = row['three_wallets_per_asset']
    require(scaled == dict(accepted_tickets=accepted*3, trader_wins=wins*3,
                          gross_lp_refund_usdc_units=gross*3,
                          net_maximum_obligation_usdc_units=9*(multiplier-1)*USDC),
            'same-path multiwallet scaling differs')
    require(row['shared_paths_independent'] is False and row['funded_admission_evaluated'] is False,
            'portfolio scope changed')


def grouped(path, compressed=False):
    opener = gzip.open if compressed else open
    with opener(path, 'rt') as stream:
        for day, records in groupby((json.loads(line) for line in stream), key=lambda r: r['day']):
            yield day, list(records)


def audit(output):
    output = Path(output)
    if (output/'audit.json').exists():
        raise FileExistsError('preserve the prior audit')
    plan, result = verify_plan(output), read(output/'result.json')
    result_hash = sha(output/'result.json')
    require(result['protocol_sha256'] == sha(output/'protocol.json'), 'result/protocol binding differs')
    for name, expected in result['artifacts_sha256'].items():
        require(sha(output/name) == expected, 'result artifact changed: '+name)
    vectors = export_vectors(Path(plan['native_binary']))
    require(vectors == read(output/'native-vectors.json'), 'native formula export differs')
    widths = {(r['asset'], r['multiplier'], r['house_edge_bps']): r['width_ppb'] for r in vectors}
    streams = (grouped(output/'paths.jsonl.gz', True), grouped(output/'cases.jsonl'), grouped(output/'joint.jsonl'))
    npaths = ncases = njoint = 0
    seen_days, totals = [], defaultdict(lambda: [0]*8)
    for pg, cg, jg in zip_longest(*streams):
        require(pg is not None and cg is not None and jg is not None, 'missing day artifact')
        day, paths = pg
        require(cg[0] == day == jg[0] and day not in seen_days, 'day alignment or uniqueness differs')
        seen_days.append(day)
        tapes = load_day(Path(plan['btc_by_day'][day]), day, ('BTC',))
        tapes.update(load_day(Path(plan['eth_hype']), day, ('ETH', 'HYPE')))
        grouped_paths = defaultdict(list)
        for path in paths:
            key = path['asset'], path['delay_ms']
            require(key[0] in ASSETS and key[1] in DELAYS, 'unknown path asset/delay')
            expected = manual_envelope(tapes[key[0]], path['quote_at'], key[1])
            require(json.dumps(expected, sort_keys=True) ==
                    json.dumps({k: path[k] for k in expected}, sort_keys=True), 'raw envelope differs')
            grouped_paths[key].append(path)
            npaths += 1
        require(len(grouped_paths) == len(ASSETS)*len(DELAYS), 'incomplete path configuration grid')
        for rows in grouped_paths.values():
            require([r['quote_at'] for r in rows] == list(range(origin(day), origin(day)+DAY, GRID)),
                    'incomplete original quote grid')
        cases = {}
        for c in cg[1]:
            key = c['asset'], c['multiplier'], c['edge_bps'], c['delay_ms'], c['strategy']
            require(key not in cases, 'duplicate case')
            cases[key] = c
        outcomes = {}
        for asset in ASSETS:
            for edge in EDGES:
                for multiplier in PAYOUTS:
                    for delay in DELAYS:
                        records = {s: cases[asset, multiplier, edge, delay, s] for s in STRATEGIES}
                        codes, collected = check_configuration(grouped_paths[asset, delay],
                            widths[asset, multiplier, edge], multiplier, edge, records)
                        outcomes[asset, multiplier, edge, delay] = codes
                        for strategy, counts in collected.items():
                            key = asset, multiplier, edge, delay, strategy
                            totals[key] = [a+b for a, b in zip(totals[key], counts)]
                        ncases += len(records)
        require(len(cases) == len(ASSETS)*len(EDGES)*len(PAYOUTS)*len(DELAYS)*len(STRATEGIES), 'extra or missing cases')
        seen_joint = set()
        for r in jg[1]:
            key = r['multiplier'], r['edge_bps'], r['delay_ms']
            require(key not in seen_joint, 'duplicate joint case')
            seen_joint.add(key)
            m, edge, delay = key
            check_joint(r, [outcomes[a, m, edge, delay] for a in ASSETS], m)
            njoint += 1
        require(len(seen_joint) == len(EDGES)*len(PAYOUTS)*len(DELAYS), 'incomplete joint grid')
        print(json.dumps(dict(audited_day=day, raw_envelopes=npaths, strategy_cases=ncases)), flush=True)
    require(seen_days == plan['days'] == result['complete_common_dates'], 'scheduled dates differ')
    require(npaths == result['path_envelopes'] and ncases == result['daily_strategy_cases'] and
            njoint == result['daily_joint_cases'], 'artifact totals differ')
    require(len(result['summary']) == len(totals), 'summary coverage differs')
    summary_keys = set()
    for row in result['summary']:
        key = row['asset'], row['multiplier'], row['edge_bps'], row['delay_ms'], row['strategy']
        require(key in totals and key not in summary_keys, 'unknown or duplicate summary')
        summary_keys.add(key)
        check_cash(row, totals[key], row['multiplier'], row['edge_bps'])
    verify_plan(output)
    require(sha(output/'result.json') == result_hash, 'result changed during audit')
    checked = dict(passed=True, result_sha256=result_hash, protocol_sha256=sha(output/'protocol.json'),
                   auditor_sha256=sha(__file__), native_formula_vectors=len(vectors),
                   raw_envelopes_reconstructed=npaths, strategy_cases_replayed=ncases,
                   joint_cases_replayed=njoint, production_pricing_validated=False,
                   independent_external_review=False, goal_complete=False)
    write(output/'audit.json', checked)
    return checked


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--research', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(audit(args.research)))
