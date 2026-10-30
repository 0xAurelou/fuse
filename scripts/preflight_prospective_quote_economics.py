#!/usr/bin/env python3
"""Retained synthetic end-to-end check of supplemental paper economics."""
import argparse
from collections import defaultdict
import json
from pathlib import Path
import shutil

import prospective_adaptive_quote_economics as paper
from test_prospective_adaptive_quote_economics import stage_synthetic, publish_synthetic


def preflight(fixture, historical, output):
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    for path in (Path(__file__), Path(paper.__file__),
                 Path(__file__).with_name('test_prospective_adaptive_quote_economics.py')):
        shutil.copyfile(path, output/path.name)
    packet, protocol = stage_synthetic(output, fixture, historical)
    publish_synthetic(packet, fixture)
    result = paper.run(packet)
    if not result['software_fixture']:
        raise ValueError('economics preflight is not a software fixture')
    with (packet/'cases.jsonl').open() as stream:
        cases = [json.loads(line) for line in stream]
    expenses = 0
    index = {}
    partitions = defaultdict(dict)
    additive = ('selected_grid_entries', 'placed_tickets', 'resolved_grid_entries',
                'censored_grid_entries', 'survived_grid_entries',
                'lp_gross_assuming_censored_refund_usdc_units', 'customer_gross_usdc_units')
    for case in cases:
        selected, known, wins, unknown, accounts = (case[k] for k in (
            'selected_grid_entries', 'resolved_grid_entries', 'survived_grid_entries',
            'censored_grid_entries', 'accounts'))
        gross = accounts*1_000_000*(known-2*wins)
        if (selected != known+unknown or case['placed_tickets'] != accounts*selected or
                case['lp_gross_assuming_censored_refund_usdc_units'] != gross or
                case['customer_gross_usdc_units'] != -gross):
            raise ValueError('independent cash or ticket conservation differs')
        key = (case['mode'], case['candidate'], case['interval'], case['strategy'], accounts)
        if key in index:
            raise ValueError('duplicate economics case')
        index[key] = case
        if accounts == 1:
            partitions[key[:3]][case['strategy']] = case
        for cost in case['cost_sensitivity']:
            allocated = accounts*selected*1_000_000*cost['expense_bps']//10000
            net = gross-allocated
            lower = net-unknown*accounts*1_000_000
            upper = net+unknown*accounts*1_000_000
            if (cost['allocated_expense_usdc_units'] != allocated or
                    cost['lp_net_assuming_censored_refund_usdc_units'] != net or
                    cost['lp_net_lower_if_all_censored_survive_usdc_units'] != lower or
                    cost['lp_net_upper_if_all_censored_fail_usdc_units'] != upper):
                raise ValueError('expense or censorship bound differs')
            break_even = .5-allocated/(2*known*accounts*1_000_000) if known else None
            if cost['resolved_survival_break_even_with_placed_expense'] != break_even:
                raise ValueError('censor-aware break-even differs')
            expenses += 1
    scalings, partition_checks = 0, 0
    for key, three in index.items():
        if key[-1] == 3:
            one = index[(*key[:-1], 1)]
            for field in ('placed_tickets', 'lp_gross_assuming_censored_refund_usdc_units', 'customer_gross_usdc_units'):
                if three[field] != 3*one[field]:
                    raise ValueError('synchronized account scaling differs')
            scalings += 1
    for group in partitions.values():
        for a, b in (('frozen_only', 'nonfrozen_only'), ('width_at_most_10ppm', 'width_over_10ppm')):
            for field in additive:
                if group[a][field]+group[b][field] != group['all_offered'][field]:
                    raise ValueError('complementary strategy partition differs')
                partition_checks += 1
    report = dict(completed=True, software_only=True, prospective_market_evidence=False,
        live_receipts_read=False, new_live_capture_started=False,
        artificial_preparation_clock=True, original_trial_failure_preserved=True,
        cases_checked=len(cases), cost_cases_checked=expenses,
        account_scalings_checked=scalings, strategy_partition_checks=partition_checks,
        quote_decisions=result['quote_decisions'], economics_validated=False,
        files_sha256={str(p.relative_to(output)):paper.sha(p) for p in output.rglob('*') if p.is_file()})
    paper.write(output/'preflight.json', report)
    print(json.dumps({k:v for k,v in report.items() if k != 'files_sha256'}, indent=2))
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fixture', type=Path, required=True)
    parser.add_argument('--historical', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    preflight(args.fixture.resolve(), args.historical.resolve(), args.output)
