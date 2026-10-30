from copy import deepcopy
import math
import unittest

from bursty_feedback import MODES, BurstyTracker, series
from gap_quantile import fit, series as old_series
from test_gap_quantile import gap_paths, training


class BurstyFeedbackTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model = fit(training(), True)

    def mixed(self):
        values = gap_paths(80)
        for i, p in enumerate(values):
            p['row']['activity_state'] = 'bursty' if i % 4 == 0 else 'active'
        return values

    def test_shared_instrumentation_reproduces_every_preceding_output(self):
        values = self.mixed()
        actual = series(values, self.model, 'shared')
        for p in actual:
            components = p.pop('feedback_components')
            self.assertAlmostEqual(p['gap_log_correction'], sum(v['weight'] * v['log_correction'] for v in components))
        self.assertEqual(actual, old_series(values, self.model, True))

    def test_non_bursty_labels_cannot_change_isolated_correction_given_fixed_forecasts(self):
        values = self.mixed(); changed = deepcopy(values)
        for p in changed:
            if p['row']['activity_state'] != 'bursty':
                p['row']['move'] = 0
        for mode in MODES:
            a, b = (series(v, self.model, mode) for v in (values, changed))
            self.assertEqual([(p['width_ppm'], p['gap_log_correction']) for p in a if p['row']['activity_state'] == 'bursty'],
                             [(p['width_ppm'], p['gap_log_correction']) for p in b if p['row']['activity_state'] == 'bursty'])
        a, b = (series(v, self.model, 'shared') for v in (values, changed))
        self.assertNotEqual([p['gap_log_correction'] for p in a], [p['gap_log_correction'] for p in b])

    def test_shape_controller_does_not_learn_another_shape_labels(self):
        values = gap_paths(75)
        for i, p in enumerate(values):
            p['row']['adaptive_features']['vol_60_ppm'] = (.3, 1., 2.)[i % 3] * p['row']['adaptive_features']['vol_300_ppm']
        changed = deepcopy(values)
        for i, p in enumerate(changed):
            if i % 3:
                p['row']['move'] = 0
        a, b = (series(v, self.model, 'shape') for v in (values, changed))
        self.assertEqual([p['width_ppm'] for p in a[::3]], [p['width_ppm'] for p in b[::3]])

    def test_sparse_startup_uses_neutral_correction_without_refusing_quotes(self):
        values = gap_paths(30)
        for p in values[:20]:
            p['row']['activity_state'] = 'active'
        for mode in MODES:
            result = series(values, self.model, mode)
            self.assertEqual(result[20]['gap_log_correction'], 0)
            self.assertEqual([p['paused'] for p in result], [p['paused'] for p in values])
        tracker = BurstyTracker('shrunk')
        row = values[20]['row']; delta, weights = tracker.correction(row, row['start'])
        self.assertEqual(weights, [('bursty', 0.)]); self.assertEqual(delta, 0.)

    def test_current_future_outcomes_wait_for_maturity_in_all_isolated_modes(self):
        values = gap_paths(50); changed = deepcopy(values)
        for p in changed[20:]:
            p['row'].update(move=999999999, valid=False)
        for mode in MODES:
            a, b = (series(v, self.model, mode) for v in (values, changed))
            self.assertEqual([p['width_ppm'] for p in a[:22]], [p['width_ppm'] for p in b[:22]])
            self.assertEqual([p['gap_floor_risk'] for p in a], [p['gap_floor_risk'] for p in b])

    def test_refused_references_still_learn_and_restart_clears_private_state(self):
        values = gap_paths(40); refused = deepcopy(values)
        for p in refused:
            p.update(paused=True, survived=None)
        for mode in MODES:
            a, b = (series(v, self.model, mode) for v in (values, refused))
            self.assertEqual([p['width_ppm'] for p in a], [p['width_ppm'] for p in b])
            changed = deepcopy(values)
            for p in changed[20:]:
                p['row']['period'] = 'next'
            self.assertEqual(series(changed, self.model, mode)[20:], series(changed[20:], self.model, mode))
            self.assertNotEqual([p['gap_log_correction'] for p in a[20:]], [p['gap_log_correction'] for p in series(values[20:], self.model, mode)])

    def test_other_prices_are_fixed_and_components_match_bounded_applied_correction(self):
        values = self.mixed()
        for mode in MODES:
            for p, old in zip(series(values, self.model, mode), values):
                self.assertEqual(p['paused'], old['paused'])
                self.assertAlmostEqual(p['gap_log_correction'], sum(x['weight'] * x['log_correction'] for x in p['feedback_components']))
                self.assertLessEqual(abs(p['gap_log_correction']), math.log(4))
                if old['row']['activity_state'] != 'bursty':
                    self.assertEqual((p['width_ppm'], p['shadow_survived']), (old['width_ppm'], old['shadow_survived']))


if __name__ == '__main__':
    unittest.main()
