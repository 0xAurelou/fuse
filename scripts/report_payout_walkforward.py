#!/usr/bin/env python3
"""Generate an audited chronological payout report and evidence budget."""
import argparse
import json
import math
from pathlib import Path

from payout_walkforward import VARIANTS
from research_payout_risk import ASSETS, MULTIPLIERS, digest, dump


def pct(value, digits=2):
    return '—' if value is None else f'{value:.{digits}%}'


def evidence_budget(meta):
    result={}
    for asset,packet in meta.items():
        result[asset]={}
        for m in MULTIPLIERS:
            needed=math.ceil(20/(.95/m))
            result[asset][str(m)]={}
            for variant,record in packet['results'][str(m)]['variants'].items():
                if variant=='minimum_width_floor':continue
                p=record['pooled'];remaining=max(0,needed-p['offered'])
                clean=math.ceil(remaining/p['availability']) if p['availability'] else None
                result[asset][str(m)][variant]=dict(
                    required_offered_references_for_20_target_expected_wins=needed,
                    already_evaluated_offered_references=p['offered'],
                    additional_offered_references=remaining,
                    additional_clean_entries_at_same_availability=clean,
                    equivalent_2880_entry_days_at_same_availability=clean/2880 if clean is not None else None,
                    availability_assumption=p['availability'],
                    interpretation='Count budget only, not independent events, statistical power, evidence of calibration or permission to reuse inspected data as a fresh holdout')
    return result


