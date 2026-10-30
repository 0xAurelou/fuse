#!/usr/bin/env python3
"""Offline USDC loss-reward stress tests; synthetic behavior, no transactions.

Pairs reward policies on exactly the same funded trading paths, projects the
existing share-mode LP waterfall, and checks fixed-snapshot burn/redemption.
No inference about voluntary demand or a secondary-market FUSE price is made.
"""
import argparse
from collections import defaultdict
from dataclasses import asdict, dataclass, replace
import hashlib
import json
from pathlib import Path
import random

from contract_lp_model import LPModel, USDC, TOKEN, DAY

ROOT = Path(__file__).resolve().parent.parent
GENESIS = 1_000_000_000 * TOKEN
MINING = 600_000_000 * TOKEN
POLICIES = {'current': (10000, 2000), 'loss9': (1000, 9000), 'neutral': (10000, 10000)}


@dataclass(frozen=True)
class Stage:
    account: int
    stake: int
    won: bool
    duration: int


@dataclass(frozen=True)
class Scenario:
    name: str = 'baseline'
    days: int = 180
    seed: int = 20261029
    lp_usdc: int = 250_000
    reserve_usdc: int = 0  # Assumed historical funding, separate from LP cash.
    traders: int = 300
    wallet_usdc: int = 1000
    games_per_day: int = 300
    stake_usdc: int = 50
    survival_bps: int = 4800
    correlation_bps: int = 0
    farmer_bps: int = 0
    farmer_duration: int = 1
    stop_day: int = 180
    cluster_start: int = -1
    cluster_days: int = 0
    allocation_bps: int = 3500


def score(stage, weights):
    return stage.stake * stage.duration * weights[0 if stage.won else 1]


