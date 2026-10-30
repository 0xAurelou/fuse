from copy import deepcopy
from datetime import datetime, timezone
import unittest
from unittest.mock import patch

from bursty_residual import MODES, fit_prior, series
from gap_quantile import fit
from research_bursty_residual import select_predictor
from test_gap_quantile import gap_paths, training


def records():
    result = []
    for day in ('2025-01-01', '2025-02-01', '2025-03-01', '2025-04-01'):
        origin = int(datetime.fromisoformat(day).replace(tzinfo=timezone.utc).timestamp() * 1000)
        for i in range(30):
            result.append(dict(source='gap', row=dict(period=day, start=origin + i * 30000, expiry=origin + (i + 1) * 30000, activity_state='bursty'),
                               ratio=.5 + i / 20, model_cutoff='2025-01-01', training_periods=['2024-11-01', '2024-12-01']))
    return result


class ResidualPriorTests(unittest.TestCase):
    def test_prior_uses_only_allowed_earlier_dates_and_neutral_fallback(self):
        rows = records(); periods = ['2025-01-01', '2025-02-01', '2025-03-01']
        a = fit_prior(rows, 'gap', periods, '2025-04-01')
        changed = deepcopy(rows)
        for r in changed:
            if r['row']['period'] >= '2025-04-01':
                r['ratio'] = 99999
        self.assertEqual(a, fit_prior(changed, 'gap', periods, '2025-04-01'))
        self.assertFalse(a['bursty']['used_parent']); self.assertEqual(a['bursty']['windows'], 90)
        empty = fit_prior(rows, 'timing', periods, '2025-04-01')
        self.assertTrue(empty['bursty']['neutral_fallback']); self.assertEqual(set(empty['bursty']['knots']), {1.})

    def test_self_fitted_forecasts_unmatured_labels_and_duplicates_are_rejected(self):
        for mutation in ('own_day_fit', 'future_model', 'maturity', 'duplicate'):
            rows = records(); periods = ['2025-01-01', '2025-02-01', '2025-03-01']
            if mutation == 'own_day_fit':
                rows[0]['training_periods'].append('2025-01-01')
            elif mutation == 'future_model':
                rows[0]['model_cutoff'] = '2025-02-01'
            elif mutation == 'maturity':
                boundary = int(datetime(2025, 4, 1, tzinfo=timezone.utc).timestamp() * 1000)
                rows[0]['row']['expiry'] = boundary - 30000
            else:
                rows.append(deepcopy(rows[0]))
            with self.assertRaises(ValueError):
                fit_prior(rows, 'gap', periods, '2025-04-01')

    def test_predictor_selection_excludes_own_day_training_and_future_model(self):
        catalog = [dict(id='earlier', bundle=dict(cutoff='2025-01-01', training_periods=['2024-11-01', '2024-12-01'])),
                   dict(id='future', bundle=dict(cutoff='2025-03-01', training_periods=['2024-11-01', '2024-12-01', '2025-01-01'])),
                   dict(id='own_day', bundle=dict(cutoff='2025-02-01', training_periods=['2025-02-01']))]
        self.assertEqual(select_predictor(catalog, '2025-02-01')['id'], 'earlier')
        self.assertIsNone(select_predictor(catalog, '2024-11-01'))


class ResidualTrackingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model = fit(training(), True)
        cls.neutral = fit_prior([], 'gap', ['2024-11-01', '2024-12-01'], '2025-01-01')

    def test_miss_magnitude_changes_correction_with_identical_static_survival_labels(self):
        near, far = gap_paths(100), gap_paths(100)
        for values, move in ((near, 120), (far, 1200)):
            for p in values:
                p['row'].update(entry=1000000, move=move)
        with patch('bursty_residual.forecast', return_value=(100, .1)):
            a, b = (series(v, self.model, self.neutral, 'ratio1h_neutral') for v in (near, far))
        self.assertGreater(b[-1]['ratio_requested'], a[-1]['ratio_requested'])
        self.assertGreater(b[-1]['width_ppm'], a[-1]['width_ppm'])
        self.assertEqual(a[0]['width_ppm'], 100)

    def test_labels_wait_until_maturity_and_other_states_do_not_teach_correction(self):
        values = gap_paths(60); changed = deepcopy(values)
        for i, p in enumerate(values):
            if i % 3:
                p['row']['activity_state'] = changed[i]['row']['activity_state'] = 'active'
                changed[i]['row']['move'] = 0
        for mode in MODES:
            a, b = (series(v, self.model, self.neutral, mode) for v in (values, changed))
            self.assertEqual([(p['width_ppm'], p['gap_log_correction']) for p in a], [(p['width_ppm'], p['gap_log_correction']) for p in b])
            future = deepcopy(values)
            for p in future[20:]:
                p['row'].update(move=999999999, valid=False)
            c = series(future, self.model, self.neutral, mode)
            self.assertEqual([p['width_ppm'] for p in a[:22]], [p['width_ppm'] for p in c[:22]])

    def test_refused_references_learn_other_prices_stay_fixed_and_missing_context_falls_back(self):
        values = gap_paths(60); refused = deepcopy(values)
        for p in refused:
            p.update(paused=True, survived=None)
        for mode in MODES:
            a, b = (series(v, self.model, self.neutral, mode) for v in (values, refused))
            self.assertEqual([p['width_ppm'] for p in a], [p['width_ppm'] for p in b])
            self.assertTrue(all(p['paused'] for p in b))
            mixed = deepcopy(values)
            for i, p in enumerate(mixed):
                if i % 3 == 0:
                    p['row']['activity_state'] = 'active'
                if i % 3 == 1:
                    p['row']['oracle_gap'] = None
            out = series(mixed, self.model, self.neutral, mode)
            for p, old in zip(out, mixed):
                if old['row']['activity_state'] != 'bursty' or old['row']['oracle_gap'] is None:
                    self.assertEqual((p['width_ppm'], p['shadow_survived']), (old['width_ppm'], old['shadow_survived']))

    def test_restart_resets_and_long_memory_retains_only_previously_matured_evidence(self):
        values = gap_paths(70)
        for p in values[35:]:
            p['row']['start'] += 7200000; p['row']['expiry'] += 7200000
        short = series(values, self.model, self.neutral, 'ratio1h_neutral')
        long = series(values, self.model, self.neutral, 'ratio4h_neutral')
        self.assertEqual(short[35]['ratio_mass'], 0)
        self.assertGreater(long[35]['ratio_mass'], 0)
        changed = deepcopy(values)
        for p in changed[35:]:
            p['row']['period'] = 'next'
        for mode in MODES:
            self.assertEqual(series(changed, self.model, self.neutral, mode)[35:], series(changed[35:], self.model, self.neutral, mode))


if __name__ == '__main__':
    unittest.main()
