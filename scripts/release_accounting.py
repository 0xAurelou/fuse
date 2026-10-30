#!/usr/bin/env python3
"""Executable candidate for RELEASE_ECONOMIC_SPEC.md, NOT a production adapter.

Integer USDC; fully custody-funded single-stage stakes only. Daily UTC closes.
Withdrawals retain each capital account's own PnL/mark until it fully exits;
every new contribution creates a new account. Calls are serial,
with separate canonical outcome and observation times and an assumed authenticated
close watermark. Safe cash releases do not wait for an overdue close. No signatures,
persistence, liability-backed stakes, reward
guarantees or oracle verification are implemented here. Keep old experiment
models intact.
"""
from dataclasses import dataclass

DAY = 86_400_000
PAYOUTS = (2, 5, 10, 25, 50, 100, 250, 1000, 10000)


def integer(value, minimum=0):
    if type(value) is not int or value < minimum:
        raise ValueError('invalid integer amount/time')
    return value


def day_start(at):
    integer(at)
    return at // DAY * DAY


def apportion(amount, weights):
    """Signed integer largest remainders, stable integer lot-ID tie order."""
    integer(abs(amount))
    if any(type(k) is not int or type(w) is not int or w < 0 for k, w in weights.items()):
        raise ValueError('invalid allocation weights')
    total = sum(weights.values())
    if amount and not total:
        raise ValueError('no positive allocation weights')
    if not total:
        return {k: 0 for k in weights}
    sign = -1 if amount < 0 else 1
    units = abs(amount)
    result = {k: units * w // total for k, w in weights.items()}
    order = sorted(weights, key=lambda k: (-(units * weights[k] % total), k))
    for key in order[:units - sum(result.values())]:
        result[key] += 1
    return {k: sign * n for k, n in result.items()}


@dataclass(frozen=True)
class Limits:
    per_bet: int
    per_market: dict
    total: int
    admission_buffer: int
    distribution_buffer: int
    backing_buffer: int

    def __post_init__(self):
        for n in (self.per_bet, self.total, *self.per_market.values()):
            integer(n, 1)
        for n in (self.admission_buffer, self.distribution_buffer, self.backing_buffer):
            integer(n)
        if (not self.per_market or self.per_bet > self.total or
                not self.admission_buffer <= self.distribution_buffer <= self.backing_buffer):
            raise ValueError('invalid capital limits/buffers')


@dataclass
class Lot:
    owner: str
    equity: int
    pnl: int = 0
    mark: int = 0
    exit_day: int = -1


@dataclass
class Bet:
    asset: str
    start: int
    expiry: int
    stake: int
    payout: int
    underwriters: dict
    status: str = 'open'
    cash_due: int = 0
    final_void_at: int = 0


class Ledger:
    def __init__(self, start, limits):
        if day_start(start) != start:
            raise ValueError('start must be 00:00 UTC')
        self.start = self.clock = start
        self.limits = limits
        self.day = 0
        self.paused = True
        self.flow_at = start  # bootstrap; thereafter only an actual daily close
        self.cash = self.loss_receivable = self.win_payable = 0
        self.operator_due = self.backing_due = 0
        self.contributed = self.exited = self.realized = 0
        self.fees = self.backing = self.operator_paid = self.backing_paid = 0
        self.next_lot = 1
        self.lots = {}
        self.archived = {}
        self.bets = {}
        self.closes = []

    @property
    def cutoff(self):
        return self.start + (self.day + 1) * DAY

    @property
    def available_cash(self):
        return self.cash - self.operator_due - self.backing_due

    @property
    def open_exposure(self):
        return sum(b.payout - b.stake for b in self.bets.values() if b.status == 'open')

    def market_exposure(self, asset):
        return sum((b.payout - b.stake if b.status == 'open' else b.cash_due)
                   for b in self.bets.values() if b.asset == asset and b.status != 'loss')

    def lot_exposure(self, lot):
        return sum(b.underwriters.get(lot, 0) for b in self.bets.values() if b.status == 'open')

    def max_withdrawal(self, lot):
        item = self.lots[lot]
        unclosed_profit = max(0, item.pnl - item.mark)
        own_room = item.equity - self.lot_exposure(lot) - unclosed_profit
        # Future admission headroom is not an obligation owed by an LP.
        # A withdrawal may leave too little cash for *new* bets; acceptance
        # must then reject them. Existing bets, wins and close liabilities
        # stay fully funded, even when trading or the daily close is paused.
        cash_room = self.available_cash - self.win_payable - self.open_exposure
        return max(0, min(own_room, cash_room))

    def _time(self, at, require_close=True):
        integer(at)
        if at < self.clock or (require_close and at >= self.cutoff):
            raise ValueError('out-of-order event or daily close required')

    def _flow(self, at):
        self._time(at)
        if (not self.paused or self.flow_at is None or self.open_exposure or
                self.loss_receivable or self.win_payable):
            raise ValueError('LP deposits require paused reconciled daily window')

    def deposit(self, owner, amount, at):
        integer(amount, 1)
        self._flow(at)
        if not owner:
            raise ValueError('owner required')
        key = self.next_lot
        self.next_lot += 1
        self.lots[key] = Lot(owner, amount)
        self.cash += amount
        self.contributed += amount
        self.clock = at
        self.check()
        return key

    def request_exit(self, lot, at):
        self._time(at, require_close=False)
        item = self.lots[lot]
        if item.exit_day >= 0:
            raise ValueError('exit already requested')
        item.exit_day = self.day
        self.clock = at

    def cancel_exit(self, lot, at):
        self._time(at, require_close=False)
        self.lots[lot].exit_day = -1
        self.clock = at

    def execute_exit(self, lot, at):
        self._time(at, require_close=False)
        item = self.lots[lot]
        if item.exit_day < 0:
            raise ValueError('exit not requested')
        if item.equity == 0 and self.lot_exposure(lot) == 0:
            self.archived[lot] = self.lots.pop(lot)
            self.clock = at
            self.check()
            return 0
        return self.withdraw(lot, item.equity, at)

    def withdraw(self, lot, amount, at):
        self._time(at, require_close=False)
        integer(amount, 1)
        item = self.lots[lot]
        if amount > self.max_withdrawal(lot):
            raise ValueError('withdrawal exceeds free capital after obligations and unclosed profit')
        self.cash -= amount
        self.exited += amount
        item.equity -= amount
        if item.equity == 0:
            self.archived[lot] = self.lots.pop(lot)
        self.clock = at
        self.check()
        return amount

    def accept(self, key, asset, stake, multiplier, at):
        self._time(at)
        integer(stake, 1)
        if (self.paused or key in self.bets or multiplier not in PAYOUTS or
                asset not in self.limits.per_market):
            raise ValueError('paused, duplicate bet, unsupported market or payout')
        liability = stake * (multiplier - 1)
        exposure = self.open_exposure + self.win_payable + liability
        if (liability > self.limits.per_bet or exposure > self.limits.total or
                self.market_exposure(asset) + liability > self.limits.per_market[asset] or
                self.available_cash < exposure + self.limits.admission_buffer):
            raise ValueError('bet exceeds funded liability/capital limit')
        capacity = {k: l.equity - self.lot_exposure(k)
                    for k, l in self.lots.items() if l.exit_day < 0}
        if sum(capacity.values()) < liability:
            raise ValueError('insufficient available underwriting accounts')
        assigned = {k: n for k, n in apportion(liability, capacity).items() if n}
        self.bets[key] = Bet(asset, at, at + 30_000, stake, stake * multiplier, assigned)
        self.clock = at
        self.flow_at = None
        self.check()

    def resolve(self, key, outcome, at, observed_at=None):
        integer(at)
        observed_at = at if observed_at is None else observed_at
        self._time(observed_at, require_close=False)
        bet = self.bets[key]
        if (bet.status != 'open' or outcome not in ('win', 'loss', 'void') or
                at < bet.start or at > observed_at or
                not self.start + self.day * DAY <= at < self.cutoff or
                (outcome == 'win' and at != bet.expiry) or
                (outcome == 'loss' and at >= bet.expiry) or
                (outcome == 'void' and at < bet.expiry) or
                (bet.final_void_at and (outcome != 'void' or at != bet.final_void_at))):
            raise ValueError('invalid, early or duplicate outcome')
        pnl = bet.stake - bet.payout if outcome == 'win' else bet.stake if outcome == 'loss' else 0
        # Retain the underwriting owners captured at acceptance through runoff.
        split = apportion(pnl, bet.underwriters)
        if any(self.lots[k].equity + n < 0 for k, n in split.items()):
            raise ValueError('unfunded outcome')
        for lot, n in split.items():
            self.lots[lot].equity += n
            self.lots[lot].pnl += n
        bet.status = outcome
        bet.cash_due = abs(pnl)
        self.realized += pnl
        self.win_payable += -pnl if pnl < 0 else 0
        self.loss_receivable += pnl if pnl > 0 else 0
        self.clock = observed_at
        self.flow_at = None
        self.check()

    def queue_final_void(self, key, at, observed_at=None):
        """Authenticated final determination; keep original risk through cutoff.

        Close completeness can use this proof without backdating the outcome.
        Only the canonical day may release the still-funded bet reservation.
        """
        integer(at)
        observed_at = at if observed_at is None else observed_at
        self._time(observed_at, require_close=False)
        bet = self.bets[key]
        if (bet.status != 'open' or bet.final_void_at or at < bet.expiry or
                at < self.cutoff or at > observed_at):
            raise ValueError('invalid final void proof')
        bet.final_void_at = at
        self.clock = observed_at
        self.flow_at = None
        self.check()

    def settle_cash(self, key, at):
        self._time(at, require_close=False)
        bet = self.bets[key]
        if bet.status not in ('win', 'loss') or bet.cash_due <= 0:
            raise ValueError('no unsettled outcome cash')
        n = bet.cash_due
        if bet.status == 'win':
            if n > self.available_cash:
                raise ValueError('win cannot consume fee/backing reservations')
            self.cash -= n
            self.win_payable -= n
        else:
            self.cash += n
            self.loss_receivable -= n
        bet.cash_due = 0
        self.clock = at
        self.flow_at = None
        self.check()

    def close(self, at, oracle_watermark, allowance, pending_credit, standard_need_30d, observed_at=None):
        """Assume authenticated watermark; no quote edge enters this API.

        An unresolved expiry exactly at cutoff belongs to the new day.
        Thirty-day demand is caller supplied and MUST include unrewarded bets.
        """
        for n in (at, oracle_watermark, allowance, pending_credit, standard_need_30d):
            integer(n)
        observed_at = max(at, self.clock) if observed_at is None else observed_at
        self._time(observed_at, require_close=False)
        if (at != self.cutoff or oracle_watermark < at or
                observed_at < at or
                any(b.status == 'open' and b.expiry < at and b.final_void_at < at
                    for b in self.bets.values())):
            raise ValueError('invalid close time or incomplete canonical outcomes')
        eligible = {k: max(0, l.pnl - l.mark) for k, l in self.lots.items()}
        new_profit = sum(eligible.values())
        charge_capacity = {k: min(n, self.lots[k].equity - self.lot_exposure(k))
                           for k, n in eligible.items()}
        room = max(0, self.available_cash - self.win_payable - self.open_exposure
                   - self.limits.distribution_buffer)
        distributable = min(sum(charge_capacity.values()), room)
        fee = distributable * 500 // 10_000
        target = (standard_need_30d * 60 + 29) // 30
        gap = max(0, target - allowance - pending_credit)
        needed = (gap * 10_000 + 8999) // 9000
        backing_room = max(0, self.available_cash - self.win_payable - self.open_exposure
                           - fee - self.limits.backing_buffer)
        backing = min(distributable - fee, needed, backing_room)
        consumed = apportion(distributable, charge_capacity)
        charges = apportion(fee + backing, consumed)
        if any(self.lots[k].equity < n for k, n in charges.items()):
            raise ValueError('invalid LP lot charge')
        row = dict(day=self.day, start=self.start + self.day * DAY, end=at,
                   eligible=new_profit, distributable=distributable, fee=fee,
                   backing=backing, retained=distributable-fee-backing,
                   protected_pending=new_profit-distributable, consumed=consumed,
                   loss_carried=sum(max(0, l.mark-l.pnl) for l in self.lots.values()),
                   open_exposure=self.open_exposure, unfunded_wins=self.win_payable,
                   target=target, charges=charges, transfers_paid=False)
        for k, lot in self.lots.items():
            lot.equity -= charges[k]
            # Only the base actually processed by this daily allocation is
            # consumed. Temporary exposure cannot forgive protected profit.
            lot.mark += consumed[k]
        self.operator_due += fee
        self.backing_due += backing
        self.fees += fee
        self.backing += backing
        self.closes.append(row)
        self.clock = observed_at
        self.flow_at = observed_at
        self.day += 1
        self.check()
        return dict(row)

    def pay_close(self, day, at):
        """Reference atomic payment; real adapters need close-bound replay IDs."""
        self._time(at, require_close=False)
        integer(day)
        row = self.closes[day]
        if row['transfers_paid']:
            raise ValueError('close already paid')
        self.cash -= row['fee'] + row['backing']
        self.operator_due -= row['fee']
        self.backing_due -= row['backing']
        self.operator_paid += row['fee']
        self.backing_paid += row['backing']
        row['transfers_paid'] = True
        self.clock = at
        self.check()
        return row['fee'], row['backing']

    def check(self):
        equity = sum(l.equity for l in self.lots.values())
        assert equity == self.available_cash + self.loss_receivable - self.win_payable
        assert equity + self.fees + self.backing + self.exited == self.contributed + self.realized
        assert self.operator_due == self.fees - self.operator_paid
        assert self.backing_due == self.backing - self.backing_paid
        assert self.win_payable == sum(b.cash_due for b in self.bets.values() if b.status == 'win')
        assert self.loss_receivable == sum(b.cash_due for b in self.bets.values() if b.status == 'loss')
        assert min(self.cash, self.available_cash, self.win_payable, self.loss_receivable,
                   self.operator_due, self.backing_due, *(l.equity for l in self.lots.values())) >= 0
        # Every known win and every possible simultaneous open win remains funded.
        assert self.available_cash >= self.win_payable + self.open_exposure
        assert all(l.equity >= self.lot_exposure(k) for k, l in self.lots.items())
