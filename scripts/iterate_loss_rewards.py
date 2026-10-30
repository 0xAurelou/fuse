#!/usr/bin/env python3
"""Research iteration: pre-funded USDC-value quotes, 9:1 losses, daily burns.

No contract/config changes. Quotes reserve worst-case dollar budget AND token
inventory before outcomes are examined. New funding becomes usable next day.
"""
import argparse
from collections import defaultdict
from dataclasses import asdict, dataclass, replace
import hashlib
import json
from pathlib import Path
import statistics

from stress_loss_rewards import GENESIS, Reserve, Scenario, Stage, TOKEN, USDC, trading_path

ROOT = Path(__file__).resolve().parent.parent


def ceildiv(n, d):
    return (n + d - 1) // d


@dataclass(frozen=True)
class Policy:
    name: str = 'seed25k-loss1-launch5'
    seed_usdc: int = 25_000
    loss_bps: int = 100
    fee_budget_bps: int = 5000
    launch_loss_bps: int = 500
    launch_budget_usdc: int = 2500
    ongoing_seed_budget_usdc: int = 0
    launch_wallet_cap_usdc: int = 10
    launch_token_cap: int = 100_000_000 * TOKEN
    mining_tokens: int = 600_000_000 * TOKEN
    days: int = 180

    def __post_init__(self):
        if (self.seed_usdc < 0 or not 0 <= self.loss_bps <= 10000
                or not 0 <= self.launch_loss_bps <= 10000
                or not 0 <= self.fee_budget_bps <= 10000
                or min(self.launch_budget_usdc, self.ongoing_seed_budget_usdc) < 0
                or self.launch_budget_usdc + self.ongoing_seed_budget_usdc > self.seed_usdc
                or self.launch_wallet_cap_usdc < 0
                or not 0 <= self.launch_token_cap <= self.mining_tokens < GENESIS
                or self.days <= 0):
            raise ValueError('invalid funded policy')


class InventoryReserve(Reserve):
    """950M is a new-allocation counterfactual, never an existing escrow change."""
    def __init__(self, initial, mining):
        self.mining = mining
        super().__init__(initial)

    def check(self, full=True):
        assert 0 <= self.outstanding <= self.balance
        assert self.balance + self.paid == self.funded
        assert self.supply == GENESIS - self.burned
        assert 0 <= self.emitted <= self.mining
        if full:
            assert sum(self.tokens.values()) + self.mining - self.emitted + GENESIS - self.mining == self.supply


@dataclass(frozen=True)
class Offer:
    account: int
    stake: int
    loss_value: int
    win_value: int
    max_tokens: int
    launch: bool


