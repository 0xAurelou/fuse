#!/usr/bin/env python3
"""Separate integer-arithmetic audit of recovery risk in a Go-verified journal.

This checker does not import the trading reducer, approve oracle outcomes, hold
keys or constitute an independent production signing controller.
"""
import argparse
from copy import deepcopy
import json
import hashlib
from pathlib import Path
import subprocess

DAY = 86_400_000
LIMIT = 1_000_000_000_000_000
OPEN = {'active','pending'}


def check(events, policy, final):
    config = deepcopy(policy.get('recovery'))
    if not config:
        raise ValueError('explicit recovery policy required')
    state = dict(mode='open',reopen_at=0,pnl=0,peak=0,losses=[])
    stages, quotes = {}, {}
    sequence, head, last_at, admissions, resolutions = 0, '', 0, 0, 0

    def advance(at):
        state['losses'] = [loss for loss in state['losses'] if loss['at'] > at-config['rolling_ms']]
        drawdown = state['peak']-state['pnl']
        if state['mode']=='open' and drawdown >= config['pause_drawdown']:
            state.update(mode='paused',reopen_at=at+config['cooldown_ms'])
        elif state['mode']!='open' and at >= state['reopen_at']:
            if drawdown <= config['resume_drawdown']:
                state['mode']='open'
            elif state['mode']=='paused':
                state['mode']='probe'

    def record(pnl, at):
        state['pnl'] += pnl
        state['peak'] = max(state['peak'],state['pnl'])
        if state['peak'] > LIMIT//2:
            state['pnl'] -= state['peak']; state['peak']=0
        if pnl < 0:
            state['losses'].append(dict(at=at,amount=-pnl))
            if state['mode']=='probe':
                state.update(mode='paused',reopen_at=at+config['cooldown_ms'])
        advance(at)

    def admission(extra, at):
        if state['mode']=='paused':
            raise ValueError(f'admission during cooldown at sequence {sequence}')
        pending = sum(s['terms']['payout']-s['terms']['stake'] for s in stages.values() if s['status'] in OPEN)
        day = sum(v['amount'] for v in state['losses'] if v['at'] > at-DAY)
        rolling = sum(v['amount'] for v in state['losses'] if v['at'] > at-config['rolling_ms'])
        ceilings = [config['daily_loss']-day,config['rolling_loss']-rolling,
                    config['hard_drawdown']-(state['peak']-state['pnl'])]
        if state['mode']=='probe':
            ceilings.append(config['probe_loss']-day)
        if extra < 0 or pending+extra > min(ceilings):
            raise ValueError(f'accepted risk exceeds recovery budget at sequence {sequence}')

    for event in events:
        command = event['command']; at=command['at']; kind=command['kind']
        if event['sequence'] != sequence+1 or event['previous_hash'] != head or at < last_at:
            raise ValueError('journal sequence, hash link or clock regressed')
        sequence,head,last_at=event['sequence'],event['hash'],at
        updates={}
        for notice in event['notices'].values():
            for stage in notice['stages']:
                sid=stage['id']
                if sid in updates and updates[sid]!=stage:
                    raise ValueError('conflicting stage notices')
                if sid in stages and stages[sid]['terms'] != stage['terms']:
                    raise ValueError('accepted terms changed')
                updates[sid]=deepcopy(stage)
        early, late = [], []
        for sid,new in updates.items():
            old=stages.get(sid)
            if old and old['status'] in OPEN and new['status'] not in OPEN:
                if new.get('resolved') != at:
                    raise ValueError('resolution timestamp differs from committed command')
                (early if old['expiry'] <= at else late).append(sid)
            elif old is None and (kind!='enter' or new['status']!='active'):
                raise ValueError('stage created outside acceptance')
        def resolve(ids):
            nonlocal resolutions
            for sid in sorted(ids):
                s=updates[sid]; status=s['status']; terms=s['terms']
                if status=='survived':record(-(terms['payout']-terms['stake']),at)
                elif status=='exploded':record(terms['stake'],at)
                elif status!='voided':raise ValueError('unknown terminal outcome')
                resolutions+=1
        if kind.startswith('local_') and (early or late):
            raise ValueError('local chain command adjudicated a trading outcome')
        resolve(early); advance(at); resolve(late)
        stages.update(updates)
        if kind=='policy_update' and command['raw'].get('recovery') != config:
            raise ValueError('recovery policy changed')
        if kind=='quote':
            q=event['result'];admission(q['payout']-q['stake'],at);quotes[q['id']]=deepcopy(q)
        elif kind=='enter':
            accepted=event['result']
            if accepted['terms'] != quotes.get(command['id']) or accepted != stages.get(accepted['id']):
                raise ValueError('acceptance differs from committed quote or notice')
            admission(0,at); admissions+=1
        elif kind=='local_block':
            for effect in command['raw']['effects']:
                if effect['module']=='LPVault' and effect['event']=='ReserveFeeAccrued':
                    record(-effect.get('amount',0),at)
    if final['sequence'] != sequence or final['journal_hash'] != head:
        raise ValueError('snapshot is not the checked journal head')
    if final['recovery'] != state:
        raise ValueError('snapshot recovery state differs from independent arithmetic')
    if final['stages'] != stages:
        raise ValueError('snapshot stages differ from committed notices')
    return dict(sequence=sequence,journal_hash=head,admissions_checked=admissions,
                resolutions_checked=resolutions,recovery=state,arithmetic_verified=True,
                independent_production_controller=False,production_approved=False,
                scope='Integer risk admission/accounting against committed stage outcomes; no independent oracle adjudication, signer separation or external security approval.')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory',type=Path)
    parser.add_argument('--engine-verifier',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();directory=args.directory.resolve()
    native=json.loads(subprocess.check_output([str(args.engine_verifier.resolve()),'-config',str(directory/'initial-policy.json'),'-replay',str(directory/'journal.jsonl')],text=True))
    policy=json.loads((directory/'initial-policy.json').read_text())
    final=json.loads((directory/'final-state.json').read_text())
    with (directory/'journal.jsonl').open() as stream:
        result=check((json.loads(line) for line in stream),policy,final)
    if native['journal_hash']!=result['journal_hash'] or native['sequence']!=result['sequence']:
        raise ValueError('native replay and arithmetic checker disagree')
    result['native_replay']=native
    result['files_sha256']={name:hashlib.sha256(path.read_bytes()).hexdigest() for name,path in {
        'journal':directory/'journal.jsonl','policy':directory/'initial-policy.json',
        'final_state':directory/'final-state.json','checker':Path(__file__).resolve(),
        'native_verifier':args.engine_verifier.resolve()}.items()}
    with args.output.open('x') as stream:json.dump(result,stream,indent=2);stream.write('\n')
    print(args.output)

if __name__=='__main__':main()
