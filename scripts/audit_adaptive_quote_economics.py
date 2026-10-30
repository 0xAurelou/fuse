#!/usr/bin/env python3
"""Recompute quote-tape economics and check original calibration denominators."""
import argparse
from collections import defaultdict
from copy import deepcopy
import gzip
import json
from pathlib import Path
import shutil

from adaptive_quote_economics import decisions
from capture_dataset import file_hash
from prospective_capture_v2 import write_new
from research_adaptive_quote_economics import binding,read_sessions,compute


def audit(directory):
    directory=directory.resolve();research=json.loads((directory/'research.json').read_text())
    archive=Path(research['archive']);parent,names=binding(archive)
    if (file_hash(archive/'research.json')!=research['archive_research_sha256']
            or file_hash(archive/'audit.json')!=research['archive_audit_sha256']):
        raise ValueError('parent research/audit changed')
    for name,digest in research['source_sha256'].items():
        if file_hash(Path(__file__).with_name(name))!=digest or file_hash(directory/'source'/name)!=digest:
            raise ValueError('economics source differs: '+name)
    for name,key in (('protocol.json','protocol_sha256'),('cases.jsonl','cases_sha256'),
                     ('entry-decisions.jsonl.gz','entry_decisions_sha256')):
        if file_hash(directory/name)!=research[key]:raise ValueError('research artifact changed: '+name)
    sessions=read_sessions(archive,names);cases,traces=compute(sessions)
    with (directory/'cases.jsonl').open() as f:stored=[json.loads(line) for line in f]
    with gzip.open(directory/'entry-decisions.jsonl.gz','rt') as f:saved=[json.loads(line) for line in f]
    if cases!=stored or traces!=saved:raise ValueError('recomputed decisions or economics differ')
    index={};partitions=defaultdict(dict);crosschecks=0;scalings=0
    parent_cases={(r['candidate'],r['case_id'],r['activity']):r for r in parent['cases']}
    for r in cases:
        key=(r['candidate'],r['session'],r['block_hour'],r['strategy'],r['accounts'])
        if key in index:raise ValueError('duplicate eight-hour case')
        index[key]=r
        if r['accounts']==1:
            partitions[key[:3]][r['strategy']]=r
            activity={'all_offered':'all','frozen_only':'frozen','nonfrozen_only':'non_frozen'}.get(r['strategy'])
            if activity:
                previous=parent_cases[r['candidate'],r['session']+f':{r["block_hour"]:02}',activity]
                for a,b in (('selected_grid_entries','offered_pre_entry_decisions'),('resolved_grid_entries','windows'),
                            ('survived_grid_entries','survived')):
                    if r[a]!=previous[b]:raise ValueError('original pricing denominator differs: '+a)
                crosschecks+=1
        expected=1000000*r['accounts']*(r['resolved_grid_entries']-2*r['survived_grid_entries'])
        if r['lp_gross_assuming_censored_refund_usdc_units']!=expected or r['customer_gross_usdc_units']!=-expected:
            raise ValueError('independent two-times trading conservation differs')
        for c in r['cost_sensitivity']:
            cost=r['placed_tickets']*1000000*c['expense_bps']//10000
            if c['lp_net_assuming_censored_refund_usdc_units']+r['customer_gross_usdc_units']+cost:
                raise ValueError('net customer/LP/expense conservation differs')
            unknown=r['censored_grid_entries']*r['accounts']*1000000
            if c['lp_net_lower_if_all_censored_survive_usdc_units']!=expected-cost-unknown or c['lp_net_upper_if_all_censored_fail_usdc_units']!=expected-cost+unknown:
                raise ValueError('two-sided censorship bound differs')
    additive=('selected_grid_entries','placed_tickets','resolved_grid_entries','censored_grid_entries',
              'survived_grid_entries','lp_gross_assuming_censored_refund_usdc_units','customer_gross_usdc_units')
    for group in partitions.values():
        for left,right in (('frozen_only','nonfrozen_only'),('width_at_most_10ppm','width_over_10ppm')):
            for field in additive:
                if group[left][field]+group[right][field]!=group['all_offered'][field]:
                    raise ValueError('complementary strategy partition differs: '+field)
    for key,one in index.items():
        if key[-1]!=1:continue
        three=index[(*key[:-1],3)]
        for field in ('placed_tickets','lp_gross_assuming_censored_refund_usdc_units','customer_gross_usdc_units',
                      'placed_turnover_usdc_units','settlement_pnl_drawdown_usdc_units','gross_survivor_losses_usdc_units'):
            if three[field]!=3*one[field]:raise ValueError('synchronized-account scaling differs: '+field)
        if three['resolved_grid_entries']!=one['resolved_grid_entries'] or three['survival']!=one['survival']:
            raise ValueError('cloned traders inflated independent outcome evidence')
        scalings+=1
    causality=[]
    for key,rows in sorted(sessions.items()):
        # A retained prefix and its maturity boundary must be identical even
        # when every present/future outcome and its censorship are altered.
        probe=deepcopy(rows[:180]);boundary=60
        changed=deepcopy(probe)
        for i,r in enumerate(changed[boundary:]):
            if r['width'] is not None:r['shadow']=None if i%3==0 else not bool(r['shadow'])
        if decisions(probe)[:boundary+2]!=decisions(changed)[:boundary+2]:
            raise ValueError('current/future outcome leaked before declared maturity')
        causality.append(dict(tape=key[0],candidate=key[1],session=key[2],prefix_and_maturity_preserved=True))
    shutil.copyfile(__file__,directory/'audit-source.py')
    result=dict(completed=True,research_sha256=file_hash(directory/'research.json'),
        audit_source_sha256=file_hash(directory/'audit-source.py'),eight_hour_cases_recomputed=len(cases),
        quote_decisions_recomputed=len(traces),original_calibration_cells_crosschecked=crosschecks,
        complementary_strategy_partitions_checked=len(partitions)*2,
        synchronized_account_pairs_checked=scalings,future_label_counterfactuals=causality,
        cash_conservation_and_censorship_bounds_verified=True,
        pricing_refitted=False,current_prospective_receipts_used=False,independent_holdout=False,
        production_approved=False,economics_validated=False,goal_complete=False)
    write_new(directory/'audit.json',result)
    print(json.dumps({k:v for k,v in result.items() if k!='future_label_counterfactuals'},indent=2))
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--directory',type=Path,required=True)
    audit(p.parse_args().directory)
