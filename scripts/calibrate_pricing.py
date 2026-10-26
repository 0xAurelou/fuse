#!/usr/bin/env python3
"""Chronological, purged 30s oracle calibration from retained real HyperCore runs."""
import argparse
from bisect import bisect_left, bisect_right
from collections import Counter
from decimal import Decimal
from fractions import Fraction
import hashlib
import json
import math
from pathlib import Path
import time

ROOT = Path(__file__).resolve().parent.parent


def observations(directory):
    sources, result = {}, []
    gap = 8000
    with (directory / "journal.jsonl").open() as stream:
        for line in stream:
            e = json.loads(line); c = e["command"]
            if c["kind"] == "policy_update": gap = c["raw"]["max_gap_ms"]
            if c["kind"] != "oracle": continue
            price = int(Decimal(c["raw"]["data"]["ctx"]["oraclePx"]) * 1_000_000)
            sources[c["source"]] = (c["at"], price)
            if len(sources) == 2 and sources["a"][1] == sources["b"][1] and all(c["at"] - at <= gap for at, _ in sources.values()):
                result.append((c["at"], price))
    return result


def windows(observed, stride_ms=30000):
    out = []; times = [a for a, _ in observed]
    if not observed: return out
    start = observed[0][0]
    while start + 30000 <= observed[-1][0]:
        i = bisect_right(times, start) - 1
        end = bisect_right(times, start + 30000)
        segment = observed[i:end]
        # Exclude incomplete/gapped windows; do not interpolate across an outage.
        if i >= 0 and start - observed[i][0] <= 8000 and segment and start+30000-segment[-1][0]<=8000 and all(b[0]-a[0] <= 8000 for a,b in zip(segment,segment[1:])):
            entry = observed[i][1]
            path = [(at,px) for at,px in segment if start <= at < start+30000]
            if path:
                max_move_ppm = max(abs(px-entry)*1_000_000/entry for _,px in path)
                out.append({"start":start,"expiry":start+30000,"entry":entry,"max_move_ppm":max_move_ppm,"max_move_units":max(abs(px-entry) for _,px in path)})
        start += stride_ms
    return out


def healthy_windows(directory, policy, observed):
    """Exclude windows invalidated by the committed disagreement/gap rule.

    Pair spacing alone misses short disagreements that make real stages pending.
    Reconstruct the reducer's pre-command health checks, including timer ticks.
    """
    sources, canonical, mismatch, bad, receipts = {}, None, None, [], []
    with (directory/'journal.jsonl').open() as stream:
        for line in stream:
            c = json.loads(line)['command']; at = c['at']
            if not c['kind'].startswith('local_'):
                if (len(sources) < 2 or any(at-t > policy['max_gap_ms'] for t, _ in sources.values())
                        or (mismatch is not None and at-mismatch >= policy['disagreement_ms'])):
                    bad.append(at)
            if c['kind'] != 'oracle':
                continue
            price = int(Decimal(c['raw']['data']['ctx']['oraclePx'])*1000000)
            sources[c['source']] = (at, price)
            if len(sources) == 2 and sources['a'][1] == sources['b'][1]:
                mismatch = None
                if all(at-t <= policy['max_gap_ms'] for t, _ in sources.values()):
                    canonical = price
            elif mismatch is None:
                mismatch = at
            receipts.append((at, dict(sources), canonical))
    times = [r[0] for r in receipts]
    result = []
    for row in windows(observed):
        start_index = bisect_right(times, row['start'])-1
        if start_index < 0:
            continue
        _, feeds, price = receipts[start_index]
        if len(feeds) != 2 or price != row['entry'] or any(row['start']-t > policy['max_gap_ms'] or px != price for t, px in feeds.values()):
            continue
        if bisect_right(bad, row['expiry']) > bisect_right(bad, row['start']):
            continue
        i = bisect_left(times, row['expiry'])-1
        if i < 0:
            continue
        _, feeds, price = receipts[i]
        if len(feeds) == 2 and all(row['expiry']-t <= policy['max_gap_ms'] and px == price for t, px in feeds.values()):
            result.append(row)
    return result


