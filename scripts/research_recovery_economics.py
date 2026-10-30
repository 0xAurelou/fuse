#!/usr/bin/env python3
"""Matched capital-only versus fee-aware fixed-recovery preset replay."""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import shutil
import time

from capture_dataset import file_hash,load_capture
from investigate_capture import write_csv
from prepare_recovery_research import ROOT
from recovery_economics import Replay
from replay_lp_economics import Bridge,DEFAULT_COSTS
from research_bursty_optimizer import dump
from research_single_stage_economics import source_files
from single_stage_economics import PROFILES,SPEC

EXTRA=('scripts/recovery_economics.py','scripts/test_recovery_economics.py',
    'scripts/research_recovery_economics.py','scripts/prepare_recovery_research.py',
    'scripts/research_engine/fuse-research/main.go','scripts/research_engine/fuse-research/main_test.go',
    'scripts/research_engine/engine/research_projection.go','scripts/research_engine/engine/research_projection_test.go')


def verify_build(build):
    report=json.loads((build/'build.json').read_text())
    if not report['completed'] or file_hash(build/'fuse-research-v2')!=report['binary_sha256']:
        raise ValueError('incomplete or changed research build')
    for name,digest in report['source_sha256'].items():
        if file_hash(ROOT/name)!=digest:raise ValueError('research build basis changed: '+name)
    for name,digest in report['copied_source_sha256'].items():
        if file_hash(build/'engine'/name)!=digest:raise ValueError('isolated engine copy changed: '+name)
    return report


def fee_fixture(binary,policy,path):
    with path.open('x') as audit:
        bridge=Bridge(binary,audit);serial=0
        def command(kind,**fields):
            nonlocal serial
            serial+=1
            return bridge.send(dict(kind='command',command=dict(kind=kind,at=1000000,key=f'fixture/{serial}',**fields)),allow_reject=True)
        try:
            bridge.send(dict(kind='init',policy=policy));command('tick')
            bridge.send(dict(kind='sync_lp',cash=250000000000,fee=0,exit=0))
            for source in ('a','b'):
                command('oracle',source=source,raw=dict(channel='activeAssetCtx',data=dict(coin='BTC',ctx=dict(oraclePx='100000'))))
            command('deposit',actor='fixture',id='fund',amount=10000000);command('ack_deposit',id='fund')
            bridge.send(dict(kind='sync_lp',cash=250000000000,fee=25000000,exit=0))
            state=bridge.send(dict(kind='snapshot'))['value']
            quote=command('quote',actor='fixture',amount=1000000,multiplier=2)
            return dict(recovery=state['recovery'],quote_accepted=quote['ok'],binary_sha256=file_hash(binary))
        finally:bridge.close()


