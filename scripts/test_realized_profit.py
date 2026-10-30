import unittest

from stress_realized_profit import crystallization_example, settled_window


class RealizedProfitTests(unittest.TestCase):
    def test_actual_resolved_payouts_define_profit(self):
        window = settled_window(10000, 9500)
        self.assertEqual(window['actual_trading_pnl'], 500)
        self.assertEqual(window['protocol'], 25)
        self.assertEqual(window['dynamic_lp_fuse_remainder'], 475)

    def test_losses_and_capital_are_recovered_before_fees(self):
        self.assertEqual(settled_window(10000, 10000)['protocol'], 0)
        self.assertEqual(settled_window(10000, 11000)['protocol'], 0)
        self.assertEqual(settled_window(10000, 9500, previous_loss=600)['protocol'], 0)
        self.assertEqual(settled_window(10000, 9500, previous_loss=200,
                                       protected_capital=100)['protocol'], 10)

    def test_timing_example_is_explicitly_not_lifetime_profit_share(self):
        example = crystallization_example()
        self.assertEqual(example['final_net_pnl_usdc_units'], 0)
        self.assertEqual(example['fees_if_one_window_closes_at_end_usdc_units'], 0)
        self.assertEqual(example['fees_if_each_step_crystallizes_usdc_units'], 500000000)


if __name__ == '__main__':
    unittest.main()