def survival(rows,width):
    if not rows: return None
    return sum(r["max_move_units"] < r["entry"]*width//1_000_000 for r in rows) / len(rows)


def wilson(successes,n):
    if not n:return [None,None]
    z=1.96;p=successes/n;d=1+z*z/n
    center=(p+z*z/(2*n))/d;half=z*math.sqrt(p*(1-p)/n+z*z/(4*n*n))/d
    return [max(0,center-half),min(1,center+half)]


def survival_thresholds(rows):
    """Smallest integer ppm width that survives each exact engine price path.

    floor(entry * width / 1e6) > max_move is equivalent to
    entry * width >= (max_move + 1) * 1e6. Touches therefore remain losses.
    """
    if not rows:
        raise ValueError('no complete training windows')
    result = []
    for row in rows:
        entry, movement = row['entry'], row['max_move_units']
        if type(entry) is not int or type(movement) is not int or entry <= 0 or movement < 0:
            raise ValueError('positive integer entry and nonnegative integer movement required')
        result.append(((movement+1)*1000000+entry-1)//entry)
    return sorted(result)


def _target(target):
    value = Fraction(str(target))
    if not 0 <= value <= 1:
        raise ValueError('target must be in [0,1]')
    return value


def survival_frontier(rows, minimum=1, maximum=None):
    """Enumerate all attainable empirical survival rates in O(n log n).

    Between consecutive thresholds the survival count is constant. Its narrowest
    width is sufficient to globally minimize target error with the existing tie rule.
    """
    if type(minimum) is not int or minimum < 1 or (maximum is not None and (type(maximum) is not int or maximum < minimum)):
        raise ValueError('invalid integer width bounds')
    thresholds = survival_thresholds(rows)
    counts = Counter(thresholds)
    survived = bisect_right(thresholds, minimum)
    result = [{'width_ppm': minimum, 'survived': survived, 'windows': len(rows)}]
    for width in sorted(counts):
        if width <= minimum:
            continue
        if maximum is not None and width > maximum:
            break
        survived += counts[width]
        result.append({'width_ppm': width, 'survived': survived, 'windows': len(rows)})
    return result


def choose_width(frontier, target):
    probability = _target(target)
    if not frontier:
        raise ValueError('empty survival frontier')
    return min(frontier, key=lambda point: (abs(point['survived']*probability.denominator-point['windows']*probability.numerator), point['width_ppm']))


def fit(train, target, minimum=1, maximum=None):
    return choose_width(survival_frontier(train, minimum, maximum), target)['width_ppm']


def fit_pinball(train, target, minimum=1, maximum=None):
    """Exact minimizer of a convex scalar quantile-loss surrogate, no LP dependency.

    Loss = sum(tau*max(threshold-width,0) + (1-tau)*max(width-threshold,0)).
    Its lower quantile minimizes the continuous relaxation; integer thresholds
    and bounds give an integer optimum too. This is a different objective from
    matching an empirical survival fraction, particularly when prices are tied.
    """
    probability = _target(target)
    survival_frontier(train, minimum, maximum)  # Validate the same legal bounds.
    if probability == 0:
        return minimum
    thresholds = survival_thresholds(train)
    rank = (probability.numerator*len(thresholds)+probability.denominator-1)//probability.denominator
    width = max(minimum, thresholds[rank-1])
    return min(width, maximum) if maximum is not None else width


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runs',type=Path,default=ROOT/'.local/live-runs')
    parser.add_argument('--output',type=Path,default=ROOT/'.local/pricing-calibration')
    args=parser.parse_args(); datasets=[]; hashes=[]
    for path in sorted(args.runs.glob('*/evidence/summary.json')):
        data=path.parent
        policy_path=data/'initial-policy.json'
        actual_policy=json.loads(policy_path.read_text()) if policy_path.exists() else json.loads((data/'final-state.json').read_text())['policy']
        rows=healthy_windows(data,actual_policy,observations(data))
        for row in rows:row['run']=data.parent.name
        datasets.extend(rows); hashes.append({'path':str(data),'sha256':hashlib.sha256((data/'journal.jsonl').read_bytes()).hexdigest(),'windows':len(rows)})
    datasets.sort(key=lambda r:r['start'])
    # Global chronological split; complete 30s, non-overlapping windows. Purge
    # any boundary overlap, including overlapping captured runs.
    independent=[]
    for row in datasets:
        if not independent or row['start']>=independent[-1]['expiry']: independent.append(row)
    if len(independent)<6:raise ValueError('at least six complete independent windows required')
    a=max(1,int(len(independent)*.6));b=max(a+1,int(len(independent)*.8))
    train,validation,test=independent[:a],independent[a:b],independent[b:]
    targets=[]
    # This experiment measures the historical fixed-payout ladder only.
    policy=json.loads((ROOT/'engine/testdata/legacy-ladder-policy.json').read_text())
    policy['mode']='local'
    maximum=policy['model']['max_width_bps']*100
    frontier=survival_frontier(train, maximum=maximum)
    for target_bps in range(4000,5401,100):
        target=target_bps/10000;point=choose_width(frontier,target);width=point['width_ppm']
        probability=_target(target);pinball=fit_pinball(train,target,maximum=maximum)
        targets.append({'target_survival':target,'width_ppm':width,'train_survival':survival(train,width),'validation_survival':survival(validation,width),'test_survival':survival(test,width),'test_95pct_interval':wilson(sum(r['max_move_units'] < r['entry']*width//1_000_000 for r in test),len(test)),
                        'exact_training_target_attainable':point['survived']*probability.denominator==len(train)*probability.numerator,
                        'convex_pinball_width_ppm':pinball,'convex_pinball_train_survival':survival(train,pinball)})
    selected=next(r for r in targets if r['target_survival']==.48)
    readiness=len(train)>=200 and len(validation)>=100 and len(test)>=100
    report={'dataset':hashes,'window_ms':30000,'counts':{'train':len(train),'validation':len(validation),'test':len(test)},'split':'chronological 60/20/20; 30s non-overlapping windows; overlap purged; no interpolation','targets':targets,'selected':selected,'production_approved':False,'minimum_sample_gate_passed':readiness,
            'optimizer':{'method':'exact integer survival frontier','complexity':'O(n log n) preprocessing; shared across targets','frontier_points':len(frontier),'maximum_width_ppm':maximum,'frontier':frontier,'comparison':'Convex scalar pinball loss solved exactly by an order statistic; it need not minimize empirical calibration error when thresholds are tied.'},
            'limits':'Short correlated BTC captures. Stage-conditioned survival cannot be estimated reliably; no production calibration claim.'}
    args.output.mkdir(parents=True,exist_ok=True)
    (args.output/'calibration.json').write_text(json.dumps(report,indent=2)+'\n')
    dataset_hash=hashlib.sha256(json.dumps({'dataset':hashes,'method':'exact-integer-frontier-v1','target_survival':.48,'maximum_width_ppm':maximum,'eligibility':'paired-entry-expiry-gap-disagreement-v1'},sort_keys=True).encode()).hexdigest()
    policy['version']='local-calibration-research-'+dataset_hash[:12]
    policy['model'].update(version=policy['version'],dataset='captured HyperCore oraclePx '+dataset_hash,training_window=str(report['counts'])+'; purged chronological windows',out_of_sample_error=f"research only; test survival {selected['test_survival']:.4f}; n={len(test)}; 95% CI {selected['test_95pct_interval']}",base_width_bps=0,base_width_ppm=selected['width_ppm'],control_width_bps=0,volatility_factor=0,valid_until=int(time.time()*1000)+86400000)
    (args.output/'policy.json').write_text(json.dumps(policy,indent=2)+'\n')
    lines=['# Oracle pricing calibration','',f"Independent windows: {len(train)} training, {len(validation)} validation, {len(test)} test. Widths are selected from training only; validation/test never select parameters.",'','| Target survival | Half-width bps | Train | Validation | Test |','|---:|---:|---:|---:|---:|']
    for r in targets:lines.append(f"| {r['target_survival']:.0%} | {r['width_ppm']/100:.2f} | {r['train_survival']:.1%} | {r['validation_survival']:.1%} | {r['test_survival']:.1%} |")
    lines+=['',f"The 48% hypothesis selects {selected['width_ppm']/100:.2f} bps. Held-out 95% interval: {selected['test_95pct_interval']}. Minimum sample gate passed: {readiness}.",'','This is a research candidate, not a demonstrated 48% survival model. Capture substantially more real oracle data across regimes before production. Flat windows and discrete oracle updates limit attainable probabilities. The research live runner may use policy.json; no public execution is enabled.']
    lines+=['',f"Search enumerated {len(frontier)} attainable training survival counts using exact integer thresholds, rather than scanning every ppm width. Legal maximum: {maximum/100:.2f} bps. Exact 48% training fraction attainable: {selected['exact_training_target_attainable']}.",
            '',f"The convex scalar quantile-loss optimum is {selected['convex_pinball_width_ppm']/100:.2f} bps, with training survival {selected['convex_pinball_train_survival']:.1%}. Convex loss optimality and exact probability calibration are different claims. Neither establishes conditional survival on later ladder stages or future data."]
    (args.output/'report.md').write_text('\n'.join(lines)+'\n')
    print(args.output/'report.md');print(json.dumps({'selected':selected,'counts':report['counts'],'minimum_sample_gate_passed':readiness}))

if __name__=='__main__':main()
