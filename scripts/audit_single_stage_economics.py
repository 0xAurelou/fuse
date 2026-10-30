#!/usr/bin/env python3
"""Re-execute all preset probe commands and LP projections from native inputs."""
import argparse
import json
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory

from capture_dataset import file_hash
from research_bursty_optimizer import dump
from research_single_stage_economics import run,ROOT


def audit(output):
    r=json.loads((output/'research.json').read_text())
    assert file_hash(output/'fuse-research')==r['binary_sha256']
    assert file_hash(output/'source-policy.json')==r['policy_sha256']
    for name,digest in r['source_files_sha256'].items():
        assert file_hash(ROOT/name)==digest and file_hash(output/'source'/name)==digest
    with TemporaryDirectory(prefix='fuse-single-stage-audit-') as temp:
        fresh=Path(temp)/'replay'
        rebuilt=run(fresh,output/'fuse-research',Path(r['policy_path']),[Path(p) for p in r['source_directories']])
        rebuilt=json.loads(json.dumps(rebuilt))
        rebuilt.pop('prepared_at_ms');saved=dict(r);saved.pop('prepared_at_ms')
        if rebuilt!=saved:
            failure=output/'failed-audit-replay'
            if not failure.exists():shutil.copytree(fresh,failure)
            raise AssertionError('recomputed research differs; retained failed replay at '+str(failure))
        for name in ('cases.csv','costs.csv'):
            assert file_hash(output/name)==file_hash(fresh/name)
        commands=0
        for result in r['results']:
            stem=f'{result["source"]}-{result["profile"]}-{result["multiplier"]}'
            for suffix in ('-audit.jsonl','-state.json','-result.json','-lp.json'):
                assert file_hash(output/(stem+suffix))==file_hash(fresh/(stem+suffix))
            commands+=result['audit_records']
            assert result['conservation_verified'] and result['zero_terminal_active']
            assert not result['healthy_outcome_mismatches']
            assert result['terminal_exposure_usdc_units']==0 and result['terminal_debt_usdc_units']==0
    report=dict(completed=True,research_sha256=file_hash(output/'research.json'),cases_recomputed=len(r['results']),
        command_audit_records_recomputed=commands,all_case_files_rebuilt_exactly=True,
        healthy_native_outcome_comparisons=r['resolved_healthy_comparisons'],
        source_sha256=file_hash(Path(__file__)),live_trial_read_or_changed=False,
        adaptive_candidate_evaluated=False,economics_validated=False,production_approved=False)
    shutil.copyfile(Path(__file__),output/'source/scripts/audit_single_stage_economics.py')
    dump(output/'audit.json',report);return report


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True)
    print(json.dumps(audit(p.parse_args().output.resolve()),indent=2))
