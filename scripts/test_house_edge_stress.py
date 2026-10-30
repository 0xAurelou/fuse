import unittest
from fractions import Fraction

from stress_house_edge import MULTIPLIERS, economics


class HouseEdgeSensitivityTests(unittest.TestCase):
    def test_each_quote_probability_matches_assumed_nominal_edge(self):
        for edge in (700, 850, 1000):
            for multiplier in MULTIPLIERS:
                row = economics(edge, multiplier)
                self.assertEqual(1 - row['survival'] * multiplier, Fraction(edge, 10000))

    def test_standard_two_percent_reward_preserves_positive_net_edge(self):
        for edge in (700, 850, 1000):
            for multiplier in MULTIPLIERS:
                row = economics(edge, multiplier)
                self.assertGreater(row['effective_house_edge'], 0)
                self.assertLess(row['effective_house_edge'], row['gross_house_edge'])
        self.assertAlmostEqual(float(economics(700)['effective_house_edge']), .05826666666666667)
        self.assertEqual(economics(1000)['effective_house_edge'], Fraction(88, 1000))

    def test_two_times_welcome_has_negative_player_ev_at_seven_to_ten_percent(self):
        for edge in (700, 850, 1000):
            self.assertGreater(economics(edge, 2, 1000)['effective_house_edge'], 0)

    def test_high_multiplier_welcome_can_still_have_positive_player_ev(self):
        self.assertLess(economics(700, 5, 1000)['effective_house_edge'], 0)
        self.assertLess(economics(850, 10, 1000)['effective_house_edge'], 0)
        for multiplier in MULTIPLIERS:
            self.assertGreater(economics(1000, multiplier, 1000)['effective_house_edge'], 0)

    def test_operator_income_is_five_percent_of_profit_not_stake(self):
        self.assertEqual(economics(700)['protocol_share_of_turnover'], Fraction(35, 10000))
        self.assertEqual(economics(1000)['protocol_share_of_turnover'], Fraction(50, 10000))

    def test_invalid_inputs_are_rejected(self):
        for args in ((-1, 2, 200), (10000, 2, 200), (700, 0, 200), (700, 2, 10001)):
            with self.assertRaises(ValueError):
                economics(*args)


if __name__ == '__main__':
    unittest.main()
