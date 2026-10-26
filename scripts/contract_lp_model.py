"""Integer projection of LPVault/LPShareVault/LPIncentiveDistributor economics.

This is an offline model of successful authorized operations, not signature,
token-callback, governance or transaction-inclusion verification. Solidity
differential vectors exercise the same transitions against deployed contracts.
The older Bernoulli/half-life simulator remains a separate research model.
"""
from collections import defaultdict
from dataclasses import dataclass

USDC = 10**6
TOKEN = 10**18
VIRTUAL = 10**12
RAY = 10**27
DAY = 86400
BUDGET = 50_000_000 * TOKEN


def ceildiv(n, d):
    return (n + d - 1) // d


def scheduled_budget(epoch):
    if not 1 <= epoch <= 90:
        return 0
    return (BUDGET * epoch * (180 - epoch) // 8100
            - BUDGET * (epoch - 1) * (181 - epoch) // 8100)


@dataclass
class Exit:
    owner: str
    shares: int
    ready: int
    epoch: int
    assets: int = 0
    fulfilled: bool = False
    claimed_shares: int = 0
    claimed_assets: int = 0


class LPModel:
    def __init__(self, start, allocation_bps=3500, target_bps=2000):
        if start <= 0 or not 0 <= allocation_bps <= 3500 or not 0 < target_bps <= 10000:
            raise ValueError('invalid economic configuration')
        self.start = self.now = self.last_update = start
        self.allocation_bps, self.target_bps = allocation_bps, target_bps
        self.cash = self.fee = self.reserved = self.reserve = 0
        self.supply = self.pnl = self.contributions = self.paid_exits = 0
        self.hwm_assets, self.hwm_shares = 1, VIRTUAL
        self.required = self.exposure = self.nav_epoch = self.nav_at = 0
        self.phase = 0
        self.paused = False
        self.liquidity = False
        self.hard_cap = 5_000_000 * USDC
        self.demand = self.capacity_until = 0
        self.shares = defaultdict(int)
        self.protocol = set()
        self.whitelist = {'protocol'}
        self.exits = []
        self.head = 0
        self.active_request = {}
        self.index = 0
        self.capital_seconds = defaultdict(int)
        self.liability_seconds = defaultdict(int)
        self.index_at_end = defaultdict(int)
        self.cursors = {}
        self.eligible = defaultdict(int)
        self.epochs = {}
        self.latest_epoch = self.published = self.claimed = 0
        self.claims = set()
        self.token_balances = defaultdict(int)

    @property
    def assets(self):
        return max(0, self.cash - self.fee - self.reserved)

    def clock(self, at):
        if at < self.now:
            raise ValueError('regressing model clock')
        self.now = at

    def checkpoint(self):
        stop = min(self.now, self.start + 90 * DAY)
        t = self.last_update
        while t < stop:
            epoch = (t - self.start) // DAY + 1
            until = min(stop, self.start + epoch * DAY)
            duration = until - t
            self.capital_seconds[epoch] += self.assets * duration
            if self.supply:
                self.index += (self.assets * RAY // self.supply) * duration
            if until == self.start + epoch * DAY:
                self.index_at_end[epoch] = self.index
            t = until
        self.last_update = max(self.last_update, stop)

    def account_checkpoint(self, owner):
        self.checkpoint()
        target = (min(self.now, self.start + 90 * DAY) - self.start) // DAY + 1
        epoch, index = self.cursors.get(owner, (1, 0))
        shares = 0 if owner in self.protocol or owner == 'vault' else self.shares[owner]
        while epoch < target:
            endpoint = self.index_at_end[epoch]
            self.eligible[epoch, owner] += shares * (endpoint - index) // RAY
            epoch, index = epoch + 1, endpoint
        if epoch <= 90:
            self.eligible[epoch, owner] += shares * (self.index - index) // RAY
        self.cursors[owner] = (epoch, self.index)

    def fresh(self):
        return self.nav_at > 0 and 0 <= self.now - self.nav_at <= 3600 and self.exposure == 0

    def set_phase(self, phase):
        if phase != self.phase + 1 or phase > 2 or not self.fresh():
            raise ValueError('phase requires next phase and fresh zero-exposure NAV')
        self.phase = phase

    def resume(self):
        # Mirrors AccessController's nonce invalidation. A generic re-pause
        # cannot restore this window; only a new settlement checkpoint can.
        self.paused = False
        self.liquidity = False

    def pause(self):
        self.paused = True
        self.liquidity = False

    def publish_capacity(self, demand, valid_until):
        if self.nav_epoch == 0 or demand < 0 or not self.now <= valid_until <= self.now + 3600:
            raise ValueError('invalid capacity')
        self.demand, self.capacity_until = demand, valid_until

    def deposit_cap(self):
        if self.phase == 0:
            return self.hard_cap
        if self.now > self.capacity_until:
            return 0
        return min(self.hard_cap, self.demand * 10000 // self.target_bps)

    def max_deposit(self, owner):
        if not owner or (self.phase != 2 and owner not in self.whitelist):
            return 0
        if self.nav_epoch and not self.fresh():
            return 0
        if self.phase and (not self.fresh() or not self.liquidity):
            return 0
        if self.supply and not self.assets:
            return 0
        return max(0, self.deposit_cap() - self.assets)

    def deposit(self, owner, amount):
        if amount <= 0 or amount > self.max_deposit(owner):
            raise ValueError('deposit unavailable')
        shares = amount * (self.supply + VIRTUAL) // (self.assets + 1)
        if not shares:
            raise ValueError('zero shares')
        self.account_checkpoint(owner)
        if self.phase == 0:
            self.protocol.add(owner)
        self.cash += amount
        self.contributions += amount
        self.supply += shares
        self.shares[owner] += shares
        self.check()
        return shares

    def finalize(self, pnl, required, exposure, pause=True):
        """Successful settlement: cash movement, NAV checkpoint, then crystallization."""
        if required < exposure or exposure < 0 or self.assets + pnl < required:
            raise ValueError('unfunded settlement')
        self.checkpoint()  # before the underwriter cash movement
        self.cash += pnl
        self.pnl += pnl
        self.required, self.exposure = required, exposure
        self.nav_epoch += 1
        self.nav_at = self.now
        self.paused = bool(pause and exposure == 0)
        self.liquidity = self.paused
        if exposure == 0:
            supply = self.supply + VIRTUAL
            threshold = ceildiv(self.hwm_assets * supply, self.hwm_shares)
            gross = self.assets + 1
            if gross > threshold:
                if self.phase:
                    equity, capital = self.assets, required
                    bps = self.allocation_bps
                    if capital > equity // 2:
                        bps = 0
                    elif capital and capital > equity // 3:
                        bps = (bps * 2 * (equity - capital) // capital - bps) // 3
                    fee = min((gross - threshold) * bps // 10000,
                              max(0, equity - 2 * capital))
                    self.fee += fee
                    gross -= fee
                self.hwm_assets, self.hwm_shares = gross, supply
        self.check()

    def fund_reserve(self, amount):
        # Share-mode reserveAllowance; legacy protocol-only distribution is not
        # projected by this model (the recorded source is separately verified).
        if self.paused or not self.phase or amount <= 0 or amount > self.fee or self.required > self.assets // 2:
            raise ValueError('reserve authorization unavailable')
        self.checkpoint()
        self.fee -= amount
        self.cash -= amount
        self.reserve += amount
        self.check()

    def request_exit(self, owner, shares):
        if not self.phase or owner == 'vault' or not owner or shares <= 0 or shares > self.shares[owner] or owner in self.active_request:
            raise ValueError('invalid exit request')
        self.account_checkpoint(owner)
        self.shares[owner] -= shares
        self.shares['vault'] += shares
        self.exits.append(Exit(owner, shares, self.now + 2 * DAY, self.nav_epoch))
        request = len(self.exits)
        self.active_request[owner] = request
        self.check()
        return request

    def fulfill(self, request):
        if request != self.head + 1 or request > len(self.exits):
            raise ValueError('FIFO exit required')
        r = self.exits[request - 1]
        if (r.fulfilled or self.now < r.ready or self.nav_epoch <= r.epoch
                or self.nav_at < r.ready or not self.fresh() or not self.liquidity):
            raise ValueError('exit needs matured request and later fresh liquidity checkpoint')
        assets = r.shares * (self.assets + 1) // (self.supply + VIRTUAL)
        if assets > self.assets or self.required > (self.assets - assets) // 2:
            raise ValueError('exit would remove required capital')
        self.checkpoint()
        r.assets, r.fulfilled = assets, True
        self.head += 1
        self.shares['vault'] -= r.shares
        self.supply -= r.shares
        self.reserved += assets
        self.check()
        return assets

    def claim_exit(self, request, shares=None, assets=None):
        if not 1 <= request <= len(self.exits):
            raise ValueError('unknown exit')
        r = self.exits[request - 1]
        left_shares, left_assets = r.shares - r.claimed_shares, r.assets - r.claimed_assets
        if not r.fulfilled or (shares is not None and assets is not None):
            raise ValueError('invalid claim')
        if assets is not None:
            if not 0 < assets <= left_assets:
                raise ValueError('invalid asset claim')
            shares = left_shares if assets == left_assets else ceildiv((r.claimed_assets + assets) * r.shares, r.assets) - r.claimed_shares
        else:
            shares = left_shares if shares is None else shares
            if not 0 < shares <= left_shares:
                raise ValueError('invalid share claim')
            assets = (r.claimed_shares + shares) * r.assets // r.shares - r.claimed_assets
        r.claimed_shares += shares
        r.claimed_assets += assets
        self.reserved -= assets
        self.cash -= assets
        self.paid_exits += assets
        if r.claimed_shares == r.shares:
            del self.active_request[r.owner]
        self.check()
        return assets

    def integrate_liability(self, begin, end, exposure):
        if end < begin or exposure < 0:
            raise ValueError('invalid liability interval')
        t, stop = max(begin, self.start), min(end, self.start + 90 * DAY)
        while t < stop:
            epoch = (t - self.start) // DAY + 1
            until = min(stop, self.start + epoch * DAY)
            self.liability_seconds[epoch] += exposure * (until - t)
            t = until

    def publish(self, epoch):
        completed = self.start + epoch * DAY
        if self.paused or not 1 <= epoch <= 90 or epoch <= self.latest_epoch or not completed <= self.now < completed + DAY:
            raise ValueError('epoch publication window expired or invalid')
        self.checkpoint()
        capital, liability = self.capital_seconds[epoch], self.liability_seconds[epoch]
        if liability > capital:
            raise ValueError('liability-time exceeds capital-time')
        effective = min(capital, liability * 10000 // self.target_bps)
        budget = scheduled_budget(epoch) * effective // capital if capital else 0
        self.epochs[epoch] = (capital, budget)
        self.latest_epoch = epoch
        self.published += budget
        self.check()
        return budget

    def earned(self, epoch, owner):
        self.account_checkpoint(owner)
        capital, budget = self.epochs.get(epoch, (0, 0))
        return budget * self.eligible[epoch, owner] // capital if capital else 0

    def claim_reward(self, epoch, owner):
        if (epoch not in self.epochs or (epoch, owner) in self.claims
                or self.now < self.start + epoch * DAY + 30 * DAY):
            raise ValueError('reward unvested, unpublished or claimed')
        amount = self.earned(epoch, owner)
        if amount <= 0:
            raise ValueError('zero reward')
        self.claims.add((epoch, owner))
        self.claimed += amount
        self.token_balances[owner] += amount
        self.check()
        return amount

    def check(self):
        assert 0 <= self.fee + self.reserved <= self.cash
        assert self.cash == self.contributions + self.pnl - self.reserve - self.paid_exits
        assert self.supply == sum(self.shares.values())
        assert all(s >= 0 for s in self.shares.values())
        assert self.reserved == sum(r.assets - r.claimed_assets for r in self.exits if r.fulfilled)
        assert 0 <= self.claimed <= self.published <= BUDGET
        assert self.claimed == sum(self.token_balances.values())

    def snapshot(self):
        return dict(cash=self.cash, assets=self.assets, fee=self.fee, reserved=self.reserved,
                    reserve=self.reserve, supply=str(self.supply), pnl=self.pnl,
                    hwm_assets=self.hwm_assets, hwm_shares=str(self.hwm_shares),
                    published=str(self.published), claimed=str(self.claimed),
                    capital_seconds=str(self.capital_seconds[1]), index=str(self.index))
