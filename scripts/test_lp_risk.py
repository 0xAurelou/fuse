import unittest
from dataclasses import replace

from lp_risk import DAY, RiskGuard, RiskPolicy
from simulate_lp_incentives import Scenario, run
from simulate_tokenomics import USDC


class RiskAdmissionTests(unittest.TestCase):
    def test_rolling_budget_does_not_reset_at_midnight(self):
        guard = RiskGuard(RiskPolicy(daily_loss_bps=1000), 1000, 1000)
        guard.reserve(DAY - 60, 1000, 1000, 100)
        guard.settle(DAY - 30, 100, 900, 1000)
        self.assertEqual(guard.capacity(DAY + 1, 900, 1000)[0], 0)
        self.assertEqual(guard.capacity(2 * DAY - 31, 900, 1000)[0], 0)
        self.assertEqual(guard.capacity(2 * DAY - 30, 900, 1000)[0], 90)

    def test_gross_losses_cannot_be_offset_by_simultaneous_revenue(self):
        guard = RiskGuard(RiskPolicy(daily_loss_bps=1000), 1000, 1000)
        guard.reserve(0, 1000, 1000, 100)
        guard.settle(30, 50, 1000, 1000)  # 50 revenue and 50 paid to winners.
        self.assertEqual(guard.capacity(31, 1000, 1000)[0], 50)

    def test_capital_flows_preserve_fraction_of_budget_consumed(self):
        guard = RiskGuard(RiskPolicy(daily_loss_bps=1000), 1000, 1000)
        guard.reserve(0, 1000, 1000, 50)
        guard.settle(30, 50, 950, 1000)
        self.assertEqual(guard.capacity(31, 1900, 2000)[0], 100)
        self.assertEqual(guard.capacity(32, 475, 500)[0], 25)

    def test_whole_batch_reserved_and_already_accepted_loss_must_settle(self):
        guard = RiskGuard(RiskPolicy(daily_loss_bps=1000), 1000, 1000)
        guard.reserve(0, 1000, 1000, 100)
        with self.assertRaises(ValueError):
            guard.capacity(1, 1000, 1000)
        with self.assertRaises(ValueError):
            guard.settle(30, 101, 899, 1000)
        guard.settle(30, 100, 900, 1000)
        self.assertTrue(guard.summary()['accepted_payouts_funded'])
        self.assertEqual(guard.capacity(31, 900, 1000)[0], 0)

    def test_hard_drawdown_is_prospective_and_peak_is_not_reset(self):
        policy = RiskPolicy(pause_drawdown_bps=1000, hard_drawdown_bps=2000,
                            resume_drawdown_bps=500)
        guard = RiskGuard(policy, 1000, 1000)
        self.assertEqual(guard.capacity(0, 1000, 1000)[0], 200)
        with self.assertRaises(ValueError):
            guard.reserve(0, 1000, 1000, 201)
        guard.reserve(0, 1000, 1000, 200)
        guard.settle(30, 200, 800, 1000)
        self.assertEqual(guard.mode, 'paused')
        self.assertEqual(guard.capacity(3 * DAY, 1600, 2000)[0], 0)
        self.assertEqual(guard.peak, 1)
        self.assertEqual(guard.summary()['other_flow_floor_breaches'], 0)

    def test_probe_recovery_preserves_floor_and_previous_peak(self):
        policy = RiskPolicy(pause_drawdown_bps=1000, hard_drawdown_bps=2000,
                            resume_drawdown_bps=500, probe_loss_bps=25)
        guard = RiskGuard(policy, 1_000_000, 1_000_000)
        guard.reserve(0, 1_000_000, 1_000_000, 100_000)
        guard.settle(30, 100_000, 900_000, 1_000_000)
        self.assertEqual(guard.capacity(DAY, 900_000, 1_000_000)[0], 0)
        at = 3 * DAY
        self.assertEqual(guard.capacity(at, 900_000, 1_000_000, fresh=False)[0], 0)
        self.assertEqual(guard.mode, 'probe')
        self.assertEqual(guard.capacity(at, 900_000, 1_000_000)[0], 2250)
        assets = 900_000
        while assets < 950_000:
            amount = min(2250, 950_000 - assets)
            guard.reserve(at, assets, 1_000_000, amount)
            assets += amount  # Already-funded losing trader pays the LP.
            at += 30
            guard.settle(at, 0, assets, 1_000_000)
        self.assertEqual(guard.mode, 'open')
        self.assertEqual(guard.peak, 1)
        self.assertEqual(guard.summary()['fully_reopened_episodes'], 1)

    def test_latched_pause_does_not_invent_a_recovery(self):
        guard = RiskGuard(RiskPolicy(pause_drawdown_bps=1000, hard_drawdown_bps=2000,
                                    resume_drawdown_bps=500, probe_loss_bps=0), 1000, 1000)
        guard.reserve(0, 1000, 1000, 100)
        guard.settle(30, 100, 900, 1000)
        self.assertEqual(guard.capacity(100 * DAY, 900, 1000)[0], 0)
        self.assertEqual(guard.mode, 'paused')
        self.assertEqual(guard.summary()['fully_reopened_episodes'], 0)

    def test_external_shock_is_reported_and_fences_new_risk(self):
        guard = RiskGuard(RiskPolicy(hard_drawdown_bps=2000), 1000, 1000)
        guard.observe(1, 500, 1000)
        self.assertEqual(guard.capacity(2, 500, 1000)[0], 0)
        self.assertEqual(guard.summary()['other_flow_floor_breaches'], 1)

    def test_multi_day_cap_is_not_a_daily_allowance(self):
        guard = RiskGuard(RiskPolicy(daily_loss_bps=1000, rolling_loss_bps=1500), 1000, 1000)
        guard.reserve(0, 1000, 1000, 100)
        guard.settle(30, 100, 900, 1000)
        self.assertEqual(guard.capacity(2 * DAY, 900, 1000)[0], 50)
        guard.reserve(2 * DAY, 900, 1000, 50)
        guard.settle(2 * DAY + 30, 50, 850, 1000)
        self.assertEqual(guard.capacity(4 * DAY, 850, 1000)[0], 0)

    def test_invalid_policies_and_backwards_clock_fail(self):
        for settings in ({'daily_loss_bps': 10000}, {'rolling_days': 0},
                         {'pause_drawdown_bps': 1000, 'hard_drawdown_bps': 500},
                         {'pause_drawdown_bps': 1000, 'hard_drawdown_bps': 2000,
                          'resume_drawdown_bps': 1000}):
            with self.assertRaises(ValueError):
                RiskPolicy(**settings)
        guard = RiskGuard(RiskPolicy(), 1000, 1000)
        guard.observe(10, 1000, 1000)
        with self.assertRaises(ValueError):
            guard.observe(9, 1000, 1000)

    def test_repeated_cluster_run_preserves_payouts_and_measures_retention(self):
        scenario = Scenario(days=125, games_per_day=300, batches_per_day=6,
                            daily_trader_inflow_usdc=10000, whitelist_day=1, public_day=7,
                            winner_cluster_days=tuple(range(30, 40)) + tuple(range(95, 98)),
                            risk_policy=RiskPolicy(daily_loss_bps=500, rolling_loss_bps=1000,
                                                   pause_drawdown_bps=1000, hard_drawdown_bps=2000,
                                                   resume_drawdown_bps=500), daily_log=True)
        result = run(scenario)
        self.assertTrue(result['conservation_verified'])
        self.assertTrue(result['risk_controls']['accepted_payouts_funded'])
        self.assertLessEqual(result['max_share_drawdown'], .20000001)
        self.assertGreater(sum(result['risk_controls']['rejected_stages_by_limit'].values()), 0)
        self.assertIn('119', result['post_bootstrap_retention'])
        self.assertTrue(all(int(row['lp_reward_today_fuse_units']) == 0 for row in result['daily'] if row['day'] >= 90))


if __name__ == '__main__':
    unittest.main()