def allocations(stages, policy, budget_cap, rate=100, common_budget=False):
    """Same integer stake*time scoring/activity denominator as rewards.go.

    common_budget holds the CURRENT policy's activity budget fixed, isolating
    who receives tokens. It is a counterfactual policy, not current Go behavior.
    """
    points = defaultdict(int)
    loss_points = 0
    for stage in stages:
        value = score(stage, POLICIES[policy])
        points[stage.account] += value
        if not stage.won:
            loss_points += value
    total = sum(points.values())
    activity_score = sum(score(x, POLICIES['current']) for x in stages) if common_budget else total
    activity_cap = activity_score * rate * TOKEN // (USDC * 30000 * 10000)
    budget = min(budget_cap, activity_cap) if total else 0
    result = {account: budget * value // total for account, value in points.items()} if total else {}
    distributed = sum(result.values())
    assert 0 <= distributed <= budget <= budget_cap
    return result, dict(activity_cap=str(activity_cap), distributed=str(distributed),
                        loss_weight_share=loss_points / total if total else 0)


def scheduled_cap(slot, initial=10_000_000 * TOKEN, decay_bps=340, horizon=180):
    """RewardDistributor.capAtSlot integer exponentiation, daily research slots."""
    if not 1 <= slot <= horizon:
        return 0
    factor, base, exponent = 10**18, (10000 - decay_bps) * 10**14, slot - 1
    while exponent:
        if exponent & 1:
            factor = factor * base // 10**18
        base = base * base // 10**18
        exponent >>= 1
    return initial * factor // 10**18


class Reserve:
    """Fixed epoch snapshots, cumulative per-account rounding and delayed claims."""
    def __init__(self, initial=0):
        self.balance = self.funded = initial
        self.supply = GENESIS
        self.outstanding = self.paid = self.emitted = self.burned = 0
        self.tokens = defaultdict(int)
        self.proceeds = defaultdict(int)
        self.epochs = []

    def fund(self, amount):
        assert amount >= 0
        self.balance += amount
        self.funded += amount

    def distribute(self, values):
        for account, amount in values.items():
            self.tokens[account] += amount
            self.emitted += amount
        self.check()

    def open(self, penalty=1000):
        assert 0 <= penalty <= 10000
        self.epochs.append(dict(supply=self.supply, backing=self.balance - self.outstanding,
                                penalty=penalty, requests=defaultdict(int), claims=defaultdict(int), paid=set()))
        return len(self.epochs) - 1

    def request(self, epoch, account, amount):
        e = self.epochs[epoch]
        assert 0 <= amount <= self.tokens[account] and amount < self.supply
        cumulative = e['requests'][account] + amount
        entitlement = cumulative * (10000 - e['penalty']) * e['backing'] // (e['supply'] * 10000)
        extra = entitlement - e['claims'][account]
        e['requests'][account] = cumulative
        e['claims'][account] = entitlement
        self.tokens[account] -= amount
        self.supply -= amount
        self.burned += amount
        self.outstanding += extra
        self.check(full=False)

    def claim(self, epoch):
        e = self.epochs[epoch]
        for account, amount in e['claims'].items():
            if account not in e['paid']:
                self.proceeds[account] += amount
                self.balance -= amount
                self.outstanding -= amount
                self.paid += amount
                e['paid'].add(account)
        self.check()

    def check(self, full=True):
        assert 0 <= self.outstanding <= self.balance
        assert self.balance + self.paid == self.funded
        assert self.supply == GENESIS - self.burned
        assert 0 <= self.emitted <= MINING
        if full:
            assert sum(self.tokens.values()) + (MINING - self.emitted) + 400_000_000 * TOKEN == self.supply


def trading_path(s):
    """One-stage 2x bets, actual funded wallets, six concurrent batches per day.

    Farm losses at specified times are adversarial bounds, not evidence that
    players can force an oracle loss. No new deposits or redeemed-cash recycling.
    """
    rng = random.Random(s.seed)
    vault = LPModel(1, allocation_bps=s.allocation_bps)
    vault.deposit('protocol', s.lp_usdc * USDC)
    vault.finalize(0, 100 * USDC, 0)
    vault.set_phase(1)  # Counterfactual activation of current share economics.
    vault.resume()
    wallets = [s.wallet_usdc * USDC] * s.traders
    initial_wallets = sum(wallets)
    farmer_count = s.traders * s.farmer_bps // 10000
    epochs = []
    peak = vault.assets
    drawdown = 0
    rejected = wins = losses = turnover = 0
    for day in range(s.days):
        stages = []
        funded_before = vault.reserve
        for batch in range(6):
            vault.clock(1 + day * DAY + batch * 60)
            common = rng.randrange(10000)
            admitted = []
            exposure = 0
            # Independent day streams make losing/winning policy paths matched.
            order = list(range(s.traders))
            rng.shuffle(order)
            if day >= s.stop_day:
                order = []
            begin = batch * s.games_per_day // 6
            end = (batch + 1) * s.games_per_day // 6
            for j in range(begin, end):
                if not order:
                    break
                account = order[j % len(order)]
                stake = s.stake_usdc * USDC
                # Keep the post-worst-case batch equity sufficient for the
                # signed next-batch capital requirement (exposure + buffer).
                if wallets[account] < stake or 2 * (exposure + stake) + 100 * USDC > vault.assets:
                    rejected += 1
                    continue
                exposure += stake
                u = common if rng.randrange(10000) < s.correlation_bps else rng.randrange(10000)
                won = u < s.survival_bps
                if s.cluster_start <= day < s.cluster_start + s.cluster_days:
                    won = True
                farmer = account < farmer_count
                if farmer:
                    won = False
                duration = 30000 if won else (s.farmer_duration if farmer else rng.randrange(1, 30000))
                admitted.append(Stage(account, stake, won, duration))
            pnl = 0
            for stage in admitted:
                change = stage.stake if stage.won else -stage.stake
                wallets[stage.account] += change
                pnl -= change
                wins += int(stage.won)
                losses += int(not stage.won)
                turnover += stage.stake
            required = max(100 * USDC, exposure + 100 * USDC)
            vault.finalize(pnl, required, 0, pause=False)
            if vault.fee and vault.required <= vault.assets // 2:
                vault.fund_reserve(vault.fee)
            vault.check()
            assert vault.cash + vault.reserve + sum(wallets) == s.lp_usdc * USDC + initial_wallets
            peak = max(peak, vault.assets)
            drawdown = max(drawdown, (peak - vault.assets) / peak)
            stages.extend(admitted)
        epochs.append(dict(stages=stages, funding=vault.reserve - funded_before))
    return dict(epochs=epochs, wallets=wallets, farmer_count=farmer_count,
                lp_final=vault.assets, lp_cash=vault.cash, accrued_fee=vault.fee,
                lp_pnl=vault.pnl, reserve_funded=vault.reserve,
                drawdown=drawdown, rejected=rejected, wins=wins, losses=losses, turnover=turnover)


def evaluate(s, path, policy, common_budget=False, redemption='end', rate=100, initial_cap=10_000_000 * TOKEN):
    reserve = Reserve(s.reserve_usdc * USDC)
    reward_by_account = defaultdict(int)
    loss_attributed = 0
    pending = []
    for day, epoch in enumerate(path['epochs']):
        # Claims settle after the prior window; pending liabilities were excluded
        # from backing as soon as their corresponding FUSE was burned.
        for window in pending:
            reserve.claim(window)
        pending = []
        reserve.fund(epoch['funding'])
        cap = min(scheduled_cap(day + 1, initial_cap), MINING - reserve.emitted)
        rewards, stats = allocations(epoch['stages'], policy, cap, rate, common_budget)
        reserve.distribute(rewards)
        for account, amount in rewards.items():
            reward_by_account[account] += amount
        loss_attributed += int(stats['loss_weight_share'] * int(stats['distributed']))
        if redemption == 'daily' and reserve.balance > reserve.outstanding and sum(reserve.tokens.values()):
            window = reserve.open()
            for account in sorted(reserve.tokens):
                reserve.request(window, account, reserve.tokens[account])
            pending.append(window)
    for window in pending:
        reserve.claim(window)
    if redemption == 'end' and reserve.balance > reserve.outstanding and sum(reserve.tokens.values()):
        window = reserve.open()
        for account in sorted(reserve.tokens):
            reserve.request(window, account, reserve.tokens[account])
        reserve.claim(window)
    reserve.check()
    initial_cash = s.lp_usdc * USDC + s.reserve_usdc * USDC + s.traders * s.wallet_usdc * USDC
    assert path['lp_cash'] + reserve.balance + sum(path['wallets']) + reserve.paid == initial_cash
    farmers = range(path['farmer_count'])
    farmer_loss = sum(s.wallet_usdc * USDC - path['wallets'][i] for i in farmers)
    farmer_paid = sum(reserve.proceeds[i] for i in farmers)
    winners_tokens = sum(amount for i, amount in reward_by_account.items() if path['wallets'][i] > s.wallet_usdc * USDC)
    net_pnl = [path['wallets'][i] - s.wallet_usdc * USDC + reserve.proceeds[i] for i in range(s.traders)]
    return dict(scenario=asdict(s), policy=policy,
                activity_budget='current-policy-held-fixed' if common_budget else 'own-weighted-score',
                redemption=redemption, lp_final_usdc_units=path['lp_final'], lp_pnl_usdc_units=path['lp_pnl'],
                lp_max_drawdown=path['drawdown'], unfunded_payouts=0,
                accepted=path['wins'] + path['losses'], rejected=path['rejected'],
                wins=path['wins'], losses=path['losses'], turnover_usdc_units=path['turnover'],
                reserve_funded_usdc_units=path['reserve_funded'], accrued_fee_usdc_units=path['accrued_fee'],
                reserve_remaining_usdc_units=reserve.balance, redeemed_usdc_units=reserve.paid,
                emitted_fuse_units=str(reserve.emitted), burned_fuse_units=str(reserve.burned),
                loss_attributed_reward_share=loss_attributed / reserve.emitted if reserve.emitted else 0,
                net_winner_reward_share=winners_tokens / reserve.emitted if reserve.emitted else 0,
                farmer_loss_usdc_units=farmer_loss, farmer_redeemed_usdc_units=farmer_paid,
                farmer_cash_pnl_usdc_units=farmer_paid - farmer_loss,
                profitable_traders_including_redemption=sum(x > 0 for x in net_pnl),
                conservation_verified=True)


def attack_case(policy, backing_usdc, attack_usdc, duration, honest_usdc=0,
                rate=100, cap_tokens=10_000_000, common_budget=False, lp_owned_bps=0):
    """One epoch, no prior attacker FUSE; assumed existing reserve stays funded.

    Honest volume is half 2x wins, half losses at 15s: zero net LP PnL. The
    attacker loses once and receives only the resulting newly distributed FUSE.
    35% funding assumes fully capitalized LP/HWM, so this is an upper bound.
    """
    stages = [Stage(0, attack_usdc * USDC, False, duration)]
    if honest_usdc:
        half = honest_usdc * USDC // 2
        stages += [Stage(1, half, True, 30000), Stage(2, half, False, 15000)]
    values, _ = allocations(stages, policy, cap_tokens * TOKEN, rate, common_budget)
    ledger = Reserve(backing_usdc * USDC)
    contribution = attack_usdc * USDC * 3500 // 10000
    ledger.fund(contribution)
    ledger.distribute(values)
    epoch = ledger.open()
    ledger.request(epoch, 0, ledger.tokens[0])
    ledger.claim(epoch)
    proceeds = ledger.proceeds[0]
    lp_equity_gain = (attack_usdc * USDC - contribution) * lp_owned_bps // 10000
    # LP equity gain is a separate mark on actual retained USDC, not a paid exit.
    return dict(policy=policy, backing_usdc=backing_usdc, attack_usdc=attack_usdc,
                duration_ms=duration, honest_usdc=honest_usdc, rate=rate, cap_tokens=cap_tokens,
                common_budget=common_budget, lp_owned_bps=lp_owned_bps,
                attacker_fuse_units=str(values.get(0, 0)), redeemed_usdc_units=proceeds,
                cash_pnl_usdc_units=proceeds - attack_usdc * USDC,
                retained_lp_equity_gain_usdc_units=lp_equity_gain,
                wealth_pnl_usdc_units=proceeds - attack_usdc * USDC + lp_equity_gain,
                conservation_verified=True)


def examples():
    base = Scenario()
    return [base,
            replace(base, name='no-demand', games_per_day=0),
            replace(base, name='demand-stops-day30', stop_day=30),
            replace(base, name='winner-cluster-10days', cluster_start=30, cluster_days=10),
            replace(base, name='negative-edge', survival_bps=5500),
            replace(base, name='correlated-80pct', correlation_bps=8000),
            replace(base, name='low-capital-10k', lp_usdc=10_000),
            replace(base, name='loss-farm-1ms', farmer_bps=2000, farmer_duration=1),
            replace(base, name='loss-farm-15s', farmer_bps=2000, farmer_duration=15000),
            replace(base, name='loss-farm-29999ms', farmer_bps=2000, farmer_duration=29999),
            replace(base, name='mature-reserve-1m', reserve_usdc=1_000_000),
            replace(base, name='mature-reserve-10m-farm', reserve_usdc=10_000_000,
                    farmer_bps=2000, farmer_duration=29999),
            replace(base, name='all-loss-bound', survival_bps=0),
            replace(base, name='all-win-bound', survival_bps=10000)]


def historical_reweight():
    """Reweight recorded final stage outcomes without rerunning or resampling prices."""
    results = []
    for run in ('20261026-002626', '20261026-012628'):
        path = ROOT / '.local/live-runs' / run / 'evidence/final-state.json'
        if not path.exists():
            continue
        state = json.loads(path.read_text())
        stages = []
        pnl = defaultdict(int)
        for stage in state['stages'].values():
            if stage['status'] not in ('survived', 'exploded'):
                continue
            terms = stage['terms']
            won = stage['status'] == 'survived'
            duration = min(terms['duration_ms'], stage['resolved'] - stage['start'])
            assert duration >= 0
            account = terms['account']
            stages.append(Stage(account, terms['stake'], won, duration))
            pnl[account] += terms['payout'] - terms['stake'] if won else -terms['stake']
        for policy in POLICIES:
            for common in (False, True):
                values, stats = allocations(stages, policy, 10_000_000 * TOKEN, common_budget=common)
                emitted = sum(values.values())
                results.append(dict(run=run, source=str(path),
                    sha256=hashlib.sha256(path.read_bytes()).hexdigest(), policy=policy,
                    common_budget=common, stages=len(stages), wins=sum(x.won for x in stages),
                    loss_weight_share=stats['loss_weight_share'], emitted_fuse_units=str(emitted),
                    net_winner_reward_share=sum(v for a, v in values.items() if pnl[a] > 0) / emitted if emitted else 0,
                    scope='Retrospective score reweighting only; one synthetic reward epoch; no new prices, capital simulation or inferred demand.'))
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / '.local/loss-reward-stress/20261029')
    parser.add_argument('--seeds', type=int, default=8)
    args = parser.parse_args()
    if args.seeds <= 0:
        parser.error('--seeds must be positive')
    args.output.mkdir(parents=True, exist_ok=True)
    assumptions = dict(version='loss-reward-stress-v1', research_only=True, empirical_demand=False,
        genesis_fuse=1_000_000_000, trader_escrow_fuse=600_000_000,
        inactive_lp_escrow_fuse=50_000_000, locked_treasury_fuse=350_000_000,
        policies=POLICIES, seeds=args.seeds, days=180, stake_usdc=50, payout_multiplier=2,
        baseline_survival_bps=4800, initial_trader_funding_usdc=300_000,
        external_topups_usdc=0, recycled_redemption_proceeds=False,
        activity_rate_fuse_per_usdc_30s=100, initial_daily_cap_fuse=10_000_000,
        daily_decay_bps=340, horizon_days=180, redemption_penalty_bps=1000,
        lp_economics='current share-mode contribution-adjusted HWM, 35% max, ramp, 2C floor; assumed activated',
        lp_operations='No new LP deposits, exits or LP incentive activation; 50M escrow remains in denominator.',
        redemption='end-of-horizon or daily fixed-snapshot requests; claims after window; no secondary bids',
        forced_losses='Adversarial bounds, not a demonstrated ability to force an oracle loss at a chosen time.',
        maturity='Positive starting reserve is assumed prior historical funding, never a transfer from initial LP capital.',
        scope='Synthetic one-stage 2x wagers; not oracle calibration, production approval, demand estimation, or a contract execution test.')
    source_paths = [Path(__file__), ROOT / 'scripts/contract_lp_model.py',
                    ROOT / 'src/LPVault.sol', ROOT / 'src/RedemptionReserve.sol',
                    ROOT / 'src/RewardDistributor.sol', ROOT / 'engine/internal/rewards/rewards.go']
    assumptions['source_sha256'] = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in source_paths}
    (args.output / 'experiment.json').write_text(json.dumps(assumptions, indent=2) + '\n')
    results = []
    for case in examples():
        for seed in range(args.seeds):
            s = replace(case, seed=20261029 + seed)
            path = trading_path(s)
            for policy in POLICIES:
                for common in (False, True):
                    for redemption in ('end', 'daily'):
                        results.append(evaluate(s, path, policy, common, redemption))
    attacks = []
    for policy in POLICIES:
        for backing in (0, 100_000, 1_000_000, 10_000_000, 100_000_000):
            for stake in (1, 10, 100, 1000, 10000):
                for duration in (1, 15000, 29999):
                    for honest in (0, 1000, 10000, 100000):
                        for rate in (1, 100, 1000):
                            for common in (False, True):
                                for owned in (0, 9000):
                                    attacks.append(attack_case(policy, backing, stake, duration, honest,
                                                               rate, common_budget=common, lp_owned_bps=owned))
    payload = dict(assumptions=assumptions, trajectories=results, attacks=attacks,
                   historical_reweighting=historical_reweight())
    (args.output / 'results.json').write_text(json.dumps(payload, indent=2) + '\n')
    write_report(args.output, payload)
    print(json.dumps(dict(trajectories=len(results), attack_cases=len(attacks), conservation_verified=True,
                          report=str(args.output / 'report.md'))))


