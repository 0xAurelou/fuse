#!/usr/bin/env python3
"""Compare old and new native responses on an unchanged legacy policy."""
import argparse
import json
from pathlib import Path

from replay_lp_economics import Bridge
from research_adaptive_native_ppb import sha, write


def compare(old_binary, new_binary, policy):
    old, new = Bridge(old_binary), Bridge(new_binary)
    count, serial = 0, 0
    def request(value):
        nonlocal count
        a = old.send(value, allow_reject=True)
        b = new.send(value, allow_reject=True)
        if a != b:
            raise ValueError('legacy native response diverged at request '+str(count))
        count += 1
        return b
    def command(kind, at, **fields):
        nonlocal serial
        serial += 1
        return request(dict(kind='command',command=dict(kind=kind,key='legacy-compare/'+str(serial),at=at,**fields)))
    try:
        request(dict(kind='init',policy=policy))
        start = 1_000_000
        command('lp_fund',start,amount=250_000_000_000)
        command('deposit',start,actor='trader',id='fund',amount=1_000_000_000)
        command('ack_deposit',start,id='fund')
        def price(at):
            for source in ('a','b'):
                command('oracle',at,source=source,raw=dict(channel='activeAssetCtx',
                    data=dict(coin='BTC',ctx=dict(oraclePx='100000'))))
        price(start)
        for multiplier in policy['multipliers']:
            q = command('quote',start,actor='trader',amount=1_000_000,multiplier=multiplier)
            if not q['ok']:
                raise ValueError('legacy compatibility vector unexpectedly rejected')
        command('enter',start,actor='trader',id=q['value']['result']['id'])
        for at in range(start+5000,start+30001,5000):
            price(at)
        command('withdraw',start+30000,actor='trader',amount=10_999_000_000)
        command('paper_settle',start+30000)
        state = request(dict(kind='snapshot'))['value']
        command('paper_pay',start+30000,id=state['accounts']['trader']['withdrawal'])
        request(dict(kind='snapshot'))
    finally:
        old.close()
        new.close()
    return dict(all_responses_equal=True, requests_compared=count,
        includes_state_and_journal_hashes=True, presets=policy['multipliers'],
        old_binary_sha256=sha(old_binary), new_binary_sha256=sha(new_binary),
        scope='Unchanged Brownian legacy policy, every preset quote, 10000x accepted win, unpaid liability, settlement, withdrawal and payment. Not exhaustive backward compatibility.',
        production_approved=False)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--old-binary',type=Path,required=True)
    p.add_argument('--new-binary',type=Path,required=True)
    p.add_argument('--policy',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    a = p.parse_args()
    result = compare(a.old_binary,a.new_binary,json.loads(a.policy.read_text()))
    result['policy_sha256'] = sha(a.policy)
    result['verifier_sha256'] = sha(__file__)
    write(a.output,result)
    print(json.dumps(result))
