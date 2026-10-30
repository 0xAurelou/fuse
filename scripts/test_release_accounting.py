import copy
from datetime import datetime, timezone
import random
import unittest

from release_accounting import DAY, PAYOUTS, Ledger, Limits, apportion, day_start


START = int(datetime(2026, 10, 26, tzinfo=timezone.utc).timestamp() * 1000)


def limits(**kw):
    values = dict(per_bet=1_000_000, per_market={a: 10_000_000 for a in ('BTC', 'ETH', 'HYPE')},
                  total=10_000_000, admission_buffer=0, distribution_buffer=0, backing_buffer=0)
    values.update(kw)
    return Limits(**values)


class ReleaseAccountingTests(unittest.TestCase):
    def ledger(self, capital=100_000, policy=None):
        ledger = Ledger(START, policy or limits())
        key = ledger.deposit('original', capital, START)
        ledger.paused = False
        return ledger, key

    def trade(self, ledger, pnl, cash=True):
        at = ledger.clock + 1
        key = 'bet-' + str(len(ledger.bets))
        ledger.accept(key, 'BTC', abs(pnl), 2, at)
        ledger.resolve(key, 'loss' if pnl > 0 else 'win', at + (29_999 if pnl > 0 else 30_000),
                       observed_at=at+30_000)
        if cash:
            ledger.settle_cash(key, at + 30_001)
        return key

    def close(self, ledger, **kw):
        args = dict(at=ledger.cutoff, oracle_watermark=ledger.cutoff, allowance=0,
                    pending_credit=0, standard_need_30d=0)
        args.update(kw)
        return ledger.close(**args)

    def test_daily_utc_calendar_not_restart_relative(self):
        self.assertEqual(day_start(START), START)
        self.assertEqual(day_start(START + DAY - 1), START)
        self.assertEqual(day_start(START + DAY), START + DAY)
        with self.assertRaisesRegex(ValueError, '00:00 UTC'):
            Ledger(START + 1, limits())

    def test_cutoff_event_requires_prior_close(self):
        ledger, _ = self.ledger()
        with self.assertRaisesRegex(ValueError, 'close required'):
            ledger.accept('next-day', 'BTC', 10, 2, ledger.cutoff)
        end = ledger.cutoff
        self.close(ledger)
        ledger.accept('next-day', 'BTC', 10, 2, end)

    def test_close_exactly_once_no_calendar_or_replay_reset(self):
        ledger, _ = self.ledger()
        old = ledger.cutoff
        self.close(ledger)
        with self.assertRaises(ValueError):
            self.close(ledger, at=old)
        with self.assertRaises(ValueError):
            self.close(ledger, at=ledger.cutoff + 1)

    def test_intraday_gains_and_losses_net_before_fee(self):
        ledger, _ = self.ledger()
        for pnl in (10_000, -12_000, 2_000):
            self.trade(ledger, pnl)
            self.assertEqual(ledger.fees, 0)
        self.assertEqual(self.close(ledger)['fee'], 0)

    def test_loss_recovery_survives_days_and_paid_fees_are_final(self):
        ledger, _ = self.ledger()
        rows = []
        for pnl in (-1000, 800, 500, -300, 300, 100):
            self.trade(ledger, pnl)
            rows.append(self.close(ledger))
        self.assertEqual([r['fee'] for r in rows], [0, 0, 15, 0, 0, 5])
        self.assertEqual([r['loss_carried'] for r in rows[:3]], [1000, 200, 0])

    def test_unwithdrawn_unfunded_win_reduces_profit_before_close(self):
        ledger, lot = self.ledger()
        self.trade(ledger, 2000)
        self.trade(ledger, -1000, cash=False)
        self.assertEqual(ledger.win_payable, 1000)
        self.assertEqual(ledger.lots[lot].pnl, 1000)
        self.assertEqual(self.close(ledger)['fee'], 50)

    def test_uncollected_profit_waits_for_cash_then_is_charged_once(self):
        ledger, _ = self.ledger(5000, limits(distribution_buffer=5000, backing_buffer=5000))
        key = self.trade(ledger, 1000, cash=False)
        self.assertEqual(self.close(ledger)['fee'], 0)
        ledger.settle_cash(key, ledger.clock + 1)
        self.assertEqual(self.close(ledger)['fee'], 50)
        self.assertEqual(self.close(ledger)['fee'], 0)

    def test_spanning_bet_is_reserved_then_recognized_in_new_day(self):
        ledger, _ = self.ledger()
        end = ledger.cutoff
        ledger.accept('span', 'ETH', 1000, 5, end - 10_000)
        row = self.close(ledger)
        self.assertEqual((row['eligible'], row['open_exposure']), (0, 4000))
        ledger.resolve('span', 'win', end + 20_000)
        self.assertEqual(ledger.open_exposure, 0)
        self.assertEqual(ledger.win_payable, 4000)
        self.assertEqual(self.close(ledger)['loss_carried'], 4000)

    def test_expiry_exactly_on_cutoff_belongs_to_next_day(self):
        ledger, _ = self.ledger()
        end = ledger.cutoff
        ledger.accept('edge', 'BTC', 1000, 2, end - 30_000)
        self.close(ledger)
        ledger.resolve('edge', 'win', end)
        self.assertEqual(self.close(ledger)['loss_carried'], 1000)

    def test_missing_preboundary_outcome_or_watermark_blocks_final_close(self):
        ledger, _ = self.ledger()
        ledger.accept('missing', 'BTC', 100, 2, START + 1)
        with self.assertRaisesRegex(ValueError, 'incomplete'):
            self.close(ledger)
        ledger.resolve('missing', 'void', START + 31_000)
        with self.assertRaisesRegex(ValueError, 'incomplete'):
            self.close(ledger, oracle_watermark=ledger.cutoff - 1)
        self.assertEqual(self.close(ledger)['fee'], 0)

    def test_new_lot_does_not_receive_old_loss_carryforward(self):
        ledger, old = self.ledger(2000)
        self.trade(ledger, -1000)
        self.close(ledger)
        ledger.paused = True
        new = ledger.deposit('newcomer', 2000, ledger.clock)
        ledger.paused = False
        self.trade(ledger, 1500)
        self.assertEqual((ledger.lots[old].pnl, ledger.lots[new].pnl), (-500, 1000))
        row = self.close(ledger)
        self.assertEqual((row['eligible'], row['fee'], row['loss_carried']), (1000, 50, 500))
        self.assertEqual(row['charges'][old], 0)
        self.assertEqual(row['charges'][new], 50)

    def test_deposit_does_not_reset_mark_or_create_profit(self):
        ledger, old = self.ledger()
        self.trade(ledger, 1000)
        self.close(ledger)
        ledger.paused = True
        ledger.deposit('original', 1000, ledger.clock)
        self.assertEqual((ledger.lots[old].pnl, ledger.lots[old].mark), (1000, 1000))
        self.assertEqual(self.close(ledger)['fee'], 0)

    def test_closed_window_or_open_risk_or_unfunded_flows_fail(self):
        ledger, _ = self.ledger()
        self.trade(ledger, 100)
        ledger.paused = True
        with self.assertRaises(ValueError):
            ledger.deposit('new', 100, ledger.clock + 1)
        ledger.paused = False
        end = ledger.cutoff
        ledger.accept('span', 'BTC', 100, 2, end - 10_000)
        self.close(ledger)
        ledger.paused = True
        with self.assertRaises(ValueError):
            ledger.deposit('new', 100, end)

    def test_newday_resolution_does_not_reopen_old_flow_window(self):
        ledger, _ = self.ledger()
        end = ledger.cutoff
        ledger.accept('span', 'BTC', 100, 2, end - 30_000)
        self.close(ledger)
        ledger.resolve('span', 'void', end)
        ledger.paused = True
        with self.assertRaises(ValueError):
            ledger.deposit('new', 100, end)

    def test_exit_request_cannot_escape_daily_fee(self):
        ledger, lot = self.ledger()
        ledger.accept('before-exit', 'BTC', 1000, 2, START + 1)
        ledger.request_exit(lot, START + 2)
        ledger.resolve('before-exit', 'loss', START + 30_000, observed_at=START+30_001)
        ledger.settle_cash('before-exit', START + 30_002)
        ledger.paused = True
        with self.assertRaises(ValueError):
            ledger.execute_exit(lot, ledger.clock)
        self.close(ledger)
        amount = ledger.execute_exit(lot, ledger.clock)
        self.assertEqual(amount, 100_950)
        self.assertEqual((ledger.operator_due, ledger.available_cash), (50, 0))
        self.assertIn(lot, ledger.archived)

    def test_exit_stays_exposed_to_losses_and_cancel_preserves_marks(self):
        ledger, lot = self.ledger()
        ledger.accept('before-exit', 'BTC', 1000, 2, START + 1)
        ledger.request_exit(lot, START + 2)
        ledger.resolve('before-exit', 'win', START + 30_001)
        ledger.settle_cash('before-exit', START + 30_002)
        ledger.cancel_exit(lot, ledger.clock)
        self.close(ledger)
        self.assertEqual((ledger.lots[lot].pnl, ledger.lots[lot].mark), (-1000, 0))

    def test_aggregate_fee_rounding_not_per_wallet(self):
        ledger = Ledger(START, limits())
        for i in range(20):
            ledger.deposit(str(i), 100, START)
        ledger.paused = False
        self.trade(ledger, 20)
        row = self.close(ledger)
        self.assertEqual(row['fee'], 1)  # Twenty separate one-unit profits still pay one.
        self.assertEqual(sum(row['charges'].values()), 1)

    def test_capital_protected_profit_waits_then_charges_only_original_account(self):
        ledger, original = self.ledger(1000, limits(distribution_buffer=1500, backing_buffer=1500))
        self.trade(ledger, 1000)
        row = self.close(ledger)
        self.assertEqual((row['eligible'], row['distributable'], row['fee']), (1000, 500, 25))
        ledger.paused = True
        newcomer = ledger.deposit('new', 100_000, ledger.clock)
        row = self.close(ledger)
        self.assertEqual(row['fee'], 25)
        self.assertEqual((row['charges'][original], row['charges'][newcomer]), (25, 0))
        self.assertEqual(self.close(ledger)['fee'], 0)

    def test_five_percent_before_dynamic_backing_and_pending_credit(self):
        ledger, _ = self.ledger()
        self.trade(ledger, 1000)
        row = self.close(ledger, standard_need_30d=270)
        self.assertEqual((row['fee'], row['target'], row['backing'], row['retained']), (50, 540, 600, 350))
        self.trade(ledger, 1000)
        row = self.close(ledger, pending_credit=540, standard_need_30d=270)
        self.assertEqual((row['fee'], row['backing']), (50, 0))

    def test_high_backing_buffer_retains_remainder(self):
        ledger, _ = self.ledger(1000, limits(backing_buffer=2000))
        self.trade(ledger, 1000)
        row = self.close(ledger, standard_need_30d=1000)
        self.assertEqual((row['fee'], row['backing'], row['retained']), (50, 0, 950))

    def test_fee_and_backing_reservations_reduce_cash_before_actual_transfer(self):
        ledger, _ = self.ledger()
        self.trade(ledger, 1000)
        self.close(ledger, standard_need_30d=270)
        cash = ledger.cash
        self.assertEqual(ledger.available_cash, cash - 650)
        ledger.pay_close(0, ledger.clock)
        self.assertEqual((ledger.cash, ledger.available_cash), (cash - 650, cash - 650))
        with self.assertRaisesRegex(ValueError, 'already paid'):
            ledger.pay_close(0, ledger.clock)

    def test_exact_liability_limit_and_first_rejected_increment(self):
        ledger, _ = self.ledger(1000)
        ledger.accept('last', 'BTC', 1000, 2, START + 1)
        before = copy.deepcopy(vars(ledger))
        with self.assertRaises(ValueError):
            ledger.accept('excess', 'ETH', 1, 2, START + 2)
        self.assertEqual(vars(ledger), before)

    def test_per_bet_market_and_total_limits_are_distinct(self):
        policies = (limits(per_bet=99),
                    limits(per_market={'BTC': 99}),
                    limits(per_bet=99, total=99))
        for policy in policies:
            ledger, _ = self.ledger(policy=policy)
            with self.assertRaises(ValueError):
                ledger.accept('too-big', 'BTC', 100, 2, START + 1)

    def test_recognized_win_still_counts_against_market_cap(self):
        ledger, _ = self.ledger(policy=limits(per_market={'BTC': 1000}))
        ledger.accept('win', 'BTC', 1000, 2, START + 1)
        ledger.resolve('win', 'win', START + 30_001)
        self.assertEqual(ledger.market_exposure('BTC'), 1000)
        with self.assertRaises(ValueError):
            ledger.accept('excess', 'BTC', 1, 2, START + 30_002)
        ledger.settle_cash('win', START + 30_002)
        self.assertEqual(ledger.market_exposure('BTC'), 0)
        ledger.accept('next', 'BTC', 1, 2, START + 30_003)

    def test_pending_losses_are_not_underwriting_cash(self):
        ledger, _ = self.ledger(1000)
        self.trade(ledger, 1000, cash=False)
        with self.assertRaises(ValueError):
            ledger.accept('unfunded', 'BTC', 1001, 2, ledger.clock + 1)

    def test_every_payout_and_market_can_win_simultaneously_without_netting(self):
        ledger, _ = self.ledger(1_000_000)
        total = 0
        for asset in ('BTC', 'ETH', 'HYPE'):
            for multiplier in PAYOUTS:
                key = asset + '-' + str(multiplier)
                ledger.accept(key, asset, 1, multiplier, START + 1)
                total += multiplier - 1
        self.assertEqual(ledger.open_exposure, total)
        for key in ledger.bets:
            ledger.resolve(key, 'win', START + 30_001)
        self.assertEqual((ledger.open_exposure, ledger.win_payable), (0, total))
        for key in ledger.bets:
            ledger.settle_cash(key, START + 30_002)
        self.assertEqual((ledger.cash, ledger.win_payable), (1_000_000 - total, 0))

    def test_void_duplicate_outcome_and_cash_replay(self):
        ledger, _ = self.ledger()
        ledger.accept('void', 'BTC', 1, 10000, START + 1)
        ledger.resolve('void', 'void', START + 30_001)
        self.assertEqual((ledger.open_exposure, ledger.realized), (0, 0))
        with self.assertRaises(ValueError):
            ledger.resolve('void', 'loss', START + 30_002)
        with self.assertRaises(ValueError):
            ledger.settle_cash('void', START + 30_002)

    def test_out_of_order_and_early_win_cannot_mutate_balances(self):
        ledger, _ = self.ledger()
        ledger.accept('early', 'BTC', 100, 2, START + 1)
        before = copy.deepcopy(vars(ledger))
        for at in (START, START + 2):
            with self.assertRaises(ValueError):
                ledger.resolve('early', 'win', at)
        self.assertEqual(vars(ledger), before)

    def test_randomized_daily_pnl_flows_and_conservation(self):
        rng = random.Random(20261030)
        ledger, _ = self.ledger()
        for day in range(60):
            for _ in range(10):
                self.trade(ledger, rng.choice((-1, 1)) * rng.randrange(1, 500))
            row = self.close(ledger, standard_need_30d=rng.randrange(100))
            self.assertEqual(row['fee'], row['distributable'] * 500 // 10_000)
            if day % 3 == 0:
                ledger.paused = True
                ledger.deposit('entrant-' + str(day), 1000, ledger.clock)
                ledger.paused = False
            ledger.pay_close(day, ledger.clock)
            ledger.check()

    def test_daily_final_fees_can_exceed_weekly_netting(self):
        ledger, _ = self.ledger()
        self.trade(ledger, 1000)
        self.assertEqual(self.close(ledger)['fee'], 50)
        self.trade(ledger, -1000)
        self.assertEqual(self.close(ledger)['fee'], 0)
        self.assertEqual((ledger.realized, ledger.fees), (0, 50))

    def test_partial_withdrawal_is_allowed_midday_during_open_bet(self):
        ledger, lot = self.ledger(1000)
        ledger.accept('live', 'BTC', 100, 2, START + 1)
        self.assertEqual(ledger.max_withdrawal(lot), 900)
        ledger.withdraw(lot, 900, START + 2)
        self.assertEqual(ledger.lots[lot].equity, 100)
        ledger.resolve('live', 'win', START + 30_001)
        self.assertEqual((ledger.lots[lot].equity, ledger.win_payable), (0, 100))
        ledger.settle_cash('live', START + 30_002)
        ledger.check()

    def test_idle_capital_can_fully_exit_without_request_delay_or_future_bet_buffer(self):
        for paused in (False, True):
            for at in (START+1, START+3*DAY):
                ledger, lot = self.ledger(1000, limits(admission_buffer=100,
                                                     distribution_buffer=200, backing_buffer=300))
                ledger.paused = paused
                self.assertEqual(ledger.max_withdrawal(lot), 1000)
                self.assertEqual(ledger.withdraw(lot, 1000, at), 1000)
                self.assertEqual((ledger.cash, ledger.archived[lot].equity), (0, 0))

    def test_future_bet_buffer_does_not_block_withdrawal_of_unassigned_cash(self):
        for outcome in ('win', 'loss', 'void'):
            ledger, lot = self.ledger(1000, limits(admission_buffer=100,
                                                 distribution_buffer=200, backing_buffer=300))
            ledger.accept('accepted', 'BTC', 100, 2, START+1)
            self.assertEqual(ledger.max_withdrawal(lot), 900)
            ledger.withdraw(lot, 900, START+2)
            with self.assertRaisesRegex(ValueError, 'capital limit'):
                ledger.accept('no-room', 'ETH', 1, 2, START+3)
            canonical = START+2 if outcome == 'loss' else START+30_001
            ledger.resolve('accepted', outcome, canonical, observed_at=START+30_001)
            if ledger.bets['accepted'].cash_due:
                ledger.settle_cash('accepted', START+30_002)
            ledger.check()

    def test_withdrawal_preserves_unpaid_winner_and_both_close_transfers(self):
        ledger, lot = self.ledger(1100, limits(admission_buffer=100,
                                             distribution_buffer=100, backing_buffer=100))
        self.trade(ledger, 1000)
        row = self.close(ledger, standard_need_30d=100)
        self.assertEqual((row['fee'], row['backing']), (50, 223))
        self.trade(ledger, -100, cash=False)
        self.assertEqual(ledger.max_withdrawal(lot), 1727)
        ledger.paused = True
        ledger.withdraw(lot, 1727, ledger.clock+1)
        self.assertEqual(ledger.cash, ledger.win_payable+ledger.operator_due+ledger.backing_due)
        ledger.settle_cash('bet-1', ledger.clock+1)
        self.assertEqual(ledger.pay_close(0, ledger.clock+1), (50, 223))
        self.assertEqual((ledger.cash, ledger.win_payable), (0, 0))

    def test_stale_withdrawal_amount_rechecked_after_new_bet(self):
        ledger, lot = self.ledger(1000, limits(admission_buffer=100,
                                             distribution_buffer=100, backing_buffer=100))
        shown = ledger.max_withdrawal(lot)
        ledger.accept('wins-the-order', 'BTC', 100, 2, START+1)
        before = copy.deepcopy(vars(ledger))
        with self.assertRaisesRegex(ValueError, 'free capital'):
            ledger.withdraw(lot, shown, START+2)
        self.assertEqual(vars(ledger), before)
        self.assertEqual(ledger.withdraw(lot, ledger.max_withdrawal(lot), START+2), 900)

    def test_bet_rechecks_cash_after_withdrawal_wins_the_order(self):
        ledger, lot = self.ledger(1000, limits(admission_buffer=100,
                                             distribution_buffer=100, backing_buffer=100))
        ledger.withdraw(lot, 1000, START+1)
        before = copy.deepcopy(vars(ledger))
        with self.assertRaisesRegex(ValueError, 'capital limit'):
            ledger.accept('loses-the-order', 'BTC', 1, 2, START+2)
        self.assertEqual(vars(ledger), before)

    def test_withdrawal_does_not_transfer_accepted_risk_to_remaining_lp(self):
        ledger = Ledger(START, limits())
        first = ledger.deposit('first', 1000, START)
        second = ledger.deposit('second', 1000, START)
        ledger.paused = False
        ledger.accept('fixed-owners', 'BTC', 200, 2, START + 1)
        ledger.withdraw(first, 900, START + 2)
        ledger.resolve('fixed-owners', 'win', START + 30_001)
        self.assertEqual((ledger.lots[first].equity, ledger.lots[second].equity), (0, 900))
        self.assertEqual((ledger.lots[first].pnl, ledger.lots[second].pnl), (-100, -100))

    def test_partial_withdrawal_preserves_unclosed_profit_and_carryforward(self):
        ledger, lot = self.ledger(1000)
        self.trade(ledger, 100)
        self.assertEqual(ledger.max_withdrawal(lot), 1000)
        ledger.withdraw(lot, 1000, ledger.clock + 1)
        self.assertEqual(ledger.max_withdrawal(lot), 0)
        self.assertEqual(self.close(ledger)['fee'], 5)
        self.assertEqual(ledger.max_withdrawal(lot), 95)

    def test_distribution_cannot_consume_specific_lots_reserved_risk(self):
        ledger, first = self.ledger(1000)
        self.trade(ledger, 1000)
        ledger.accept('span', 'BTC', 2000, 2, ledger.cutoff - 1)
        row = self.close(ledger, standard_need_30d=10000)
        self.assertEqual((row['eligible'], row['distributable'], row['fee'], row['backing']), (1000, 0, 0, 0))
        self.assertEqual(ledger.lots[first].equity, 2000)

    def test_cutoff_exposure_cannot_forgive_unprocessed_profit(self):
        ledger, lot = self.ledger(1000)
        self.trade(ledger, 1000)
        end = ledger.cutoff
        ledger.accept('cutoff-risk', 'BTC', 2000, 2, end - 1)
        row = self.close(ledger)
        self.assertEqual((row['fee'], row['protected_pending'], ledger.lots[lot].mark), (0, 1000, 0))
        ledger.resolve('cutoff-risk', 'void', end + 30_000)
        self.assertEqual(ledger.max_withdrawal(lot), 1000)
        self.assertEqual(self.close(ledger)['fee'], 50)
        self.assertEqual(self.close(ledger)['fee'], 0)

    def test_no_new_risk_for_account_with_full_exit_request(self):
        ledger, lot = self.ledger(1000)
        ledger.request_exit(lot, START + 1)
        with self.assertRaises(ValueError):
            ledger.accept('new-risk', 'BTC', 1, 2, START + 2)
        self.assertEqual(ledger.execute_exit(lot, START + 2), 1000)

    def test_pending_profit_lost_before_distribution_is_not_charged(self):
        ledger, lot = self.ledger(1000, limits(distribution_buffer=5000, backing_buffer=5000))
        self.trade(ledger, 1000)
        self.assertEqual(self.close(ledger)['protected_pending'], 1000)
        self.trade(ledger, -1000)
        row = self.close(ledger)
        self.assertEqual((row['fee'], row['protected_pending'], ledger.lots[lot].mark), (0, 0, 0))

    def test_randomized_withdrawals_preserve_original_underwriting_owners(self):
        rng = random.Random(703)
        ledger, _ = self.ledger(100_000, limits(admission_buffer=100,
                                              distribution_buffer=200, backing_buffer=300))
        ledger.paused = True
        ledger.deposit('second', 100_000, START)
        ledger.paused = False
        for day in range(8):
            for _ in range(100):
                action = rng.randrange(3)
                at = ledger.clock + 1
                if action == 0:
                    try:
                        ledger.accept('random-' + str(len(ledger.bets)), rng.choice(('BTC', 'ETH', 'HYPE')),
                                      rng.randrange(1, 50), rng.choice(PAYOUTS), at)
                    except ValueError:
                        pass
                elif action == 1:
                    choices = [k for k, b in ledger.bets.items() if b.status == 'open']
                    if choices:
                        key = rng.choice(choices)
                        at = max(at, ledger.bets[key].expiry)
                        outcome = rng.choice(('win', 'loss', 'void'))
                        canonical = ledger.bets[key].expiry if outcome == 'win' else min(at, ledger.bets[key].expiry-1) if outcome == 'loss' else at
                        ledger.resolve(key, outcome, canonical, observed_at=at)
                        if ledger.bets[key].cash_due:
                            ledger.settle_cash(key, at)
                else:
                    if ledger.lots:
                        key = rng.choice(list(ledger.lots))
                        free = ledger.max_withdrawal(key)
                        if free:
                            ledger.withdraw(key, rng.randrange(1, free+1), at)
                ledger.check()
            for key in ledger.bets:
                if ledger.bets[key].status == 'open':
                    at = max(ledger.clock+1, ledger.bets[key].expiry)
                    outcome = rng.choice(('win', 'loss', 'void'))
                    canonical = ledger.bets[key].expiry if outcome == 'win' else min(at, ledger.bets[key].expiry-1) if outcome == 'loss' else at
                    ledger.resolve(key, outcome, canonical, observed_at=at)
                    if ledger.bets[key].cash_due:
                        ledger.settle_cash(key, at)
            self.close(ledger, standard_need_30d=100)
            ledger.pay_close(day, ledger.clock)
            ledger.paused = True
            ledger.deposit('new-' + str(day), 1000, ledger.clock)
            ledger.paused = False

    def test_randomized_apportionment_conserves_signed_pnl(self):
        rng = random.Random(9)
        for _ in range(1000):
            weights = {i: rng.randrange(1000) for i in range(20)}
            n = rng.randrange(-10000, 10000)
            split = apportion(n, weights)
            self.assertEqual(sum(split.values()), n)
            self.assertEqual(split, {k: -v for k, v in apportion(-n, weights).items()})

    def test_overdue_close_does_not_lock_free_capital_or_old_underwriting(self):
        ledger, lot = self.ledger(1000)
        ledger.accept('late-proof', 'BTC', 100, 2, START+1)
        end = ledger.cutoff
        ledger.withdraw(lot, 900, end+10_000)
        self.assertEqual((ledger.cash, ledger.lot_exposure(lot)), (100, 100))
        with self.assertRaisesRegex(ValueError, 'close required'):
            ledger.accept('new-day-risk', 'BTC', 1, 2, end+10_001)
        ledger.resolve('late-proof', 'win', START+30_001, observed_at=end+10_001)
        self.assertEqual((ledger.lots[lot].equity, ledger.win_payable), (0, 100))
        ledger.settle_cash('late-proof', end+10_002)
        row = self.close(ledger, observed_at=end+10_003)
        self.assertEqual((row['fee'], row['loss_carried'], ledger.clock), (0, 100, end+10_003))

    def test_late_same_day_loss_is_charged_once_without_rewinding_observation_clock(self):
        ledger, lot = self.ledger(1000)
        ledger.accept('late-loss', 'BTC', 100, 2, START+1)
        end = ledger.cutoff
        ledger.request_exit(lot, end+1)
        ledger.withdraw(lot, 900, end+2)
        ledger.resolve('late-loss', 'loss', START+2, observed_at=end+3)
        ledger.settle_cash('late-loss', end+4)
        row = self.close(ledger, observed_at=end+5)
        self.assertEqual((row['eligible'], row['fee'], ledger.clock), (100, 5, end+5))
        self.assertEqual(ledger.execute_exit(lot, end+6), 195)
        self.assertEqual(ledger.archived[lot].mark, 100)
        ledger.pay_close(0, end+7)
        self.assertEqual((ledger.cash, ledger.operator_paid), (0, 5))

    def test_late_win_nets_in_its_canonical_day_after_free_principal_withdrawal(self):
        ledger, lot = self.ledger(1000)
        self.trade(ledger, 200)
        ledger.accept('late-win', 'BTC', 100, 2, START+50_000)
        end = ledger.cutoff
        ledger.withdraw(lot, 900, end+1)
        self.assertEqual(ledger.lots[lot].equity, 300)
        ledger.resolve('late-win', 'win', START+80_000, observed_at=end+2)
        ledger.settle_cash('late-win', end+3)
        row = self.close(ledger)
        self.assertEqual((row['eligible'], row['fee'], ledger.clock), (100, 5, end+3))

    def test_boundary_win_requires_previous_close_even_when_observed_late(self):
        ledger, lot = self.ledger(1000)
        end = ledger.cutoff
        ledger.accept('boundary', 'BTC', 100, 2, end-30_000)
        ledger.withdraw(lot, 900, end+1000)
        with self.assertRaises(ValueError):
            ledger.resolve('boundary', 'win', end, observed_at=end+1001)
        self.assertEqual(self.close(ledger)['eligible'], 0)
        ledger.resolve('boundary', 'win', end, observed_at=end+1001)
        self.assertEqual(self.close(ledger)['loss_carried'], 100)

    def test_known_winner_can_be_funded_and_paid_closes_can_transfer_while_overdue(self):
        ledger, lot = self.ledger(1000)
        self.trade(ledger, 200)
        self.close(ledger)
        self.trade(ledger, -100, cash=False)
        late = ledger.cutoff+1
        ledger.pay_close(0, late)
        ledger.withdraw(lot, ledger.max_withdrawal(lot), late+1)
        ledger.settle_cash('bet-1', late+2)
        self.assertEqual((ledger.win_payable, ledger.open_exposure), (0, 0))
        ledger.check()

    def test_wrong_outcome_time_or_late_finalized_day_cannot_shift_daily_profit(self):
        ledger, _ = self.ledger(1000)
        ledger.accept('timing', 'BTC', 100, 2, START+1)
        before = copy.deepcopy(vars(ledger))
        for outcome, canonical, observed in (('win',START+30_002,START+30_002),
                                             ('loss',START+30_001,START+30_001),
                                             ('loss',START+3,START+2)):
            with self.assertRaises(ValueError):
                ledger.resolve('timing', outcome, canonical, observed_at=observed)
            self.assertEqual(vars(ledger), before)
        ledger.resolve('timing', 'void', START+30_001)
        self.close(ledger)
        with self.assertRaises(ValueError):
            ledger.resolve('timing', 'loss', START+2, observed_at=ledger.clock+1)

    def test_final_void_after_cutoff_keeps_risk_through_prior_close_then_releases(self):
        ledger, lot = self.ledger(1000)
        self.trade(ledger, 100)
        end = ledger.cutoff
        ledger.accept('outage', 'BTC', 1100, 2, end-60_000)
        final = end+10_000
        with self.assertRaises(ValueError):
            ledger.resolve('outage', 'void', final)
        ledger.queue_final_void('outage', final)
        self.assertEqual((ledger.open_exposure, ledger.max_withdrawal(lot)), (1100, 0))
        with self.assertRaises(ValueError):
            ledger.resolve('outage', 'loss', end-59_000, observed_at=final)
        row = self.close(ledger)
        self.assertEqual((row['fee'], row['protected_pending'], row['open_exposure']), (0, 100, 1100))
        ledger.resolve('outage', 'void', final)
        self.assertEqual((ledger.open_exposure, ledger.max_withdrawal(lot)), (0, 1000))
        self.assertEqual(self.close(ledger)['fee'], 5)
        self.assertEqual(self.close(ledger)['fee'], 0)

    def test_final_void_proof_allows_sequential_multiday_recovery_without_releasing_early(self):
        ledger, _ = self.ledger(1000)
        end = ledger.cutoff
        ledger.accept('long-outage', 'BTC', 100, 2, end-60_000)
        final = end+2*DAY+10_000
        ledger.queue_final_void('long-outage', final)
        for _ in range(3):
            self.assertEqual(self.close(ledger)['open_exposure'], 100)
        ledger.resolve('long-outage', 'void', final)
        self.assertEqual(ledger.open_exposure, 0)
        with self.assertRaises(ValueError):
            ledger.queue_final_void('long-outage', final+1)

    def test_paused_reconciled_deposit_window_is_not_a_single_timestamp(self):
        ledger, old = self.ledger(1000)
        self.trade(ledger, -100)
        self.close(ledger)
        ledger.paused = True
        ledger.request_exit(old, ledger.clock+1000)
        new = ledger.deposit('newcomer', 1000, ledger.clock+10_000)
        self.assertEqual((ledger.lots[old].pnl, ledger.lots[new].pnl), (-100, 0))
        self.assertEqual(ledger.lots[new].mark, 0)


if __name__ == '__main__':
    unittest.main()
