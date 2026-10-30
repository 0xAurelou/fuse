"""Causal single-stream oracle replay for release-pricing rejection controls.

This is NOT paired native admission, a fitted model, funded LP accounting or
prospective certification. Every offered/rejected/censored grid row survives.
"""
from bisect import bisect_left
from collections import deque
from dataclasses import dataclass, asdict

DAY = 86_400_000
GRID = 30_000
USDC = 1_000_000
ASSETS = ('BTC', 'ETH', 'HYPE')
PAYOUTS = (2, 5, 10, 25, 50, 100, 250, 1000, 10000)
EDGES = (500, 700, 850, 1000)
DELAYS = (0, 250, 1000, 1999, 2000)
STRATEGIES = ('all_offered', 'prior30_flat', 'prior30_moving', 'prior30_jump_100ppm',
              'mark_gap_at_most_1bp', 'mark_gap_over_1bp',
              'last_matured_survived', 'last_matured_failed')
SPEC = dict(version='release-pricing-rejection-v1', assets=ASSETS, payouts=PAYOUTS,
    edge_bps=EDGES, acceptance_delays_ms=DELAYS, strategies=STRATEGIES,
    duration_ms=GRID, quote_ttl_ms=2000, max_gap_ms=8000, prior_jump_ppm=100,
    public_label_delay_after_expiry_ms=30000,
    calendar='All retained complete raw BTC days with corresponding full ETH/HYPE monthly '
             'raw coverage and provider-declared asset availability. Deduplicate dates before prices are read.',
    sources='Previously inspected third-party raw single-stream HyperCore oracle observations; '
            'not independent calendar holdouts, native paired receivers or actual trader demand.',
    order='Only receipts strictly before quote/acceptance enter their state. Same-time receipts '
          'are ordered after that action. No overnight interpolation or synthesized second receiver.',
    admission='Single-stream analogue: quote and acceptance must be fresh; any intervening '
              'oracle price change invalidates the quote even if price subsequently returns. '
              'Acceptance at the two-second deadline is rejected.',
    outcome='Fixed quote barriers, full thirty seconds beginning at acceptance; touches lose. '
            'Every later freshness/disconnect/coverage failure censors the whole outcome, '
            'even if an observed breach exists. This conservative rule is not native void adjudication.',
    public_history='Assume public access to every hypothetical accepted quote and its clean '
                   'oracle result only thirty seconds after expiry. History carries within each '
                   'complete day, resets between separately sampled days, and is never strategy-selected.',
    costs='0/10/50/100-bps illustrative expense charged on every accepted ticket, including censored tickets.',
    verdict='Historical formula rejection controls only. No candidate selection or production approval.')


