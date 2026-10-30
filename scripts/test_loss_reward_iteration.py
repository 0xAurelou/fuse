import unittest
from dataclasses import replace

from iterate_loss_rewards import (
    GENESIS, InventoryReserve, Policy, Quoter, Scenario, Stage, TOKEN, USDC,
    evaluate, funded_policies, hedge_case, trading_path,
)


class FundedRewardTests(unittest.TestCase):
    def ledger(self, policy=None):
        policy = policy or Policy()
        reserve = InventoryReserve(policy.seed_usdc * USDC, policy.mining_tokens)
        return reserve, Quoter(policy, reserve)

    def redeem(self, reserve):
        epoch = reserve.open(penalty=0)
        for account, amount in list(reserve.tokens.items()):
            if amount:
                reserve.request(epoch, account, amount)
        reserve.claim(epoch)

    def test_no_funding_cannot_quote_a_dollar_reward(self):
        p = replace(Policy(), seed_usdc=0, launch_budget_usdc=0)
        reserve, quoter = self.ledger(p)
        self.assertIsNone(quoter.quote(0, 100 * USDC))
        reserve.fund(100 * USDC)
        self.assertIsNone(quoter.quote(0, 100 * USDC))
        quoter.credit(100 * USDC)
        self.assertIsNotNone(quoter.quote(0, 100 * USDC))

    def test_quote_reserves_full_losing_budget_before_outcome(self):
        p = replace(Policy(), launch_budget_usdc=5)
        _, q = self.ledger(p)
        first = q.quote(0, 100 * USDC)
        self.assertEqual(first.loss_value, 5 * USDC)
        self.assertEqual(q.held_launch, 5 * USDC)
        self.assertIsNone(q.quote(1, 100 * USDC))

    def test_winner_frees_unused_capacity_and_gets_one_ninth(self):
        reserve, q = self.ledger()
        offer = q.quote(0, 100 * USDC)
        self.assertEqual(offer.win_value, offer.loss_value // 9)
        q.settle([offer], [Stage(0, 100 * USDC, True, 30000)])
        self.assertEqual(q.held_launch, 0)
        self.assertEqual(q.held_tokens, 0)
        self.assertEqual(q.launch_left + q.launch_paid, 2500 * USDC)
        self.redeem(reserve)
        self.assertGreaterEqual(reserve.proceeds[0], offer.win_value)

    def test_wallet_cap_is_reserved_before_outcome_and_global_cap_remains(self):
        reserve, q = self.ledger()
        a, b = q.quote(0, 100 * USDC), q.quote(0, 100 * USDC)
        self.assertIsNone(q.quote(0, 100 * USDC))
        self.assertIsNotNone(q.quote(1, 100 * USDC))
        q.settle([a, b], [Stage(0, 100 * USDC, False, 1), Stage(0, 100 * USDC, False, 1)])
        self.assertEqual(q.wallet_launch_paid[0], 10 * USDC)
        self.assertIsNone(q.quote(0, 100 * USDC))
        q.check()

    def test_actual_reward_budget_ignores_new_unfunded_lp_profit(self):
        p = replace(Policy(), launch_budget_usdc=0)
        reserve, q = self.ledger(p)
        self.assertIsNone(q.quote(0, 100 * USDC))
        reserve.fund(100 * USDC)
        q.credit(100 * USDC)
        self.assertEqual(q.earned_left, 50 * USDC)
        self.assertIsNotNone(q.quote(0, 100 * USDC))

    def test_continuity_buffer_is_funded_once_and_cannot_exceed_seed(self):
        p = funded_policies()[1]
        reserve, q = self.ledger(p)
        self.assertEqual(reserve.balance, 125_000 * USDC)
        self.assertEqual(q.earned_left, 10_000 * USDC)
        self.assertEqual(q.launch_left, 10_000 * USDC)
        self.assertEqual(q.earned_credited, 10_000 * USDC)
        with self.assertRaises(ValueError):
            replace(p, ongoing_seed_budget_usdc=120_000)

    def test_mature_backing_changes_token_count_not_dollar_promise(self):
        values = []
        tokens = []
        for seed in (25_000, 1_000_000, 100_000_000):
            p = replace(Policy(), seed_usdc=seed)
            reserve, q = self.ledger(p)
            stage = Stage(0, 100 * USDC, False, 1)
            offer = q.quote(0, stage.stake)
            q.settle([offer], [stage])
            tokens.append(reserve.emitted)
            self.redeem(reserve)
            values.append(reserve.proceeds[0])
        self.assertEqual(values, [5 * USDC] * 3)
        self.assertGreater(tokens[0], tokens[1])
        self.assertGreater(tokens[1], tokens[2])

    def test_candidate_standard_rate_stays_two_percent_at_maturity(self):
        for seed in (100_000, 125_000, 150_000, 100_000_000):
            p = replace(funded_policies()[1], seed_usdc=seed, launch_budget_usdc=0)
            reserve, q = self.ledger(p)
            offer = q.quote(0, 100 * USDC)
            self.assertEqual(offer.loss_value, 2 * USDC)
            q.settle([offer], [Stage(0, 100 * USDC, False, 1)])
            self.redeem(reserve)
            self.assertEqual(reserve.proceeds[0], 2 * USDC)

    def test_two_percent_fits_assumed_profit_budget_but_three_needs_subsidy(self):
        p = funded_policies()[1]
        survival = 0.48
        funding_per_dollar = (1 - 2 * survival) * .35 * p.fee_budget_bps / 10000
        expected_reward = lambda loss_bps: ((1 - survival) + survival / 9) * loss_bps / 10000
        self.assertLess(expected_reward(200), funding_per_dollar)
        self.assertGreater(expected_reward(300), funding_per_dollar)

    def test_early_genuine_loss_gets_same_bounded_reward(self):
        paid = []
        for duration in (1, 15000, 29999):
            reserve, q = self.ledger()
            offer = q.quote(0, 100 * USDC)
            q.settle([offer], [Stage(0, 100 * USDC, False, duration)])
            self.redeem(reserve)
            paid.append(reserve.proceeds[0])
        self.assertEqual(paid, [5 * USDC] * 3)

    def test_token_inventory_cannot_be_overpromised(self):
        p = replace(Policy(), launch_token_cap=100 * TOKEN)
        reserve, q = self.ledger(p)
        self.assertIsNone(q.quote(0, 100 * USDC))
        q.credit(100 * USDC)
        reserve.emitted = p.mining_tokens - 10 * TOKEN
        reserve.tokens[7] = reserve.emitted
        self.assertIsNone(q.quote(0, 100 * USDC))
        q.check()

    def test_all_genesis_counts_under_both_allocation_variants(self):
        for mining in (600_000_000, 950_000_000):
            p = replace(Policy(), mining_tokens=mining * TOKEN)
            reserve, q = self.ledger(p)
            self.assertEqual(reserve.supply, GENESIS)
            offer = q.quote(0, 100 * USDC)
            q.settle([offer], [Stage(0, 100 * USDC, False, 1)])
            self.redeem(reserve)
            self.assertEqual(reserve.proceeds[0], 5 * USDC)
            reserve.check()

    def test_positive_new_funding_cannot_break_reserved_inventory(self):
        reserve, q = self.ledger()
        offer = q.quote(0, 100 * USDC)
        reserve.fund(100 * USDC)
        q.settle([offer], [Stage(0, 100 * USDC, False, 1)])
        self.assertLessEqual(reserve.emitted, offer.max_tokens)
        self.redeem(reserve)
        self.assertGreaterEqual(reserve.proceeds[0], 5 * USDC)

    def test_zero_cost_hedge_is_explicitly_not_claimed_safe(self):
        for split in (False, True):
            case = hedge_case(Policy(), split_wallets=split)
            self.assertEqual(case['pair_trading_pnl_usdc_units'], 0)
            self.assertGreater(case['pair_reward_usdc_units'], 0)

    def test_many_wallets_cannot_overdraw_global_promised_budget(self):
        reserve, q = self.ledger()
        stages = [Stage(i, 100 * USDC, False, 1) for i in range(1000)]
        offers = [q.quote(s.account, s.stake) for s in stages]
        self.assertEqual(sum(o is not None for o in offers), 500)
        q.settle(offers, stages)
        self.redeem(reserve)
        self.assertEqual(q.launch_paid, 2500 * USDC)
        self.assertEqual(reserve.paid, 2500 * USDC)
        self.assertIsNone(q.quote(1001, 100 * USDC))
        q.check()

    def test_conservation_and_accepted_quote_minima_across_timing(self):
        s = Scenario(days=6)
        path = trading_path(s)
        daily = evaluate(Policy(), s, path)
        held = evaluate(Policy(), s, path, timing='end')
        self.assertTrue(daily['conservation_verified'])
        self.assertTrue(held['conservation_verified'])
        self.assertGreaterEqual(held['actual_rewards_usdc_units'], held['quote_minimum_usdc_units'])
        self.assertEqual(daily['lp_final_usdc_units'], held['lp_final_usdc_units'])

    def test_no_demand_leaves_external_seed_and_budget_intact(self):
        s = Scenario(days=3, games_per_day=0)
        result = evaluate(Policy(), s, trading_path(s))
        self.assertEqual(result['reserve_remaining_usdc_units'], 25_000 * USDC)
        self.assertEqual(result['actual_rewards_usdc_units'], 0)
        self.assertEqual(result['emitted_fuse_units'], '0')

    def test_campaign_expiry_stops_only_new_offers(self):
        p = replace(Policy(), days=1)
        s = Scenario(days=3)
        result = evaluate(p, s, trading_path(s))
        self.assertGreater(result['actual_rewards_usdc_units'], 0)
        self.assertEqual(result['timeline'][1]['eligible'], 0)
        self.assertEqual(result['timeline'][2]['eligible'], 0)


if __name__ == '__main__':
    unittest.main()
