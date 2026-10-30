#!/usr/bin/env python3
"""Offline candidate for a finite, pool-wide, below-$3M LP campaign.

Exact rational scores are a specification oracle, not a production checkpoint
implementation. Inputs must already exclude customer custody, funded exits,
backing, and operations, and identify ineligible protocol/requested-exit equity.
No assumed token market price, customer demand, or guaranteed LP return.
"""
from dataclasses import dataclass
from fractions import Fraction

USDC = 10**6
TOKEN = 10**18
DAY = 86400
BUDGET = 50_000_000 * TOKEN
DAYS = 90
VESTING = 30 * DAY
FULL_RATE_EQUITY = 250_000 * USDC
STOP_EQUITY = 3_000_000 * USDC
TARGET_UTILIZATION_BPS = 2000


def scheduled(epoch):
    if type(epoch) is not int or not 0 <= epoch < DAYS:
        raise ValueError('epoch outside the single 90-day campaign')
    def cumulative(n):
        return BUDGET * n * (2 * DAYS - n) // (DAYS * DAYS)
    return cumulative(epoch + 1) - cumulative(epoch)


def taper(equity):
    if type(equity) is not int or equity < 0:
        raise ValueError('invalid equity')
    return min(Fraction(1), max(Fraction(0),
        Fraction(STOP_EQUITY - equity, STOP_EQUITY - FULL_RATE_EQUITY)))


@dataclass(frozen=True)
class Segment:
    seconds: int
    # All equity bears risk and enters the denominator. Only the subset in
    # eligible earns tokens; protocol capital and requested exits are excluded.
    equity: dict
    eligible: frozenset
    liability: int


def epoch_entitlements(epoch, segments):
    cap = scheduled(epoch)
    total_seconds = capital_time = liability_time = 0
    scores = {}
    for segment in segments:
        if type(segment.seconds) is not int or segment.seconds <= 0:
            raise ValueError('invalid segment duration')
        if not isinstance(segment.eligible, frozenset) or not segment.eligible <= segment.equity.keys():
            raise ValueError('invalid eligible owners')
        if any(not isinstance(k, str) or not k or type(v) is not int or v < 0
               for k, v in segment.equity.items()):
            raise ValueError('invalid capital account')
        equity = sum(segment.equity.values())
        if type(segment.liability) is not int or not 0 <= segment.liability <= equity:
            raise ValueError('liability must be funded by underwriting equity')
        total_seconds += segment.seconds
        capital_time += equity * segment.seconds
        liability_time += segment.liability * segment.seconds
        factor = taper(equity)
        for owner in segment.eligible:
            scores[owner] = scores.get(owner, Fraction(0)) + segment.equity[owner] * segment.seconds * factor
    if total_seconds != DAY:
        raise ValueError('complete nonoverlapping daily segments required')
    utilization = min(Fraction(1), Fraction(liability_time * 10000,
        capital_time * TARGET_UTILIZATION_BPS)) if capital_time else Fraction(0)
    # Use a single rational calculation then floor each cumulative daily claim.
    # Splitting wallets cannot increase a parent's aggregate entitlement.
    entitlements = {owner: int(cap * utilization * score / capital_time)
                    for owner, score in sorted(scores.items())} if capital_time else {}
    earned = sum(entitlements.values())
    if not 0 <= earned <= cap:
        raise AssertionError('daily allocation exceeded')
    return dict(epoch=epoch, scheduled_fuse_units=cap,
                earned_fuse_units=earned, unused_fuse_units=cap-earned,
                capital_usdc_seconds=capital_time, liability_usdc_seconds=liability_time,
                entitlements=entitlements)


class Campaign:
    """One campaign. Skipped slots expire; exit does not cancel vested rights."""
    def __init__(self):
        self.latest = -1
        self.epochs = {}
        self.claimed = set()
        self.earned = self.paid = 0

    def close(self, epoch, segments):
        if epoch <= self.latest:
            raise ValueError('epoch already closed or expired')
        row = epoch_entitlements(epoch, segments)
        self.latest = epoch
        self.epochs[epoch] = row
        self.earned += row['earned_fuse_units']
        assert self.paid <= self.earned <= BUDGET
        return row

    def claim(self, epoch, owner, now):
        key = (epoch, owner)
        amount = self.epochs.get(epoch, {}).get('entitlements', {}).get(owner, 0)
        if not amount or key in self.claimed or now < (epoch+1)*DAY + VESTING:
            raise ValueError('unavailable, unvested, or already claimed')
        self.claimed.add(key)
        self.paid += amount
        assert self.paid <= self.earned <= BUDGET
        return amount


def bootstrap_evidence():
    grid = []
    # Fully external, constant equity, full target utilization. Upper-bound
    # illustrations of the proposal, not estimates of actual participation.
    for dollars in (250_000, 500_000, 1_000_000, 2_000_000, 2_750_000, 3_000_000, 4_000_000):
        equity = dollars * USDC
        segments = [Segment(DAY, {'external': equity}, frozenset({'external'}), equity//5)]
        campaign = Campaign()
        for epoch in range(DAYS):
            campaign.close(epoch, segments)
        grid.append(dict(pool_usdc_units=equity, taper_numerator=taper(equity).numerator,
            taper_denominator=taper(equity).denominator,
            earned_fuse_units=campaign.earned,
            initial_backing_equivalent_usdc_units=campaign.earned * 125_000 * USDC // (1_000_000_000*TOKEN)))
    return dict(proposed_only=True, production_implemented=False, budget_funded_or_verified=False,
        pool_threshold_usdc_units=STOP_EQUITY, full_rate_pool_usdc_units=FULL_RATE_EQUITY,
        maximum_fuse_units=BUDGET, campaign_days=DAYS, vesting_seconds=VESTING,
        target_utilization_bps=TARGET_UTILIZATION_BPS,
        initial_backing_equivalent_max_usdc_units=6250*USDC,
        initial_backing_equivalent_assumptions='125k backing, 1B outstanding, no later funding or haircut; not a token market price or guaranteed redemption value',
        constant_fully_external_at_target_utilization=grid,
        attack_bound='Even if all qualifying liability-time is self-funded LP/player activity, total awarded tokens cannot exceed 50M. Utilization is not proof of organic demand or resistance to wash activity.',
        future_dollar_value_bounded=False,
        required_additional_underwriting_to_reach_threshold_usdc_units=2_750_000*USDC)
