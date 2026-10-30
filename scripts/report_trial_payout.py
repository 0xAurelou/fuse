#!/usr/bin/env python3
"""Render the audited weekday/weekend payout backtest without choosing a winner."""
import argparse
import json
from pathlib import Path

from research_payout_risk import digest


def rate(value):return '—' if value is None else f'{value:.2%}'


def count_rate(p):return f"{p['wins']:,} / {p['offered']:,} ({rate(p['survival'])})"


def report(root):
    meta=json.loads((root/'research.json').read_text());audit=json.loads((root/'audit.json').read_text());plan=json.loads((root/'protocol.json').read_text())
    if not audit['passed'] or audit['research_sha256']!=digest(root/'research.json') or meta['protocol_sha256']!=digest(root/'protocol.json'):
        raise ValueError('Matching successful payout audit required')
    results={}
    for a,sha in meta['research_sha256'].items():
        if digest(root/a/'research.json')!=sha:raise ValueError('Payout asset binding differs')
        results[a]=json.loads((root/a/'research.json').read_text())
    lines=['# Consecutive ETH and HYPE 100x and 1000x corridor backtests','',
        'These backtests quote and settle actual thirty-second corridors on September 1–10, 2026 UTC oracle paths. They compare trader survival, quote availability and equal-stake LP gross arithmetic on eight weekday dates and two weekend dates, September 5 and 6. Each asset has 28,800 fixed grid entries; unresolved paths remain excluded from outcome arithmetic. This is historical development on already inspected data.', '']
    qualifying={a:{m:r['qualifying_variants'] for m,r in v['results'].items()} for a,v in results.items()}
    if not any(v for a in qualifying.values() for v in a.values()):
        lines+=['No tested variant passes all existing necessary development screens at either payout. The native formula and fitted research models remain separate comparisons; no live formula was changed.','']
    else:lines+=['Any passing descriptive screens are recorded in the research packet; they do not establish prospective calibration or net profitability.','']
    rates=[v['results'][m]['variants']['shipped_formula']['matched'][g]['pooled']['survival'] for v in results.values() for m in ('100','1000') for g in ('weekday','weekend')]
    lines += [f"The shipped fixed-volatility control has trader win rates of {min(rates):.2%}–{max(rates):.2%}, far above either payout target. Its corridors are too wide for these observed oracle paths under the shipped volatility assumptions.",'']
    for a,r in results.items():
        s=r['results']['100']['variants']['calendar_liquidity_raw_cdf']['matched'];d=s['weekday']['pooled'];w=s['weekend']['pooled']
        lines += [f"At 100×, the fixed fitted calendar-plus-liquidity model gives {a} weekday survival of {rate(d['survival'])} with {rate(d['availability'])} availability, versus weekend survival of {rate(w['survival'])} with {rate(w['availability'])} availability. The target is 0.95%.",'']
    lines+=['## Quote and settlement rules','',
        'The shipped-formula control uses `brownian-first-mode-v1`, a five percent target edge and the shipped thirty-second volatility assumptions: ETH 1,500 ppm and HYPE 3,000 ppm. Its Q12 logarithm, integer square root and downward ppb quantization match all ninety retained native pricing reference vectors. It is an assumption-based formula control, rather than a fitted probability guarantee.','',
        'The research corridors reuse the previous audited daily earlier-only risk coefficients, separately for each asset. Their positive movement CDF is refitted at each daily origin from the same matched earlier paths: twenty first-of-month dates from January 2025 through August 2026, followed by matured preceding trial dates. Calibrated controls use only earlier out-of-sample monthly raw forecasts and matured prior trial forecasts. Current-date outcomes never enter coefficients, movement widths or calibration. The last two previous-day windows are withheld when their expiry plus thirty seconds has not passed the origin.','',
        'The primary fixed comparison is calendar plus oracle activity versus the same model plus measured liquidity, both raw. Activity-only and prior-32 calibrated variants are retained as fixed controls, together with the one-ppm minimum-width diagnostic. All ten variants are saved; none is selected from the payout results. Research CDF quotes use the existing slow-volatility anchor, activity groups, one-ppm minimum, 50,000-ppm maximum, risk gate at the target and at least twenty positive-tail training references. Unsupported quotes are refused.','',
        'All variants share the five-minute pre-entry research-history requirement. A trader wins only if every observed oracle price stays strictly inside both integer barriers for the full thirty seconds. Touching a barrier loses. The shipped control retains ppb widths; empirical research widths retain their existing integer ppm quantization. Original freshness and disconnect exclusions apply. Pre-entry offers and subsequently unresolved offers are retained separately, so a future outage cannot become an admission feature.','',
        'This is an oracle-path formula replay. It does not reproduce dual-receiver canonical admission, order acceptance latency, account limits, aggregate underwriting capacity or a native engine journal.','',
        '| Total payout | Target trader win rate at five percent edge | Zero-cost LP break-even trader win rate |',
        '| --- | ---: | ---: |','| 100× | 0.950% | 1.000% |','| 1,000× | 0.095% | 0.100% |','',
        'A total payout includes the returned stake. For N accepted resolved one-unit stakes and W trader wins, LP gross is `N − M × W`; gross per stake is `1 − M × W / N`. A negative percentage can exceed a one-stake loss because one winner receives many stakes. This arithmetic excludes costs, funding, hedging, capital limits and loss correlation. Zero quotes produce no estimated win rate or return.','',
        '## Weekday and weekend comparison','',
        'The primary table uses the same clean oracle paths with fresh pre-entry books for every variant. “Kept” is accepted resolved quotes divided by those eligible paths. A strategy can reduce wins by quoting fewer times, so counts and availability accompany every win rate.','']
    primary=('shipped_formula','calendar_raw_cdf','calendar_liquidity_raw_cdf')
    labels={'shipped_formula':'Shipped formula','calendar_raw_cdf':'Fitted calendar','calendar_liquidity_raw_cdf':'Fitted calendar plus liquidity'}
    for a,r in results.items():
        lines += [f'### {a}','',f"{r['matched_clean_paths']:,} matched clean paths, versus {r['all_clean_paths']:,} clean oracle paths before requiring a book.",'',
            '| Payout | Model | Weekday wins / quotes and rate | Weekday kept | Weekend wins / quotes and rate | Weekend kept | Weekday LP gross per stake | Weekend LP gross per stake |',
            '| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |']
        for m in ('100','1000'):
            for v in primary:
                values=r['results'][m]['variants'][v]['matched'];d=values['weekday']['pooled'];w=values['weekend']['pooled']
                lines.append(f"| {int(m):,}× | {labels[v]} | {count_rate(d)} | {rate(d['availability'])} | {count_rate(w)} | {rate(w['availability'])} | {rate(d['gross_lp_per_stake'])} | {rate(w['gross_lp_per_stake'])} |")
        lines.append('')
    lines+=['## All fixed variants','',
        'The following pooled matched-path results include every fixed variant and payout. The one-ppm row is an always-open lower-bound diagnostic and cannot qualify as a calibrated payout rule. “Worst day kept” includes empty quote dates. Full daily and weekday/weekend breakdowns for every row are retained in each asset research JSON.','',
        '| Asset | Payout | Variant | Wins / quotes and rate | Kept | Worst day kept | Target expected wins | LP gross per stake | Passes screens |',
        '| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | --- |']
    for a,r in results.items():
        for m,vv in r['results'].items():
            for v,values in vv['variants'].items():
                s=values['matched']['overall'];p=s['pooled']
                lines.append(f"| {a} | {int(m):,}× | {v} | {count_rate(p)} | {rate(p['availability'])} | {rate(s['minimum_daily_availability'])} | {p['target_expected_wins']:.2f} | {rate(p['gross_lp_per_stake'])} | {'Yes' if values['screen']['qualifies'] else 'No'} |")
    lines+=['','## Missing book sensitivity','',
        'This secondary comparison includes every clean oracle path. Missing books remain in the availability denominator and cause the liquidity variants to refuse quotes. Outcomes are never filled with zero; baseline models can still quote without a book. All variants retain identical earlier matched training cohorts, so this measures entry-book availability rather than a second choice of training data.','',
        '| Asset | Payout | Model | Weekday wins / quotes and rate | Weekday kept | Weekend wins / quotes and rate | Weekend kept |',
        '| --- | --- | --- | ---: | ---: | ---: | ---: |']
    for a,r in results.items():
        for m in ('100','1000'):
            for v in primary:
                values=r['results'][m]['variants'][v]['all_clean'];d=values['weekday']['pooled'];w=values['weekend']['pooled']
                lines.append(f"| {a} | {int(m):,}× | {labels[v]} | {count_rate(d)} | {rate(d['availability'])} | {count_rate(w)} | {rate(w['availability'])} |")
    lines+=['','## Limits and verification','',
        'The existing necessary screens require quotes on every date, at least 85 percent availability on every date, pooled survival within 75–125 percent of target, nonnegative zero-cost LP gross and at least twenty target-expected evaluated wins. These are descriptive checks, not an independent-event confidence test. At 1,000×, twenty target-expected wins require at least 21,053 accepted resolved quotes. Most refused-entry policies cannot supply that budget in ten dates.','',
        'Only one Saturday and one Sunday are included. Consecutive days can share market regimes, and these outcomes were already inspected for oracle and liquidity research. Calendar differences cannot identify liquidity as the cause. A small improvement in a probability loss metric does not by itself establish payout calibration, availability or positive LP arithmetic.','',
        f"The audit passed. It refitted {sum(a['risk_models_refit'] for a in audit['assets'])} earlier-only risk models, verified every positive CDF point/date weight and calibration population, independently replayed {sum(a['decisions_replayed'] for a in audit['assets']):,} quote decisions, and reconciled all calendar, daily and cohort summaries. The source oracle packet remains bound to its earlier successful 57,600-row reconstruction audit and the hashes of 1,440 raw slices. Five focused tests cover all ninety native vectors, exact barrier touches, future-outcome independence, tail support, missing-book denominators, midnight maturity, complete export/audit and tamper rejection.",'',
        f"Research packet: `{root.resolve()}`. Input oracle/liquidity packet: `{plan['liquidity']}`. Each asset retains every daily origin model and all grid decisions, including refused and unresolved entries. The protocol freezes the full Python source closure and native pricing source/vectors before the payout replay. The live policy and fresh collector were not changed.",'',
        '```sh','PYTHONPATH=scripts OPENBLAS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 python3 -B -m unittest scripts.test_trial_payout',
        f"python3 -B scripts/research_trial_payout.py --declare --liquidity {plan['liquidity']} --output .local/adaptive-corridor/NEW-CONSECUTIVE-PAYOUT",
        'OPENBLAS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 python3 -B scripts/research_trial_payout.py --output .local/adaptive-corridor/NEW-CONSECUTIVE-PAYOUT',
        'OPENBLAS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 python3 -B scripts/research_trial_payout.py --audit --output .local/adaptive-corridor/NEW-CONSECUTIVE-PAYOUT','```','',
        f"Research SHA-256: `{digest(root/'research.json')}`. Audit SHA-256: `{digest(root/'audit.json')}`.",'']
    return '\n'.join(lines)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--research',type=Path,required=True);parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    args.output.write_text(report(args.research));print(args.output)
