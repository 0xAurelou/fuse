#!/usr/bin/env python3
"""Re-execute matched fee/recovery cases and verify every archived artifact."""
import argparse
import json
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory

from capture_dataset import file_hash
from research_bursty_optimizer import dump
from research_recovery_economics import run,ROOT


def audit(output):
    result=json.loads((output/'research.json').read_text())
    for name,digest in result['source_sha256'].items():
        assert file_hash(ROOT/name)==digest and file_hash(output/'source'/name)==digest
    records=0
    with TemporaryDirectory(prefix='fuse-recovery-audit-') as temp:
        fresh=Path(temp)/'recomputed'
        replay=run(fresh,Path(result['baseline']),Path(result['build']),Path(result['recovery_policy_path']))
        replay=json.loads(json.dumps(replay));replay.pop('prepared_at_ms')
        saved=dict(result);saved.pop('prepared_at_ms');assert replay==saved
        for name in ('paired.csv','costs.csv','fee-differential.json','old-fee-fixture.jsonl','new-fee-fixture.jsonl'):
            assert file_hash(output/name)==file_hash(fresh/name)
        for case in result['results']:
            stem=f'{case["source"]}-{case["profile"]}-{case["multiplier"]}-{case["arm"]}'
            for suffix in ('-audit.jsonl','-state.json','-lp.json','-result.json'):
                assert file_hash(output/(stem+suffix))==file_hash(fresh/(stem+suffix))
            assert case['conservation_verified'] and case['fee_projection_verified']
            assert case['terminal_debt_usdc_units']==0 and case['terminal_exposure_usdc_units']==0
            if case['recovery_enabled']:
                assert case['recovery_final']['pnl']==case['lp_trading_pnl_usdc_units']-case['reserve_fee_accrued_usdc_units']
                assert sum(c['fee_delta'] for c in case['fee_projection_checks'])==case['reserve_fee_accrued_usdc_units']
            records+=case['audit_records']
    report=dict(completed=True,research_sha256=file_hash(output/'research.json'),cases_recomputed=len(result['results']),
        baseline_states_reproduced=result['baseline_states_reproduced'],command_audit_records_recomputed=records,
        all_case_files_rebuilt_exactly=True,source_sha256=file_hash(Path(__file__)),
        adaptive_candidate_changed=False,live_trial_inputs_read=False,economics_validated=False,production_approved=False)
    shutil.copyfile(Path(__file__),output/'source/scripts/audit_recovery_economics.py')
    dump(output/'audit.json',report);return report


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True)
    print(json.dumps(audit(p.parse_args().output.resolve()),indent=2))
