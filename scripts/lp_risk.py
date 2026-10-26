"""Exact, simulation-only admission controls; existing accepted risk is never canceled."""
from collections import deque
from dataclasses import dataclass
from fractions import Fraction

DAY = 86400
RISK_SCALE = 10**36


def floor(value):
    return value.numerator // value.denominator


def ceil(value):
    return -(-value.numerator // value.denominator)


@dataclass(frozen=True)
class RiskPolicy:
    name: str = 'current'
    daily_loss_bps: int = 0
    rolling_loss_bps: int = 0
    rolling_days: int = 7
    pause_drawdown_bps: int = 0
    hard_drawdown_bps: int = 0
    resume_drawdown_bps: int = 0
    cooldown_seconds: int = 2 * DAY
    probe_loss_bps: int = 25
    probe_max_loss_bps: int = 0
    probe_positive_batches: int = 3
    probe_step_gain_bps: int = 10

    def __post_init__(self):
        if not (isinstance(self.rolling_days, int) and self.rolling_days > 0
                and isinstance(self.cooldown_seconds, int) and self.cooldown_seconds >= 0
                and all(isinstance(x, int) and 0 <= x < 10000 for x in (
                    self.daily_loss_bps, self.rolling_loss_bps,
                    self.pause_drawdown_bps, self.hard_drawdown_bps,
                    self.resume_drawdown_bps, self.probe_loss_bps,
                    self.probe_max_loss_bps, self.probe_step_gain_bps))
                and isinstance(self.probe_positive_batches, int) and self.probe_positive_batches > 0):
            raise ValueError('invalid loss, drawdown or timing policy')
        if self.probe_max_loss_bps and self.probe_max_loss_bps < self.probe_loss_bps:
            raise ValueError('adaptive probe maximum is below initial budget')
        if self.pause_drawdown_bps and not (
                self.resume_drawdown_bps < self.pause_drawdown_bps <= self.hard_drawdown_bps):
            raise ValueError('resume < pause <= hard drawdown is required')

    @property
    def enabled(self):
        return bool(self.daily_loss_bps or self.rolling_loss_bps or self.hard_drawdown_bps)


class RiskGuard:
    """Limits are in assets/share, so fair-NAV capital flows cannot reset losses.

    Gross incremental LP debits from winning positions consume loss budgets;
    losing traders do not replenish them. Whole-batch worst-case exposure is
    reserved before the outcomes are known. Budget reference NAV is the last
    observed NAV at/before the rolling window boundary, or inception NAV.
    """
    def __init__(self, policy, assets, shares):
        self.policy = policy
        self.peak = Fraction(assets, shares)
        self.windows = {seconds: {'nav': deque([(-1, self.peak)]),
                                  'losses': deque(), 'spent': 0}
                        for seconds in (DAY, policy.rolling_days * DAY)}
        self.mode = 'open'
        self.reopen_at = 0
        self.reserved = 0
        self.reservation_shares = 0
        self.reservation_at = 0
        self.reservation_floor = 0
        self.transitions = []
        self.pause_episodes = []
        self.last_at = 0
        self.admissions = 0
        self.settlements = 0
        self.floor_breaches_from_other_flows = 0
        self._outside_floor = False
        self.probe_budget_bps = policy.probe_loss_bps
        self.positive_probes = 0
        self.probe_step_nav = self.peak
        self.reservation_assets = assets
        self.reservation_mode = 'open'

    def _transition(self, at, mode):
        if self.mode == mode:
            return
        previous = self.mode
        self.mode = mode
        self.transitions.append({'at_seconds': at, 'from': previous, 'to': mode})
        if mode == 'paused':
            self.pause_episodes.append({'paused_at_seconds': at, 'probe_at_seconds': None,
                                        'reopened_at_seconds': None,
                                        'peak_nav_numerator': str(self.peak.numerator),
                                        'peak_nav_denominator': str(self.peak.denominator),
                                        'nav_recovered_at_seconds': None})
            self.probe_budget_bps = self.policy.probe_loss_bps
            self.positive_probes = 0
        elif mode == 'probe':
            self.pause_episodes[-1]['probe_at_seconds'] = at
            self.probe_step_nav = self.last_nav
        elif mode == 'open':
            self.pause_episodes[-1]['reopened_at_seconds'] = at

    def observe(self, at, assets, shares):
        if at < self.last_at:
            raise ValueError('risk clock moved backward')
        self.last_at = at
        nav = Fraction(assets, shares)
        self.last_nav = nav
        self.peak = max(self.peak, nav)
        for episode in self.pause_episodes:
            if episode['nav_recovered_at_seconds'] is None and nav >= Fraction(
                    int(episode['peak_nav_numerator']), int(episode['peak_nav_denominator'])):
                episode['nav_recovered_at_seconds'] = at
        for seconds, window in self.windows.items():
            history = window['nav']
            if history[-1][0] == at:
                history[-1] = (at, nav)
            elif history[-1][1] != nav:
                history.append((at, nav))
            boundary = at - seconds
            while len(history) > 1 and history[1][0] <= boundary:
                history.popleft()
            while window['losses'] and window['losses'][0][0] <= boundary:
                window['spent'] -= window['losses'].popleft()[1]
        drawdown = 1 - nav / self.peak
        p = self.policy
        outside = bool(p.hard_drawdown_bps and drawdown > Fraction(p.hard_drawdown_bps, 10000))
        if outside and not self._outside_floor:
            # Admission/settlement checks below forbid a trade-caused breach.
            # Shocks, reserve withdrawals, or other external flows are distinct.
            self.floor_breaches_from_other_flows += 1
        self._outside_floor = outside
        if p.pause_drawdown_bps:
            if self.mode == 'open' and drawdown >= Fraction(p.pause_drawdown_bps, 10000):
                self.reopen_at = at + p.cooldown_seconds
                self._transition(at, 'paused')
            elif self.mode != 'open' and at >= self.reopen_at:
                if drawdown <= Fraction(p.resume_drawdown_bps, 10000):
                    self._transition(at, 'open')
                elif self.mode == 'paused' and p.probe_loss_bps:
                    self._transition(at, 'probe')

    def remaining(self, at, shares, seconds, bps):
        if not bps:
            return None
        window = self.windows[seconds]
        # Round each debit upward and reference NAV downward at 1e36 precision.
        # A capital-flow rounding difference can only reduce new admission.
        allowance = floor(window['nav'][0][1] * RISK_SCALE) * bps // 10000
        return max(0, (allowance - window['spent']) * shares // RISK_SCALE)

    def capacity(self, at, assets, shares, fresh=True):
        self.observe(at, assets, shares)
        if self.reserved:
            raise ValueError('previous risk reservation is still open')
        if not fresh:
            return 0, 'stale_reconciliation'
        if self.mode == 'paused':
            return 0, 'drawdown_cooldown'
        limits = [(assets, 'equity')]
        p = self.policy
        if p.daily_loss_bps:
            limits.append((self.remaining(at, shares, DAY, p.daily_loss_bps), 'rolling_24h_loss'))
        if p.rolling_loss_bps:
            limits.append((self.remaining(at, shares, p.rolling_days * DAY, p.rolling_loss_bps), 'rolling_multi_day_loss'))
        if p.hard_drawdown_bps:
            minimum = ceil(self.peak * (10000 - p.hard_drawdown_bps) * shares / 10000)
            limits.append((max(0, assets - minimum), 'drawdown_floor'))
        if self.mode == 'probe':
            limits.append((self.remaining(at, shares, DAY, self.probe_budget_bps), 'probe_24h_loss'))
        return min(limits, key=lambda item: item[0])

    def reserve(self, at, assets, shares, exposure, fresh=True):
        capacity, reason = self.capacity(at, assets, shares, fresh)
        if exposure < 0 or exposure > capacity:
            raise ValueError(f'new exposure exceeds {reason}: {exposure} > {capacity}')
        self.reserved = exposure
        self.reservation_shares = shares
        self.reservation_at = at
        self.reservation_assets = assets
        self.reservation_mode = self.mode
        p = self.policy
        self.reservation_floor = (ceil(self.peak * (10000 - p.hard_drawdown_bps) * shares / 10000)
                                  if p.hard_drawdown_bps else 0)
        if exposure:
            self.admissions += 1

    def settle(self, at, loss, assets, shares):
        if at < self.reservation_at or loss < 0 or loss > self.reserved:
            raise ValueError('settled loss exceeds accepted worst-case exposure')
        if shares != self.reservation_shares:
            raise ValueError('share supply changed while exposure was open')
        if self.reserved and assets < self.reservation_floor:
            raise ValueError('accepted payout breached prospective drawdown floor')
        if loss:
            units = (loss * RISK_SCALE + shares - 1) // shares
            for window in self.windows.values():
                window['losses'].append((at, units))
                window['spent'] += units
        if self.reserved:
            self.settlements += 1
        if self.reserved and self.reservation_mode == 'probe' and self.policy.probe_max_loss_bps:
            nav = Fraction(assets, shares)
            if assets < self.reservation_assets:
                self.probe_budget_bps = self.policy.probe_loss_bps
                self.positive_probes = 0
                self.probe_step_nav = nav
            elif assets > self.reservation_assets:
                self.positive_probes += 1
                if (self.positive_probes >= self.policy.probe_positive_batches
                        and nav >= self.probe_step_nav * (10000 + self.policy.probe_step_gain_bps) / 10000):
                    self.probe_budget_bps = min(self.policy.probe_max_loss_bps, 2 * self.probe_budget_bps)
                    self.positive_probes = 0
                    self.probe_step_nav = nav
        self.reserved = 0
        self.observe(at, assets, shares)

    def summary(self):
        return {'policy': self.policy.name, 'mode': self.mode,
                'accepted_batches': self.admissions, 'settled_batches': self.settlements,
                'pause_episodes': self.pause_episodes,
                'fully_reopened_episodes': sum(q['reopened_at_seconds'] is not None for q in self.pause_episodes),
                'nav_recovered_episodes': sum(q['nav_recovered_at_seconds'] is not None for q in self.pause_episodes),
                'probe_budget_bps': self.probe_budget_bps,
                'other_flow_floor_breaches': self.floor_breaches_from_other_flows,
                'accepted_payouts_funded': self.admissions == self.settlements and self.reserved == 0}
