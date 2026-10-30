#!/usr/bin/env python3
"""Attribute the rejected challenger's errors without fitting or repricing."""
import argparse
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from fractions import Fraction
import gzip
from itertools import groupby, zip_longest
import json
from pathlib import Path
import shutil
import sys

from release_evidence import empirical_pricing_evidence
from release_pricing import ASSETS, DELAYS, EDGES, PAYOUTS, USDC
from research_release_empirical import path_days
from research_release_pricing import ROOT, read, sha, write

SOURCES=('scripts/diagnose_release_empirical.py','scripts/test_release_empirical_diagnostics.py')
SPEC=dict(version='release-empirical-error-attribution-v1',
    scope='All assets, payouts, edges, delays and dates of the audited rejected challenger; no fitting or quote changes.',
    groups=['all','flat','moving','jump','missing_history'],
    partition='Resolved zero-motion winners, positive-motion winners, exact touches and other losses; censored outcomes remain unknown.',
    training='Sum actual historical survivor fractions at each offered width, only for resolved accepted tickets. Exact rational arithmetic; not current predictive confidence.',
    age='Age since the newest matured training label at quote time; not oracle receipt age.',
    floor='Hindsight cohort bounds at unchanged corridors. Grant all censored tickets a player loss; removing realized flat paths is not an implementable entry policy.',
    independent_external_review=False,production_pricing_validated=False,goal_complete=False)


def rational(value):
    return dict(numerator=value.numerator,denominator=value.denominator)


@dataclass
class DiagnosticCounts:
    grid:int=0
    oracle_available:int=0
    offered:int=0
    accepted:int=0
    censored:int=0
    resolved:int=0
    flat_wins:int=0
    moving_wins:int=0
    touch_losses:int=0
    other_losses:int=0
    historical_wins:Counter=field(default_factory=Counter)
    training_group:Counter=field(default_factory=Counter)
    youngest_label_age_ms:int=None
    oldest_label_age_ms:int=None

    def add(self,row,offer,forecast):
        self.grid+=1
        self.oracle_available+=row['quote_available']
        self.offered+=offer['offered']
        if not offer['offered']:return
        n,k=forecast['training_references'],offer['training_survivors']
        age=row['quote_at']-forecast['maximum_label_maturity_ms']
        if (not row['quote_available'] or offer['delta']<=0 or n<=0 or not 0<=k<=n or age<=0):
            raise ValueError('invalid offered width, reference or maturity')
        self.training_group[forecast['training_group'][0]]+=1
        self.youngest_label_age_ms=age if self.youngest_label_age_ms is None else min(age,self.youngest_label_age_ms)
        self.oldest_label_age_ms=age if self.oldest_label_age_ms is None else max(age,self.oldest_label_age_ms)
        if not row['accepted']:return
        self.accepted+=1
        if not row['valid']:
            self.censored+=1
            return
        if row['move']<0:raise ValueError('negative excursion')
        self.resolved+=1
        self.historical_wins[n]+=k
        if row['move']==0:self.flat_wins+=1
        elif row['move']<offer['delta']:self.moving_wins+=1
        elif row['move']==offer['delta']:self.touch_losses+=1
        else:self.other_losses+=1

    def merge(self,other):
        for name in ('grid','oracle_available','offered','accepted','censored','resolved',
                     'flat_wins','moving_wins','touch_losses','other_losses'):
            setattr(self,name,getattr(self,name)+getattr(other,name))
        self.historical_wins.update(other.historical_wins)
        self.training_group.update(other.training_group)
        if other.youngest_label_age_ms is not None:
            self.youngest_label_age_ms=other.youngest_label_age_ms if self.youngest_label_age_ms is None else min(self.youngest_label_age_ms,other.youngest_label_age_ms)
            self.oldest_label_age_ms=other.oldest_label_age_ms if self.oldest_label_age_ms is None else max(self.oldest_label_age_ms,other.oldest_label_age_ms)

    def result(self,multiplier,edge):
        wins=self.flat_wins+self.moving_wins
        if (self.resolved+self.censored!=self.accepted or
                self.flat_wins+self.moving_wins+self.touch_losses+self.other_losses!=self.resolved):
            raise AssertionError('diagnostic partition differs')
        historical=sum((Fraction(k,n) for n,k in self.historical_wins.items()),Fraction(0))
        target=Fraction(self.resolved*(10000-edge),10000*multiplier)
        # Existing historical support is not a probability guarantee. This
        # equality records exactly what the rejected width selected in training.
        if historical>target:raise AssertionError('historical quote budget differs')
        gross=(self.resolved-multiplier*wins)*USDC
        return dict(grid=self.grid,oracle_quote_available=self.oracle_available,quote_available=self.offered,
            accepted=self.accepted,censored=self.censored,resolved=self.resolved,wins=wins,
            flat_wins=self.flat_wins,moving_wins=self.moving_wins,
            touch_losses=self.touch_losses,other_losses=self.other_losses,
            flat_payout_usdc_units=multiplier*self.flat_wins*USDC,
            moving_payout_usdc_units=multiplier*self.moving_wins*USDC,
            gross_lp_refund_usdc_units=gross,
            gross_lp_if_censored_all_fail_usdc_units=gross+self.censored*USDC,
            flat_only_lp_upper_usdc_units=(self.accepted-multiplier*self.flat_wins)*USDC,
            after_hindsight_flat_removal_lp_upper_usdc_units=(self.accepted-self.flat_wins-multiplier*self.moving_wins)*USDC,
            historical_expected_wins=rational(historical) if self.resolved else None,
            target_expected_wins=rational(target) if self.resolved else None,
            observed_minus_historical_wins=rational(Fraction(wins)-historical) if self.resolved else None,
            newest_training_label_age_min_ms=self.youngest_label_age_ms,
            newest_training_label_age_max_ms=self.oldest_label_age_ms,
            offered_training_groups=dict(self.training_group),
            current_probability_validated=False)