class Quoter:
    def __init__(self, policy, reserve):
        self.policy = policy
        self.reserve = reserve
        self.launch_left = policy.launch_budget_usdc * USDC
        self.earned_left = policy.ongoing_seed_budget_usdc * USDC
        self.earned_credited = self.earned_left
        self.launch_paid = self.earned_paid = self.launch_emitted = 0
        self.held_launch = self.held_earned = self.held_tokens = self.held_launch_tokens = 0
        self.wallet_launch_paid = defaultdict(int)
        self.wallet_launch_held = defaultdict(int)
        self.closed = False

    def credit(self, actual_funding):
        value = actual_funding * self.policy.fee_budget_bps // 10000
        self.earned_left += value
        self.earned_credited += value

    def quote(self, account, stake):
        """Outcome-independent: no status/duration argument is accepted."""
        if self.closed or stake <= 0:
            return None
        backing = self.reserve.balance - self.reserve.outstanding
        if backing <= 0:
            return None
        remaining = self.policy.mining_tokens - self.reserve.emitted - self.held_tokens
        for launch in (True, False):
            bps = self.policy.launch_loss_bps if launch else self.policy.loss_bps
            amount = stake * bps // 10000
            budget = self.launch_left if launch else self.earned_left
            if amount <= 0 or amount > budget:
                continue
            if launch and amount > (self.policy.launch_wallet_cap_usdc * USDC
                                     - self.wallet_launch_paid[account] - self.wallet_launch_held[account]):
                continue
            tokens = ceildiv(amount * self.reserve.supply, backing)
            if tokens > remaining:
                continue
            if launch and tokens > self.policy.launch_token_cap - self.launch_emitted - self.held_launch_tokens:
                continue
            if launch:
                self.launch_left -= amount
                self.held_launch += amount
                self.held_launch_tokens += tokens
                self.wallet_launch_held[account] += amount
            else:
                self.earned_left -= amount
                self.held_earned += amount
            self.held_tokens += tokens
            return Offer(account, stake, amount, amount // 9, tokens, launch)
        return None

    def settle(self, offers, stages):
        """Exact accepted quote is honored; unspent worst-case capacity returns."""
        assert len(offers) == len(stages)
        backing = self.reserve.balance - self.reserve.outstanding
        values = defaultdict(int)
        dollars = defaultdict(int)
        loss_value = win_value = 0
        for offer, stage in zip(offers, stages):
            if offer is None:
                continue
            assert offer.account == stage.account and offer.stake == stage.stake
            amount = offer.win_value if stage.won else offer.loss_value
            # Current backing/share cannot fall through a proportional 0%-fee
            # redemption, and only positive reserve funding is modeled.
            tokens = ceildiv(amount * self.reserve.supply, backing) if amount else 0
            assert tokens <= offer.max_tokens
            values[stage.account] += tokens
            dollars[stage.account] += amount
            if stage.won:
                win_value += amount
            else:
                loss_value += amount
            if offer.launch:
                self.launch_left += offer.loss_value - amount
                self.launch_paid += amount
                self.launch_emitted += tokens
                self.held_launch -= offer.loss_value
                self.held_launch_tokens -= offer.max_tokens
                self.wallet_launch_held[stage.account] -= offer.loss_value
                self.wallet_launch_paid[stage.account] += amount
            else:
                self.earned_left += offer.loss_value - amount
                self.earned_paid += amount
                self.held_earned -= offer.loss_value
            self.held_tokens -= offer.max_tokens
        self.reserve.distribute(values)
        self.check()
        return dict(dollars), dict(loss=loss_value, win=win_value)

    def check(self):
        assert self.launch_left + self.held_launch + self.launch_paid == self.policy.launch_budget_usdc * USDC
        assert self.earned_left + self.held_earned + self.earned_paid == self.earned_credited
        assert min(self.launch_left, self.earned_left, self.held_tokens) >= 0
        assert self.reserve.emitted + self.held_tokens <= self.policy.mining_tokens
        assert self.launch_emitted + self.held_launch_tokens <= self.policy.launch_token_cap
        assert all(0 <= value + self.wallet_launch_held[account] <= self.policy.launch_wallet_cap_usdc * USDC
                   for account, value in self.wallet_launch_paid.items())


def evaluate(policy, scenario, path, timing='daily'):
    reserve = InventoryReserve((policy.seed_usdc + scenario.reserve_usdc) * USDC, policy.mining_tokens)
    quoter = Quoter(policy, reserve)
    pending = []
    earned_values = defaultdict(int)
    launch_values = defaultdict(int)
    loss_value = win_value = loss_stake = win_stake = 0
    eligible = rejected = minimum_paid = 0
    first_off_day = None
    timeline = []
    for day, epoch in enumerate(path['epochs']):
        for window in pending:
            reserve.claim(window)
        pending = []
        if day >= policy.days:
            quoter.closed = True
        # Reserve all worst-case promises before examining any stage outcome.
        offers = [quoter.quote(stage.account, stage.stake) for stage in epoch['stages']]
        for offer, stage in zip(offers, epoch['stages']):
            if stage.won:
                win_stake += stage.stake
            else:
                loss_stake += stage.stake
            eligible += int(offer is not None)
            rejected += int(offer is None)
            if offer is None and first_off_day is None:
                first_off_day = day + 1
        # Same trading economics as the prior study. Today's actually funded
        # reserve profits improve backing, but can fund new quotes only tomorrow.
        reserve.fund(epoch['funding'])
        promised, split = quoter.settle(offers, epoch['stages'])
        for account, amount in promised.items():
            earned_values[account] += amount
        for offer, stage in zip(offers, epoch['stages']):
            if offer is not None and offer.launch:
                launch_values[stage.account] += offer.win_value if stage.won else offer.loss_value
        loss_value += split['loss']
        win_value += split['win']
        quoter.credit(epoch['funding'])
        if timing == 'daily' and promised:
            window = reserve.open(penalty=0)
            for account in promised:
                amount = reserve.tokens[account]
                if amount:
                    reserve.request(window, account, amount)
            pending.append(window)
        timeline.append(dict(day=day + 1, eligible=sum(o is not None for o in offers),
                             bets=len(offers), quoted_loss_value=split['loss'], quoted_win_value=split['win'],
                             emitted_fuse_units=str(reserve.emitted), reserve_usdc_units=reserve.balance,
                             launch_remaining_usdc_units=quoter.launch_left,
                             ongoing_remaining_usdc_units=quoter.earned_left))
    for window in pending:
        reserve.claim(window)
    if timing == 'end' and sum(reserve.tokens.values()):
        window = reserve.open(penalty=0)
        for account, amount in list(reserve.tokens.items()):
            if amount:
                reserve.request(window, account, amount)
        reserve.claim(window)
    for account, minimum in earned_values.items():
        # Per-day cumulative recipient floors can add tiny positive dust when
        # several separately ceil-rounded rewards are redeemed together.
        assert reserve.proceeds[account] >= minimum
        minimum_paid += minimum
    reserve.check()
    quoter.check()
    initial = (scenario.lp_usdc + scenario.reserve_usdc + policy.seed_usdc
               + scenario.traders * scenario.wallet_usdc) * USDC
    assert path['lp_cash'] + reserve.balance + sum(path['wallets']) + reserve.paid == initial
    farmer_loss = sum(scenario.wallet_usdc * USDC - path['wallets'][i] for i in range(path['farmer_count']))
    farmer_paid = sum(reserve.proceeds[i] for i in range(path['farmer_count']))
    return dict(policy=asdict(policy), scenario=asdict(scenario), timing=timing,
                lp_final_usdc_units=path['lp_final'], reserve_funded_usdc_units=path['reserve_funded'],
                actual_rewards_usdc_units=reserve.paid, quote_minimum_usdc_units=minimum_paid,
                reserve_remaining_usdc_units=reserve.balance, emitted_fuse_units=str(reserve.emitted),
                loss_rewards_usdc_units=loss_value, win_rewards_usdc_units=win_value,
                loss_stake_usdc_units=loss_stake, win_stake_usdc_units=win_stake,
                loss_compensation_bps=loss_value * 10000 / loss_stake if loss_stake else 0,
                launch_paid_usdc_units=quoter.launch_paid, ongoing_paid_usdc_units=quoter.earned_paid,
                ongoing_budget_credited_usdc_units=quoter.earned_credited,
                reward_coverage=eligible / (eligible + rejected) if eligible + rejected else 0,
                first_unrewarded_bet_day=first_off_day, reward_eligible_bets=eligible,
                unrewarded_bets=rejected, maximum_launch_reward_per_wallet_usdc_units=max(launch_values.values(), default=0),
                farmer_loss_usdc_units=farmer_loss, farmer_paid_usdc_units=farmer_paid,
                farmer_cash_pnl_usdc_units=farmer_paid - farmer_loss, conservation_verified=True,
                timeline=timeline if scenario.seed == 20261029 and timing == 'daily' else [])


def policies():
    base = Policy()
    return [replace(base, name='zero-seed-loss1', seed_usdc=0, launch_budget_usdc=0, launch_loss_bps=0),
            replace(base, name='seed25k-loss1', launch_budget_usdc=0, launch_loss_bps=0),
            base,
            replace(base, name='seed25k-loss2-launch5', loss_bps=200),
            replace(base, name='seed25k-loss1-launch10', launch_loss_bps=1000),
            replace(base, name='seed100k-loss1-launch5', seed_usdc=100_000, launch_budget_usdc=10000),
            replace(base, name='community95-loss1-launch5', mining_tokens=950_000_000 * TOKEN),
            replace(base, name='community95-loss2-launch5', mining_tokens=950_000_000 * TOKEN, loss_bps=200)]


def funded_policies():
    base = Policy(name='seed125k-loss2-launch10', seed_usdc=125_000, loss_bps=200,
                  fee_budget_bps=9000, launch_loss_bps=1000, launch_budget_usdc=10000,
                  launch_wallet_cap_usdc=25, ongoing_seed_budget_usdc=10000)
    return [replace(base, name='seed100k-loss2-launch10', seed_usdc=100_000),
            base, replace(base, name='seed150k-loss2-launch10', seed_usdc=150_000),
            replace(base, name='seed125k-loss1-launch10', loss_bps=100),
            replace(base, name='seed125k-loss3-launch10', loss_bps=300),
            replace(base, name='seed125k-loss2-launch5', launch_loss_bps=500),
            replace(base, name='seed125k-loss2-no-buffer', ongoing_seed_budget_usdc=0),
            replace(base, name='community95-seed125k-loss2', mining_tokens=950_000_000 * TOKEN)]


def scenarios():
    base = Scenario()
    return [base, replace(base, name='no-demand', games_per_day=0),
            replace(base, name='demand-stops-day30', stop_day=30),
            replace(base, name='winner-cluster', cluster_start=30, cluster_days=10),
            replace(base, name='negative-edge', survival_bps=5500),
            replace(base, name='instant-loss-farm', farmer_bps=2000, farmer_duration=1),
            replace(base, name='late-loss-farm', farmer_bps=2000, farmer_duration=29999),
            replace(base, name='mature100m', reserve_usdc=100_000_000),
            replace(base, name='weaker-2pct-edge', survival_bps=4900),
            replace(base, name='higher-volume', traders=1000, games_per_day=1000)]


def hedge_case(policy, split_wallets=False, honest_funding_usdc=0):
    """Deliberately adversarial zero-net-cost offset pair; not demonstrated quotes.

    Shows that bounded gross-loss rebates are NOT a Sybil/hedge prevention proof.
    """
    reserve = InventoryReserve(policy.seed_usdc * USDC, policy.mining_tokens)
    quoter = Quoter(policy, reserve)
    reserve.fund(honest_funding_usdc * USDC)
    quoter.credit(honest_funding_usdc * USDC)
    stages = [Stage(0, 100 * USDC, True, 30000),
              Stage(1 if split_wallets else 0, 100 * USDC, False, 1)]
    offers = [quoter.quote(s.account, s.stake) for s in stages]
    quoter.settle(offers, stages)
    if sum(reserve.tokens.values()):
        window = reserve.open(penalty=0)
        for account, amount in list(reserve.tokens.items()):
            if amount:
                reserve.request(window, account, amount)
        reserve.claim(window)
    return dict(policy=policy.name, split_wallets=split_wallets,
                honest_funding_usdc=honest_funding_usdc, pair_trading_pnl_usdc_units=0,
                pair_reward_usdc_units=reserve.paid, conservation_verified=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / '.local/loss-reward-iteration/20261029-funded-v3')
    parser.add_argument('--seeds', type=int, default=4)
    parser.add_argument('--profile', choices=('prototype', 'funded'), default='funded')
    args = parser.parse_args()
    if args.seeds <= 0:
        parser.error('positive --seeds required')
    args.output.mkdir(parents=True, exist_ok=True)
    active = funded_policies() if args.profile == 'funded' else policies()
    candidate = active[1] if args.profile == 'funded' else Policy()
    assumption = dict(version='loss-reward-iteration-v3', research_only=True, seeds=args.seeds,
        profile=args.profile, candidate_policy=candidate.name,
        budget='External USDC seed; launch and ongoing seed budgets are subsets of that seed, never counted twice. '
               'Ongoing credit is the configured 50% or 90% of actually funded new reserve profits, usable next day.',
        quote='Reserve full losing-outcome dollar amount and token inventory before seeing outcome. '
              'Winning quote is one ninth. Launch maximum $10 or $25 per wallet, with a global budget; '
              'wallet caps are not Sybil resistance. No accepted reward is retroactively reduced.',
        score_change='Completed funded outcome replaces stake*time for VALUE quotes; instantaneous genuine losses '
                     'receive the same bounded percentage. 9:1 applies to equal-stake outcomes.',
        supply='600M current trader inventory or explicit 950M new-deployment counterfactual; always 1B denominator.',
        redemption='0% penalty, daily requests/next-window claims, or hold until end. No token buyers.',
        behavior='Same finite funded trading paths across policies; no topups, retention assumption or recycling rewards.',
        limits='No hedge/Sybil prevention claimed. No operating/gas costs. LP drawdown control remains outside this iteration.')
    sources = [Path(__file__), ROOT / 'scripts/stress_loss_rewards.py', ROOT / 'scripts/contract_lp_model.py']
    assumption['source_sha256'] = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}
    assumption['policies'] = [asdict(p) for p in active]
    (args.output / 'experiment.json').write_text(json.dumps(assumption, indent=2) + '\n')
    results = []
    for case in scenarios():
        for seed in range(args.seeds):
            scenario = replace(case, seed=20261029 + seed)
            path = trading_path(scenario)
            for policy in active:
                results.append(evaluate(policy, scenario, path))
                if case.name == 'baseline':
                    results.append(evaluate(policy, scenario, path, timing='end'))
    hedges = [hedge_case(p, split, honest) for p in active for split in (False, True) for honest in (0, 1000)]
    payload = dict(assumptions=assumption, results=results, hedges=hedges)
    (args.output / 'results.json').write_text(json.dumps(payload, indent=2) + '\n')
    write_report(args.output, payload)
    print(json.dumps(dict(trajectories=len(results), hedge_cases=len(hedges), report=str(args.output / 'report.md'))))