def write_report(output, payload):
    import statistics
    rows = payload['trajectories']
    lines = ['# USDC-backed FUSE: 9x loss-weight stress test', '',
             'Research only. Fixed 1B genesis supply; existing tokens distributed, then burned for redemption. '
             'FUSE has no claim on LP equity. Backing is segregated USDC funded from eligible realized LP profits.', '',
             f"{len(rows):,} paired policy/timing/budget trajectories and {len(payload['attacks']):,} single-epoch adversarial cases. "
             'Integer USDC and FUSE conservation passed throughout.', '',
             '## Assumptions', '',
             '180 synthetic days; 300 wallets each initially funded with $1,000; up to 300 $50 one-stage 2x bets/day. '
             'Baseline survival 48% (4% expected house edge). No trader topups, token buyers, LP flows or recycling redemption proceeds. '
             'Six concurrent batches/day; admitted worst-case payouts must be funded. '
             'LP starts at $250,000 unless specified. Share economics are assumed activated, with the existing HWM, '
             'capitalization ramp, 35% maximum fee and 2C funding floor. Accrued fees are separately tracked.', '',
             'Current weights: win 10,000 / loss 2,000. Proposed weights: win 1,000 / loss 9,000. '
             'Neutral: 10,000 / 10,000. Score also includes actual stake and time exposed. '
             'The 9x ratio does not reserve 90% of tokens for losses. Weight magnitudes affect the activity budget.', '',
             'Research emissions: 100 FUSE per $1 exposed for 30 seconds at weight 1; daily cap starts at 10M FUSE '
             'and decays 3.4% per day for 180 days, with a 600M lifetime escrow limit. '
             'This daily schedule is hypothetical, not the accelerated local deployment schedule or an approved launch policy. '
             'Redemption burns at a fixed snapshot, with 10% penalty. All treasury and inactive LP tokens count in supply.', '',
             'The paired comparison holds trading behavior and wallet funding fixed. It cannot demonstrate that loss rewards '
             'increase voluntary play, retention, or LP profits. Forced-loss tests at specified times are adversarial bounds; '
             'they do not demonstrate control over oracle outcomes.', '',
             '## Paired results', '',
             'Medians across seeds; direct weighted activity cap; all trader tokens redeemed at the end. '
             'LP and backing funding are identical across reward policies on each matched path. '
             'Reserve paid is aggregate trader proceeds, not a guaranteed per-player refund.', '',
             '| Scenario | LP final $ | Max LP drawdown | New backing $ | Current redemption $ | 9x-loss redemption $ | 9x tokens attributed to losses |',
             '|---|---:|---:|---:|---:|---:|---:|']
    for s in examples():
        groups = {p: [r for r in rows if r['scenario']['name'] == s.name and r['policy'] == p
                      and r['activity_budget'] == 'own-weighted-score' and r['redemption'] == 'end'] for p in POLICIES}
        med = lambda key, p='loss9': statistics.median(r[key] for r in groups[p])
        lines.append(f"| {s.name} | {med('lp_final_usdc_units') / USDC:,.2f} | {med('lp_max_drawdown'):.1%} | "
                     f"{med('reserve_funded_usdc_units') / USDC:,.2f} | {med('redeemed_usdc_units', 'current') / USDC:,.2f} | "
                     f"{med('redeemed_usdc_units') / USDC:,.2f} | {med('loss_attributed_reward_share'):.1%} |")
    lines += ['', '## Budget and redemption timing controls', '',
              'Baseline medians. Holding the current-policy activity budget fixed isolates redistribution from aggregate emission changes.', '',
              '| Policy | Activity budget | Redemption | Emitted FUSE | Paid USDC | Rewards to net USDC winners |',
              '|---|---|---|---:|---:|---:|']
    for policy in POLICIES:
        for common in ('own-weighted-score', 'current-policy-held-fixed'):
            for timing in ('end', 'daily'):
                group = [r for r in rows if r['scenario']['name'] == 'baseline' and r['policy'] == policy
                         and r['activity_budget'] == common and r['redemption'] == timing]
                med = lambda key: statistics.median(float(r[key]) for r in group)
                lines.append(f"| {policy} | {common} | {timing} | {med('emitted_fuse_units') / TOKEN:,.0f} | "
                             f"{med('redeemed_usdc_units') / USDC:,.2f} | {med('net_winner_reward_share'):.1%} |")
    lines += ['', '## Deliberate-loss bounds', '',
              'All examples below use the current 100 FUSE activity rate, a 10M epoch cap, a single $100 attacker loss, '
              'no initial attacker FUSE and no external buyers. Starting reserve is hypothetical historical backing. '
              'Fee funding assumes the maximum 35% is available. Late forced losses are adversarial bounds.', '',
              '| Initial backing $ | Loss duration | Honest turnover $ | Policy | Redeemed $ | Attacker cash PnL $ |',
              '|---|---:|---:|---|---:|---:|']
    for backing, duration, honest in ((0, 29999, 0), (1_000_000, 29999, 0), (10_000_000, 29999, 0),
                                      (100_000_000, 1, 0), (100_000_000, 15000, 0),
                                      (100_000_000, 29999, 10000)):
        for policy in ('current', 'loss9'):
            a = attack_case(policy, backing, 100, duration, honest)
            lines.append(f"| {backing:,.0f} | {duration:,} ms | {honest:,} | {policy} | "
                         f"{a['redeemed_usdc_units'] / USDC:,.4f} | {a['cash_pnl_usdc_units'] / USDC:,.4f} |")
    lines += ['', '## Interpretation and limits', '',
              '- Changing rewards alone does not change the matched LP trading result or create backing. '
              'A growth benefit requires new funded activity and must be measured separately.',
              '- A loss reward is not a fixed refund. Initially empty backing can produce very little executable USDC '
              'even when token rewards look large. Existing holders and unreleased escrows share the backing.',
              '- At sufficient historical backing per outstanding FUSE, mining existing escrowed tokens and redeeming them '
              'can exceed the cost of a deliberate loss. This is a transfer of existing backing rights, not new minting '
              'or an insolvent redemption. The rate, time exposed, available epoch cap and competition matter.',
              '- Stake*time strongly suppresses instantaneous-loss farming but also gives early genuine losses smaller rewards. '
              'A 9x outcome multiplier is not a 9x payout when durations differ.',
              '- Gross losing stages still reward accounts that win overall. Period-level net-loss rules need a separate '
              'wallet-splitting/adversarial analysis; per-wallet netting alone is not Sybil-resistant.',
              '- An attacker that also owns LP shares recaptures some retained losses as LP equity. '
              'The attack grid reports this separately from realized redemption cash; it assumes no instant LP exit.',
              '- Winner clusters and negative underwriting edge can deplete LP capital regardless of reward split. '
              'FUSE backing remains segregated and cannot be recycled to pay bets.',
              '- Finite emission slots expire and rewards are bounded by escrow. Daily redemption burns early rights to future '
              'backing; waiting is a different economic choice. Pending redemption claims are excluded from later snapshots.',
              '- No secondary-market price, user retention benefit, HYPE conversion, operating/gas cost or production safety '
              'claim is inferred. Existing reserve funding is assumed immediately dual-authorized when permitted.', '',
              '## Reproduce', '',
              '```sh', 'python3 -m unittest discover -s scripts -p test_loss_reward_stress.py',
              'python3 scripts/stress_loss_rewards.py --seeds 8', '```', '',
              'Full case results are in results.json; experiment.json pins assumptions and source hashes.']
    (output / 'report.md').write_text('\n'.join(lines) + '\n')


if __name__ == '__main__':
    main()
