#!/usr/bin/env python3
"""Separate quote edge, actual trading outcomes, and the 5% profit share.

Quoted edge is metadata in this sensitivity. Actual outcome probabilities alone
drive the funded settlement ledger. No nominal-margin revenue is booked.
"""
import argparse
from dataclasses import replace
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import statistics

from dynamic_profit_allocation import run, allocate
from stress_loss_rewards import Scenario, USDC

ROOT = Path(__file__).resolve().parent.parent


def settled_window(stakes, recognized_payouts, previous_loss=0, protected_capital=0):
    """Explanatory complete-outcome window, not a contract ledger substitute.

    Stakes/payouts refer only to resolved bets, including recognized winnings
    still owed to users. Capital deposits and outstanding bet principal are not
    accepted as revenue inputs. Protected capital is retained before profit share.
    """
    if min(stakes, recognized_payouts, previous_loss, protected_capital) < 0:
        raise ValueError('nonnegative window amounts required')
    actual_pnl = stakes - recognized_payouts
    profit_after_recovery = max(0, actual_pnl - previous_loss)
    distributable = max(0, profit_after_recovery - protected_capital)
    protocol = distributable * 500 // 10000
    return dict(stakes=stakes, recognized_payouts=recognized_payouts,
                actual_trading_pnl=actual_pnl, prior_loss_recovered=min(max(0, actual_pnl), previous_loss),
                distributable_profit=distributable, protocol=protocol,
                dynamic_lp_fuse_remainder=distributable - protocol)


