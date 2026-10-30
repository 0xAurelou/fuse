import unittest
from release_lp_bootstrap import (BUDGET, DAY, DAYS, TOKEN, USDC, VESTING,
    Campaign, Segment, bootstrap_evidence, epoch_entitlements, scheduled, taper)


def segment(equity=250_000, liability=50_000, seconds=DAY, owner='lp'):
    return Segment(seconds, {owner: equity*USDC}, frozenset({owner}), liability*USDC)


class BootstrapTests(unittest.TestCase):
    def test_complete_schedule_exactly_finite_and_declining(self):
        caps = [scheduled(i) for i in range(DAYS)]
        self.assertEqual(sum(caps), BUDGET)
        self.assertTrue(all(a > b > 0 for a, b in zip(caps, caps[1:])))
        for invalid in (-1, DAYS, True, 1.5):
            with self.assertRaises(ValueError):
                scheduled(invalid)

    def test_threshold_taper_and_full_utilization(self):
        self.assertEqual(taper(250_000*USDC), 1)
        self.assertEqual(taper(3_000_000*USDC), 0)
        for dollars in (0, 100_000, 250_000, 500_000, 2_999_999, 3_000_000, 5_000_000):
            row = epoch_entitlements(0, [Segment(DAY, {'lp': dollars*USDC},
                frozenset({'lp'}), dollars*USDC//5)])
            expected = int(scheduled(0)*taper(dollars*USDC)) if dollars else 0
            self.assertEqual(row['earned_fuse_units'], expected)

    def test_no_demand_or_protocol_capital_cannot_mine(self):
        self.assertEqual(epoch_entitlements(0, [segment(liability=0)])['earned_fuse_units'], 0)
        row = Segment(DAY, {'protocol': 250_000*USDC}, frozenset(), 50_000*USDC)
        self.assertEqual(epoch_entitlements(0, [row])['earned_fuse_units'], 0)
        row = Segment(DAY, {'protocol': 125_000*USDC, 'lp': 125_000*USDC}, frozenset({'lp'}), 50_000*USDC)
        self.assertEqual(epoch_entitlements(0, [row])['earned_fuse_units'], scheduled(0)//2)

    def test_utilization_scales_and_cannot_exceed_cap(self):
        half = epoch_entitlements(0, [segment(liability=25_000)])
        full = epoch_entitlements(0, [segment(liability=250_000)])
        self.assertEqual(half['earned_fuse_units'], scheduled(0)//2)
        self.assertEqual(full['earned_fuse_units'], scheduled(0))

    def test_point_in_time_withdrawal_cannot_reprice_past_capital_time(self):
        # 12h at the threshold pays nothing for that time. 12h at 250k can
        # earn only against its actual capital-time; an end-of-day TVL would
        # incorrectly pay the full cap. No exit delay is added by this model.
        row = epoch_entitlements(0, [segment(3_000_000, 600_000, DAY//2),
                                     segment(250_000, 50_000, DAY//2)])
        self.assertEqual(row['earned_fuse_units'], scheduled(0)//13)
        self.assertEqual(row, epoch_entitlements(0, [segment(3_000_000, 600_000, DAY//4),
            segment(3_000_000, 600_000, DAY//4), segment(250_000, 50_000, DAY//2)]))

    def test_wallet_splits_cannot_increase_aggregate_subsidy(self):
        whole = epoch_entitlements(0, [segment(777_777, 155_555)])['earned_fuse_units']
        for wallets in (2, 3, 100):
            total = 777_777*USDC
            split = {str(i): total//wallets + (i < total % wallets) for i in range(wallets)}
            row = epoch_entitlements(0, [Segment(DAY, split, frozenset(split), 155_555*USDC)])
            self.assertLessEqual(row['earned_fuse_units'], whole)
            self.assertLess(whole-row['earned_fuse_units'], wallets)

    def test_requested_exit_stops_earning_but_earlier_rights_survive_exit(self):
        row = epoch_entitlements(0, [segment(seconds=DAY//2),
            Segment(DAY//2, {'lp': 250_000*USDC}, frozenset(), 50_000*USDC)])
        self.assertEqual(row['earned_fuse_units'], scheduled(0)//2)
        campaign = Campaign()
        earned = campaign.close(0, [segment()])['entitlements']['lp']
        campaign.close(1, [Segment(DAY, {}, frozenset(), 0)])
        with self.assertRaises(ValueError):
            campaign.claim(0, 'lp', DAY+VESTING-1)
        self.assertEqual(campaign.claim(0, 'lp', DAY+VESTING), earned)
        with self.assertRaises(ValueError):
            campaign.claim(0, 'lp', DAY+VESTING)

    def test_wholly_self_funded_activity_is_still_bounded_no_restart_or_catchup(self):
        campaign = Campaign()
        for epoch in range(DAYS):
            campaign.close(epoch, [segment(liability=250_000)])
            campaign.claim(epoch, 'lp', (DAYS+31)*DAY)
        self.assertEqual(campaign.paid, BUDGET)
        with self.assertRaises(ValueError):
            campaign.close(0, [segment()])
        with self.assertRaises(ValueError):
            campaign.close(DAYS, [segment()])
        other = Campaign()
        other.close(2, [segment()])
        with self.assertRaises(ValueError):
            other.close(1, [segment()])
        self.assertEqual(other.earned, scheduled(2))

    def test_incomplete_or_unfunded_or_fabricated_inputs_rejected(self):
        for segments in ([segment(seconds=DAY-1)], [segment(seconds=DAY+1)],
            [segment(liability=250_001)], [segment(equity=-1, liability=0)],
            [Segment(DAY, {'lp': USDC}, frozenset({'stranger'}), 0)],
            [Segment(DAY, {'lp': USDC}, frozenset({'lp'}), -1)]):
            with self.assertRaises(ValueError):
                epoch_entitlements(0, segments)

    def test_backing_equivalent_is_not_new_operating_cash_or_a_return_promise(self):
        evidence = bootstrap_evidence()
        self.assertEqual(evidence['initial_backing_equivalent_max_usdc_units'], 6250*USDC)
        self.assertFalse(evidence['production_implemented'])
        self.assertFalse(evidence['future_dollar_value_bounded'])
        rows = evidence['constant_fully_external_at_target_utilization']
        self.assertEqual(rows[0]['earned_fuse_units'], 50_000_000*TOKEN)
        self.assertEqual(rows[-2]['earned_fuse_units'], 0)
        self.assertEqual(rows[-1]['earned_fuse_units'], 0)


if __name__ == '__main__':
    unittest.main()
