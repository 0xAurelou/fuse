#!/usr/bin/env python3
"""Independent rank/causality/cash cross-check; not external pricing review."""
import argparse
from bisect import bisect_right
from collections import Counter, defaultdict
import gzip
import hashlib
from itertools import groupby, zip_longest
import json
from pathlib import Path

from audit_release_pricing import add, check_cash, check_joint, choose, require
from release_pricing import ASSETS, DELAYS, EDGES, PAYOUTS, STRATEGIES
from research_release_empirical import path_days, verify
from research_release_pricing import origin, read, sha, write
from replay_lp_economics import Bridge


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def records(path, compressed=False):
    with (gzip.open(path,'rt') if compressed else path.open()) as f:
        for day, group in groupby((json.loads(l) for l in f), key=lambda r:r['day']):
            yield day,list(group)


def activity_key(row):
    gap=row['mark_gap_ppm']
    return (row['prior_state'], 'unknown' if gap is None else 'low' if gap<=100 else 'high',
            'fresh' if row['quote_age_ms'] is not None and row['quote_age_ms']<=1000 else 'older')


def build_groups(past, cutoff):
    grouped=defaultdict(list)
    for r in past:
        if r['expiry']+30_000>=cutoff:continue
        c=activity_key(r)
        for k in [('exact',*c),('activity',c[0]),('global',)]:grouped[k].append(r)
    result={}
    for key,rows in grouped.items():
        # Strict floor(delta) > maximum excursion; derive independently by
        # integer quotient/remainder rather than the forecast's threshold helper.
        values=[]
        for r in rows:
            quotient,remainder=divmod((r['move']+1)*10**9,r['entry'])
            values.append(quotient+bool(remainder))
        values.sort()
        result[key]=dict(thresholds=values,dates=sorted({r['day'] for r in rows}),
            maximum_label_maturity_ms=max(r['expiry']+30_000 for r in rows),
            references=len(rows),threshold_sha256=fingerprint(values))
    return result


