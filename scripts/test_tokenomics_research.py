import unittest
from simulate_tokenomics import Scenario,run,reserve_amount,emission_budgets,MINING
from calibrate_pricing import windows,survival,fit

class ResearchTests(unittest.TestCase):
 def test_no_demand_cannot_issue_rewards_or_create_backing(self):
  result=run(Scenario(behavior='no-demand',days=10))
  self.assertEqual(result['emitted_fuse_units'],'0');self.assertEqual(result['reserve_usdc_units'],0);self.assertEqual(result['lp_final_usdc_units'],250000000000)
 def test_correlated_winners_do_not_pay_more_than_lp(self):
  result=run(Scenario(behavior='correlated-winners',initial_lp_usdc=100000,days=10))
  self.assertTrue(result['conservation_verified']);self.assertGreater(result['rejected_stages'],0);self.assertGreaterEqual(result['lp_min_usdc_units'],0)
 def test_reserve_recovers_hwm_and_retains_two_times_capital(self):
  self.assertEqual(reserve_amount(900,1000,0,10000,100,3500),(0,0))
  self.assertEqual(reserve_amount(1000,1000,0,2000,1000,3500),(0,0))
  amount,consumed=reserve_amount(1000,1000,0,3000,1000,3500)
  self.assertEqual(amount,350);self.assertEqual(consumed,1000)
  self.assertEqual(reserve_amount(1000,1000,consumed,2650,1000,3500),(0,0))
 def test_emission_schedules_have_a_finite_cap(self):
  for half_life in [10,20,22,30,35]:self.assertLessEqual(sum(emission_budgets(180,half_life)),MINING)
 def test_barrier_touch_and_expiry_use_exact_integer_rules(self):
  observed=[(t,100000000) for t in range(0,61000,1000)];observed[10]=(10000,100010000)
  rows=windows(observed)
  self.assertEqual(len(rows),2);self.assertEqual(survival(rows,100),.5);self.assertEqual(survival(rows,101),1)
  self.assertEqual(fit(rows,.48),1)
 def test_gap_is_not_interpolated_into_survival(self):
  rows=windows([(0,100000000),(1000,100000000),(29000,100000000),(30000,100000000),(60000,100000000)])
  self.assertEqual(rows,[])
 def test_market_and_redemption_conserve_assets_across_seeds(self):
  for seed in range(5):self.assertTrue(run(Scenario(seed=seed,days=12,unlock_day=3,market_depth_usdc=10000))['conservation_verified'])

if __name__=='__main__':unittest.main()
