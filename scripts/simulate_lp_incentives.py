#!/usr/bin/env python3
"""Research-only endogenous LP shares, withdrawal queues and bootstrap incentives.

No contract calls. Integer USDC/FUSE ledgers; behavioral probabilities are explicit
assumptions, not estimates of external LP demand. Run --help for reproduction.
"""
import argparse
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field, replace
from fractions import Fraction
import hashlib
import json
import math
from pathlib import Path
import random

from simulate_tokenomics import GENESIS, MINING, PAYOUT, TOKEN, TREASURY, USDC, emission_budgets
from lp_risk import RiskGuard, RiskPolicy

ROOT = Path(__file__).resolve().parent.parent
DAY = 86400
SHARE = 10**18


def ceil_fraction(value):
    return -(-value.numerator // value.denominator)


@dataclass(frozen=True)
class Scenario:
    name: str = 'baseline-250k'
    days: int = 180
    seed: int = 20261026
    initial_lp_usdc: int = 250_000
    lp_agents: int = 100
    wallet_usdc: int = 50_000
    traders: int = 300
    trader_wallet_usdc: int = 1000
    daily_trader_inflow_usdc: int = 0
    games_per_day: int = 300
    batches_per_day: int = 6
    max_exposure_usdc: int = 100_000
    max_account_exposure_usdc: int = 10_000
    max_stake_usdc: int = 1000
    survival_bps: int = 4800
    correlation_bps: int = 8000
    behavior: str = 'mixed'
    allocation_bps: int = 3500
    lp_budget_tokens: int = 50_000_000
    bootstrap_days: int = 90
    lp_half_life_days: int = 30
    vest_days: int = 30
    exit_delay_days: int = 2
    whitelist_day: int = 14
    public_day: int = 45
    max_tvl_usdc: int = 20_000_000
    dynamic_cap: bool = True
    target_utilization_bps: int = 2000
    response_bps: int = 5000
    incentive_response_bps: int = 1000
    penalty_bps: int = 1000
    transfer_day: int = 7
    daily_log: bool = False
    risk_policy: RiskPolicy = field(default_factory=RiskPolicy)
    winner_cluster_days: tuple = ()
    demand_stops_day: int = None

    def __post_init__(self):
        if not (self.days > 0 and self.initial_lp_usdc > 0 and self.lp_agents > 0
                and self.wallet_usdc >= 0 and self.games_per_day >= 0
                and self.traders > 0 and self.trader_wallet_usdc >= 0
                and self.daily_trader_inflow_usdc >= 0
                and 0 < self.batches_per_day <= DAY // 240 and self.bootstrap_days > 0
                and self.max_exposure_usdc > 0 and self.max_account_exposure_usdc > 0
                and self.max_stake_usdc > 0
                and self.lp_half_life_days > 0 and self.vest_days >= 0
                and self.exit_delay_days >= 2 and self.max_tvl_usdc > 0):
            raise ValueError('invalid horizon, capital, population or timing')
        if not (0 <= self.lp_budget_tokens <= TREASURY // TOKEN
                and 0 <= self.allocation_bps <= 3500
                and 0 < self.target_utilization_bps <= 10000
                and 0 <= self.whitelist_day <= self.public_day
                and all(0 <= value <= 10000 for value in (
                    self.survival_bps, self.correlation_bps, self.response_bps,
                    self.incentive_response_bps, self.penalty_bps))):
            raise ValueError('invalid research policy')
        if any(not isinstance(day, int) or day < 0 for day in self.winner_cluster_days):
            raise ValueError('invalid winner cluster days')
        if self.demand_stops_day is not None and (not isinstance(self.demand_stops_day, int) or self.demand_stops_day < 0):
            raise ValueError('invalid demand stop day')


class Vault:
    """Settled NAV; pending shares remain invested until fulfilled at current NAV.

    Entry/fulfillment requires zero open exposure and a fresh reconciliation.
    This is a conservative research rule, not an ERC-7540 implementation.
    """
    def __init__(self, initial, exit_delay=2):
        self.assets = initial
        self.shares = {'protocol': initial * SHARE // USDC}
        self.supply = self.shares['protocol']
        self.hwm = self.nav()
        self.pending = []
        self.exit_delay = exit_delay
        self.exposure = 0
        self.fresh = True
        self.required = 100 * USDC
        self.net_contributions = initial
        self.trading_pnl = 0
        self.reserve_funded = 0
        self.total_deposited = 0
        self.total_withdrawn = 0
        self.fulfilled = []
        self.delayed_days = 0

    def nav(self):
        return Fraction(self.assets, self.supply) if self.supply else Fraction(USDC, SHARE)

    def queued(self, owner):
        return sum(q['shares'] for q in self.pending if q['owner'] == owner)

    def deposit(self, owner, amount, cap):
        if not self.fresh or self.exposure or self.assets <= 0 or amount <= 0:
            return 0
        amount = min(amount, max(0, cap - self.assets))
        minted = amount * self.supply // self.assets if self.supply else amount * SHARE // USDC
        if minted == 0:
            return 0
        # HWM is in assets/share: adding or removing fair-NAV capital is not PnL.
        self.assets += amount
        self.supply += minted
        self.shares[owner] = self.shares.get(owner, 0) + minted
        self.net_contributions += amount
        self.total_deposited += amount
        return amount

    def request(self, owner, shares, day):
        shares = min(shares, self.shares.get(owner, 0) - self.queued(owner))
        if shares <= 0:
            return False
        self.pending.append({'owner': owner, 'shares': shares, 'day': day})
        return True

    def fulfill(self, day):
        paid = defaultdict(int)
        # Strict FIFO, no early pricing or fixed USDC entitlement at request.
        while self.pending and day >= self.pending[0]['day'] + self.exit_delay:
            request = self.pending[0]
            amount = request['shares'] * self.assets // self.supply
            if (not self.fresh or self.exposure
                    or self.assets - amount < 2 * self.required):
                self.delayed_days += 1
                break
            self.pending.pop(0)
            self.assets -= amount
            self.supply -= request['shares']
            self.shares[request['owner']] -= request['shares']
            self.net_contributions -= amount
            self.total_withdrawn += amount
            paid[request['owner']] += amount
            self.fulfilled.append({**request, 'fulfilled_day': day, 'assets': amount})
        return paid

    def settle(self, pnl):
        if self.assets + pnl < 0:
            raise ValueError('unfunded payout')
        self.assets += pnl
        self.trading_pnl += pnl

    def waterfall(self, cap_bps):
        if not self.fresh or self.exposure:
            return 0
        eligible = max(0, self.assets - ceil_fraction(self.hwm * self.supply))
        capital = self.required
        alpha = cap_bps
        if capital and self.assets < 3 * capital:
            alpha = max(0, (2 * cap_bps * (self.assets - capital) // capital - cap_bps) // 3)
        amount = min(eligible * alpha // 10000, max(0, self.assets - 2 * capital))
        self.assets -= amount
        self.reserve_funded += amount
        # Protected profits retained to restore capital become LP equity. They
        # cannot be charged retroactively after capitalization improves.
        self.hwm = max(self.hwm, self.nav())
        return amount

    def check(self):
        assert self.assets == self.net_contributions + self.trading_pnl - self.reserve_funded
        assert self.supply == sum(self.shares.values()) and self.assets >= 0
        assert all(0 <= self.queued(owner) <= value for owner, value in self.shares.items())
        assert 0 <= self.exposure <= self.assets


class Rewards:
    def __init__(self, scenario):
        self.s = scenario
        self.budget = scenario.lp_budget_tokens * TOKEN
        weights = [Fraction(str(2 ** (-d / scenario.lp_half_life_days)))
                   for d in range(scenario.bootstrap_days)]
        total = sum(weights)
        self.schedule = [int(w / total * self.budget) for w in weights]
        assert sum(self.schedule) <= self.budget
        self.earned = 0
        self.vesting = []
        self.liquid = defaultdict(int)
        self.claimed = 0
        self.expired = 0

    def accrue(self, day, scores, total_capital_time, exposure_time):
        if day >= self.s.bootstrap_days:
            return 0
        scheduled = self.schedule[day]
        # Utilization counts exact admitted worst-case incremental liabilities
        # times their actual at-risk duration, not deposits or rejected demand.
        budget = min(scheduled, scheduled * exposure_time * 10000
                     // max(1, total_capital_time * self.s.target_utilization_bps))
        total = sum(scores.values())
        distributed = 0
        if total and total_capital_time:
            # Protocol capital participates in the denominator but does not mine.
            # Pending-exit shares do not mine; their capital remains at risk.
            for owner, value in scores.items():
                amount = budget * value // total_capital_time
                if amount:
                    self.vesting.append((day + self.s.vest_days, owner, amount))
                    distributed += amount
        self.earned += distributed
        self.expired += scheduled - distributed
        assert self.earned <= self.budget
        return distributed

    def vest(self, day):
        waiting = []
        for maturity, owner, amount in self.vesting:
            if maturity <= day:
                self.liquid[owner] += amount
                self.claimed += amount
            else:
                waiting.append((maturity, owner, amount))
        self.vesting = waiting

    def check(self):
        assert self.earned == self.claimed + sum(row[2] for row in self.vesting)
        assert 0 <= self.earned <= self.budget


def run(s, keep_events=False):
    rng = random.Random(s.seed)
    vault = Vault(s.initial_lp_usdc * USDC, s.exit_delay_days)
    guard = RiskGuard(s.risk_policy, vault.assets, vault.supply)
    rewards = Rewards(s)
    cash = {f'lp-{i:03d}': s.wallet_usdc * USDC for i in range(s.lp_agents)}
    initial_wealth = vault.assets + sum(cash.values())
    trader_cash = [s.trader_wallet_usdc * USDC for _ in range(s.traders)]
    initial_wealth += sum(trader_cash)
    trader_inflows = unfunded_games = busy_games = 0
    traders = {k: 0 for k in ('organic', 'early-miners', 'late-miners')}
    trader_tokens = defaultdict(int)
    token_redemptions = defaultdict(int)
    contributed = defaultdict(int)
    withdrawn = defaultdict(int)
    trader_emitted = burned = reserve = 0
    trader_budgets = emission_budgets(180, 20)
    outcomes = Counter()
    rejected = offered = accepted = 0
    nav_history = [float(vault.nav())]
    peak_nav = vault.nav()
    max_drawdown = 0.0
    min_assets = max_assets = vault.assets
    requested_history, accepted_history = [], []
    daily, events = [], []
    exposure_sum = capital_time_sum = 0
    peak_exposure = 0
    peak_pending_requests = peak_queued_assets = 0
    observed_utilization = 0.0
    risk_rejects, risk_days = Counter(), Counter()
    bootstrap_owners, retention = None, {}
    recovery_episodes = []

    def log(day, kind, **data):
        if keep_events:
            events.append({'day': day, 'kind': kind, **data})

    def sample_equity(at=None):
        nonlocal min_assets, max_assets, peak_nav, max_drawdown
        min_assets = min(min_assets, vault.assets)
        max_assets = max(max_assets, vault.assets)
        peak_nav = max(peak_nav, vault.nav())
        drawdown = 1 - float(vault.nav() / peak_nav)
        max_drawdown = max(max_drawdown, drawdown)
        if at is not None:
            for episode in recovery_episodes:
                if episode['nav_recovered_at_seconds'] is not None:
                    continue
                target = Fraction(int(episode['peak_nav_numerator']), int(episode['peak_nav_denominator']))
                if vault.nav() < target and episode['first_deficit_at_seconds'] is None:
                    episode['first_deficit_at_seconds'] = at
                elif vault.nav() >= target and episode['first_deficit_at_seconds'] is not None:
                    episode['nav_recovered_at_seconds'] = at

    for day in range(s.days):
        phase = 'protocol' if day < s.whitelist_day else 'whitelisted' if day < s.public_day else 'public'
        vault.fresh = not (s.behavior == 'oracle-outage' and 30 <= day < 35)
        inflow = s.daily_trader_inflow_usdc * USDC
        if s.behavior in ('demand-collapse', 'farming-collapse', 'no-organic-demand') and day >= s.bootstrap_days:
            inflow = 0
        if s.demand_stops_day is not None and day >= s.demand_stops_day:
            inflow = 0
        for i in range(s.traders):
            trader_cash[i] += inflow // s.traders + int(i < inflow % s.traders)
        trader_inflows += inflow
        vault.required = max([100 * USDC] + accepted_history[-7:])
        rewards.vest(day)
        for owner, amount in vault.fulfill(day).items():
            cash[owner] += amount
            withdrawn[owner] += amount
            log(day, 'lp_withdrawal_paid', owner=owner, usdc_units=amount)

        demand = max(requested_history[-7:], default=0)
        deposit_cap = s.max_tvl_usdc * USDC
        if s.dynamic_cap:
            deposit_cap = min(deposit_cap, max(100 * USDC, demand * 10000 // s.target_utilization_bps))
        recent_return = nav_history[-1] / nav_history[max(0, len(nav_history) - 8)] - 1
        current_drawdown = 1 - float(vault.nav() / peak_nav)
        for i, owner in enumerate(cash):
            shares = vault.shares.get(owner, 0)
            risk_aversion = .5 + (i % 10) / 5
            hurdle = (i % 7) / 10000
            loss_signal = (recent_return < -.002 * risk_aversion
                           or current_drawdown > .03 * risk_aversion
                           or (day > s.public_day and observed_utilization < .01)
                           or (s.behavior == 'bank-run' and day >= 31))
            if shares and not vault.queued(owner) and loss_signal and rng.randrange(10000) < s.response_bps:
                available = shares - vault.queued(owner)
                if vault.request(owner, max(1, available // 2), day):
                    log(day, 'lp_withdrawal_requested', owner=owner, pending_shares=str(vault.queued(owner)))
            allowed = phase == 'public' or (phase == 'whitelisted' and i < max(1, s.lp_agents // 5))
            attractive = recent_return > hurdle + risk_aversion * current_drawdown
            incentive_interest = (day < s.bootstrap_days and s.lp_budget_tokens > 0
                                  and rng.randrange(10000) < s.incentive_response_bps)
            if (allowed and not loss_signal and not vault.queued(owner)
                    and observed_utilization > .01 and (attractive or incentive_interest)
                    and rng.randrange(10000) < s.response_bps):
                amount = vault.deposit(owner, cash[owner] // (2 + i % 4), deposit_cap)
                if amount:
                    cash[owner] -= amount
                    contributed[owner] += amount
                    log(day, 'lp_deposit', owner=owner, usdc_units=amount, cap_usdc_units=deposit_cap)
        peak_pending_requests = max(peak_pending_requests, len(vault.pending))
        peak_queued_assets = max(peak_queued_assets, sum(q['shares'] for q in vault.pending) * vault.assets // vault.supply)
        if s.risk_policy.enabled:
            guard.observe(day * DAY, vault.assets, vault.supply)
        if day in s.winner_cluster_days and day - 1 not in s.winner_cluster_days:
            target = max(peak_nav, vault.nav())
            recovery_episodes.append({'cluster_start_day': day,
                                      'peak_nav_numerator': str(target.numerator),
                                      'peak_nav_denominator': str(target.denominator),
                                      'first_deficit_at_seconds': None,
                                      'nav_recovered_at_seconds': None})
            sample_equity(day * DAY)

        games = 0 if s.behavior == 'no-demand' else s.games_per_day
        if s.demand_stops_day is not None and day >= s.demand_stops_day:
            games = 0
        if s.behavior == 'demand-collapse' and day >= 90:
            games //= 20
        if s.behavior == 'farming-collapse' and day >= s.bootstrap_days:
            games //= 4
        if s.behavior == 'no-organic-demand':
            games = games // 3 if day < s.bootstrap_days else 0
        scores = defaultdict(int)
        trader_scores = defaultdict(int)
        daily_exposure_time = day_peak = day_requested_peak = daily_capital_time = 0
        used_seconds = 0
        for batch in range(s.batches_per_day):
            count = games // s.batches_per_day + int(batch < games % s.batches_per_day)
            positions = []
            batch_owners = set()
            for i in range(count):
                owner = (day * games + batch * (games // s.batches_per_day) + min(batch, games % s.batches_per_day) + i) % s.traders
                if owner in batch_owners:
                    busy_games += 1
                    continue
                stake = min(trader_cash[owner], s.max_stake_usdc * USDC,
                            (100 + (i * 137 + batch * 83) % 1400) * USDC)
                if stake < USDC:
                    unfunded_games += 1
                    continue
                trader_cash[owner] -= stake
                batch_owners.add(owner)
                cohort = ('early-miners' if day < 30 else 'late-miners') if i % 5 < 2 else 'organic'
                positions.append({'owner': owner, 'game': i, 'stake': stake, 'initial': stake,
                                  'target': (1, 2, 3, 4, 8)[i % 5], 'cohort': cohort})
            for stage in range(1, 9):
                if not positions:
                    break
                admitted = []
                reserve_risk = 0
                wanted = sum(pos['initial'] * PAYOUT[stage] // 10**9 - pos['stake'] for pos in positions)
                day_requested_peak = max(day_requested_peak, min(wanted, s.max_exposure_usdc * USDC))
                offered += len(positions)
                at = day * DAY + batch * DAY // s.batches_per_day + (stage - 1) * 30
                risk_capacity, risk_reason = (guard.capacity(at, vault.assets, vault.supply, vault.fresh)
                                              if s.risk_policy.enabled else (vault.assets, 'current'))
                for pos in positions:
                    payout = pos['initial'] * PAYOUT[stage] // 10**9
                    risk = payout - pos['stake']
                    if (not vault.fresh or reserve_risk + risk + 100 * USDC > vault.assets
                            or reserve_risk + risk > s.max_exposure_usdc * USDC
                            or risk > s.max_account_exposure_usdc * USDC):
                        rejected += 1
                        trader_cash[pos['owner']] += pos['stake']
                        continue
                    if reserve_risk + risk > risk_capacity:
                        rejected += 1
                        risk_rejects[risk_reason] += 1
                        trader_cash[pos['owner']] += pos['stake']
                        continue
                    reserve_risk += risk
                    admitted.append((pos, payout))
                vault.exposure = reserve_risk
                vault.required = max(vault.required, reserve_risk + 100 * USDC)
                vault.check()
                if s.risk_policy.enabled:
                    guard.reserve(at, vault.assets, vault.supply, reserve_risk, vault.fresh)
                day_peak = max(day_peak, reserve_risk)
                peak_exposure = max(peak_exposure, reserve_risk)
                common = int.from_bytes(hashlib.sha256(
                    f'{s.seed}/{day}/{batch}/{stage}/common'.encode()).digest()[:8], 'big') % 10000
                survivors = []
                batch_pnl = exposure_time = gross_debit = 0
                for pos, payout in admitted:
                    accepted += 1
                    if s.behavior == 'oracle-gap' and day in (7, 30, 90):
                        outcomes['voided'] += 1
                        trader_cash[pos['owner']] += pos['stake']
                        continue
                    # Market draws do not consume the LP behavioral RNG. This
                    # keeps an unchanged trade's latent path fixed when testing
                    # incentive budgets, agent decisions or capacity settings.
                    draw = hashlib.sha256(
                        f"{s.seed}/{day}/{batch}/{stage}/{pos['owner']}/{pos['game']}".encode()).digest()
                    selector = int.from_bytes(draw[:8], 'big') % 10000
                    private = int.from_bytes(draw[8:16], 'big') % 10000
                    u = common if selector < s.correlation_bps else private
                    probability = s.survival_bps
                    if s.behavior == 'stage-conditioned':
                        probability = (4300, 2000, 6500, 4800, 4800, 4800, 4800, 4800)[stage - 1]
                    won = u < probability
                    if s.behavior in ('correlated-winners', 'bank-run') and day == 30:
                        won = True
                    if day in s.winner_cluster_days:
                        won = True
                    if s.behavior == 'deliberate-loss-farming' and pos['cohort'] != 'organic':
                        won = False
                    duration = 30000 if won else (1 if s.behavior == 'deliberate-loss-farming'
                                                  else 1 + int.from_bytes(draw[16:24], 'big') % 29999)
                    exposure_time += (payout - pos['stake']) * duration
                    trader_scores[pos['cohort']] += pos['stake'] * duration * (10000 if won else 2000)
                    delta = -(payout - pos['stake']) if won else pos['stake']
                    batch_pnl += delta
                    traders[pos['cohort']] -= delta
                    outcomes['survived' if won else 'breached'] += 1
                    if won:
                        gross_debit += payout - pos['stake']
                        pos['stake'] = payout
                        if stage < pos['target']:
                            survivors.append(pos)
                        else:
                            trader_cash[pos['owner']] += payout
                # All admission was against aggregate worst-case liability. No
                # investor may exit between acceptance and confirmed settlement.
                assets_before = vault.assets
                for owner, shares in vault.shares.items():
                    if owner != 'protocol':
                        active = shares - vault.queued(owner)
                        scores[owner] += active * assets_before * 30000 // vault.supply
                daily_capital_time += assets_before * 30000
                used_seconds += 30
                daily_exposure_time += exposure_time
                vault.settle(batch_pnl)
                vault.exposure = 0
                # Crystallize at each settled batch, not once after all daily
                # returns: a later drawdown must retain the prior high-water mark.
                amount = vault.waterfall(s.allocation_bps)
                reserve += amount
                if s.risk_policy.enabled:
                    guard.settle(at + 30, gross_debit, vault.assets, vault.supply)
                sample_equity(at + 30)
                log(day, 'settled_batch', batch=batch, stage=stage, positions=len(admitted),
                    pnl_usdc_units=batch_pnl, exposure_usdc_units=reserve_risk,
                    lp_usdc_units=vault.assets, reserve_funding_usdc_units=amount,
                    gross_lp_debit_usdc_units=gross_debit, at_seconds=at + 30,
                    risk_capacity_usdc_units=risk_capacity, risk_limit=risk_reason,
                    risk_mode=guard.mode, probe_budget_bps=guard.probe_budget_bps)
                positions = survivors

        if s.behavior in ('drawdown', 'bank-run') and day == 30:
            loss = vault.assets // 5
            vault.settle(-loss)
            traders['organic'] += loss
            trader_cash[0] += loss
            sample_equity((day + 1) * DAY - 1)
            log(day, 'drawdown_stress', loss_usdc_units=loss)
        idle_ms = (DAY - used_seconds) * 1000
        if idle_ms < 0:
            raise ValueError('too many sequential stages for a simulated day')
        daily_capital_time += vault.assets * idle_ms
        for owner, shares in vault.shares.items():
            if owner != 'protocol':
                scores[owner] += (shares - vault.queued(owner)) * vault.assets * idle_ms // vault.supply
        earned = rewards.accrue(day, scores, daily_capital_time, daily_exposure_time)
        rewards.vest(day)  # Supports a zero-vesting stress policy.
        if earned:
            log(day, 'lp_rewards_earned', fuse_units=str(earned), vest_day=day + s.vest_days)
        total_score = sum(trader_scores.values())
        activity_cap = total_score * 100 * TOKEN // (USDC * 30000 * 10000)
        scheduled_trader = trader_budgets[day] if day < len(trader_budgets) else 0
        trader_budget = min(scheduled_trader, activity_cap, MINING - trader_emitted)
        if total_score:
            for owner, value in trader_scores.items():
                tokens = trader_budget * value // total_score
                trader_tokens[owner] += tokens
                trader_emitted += tokens

        # No external token bid or imagined price. Redemption is the only FUSE
        # cash flow and uses one common epoch snapshot including locked supply.
        if day >= s.transfer_day and reserve:
            supply, backing = GENESIS - burned, reserve
            for book in (trader_tokens, rewards.liquid):
                for owner in list(book):
                    tokens = book[owner] // 5
                    paid = tokens * backing * (10000 - s.penalty_bps) // (supply * 10000)
                    if tokens and paid:
                        book[owner] -= tokens
                        burned += tokens
                        reserve -= paid
                        token_redemptions[owner] += paid
        requested_history.append(day_requested_peak)
        accepted_history.append(day_peak + 100 * USDC)
        observed_utilization = day_peak / max(1, vault.assets)
        nav_history.append(float(vault.nav()))
        sample_equity((day + 1) * DAY)
        exposure_sum += daily_exposure_time
        capital_time_sum += daily_capital_time
        rewards.check()
        vault.check()
        assert min(trader_cash) >= 0 and min(cash.values()) >= 0
        assert sum(trader_cash) == s.traders * s.trader_wallet_usdc * USDC + trader_inflows + sum(traders.values())
        assert (vault.assets + reserve + sum(cash.values()) + sum(trader_cash)
                + sum(token_redemptions.values()) == initial_wealth + trader_inflows)
        token_total = (TREASURY - rewards.budget + rewards.budget - rewards.earned
                       + sum(row[2] for row in rewards.vesting) + sum(rewards.liquid.values())
                       + MINING - trader_emitted + sum(trader_tokens.values()))
        assert token_total == GENESIS - burned
        record = {'day': day, 'phase': phase, 'lp_usdc_units': vault.assets,
                  'share_nav_usdc': float(vault.nav() * SHARE / USDC),
                  'hwm_usdc_per_share': float(vault.hwm * SHARE / USDC),
                  'reserve_usdc_units': reserve, 'lp_earned_fuse_units': str(rewards.earned),
                  'lp_reward_today_fuse_units': str(earned), 'lp_vested_fuse_units': str(rewards.claimed),
                  'pending_exit_shares': str(sum(q['shares'] for q in vault.pending)),
                  'peak_utilization': observed_utilization,
                  'time_weighted_utilization': daily_exposure_time / max(1, daily_capital_time),
                  'deposit_cap_usdc_units': deposit_cap, 'fresh_reconciliation': vault.fresh}
        record['required_capital_usdc_units'] = vault.required
        record['share_supply_units'] = str(vault.supply)
        record['reserve_funded_cumulative_usdc_units'] = vault.reserve_funded
        record['trader_wallets_usdc_units'] = sum(trader_cash)
        record['unfunded_games'] = unfunded_games
        if s.risk_policy.enabled:
            guard.observe((day + 1) * DAY, vault.assets, vault.supply)
        risk_days[guard.mode] += 1
        invested = {owner: vault.shares.get(owner, 0) * vault.assets // vault.supply for owner in cash}
        if day == s.bootstrap_days - 1:
            bootstrap_owners = {owner for owner, value in invested.items() if value >= USDC}
        if bootstrap_owners is not None and day in (s.bootstrap_days - 1, s.bootstrap_days + 29, s.bootstrap_days + 89):
            retention[str(day)] = {
                'bootstrap_owners': len(bootstrap_owners),
                'still_invested_owners': sum(invested[owner] >= USDC for owner in bootstrap_owners),
                'unrequested_owners': sum(invested[owner] >= USDC and not vault.queued(owner) for owner in bootstrap_owners),
                'remaining_equity_usdc_units': sum(invested[owner] for owner in bootstrap_owners)}
        record['external_invested_owners'] = sum(value >= USDC for value in invested.values())
        record['risk_mode'] = guard.mode
        record['risk_rejections_cumulative'] = sum(risk_rejects.values())
        if s.daily_log:
            daily.append(record)
        log(day, 'daily_accounting_verified', **{k: v for k, v in record.items() if k != 'day'})

    external_equity = sum(value for owner, value in vault.shares.items() if owner != 'protocol') * vault.assets // vault.supply
    external_pnl = {owner: cash[owner] + vault.shares.get(owner, 0) * vault.assets // vault.supply
                    - s.wallet_usdc * USDC for owner in cash}
    return {'scenario': asdict(s), 'research_only': True, 'contract_execution': False,
            'empirical_lp_demand_calibrated': False, 'conservation_verified': True,
            'lp_final_usdc_units': vault.assets, 'lp_min_usdc_units': min_assets,
            'lp_max_usdc_units': max_assets, 'share_nav_usdc': float(vault.nav() * SHARE / USDC),
            'share_return': float(vault.nav() * SHARE / USDC) - 1,
            'max_share_drawdown': max_drawdown, 'external_deposits_usdc_units': vault.total_deposited,
            'external_withdrawals_usdc_units': vault.total_withdrawn,
            'external_final_equity_usdc_units': external_equity,
            'external_underwriting_pnl_usdc_units': sum(external_pnl.values()),
            'external_underwriting_pnl_by_owner': external_pnl,
            'external_redemption_cash_usdc_units': sum(value for owner, value in token_redemptions.items() if owner in cash),
            'participating_external_lps': len(contributed),
            'pending_requests': len(vault.pending), 'pending_exit_shares': str(sum(q['shares'] for q in vault.pending)),
            'pending_lp_owners': len({q['owner'] for q in vault.pending}),
            'peak_pending_requests': peak_pending_requests,
            'peak_queued_assets_usdc_units': peak_queued_assets,
            'oldest_pending_wait_days': max((s.days - 1 - q['day'] for q in vault.pending), default=0),
            'pending_exit_current_nav_usdc_units': sum(q['shares'] for q in vault.pending) * vault.assets // vault.supply,
            'withdrawal_queue_delayed_days': vault.delayed_days,
            'fulfilled_withdrawals': len(vault.fulfilled),
            'longest_fulfilled_wait_days': max((q['fulfilled_day'] - q['day'] for q in vault.fulfilled), default=0),
            'lp_bootstrap_earned_fuse_units': str(rewards.earned),
            'lp_bootstrap_vested_fuse_units': str(rewards.claimed),
            'lp_unvested_fuse_units': str(sum(q[2] for q in rewards.vesting)),
            'lp_unearned_budget_fuse_units': str(rewards.budget - rewards.earned),
            'lp_expired_scheduled_fuse_units': str(rewards.expired),
            'trader_emitted_fuse_units': str(trader_emitted), 'burned_fuse_units': str(burned),
            'outstanding_supply_fuse_units': str(GENESIS - burned),
            'locked_treasury_fuse_units': str(TREASURY - rewards.budget),
            'reserve_usdc_units': reserve, 'reserve_funded_usdc_units': vault.reserve_funded,
            'lp_realized_trading_pnl_usdc_units': vault.trading_pnl,
            'time_weighted_utilization': exposure_sum / max(1, capital_time_sum),
            'peak_accepted_exposure_usdc_units': peak_exposure,
            'offered_stages': offered, 'accepted_stages': accepted, 'rejected_stages': rejected,
            'unfunded_games': unfunded_games, 'trader_inflows_usdc_units': trader_inflows,
            'busy_wallet_games': busy_games,
            'trader_final_cash_usdc_units': sum(trader_cash),
            'trader_cash_pnl_usdc_units': dict(traders),
            'risk_controls': {**guard.summary(), 'enabled': s.risk_policy.enabled,
                              'rejected_stages_by_limit': dict(risk_rejects),
                              'days_by_mode': dict(risk_days), 'transitions': guard.transitions},
            'post_bootstrap_retention': retention,
            'nav_recovery_episodes': recovery_episodes,
            'overdue_pending_requests': sum(s.days - 1 - q['day'] > s.exit_delay_days + 7 for q in vault.pending),
            'withdrawals_requested_after_bootstrap': sum(q['day'] >= s.bootstrap_days for q in vault.pending + vault.fulfilled),
            'outcomes': dict(outcomes), 'daily': daily, 'events': events}


def scenario_grid(seed):
    base = Scenario(seed=seed)
    # Funded continuing demand is an explicit sensitivity, never a free source
    # of losses for LPs. Without inflows, the finite trader wallets may run dry.
    active = replace(base, initial_lp_usdc=250_000, games_per_day=3000, batches_per_day=12,
                     daily_trader_inflow_usdc=150_000, correlation_bps=0,
                     whitelist_day=1, public_day=7)
    cases = [base, replace(base, name='proposal-5m-seed', initial_lp_usdc=5_000_000),
             replace(active, name='continuing-funded-demand')]
    for behavior in ('no-demand', 'no-organic-demand', 'correlated-winners', 'drawdown',
                     'bank-run', 'oracle-gap', 'oracle-outage', 'demand-collapse',
                     'farming-collapse', 'deliberate-loss-farming', 'stage-conditioned'):
        cases.append(replace(active if behavior in ('bank-run', 'correlated-winners', 'oracle-outage', 'demand-collapse', 'farming-collapse') else base,
                             name=behavior, behavior=behavior))
    dimensions = {
        'initial_lp_usdc': [250_000, 5_000_000, 20_000_000],
        'survival_bps': [4000, 4400, 4800, 5000, 5400],
        'allocation_bps': [0, 1000, 3500], 'bootstrap_days': [60, 90],
        'lp_budget_tokens': [0, 10_000_000, 50_000_000],
        'lp_half_life_days': [15, 30, 45], 'vest_days': [0, 30, 60],
        'exit_delay_days': [2, 4, 7], 'dynamic_cap': [True, False],
        'target_utilization_bps': [1000, 2000, 4000],
        'response_bps': [0, 2500, 5000, 10000],
        'incentive_response_bps': [0, 1000, 5000],
        'games_per_day': [0, 300, 3000], 'correlation_bps': [0, 8000, 10000],
        'daily_trader_inflow_usdc': [0, 10_000, 150_000],
        'max_exposure_usdc': [100_000, 250_000, 1_000_000],
    }
    for field, values in dimensions.items():
        for value in values:
            if value != getattr(base, field):
                cases.append(replace(base, name=f'{field}-{value}', **{field: value}))
    rng = random.Random(seed)
    for i in range(24):
        cases.append(replace(base, name=f'joint-{i:02d}', **{key: rng.choice(values) for key, values in dimensions.items()}))
    for offset in range(1, 5):
        for template in (base, active, replace(active, behavior='bank-run'), replace(active, behavior='demand-collapse')):
            cases.append(replace(template, name=f'seed-{offset}-{template.behavior}-{template.games_per_day}',
                                 seed=seed + offset))
    return cases, dimensions


def retained_run_illustrations():
    """Replay observed LP postings into a hypothetical ownership/fee ledger.

    No new demand, external LPs, changed trades, or contract execution is inferred.
    Reserve deductions from the original run are removed before repricing fees.
    """
    results = []
    for directory in sorted((ROOT / '.local/live-runs').glob('*/evidence')):
        summary_path = directory / 'summary.json'
        if not summary_path.exists():
            continue
        summary = json.loads(summary_path.read_text())
        if not summary.get('passed'):
            continue
        vault = Vault(summary['initial_lp_usdc_units'])
        account_debt, stage_risk = {}, {}
        pnl = 0
        for line in (directory / 'journal.jsonl').open():
            event = json.loads(line)
            # Decode canonical event fields, independently of deposits and
            # reserve outflows. The normalized effect does not carry amounts.
            change = 0
            for evidence in event['command'].get('raw', {}).get('evidence', []):
                if evidence.get('Module') == 'LPVault':
                    if evidence.get('Event') == 'NetTraderLossesReceived':
                        change += evidence['Fields']['amount']
                    elif evidence.get('Event') == 'NetTraderWinsFunded':
                        change -= evidence['Fields']['amount']
            for owner, notice in event.get('notices', {}).items():
                balances = notice['account']['balances']
                account_debt[owner] = sum(balances.get(k, 0) for k in ('unfunded', 'earned_unfunded', 'withdrawal_unfunded'))
                for stage in notice['stages']:
                    stage_risk[stage['id']] = stage['terms']['payout'] - stage['funded'] if stage['status'] in ('active', 'pending') else 0
            if change:
                vault.settle(change)
                pnl += change
            vault.required = sum(account_debt.values()) + sum(stage_risk.values()) + 100 * USDC
            # Hypothetical fee calculation only at recorded reconciliation points.
            if change:
                vault.waterfall(3500)
        if pnl != summary['lp_realized_pnl_usdc_units']:
            raise ValueError(f'retained trading PnL does not reconcile: {directory}')
        results.append({'run': directory.parent.name,
                        'journal_sha256': hashlib.sha256((directory / 'journal.jsonl').read_bytes()).hexdigest(),
                        'observed_trading_pnl_usdc_units': pnl,
                        'observed_lp_final_usdc_units': summary['final_lp_usdc_units'],
                        'hypothetical_lp_final_usdc_units': vault.assets,
                        'hypothetical_reserve_funding_usdc_units': vault.reserve_funded,
                        'scope': 'Counterfactual settlement-level fee ledger; no external LPs or changed trade admissions; not an E2E result.'})
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / '.local/lp-incentives-research')
    parser.add_argument('--seed', type=int, default=20261026)
    parser.add_argument('--days', type=int, default=180)
    parser.add_argument('--quick', action='store_true', help='baseline and principal stresses only')
    parser.add_argument('--skip-retained-runs', action='store_true')
    args = parser.parse_args()
    cases, dimensions = scenario_grid(args.seed)
    if args.quick:
        cases = cases[:14]
    args.output.mkdir(parents=True, exist_ok=True)
    source_files = ['scripts/simulate_lp_incentives.py', 'scripts/simulate_tokenomics.py', 'scripts/lp_risk.py',
                    'docs/LP_INCENTIVES_PROPOSAL.txt']
    experiment = {'seed': args.seed, 'scenarios': [asdict(replace(case, days=args.days)) for case in cases],
                  'source_sha256': {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
                                    for name in source_files},
                  'scope': 'Synthetic, finite-wallet research scenarios. No public or local contract transactions.'}
    (args.output / 'experiment.json').write_text(json.dumps(experiment, indent=2) + '\n')
    results = []
    for i, case in enumerate(cases):
        logged = case.name in ('baseline-250k', 'continuing-funded-demand', 'bank-run',
                               'oracle-outage', 'demand-collapse', 'farming-collapse')
        result = run(replace(case, days=args.days, daily_log=True), keep_events=logged)
        if logged:
            filename = 'baseline-events.jsonl' if i == 0 else f'{case.name}-events.jsonl'
            with (args.output / filename).open('w') as stream:
                for event in result['events']:
                    stream.write(json.dumps(event) + '\n')
        result.pop('events')
        results.append(result)
        if (i + 1) % 10 == 0:
            print(f'Simulated {i + 1}/{len(cases)} LP scenarios', flush=True)
    retained = [] if args.skip_retained_runs else retained_run_illustrations()
    report = {'research_only': True, 'production_approved': False,
              'contract_shares_or_lp_rewards_implemented': False,
              'method': 'Baseline + named stresses + one-factor sweeps + 24 seeded joint combinations + 16 additional seed trajectories; not exhaustive optimization.',
              'dimensions': dimensions, 'allocation': {'genesis_fuse': 1_000_000_000,
                  'trader_mining_fuse': 600_000_000, 'lp_bootstrap_fuse_baseline': 50_000_000,
                  'remaining_locked_treasury_fuse_baseline': 350_000_000},
              'assumptions': {
                  'agents': '100 synthetic external LPs with $50k each; 300 finite trader wallets with $1000 each; 300 attempted games/day baseline, six batches, varied stakes capped by available cash and $1000, targets 1/2/3/4/8. Unfunded attempts do not trade.',
                  'risk_caps': 'Baseline matches local policy limits: $100k aggregate incremental exposure, $10k per active account, $100 LP buffer. The model executes sequential batches, with at most one active stage per trader. Risk-cap sweeps are explicit research alternatives.',
                  'trader_inflows': 'Zero in baseline. Continuing-funded-demand sensitivity adds an explicitly external $150k/day to trader wallets, not LP profits, and attempts 3000 games/day in 12 batches. Demand/farming-collapse cases stop this inflow after bootstrap. No infinite unfunded trader losses; repeated willingness to play remains a synthetic assumption.',
                  'capital_response': 'Unmeasured weekly NAV-return, drawdown, utilization and subjective bootstrap-interest rules. FUSE has no assumed USD price.',
                  'launch': 'Protocol only days 0-13; first 20% of agents eligible days 14-44; all agents eligible from day 45. Research phase labels only.',
                  'capacity': 'Deposits capped by trailing seven-day requested peak liabilities / target peak utilization and $20M ceiling. Existing excess capital is not forcibly removed.',
                  'nav': 'Integer settled equity/share; no deposit or withdrawal fulfillment with open exposure or stale reconciliation. Pending shares remain exposed until fulfillment.',
                  'waterfall': 'Per-share HWM carries through capital flows; crystallized each settled batch. At most 35%, existing capitalization ramp and 2x required-capital floor. Protected retained profits cannot later be charged retroactively.',
                  'withdrawals': '48h minimum request delay, current NAV on fulfillment, strict FIFO, 2x trailing accepted capital floor. No promise of payment in 48h; head-of-line blocking is measured.',
                  'lp_rewards': '90-day decaying finite schedule; time-weighted net capital multiplied by actual admitted liability-time utilization / 20% target. Protocol and pending-exit capital receive none; missed slots expire; 30-day vesting.',
                  'token_cash': 'Only actual simulated reserve redemptions after vesting/activation create USDC proceeds. Locked and unvested FUSE remain in the backing denominator. No secondary bids or guaranteed APY.',
                  'costs': 'No operating costs, smart-contract exploit losses or external liquidity market; drawdown shock is explicit. Therefore simulated returns are before unspecified costs.',
                  'market': 'Seeded correlated Bernoulli outcomes; no calibrated oracle forecasting or empirically estimated voluntary demand.'},
              'results': results, 'retained_run_counterfactuals': retained}
    (args.output / 'results.json').write_text(json.dumps(report, indent=2) + '\n')
    lines = ['# LP participation and incentives research', '',
             f'{len(results)} scenarios × {args.days} days; per-day USDC/FUSE/share conservation passed. Research only; no new contract execution.', '',
             'Baseline allocation: 600M trader mining + 50M LP bootstrapping + 350M locked treasury = 1B genesis. No new supply.', '',
             '| Scenario | LP final USDC | Share return | Max NAV drawdown | External LPs | LP FUSE earned | Pending exits |',
             '|---|---:|---:|---:|---:|---:|---:|']
    for result in results:
        lines.append(f"| {result['scenario']['name']} | {result['lp_final_usdc_units']/USDC:,.2f} | {result['share_return']:.1%} | {result['max_share_drawdown']:.1%} | {result['participating_external_lps']} | {int(result['lp_bootstrap_earned_fuse_units'])/TOKEN:,.2f} | {result['pending_requests']} |")
    lines += ['', 'LP equity is endogenous: deposits, delayed withdrawals, underwriting losses and reserve contributions change available capital and trade admission. Share return excludes deposits/withdrawals and token incentives. LP emissions are separate from realized USDC performance.', '',
              'A 48-hour request period is a minimum, not a liquidity guarantee. Pending shares retain losses and may be delayed by solvency or reconciliation gates. Zero emissions after the bootstrap period; zero rewards without actual underwriting liability-time.', '',
              f'{len(retained)} retained live-run settlement paths were also replayed through the hypothetical new fee waterfall; see results.json. These are counterfactual accounting illustrations, not new contract E2Es.', '',
              'This research model does not deploy or exercise LP share, redemption queue, reward or vesting contracts. Contract/backend integration and ERC-7540 compliance require separate verification.', '',
              'Inspect results.json for all assumptions, parameters, daily NAV, utilization, cash PnL, pending claims and vesting. experiment.json records the input matrix and source hashes. The *-events.jsonl files contain deposits, requests, payments, batch settlements and verified daily accounting for the baseline and active LP stresses. No actual external LP demand has been established.']
    (args.output / 'report.md').write_text('\n'.join(lines) + '\n')
    print(args.output / 'report.md')
    print(json.dumps({'scenarios': len(results), 'days': args.days, 'conservation_verified': True,
                      'retained_run_counterfactuals': len(retained), 'contract_execution': False}))


if __name__ == '__main__':
    main()
