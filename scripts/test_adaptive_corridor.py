from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from adaptive_corridor import (evaluate, features, fit_and_evaluate, fit_models,
                               fit_scale, pinball, predict, replay,
                               required_width, shape)


def row(at=0, move=100, vol=100, trend=0, jump=0):
    return dict(start=at, expiry=at + 30_000, valid=True, entry=1_000_000,
                move=move, lag_features=dict(vol_bps=vol / 100, net_bps=0,
                                             efficiency=0, max_step_bps=jump / 100),
                adaptive_features=dict(vol_60_ppm=vol, vol_300_ppm=vol,
                                       trend_60_ppm=trend, jump_60_ppm=jump))


class AdaptiveCorridorTests(unittest.TestCase):
    def test_scalar_fit_minimizes_continuous_pinball_loss(self):
        rows = [row(move=m, vol=v) for m, v in ((10, 1), (50, 2), (12, 3), (80, 8))]
        model = dict(family='volatility', fast_weight=0, trend_weight=0,
                     jump_weight=0, maximum_width_ppm=50_000)
        fitted = fit_scale(rows, model, .48)
        loss = lambda a: sum(pinball(required_width(r), a * shape(r, model), .48) for r in rows)
        for scale in (0, 1, 4, 8, 11, 15, 26, 50):
            self.assertLessEqual(loss(fitted['scale']), loss(scale) + 1e-10)

    def test_exact_touch_quantization_and_cap_are_scored(self):
        sample = row(move=100)
        model = dict(family='fixed', scale=100, maximum_width_ppm=1000)
        self.assertEqual(required_width(sample), 101)
        self.assertEqual(evaluate([sample], model, .48)['survived'], 0)
        model['scale'] = 100.01
        self.assertEqual(evaluate([sample], model, .48)['survived'], 1)
        model.update(scale=5000, maximum_width_ppm=100)
        self.assertEqual(predict(sample, model), (100, True))
        self.assertEqual(evaluate([sample], model, .48)['capped_windows'], 1)

    def test_features_and_predictions_ignore_prices_at_and_after_entry(self):
        rows = [dict(start=i * 30_000, expiry=(i + 1) * 30_000, valid=True) for i in range(20)]
        paired = [(at, 100_000_000 + (at // 1000) ** 2) for at in range(0, 600_000, 1000)]
        before, after = deepcopy(rows), deepcopy(rows)
        changed = [(at, p if at < 360_000 else p * 3) for at, p in paired]
        features(before, paired, 0)
        features(after, changed, 0)
        self.assertEqual(before[12]['adaptive_features'], after[12]['adaptive_features'])
        self.assertNotEqual(before[13]['adaptive_features'], after[13]['adaptive_features'])
        model = dict(family='adaptive', fast_weight=.5, trend_weight=1,
                     jump_weight=.5, scale=2, maximum_width_ppm=50_000)
        self.assertEqual(predict(before[12], model), predict(after[12], model))
        rows[8]['valid'] = False
        features(rows, paired, 0)
        self.assertIsNone(rows[12]['adaptive_features'])
        self.assertIsNotNone(rows[19]['adaptive_features'])
        with self.assertRaises(ValueError):
            predict(rows[12], model)

    def test_formula_can_recover_volatility_trend_and_jump_shape(self):
        rows = []
        for i in range(90):
            vol, trend, jump = 100 + (i % 5) * 10, (i % 3) * 100, (i % 2) * 50
            # Required width is precisely 2 * (vol + trend + 0.5 * jump).
            rows.append(row(i * 30_000, int(2 * (vol + trend + .5 * jump)) - 1,
                            vol, trend, jump))
        models = fit_models(rows, .48, 50_000)
        self.assertAlmostEqual(models['adaptive']['training_continuous_pinball_ppm'], 0)
        self.assertGreater(models['fixed']['training_continuous_pinball_ppm'], 0)
        for r in rows:
            self.assertEqual(predict(r, models['adaptive'])[0], required_width(r))

    def test_later_outcomes_and_features_do_not_change_fitted_coefficients(self):
        first = dict(name='first', rows=[row(i * 30_000, 100 + i % 11, 100 + i % 5) for i in range(100)])
        later = dict(name='later', rows=[row(4_000_000 + i * 30_000) for i in range(20)])
        original = fit_and_evaluate([deepcopy(first), deepcopy(later)], .48, 50_000)
        for r in first['rows'][60:] + later['rows']:
            r['move'] *= 100
            r['adaptive_features']['vol_60_ppm'] *= 1000
            r['lag_features']['vol_bps'] *= 1000
        changed = fit_and_evaluate([first, later], .48, 50_000)
        self.assertEqual(original['models'], changed['models'])
        self.assertEqual(original['regime_thresholds'], changed['regime_thresholds'])

    def test_higher_target_has_wider_or_equal_loss_minimizing_scale(self):
        rows = [row(move=i) for i in range(100)]
        model = dict(family='fixed', maximum_width_ppm=1000)
        low = fit_scale(rows, model, .1)
        high = fit_scale(rows, model, .9)
        self.assertLessEqual(low['scale'], high['scale'])

    def test_existing_experiment_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, 'never overwrite'):
                replay([], Path(directory))


if __name__ == '__main__':
    unittest.main()