def verify_forecast(record,row,groups,spec,model_id):
    require(record['model_id']==model_id and record['entry']==row['entry'],'model/price binding differs')
    c=activity_key(row);key=();d=None
    for candidate in [('exact',*c),('activity',c[0]),('global',)]:
        proposed=groups.get(candidate)
        if proposed and proposed['references']>=spec['minimum_references'] and len(proposed['dates'])>=spec['minimum_dates']:
            key,d=candidate,proposed;break
    common=dict(training_group=list(key),training_references=d['references'] if d else 0,
        training_dates=d['dates'] if d else [],maximum_label_maturity_ms=d['maximum_label_maturity_ms'] if d else None,
        threshold_sha256=d['threshold_sha256'] if d else None)
    require(all(record[k]==v for k,v in common.items()),'causal reference group/support differs')
    previous_w,previous_delta=10**9,None
    require([q['multiplier'] for q in record['offers']]==list(PAYOUTS),'incomplete preset forecast')
    for q in record['offers']:
        m=q['multiplier'];width=delta=wins=None
        if not row['quote_available'] or row['prior_state']=='missing_history':reason='unavailable_preentry_context'
        elif d is None:reason='insufficient_earlier_reference_dates'
        else:
            permitted=d['references']*(10_000-record['edge_bps'])//(10_000*m)
            if permitted<spec['minimum_empirical_survivors']:reason='insufficient_tail_reference_rank'
            else:
                upper=min(d['thresholds'][permitted]-1,spec['maximum_width_ppb'],previous_w-1)
                if previous_delta is not None:
                    # Largest width whose delta is strictly below the previous.
                    upper=min(upper,((previous_delta*10**9)-1)//row['entry'])
                proposed_delta=(upper*row['entry'])//10**9
                wins=bisect_right(d['thresholds'],upper)
                if upper<=0 or proposed_delta<=0:reason='native_minimum_width_exceeds_empirical_budget'
                elif row['entry']+proposed_delta>10**15:reason='native_arithmetic_limit'
                elif wins<spec['minimum_empirical_survivors']:reason='insufficient_observed_tail_survivors'
                else:
                    reason='offered';width,delta=upper,proposed_delta
                    require(wins*10_000*m<=d['references']*(10_000-record['edge_bps']),'historical risk budget exceeded')
                    previous_w,previous_delta=width,delta
        require(q==dict(multiplier=m,offered=reason=='offered',reason=reason,width_ppb=width,delta=delta,training_survivors=wins),
                'forecast/refusal/rank/quantization differs')


def audit(output):
    output=Path(output);p=verify(output);result=read(output/'result.json')
    if (output/'audit.json').exists():raise FileExistsError('preserve completed audit')
    require(result['protocol_sha256']==sha(output/'protocol.json'),'protocol/result differs')
    for name,h in result['artifacts_sha256'].items():require(sha(output/name)==h,'artifact changed: '+name)
    streams=[path_days(Path(p['baseline_directory'])/'paths.jsonl.gz'),records(output/'models.jsonl.gz',True),
        records(output/'forecasts.jsonl.gz',True),records(output/'cases.jsonl'),records(output/'joint.jsonl')]
    past={a:[] for a in ASSETS};total=defaultdict(lambda:[0]*8);oracle_total=defaultdict(int);reason_total=defaultdict(Counter)
    vectors=set();nforecasts=ncases=njoint=0;days=[]
    for bundles in zip_longest(*streams):
        require(all(b is not None for b in bundles),'missing day artifact')
        day,paths=bundles[0];require(all(b[0]==day for b in bundles),'artifact day differs');days.append(day)
        models={m['asset']:m for m in bundles[1][1]};require(set(models)==set(ASSETS) and len(bundles[1][1])==3,'model assets differ')
        forecast={(r['asset'],r['edge_bps'],r['quote_at']):r for r in bundles[2][1]}
        require(len(forecast)==len(bundles[2][1]),'duplicate forecast')
        cases={(r['asset'],r['multiplier'],r['edge_bps'],r['delay_ms'],r['strategy']):r for r in bundles[3][1]}
        require(len(cases)==3*len(PAYOUTS)*len(EDGES)*len(DELAYS)*len(STRATEGIES)==len(bundles[3][1]),'missing/extra daily cash case')
        codes={}
        for asset in ASSETS:
            groups=build_groups(past[asset],origin(day))
            expected=dict(day=day,asset=asset,cutoff_ms=origin(day),groups=[dict(key=list(k),**v) for k,v in sorted(groups.items())])
            model_id=fingerprint(expected)
            require(models[asset]==dict(model_id=model_id,**expected),'frozen daily fit differs or uses future labels')
            for edge in EDGES:
                for row in paths[asset,0]:
                    record=forecast[asset,edge,row['quote_at']]
                    verify_forecast(record,row,groups,p['spec'],model_id)
                    for q in record['offers']:
                        if q['offered']:vectors.add((row['entry'],q['width_ppb'],q['delta']))
                    nforecasts+=len(PAYOUTS)
                for m in PAYOUTS:
                    for delay in DELAYS:
                        counts={s:[0]*8 for s in STRATEGIES};history_times=[];history_labels=[];states=bytearray();reasons=Counter();oracle=0
                        for row in paths[asset,delay]:
                            q=forecast[asset,edge,row['quote_at']]['offers'][PAYOUTS.index(m)]
                            adjusted=row if q['offered'] else dict(row,quote_available=False,accepted=False)
                            outcome=(max(0,row['move'])<q['delta']) if adjusted['accepted'] and row['valid'] else None
                            matured=bisect_right(history_times,row['quote_at']);last=history_labels[matured-1] if matured else None
                            for s in STRATEGIES:add(counts[s],adjusted,choose(s,adjusted,last),outcome)
                            if adjusted['accepted'] and outcome is not None:
                                history_times.append(row['expiry']+30_000);history_labels.append(outcome)
                            states.append(3 if outcome is True else 2 if outcome is False else 1 if adjusted['accepted'] else 0)
                            reasons[q['reason']]+=1;oracle+=row['quote_available']
                        codes[asset,m,edge,delay]=states
                        for s,c in counts.items():
                            key=asset,m,edge,delay,s;case=cases[key];check_cash(case,c,m,edge)
                            require(case['oracle_quote_available']==oracle,'natural availability denominator differs')
                            require(case['refusal_reasons']==(dict(reasons) if s=='all_offered' else {}),'refusal denominator differs')
                            total[key]=[a+b for a,b in zip(total[key],c)];oracle_total[key]+=oracle
                            if s=='all_offered':reason_total[key].update(reasons)
                            ncases+=1
            past[asset].extend(r for r in paths[asset,0] if r['accepted'] and r['valid'] and r['prior_state']!='missing_history')
        require(len(forecast)==3*len(EDGES)*len(paths[ASSETS[0],0]),'extra/missing forecast grid')
        require(len(bundles[4][1])==len(PAYOUTS)*len(EDGES)*len(DELAYS),'joint grid differs')
        require({(r['multiplier'],r['edge_bps'],r['delay_ms']) for r in bundles[4][1]}=={(m,e,d) for m in PAYOUTS for e in EDGES for d in DELAYS},'duplicate/missing joint configuration')
        for j in bundles[4][1]:check_joint(j,[codes[a,j['multiplier'],j['edge_bps'],j['delay_ms']] for a in ASSETS],j['multiplier']);njoint+=1
        print(json.dumps(dict(day=day,forecasts_verified=nforecasts,cases_verified=ncases)),flush=True)
    require(days==p['days'],'incomplete/changed audit calendar')
    require(len(result['summary'])==len(total),'summary grid differs')
    require({(r['asset'],r['multiplier'],r['edge_bps'],r['delay_ms'],r['strategy']) for r in result['summary']}==set(total),'duplicate/missing summary case')
    for r in result['summary']:
        key=r['asset'],r['multiplier'],r['edge_bps'],r['delay_ms'],r['strategy']
        check_cash(r,total[key],r['multiplier'],r['edge_bps'])
        require(r['oracle_quote_available']==oracle_total[key] and r['refusal_reasons']==dict(reason_total[key]),'summary availability/refusal differs')
    with (output/'native-quantization.jsonl').open() as f:native=[json.loads(l) for l in f]
    require([(r['price'],r['width_ppb'],r['delta']) for r in native]==sorted(vectors),'missing/extra native vector')
    bridge=Bridge(output/'fuse-research')
    try:
        for i in range(0,len(native),2048):
            rows=native[i:i+2048]
            got=bridge.send(dict(kind='quantize_corridors',policy=read(output/'native-policy.json'),corridors=[dict(price=r['price'],width_ppb=r['width_ppb']) for r in rows]))['value']
            require(got==rows and all(r['valid'] for r in rows),'native integer verification differs')
    finally:bridge.close()
    verify(output)
    require(nforecasts==result['forecasted_asset_payout_edge_opportunities'] and ncases==result['daily_strategy_cases'] and njoint==result['daily_joint_cases'],'audit coverage differs')
    checked=dict(passed=True,protocol_sha256=sha(output/'protocol.json'),result_sha256=sha(output/'result.json'),
        auditor_sha256=sha(__file__),forecasts_reconstructed=nforecasts,cash_cases_replayed=ncases,
        joint_cases_checked=njoint,native_arithmetic_vectors_reexecuted=len(native),independent_external_review=False,
        production_pricing_validated=False,goal_complete=False)
    write(output/'audit.json',checked);return checked


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True)
    print(json.dumps(audit(p.parse_args().output)))
