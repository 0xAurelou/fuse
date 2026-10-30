import unittest
from dataclasses import replace

from stress_loss_rewards import (
    GENESIS, MINING, POLICIES, Reserve, Scenario, Stage, TOKEN, USDC,
    allocations, attack_case, evaluate, scheduled_cap, score, trading_path,
)


class LossRewardStressTests(unittest.TestCase):
    def test_nine_times_only_for_equal_stake_and_duration(self):
        win = Stage(0, 100 * USDC, True, 30000)
        loss = replace(win, account=1, won=False)
        self.assertEqual(score(loss, POLICIES['loss9']), 9 * score(win, POLICIES['loss9']))
        early = replace(loss, duration=1)
        self.assertLess(score(early, POLICIES['loss9']), score(win, POLICIES['loss9']))
        values, _ = allocations([win, loss], 'loss9', 100 * TOKEN)
        self.assertEqual(values[1], 90 * TOKEN)
        self.assertEqual(values[0], 10 * TOKEN)

    def test_outcome_ratio_does_not_fix_total_loss_pool_share(self):
        stages = [Stage(0, USDC, True, 30000), Stage(1, USDC, False, 15000)]
        _, stats = allocations(stages, 'loss9', 10**30)
        self.assertAlmostEqual(stats['loss_weight_share'], 4.5 / 5.5)

    def test_activity_rate_and_weight_magnitude_are_separate_from_ratio(self):
        stages = [Stage(0, USDC, True, 30000)]
        current, _ = allocations(stages, 'current', 10**30)
        proposal, _ = allocations(stages, 'loss9', 10**30)
        controlled, _ = allocations(stages, 'loss9', 10**30, common_budget=True)
        self.assertEqual(current[0], 100 * TOKEN)
        self.assertEqual(proposal[0], 10 * TOKEN)
        self.assertEqual(controlled[0], current[0])
        self.assertEqual(allocations([], 'loss9', 10**30)[0], {})

    def test_go_denominator_equivalence_including_zero_bonus_factor(self):
        stage = Stage(0, 123456789, False, 23456)
        raw_go_score = stage.stake * stage.duration * 9000 * 10000
        go_budget = raw_go_score * (100 * TOKEN) // 3_000_000_000_000_000_000
        values, _ = allocations([stage], 'loss9', 10**40)
        self.assertEqual(values[0], go_budget)

    def test_epoch_snapshot_is_order_independent_and_split_invariant(self):
        def redeem(order, split):
            reserve = Reserve(1000 * USDC)
            reserve.distribute({0: 123456 * TOKEN, 1: 987654 * TOKEN})
            epoch = reserve.open()
            for account in order:
                amount = reserve.tokens[account]
                if split:
                    reserve.request(epoch, account, amount // 3)
                    reserve.request(epoch, account, amount - amount // 3)
                else:
                    reserve.request(epoch, account, amount)
            reserve.claim(epoch)
            reserve.check()
            return dict(reserve.proceeds), reserve.balance, reserve.supply
        self.assertEqual(redeem([0, 1], False), redeem([1, 0], True))

    def test_pending_claims_do_not_back_later_epochs(self):
        reserve = Reserve(1000 * USDC)
        reserve.distribute({0: 100_000_000 * TOKEN, 1: 100_000_000 * TOKEN})
        first = reserve.open(penalty=0)
        reserve.request(first, 0, reserve.tokens[0])
        self.assertEqual(reserve.outstanding, 100 * USDC)
        second = reserve.open(penalty=0)
        self.assertEqual(reserve.epochs[second]['backing'], 900 * USDC)
        reserve.request(second, 1, reserve.tokens[1])
        reserve.claim(second)
        reserve.claim(first)
        self.assertEqual(reserve.paid, 200 * USDC)
        reserve.check()

    def test_full_escrow_supply_counts_and_emissions_do_not_mint(self):
        reserve = Reserve(1000 * USDC)
        reserve.distribute({0: 100_000_000 * TOKEN})
        self.assertEqual(reserve.supply, GENESIS)
        epoch = reserve.open(penalty=1000)
        reserve.request(epoch, 0, reserve.tokens[0])
        reserve.claim(epoch)
        self.assertEqual(reserve.paid, 90 * USDC)
        self.assertEqual(reserve.supply, 900_000_000 * TOKEN)

    def test_no_demand_and_no_backing_cannot_generate_redemption_cash(self):
        s = Scenario(days=3, games_per_day=0)
        path = trading_path(s)
        for policy in POLICIES:
            result = evaluate(s, path, policy)
            self.assertEqual(result['emitted_fuse_units'], '0')
            self.assertEqual(result['redeemed_usdc_units'], 0)
        r = Reserve()
        r.distribute({0: TOKEN})
        epoch = r.open()
        r.request(epoch, 0, TOKEN)
        r.claim(epoch)
        self.assertEqual(r.paid, 0)

    def test_pairing_changes_rewards_without_changing_lp_funding(self):
        s = Scenario(days=5)
        path = trading_path(s)
        values = [evaluate(s, path, p, common_budget=True) for p in POLICIES]
        for key in ('lp_final_usdc_units', 'reserve_funded_usdc_units'):
            self.assertEqual(len({x[key] for x in values}), 1)
        emitted = [int(x['emitted_fuse_units']) for x in values]
        paid = [x['redeemed_usdc_units'] for x in values]
        # Each epoch floors once per recipient, as does reserve redemption.
        self.assertLessEqual(max(emitted) - min(emitted), s.traders * s.days)
        self.assertLessEqual(max(paid) - min(paid), s.traders)

    def test_late_farming_can_transfer_old_backing_without_insolvency(self):
        empty = attack_case('loss9', 0, 100, 29999)
        mature = attack_case('loss9', 100_000_000, 100, 29999)
        self.assertLess(empty['cash_pnl_usdc_units'], 0)
        self.assertGreater(mature['cash_pnl_usdc_units'], 0)
        self.assertLess(mature['redeemed_usdc_units'], 100_000_035 * USDC)
        instant = attack_case('loss9', 100_000_000, 100, 1)
        self.assertLess(instant['cash_pnl_usdc_units'], 0)

    def test_lp_rebate_is_equity_and_separate_from_cash(self):
        plain = attack_case('loss9', 10_000_000, 100, 29999)
        lp_owned = attack_case('loss9', 10_000_000, 100, 29999, lp_owned_bps=9000)
        self.assertEqual(plain['cash_pnl_usdc_units'], lp_owned['cash_pnl_usdc_units'])
        self.assertLess(lp_owned['cash_pnl_usdc_units'], 0)
        self.assertGreater(lp_owned['wealth_pnl_usdc_units'], 0)

    def test_all_winning_admissions_remain_funded_at_low_capital(self):
        s = Scenario(days=6, lp_usdc=1000, survival_bps=10000)
        path = trading_path(s)
        self.assertGreater(path['rejected'], 0)
        self.assertGreaterEqual(path['lp_final'], 100 * USDC)
        self.assertEqual(path['reserve_funded'], 0)
        for timing in ('end', 'daily'):
            self.assertTrue(evaluate(s, path, 'loss9', redemption=timing)['conservation_verified'])

    def test_finite_emission_slots_decay_and_do_not_catch_up(self):
        caps = [scheduled_cap(i) for i in range(1, 181)]
        self.assertLessEqual(sum(caps), MINING)
        self.assertTrue(all(a >= b for a, b in zip(caps, caps[1:])))
        self.assertEqual(scheduled_cap(1), 10_000_000 * TOKEN)
        self.assertEqual(scheduled_cap(2), 9_660_000 * TOKEN)
        self.assertEqual(scheduled_cap(181), 0)


if __name__ == '__main__':
    unittest.main()
