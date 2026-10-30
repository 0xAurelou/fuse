#!/usr/bin/env python3
"""Check diagnostic cash/coverage and report it; no independent path audit."""
import argparse
from collections import Counter
from fractions import Fraction
import json
from pathlib import Path
import shutil

from diagnose_release_empirical import SPEC,verify
from release_pricing import ASSETS,DAY,DELAYS,EDGES,GRID,PAYOUTS
from research_release_pricing import ROOT,read,sha,write

ADDITIVE=('grid','oracle_quote_available','quote_available','accepted','censored','resolved','wins',
    'flat_wins','moving_wins','touch_losses','other_losses','flat_payout_usdc_units','moving_payout_usdc_units',
    'gross_lp_refund_usdc_units','gross_lp_if_censored_all_fail_usdc_units',
    'flat_only_lp_upper_usdc_units','after_hindsight_flat_removal_lp_upper_usdc_units')
RATIONAL=('historical_expected_wins','target_expected_wins','observed_minus_historical_wins')
CASH=('grid','oracle_quote_available','quote_available','accepted','censored','resolved','wins',
    'gross_lp_refund_usdc_units','gross_lp_if_censored_all_fail_usdc_units')


def require(ok,message):
    if not ok:raise ValueError(message)


def fraction(value):
    return Fraction(value['numerator'],value['denominator']) if value is not None else Fraction(0)


def check_row(r):
    require(all(type(r[k]) is int for k in ADDITIVE) and all(r[k]>=0 for k in ADDITIVE[:13]),'invalid diagnostic count')
    n,c,f,w=r['resolved'],r['censored'],r['flat_wins'],r['moving_wins']
    m,e=r['multiplier'],r['edge_bps']
    require(n+c==r['accepted']<=r['quote_available']<=r['oracle_quote_available']<=r['grid'],'placement denominator differs')
    require(f+w==r['wins'] and r['wins']+r['touch_losses']+r['other_losses']==n,'diagnostic win/loss partition differs')
    require(r['flat_payout_usdc_units']==m*f*10**6 and r['moving_payout_usdc_units']==m*w*10**6,'diagnostic payout differs')
    require(r['gross_lp_refund_usdc_units']==n*10**6-r['flat_payout_usdc_units']-r['moving_payout_usdc_units'],'diagnostic gross differs')
    require(r['gross_lp_if_censored_all_fail_usdc_units']==(n+c-m*(f+w))*10**6,'diagnostic censor bound differs')
    require(r['flat_only_lp_upper_usdc_units']==(n+c-m*f)*10**6,'diagnostic flat bound differs')
    require(r['after_hindsight_flat_removal_lp_upper_usdc_units']==(n-f+c-m*w)*10**6,'diagnostic moving bound differs')
    require(r['current_probability_validated'] is False,'diagnostic promoted to probability validation')
    if n:
        target=Fraction(n*(10000-e),10000*m);historical=fraction(r['historical_expected_wins'])
        require(all(r[k] is not None for k in RATIONAL) and 0<=historical<=target,'historical support differs')
        require(fraction(r['target_expected_wins'])==target and fraction(r['observed_minus_historical_wins'])==f+w-historical,'historical expectation differs')
    else:require(all(r[k] is None for k in RATIONAL),'empty cohort has probability estimate')
    groups=r['offered_training_groups']
    require(set(groups)<={'exact','activity','global'} and all(type(v) is int and v>=0 for v in groups.values()) and sum(groups.values())==r['quote_available'],'training groups differ')
    lo,hi=r['newest_training_label_age_min_ms'],r['newest_training_label_age_max_ms']
    require((isinstance(lo,int) and isinstance(hi,int) and 0<lo<=hi) if r['quote_available'] else lo is None and hi is None,'training maturity age differs')


def check_sum(target,parts):
    require(all(target[k]==sum(p[k] for p in parts) for k in ADDITIVE),'diagnostic partition/pooled counts differ')
    for k in RATIONAL:require(fraction(target[k])==sum((fraction(p[k]) for p in parts),Fraction(0)),'diagnostic pooled rational differs')
    groups=Counter()
    for p in parts:groups.update(p['offered_training_groups'])
    require(dict(groups)==target['offered_training_groups'],'diagnostic pooled training groups differ')
    available=[p for p in parts if p['quote_available']]
    lo=min((p['newest_training_label_age_min_ms'] for p in available),default=None)
    hi=max((p['newest_training_label_age_max_ms'] for p in available),default=None)
    require((lo,hi)==(target['newest_training_label_age_min_ms'],target['newest_training_label_age_max_ms']),'diagnostic pooled ages differ')


