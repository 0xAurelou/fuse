#!/usr/bin/env python3
"""Rebuild the retained payout screen and independently check bound maximality."""
import argparse
from fractions import Fraction
import json
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory

from capture_dataset import file_hash
from research_bursty_optimizer import dump
from research_payout_feasibility import run,ROOT


def audit(output):
    r=json.loads((output/'research.json').read_text())
    for name,digest in r['source_sha256'].items():
        assert file_hash(ROOT/name)==digest
        assert file_hash(output/'source'/name)==digest
    assert file_hash(output/'source-policy.json')==r['policy_sha256']
    with TemporaryDirectory(prefix='fuse-payout-feasibility-') as temp:
        fresh=Path(temp)/'recomputed'
        rebuilt=run(Path(r['dataset']),Path(r['late_raw']),Path(r['policy']),fresh)
        assert json.loads(json.dumps(rebuilt))==r
        for name in ('cases.csv','profiles.csv','rare_events.csv','batch_illustrations.csv','liabilities.csv'):
            assert file_hash(output/name)==file_hash(fresh/name)
    checked=0
    for c in r['cases']:
        n,z,k=c['clean_outcomes'],c['zero_motion_survivors'],c['maximum_kept']
        q=Fraction(c['target_fraction'])
        if n==0:
            assert k is None;continue
        if k:
            assert Fraction(max(0,z-(n-k)),k)<=q
        if k<n:
            assert Fraction(max(0,z-(n-k-1)),k+1)>q
        assert c['minimum_refusals']==n-k
        assert c['reference_availability_compatible']==(Fraction(k,n)>=Fraction(1,2) if c['group']=='frozen' else Fraction(k,n)>=Fraction(17,20))
        checked+=1
    for c in r['fortyeight_percent_batch_illustrations']:
        gross=Fraction(1)-c['multiplier']*Fraction(12,25)
        fee=max(0,gross)*Fraction(c['positive_batch_profit_allocation_bps_assumed'],10000)
        net=gross-fee-Fraction(c['cost_bps_assumed'],10000)
        assert abs(float(net)-c['net'])<1e-12
    report=dict(completed=True,research_sha256=file_hash(output/'research.json'),recomputed_cases=len(r['cases']),
        nonempty_maximal_bounds_checked=checked,all_csv_rebuilt_exactly=True,
        source_sha256=file_hash(Path(__file__)),live_trial_receipts_read=False,
        pricing_candidate_changed=False,economics_validated=False,
        scope='Necessary finite-path zero-motion feasibility only. Passing a bound is not causal calibration or net LP validation.')
    shutil.copyfile(Path(__file__),output/'source/scripts/audit_payout_feasibility.py')
    dump(output/'audit.json',report);return report


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True)
    print(json.dumps(audit(p.parse_args().output),indent=2))