def write_report(output, payload):
    rows = payload['results']
    lines = ['# FUSE reward iteration: funded value quotes', '',
             'Research only. Dollar budgets and token inventory are reserved before outcomes. '
             'Positive USDC seed is external funding, separate from LP capital. '
             'A 950M trader inventory is a new-deployment allocation counterfactual, not an existing escrow mutation.', '',
             f"{len(rows)} trajectories and {len(payload['hedges'])} offset-pair cases; all conservation checks passed.", '',
             '## Baseline medians', '',
             '| Policy | Seed USDC | Paid USDC | Loss compensation | Rewarded bets | Emitted FUSE | Launch paid USDC |',
             '|---|---:|---:|---:|---:|---:|---:|']
    for config in payload['assumptions']['policies']:
        policy = Policy(**config)
        group = [r for r in rows if r['scenario']['name'] == 'baseline'
                 and r['policy']['name'] == policy.name and r['timing'] == 'daily']
        med = lambda key: statistics.median(float(r[key]) for r in group)
        lines.append(f"| {policy.name} | {policy.seed_usdc:,} | {med('actual_rewards_usdc_units') / USDC:,.2f} | "
                     f"{med('loss_compensation_bps') / 100:.2f}% | {med('reward_coverage'):.1%} | "
                     f"{med('emitted_fuse_units') / TOKEN:,.0f} | {med('launch_paid_usdc_units') / USDC:,.2f} |")
    lines += ['', f"## Candidate stresses: {payload['assumptions']['candidate_policy']}", '',
              '| Scenario | LP final USDC | New backing USDC | Paid USDC | Rewarded bets | Farmer cash PnL USDC |',
              '|---|---:|---:|---:|---:|---:|']
    for case in scenarios():
        group = [r for r in rows if r['scenario']['name'] == case.name
                 and r['policy']['name'] == payload['assumptions']['candidate_policy'] and r['timing'] == 'daily']
        med = lambda key: statistics.median(float(r[key]) for r in group)
        lines.append(f"| {case.name} | {med('lp_final_usdc_units') / USDC:,.2f} | "
                     f"{med('reserve_funded_usdc_units') / USDC:,.2f} | {med('actual_rewards_usdc_units') / USDC:,.2f} | "
                     f"{med('reward_coverage'):.1%} | {med('farmer_cash_pnl_usdc_units') / USDC:,.2f} |")
    lines += ['', '## Boundaries', '',
              '- A reward offer can be unavailable after dollar/token capacity is used. The user must see this before entry; '
              'gameplay can continue without a reward, with no previously accepted promise reduced.',
              '- Launch reward is a funded promotional target, not perpetual cashback. Ongoing rates are subject to '
              'actual fee funding and finite token inventory. No demand or retention improvement is assumed.',
              '- Daily payouts satisfy quoted dollar minima in this monotonic segregated-backing model. Holding tokens '
              'can return more later; a current-value issuance cap does not cap future token appreciation.',
              '- A zero-net-cost offset pair earns gross-loss rewards in the adversarial cases. The pair is an assumed '
              'hedge, not a demonstrated FUSE strategy. Aggregate limits bound the subsidy, but do not prove Sybil resistance.',
              '- Fixed supply, broader player allocation and removing the redemption haircut improve different parts '
              'of the offer; none creates USDC, eliminates LP drawdown or substitutes for measured funded demand.', '',
              'Full policy and scenario outputs, held-token controls and hedge bounds are in results.json. '
              'experiment.json pins the exact source hashes and explicit assumptions.']
    (output / 'report.md').write_text('\n'.join(lines) + '\n')


if __name__ == '__main__':
    main()
