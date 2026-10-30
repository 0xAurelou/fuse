from copy import deepcopy
import math
import unittest

from gap_quantile import fit, features, forecast, series, all_series, Tracker, SPEC
from oracle_gap_features import attach
from research_gap_quantile import add_context
from test_preentry_bursty import paths


def gap_paths(count=90):
    values = paths(count)
    for i, p in enumerate(values):
        p['row']['oracle_gap'] = dict(values=[math.sin(i / 8), abs(math.sin(i / 8)), (i % 7) / 3, (i % 9) / 4, (i % 9) / 4])
    return values


def training():
    values = []
    for i in range(3):
        for p in gap_paths():
            p['row'].update(period=str(i), start=i * 10_000_000 + p['row']['start'], expiry=i * 10_000_000 + p['row']['expiry'])
            values.append(p)
    return values


class GapFeatureTests(unittest.TestCase):
    def row(self):
        return dict(start=60000, entry=100000000, adaptive_features=dict(vol_300_ppm=20))

    def points(self):
        return [(29999, 100000000, 100002000, 100002100), (59999, 100000000, 100003000, 100003100),
                (60000, 100010000, 100020000, 100030000)]

    def test_entry_and_future_receipts_cannot_change_pre_entry_features(self):
        points = self.points(); a = attach([self.row()], points, 0)
        points[-1] = (60000, 999999, 888888, 777777)
        points.append((60001, 999999, 999999, 999999))
        self.assertEqual(a, attach([self.row()], points, 0))
        g = a[0]['oracle_gap']; self.assertEqual(g['observed_at'], 59999)
        self.assertEqual(g['lag_observed_at'], 29999)
        self.assertAlmostEqual(g['mark_gap_ppm'], 30)

    def test_stale_missing_and_outside_restart_history_fall_back(self):
        points = self.points()
        self.assertIsNone(attach([self.row()], points, 30000)[0]['oracle_gap'])
        self.assertIsNone(attach([self.row()], [points[0]], 0)[0]['oracle_gap'])
        self.assertIsNone(attach([self.row()], [(29999, 100000000, None, None), points[1]], 0)[0]['oracle_gap'])
        self.assertIsNone(attach([self.row()], [], 0)[0]['oracle_gap'])
        with self.assertRaises(ValueError):
            attach([dict(self.row(), entry=1)], points, 0)

    def test_native_training_and_sessions_without_market_source_use_missing_context(self):
        row = dict(self.row(), period='native-capture')
        ctx = dict(original=[row], expanded_rawdays={}, sessions=[dict(source='native', period='native-capture', id='native', values=[dict(row=row)])])
        add_context(ctx, dict(normalized={}, raw={}))
        self.assertIsNone(ctx['original'][0]['oracle_gap'])
        self.assertIsNone(ctx['sessions'][0]['values'][0]['row']['oracle_gap'])


class GapQuantileTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.models = dict(timing=fit(training(), False), gap=fit(training(), True))

    def test_matched_support_and_feature_allowlist_ignore_outcomes(self):
        self.assertEqual(self.models['timing']['windows'], self.models['gap']['windows'])
        values = gap_paths(1); p = values[0]; changed = deepcopy(p)
        changed['row'].update(move=999999999, valid=False, entry=3)
        for use_gap in (False, True):
            self.assertEqual(features(p['row'], use_gap), features(changed['row'], use_gap))
            model = self.models['gap' if use_gap else 'timing']
            self.assertEqual(forecast(p, model), forecast(changed, model))
        a = fit(training(), True); changed_training = training()
        for p in changed_training:
            p['row']['oracle_gap']['values'][0] *= (p['row']['move'] + 1)
        self.assertNotEqual(a['price_coefficients'], fit(changed_training, True)['price_coefficients'])

    def test_current_and_future_outcomes_wait_for_maturity(self):
        values = gap_paths(50); changed = deepcopy(values)
        for p in changed[20:]:
            p['row'].update(move=999999999, valid=False)
        for source, model in self.models.items():
            a, b = (series(v, model, True) for v in (values, changed))
            self.assertEqual([p['width_ppm'] for p in a[:22]], [p['width_ppm'] for p in b[:22]])
            self.assertEqual([p['gap_floor_risk'] for p in a], [p['gap_floor_risk'] for p in b])
            self.assertNotEqual([p['gap_log_correction'] for p in a[25:]], [p['gap_log_correction'] for p in b[25:]])

    def test_non_bursty_prices_and_all_admission_decisions_stay_fixed(self):
        values = gap_paths(40)
        for i, p in enumerate(values):
            p['row']['activity_state'] = ('bursty', 'active', 'sparse', 'frozen')[i % 4]
            if i % 3 == 0:
                p.update(paused=True, survived=None)
        for result in all_series(values, self.models).values():
            self.assertEqual([p['paused'] for p in result], [p['paused'] for p in values])
            for p, b in zip(result, values):
                if b['row']['activity_state'] != 'bursty':
                    self.assertEqual((p['width_ppm'], p['shadow_survived']), (b['width_ppm'], b['shadow_survived']))
                self.assertTrue(1 <= p['width_ppm'] <= 50000)

    def test_refused_references_learn_and_missing_context_uses_benchmark(self):
        values = gap_paths(35); refused = deepcopy(values)
        for p in refused:
            p.update(paused=True, survived=None)
        a, b = (series(v, self.models['gap'], True) for v in (values, refused))
        self.assertEqual([p['width_ppm'] for p in a], [p['width_ppm'] for p in b])
        self.assertTrue(any(p['gap_log_correction'] != 0 for p in a[5:]))
        for p in values:
            p['row']['oracle_gap'] = None
        for result in all_series(values, self.models).values():
            self.assertEqual([(p['width_ppm'], p['shadow_survived']) for p in result], [(p['width_ppm'], p['shadow_survived']) for p in values])

    def test_restart_resets_state_and_continuous_scoring_does_not(self):
        values = gap_paths(40); model = self.models['gap']
        full = series(values, model, True); fresh = series(values[20:], model, True)
        self.assertNotEqual([p['gap_log_correction'] for p in full[20:]], [p['gap_log_correction'] for p in fresh])
        changed = deepcopy(values)
        for p in changed[20:]:
            p['row']['period'] = 'next'
        reset = series(changed, model, True)
        self.assertEqual(reset[20:], series(changed[20:], model, True))
        with self.assertRaises(ValueError):
            series(list(reversed(values)), model, True)

    def test_floor_branch_and_controller_direction_and_anti_windup(self):
        model = deepcopy(self.models['gap']); model['floor_coefficients'] = [10] + [0] * (len(model['floor_coefficients']) - 1)
        self.assertEqual(forecast(gap_paths(1)[0], model)[0], 1)
        row = gap_paths(1)[0]['row']; row.update(move=0, expiry=30000)
        tracker = Tracker()
        tracker.learn(dict(row=row, width=50, mature_at=60000, weights=[('parent', 1.)]))
        self.assertLess(tracker.states['parent']['delta'], 0)
        before = tracker.states['parent']['delta']
        tracker.learn(dict(row=row, width=1, mature_at=90000, weights=[('parent', 1.)]))
        self.assertEqual(before, tracker.states['parent']['delta'])
        row = dict(row, move=999999999)
        tracker.learn(dict(row=row, width=50, mature_at=120000, weights=[('parent', 1.)]))
        self.assertGreater(tracker.states['parent']['delta'], before)
        self.assertEqual(tracker.state('parent', 120000 + SPEC['maximum_age_ms'] + 1)['delta'], 0)


if __name__ == '__main__':
    unittest.main()
