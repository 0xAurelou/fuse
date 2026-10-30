"""Causal entry-selection diagnostics on immutable adaptive quote tapes.

Two-times unit tickets, before actual reserve fees/funding/LP share accounting.
No pricing, fitting, actual trades or inference of independent observations.
"""
from collections import deque
from dataclasses import dataclass
import math

GRID=30000
BLOCK=8*3600000
UNIT=1000000
TARGET=.48
COST_BPS=(0,10,50,100)
ACCOUNTS=(1,3)
STRATEGIES=(
    'all_offered','frozen_only','nonfrozen_only','width_at_most_10ppm',
    'width_over_10ppm','minimum_width_1ppm','last_matured_survived',
    'last_matured_failed','last12_majority_survived','last12_majority_failed',
    'internal_floor_at_least_48','internal_floor_at_least_53','internal_floor_below_48',
)
SPEC=dict(multiplier=2,stake_usdc=1,accounts=ACCOUNTS,cost_bps=COST_BPS,strategies=STRATEGIES,
    outcome='Archived shadow at original width. Selected censored entries stay in placed-ticket denominators. An assumed refund gives zero trading PnL; independent all-win/all-loss censoring bounds are also reported.',
    public_signals='Quoted width and pre-entry oracle activity; public opportunity labels become available only entry+60s, matching the existing conservative maturity delay. Labels are from every offered opportunity, whether this strategy entered it or not.',
    internal_signals='Forecast-floor strategies are informed stress diagnostics: floor is not assumed to be visible to real users.',
    history='Private trader label state per archived pricing session. Continuous sessions carry matured history across eight-hour reporting blocks; restart sessions begin with empty trader history.',
    cost='Illustrative total expense per placed ticket as a fixed fraction of stake, including assumed-refunded tickets. These are sensitivities, not measured reserve fees, gas or operating costs.',
    selection='All declared strategies and costs are reported; no winning policy is selected or fitted. Already inspected historical dates are development data, not a new holdout.',
    capital='Uncapped unit-ticket counterfactual. No reserve admission, recovery policy, bankroll gate, fee-on-profit, share NAV, token liquidity, capital funding or dynamic demand simulation. Three accounts repeat exactly the same path; they are not independent.',
    aggregation='Separate source/date/pricing session and original UTC eight-hour block. Never pool continuous/restart or raw/normalized duplicates into an independent sample.',
    production_approved=False,economics_validated=False)


@dataclass(frozen=True)
class Quote:
    start:int
    activity:str
    width:int
    floor:float
    offered:bool


def validate(records):
    previous=None
    for r in records:
        at=r['start'];width=r['width'];floor=r['floor'];shadow=r['shadow']
        if (type(at) is not int or (previous is not None and at!=previous+GRID)
                or (width is not None and (type(width) is not int or not 1<=width<=50000))
                or type(r['paused']) is not bool or not isinstance(r['activity'],str)
                or (shadow is not None and type(shadow) is not bool)
                or (floor is not None and (type(floor) not in (int,float) or not math.isfinite(floor) or not 0<=floor<=1))
                or (width is None and shadow is not None)):
            raise ValueError('invalid or non-contiguous archived quote tape')
        previous=at


def intends(strategy,quote,history):
    """Only pre-entry fields and already matured public labels are accessible."""
    if strategy not in STRATEGIES:raise ValueError('undeclared entry strategy')
    if not quote.offered:return False
    if strategy=='all_offered':return True
    if strategy=='frozen_only':return quote.activity=='frozen'
    if strategy=='nonfrozen_only':return quote.activity!='frozen'
    if strategy=='width_at_most_10ppm':return quote.width<=10
    if strategy=='width_over_10ppm':return quote.width>10
    if strategy=='minimum_width_1ppm':return quote.width==1
    if strategy=='last_matured_survived':return bool(history) and history[-1]
    if strategy=='last_matured_failed':return bool(history) and not history[-1]
    if strategy=='last12_majority_survived':return len(history)>=12 and sum(history)>6
    if strategy=='last12_majority_failed':return len(history)>=12 and sum(history)<6
    if strategy=='internal_floor_at_least_48':return quote.floor is not None and quote.floor>=.48
    if strategy=='internal_floor_at_least_53':return quote.floor is not None and quote.floor>=.53
    if strategy=='internal_floor_below_48':return quote.floor is not None and quote.floor<.48
    raise AssertionError('unhandled declared strategy')