def report(root, output):
    audit=json.loads((root/'audit.json').read_text());research=json.loads((root/'research.json').read_text())
    if not audit['passed'] or audit['research_sha256']!=digest(root/'research.json'):
        raise ValueError('matching completed audit required')
    checks=json.loads((root/'verification.json').read_text())
    if checks['suite_exit_code']!=0 or digest(root/'tests.log')!=checks['tests_log_sha256'] or checks['audit_sha256']!=digest(root/'audit.json'):
        raise ValueError('verification evidence differs')
    assets={a:json.loads((root/a/'research.json').read_text()) for a in ASSETS}
    for a in ASSETS:
        if digest(root/a/'research.json')!=research['research_sha256'][a]:raise ValueError('asset result binding differs')
    budget=evidence_budget(assets)
    if not (root/'evidence-budget.json').exists():dump(root/'evidence-budget.json',budget)
    elif json.loads((root/'evidence-budget.json').read_text())!=budget:raise ValueError('evidence budget differs')
    qualifiers={a:{m:p['qualifying_variants'] for m,p in v['results'].items()} for a,v in assets.items()}
    any_qualifies=any(names for v in qualifiers.values() for names in v.values())
    lines=['# ETH/HYPE payout walk-forward research — 29 October 2026','',
        ('Some variants meet the necessary development screens; none is promoted.' if any_qualifies else
         'No tested pricing variant meets all necessary development screens. The larger chronological replay still does not establish deployable 100× or 1,000× pricing.'),
        '', '## What changed','',
        'The evaluation now expands through time. After six warmup dates, every later sampled date is scored once per asset/payout/variant. Every origin refits both risk coefficients and movement distributions from all strictly earlier, matured paths of that asset. The old train/validation/test labels do not control these fits. No previous final coefficients, selected risk family, payout widths or future-selected policy are reused.','',
        'This is a broader evaluation of an already inspected development archive. It is not new market data or a new holdout. [Tardis raw API documentation](https://docs.tardis.dev/api/http-api-reference) makes first-of-month histories available without an API key; the archive therefore consists of sampled full days separated by monthly gaps. No continuous history, paid access or unattended capture was added.','',
        '| Asset | Warmup dates | Scored dates | Scored UTC range | Unique grid entries | Clean paths | Weekend / weekday dates |',
        '| --- | ---: | ---: | --- | ---: | ---: | ---: |']
    from datetime import date
    for asset,p in assets.items():
        dates=p['evaluated_dates'];weekends=sum(date.fromisoformat(d).weekday()>=5 for d in dates)
        lines.append(f"| {asset} | {len(p['warmup_dates'])} | {len(dates)} | {dates[0]}–{dates[-1]} | {p['unique_evaluated_entries']:,} | {p['results']['100']['floor']['eligible']:,} | {weekends} / {len(dates)-weekends} |")
    lines += ['',
        'The paired fixed models use oracle timing/activity features, with or without UTC weekend/hour features, at ridge 0.003. Each is evaluated raw and with prior-32 score-bin calibration. Calibration receives all clean earlier walk-forward forecasts, including refused paths. It never receives own-date forecasts or fitted in-sample forecasts. Supported bins still require at least 200 paths across three earlier dates; otherwise raw probabilities remain. Coefficients and calibration are frozen for the entire scored date.','',
        'Positive movement widths use the exact date-weighted empirical CDF of required width divided by slow volatility, grouped by pre-entry activity state and shrunk toward the global positive CDF. Local groups require 200 positive paths across three dates; otherwise the parent is used. The requested positive quantile is `(0.95/M − predicted_floor)/(1 − predicted_floor)`. Quotes require forecast floor at most target and at least twenty global count-times-positive-quantile training references. Neither this support rule nor the 85% daily availability reference is relaxed.','',
        'The one-ppm open corridor is a lower-bound diagnostic only. Its win rate is the unavoidable floor for this research width bound, not a calibrated payout model. Zero movement is the separate floor applying to every valid positive corridor.','',
        '## Chronological quote results','',
        'Targets are 0.95% at 100× and 0.095% at 1,000×. The zero-cost break-even rates are 1% and 0.1%. “Kept” is measured among paths with a healthy resolved label and available entry history; quote admission itself cannot see that future health label. Pre-entry and resolved counts are retained separately. Each row is a fixed comparison, not a selected winner.','',
        '| Asset | Payout | Fixed variant | Kept | Worst date kept | Wins / kept | Win rate | Target-expected wins |',
        '| --- | ---: | --- | ---: | ---: | ---: | ---: | ---: |']
    for asset in ASSETS:
        for m in MULTIPLIERS:
            for variant in VARIANTS[1:]:
                r=assets[asset]['results'][str(m)]['variants'][variant];p=r['pooled']
                lines.append(f"| {asset} | {m:,}× | {variant} | {pct(p['availability'])} | {pct(r['minimum_daily_availability'])} | {p['wins']} / {p['offered']:,} | {pct(p['survival'],4)} | {p['target_expected_wins']:.2f} |")
    eth=assets['ETH']['results']['1000']['variants']['timing_cal32_cdf']['pooled']
    hype=assets['HYPE']['results']['1000']['variants']['timing_cal32_cdf']['pooled']
    lines += ['',
        f"For the fixed calibrated timing comparison at 1,000×, ETH retains {pct(eth['availability'])} of clean paths but has {eth['wins']} wins in {eth['offered']:,} quotes ({pct(eth['survival'],4)} versus the 0.095% target). HYPE retains {pct(hype['availability'])}, with {hype['wins']} wins in {hype['offered']:,} quotes ({pct(hype['survival'],4)}). HYPE’s pooled rate is near the target reference band, but sparse availability, empty dates and only {hype['target_expected_wins']:.2f} target-expected wins still fail the screens. These rows do not select the timing family or establish future performance."]
    lines += ['',
        'The same necessary descriptive screens now apply to every fixed walk-forward variant: nonempty quotes on every scheduled date, at least 85% availability on every date, pooled survival within 75–125% of target, nonnegative zero-cost equal-stake gross arithmetic, and at least twenty target-expected wins. These screens do not establish confidence, conditional calibration, joint liability coverage, or net LP returns. Failures and all daily summaries are retained in each asset’s research packet.','',
        'Early 1,000× origins can have too few positive training paths even if predicted floor were zero. Those dates are retained as real refusals in the scheduled evaluation. Later data cannot retroactively make an earlier quote sufficiently supported. The twenty-reference training-tail screen and twenty target-expected evaluated wins are separate requirements.','',
        '## Does a weekend term help?','',
        'The table scores minimum-width probability on all clean reference paths, including paths a pricing rule refused. Lower log loss is better. Paired calendar comparisons share the same origins and ridge; no calendar variant is selected from the observed results.','',
        '| Asset | Risk forecast | All-path floor log loss | Weekday floor log loss | Weekend floor log loss |',
        '| --- | --- | ---: | ---: | ---: |']
    for asset in ASSETS:
        for variant in VARIANTS[1:]:
            r=assets[asset]['results']['100']['variants'][variant]
            values=[r['all_reference_risk']['floor_log_loss']]+[r['calendar_groups'][g]['all_reference_risk']['floor_log_loss'] for g in ('weekday','weekend')]
            lines.append(f"| {asset} | {variant} | "+' | '.join('—' if x is None else f'{x:.6f}' for x in values)+' |')
    lines += ['',
        '| Asset | Calendar group | Clean paths | Zero-motion wins | Minimum-width wins | Minimum-width survival |',
        '| --- | --- | ---: | ---: | ---: | ---: |']
    for asset in ASSETS:
        groups=assets[asset]['results']['100']['variants']['minimum_width_floor']['calendar_groups']
        for group,r in groups.items():
            p=r['pooled'];lines.append(f"| {asset} | {group} | {p['eligible']:,} | {p['zero_wins']} | {p['wins']} | {pct(p['survival'],4)} |")
    weekend_wins={a:{g:r['pooled']['wins'] for g,r in assets[a]['results']['1000']['variants']['timing_cal32_cdf']['calendar_groups'].items()} for a in ASSETS}
    lines += ['',
        f"In the fixed calibrated timing 1,000× comparison, ETH has {weekend_wins['ETH']['weekend']} weekend wins and {weekend_wins['ETH']['weekday']} weekday wins. HYPE has {weekend_wins['HYPE']['weekend']} weekend wins and {weekend_wins['HYPE']['weekday']} weekday wins. The weekend-only explanation does not fit either complete cohort; quote counts, rates and daily clustering must accompany win counts."]
    lines += ['',
        'Weekend is a timestamp feature, not a measured liquidity state. This study has no spread, depth, trade volume or execution-cost measurements. Monthly sampling and a handful of weekend dates cannot establish that liquidity caused a win cluster or that a calendar coefficient will transfer to future weekends.','',
        '## Oracle floor and evidence budget','',
        'For N paths and Z unavoidable flat winners, retaining K quotes leaves at least `max(0, Z − (N − K))` winners, even with perfect hindsight about which paths to reject. A target win probability q therefore requires `K ≤ floor((N − Z)/(1 − q))`, capped at N. The code uses exact integer arithmetic. This is an optimistic historical ceiling, never an achievable pre-entry policy or probability guarantee. Daily ceilings are retained as well.','',
        '| Asset | Payout | All clean paths | Universal zero-motion floor | Most quotes possible at target, even with hindsight | All-quotes target-expected wins |',
        '| --- | ---: | ---: | ---: | ---: | ---: |']
    for asset in ASSETS:
        for m in MULTIPLIERS:
            f=assets[asset]['results'][str(m)]['floor']
            lines.append(f"| {asset} | {m:,}× | {f['eligible']:,} | {pct(f['zero_motion_rate'],4)} | {f['universal_maximum_kept_at_target']:,} | {f['target_expected_wins_if_all_offered']:.2f} |")
    lines += ['',
        'Twenty target-expected wins require at least 2,106 offered paths at 100× or 21,053 at 1,000×. These are count references, not sample-size calculations for independent confidence intervals. `evidence-budget.json` records additional offered paths and clean-entry equivalents at each observed availability. Those projections assume unchanged retention and full 2,880-entry days; they cannot substitute for newly observed data, independent market episodes or prospective evaluation. A policy with zero availability has no finite estimate under that assumption.','',
        'The next data-dependent decision requires consecutive, newly observed weekday and weekend sessions, followed by a frozen-policy evaluation. A liquidity hypothesis also requires synchronized depth/spread/volume observations. This iteration establishes the chronological replay and evidence accounting needed for that test; the current archive cannot answer the liquidity-causality question.','',
        '## Verification and reproduction','',
        f"Archive: `{root.as_posix()}`. The audit checks {sum(p['origins'] for p in audit['assets'])} fitted origins and independently replays {sum(p['trace_rows'] for p in audit['assets']):,} saved decisions. It refits every saved risk coefficient from earlier labels, reconstructs calibration populations and monotone maps, verifies every positive CDF point/date weight, checks unique scoring entries and reconciles pooled/daily/calendar metrics and screens.",'',
        f"Seven focused tests cover own/future-label exclusion, duplicate/maturity rejection, pre-entry admission, exhaustive floor-bound arithmetic, empty-quote handling and end-to-end export/audit/tamper rejection. The full Python suite ran {checks['full_suite_tests']} tests with {checks['skipped']} skips; all others passed. No live pricing or running capture was changed.",'',
        '```sh',
        'python3 -B scripts/research_payout_walkforward.py --declare --parent .local/adaptive-corridor/20261028-ETH-HYPE-raw-fits-v2 --output .local/adaptive-corridor/NEW-WALKFORWARD',
        'OPENBLAS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 python3 -B scripts/research_payout_walkforward.py --output .local/adaptive-corridor/NEW-WALKFORWARD',
        'OPENBLAS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 python3 -B scripts/audit_payout_walkforward.py --research .local/adaptive-corridor/NEW-WALKFORWARD',
        'python3 -B -m unittest discover -s scripts -p test_payout_walkforward.py',
        '```','']
    output.write_text('\n'.join(lines));return dict(report=str(output),sha256=digest(output))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--research',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();print(json.dumps(report(args.research,args.output),indent=2))
