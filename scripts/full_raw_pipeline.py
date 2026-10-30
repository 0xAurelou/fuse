"""Refit the complete offline pricing stack on preceding raw-oracle dates."""
from copy import deepcopy
from fractions import Fraction
import math

from bursty_episodes import fit_model as fit_bursty
from chronological_raw_priors import training_rows, floor_values, replay
from research_activity_calibration import fit, predict, shadow
from research_flat_pause import ENGINE_SPEC, apply_pause
from research_frozen_pricing import PAUSE, fit_overlay, reprice as frozen_reprice
from research_startup_admission import priced
from research_raw_flat_panels import cell
from startup_admission import SPECS as RULES, admit

STAGES = ('retained', 'raw_overlay', 'raw_core')
POLICIES = ('previous_floor_53', 'warm12_floor30', 'no_pause')
VARIANTS = tuple(stage+':'+policy for stage in STAGES for policy in POLICIES)
AVAILABILITY = dict(minimum_overall=.85, minimum_populated_frozen=.50,
                    minimum_populated_cell=20,
                    role='Provisional earlier-fold availability screens; no approved production thresholds')
SPEC = dict(training='One version of each permitted earlier date; complete raw day replaces normalized day when available',
            stages=STAGES, policies=POLICIES, pricing='Unchanged activity engine, frozen hurdle overlay and floor10 burst pool120 formulas',
            selection='Full raw scoring day replaces matching normalized scoring day when available; first 14 date universe unchanged',
            population='Raw date replacements change selection population; scores are not directly comparable with preceding normalized-only scores')
SPEC['overlay_training']='All clean frozen reference paths, including refused paths; match all-reference online hurdle learning'


def fit_bundle(original, rawdays, periods, cutoff, retained, stage):
    if stage not in STAGES:
        raise ValueError('unknown pipeline stage')
    if stage == 'retained':
        return deepcopy(retained)
    rows, provenance = training_rows(original, rawdays, periods, cutoff, True)
    engine = fit(rows, ENGINE_SPEC) if stage == 'raw_core' else deepcopy(retained['engine'])
    paused = apply_pause(predict(rows,engine),PAUSE)
    # fit_overlay historically filters survived!=None. Restore shadow labels
    # explicitly so a prior for an all-reference learner is not admission-biased.
    overlay = fit_overlay(shadow(paused),retained['overlay']['spec'])
    base = frozen_reprice(paused,overlay)
    prior = fit_bursty(floor_values(base,engine))
    return dict(engine=engine,overlay=overlay,prior=prior,
                training_periods=sorted(periods),cutoff=cutoff,provenance=provenance,
                raw_dates=sum(p['source']=='raw' for p in provenance),
                training_rows=len(rows),training_frozen=sum(r['valid'] and r['activity_state']=='frozen' for r in rows))


def price(rows, bundle):
    base = priced(rows,bundle['engine'],bundle['overlay'])
    prices = replay(floor_values(base,bundle['engine']),bundle['prior'],'floor10_burst_pool120')
    return base,prices


def mask(values, base, policy):
    if policy not in POLICIES:
        raise ValueError('unknown admission policy')
    if policy == 'no_pause':
        return [dict(p,paused=False,floor_reason='',survived=p['shadow_survived']) for p in values]
    decisions = admit(base,next(r for r in RULES if r['name']==policy))
    if len(values)!=len(decisions):raise ValueError('admission alignment differs')
    return [dict(p,paused=m['paused'],floor_reason=m['floor_reason'],
                 survived=None if m['paused'] else p['shadow_survived']) for p,m in zip(values,decisions)]


def availability(cases):
    overall = [r['eligible_quote_fraction'] for r in cases if r['activity']=='all' and r['eligible_outcomes']]
    frozen = [r['eligible_quote_fraction'] for r in cases if r['activity']=='frozen' and r['eligible_outcomes']>=20]
    return dict(minimum_overall=min(overall,default=1.),minimum_populated_frozen=min(frozen,default=1.),
                feasible=min(overall,default=1.)>=AVAILABILITY['minimum_overall'] and
                         min(frozen,default=1.)>=AVAILABILITY['minimum_populated_frozen'])


def floor_bound(total, minimum_survivors, lower=Fraction(43,100), upper=Fraction(53,100)):
    """Best hindsight retention with positive widths, even granting perfect refusal.

    Other paths may be assigned either outcome without a width cap, so this is
    optimistic. It is a finite-path bound, never a forecast or causal policy.
    """
    if not isinstance(total,int) or not isinstance(minimum_survivors,int) or not 0<=minimum_survivors<=total:
        raise ValueError('integer path counts required')
    if total==0:return dict(minimum_refusals=None,maximum_retention=None,fixed_quotes_feasible=None)
    for refused in range(total):
        kept=total-refused
        mandatory=max(0,minimum_survivors-refused)
        low=max(mandatory,math.ceil(lower*kept));high=math.floor(upper*kept)
        if low<=high:
            return dict(minimum_refusals=refused,maximum_retention=kept/total,fixed_quotes_feasible=refused==0)
    return dict(minimum_refusals=None,maximum_retention=0.,fixed_quotes_feasible=False)


def bounds(values):
    result=cell(values)
    full=[p for p in values if p['shadow_survived'] is not None]
    offered=[p for p in full if not p['paused']]
    from adaptive_corridor import required_width
    for name,part in (('eligible',full),('offered',offered)):
        mandatory=sum(required_width(p['row'])<=1 for p in part)
        bound=floor_bound(len(part),mandatory)
        result.update({name+'_floor_survivors':mandatory,**{name+'_'+key:value for key,value in bound.items()}})
    return result
