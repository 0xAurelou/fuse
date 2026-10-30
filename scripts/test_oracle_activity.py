from copy import deepcopy
import unittest

from oracle_activity_features import annotate, state
from research_activity_calibration import (SPECS, availability, choose, fit,
                                            metrics, predict, shadow)
from stabilize_adaptive_corridor import predict_sequence


def row(at, period='day', kind='mixed', activity='active', move=100):
    return dict(start=at, expiry=at + 30_000, period=period, split='train',
                valid=True, entry=1_000_000, move=move, market_regime=kind,
                activity_state=activity,
                activity_features=dict(idle_ms=1000, changes_60=20, changes_300=100,
                                       empty_bins_300=0, largest_variance_share_300=.1),
                adaptive_features=dict(vol_60_ppm=100, vol_300_ppm=100))


def training():
    return [row(day * 10_000_000 + i * 30_000, str(day), move=100 + i % 31)
            for day in range(3) for i in range(100)]


class OracleActivityTests(unittest.TestCase):
    def test_activity_ignores_entry_and_future_price_changes(self):
        observations = [(at, 100_000_000 + (at // 1000) % 23) for at in range(0, 600_000, 1000)]
        changed = [(at, p if at < 360_000 else p * 2) for at, p in observations]
        a, b = [row(360_000)], [row(360_000)]
        annotate(a, observations)
        annotate(b, changed)
        self.assertEqual(a[0]['activity_features'], b[0]['activity_features'])
        changed = observations + [(600_000, 1)]
        c = [row(360_000)]
        annotate(c, changed)
        self.assertEqual(c[0]['activity_features'], a[0]['activity_features'])

    def test_heartbeat_duplicates_do_not_create_activity(self):
        base = [(0, 100), (100_000, 101), (200_000, 100), (350_000, 102)]
        repeated = []
        for i, (at, price) in enumerate(base):
            end = base[i + 1][0] if i + 1 < len(base) else 360_000
            repeated.extend((t, price) for t in range(at, end, 1000))
        a, b = [row(360_000)], [row(360_000)]
        annotate(a, base)
        annotate(b, repeated)
        self.assertEqual(a[0]['activity_features'], b[0]['activity_features'])
        self.assertEqual(a[0]['activity_features']['idle_ms'], 10_000)

    def test_no_fabricated_change_at_first_observation_and_state_precedence(self):
        rows = [row(360_000)]
        annotate(rows, [(0, 100), (100_000, 100), (350_000, 100)])
        f = rows[0]['activity_features']
        self.assertEqual(f['changes_300'], 0)
        self.assertTrue(f['idle_is_lower_bound'])
        self.assertEqual(f['empty_bins_300'], 1)
        self.assertEqual(state(rows[0]), 'frozen')
        f.update(idle_ms=1000, changes_60=2, largest_variance_share_300=.9)
        self.assertEqual(state(rows[0]), 'sparse')
        f.update(changes_60=20, empty_bins_300=0)
        self.assertEqual(state(rows[0]), 'bursty')

    def test_previous_rule_has_exact_prediction_parity(self):
        model = fit(training(), SPECS[0])
        rows = [row(i * 30_000, move=300) for i in range(150)]
        a, b = predict(rows, model), predict_sequence(rows, model['base'])
        self.assertEqual([(p['width_ppm'], p['correction'], p['survived']) for p in a],
                         [(p['width_ppm'], p['correction'], p['survived']) for p in b])

    def test_past_maturity_and_not_future_eligibility_controls_correction(self):
        model = fit(training(), next(s for s in SPECS if s['name'] == 'activity_local_wide'))
        model['online'].update(minimum_mature_outcomes=1, prior_mass=.1)
        model.update(local_minimum=1, local_prior_mass=.1)
        rows = [row(i * 30_000, move=500) for i in range(12)]
        changed = deepcopy(rows)
        changed[0]['valid'] = False
        a, b = predict(rows, model), predict(changed, model)
        self.assertEqual(a[1]['width_ppm'], b[1]['width_ppm'])
        self.assertNotEqual(a[2]['width_ppm'], b[2]['width_ppm'])
        changed = deepcopy(rows)
        for r in changed[6:]:
            r['move'] *= 20
            r['valid'] = False
        c = predict(changed, model)
        self.assertEqual([p['width_ppm'] for p in a[:6]], [p['width_ppm'] for p in c[:6]])

    def test_pause_is_based_on_prior_floor_and_reports_full_shadow_denominator(self):
        train = training()
        for r in train:
            r.update(activity_state='frozen', move=0)
        model = fit(train, next(s for s in SPECS if s['name'] == 'activity_pause'))
        rows = [row(0, activity='frozen', move=0), row(30_000, activity='frozen', move=1000)]
        pred = predict(rows, model)
        self.assertTrue(all(p['paused'] for p in pred))
        self.assertEqual(metrics(pred)['windows'], 0)
        self.assertEqual(metrics(shadow(pred))['windows'], 2)
        self.assertEqual(availability(pred)['paused_eligible_outcomes'], 2)
        changed = deepcopy(rows)
        changed[0]['move'] = 1_000_000
        self.assertEqual([p['paused'] for p in pred], [p['paused'] for p in predict(changed, model)])

    def test_sparse_activity_group_falls_back_and_correction_bounds_hold(self):
        train = training() + [row(40_000_000, 'one', activity='bursty', move=1000)]
        model = fit(train, next(s for s in SPECS if s['name'] == 'activity_local_wide'))
        self.assertEqual(model['activity_scales']['bursty']['multiplier'], 1)
        model['online'].update(minimum_mature_outcomes=1, prior_mass=.1)
        pred = predict([row(i * 30_000, move=10_000) for i in range(100)], model)
        for a, b in zip(pred, pred[1:]):
            self.assertTrue(.4 <= b['correction'] <= 2)
            self.assertLessEqual(b['correction'], a['correction'] * 1.02 + 1e-12)
            self.assertGreaterEqual(b['correction'], a['correction'] * .98 - 1e-12)

    def test_outer_periods_do_not_select_activity_or_pause_hyperparameters(self):
        dates = [f'day-{i:02d}' for i in range(24)]
        rows = [row(day * 10_000_000 + i * 30_000, date, move=100 + i % 31)
                for day, date in enumerate(dates) for i in range(60)]
        a = choose(rows, dates)
        changed = deepcopy(rows)
        for r in changed:
            if r['period'] in dates[14:]:
                r.update(move=0, activity_state='frozen', valid=False)
        self.assertEqual(a, choose(changed, dates))


if __name__ == '__main__':
    unittest.main()
