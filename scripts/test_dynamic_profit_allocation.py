import random
import unittest
from dataclasses import replace

from dynamic_profit_allocation import allocate, run
from stress_loss_rewards import Scenario, USDC


class DynamicProfitTests(unittest.TestCase):
    def test_protocol_fixed_five_percent_remainder_is_dynamic(self):
        a = allocate(1000, 10000, 1000, 0, 540)
        self.assertEqual((a.protocol, a.backing, a.lp_retained), (50, 600, 350))
        b = allocate(1000, 10000, 1000, 540, 540)
        self.assertEqual((b.protocol, b.backing, b.lp_retained), (50, 0, 950))

    def test_thin_lp_retains_all_ninety_five_percent(self):
        a = allocate(500, 2900, 1000, 0, 10000)
        self.assertEqual((a.protocol, a.backing, a.lp_retained), (25, 0, 475))

    def test_two_times_capital_is_protected_before_defining_distributable(self):
        a = allocate(1000, 2500, 1000, 0, 10000)
        self.assertEqual(a.distributable, 500)
        self.assertEqual(a.protocol, 25)
        self.assertEqual(a.restoration_retained, 500)
        self.assertEqual(a.backing, 0)
        self.assertEqual(allocate(1000, 1900, 1000, 0, 10000).protocol, 0)

    def test_no_profit_no_fee_even_when_fuse_needs_funding(self):
        a = allocate(0, 100000, 1000, 0, 1000000)
        self.assertEqual((a.protocol, a.backing, a.lp_retained), (0, 0, 0))

    def test_backing_uses_actual_shortfall_and_retains_three_times_capital(self):
        a = allocate(1000, 3500, 1000, 0, 10000)
        self.assertEqual((a.protocol, a.backing, a.lp_retained), (50, 450, 500))
        self.assertEqual(3500 - a.protocol - a.backing, 3000)

    def test_can_route_all_remaining_profit_to_backing_without_fixed_lp_percentage(self):
        a = allocate(1000, 10000, 1000, 0, 100000)
        self.assertEqual((a.protocol, a.backing, a.lp_retained), (50, 950, 0))

    def test_randomized_partition_and_capital_invariants(self):
        r = random.Random(20261029)
        for _ in range(10000):
            equity, capital, profit = r.randrange(1000000), r.randrange(100000), r.randrange(100000)
            a = allocate(profit, equity, capital, r.randrange(100000), r.randrange(100000))
            self.assertEqual(a.protocol + a.backing + a.lp_retained, profit)
            self.assertEqual(a.protocol, a.distributable * 5 // 100)
            if equity >= 2 * capital:
                self.assertGreaterEqual(equity - a.protocol - a.backing, 2 * capital)

    def test_funded_quote_and_cash_conservation_under_changed_underwriting(self):
        s = Scenario(days=5)
        for mode in ('fixed35', 'dynamic'):
            a = run(s, mode)
            self.assertTrue(a['conservation_verified'])
            self.assertEqual(a['reward_coverage'], 1)
            self.assertGreater(a['protocol_usdc_units'], 0)

    def test_no_activity_does_not_pay_operator_from_seed(self):
        a = run(Scenario(days=4, games_per_day=0))
        self.assertEqual(a['protocol_usdc_units'], 0)
        self.assertEqual(a['reserve_funded_usdc_units'], 0)
        self.assertEqual(a['reserve_final_usdc_units'], 125000 * USDC)

    def test_all_winners_and_low_capital_remain_funded(self):
        s = Scenario(days=5, lp_usdc=1000, survival_bps=10000)
        a = run(s)
        self.assertTrue(a['conservation_verified'])
        self.assertGreater(a['rejected'], 0)
        self.assertEqual(a['protocol_usdc_units'], 0)
        self.assertEqual(a['reserve_funded_usdc_units'], 0)


if __name__ == '__main__':
    unittest.main()