def inspect(output):
    output=Path(output);plan=verify(output);result=read(output/'result.json')
    require(result['protocol_sha256']==sha(output/'protocol.json') and result['daily_sha256']==sha(output/'daily.jsonl'),'diagnostic artifact changed')
    require(result['post_result_diagnostic'] is True and all(result[k] is False for k in ('new_model_evaluated','fresh_holdout','production_pricing_validated','goal_complete')),'diagnostic scope changed')
    require(result['days']==plan['days'] and len(result['days'])==len(set(result['days'])),'diagnostic calendar changed')
    keys={(a,m,e,d,g) for a in ASSETS for m in PAYOUTS for e in EDGES for d in DELAYS for g in SPEC['groups']}
    with (output/'daily.jsonl').open() as f:daily=[json.loads(l) for l in f]
    indexed={(r['day'],r['asset'],r['multiplier'],r['edge_bps'],r['delay_ms'],r['group']):r for r in daily}
    require(len(daily)==len(indexed)==len(keys)*len(plan['days'])==result['daily_diagnostic_cases'],'diagnostic daily coverage differs')
    require(set(indexed)=={(day,*k) for day in plan['days'] for k in keys},'diagnostic daily configuration differs')
    summary={(r['asset'],r['multiplier'],r['edge_bps'],r['delay_ms'],r['group']):r for r in result['summary']}
    require(len(summary)==len(result['summary']) and set(summary)==keys,'diagnostic summary coverage differs')
    for r in [*daily,*result['summary']]:check_row(r)
    for day in plan['days']:
        for a,m,e,d,g in keys:
            if g!='all':continue
            key=day,a,m,e,d
            check_sum(indexed[(*key,'all')],[indexed[(*key,s)] for s in SPEC['groups'][1:]])
    for k,r in summary.items():check_sum(r,[indexed[(day,*k)] for day in plan['days']])
    parent=Path(plan['parent']);parent_result=read(parent/'result.json')
    original={(r['asset'],r['multiplier'],r['edge_bps'],r['delay_ms']):r for r in parent_result['summary'] if r['strategy']=='all_offered'}
    for k,r in summary.items():
        if k[-1]=='all':require(all(r[n]==original[k[:-1]][n] for n in CASH),'diagnostic parent cash differs')
    expected=len(plan['days'])*len(ASSETS)*len(PAYOUTS)*len(EDGES)*len(DELAYS)*DAY//GRID
    require(result['delayed_forecasts']==expected,'diagnostic forecast coverage differs')
    return result


