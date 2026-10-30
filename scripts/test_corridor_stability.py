from copy import deepcopy
import unittest

from stabilize_adaptive_corridor import (ONLINE, SPECS, balanced_weights, fit_model,
                                         metrics, phase, predict_sequence, select_spec)


def row(at, period='day', move=300, kind='mixed', valid=True):
    return dict(start=at, expiry=at + 30_000, period=period, split='train',
                entry=1_000_000, move=move, market_regime=kind, valid=valid,
                adaptive_features=dict(vol_60_ppm=100, vol_300_ppm=100))


def model(memory=120):
    return dict(name='test', grouping='all', global_scale=1, scales={}, memory=memory,
                online=dict(ONLINE, prior_mass=.1, minimum_mature_outcomes=1) if memory else None,
                target_survival=.48, maximum_width_ppm=50_000)


class CorridorStabilityTests(unittest.TestCase):
    def test_outcomes_and_eligibility_affect_width_only_after_declared_maturity(self):
        original = [row(i * 30_000) for i in range(8)]
        changed = deepcopy(original)
        changed[0]['move'] = 10
        a, b = predict_sequence(original, model()), predict_sequence(changed, model())
        self.assertEqual([p['width_ppm'] for p in a[:2]], [p['width_ppm'] for p in b[:2]])
        self.assertNotEqual(a[2]['width_ppm'], b[2]['width_ppm'])
        self.assertEqual(a[1]['mature_outcomes'], 0)
        self.assertEqual(a[2]['mature_outcomes'], 1)
        changed = deepcopy(original)
        changed[0]['valid'] = False
        c = predict_sequence(changed, model())
        self.assertEqual(a[0]['width_ppm'], c[0]['width_ppm'])
        self.assertEqual(a[1]['width_ppm'], c[1]['width_ppm'])
        self.assertNotEqual(a[2]['width_ppm'], c[2]['width_ppm'])

    def test_future_suffix_does_not_change_prior_predictions(self):
        original = [row(i * 30_000) for i in range(50)]
        changed = deepcopy(original)
        for r in changed[25:]:
            r['move'] *= 10
            r['valid'] = False
            r['adaptive_features']['vol_60_ppm'] *= 10
        a, b = predict_sequence(original, model()), predict_sequence(changed, model())
        self.assertEqual([(p['width_ppm'], p['correction']) for p in a[:25]],
                         [(p['width_ppm'], p['correction']) for p in b[:25]])

    def test_correction_is_bounded_slow_and_resets_only_at_new_session(self):
        rows = [row(i * 30_000) for i in range(100)]
        p = predict_sequence(rows, model())
        for before, after in zip(p, p[1:]):
            self.assertLessEqual(after['correction'], before['correction'] * 1.02 + 1e-12)
            self.assertGreaterEqual(after['correction'], before['correction'] * .98 - 1e-12)
            self.assertTrue(.75 <= after['correction'] <= 4 / 3)
        rows += [row(3_000_000, 'next')]
        self.assertEqual(predict_sequence(rows, model())[-1]['correction'], 1)
        rows[50]['adaptive_features'] = None
        p = predict_sequence(rows, model())
        self.assertIsNone(p[50]['width_ppm'])
        self.assertGreater(p[51]['correction'], 1)

    def test_insufficient_maturity_keeps_prior_and_old_outcomes_expire(self):
        configured = model()
        configured['online']['minimum_mature_outcomes'] = 30
        rows = [row(i * 30_000) for i in range(35)]
        p = predict_sequence(rows, configured)
        self.assertEqual(p[30]['correction'], 1)
        self.assertGreater(p[31]['correction'], 1)
        rows += [row(20_000_000)]
        last = predict_sequence(rows, configured)[-1]
        self.assertEqual(last['mature_outcomes'], 0)

    def test_balancing_prevents_long_days_and_long_episodes_dominating(self):
        rows = [row(0, 'a'), row(30_000, 'a'), row(500_000, 'a'), row(1_000_000, 'b')]
        w = balanced_weights(rows)
        self.assertAlmostEqual(sum(w[:3]), 1)
        self.assertEqual(w[3], 1)
        w = balanced_weights(rows, directional=True)
        self.assertEqual(w, [.25, .25, .5, 1])

    def test_phase_boundaries_and_sparse_group_fallback(self):
        r = row(0, kind='pump')
        r['adaptive_features']['vol_60_ppm'] = 74
        self.assertEqual(phase(r), 'cooling')
        r['adaptive_features']['vol_60_ppm'] = 75
        self.assertEqual(phase(r), 'steady')
        r['adaptive_features']['vol_60_ppm'] = 126
        self.assertEqual(phase(r), 'accelerating')
        rows = [row(i * 30_000, str(i // 50)) for i in range(150)] + [row(5_000_000, 'p', kind='pump')]
        fitted = fit_model(rows, next(s for s in SPECS if s['name'] == 'period_phase'))
        self.assertEqual(fitted['scales']['pump']['scale'], fitted['global_scale'])
        self.assertEqual(fitted['scales']['pump_cooling']['scale'], fitted['scales']['pump']['scale'])

    def test_exact_touch_and_scoring_denominator_include_initial_learning_period(self):
        samples = [row(0, move=100), row(30_000, move=99), row(60_000, valid=False)]
        predictions = predict_sequence(samples, model(memory=0))
        result = metrics(predictions)
        self.assertEqual((result['windows'], result['survived']), (2, 1))
        self.assertIsNotNone(predictions[2]['width_ppm'])
        self.assertIsNone(predictions[2]['survived'])

    def test_outer_periods_cannot_select_hyperparameters(self):
        dates = [f'period-{i:02d}' for i in range(24)]
        rows = [row(day * 10_000_000 + i * 30_000, date, move=100 + (i % 11) * 20,
                    kind='pump' if i % 3 == 0 else 'mixed')
                for day, date in enumerate(dates) for i in range(60)]
        a = select_spec(rows, dates)
        changed = deepcopy(rows)
        for r in changed:
            if r['period'] in dates[14:]:
                r['move'] *= 100
                r['adaptive_features']['vol_60_ppm'] *= 100
                r['valid'] = False
        b = select_spec(changed, dates)
        self.assertEqual(a, b)


if __name__ == '__main__':
    unittest.main()