def declare(output,parent):
    output,parent=Path(output).resolve(),Path(parent).resolve()
    if output.exists():raise FileExistsError('preserve existing diagnostics')
    bound=empirical_pricing_evidence(parent)
    original=read(parent/'protocol.json')
    inputs={str(parent/n):sha(parent/n) for n in ('protocol.json','result.json','audit.json','forecasts.jsonl.gz','cases.jsonl')}
    paths=Path(original['baseline_directory'])/'paths.jsonl.gz'
    inputs[str(paths)]=sha(paths)
    names=set(SOURCES)|set(bound['audited_sources_sha256'])|{
        'scripts/release_evidence.py','scripts/release_accounting.py','scripts/release_lp_bootstrap.py'}
    sources={n:sha(ROOT/n) for n in sorted(names)}
    output.mkdir(parents=True)
    for n in sources:
        target=output/'source'/n;target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(ROOT/n,target)
    plan=dict(spec=SPEC,parent=str(parent),days=bound['days'],paths=str(paths),input_sha256=inputs,
        source_sha256=sources,parent_software_audit_sha256=bound['audit_sha256'],
        python_version=sys.version,
        post_result_diagnostic=True,new_model_evaluated=False,fresh_holdout=False,
        production_pricing_validated=False,goal_complete=False)
    write(output/'protocol.json',plan)
    write(output/'freeze.json',dict(protocol_sha256=sha(output/'protocol.json')))
    return plan


def verify(output):
    output=Path(output);plan=read(output/'protocol.json')
    if (sha(output/'protocol.json')!=read(output/'freeze.json')['protocol_sha256'] or plan['spec']!=SPEC):
        raise ValueError('diagnostic protocol changed')
    if plan['python_version']!=sys.version:raise ValueError('diagnostic Python runtime changed')
    for n,h in plan['source_sha256'].items():
        if sha(ROOT/n)!=h or sha(output/'source'/n)!=h:raise ValueError('diagnostic source changed')
    for n,h in plan['input_sha256'].items():
        if sha(n)!=h:raise ValueError('diagnostic input changed')
    return plan


def forecast_days(path):
    with gzip.open(path,'rt') as f:
        for day,rows in groupby((json.loads(l) for l in f),lambda r:r['day']):
            values=list(rows)
            indexed={(r['asset'],r['edge_bps'],r['quote_at']):r for r in values}
            if len(indexed)!=len(values):raise ValueError('duplicate diagnostic forecast')
            yield day,indexed


