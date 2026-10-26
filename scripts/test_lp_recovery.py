import unittest
from lp_risk import DAY, RiskGuard, RiskPolicy
from optimize_lp_recovery import candidates, metrics, rank
from simulate_lp_incentives import Scenario, run


class RecoveryOptimizationTests(unittest.TestCase):
    def probe_guard(self):
        policy = RiskPolicy(pause_drawdown_bps=1000, hard_drawdown_bps=2000,
                            resume_drawdown_bps=500, probe_loss_bps=25,
                            probe_max_loss_bps=100)
        guard = RiskGuard(policy, 1_000_000, 1_000_000)
        guard.reserve(0, 1_000_000, 1_000_000, 100_000)
        guard.settle(30, 100_000, 900_000, 1_000_000)
        guard.capacity(3 * DAY, 900_000, 1_000_000)
        return guard

    def test_adaptation_requires_realized_gains_and_keeps_spent_losses(self):
        guard = self.probe_guard()
        assets, at = 900_000, 3 * DAY
        for i in range(6):
            guard.reserve(at, assets, 1_000_000, 1000)
            assets += 500
            at += 30
            guard.settle(at, 250, assets, 1_000_000)
            if i == 1:
                self.assertEqual(guard.probe_budget_bps, 25)
            if i == 2:
                self.assertEqual(guard.probe_budget_bps, 50)
        self.assertEqual(guard.probe_budget_bps, 100)
        guard.reserve(at, assets, 1_000_000, 1000)
        assets -= 500
        guard.settle(at + 30, 500, assets, 1_000_000)
        self.assertEqual(guard.probe_budget_bps, 25)
        # 1500 prior debits + 500 loss still consume the original 2250 budget.
        self.assertEqual(guard.capacity(at + 31, assets, 1_000_000)[0], 250)

    def test_small_positive_or_zero_batches_do_not_fake_a_regime_change(self):
        guard = self.probe_guard()
        assets, at = 900_000, 3 * DAY
        for gain in (1, 1, 1, 0, 0):
            guard.reserve(at, assets, 1_000_000, 1)
            assets += gain
            at += 30
            guard.settle(at, 0, assets, 1_000_000)
        self.assertEqual(guard.probe_budget_bps, 25)

    def test_adaptive_setting_cannot_relax_the_hard_floor(self):
        guard = self.probe_guard()
        guard.probe_budget_bps = 100
        self.assertLessEqual(guard.capacity(4 * DAY, 800_000, 1_000_000)[0], 0)
        with self.assertRaises(ValueError):
            guard.reserve(4 * DAY, 800_000, 1_000_000, 1)

    def test_reopening_is_distinct_from_full_nav_recovery(self):
        guard = self.probe_guard()
        guard.observe(4 * DAY, 950_000, 1_000_000)
        self.assertEqual(guard.mode, 'open')
        self.assertEqual(guard.summary()['nav_recovered_episodes'], 0)
        guard.observe(5 * DAY, 1_000_000, 1_000_000)
        self.assertEqual(guard.summary()['nav_recovered_episodes'], 1)

    def test_no_demand_cannot_restore_lost_nav_and_is_censored(self):
        scenario = Scenario(days=45, games_per_day=3000, batches_per_day=12,
                            daily_trader_inflow_usdc=150000, correlation_bps=0,
                            winner_cluster_days=(2, 3, 4, 5), demand_stops_day=6,
                            risk_policy=RiskPolicy(pause_drawdown_bps=500, hard_drawdown_bps=2000,
                                                   resume_drawdown_bps=200), daily_log=True)
        result = run(scenario)
        measured = metrics(result)
        self.assertGreater(measured['nav_unrecovered_episodes'], 0)
        self.assertEqual(measured['penalized_worst_days'], 45)
        self.assertTrue(all(row['lp_usdc_units'] == result['daily'][6]['lp_usdc_units']
                            for row in result['daily'][6:]))

    def test_search_keeps_floor_and_reopening_threshold_fixed(self):
        options = candidates()
        self.assertEqual(len(options), 24)
        self.assertEqual(len({p.name for p in options}), 24)
        self.assertTrue(all(p.hard_drawdown_bps == 2000 and p.resume_drawdown_bps == 500 for p in options))
        self.assertEqual(sum(p.name == 'baseline' for p in options), 1)

    def test_ranking_rejects_fast_but_unsafe_or_starved_candidates(self):
        policies = [RiskPolicy(name=name) for name in ('baseline', 'fast-unsafe', 'starved')]
        training = []
        for policy in policies:
            for world in ('funded-steady', 'cluster-10d'):
                row = {'policy': policy.name, 'environment': world, 'seed': 1,
                       'accepted_stages': 100 if policy.name != 'starved' else 1,
                       'penalized_recovery_days': [10 if policy.name == 'baseline' else 1],
                       'nav_unrecovered_episodes': 0, 'max_drawdown': .1 if policy.name != 'fast-unsafe' else .21,
                       'overdue_pending_requests': 0, 'payouts_funded': True, 'ledgers_conserved': True}
                training.append({'metrics': row})
        ranking = rank(training, policies)
        self.assertEqual(ranking[0]['policy']['name'], 'baseline')
        self.assertTrue(ranking[0]['training_feasible'])
        self.assertTrue(all(not row['training_feasible'] for row in ranking[1:]))


if __name__ == '__main__':
    unittest.main()