def decisions(records):
    validate(records);history=deque(maxlen=12);pending=deque();result=[]
    for r in records:
        while pending and pending[0][0]<=r['start']:
            _,label=pending.popleft();history.append(label)
        q=Quote(r['start'],r['activity'],r['width'],r['floor'],r['width'] is not None and not r['paused'])
        chosen=[name for name in STRATEGIES if intends(name,q,history)]
        result.append(dict(start=q.start,strategies=chosen))
        if q.offered and r['shadow'] is not None:pending.append((q.start+2*GRID,r['shadow']))
    return result


def summarize(records,chosen,strategy,accounts=1):
    if accounts not in ACCOUNTS:raise ValueError('undeclared account multiplicity')
    if len(records)!=len(chosen):raise ValueError('decision alignment differs')
    placed=[]
    for r,d in zip(records,chosen):
        if r['start']!=d['start']:raise ValueError('decision clock differs')
        if strategy in d['strategies']:placed.append(r)
    wins=sum(r['shadow'] is True for r in placed);losses=sum(r['shadow'] is False for r in placed)
    unknown=sum(r['shadow'] is None for r in placed);resolved=wins+losses
    trading=accounts*UNIT*(losses-wins);turnover=len(placed)*accounts*UNIT
    peak=0;balance=0;drawdown=0;gross_survivor_loss=0;max_consecutive_loss=0;run=0
    for r in placed:
        pnl=0 if r['shadow'] is None else accounts*UNIT*(-1 if r['shadow'] else 1)
        balance+=pnl;peak=max(peak,balance);drawdown=max(drawdown,peak-balance)
        if r['shadow'] is True:
            run+=1;gross_survivor_loss+=accounts*UNIT
        else:
            max_consecutive_loss=max(max_consecutive_loss,run);run=0
    max_consecutive_loss=max(max_consecutive_loss,run)
    sensitivity=[]
    for bps in COST_BPS:
        cost=turnover*bps//10000;net=trading-cost
        if net-trading+cost!=0 or net+(-trading)+cost!=0:raise AssertionError('cash conservation')
        sensitivity.append(dict(expense_bps=bps,allocated_expense_usdc_units=cost,
            lp_net_assuming_censored_refund_usdc_units=net,
            lp_net_return_per_placed_stake=net/turnover if turnover else None,
            lp_net_lower_if_all_censored_survive_usdc_units=net-unknown*accounts*UNIT,
            lp_net_upper_if_all_censored_fail_usdc_units=net+unknown*accounts*UNIT,
            expected_margin_at_48_percent=1-2*TARGET-bps/10000,
            break_even_survival=(1-bps/10000)/2))
    return dict(strategy=strategy,signal_access='internal_forecast_stress' if strategy.startswith('internal_') else 'public_quote_and_oracle_history',
        accounts=accounts,grid_windows=len(records),offered_grid_windows=sum(r['width'] is not None and not r['paused'] for r in records),
        selected_grid_entries=len(placed),placed_tickets=len(placed)*accounts,
        selection_fraction_of_grid=len(placed)/len(records) if records else None,
        resolved_grid_entries=resolved,censored_grid_entries=unknown,survived_grid_entries=wins,
        survival=wins/resolved if resolved else None,
        lp_gross_assuming_censored_refund_usdc_units=trading,customer_gross_usdc_units=-trading,
        placed_turnover_usdc_units=turnover,lp_gross_return_per_placed_stake=trading/turnover if turnover else None,
        settlement_pnl_drawdown_usdc_units=drawdown,gross_survivor_losses_usdc_units=gross_survivor_loss,
        maximum_consecutive_selected_survivors=max_consecutive_loss,
        shared_outcomes_independent=False,cost_sensitivity=sensitivity,
        actual_lp_reserve_fees_evaluated=False,funded_admission_evaluated=False,economics_validated=False)


def evaluate(records,origin):
    chosen=decisions(records);groups={}
    for r,d in zip(records,chosen):
        block=(r['start']-origin)//BLOCK
        if not 0<=block<3:raise ValueError('quote outside declared historical day')
        rows,ds=groups.setdefault(block,([],[]));rows.append(r);ds.append(d)
    result=[]
    for block,(rows,ds) in sorted(groups.items()):
        if len(rows)!=960:raise ValueError('complete original eight-hour grid required')
        result.extend(dict(block_hour=block*8,start=origin+block*BLOCK,end=origin+(block+1)*BLOCK,
            **summarize(rows,ds,strategy,accounts)) for strategy in STRATEGIES for accounts in ACCOUNTS)
    return result,chosen