def report(output):
    output=Path(output)
    if any((output/n).exists() for n in ('report.md','checks.json','manifest.json')):raise FileExistsError('preserve diagnostic report')
    result=inspect(output)
    rows=[r for r in result['summary'] if r['group']=='all' and r['delay_ms']==0]
    offered=[r for r in rows if r['quote_available']]
    facts=dict(immediate_configurations=len(rows),immediate_with_offers=len(offered),
        immediate_no_offers=sum(not r['quote_available'] for r in rows),
        flat_alone_lp_best_case_negative=sum(r['flat_only_lp_upper_usdc_units']<0 for r in offered),
        after_perfect_hindsight_flat_removal_lp_best_case_negative=sum(r['after_hindsight_flat_removal_lp_upper_usdc_units']<0 for r in offered),
        observed_wins_above_historical_expectation=sum(fraction(r['observed_minus_historical_wins'])>0 for r in offered),
        newest_training_label_age_min_ms=min((r['newest_training_label_age_min_ms'] for r in offered),default=None),
        newest_training_label_age_max_ms=max((r['newest_training_label_age_max_ms'] for r in offered),default=None))
    age_text=(f"The newest matured label used for offers is between {facts['newest_training_label_age_min_ms']/DAY:.3f} "
        f"and {facts['newest_training_label_age_max_ms']/DAY:.3f} days old at quote time. "
        'This measures the newest training label, not oracle receipt freshness. Sparse nonconsecutive '
        'sampling leaves the model without recent regime evidence; age alone does not prove the '
        'cause of an individual pricing error.') if offered else 'No quotes were offered; training-label age is unavailable.'
    lines=['# Rejected empirical challenger: error attribution','',
        '**Production pricing validated: NO. This is a post-result diagnostic, not a new candidate or holdout.**','',
        f"All {result['delayed_forecasts']:,} delayed asset/payout/edge forecasts are retained in "
        f"{result['daily_diagnostic_cases']:,} daily cases, partitioned by pre-entry activity. "
        f"They reuse {len(result['days'])*len(ASSETS)*DAY//GRID:,} distinct asset/grid observations from the previously audited challenger.", '',
        f"{facts['immediate_with_offers']} immediate configurations receive quotes; "
        f"{facts['immediate_no_offers']} receive none. Realized wins exceed the selected historical "
        f"survivor fractions in all {facts['observed_wins_above_historical_expectation']} offered configurations. "
        'Those fractions are development estimates, not independently calibrated probabilities.', '',
        f"Flat paths alone make {facts['flat_alone_lp_best_case_negative']} configurations lose "
        'even if every other accepted ticket loses for the player. Granting a perfect hindsight '
        f"filter that removes all realized flat paths still leaves {facts['after_perfect_hindsight_flat_removal_lp_best_case_negative']} "
        'configurations losing on their unchanged moving-path corridors, even if every censored '
        'ticket loses for the player. These two groups can overlap. The hindsight filter is not '
        'an executable pre-entry policy.', '',
        age_text, '',
        '## 850-bps midpoint, immediate entries','',
        'One-USDC hypothetical tickets; the last two columns grant player losses on every '
        'censored ticket. Gross excludes fees, rewards, execution and operating costs. '
        'All four edge settings and all delays remain in result.json.', '',
        '| Asset | Payout | Realized wins | Historical expected wins | Flat / moving wins | Flat-only LP upper ($) | After flat removal LP upper ($) |',
        '| --- | ---: | ---: | ---: | ---: | ---: | ---: |']
    for r in rows:
        if r['edge_bps']!=850:continue
        if not r['quote_available']:
            lines.append(f"| {r['asset']} | {r['multiplier']} | Unavailable | — | — | — | — |")
        else:
            lines.append(f"| {r['asset']} | {r['multiplier']} | {r['wins']:,} | {float(fraction(r['historical_expected_wins'])):,.2f} | "
                f"{r['flat_wins']:,} / {r['moving_wins']:,} | {r['flat_only_lp_upper_usdc_units']/1e6:,.0f} | "
                f"{r['after_hindsight_flat_removal_lp_upper_usdc_units']/1e6:,.0f} |")
    lines+=['','## Consequence for the replacement model','',
        'A flat-risk gate alone is insufficient. A replacement needs recent or demonstrably '
        'transferable references, calibrated positive-movement tails, explicit refusal/support '
        'for every asset/payout, and a frozen fresh native evaluation. No feature or threshold '
        'is selected from these diagnostics. Wide support and a nonempty quote set remain '
        'separate from measured margin; no release-menu change is approved.', '',
        'The checker verifies complete configuration coverage, exact rational aggregation, '
        'cash partitions, maturity-age summaries and reconciliation to the software-audited parent. '
        'It does not independently reconstruct raw path classifications or refit a model. '
        'The parent retains its separate full path/forecast software audit. Neither checker '
        'is independent external pricing review. All ten release gates remain open.','']
    (output/'report.md').write_text('\n'.join(lines))
    shutil.copyfile(__file__,output/'report-source.py')
    tests=ROOT/'scripts/test_release_empirical_diagnostic_report.py'
    shutil.copyfile(tests,output/'report-tests-source.py')
    write(output/'checks.json',dict(passed=True,result_sha256=sha(output/'result.json'),
        reporter_sha256=sha(__file__),reporter_tests_sha256=sha(tests),facts=facts,
        complete_cash_and_partition_check=True,independent_path_reconstruction=False,
        independent_external_review=False,production_pricing_validated=False,goal_complete=False))
    manifest={str(f.relative_to(output)):sha(f) for f in sorted(output.rglob('*')) if f.is_file()}
    write(output/'manifest.json',manifest)
    return facts


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True)
    print(json.dumps(report(parser.parse_args().output)))