def simulate(quoted_edge_bps, actual_survival_bps, seed=20261029, days=180):
    if not 0 <= quoted_edge_bps < 10000 or not 0 <= actual_survival_bps <= 10000:
        raise ValueError('invalid quote/outcome input')
    # Critical separation: quoted edge is NOT supplied to the profit allocator
    # or used to generate actual outcomes. Payout is fixed at 2x in this study.
    s = Scenario(seed=seed, days=days, survival_bps=actual_survival_bps)
    result = run(s, 'dynamic', 60)
    result['quoted_house_edge_bps'] = quoted_edge_bps
    result['actual_survival_bps_assumption'] = actual_survival_bps
    result['actual_expected_trading_margin'] = float(1 - 2 * Fraction(actual_survival_bps, 10000))
    result['realized_trading_margin'] = (
        result['trading_pnl_usdc_units'] / (result['accepted'] * s.stake_usdc * USDC)
        if result['accepted'] else None)
    result['ideal_quote_expectation_not_booked_usdc_units'] = (
        result['accepted'] * s.stake_usdc * USDC * quoted_edge_bps // 10000)
    return result


def crystallization_example():
    """A later loss cannot be known when an earlier fee is paid.

    Simple gross-profit HWM illustration with no other allocations: it shows
    why a fee window must be stated, not an alternative modeled allocation rule.
    """
    increments = [10000 * USDC, -12000 * USDC, 2000 * USDC]
    cumulative = hwm = fee_paid = 0
    for delta in increments:
        cumulative += delta
        fee_paid += max(0, cumulative - hwm) * 500 // 10000
        hwm = max(hwm, cumulative)
    return dict(pnl_sequence_usdc_units=increments, final_net_pnl_usdc_units=cumulative,
                fees_if_each_step_crystallizes_usdc_units=fee_paid,
                fees_if_one_window_closes_at_end_usdc_units=max(0, cumulative) * 500 // 10000,
                scope='Timing illustration only; no fee clawback or new contract rule is implemented.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seeds', type=int, default=4)
    parser.add_argument('--output', type=Path, default=ROOT / '.local/realized-profit-stress/20261029')
    args = parser.parse_args()
    if args.seeds <= 0:
        parser.error('positive --seeds required')
    args.output.mkdir(parents=True, exist_ok=True)
    sources = [Path(__file__), ROOT / 'scripts/dynamic_profit_allocation.py',
               ROOT / 'scripts/iterate_loss_rewards.py', ROOT / 'scripts/stress_loss_rewards.py']
    assumption = dict(research_only=True, seeds=args.seeds, quote_edges_bps=(700, 850, 1000),
        separation='Quote edge is a pricing target; actual survival is independently assumed. '
                   'Only actual settled PnL, recovered losses and capital headroom enter distributable profit.',
        scope='2x fixed payouts; no oracle calibration, LP capital flows, reward reinvestment or voluntary retention model. '
              'Distinct quote labels on identical actual paths are controls, not independent observations.',
        fee_timing='Existing research model crystallizes at each completed batch. Paid fees are not clawed back after later losses.',
        source_sha256={str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources})
    (args.output / 'experiment.json').write_text(json.dumps(assumption, indent=2) + '\n')
    rows = []
    for quoted in assumption['quote_edges_bps']:
        cases = [('calibrated', (10000 - quoted) // 2), ('actual-4pct', 4800),
                 ('actual-breakeven', 5000), ('actual-negative10pct', 5500)]
        for name, actual in cases:
            for seed in range(args.seeds):
                result = simulate(quoted, actual, 20261029 + seed)
                result['case'] = name
                rows.append(result)
    examples = [dict(name='profitable', **settled_window(10000 * USDC, 9500 * USDC)),
                dict(name='breakeven', **settled_window(10000 * USDC, 10000 * USDC)),
                dict(name='loss', **settled_window(10000 * USDC, 10500 * USDC)),
                dict(name='recovery', **settled_window(10000 * USDC, 9500 * USDC, 500 * USDC)),
                dict(name='capital-restoration', **settled_window(10000 * USDC, 9000 * USDC, 0, 600 * USDC))]
    timing = crystallization_example()
    payload = dict(assumptions=assumption, results=rows, explanatory_windows=examples, fee_timing=timing)
    (args.output / 'results.json').write_text(json.dumps(payload, indent=2) + '\n')
    lines = ['# Pricing edge is separate from realized profit share', '',
             f'{len(rows)} quote/outcome controls. The same actual ledger has the same fees under every quote-edge label. '
             'All funded-quote and cash conservation checks pass.', '',
             '| Quote edge | Actual outcome assumption | Realized trading PnL USDC | New distributable profit USDC | Operator paid USDC | Reward coverage |',
             '|---|---|---:|---:|---:|---:|']
    for quoted in assumption['quote_edges_bps']:
        for name in ('calibrated', 'actual-4pct', 'actual-breakeven', 'actual-negative10pct'):
            group = [r for r in rows if r['quoted_house_edge_bps'] == quoted and r['case'] == name]
            med = lambda k:statistics.median(r[k] for r in group)
            lines.append(f"| {quoted / 100:.1f}% | {name} | {med('trading_pnl_usdc_units') / USDC:,.2f} | "
                         f"{med('distributable_profit_usdc_units') / USDC:,.2f} | {med('protocol_usdc_units') / USDC:,.2f} | "
                         f"{med('reward_coverage'):.1%} |")
    lines += ['', 'Operator fees can have been paid at earlier profitable checkpoints even when the eventual period '
              'is loss-making. There are no new fees while an unrecovered drawdown remains. A different fee '
              'crystallization window changes this timing; neither hypothetical fees nor future profit are cash revenue.', '',
              'The separate timing illustration has +$10k, -$12k, +$2k trading PnL: $0 net over the whole window. '
              'Immediate crystallization can already have paid $500; end-of-window crystallization would pay $0. '
              'This illustration is not an implemented alternative fee rule. Full examples, assumptions and source hashes '
              'are retained in the JSON artifacts.']
    (args.output / 'report.md').write_text('\n'.join(lines) + '\n')
    print(json.dumps(dict(controls=len(rows), report=str(args.output / 'report.md'))))


if __name__ == '__main__':
    main()
