"""Earlier-only per-asset realized-volatility opening gates; not Cboe VIX."""
from collections import Counter
from math import lcm

from active_tail_payout import admissible
from research_trial_liquidity import training

GATES=('none','fast25','fast50','fast75','slow25','slow50','slow75')
BASES=('active_hybrid','conditional_recent')
SPEC=dict(version='volatility-open-gate-v1',gates=GATES,bases=BASES,
    meaning='Asset oracle realized volatility, not options-implied VIX. Fast is preceding 60 seconds; slow is preceding 300 seconds, both in ppm.',
    fitting='Separate assets, strictly earlier matured admissible matched paths. Last three observed training dates with equal date mass. Exact weighted quartiles; no outcome-based threshold selection.',
    gate='Open when preceding oracle volatility is at least its earlier fitted 25th, 50th or 75th percentile. Retain every underlying book/flat/model veto and width. none exactly reproduces the base.',
    bases_explained='active_hybrid uses active_empirical at X100 and active_calibrated at X1000; conditional_recent is unchanged. The hybrid is declared before gate replay, motivated by the inadequate parametric X100 tail and absent empirical X1000 support.',
    timing='Freeze thresholds at UTC midnight, same zero-lookahead features. A gate closes admission only, never cancels an existing corridor. No hysteresis/dwell-time simulation in this ablation.',
    evidence='Already inspected historical development; no threshold selected from September outcomes, no fresh holdout or causal liquidity claim. Full original availability denominator and prior screens retained; no live promotion.')


def fit(rows,asset,cutoff):
    earlier=[r for r in training(rows,asset,cutoff) if admissible(r)];dates=sorted({r['period'] for r in earlier})[-3:];part=[r for r in earlier if r['period'] in dates]
    if len(part)<200 or len(dates)<3:raise ValueError('Insufficient volatility gate fit support')
    counts=Counter(r['period'] for r in part);common=lcm(*counts.values());thresholds={}
    for axis,field in (('fast','vol_60_ppm'),('slow','vol_300_ppm')):
        pairs=sorted((r['adaptive_features'][field],common//counts[r['period']]) for r in part)
        for q in (25,50,75):
            total=0
            for value,mass in pairs:
                total+=mass
                if total*100>=q*len(counts)*common:break
            thresholds[axis+str(q)]=float(value)
    return dict(asset=asset,cutoff=cutoff,training_dates=dates,rows=len(part),thresholds=thresholds)


def opens(row,gate,model):
    if gate=='none':return True
    if row['adaptive_features'] is None:return False
    field='vol_60_ppm' if gate.startswith('fast') else 'vol_300_ppm'
    return row['adaptive_features'][field]>=model['thresholds'][gate]


def apply(row,prediction,gate,model):
    if opens(row,gate,model) or not prediction['offered']:return prediction
    return dict(prediction,offered=False,survived=None,reason='volatility_open_gate')