def run(output,baseline,build,recovery_path):
    if output.exists():raise ValueError('preserve previous replay; choose a new output')
    old=json.loads((baseline/'research.json').read_text());audit=json.loads((baseline/'audit.json').read_text())
    if not audit['completed'] or audit['research_sha256']!=file_hash(baseline/'research.json'):
        raise ValueError('audited baseline required')
    if file_hash(baseline/'fuse-research')!=old['binary_sha256']:raise ValueError('baseline binary changed')
    for name,digest in old['source_files_sha256'].items():
        if file_hash(ROOT/name)!=digest:raise ValueError('baseline implementation changed: '+name)
    built=verify_build(build);base_policy=json.loads((baseline/'source-policy.json').read_text())
    risk_policy=json.loads(recovery_path.read_text());recovery=risk_policy['recovery']
    if base_policy.get('recovery') is not None:raise ValueError('baseline must be capital-only')
    names=tuple(dict.fromkeys(source_files()+EXTRA))
    protocol=dict(version='matched-fee-aware-recovery-economics-v1',prepared_at_ms=time.time_ns()//1000000,
        baseline=str(baseline.resolve()),baseline_sha256=file_hash(baseline/'research.json'),
        build=str(build.resolve()),build_sha256=file_hash(build/'build.json'),binary_sha256=built['binary_sha256'],
        recovery_policy_path=str(recovery_path.resolve()),recovery_policy_sha256=file_hash(recovery_path),recovery_policy=recovery,
        source_sha256={n:file_hash(ROOT/n) for n in names},spec=SPEC,profiles=PROFILES,multipliers=old['multipliers'],
        arms=['capital_only','fixed_recovery'],cost_assumptions=DEFAULT_COSTS,
        rule='Same original native prefixes, profiles, stake, widths, capital and settlement schedule. Only the fixed recovery controller differs. No parameter search or threshold selection. Baseline must reproduce the prior Go final state exactly.',
        fee_rule='Verified isolated v2 bridge charges actual local ReserveFeeAccrued handler, once at each positive fee increment. No fee reduction, operator-cost budget charge or LP exit lifecycle.',
        no_live_trial_inputs=True,adaptive_candidate_changed=False,economics_validated=False,production_approved=False)
    output.mkdir();(output/'source').mkdir();dump(output/'protocol.json',protocol)
    for name in names:
        target=output/'source'/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(ROOT/name,target)
    shutil.copyfile(build/'fuse-research-v2',output/'fuse-research-v2');(output/'fuse-research-v2').chmod(0o700)
    shutil.copyfile(build/'build.json',output/'engine-build.json');shutil.copyfile(recovery_path,output/'recovery-policy.json')
    fixture_policy=deepcopy(base_policy);fixture_policy['recovery']=deepcopy(recovery)
    before=fee_fixture(baseline/'fuse-research',fixture_policy,output/'old-fee-fixture.jsonl')
    after=fee_fixture(output/'fuse-research-v2',fixture_policy,output/'new-fee-fixture.jsonl')
    if not (before['recovery']['pnl']==0 and before['quote_accepted'] and after['recovery']['pnl']==-25000000
            and after['recovery']['mode']=='paused' and not after['quote_accepted']):
        raise ValueError('fee/recovery differential does not reproduce the diagnosed fix')
    dump(output/'fee-differential.json',dict(synthetic_accounting_fixture=True,market_evidence=False,before=before,after=after))
    old_cases={(r['source'],r['profile'],r['multiplier']):r for r in old['results']}
    bindings=[];results=[];pairs=[];cost_rows=[];parity=0
    for directory in old['source_directories']:
        source=Path(directory);_,binding,manifest=load_capture(source)
        start=manifest['frozen_at_ms'];end=start+SPEC['prefix_ms']
        with (source/'receipts.jsonl').open() as stream:receipts=[r for line in stream if (r:=json.loads(line))['at']<end]
        bindings.append(dict(binding,prefix_start_ms=start,prefix_end_ms=end,prefix_receipts=len(receipts)))
        for profile in PROFILES:
            for multiplier in old['multipliers']:
                saved={}
                for arm in protocol['arms']:
                    policy=deepcopy(base_policy)
                    if arm=='fixed_recovery':
                        policy['recovery']=deepcopy(recovery);policy['version']+='-fixed-recovery-probe'
                    name=f'{source.name}-{profile["name"]}-{multiplier}-{arm}';print('Replaying '+name,flush=True)
                    with (output/(name+'-audit.jsonl')).open('x') as log:
                        bridge=Bridge(output/'fuse-research-v2',log)
                        try:
                            replay=Replay(bridge,policy,receipts,start,end,profile,multiplier,DEFAULT_COSTS)
                            result,state=replay.run()
                        finally:bridge.close()
                    if arm=='capital_only':
                        original=baseline/f'{source.name}-{profile["name"]}-{multiplier}-state.json'
                        if state!=json.loads(original.read_text()):raise ValueError('capital baseline state differs from archived reducer result')
                        control=old_cases[source.name,profile['name'],multiplier]
                        for field in ('accepted_stages','outcomes','lp_trading_pnl_usdc_units','cost_sensitivities',
                                      'reserve_fee_accrued_usdc_units','peak_total_exposure_usdc_units'):
                            if result[field]!=control[field]:raise ValueError('capital economic control differs: '+field)
                        parity+=1
                    result.update(source=source.name,arm=arm)
                    dump(output/(name+'-state.json'),state);dump(output/(name+'-lp.json'),replay.snapshots)
                    result.update(audit_sha256=file_hash(output/(name+'-audit.jsonl')),final_state_sha256=file_hash(output/(name+'-state.json')))
                    dump(output/(name+'-result.json'),result);results.append(result);saved[arm]=(result,state)
                    cost_rows.extend(dict(source=source.name,profile=profile['name'],multiplier=multiplier,arm=arm,**c) for c in result['cost_sensitivities'])
                control,cs=saved['capital_only'];treated,ts=saved['fixed_recovery']
                a={(s['terms']['account'],s['start']):s for s in cs['stages'].values()}
                b={(s['terms']['account'],s['start']):s for s in ts['stages'].values()};common=a.keys()&b.keys()
                for key in common:
                    if any(a[key]['terms'][f]!=b[key]['terms'][f] for f in ('entry_price','lower','upper','stake','payout','multiplier')):
                        raise ValueError('controller changed common accepted pricing')
                pairs.append(dict(source=source.name,profile=profile['name'],multiplier=multiplier,
                    intended_tickets=control['quote_attempts'],capital_accepted=control['accepted_stages'],
                    recovery_accepted=treated['accepted_stages'],common_accepted=len(common),
                    capital_pnl_usdc_units=control['lp_trading_pnl_usdc_units'],recovery_pnl_usdc_units=treated['lp_trading_pnl_usdc_units'],
                    capital_acceptance=control['acceptance_fraction'],recovery_acceptance=treated['acceptance_fraction'],
                    capital_drawdown=control['settlement_nav_max_drawdown'],recovery_drawdown=treated['settlement_nav_max_drawdown']))
        if file_hash(source/'receipts.jsonl')!=binding['sha256']:raise ValueError('native source changed')
    verify_build(build)
    for name,digest in protocol['source_sha256'].items():
        if file_hash(ROOT/name)!=digest:raise ValueError('replay source changed: '+name)
    report=dict(protocol,sources=bindings,results=results,paired=pairs,baseline_states_reproduced=parity,
        all_conserved=all(r['conservation_verified'] for r in results),
        limits='Short reused native prefixes, assumed demand and fixed research Brownian pricing. No calibrated adaptive economics, organic demand, measured costs, operator-cost recovery charge, reward/redemption, fee funding or LP exit validation.')
    dump(output/'research.json',report)
    write_csv(output/'paired.csv',pairs,list(pairs[0]));write_csv(output/'costs.csv',cost_rows,list(cost_rows[0]))
    return report


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--baseline',type=Path,required=True);p.add_argument('--build',type=Path,required=True)
    p.add_argument('--recovery-policy',type=Path,default=ROOT/'engine/config/paper-recovery.json');a=p.parse_args()
    r=run(a.output.resolve(),a.baseline.resolve(),a.build.resolve(),a.recovery_policy.resolve())
    print(json.dumps(dict(cases=len(r['results']),pairs=len(r['paired']),baseline_states_reproduced=r['baseline_states_reproduced'],all_conserved=r['all_conserved']),indent=2))
