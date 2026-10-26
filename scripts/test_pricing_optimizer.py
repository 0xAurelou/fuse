from fractions import Fraction
import random
import unittest

from calibrate_pricing import fit, fit_pinball, survival, survival_frontier, survival_thresholds, choose_width


class PricingOptimizerTests(unittest.TestCase):
    def test_exact_floor_touch_and_small_price_threshold(self):
        rows = [{'entry': 100000000, 'max_move_units': 10000}]
        self.assertEqual(survival_thresholds(rows), [101])
        self.assertEqual(survival(rows, 100), 0)
        self.assertEqual(survival(rows, 101), 1)
        self.assertEqual(fit(rows, 1), 101)
        tiny = [{'entry': 1, 'max_move_units': 0}]
        self.assertEqual(fit(tiny, 1), 1000000)
        self.assertEqual(fit(tiny, 1, maximum=50000), 1)
        self.assertEqual(fit_pinball(tiny, 1, maximum=50000), 50000)

    def test_global_integer_optimum_matches_engine_formula_over_random_paths(self):
        rng = random.Random(20261026)
        for _ in range(100):
            rows = [{'entry': rng.randint(1000000, 90000000), 'max_move_units': rng.randint(0, 8000)} for _ in range(rng.randint(2, 20))]
            frontier = survival_frontier(rows, minimum=3, maximum=120)
            for target in (Fraction(0), Fraction(12, 25), Fraction(1, 2), Fraction(1)):
                def objective(width):
                    survived = sum(row['max_move_units'] < row['entry']*width//1000000 for row in rows)
                    return abs(Fraction(survived, len(rows))-target), width
                expected = min(range(3, 121), key=objective)
                self.assertEqual(choose_width(frontier, target)['width_ppm'], expected)

    def test_closed_form_quantile_globally_minimizes_convex_loss(self):
        rng = random.Random(11)
        for _ in range(50):
            rows = [{'entry': 1000000, 'max_move_units': rng.randint(0, 140)} for _ in range(13)]
            thresholds = survival_thresholds(rows)
            for target in (Fraction(0), Fraction(12, 25), Fraction(1, 2), Fraction(1)):
                def loss(width):
                    return sum(target*max(value-width, 0)+(1-target)*max(width-value, 0) for value in thresholds)
                expected = min(range(3, 121), key=lambda width: (loss(width), width))
                self.assertEqual(fit_pinball(rows, target, minimum=3, maximum=120), expected)

    def test_ties_make_target_unattainable_despite_convex_optimality(self):
        rows = [{'entry': 1000000, 'max_move_units': 99} for _ in range(10)]
        frontier = survival_frontier(rows)
        self.assertEqual([point['survived'] for point in frontier], [0, 10])
        self.assertEqual(fit(rows, .48), 1)
        self.assertEqual(fit_pinball(rows, .48), 100)
        self.assertNotIn(Fraction(12, 25), [Fraction(point['survived'], point['windows']) for point in frontier])

    def test_invalid_inputs_and_bounds_fail_closed(self):
        rows = [{'entry': 1000000, 'max_move_units': 0}]
        for target in (-.1, 1.1):
            with self.assertRaises(ValueError):
                fit(rows, target)
        for lower, upper in ((0, None), (5, 4)):
            with self.assertRaises(ValueError):
                fit(rows, .48, minimum=lower, maximum=upper)
        for bad in ([], [{'entry': 0, 'max_move_units': 1}], [{'entry': 1, 'max_move_units': -1}], [{'entry': 1.0, 'max_move_units': 0}]):
            with self.assertRaises(ValueError):
                fit(bad, .48)


if __name__ == '__main__':
    unittest.main()
