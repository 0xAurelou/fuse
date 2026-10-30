from copy import deepcopy
import math
import unittest

import numpy as np

from bursty_optimizer import BayesianSearch, anchors, cache_forecasts, decode, encode, replay
from bursty_residual import series
from gap_quantile import fit
from test_gap_quantile import gap_paths, training


class SearchTests(unittest.TestCase):
    def test_bounds_round_trip_and_invalid_parameters(self):
        rng = np.random.default_rng(12)
        for x in rng.random((20, 6)):
            params = decode(x)
            restored = decode(encode(params))
            self.assertEqual(restored['source'], params['source'])
            for name in params.keys() - {'source'}:
                self.assertAlmostEqual(restored[name], params[name], places=12)
        for x in ([2.] * 6, [math.nan] * 6, [0.] * 5):
            with self.assertRaises(ValueError):
                decode(x)
        bad = anchors()[0]; bad['prior_mass'] = 0
        with self.assertRaises(ValueError):
            encode(bad)

    def test_search_is_reproducible_unique_and_finds_better_toy_parameters(self):
        runs = []
        for _ in range(2):
            optimizer = BayesianSearch(9); results = []
            for i in range(32):
                params = optimizer.ask(); x = encode(params)
                score = float(np.sum((x[1:] - .28) ** 2) + .1 * x[0])
                optimizer.tell(params, score); results.append((params, score))
            runs.append(results)
        self.assertEqual(runs[0], runs[1])
        self.assertEqual(len({tuple(encode(p)) for p, _ in runs[0]}), 32)
        self.assertLess(min(s for _, s in runs[0][10:]), min(s for _, s in runs[0][:10]))

    def test_trial_protocol_rejects_missing_mismatched_and_nonfinite_results(self):
        optimizer = BayesianSearch()
        with self.assertRaises(ValueError):
            optimizer.tell({}, 1)
        params = optimizer.ask()
        with self.assertRaises(ValueError):
            optimizer.ask()
        with self.assertRaises(ValueError):
            optimizer.tell(params, math.nan)
        with self.assertRaises(ValueError):
            optimizer.tell(dict(params, source='timing'), 1)
        optimizer.tell(params, 1)


class CachedReplayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model = fit(training(), True)
        cls.prior = dict(bursty=dict(knots=[.6 + i / 128 for i in range(128)]))

    def apply(self, values, params=None):
        params = anchors()[0] if params is None else params
        cached = cache_forecasts(values, {'gap': self.model})['gap']
        return replay(values, cached, self.prior, params)

    def test_exact_reconstruction_of_existing_neutral_and_learned_controls(self):
        values = gap_paths(100)
        for weight, mode in ((1., 'ratio4h_prior'), (0., 'ratio4h_neutral')):
            params = dict(anchors()[0], learned_weight=weight)
            a = self.apply(values, params); b = series(values, self.model, self.prior, mode)
            self.assertEqual([(p['width_ppm'], p['shadow_survived']) for p in a],
                             [(p['width_ppm'], p['shadow_survived']) for p in b])

    def test_outcomes_wait_for_maturity_and_other_states_cannot_teach_correction(self):
        values = gap_paths(80)
        for i, p in enumerate(values):
            if i % 3:
                p['row']['activity_state'] = 'active'
        changed = deepcopy(values)
        for p in changed:
            if p['row']['activity_state'] == 'active':
                p['row']['move'] = 0
        a, b = self.apply(values), self.apply(changed)
        self.assertEqual([p['width_ppm'] for p in a], [p['width_ppm'] for p in b])
        changed = deepcopy(values)
        for p in changed[20:]:
            p['row'].update(move=9999999, valid=False)
        b = self.apply(changed)
        self.assertEqual([p['width_ppm'] for p in a[:22]], [p['width_ppm'] for p in b[:22]])

    def test_masks_fallback_other_prices_and_period_reset(self):
        values = gap_paths(90)
        for i, p in enumerate(values):
            if i % 4 == 0:
                p['row']['activity_state'] = 'frozen'
            if i % 4 == 1:
                p['row']['oracle_gap'] = None
        output = self.apply(values)
        for p, old in zip(output, values):
            self.assertEqual(p['paused'], old['paused'])
            self.assertTrue(1 <= p['width_ppm'] <= 50000)
            if old['row']['activity_state'] != 'bursty' or old['row']['oracle_gap'] is None:
                self.assertEqual(p, old)
        refused = deepcopy(values)
        for p in refused:
            p.update(paused=True, survived=None)
        self.assertEqual([p['width_ppm'] for p in output], [p['width_ppm'] for p in self.apply(refused)])
        for p in values[45:]:
            p['row']['period'] = 'next'
        self.assertEqual(self.apply(values)[45:], self.apply(values[45:]))
        with self.assertRaises(ValueError):
            self.apply(list(reversed(values)))


if __name__ == '__main__':
    unittest.main()
