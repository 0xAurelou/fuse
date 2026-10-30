#!/usr/bin/env python3
"""Bounded actual-reducer payout/strategy replay of completed native prefixes."""
import argparse
import json
from pathlib import Path
import shutil
import time

from capture_dataset import file_hash,load_capture
from investigate_capture import write_csv
from replay_lp_economics import Bridge,DEFAULT_COSTS,GAS_ASSUMPTIONS
from research_bursty_optimizer import dump
from research_frozen_market import DEPENDENCIES
from single_stage_economics import Replay,PROFILES,SPEC

ROOT=Path(__file__).resolve().parent.parent
DEFAULT_SOURCES=('20261026-117ppm-8h','20261026-round2-314ppm-8h')


def source_files():
    names=['scripts/'+n for n in DEPENDENCIES]
    names+=['scripts/'+n for n in ('single_stage_economics.py','research_single_stage_economics.py',
        'test_single_stage_economics.py','native_adaptive_data.py','replay_lp_economics.py',
        'contract_lp_model.py','calibrate_pricing.py')]
    names += [str(p.relative_to(ROOT)) for folder in ('engine/internal/engine','engine/cmd/fuse-research')
              for p in (ROOT/folder).glob('*.go')]
    names += ['src/LPVault.sol','src/LPShareVault.sol','src/LPIncentiveDistributor.sol',
              'engine/go.mod','engine/go.sum']
    return tuple(dict.fromkeys(names))


def run(output,binary,policy_path,sources):
    if output.exists():raise ValueError('preserve previous replay; choose a new output')
    policy=json.loads(policy_path.read_text())
    if policy.get('recovery') is not None:raise ValueError('combined recovery/fee projection is not supported')
    output.mkdir();(output/'source').mkdir()
    protocol=dict(version='single-stage-native-economics-v1',prepared_at_ms=time.time_ns()//1000000,spec=SPEC,
        source_directories=[str(p.resolve()) for p in sources],source_files_sha256={n:file_hash(ROOT/n) for n in source_files()},
        policy_path=str(policy_path.resolve()),policy_sha256=file_hash(policy_path),binary_sha256=file_hash(binary),
        multipliers=policy['multipliers'],cost_assumptions=DEFAULT_COSTS,gas_units_assumptions=GAS_ASSUMPTIONS,
        source_selection='First thirty minutes of each named retained recording; all nine presets and three fixed profiles. Chosen before replay outcomes.',
        model_role='Shipped fixed-volatility Brownian research assumptions only; the live adaptive challenger is not evaluated or changed.',
        demand='Counterfactual funded wallets, fixed stakes and synchronized entries, not recorded voluntary demand',
        no_new_observations=True,prospective_evidence=False,adaptive_candidate_changed=False,economics_validated=False,
        production_approved=False)
    dump(output/'protocol.json',protocol)
    shutil.copyfile(policy_path,output/'source-policy.json');shutil.copyfile(binary,output/'fuse-research')
    (output/'fuse-research').chmod(0o700)
    for name in protocol['source_files_sha256']:
        path=output/'source'/name;path.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(ROOT/name,path)
    bindings=[];results=[];cost_rows=[]
    for source in sources:
        _,binding,manifest=load_capture(source)
        start=manifest['frozen_at_ms'];end=start+SPEC['prefix_ms']
        if end>start+manifest['duration_ms']:raise ValueError('recording shorter than declared prefix')
        if any(policy[k]!=manifest['policy'][k] for k in ('duration_ms','max_gap_ms','disagreement_ms','void_delay_ms')):
            raise ValueError('native source health policy differs from replay')
        with (source/'receipts.jsonl').open() as stream:receipts=[r for line in stream if (r:=json.loads(line))['at']<end]
        bindings.append(dict(binding,prefix_start_ms=start,prefix_end_ms=end,prefix_receipts=len(receipts)))
        for profile in PROFILES:
            for multiplier in policy['multipliers']:
                name=f'{source.name}-{profile["name"]}-{multiplier}'
                print('Replaying '+name,flush=True)
                with (output/(name+'-audit.jsonl')).open('x') as audit:
                    bridge=Bridge(output/'fuse-research',audit)
                    try:
                        replay=Replay(bridge,policy,receipts,start,end,profile,multiplier,DEFAULT_COSTS)
                        result,state=replay.run()
                    finally:bridge.close()
                result.update(source=source.name,audit_sha256=file_hash(output/(name+'-audit.jsonl')),
                    final_state_sha256=None)
                dump(output/(name+'-state.json'),state);result['final_state_sha256']=file_hash(output/(name+'-state.json'))
                dump(output/(name+'-result.json'),result);dump(output/(name+'-lp.json'),replay.snapshots)
                results.append(result)
                cost_rows.extend(dict(source=source.name,profile=profile['name'],multiplier=multiplier,**c) for c in result['cost_sensitivities'])
        if file_hash(source/'receipts.jsonl')!=binding['sha256']:raise ValueError('source changed during replay')
    for name,digest in protocol['source_files_sha256'].items():
        if file_hash(ROOT/name)!=digest:raise ValueError('source changed during replay: '+name)
    report=dict(protocol,sources=bindings,results=results,
        resolved_healthy_comparisons=sum(r['healthy_outcome_comparisons'] for r in results),
        all_conserved=all(r['conservation_verified'] for r in results),
        source_recordings_are_development=True,
        limits='Short original thirty-minute prefixes with hypothetical demand. Same paths repeat across policies/accounts; not independent samples. No organic demand, strategy optimality, adaptive-width economics, recovery+fee integration, LP exits, reward/redemption, measured costs or production validation.')
    dump(output/'research.json',report)
    fields=('source','profile','accounts','multiplier','grid_windows','history_eligible','intended_grid_entries',
        'quote_attempts','accepted_stages','acceptance_fraction','grid_ticket_availability','survival','configured_survival_target',
        'accepted_turnover_usdc_units','lp_trading_pnl_usdc_units','gross_return_per_stake',
        'reserve_fee_accrued_usdc_units','lp_profit_after_fee_usdc_units','peak_total_exposure_usdc_units',
        'peak_unfunded_debt_usdc_units','settlement_nav_max_drawdown','healthy_outcome_comparisons')
    write_csv(output/'cases.csv',results,fields);write_csv(output/'costs.csv',cost_rows,list(cost_rows[0]))
    return report


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--binary',type=Path,required=True);p.add_argument('--policy',type=Path,default=ROOT/'engine/config/paper.json')
    p.add_argument('--source',type=Path,action='append');a=p.parse_args()
    sources=a.source or [ROOT/'.local/prospective-runs'/n for n in DEFAULT_SOURCES]
    r=run(a.output.resolve(),a.binary.resolve(),a.policy.resolve(),sources)
    print(json.dumps(dict(cases=len(r['results']),all_conserved=r['all_conserved'],
        healthy_comparisons=r['resolved_healthy_comparisons'],economics_validated=False),indent=2))
