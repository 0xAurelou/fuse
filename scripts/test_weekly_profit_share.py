import unittest

from weekly_profit_share import WeeklyProfitShare, simulate_weekly


class WeeklyProfitShareTests(unittest.TestCase):
    def close(self, ledger, equity=100000):
        return ledger.close(equity, required=1000, allowance=10000, target=10000)

    def test_intraweek_gains_cannot_pay_before_later_losses_are_netted(self):
        ledger = WeeklyProfitShare()
        for pnl in (10000, -12000, 2000):
            ledger.settle(pnl)
            self.assertEqual(ledger.protocol_paid, 0)
        allocation = self.close(ledger)
        self.assertEqual(allocation.protocol, 0)
        self.assertEqual(ledger.weeks[0]['week_trading_pnl_usdc_units'], 0)

    def test_losses_survive_calendar_boundaries(self):
        ledger = WeeklyProfitShare()
        ledger.settle(-1000)
        self.assertEqual(self.close(ledger).protocol, 0)
        ledger.settle(800)
        self.assertEqual(self.close(ledger).protocol, 0)
        self.assertEqual(ledger.weeks[-1]['loss_carried_usdc_units'], 200)
        ledger.settle(500)
        allocation = self.close(ledger)
        self.assertEqual(allocation.eligible, 300)
        self.assertEqual(allocation.protocol, 15)

    def test_prior_earned_fees_are_not_clawed_back_but_recovery_is_not_recharged(self):
        ledger = WeeklyProfitShare()
        for pnl, fee in ((1000, 50), (-500, 0), (500, 0), (100, 5)):
            ledger.settle(pnl)
            self.assertEqual(self.close(ledger).protocol, fee)
        self.assertEqual(ledger.protocol_paid, 55)

    def test_capital_protection_precedes_fee_and_has_no_retroactive_tax(self):
        ledger = WeeklyProfitShare()
        ledger.settle(1000)
        allocation = self.close(ledger, equity=2500)
        self.assertEqual(allocation.distributable, 500)
        self.assertEqual(allocation.protocol, 25)
        self.assertEqual(self.close(ledger, equity=100000).protocol, 0)

    def test_dynamic_backing_and_operator_partition_distributable_profit(self):
        ledger = WeeklyProfitShare()
        ledger.settle(1000)
        allocation = ledger.close(10000, 1000, 0, 540)
        self.assertEqual((allocation.protocol, allocation.backing, allocation.lp_retained),
                         (50, 600, 350))

    def test_quote_edge_does_not_change_fees_on_identical_actual_paths(self):
        low = simulate_weekly(700, 5000, trading_days=14)
        high = simulate_weekly(1000, 5000, trading_days=14)
        self.assertNotEqual(low['nominal_expected_margin_usdc_units'],
                            high['nominal_expected_margin_usdc_units'])
        for key in ('realized_trading_pnl_usdc_units', 'protocol_usdc_units',
                    'new_backing_usdc_units', 'lp_final_usdc_units', 'rewards_usdc_units'):
            self.assertEqual(low[key], high[key])
        self.assertFalse(low['nominal_expected_margin_booked_as_revenue'])

    def test_negative_week_with_high_quote_edge_pays_no_fee(self):
        result = simulate_weekly(1000, 10000, trading_days=7)
        self.assertLess(result['realized_trading_pnl_usdc_units'], 0)
        self.assertEqual(result['protocol_usdc_units'], 0)
        self.assertTrue(result['conservation_verified'])

    def test_zero_activity_keeps_seed_and_lp_without_fees(self):
        result = simulate_weekly(1000, 4500, case='no-demand', trading_days=8)
        self.assertEqual(result['accounting_days'], 14)
        self.assertEqual(len(result['weeks']), 2)
        self.assertEqual(result['protocol_usdc_units'], 0)
        self.assertEqual(result['new_backing_usdc_units'], 0)
        self.assertEqual(result['lp_final_usdc_units'], 250000000000)
        self.assertEqual(result['reserve_final_usdc_units'], 125000000000)


if __name__ == '__main__':
    unittest.main()
