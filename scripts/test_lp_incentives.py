import unittest
from dataclasses import replace

from simulate_lp_incentives import Rewards, Scenario, Vault, run
from simulate_tokenomics import GENESIS, MINING, TOKEN, TREASURY, USDC


class LPParticipationTests(unittest.TestCase):
    def test_illustrative_65_35_waterfall_and_loss_recovery(self):
        vault = Vault(5_000_000 * USDC)
        vault.settle(200_000 * USDC)
        self.assertEqual(vault.waterfall(3500), 70_000 * USDC)
        self.assertEqual(vault.assets, 5_130_000 * USDC)
        peak = vault.hwm
        vault.settle(-100_000 * USDC)
        self.assertEqual(vault.waterfall(3500), 0)
        vault.settle(100_000 * USDC)
        self.assertEqual(vault.waterfall(3500), 0)
        self.assertEqual(vault.hwm, peak)
        vault.settle(100 * USDC)
        self.assertEqual(vault.waterfall(3500), 35 * USDC)
        vault.check()

    def test_capital_flows_do_not_reset_loss_hwm_or_create_fee_profit(self):
        vault = Vault(1000 * USDC)
        vault.settle(-200 * USDC)
        vault.waterfall(3500)
        previous_hwm = vault.hwm
        vault.deposit('alice', 800 * USDC, 10_000 * USDC)
        self.assertEqual(vault.hwm, previous_hwm)
        self.assertEqual(vault.waterfall(3500), 0)
        self.assertEqual(vault.shares['alice'], vault.shares['protocol'])
        vault.settle(400 * USDC)
        self.assertEqual(vault.waterfall(3500), 0)
        vault.settle(100 * USDC)
        self.assertEqual(vault.waterfall(3500), 35 * USDC)

    def test_requested_exit_is_exposed_until_current_nav_fulfillment(self):
        vault = Vault(1000 * USDC)
        vault.deposit('alice', 1000 * USDC, 10_000 * USDC)
        self.assertTrue(vault.request('alice', vault.shares['alice'], 0))
        self.assertFalse(vault.request('alice', 1, 0))
        self.assertEqual(dict(vault.fulfill(1)), {})
        vault.exposure = 200 * USDC
        self.assertEqual(dict(vault.fulfill(2)), {})
        self.assertEqual(vault.deposit('bob', 100 * USDC, 10_000 * USDC), 0)
        vault.settle(-400 * USDC)
        vault.exposure = 0
        vault.fresh = False
        self.assertEqual(dict(vault.fulfill(3)), {})
        vault.fresh = True
        self.assertEqual(dict(vault.fulfill(4)), {'alice': 800 * USDC})
        self.assertEqual(vault.shares['alice'], 0)
        vault.check()

    def test_queue_cannot_remove_required_capital_and_is_fifo(self):
        vault = Vault(1000 * USDC)
        vault.deposit('alice', 1000 * USDC, 10_000 * USDC)
        vault.deposit('bob', 10 * USDC, 10_000 * USDC)
        vault.request('alice', vault.shares['alice'], 0)
        vault.request('bob', vault.shares['bob'], 0)
        vault.required = 800 * USDC
        self.assertEqual(dict(vault.fulfill(2)), {})
        self.assertEqual(len(vault.pending), 2)
        vault.required = 100 * USDC
        self.assertEqual(dict(vault.fulfill(3)), {'alice': 1000 * USDC, 'bob': 10 * USDC})
        vault.check()

    def test_capital_restoration_retention_is_not_charged_later(self):
        vault = Vault(1000 * USDC)
        vault.required = 700 * USDC
        vault.settle(100 * USDC)
        self.assertEqual(vault.waterfall(3500), 0)
        vault.required = 100 * USDC
        self.assertEqual(vault.waterfall(3500), 0)
        vault.settle(100 * USDC)
        self.assertEqual(vault.waterfall(3500), 35 * USDC)
        self.assertGreaterEqual(vault.assets, 2 * vault.required)

    def test_dynamic_cap_and_deposit_rounding_cannot_mint_free_shares(self):
        vault = Vault(1000 * USDC)
        vault.settle(333 * USDC)
        before = vault.nav()
        self.assertEqual(vault.deposit('alice', 1000 * USDC, 1500 * USDC), 167 * USDC)
        self.assertGreaterEqual(vault.nav(), before)
        self.assertEqual(vault.deposit('bob', 1, 1500 * USDC), 0)
        vault.check()

    def test_rewards_expire_without_utilization_and_vest_after_30_days(self):
        rewards = Rewards(Scenario())
        budget = rewards.schedule[0]
        self.assertEqual(rewards.accrue(0, {'alice': 100}, 100, 0), 0)
        self.assertEqual(rewards.expired, budget)
        earned = rewards.accrue(1, {'alice': 50}, 100, 20)
        self.assertEqual(earned, rewards.schedule[1] // 2)
        rewards.vest(30)
        self.assertEqual(rewards.liquid['alice'], 0)
        rewards.vest(31)
        self.assertEqual(rewards.liquid['alice'], earned)
        self.assertEqual(rewards.accrue(90, {'alice': 100}, 100, 100), 0)
        rewards.check()

    def test_protocol_or_fully_queued_capital_cannot_mine(self):
        rewards = Rewards(Scenario())
        self.assertEqual(rewards.accrue(0, {}, 100, 100), 0)
        self.assertEqual(rewards.earned, 0)

    def test_allocation_is_from_existing_400m_and_schedule_is_finite(self):
        for days in (60, 90):
            rewards = Rewards(Scenario(bootstrap_days=days))
            self.assertLessEqual(sum(rewards.schedule), 50_000_000 * TOKEN)
            self.assertEqual(MINING + rewards.budget + TREASURY - rewards.budget, GENESIS)
            self.assertTrue(all(a >= b for a, b in zip(rewards.schedule, rewards.schedule[1:])))

    def test_no_demand_cannot_attract_capped_capital_or_mine(self):
        result = run(Scenario(behavior='no-demand', days=100))
        self.assertEqual(result['external_deposits_usdc_units'], 0)
        self.assertEqual(result['lp_bootstrap_earned_fuse_units'], '0')
        self.assertEqual(result['trader_emitted_fuse_units'], '0')
        self.assertEqual(result['lp_final_usdc_units'], 250_000 * USDC)
        self.assertEqual(result['reserve_usdc_units'], 0)

    def test_longer_trajectories_preserve_all_ledgers_and_terminal_claims(self):
        for behavior in ('mixed', 'bank-run', 'oracle-gap', 'oracle-outage',
                         'correlated-winners', 'demand-collapse'):
            result = run(Scenario(behavior=behavior, days=125, lp_agents=12,
                                  games_per_day=40, whitelist_day=1, public_day=2,
                                  target_utilization_bps=1000, daily_log=True))
            self.assertTrue(result['conservation_verified'])
            self.assertGreaterEqual(result['lp_min_usdc_units'], 0)
            self.assertTrue(all(int(row['lp_reward_today_fuse_units']) == 0
                                for row in result['daily'] if row['day'] >= 90))
            self.assertEqual(result['lp_unvested_fuse_units'], '0')

    def test_same_seed_reproduces_full_trajectory(self):
        scenario = Scenario(days=12, games_per_day=30, daily_log=True)
        self.assertEqual(run(scenario, True), run(scenario, True))

    def test_market_draws_do_not_change_when_only_lp_rewards_change(self):
        scenario = Scenario(days=12, whitelist_day=14)
        first = run(scenario)
        second = run(replace(scenario, lp_budget_tokens=0))
        for key in ('lp_realized_trading_pnl_usdc_units', 'outcomes', 'accepted_stages'):
            self.assertEqual(first[key], second[key])

    def test_traders_cannot_lose_more_than_funded_cash(self):
        result = run(Scenario(days=60, survival_bps=0, games_per_day=3000))
        self.assertGreater(result['unfunded_games'], 0)
        self.assertLessEqual(result['lp_realized_trading_pnl_usdc_units'], 300 * 1000 * USDC)
        self.assertGreaterEqual(result['trader_final_cash_usdc_units'], 0)

    def test_active_lp_stress_really_exercises_entries_rewards_and_queue(self):
        result = run(Scenario(days=45, behavior='bank-run', games_per_day=3000,
                              daily_trader_inflow_usdc=150_000, correlation_bps=0,
                              whitelist_day=1, public_day=7))
        self.assertGreater(result['participating_external_lps'], 0)
        self.assertGreater(int(result['lp_bootstrap_earned_fuse_units']), 0)
        self.assertGreater(result['peak_pending_requests'], 0)
        self.assertGreater(result['withdrawal_queue_delayed_days'], 0)


if __name__ == '__main__':
    unittest.main()