def same_parent_cash(actual,parent):
    for name in ('grid','oracle_quote_available','quote_available','accepted','resolved','wins','censored',
                 'gross_lp_refund_usdc_units','gross_lp_if_censored_all_fail_usdc_units'):
        if actual[name]!=parent[name]:raise ValueError('diagnostic differs from audited parent: '+name)


def run(output):
    output=Path(output);plan=verify(output)
    if any((output/n).exists() for n in ('daily.jsonl','result.json')):raise FileExistsError('preserve prior diagnostic run')
    parent=read(Path(plan['parent'])/'result.json')
    with (Path(plan['parent'])/'cases.jsonl').open() as f:
        parent_cases={(r['day'],r['asset'],r['multiplier'],r['edge_bps'],r['delay_ms']):r
            for r in (json.loads(l) for l in f) if r['strategy']=='all_offered'}
    pooled=defaultdict(DiagnosticCounts);days=[];nforecasts=ncases=0
    with (output/'daily.jsonl').open('x') as sink:
        for pair in zip_longest(path_days(plan['paths']),forecast_days(Path(plan['parent'])/'forecasts.jsonl.gz')):
            if any(x is None for x in pair) or pair[0][0]!=pair[1][0]:raise ValueError('diagnostic day mismatch')
            (day,paths),(_,forecasts)=pair;days.append(day)
            wanted={(a,e,r['quote_at']) for a in ASSETS for e in EDGES for r in paths[a,0]}
            if set(forecasts)!=wanted:raise ValueError('incomplete diagnostic forecast grid')
            for asset in ASSETS:
                for edge in EDGES:
                    for m in PAYOUTS:
                        for delay in DELAYS:
                            counters=defaultdict(DiagnosticCounts)
                            for row in paths[asset,delay]:
                                f=forecasts[asset,edge,row['quote_at']]
                                if f['entry']!=row['entry']:raise ValueError('diagnostic entry binding differs')
                                q=f['offers'][PAYOUTS.index(m)]
                                if q['multiplier']!=m:raise ValueError('diagnostic preset binding differs')
                                group=row['prior_state']
                                if group not in SPEC['groups'][1:]:raise ValueError('unknown pre-entry activity')
                                counters['all'].add(row,q,f);counters[group].add(row,q,f)
                                nforecasts+=1
                            for group in SPEC['groups']:
                                c=counters[group];value=c.result(m,edge)
                                if group=='all':same_parent_cash(value,parent_cases[day,asset,m,edge,delay])
                                sink.write(json.dumps(dict(day=day,asset=asset,multiplier=m,edge_bps=edge,delay_ms=delay,group=group,**value),separators=(',',':'))+'\n')
                                pooled[asset,m,edge,delay,group].merge(c)
                                ncases+=1
            print(json.dumps(dict(day=day,delayed_forecasts=nforecasts,diagnostic_cases=ncases)),flush=True)
    if days!=plan['days']:raise ValueError('incomplete diagnostic calendar')
    expected={(a,m,e,d) for a in ASSETS for m in PAYOUTS for e in EDGES for d in DELAYS}
    if {(r['asset'],r['multiplier'],r['edge_bps'],r['delay_ms']) for r in parent['summary'] if r['strategy']=='all_offered'}!=expected:
        raise ValueError('parent summary grid changed')
    parent_summary={(r['asset'],r['multiplier'],r['edge_bps'],r['delay_ms']):r for r in parent['summary'] if r['strategy']=='all_offered'}
    summary=[]
    for (a,m,e,d,g),c in sorted(pooled.items()):
        value=c.result(m,e)
        if g=='all':same_parent_cash(value,parent_summary[a,m,e,d])
        summary.append(dict(asset=a,multiplier=m,edge_bps=e,delay_ms=d,group=g,**value))
    verify(output)
    result=dict(protocol_sha256=sha(output/'protocol.json'),days=days,delayed_forecasts=nforecasts,
        daily_diagnostic_cases=ncases,daily_sha256=sha(output/'daily.jsonl'),summary=summary,
        post_result_diagnostic=True,new_model_evaluated=False,fresh_holdout=False,
        production_pricing_validated=False,goal_complete=False)
    write(output/'result.json',result)
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--parent',type=Path)
    parser.add_argument('--declare',action='store_true')
    args=parser.parse_args()
    if args.declare:
        if args.parent is None:parser.error('--declare requires --parent')
        declare(args.output,args.parent)
    else:run(args.output)
