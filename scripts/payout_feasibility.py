"""Exact necessary economics bounds, not pricing or a causal admission policy."""
from fractions import Fraction
import math


def retention_bound(total,flat,upper):
    """Largest hindsight subset whose mandatory winners can be <= upper.

    A path with no oracle motion survives every positive representable corridor.
    Grant perfect foresight to reject flat paths first and make every other
    path lose. This optimistic bound ignores quantization, width caps, parameter
    learning, future uncertainty, lower calibration bands and trading costs.
    """
    upper=Fraction(upper)
    if (not isinstance(total,int) or not isinstance(flat,int)
            or not 0<=flat<=total or not 0<=upper<=1):raise ValueError('invalid path counts or probability')
    if total==0:return dict(maximum_kept=None,minimum_refusals=None,maximum_retention=None)
    kept=total if upper==1 else min(total,(total-flat)//(1-upper))
    return dict(maximum_kept=kept,minimum_refusals=total-kept,maximum_retention=kept/total)


def target(multiplier,edge_bps=500,cost_bps=0):
    """Payout includes stake; desired gross margin plus allocated cost per stake."""
    if (not isinstance(multiplier,int) or multiplier<2
            or not isinstance(edge_bps,int) or not isinstance(cost_bps,int)
            or not 0<=edge_bps<=10000 or not 0<=cost_bps<=10000):raise ValueError('invalid payout, edge or cost')
    available=10000-edge_bps-cost_bps
    return Fraction(available,10000*multiplier) if available>=0 else None


def batch_return(probability,multiplier,cost_bps=0,positive_profit_allocation_bps=0):
    """Illustrative equal-stake batch profit, not contract high-water accounting.

    The optional flat allocation of positive net batch profit is a stated stress
    assumption. Actual reserve accrual is path/capital/high-water dependent.
    """
    probability=Fraction(probability)
    if (not 0<=probability<=1 or not isinstance(multiplier,int) or multiplier<2
            or not isinstance(cost_bps,int) or not 0<=cost_bps<=10000
            or not isinstance(positive_profit_allocation_bps,int)
            or not 0<=positive_profit_allocation_bps<=10000):raise ValueError('invalid batch assumption')
    gross=1-multiplier*probability
    fee=max(Fraction(0),gross)*Fraction(positive_profit_allocation_bps,10000)
    return dict(gross=gross,allocation=fee,cost=Fraction(cost_bps,10000),net=gross-fee-Fraction(cost_bps,10000))


def maximum_liability(stake,multiplier,tickets=1,funded=None):
    """Additive maximum obligation less only physically funded stake."""
    funded=stake if funded is None else funded
    if (not all(isinstance(v,int) for v in (stake,multiplier,tickets,funded))
            or stake<=0 or multiplier<2 or tickets<0 or not 0<=funded<=stake):raise ValueError('invalid funded ticket')
    return tickets*(stake*multiplier-funded)


def rare_event_diagnostic(probability,windows=960,confidence=.95):
    """Independent Bernoulli illustration; not an effective sample size claim."""
    p=float(probability)
    if not 0<=p<=1 or not isinstance(windows,int) or windows<0 or not 0<confidence<1:
        raise ValueError('invalid event illustration')
    chance=(1. if windows else 0.) if p==1 else -math.expm1(windows*math.log1p(-p))
    needed=None if p==0 else 1 if p==1 else math.ceil(math.log1p(-confidence)/math.log1p(-p))
    return dict(windows=windows,expected_survivors=windows*p,chance_of_at_least_one_survivor=chance,
        confidence=confidence,independent_windows_for_requested_chance_one_survivor=needed,
        days_at_nonoverlapping_30s_grid=needed/2880 if needed is not None else None)