class OracleTape:
    def __init__(self, observations, start, end, disconnects=()):
        """Observations are (receipt_ms, integer oracle price, optional mark price)."""
        if end <= start or (end-start) % GRID:
            raise ValueError('complete grid horizon required')
        self.start, self.end = start, end
        self.points = list(observations)
        self.times = [p[0] for p in self.points]
        if (not self.points or any(not start <= t < end for t in self.times) or
                self.times != sorted(self.times) or
                any(type(p[1]) is not int or p[1] <= 0 for p in self.points)):
            raise ValueError('invalid or unordered oracle observations')
        self.disconnects = list(disconnects)
        if any(b < a for a, b in self.disconnects):
            raise ValueError('regressing disconnect interval')
        self.changes = []
        count, previous = 0, None
        for _, price, _ in self.points:
            count += price != previous
            self.changes.append(count)
            previous = price

    def prior(self, at):
        return bisect_left(self.times, at)-1

    def disconnected(self, left, right, known_before=None):
        # Untimestamped transport breaks occupy a conservative interval between
        # their surrounding actual receipts. Never turn a future marker into
        # a pre-entry refusal.
        return any(a < right and b >= left and (known_before is None or b < known_before)
                   for a, b in self.disconnects)

    def context(self, at, index):
        if index < 0:
            return dict(prior_state='missing_history', mark_gap_ppm=None)
        _, entry, mark = self.points[index]
        mark_gap = abs(mark-entry)*1_000_000//entry if mark is not None else None
        j = self.prior(at-GRID)
        if j < 0 or at-GRID-self.times[j] > 8000 or self.disconnected(at-GRID, at, known_before=at):
            return dict(prior_state='missing_history', mark_gap_ppm=mark_gap)
        part = self.points[j:index+1]
        gaps = [b[0]-a[0] for a, b in zip(part, part[1:])]
        if (at-part[-1][0] > 8000 or (gaps and max(gaps) > 8000)):
            state = 'missing_history'
        else:
            jumps = [abs(b[1]-a[1])*1_000_000//a[1] for a, b in zip(part, part[1:])]
            state = ('jump' if jumps and max(jumps) >= 100 else
                     'flat' if self.changes[index] == self.changes[j] else 'moving')
        return dict(prior_state=state, mark_gap_ppm=mark_gap)

    def envelope(self, quote_at, delay):
        if delay not in DELAYS or not self.start <= quote_at < self.end:
            raise ValueError('undeclared delay or quote time')
        qi = self.prior(quote_at)
        accept = quote_at+delay
        expiry = accept+GRID
        ai = self.prior(accept)
        row = dict(quote_at=quote_at, accepted_at=accept, expiry=expiry,
                   entry=self.points[qi][1] if qi >= 0 else None,
                   quote_age_ms=quote_at-self.times[qi] if qi >= 0 else None,
                   quote_available=qi >= 0 and quote_at-self.times[qi] <= 8000,
                   accepted=False, reason='', valid=False, move=None,
                   observed_path_jump_100ppm=None, **self.context(quote_at, qi))
        if not row['quote_available']:
            row['reason'] = 'missing_or_stale_quote_oracle'
        elif delay >= 2000:
            row['reason'] = 'quote_expired'
        elif ai < 0 or accept-self.times[ai] > 8000:
            row['reason'] = 'stale_acceptance_oracle'
        elif self.changes[ai] != self.changes[qi]:
            row['reason'] = 'oracle_sequence_changed'
        else:
            row['accepted'] = True
        if not row['accepted']:
            return row
        if expiry > self.end:
            row['reason'] = 'right_censored_archive'
            return row
        stop = bisect_left(self.times, expiry)
        # Include the actual held price at acceptance and observations at
        # acceptance; observations exactly at expiry are excluded.
        part = self.points[ai:stop]
        prices = [p[1] for p in part]
        row['move'] = max(abs(min(prices)-row['entry']), abs(max(prices)-row['entry']))
        gaps = [b[0]-a[0] for a, b in zip(part, part[1:])]
        worst_gap = max([accept-part[0][0], expiry-part[-1][0]]+gaps)
        jumps = [abs(b[1]-a[1])*1_000_000//a[1] for a, b in zip(part, part[1:])]
        row['observed_path_jump_100ppm'] = bool(jumps and max(jumps) >= 100)
        row['valid'] = worst_gap <= 8000 and not self.disconnected(accept, expiry)
        if not row['valid']:
            row['reason'] = 'censored_gap_or_disconnect'
        return row


def selected(strategy, row, last):
    if strategy not in STRATEGIES:
        raise ValueError('undeclared strategy')
    if not row['quote_available']:
        return False
    state, gap = row['prior_state'], row['mark_gap_ppm']
    return {'all_offered': True, 'prior30_flat': state == 'flat',
            'prior30_moving': state in ('moving', 'jump'),
            'prior30_jump_100ppm': state == 'jump',
            'mark_gap_at_most_1bp': gap is not None and gap <= 100,
            'mark_gap_over_1bp': gap is not None and gap > 100,
            'last_matured_survived': last is True,
            'last_matured_failed': last is False}[strategy]


@dataclass
class Counts:
    grid: int = 0
    quote_available: int = 0
    intended: int = 0
    accepted: int = 0
    rejected: int = 0
    resolved: int = 0
    wins: int = 0
    censored: int = 0

    def add(self, row, choose, outcome):
        self.grid += 1
        self.quote_available += row['quote_available']
        self.intended += choose
        if not choose:
            return
        self.accepted += row['accepted']
        self.rejected += not row['accepted']
        if row['accepted']:
            self.censored += outcome is None
            self.resolved += outcome is not None
            self.wins += outcome is True

    def merge(self, other):
        for k in self.__dataclass_fields__:
            setattr(self, k, getattr(self, k)+getattr(other, k))

    def result(self, multiplier, edge):
        n, w, c = self.resolved, self.wins, self.censored
        if (n+c != self.accepted or self.intended != self.accepted+self.rejected or
                not 0 <= w <= n):
            raise AssertionError('ticket accounting mismatch')
        gross = (n-multiplier*w)*USDC
        lower, upper = gross-(multiplier-1)*c*USDC, gross+c*USDC
        return dict(asdict(self), survival=w/n if n else None,
            target_survival=(10_000-edge)/(10_000*multiplier),
            gross_lp_refund_usdc_units=gross, gross_player_refund_usdc_units=-gross,
            gross_lp_if_censored_all_win_usdc_units=lower,
            gross_lp_if_censored_all_fail_usdc_units=upper,
            quoted_target_expected_wins=n*(10_000-edge)/(10_000*multiplier),
            costs=[dict(expense_bps=bps, expense_usdc_units=self.accepted*USDC*bps//10_000,
                        net_lp_refund_usdc_units=gross-self.accepted*USDC*bps//10_000,
                        net_lp_lower_usdc_units=lower-self.accepted*USDC*bps//10_000,
                        net_lp_upper_usdc_units=upper-self.accepted*USDC*bps//10_000)
                   for bps in (0, 10, 50, 100)])


def replay(envelopes, width_ppb, multiplier, edge):
    """Return every predeclared strategy and one byte per grid portfolio leg.

    Codes: 0 rejected/no quote, 1 accepted censored, 2 resolved loss, 3 win.
    Public history uses all hypothetical accepted quotes, never chosen trades.
    """
    counts = {s: Counts() for s in STRATEGIES}
    strata = {}
    pending = deque()
    last = None
    states = bytearray()
    for row in envelopes:
        while pending and pending[0][0] <= row['quote_at']:
            _, last = pending.popleft()
        delta = row['entry']*width_ppb//10**9 if row['entry'] is not None else 0
        actual = row if delta > 0 else dict(row, quote_available=False, accepted=False,
                                           reason='unrepresentable_integer_barrier')
        outcome = (actual['move'] < delta if actual['accepted'] and actual['valid'] else None)
        code = (3 if outcome else 2) if outcome is not None else 1 if actual['accepted'] else 0
        states.append(code)
        for strategy, count in counts.items():
            count.add(actual, selected(strategy, actual, last), outcome)
        # Report future path jumps only as ex-post strata, never an entry signal.
        for axis, group in (('prior_state', actual['prior_state']),
                            ('quote_age', 'missing' if actual['quote_age_ms'] is None else
                             'at_most_1s' if actual['quote_age_ms'] <= 1000 else
                             '1_to_8s' if actual['quote_age_ms'] <= 8000 else 'over_8s'),
                            ('observed_jump', 'unknown' if actual['observed_path_jump_100ppm'] is None else
                             'jump' if actual['observed_path_jump_100ppm'] else 'no_jump')):
            strata.setdefault((axis, group), Counts()).add(actual, selected('all_offered', actual, last), outcome)
        if actual['accepted'] and outcome is not None:
            pending.append((actual['expiry']+30_000, outcome))
    return counts, strata, states


def joint(states, multiplier):
    """Real contemporaneous paths; no independent-outcome resampling."""
    if len(states) != 3 or len({len(s) for s in states}) != 1:
        raise ValueError('three complete aligned asset grids required')
    patterns = [0]*4
    coaccepted = coresolved = 0
    pairs = {f'{ASSETS[a]}:{ASSETS[b]}': [0, 0, 0, 0] for a, b in ((0, 1), (0, 2), (1, 2))}
    accepted = resolved = wins = censored = 0
    for row in zip(*states):
        accepted += sum(s > 0 for s in row)
        resolved += sum(s >= 2 for s in row)
        wins += sum(s == 3 for s in row)
        censored += sum(s == 1 for s in row)
        coaccepted += all(s > 0 for s in row)
        if all(s >= 2 for s in row):
            coresolved += 1
            patterns[sum(s == 3 for s in row)] += 1
        for a, b in ((0, 1), (0, 2), (1, 2)):
            if row[a] >= 2 and row[b] >= 2:
                pair = pairs[f'{ASSETS[a]}:{ASSETS[b]}']
                pair[0] += 1
                pair[1] += row[a] == 3
                pair[2] += row[b] == 3
                pair[3] += row[a] == 3 and row[b] == 3
    gross = (resolved-multiplier*wins)*USDC
    return dict(grid=len(states[0]), coaccepted=coaccepted, coresolved=coresolved,
        clean_coaccepted_win_count_histogram=patterns, paired_resolved_counts=pairs,
        accepted_tickets=accepted, resolved_tickets=resolved, censored_tickets=censored,
        trader_wins=wins, gross_lp_refund_usdc_units=gross,
        gross_lp_lower_usdc_units=gross-(multiplier-1)*censored*USDC,
        gross_lp_upper_usdc_units=gross+censored*USDC,
        one_wallet_per_asset_net_maximum_obligation_usdc_units=3*(multiplier-1)*USDC,
        three_wallets_per_asset=dict(accepted_tickets=accepted*3, trader_wins=wins*3,
            gross_lp_refund_usdc_units=gross*3,
            net_maximum_obligation_usdc_units=9*(multiplier-1)*USDC),
        shared_paths_independent=False, funded_admission_evaluated=False)
