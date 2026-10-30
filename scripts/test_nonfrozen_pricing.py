from copy import deepcopy
import math
import unittest

from nonfrozen_pricing import SPECS, STATES, fit_prior, quantile_grid, reprice, spec
from research_activity_calibration import fit
from research_flat_pause import ENGINE_SPEC
from research_nonfrozen_pricing import choose, fixed_mask, measures
from test_flat_pause import prediction
from test_oracle_activity import training


def references(n=80, move=0):
    values = [prediction(i * 30_000) for i in range(n)]
    for p in values:
        p['row']['move'] = move
    return values


def prior():
    values = [prediction(day * 10_000_000 + i * 30_000, period=str(day))
              for day in range(3) for i in range(100)]
    for i, p in enumerate(values):
        p['row'].update(activity_state=STATES[i % 3], move=20 + i % 100)
    return fit_prior(values)


class NonFrozenPricingTests(unittest.TestCase):
    def test_all_families_preserve_frozen_prices_masks_and_outcome_eligibility(self):
        values = references()
        values[4].update(paused=True, survived=None)
        values[5]['row']['valid'] = False
        values[5].update(survived=None, shadow_survived=None)
        values[6]['row']['activity_state'] = 'frozen'
        values[7].update(width_ppm=None, survived=None, shadow_survived=None)
        model = fit(training(), ENGINE_SPEC)
        for candidate in SPECS:
            result = reprice(values, prior(), candidate, model)
            self.assertEqual([p['paused'] for p in values], [p['paused'] for p in result])
            self.assertEqual([p['width_ppm'] is None for p in values], [p['width_ppm'] is None for p in result])
            self.assertEqual([p['shadow_survived'] is None for p in values], [p['shadow_survived'] is None for p in result])
            self.assertEqual(result[6]['width_ppm'], values[6]['width_ppm'])
            self.assertEqual(result[6]['shadow_survived'], values[6]['shadow_survived'])
            self.assertTrue(all(1 <= p['width_ppm'] <= 50_000 for p in result if p['width_ppm'] is not None))
        self.assertEqual(model['online']['minimum_correction'], .4)

    def test_future_validity_and_movement_wait_until_expiry_plus_delay(self):
        values = references()
        altered = deepcopy(values)
        for p in altered[40:]:
            p['row'].update(valid=False, move=10000)
        for candidate in SPECS:
            engine = fit(training(), ENGINE_SPEC)
            a, b = reprice(values, prior(), candidate, engine), reprice(altered, prior(), candidate, engine)
            self.assertEqual([p['width_ppm'] for p in a[:42]], [p['width_ppm'] for p in b[:42]], candidate['name'])
            self.assertTrue(all(p['width_ppm'] is not None for p in b[40:]))

    def test_minimum_mature_context_and_refused_reference_learning(self):
        values = references()
        for p in values:
            p.update(paused=True, survived=None)
        s = spec('rolling', 'residual')
        result = reprice(values, prior(), s)
        self.assertEqual(result[12]['nonfrozen_mature'], 11)
        self.assertEqual(result[12]['width_ppm'], 100)
        self.assertEqual(result[13]['nonfrozen_mature'], 12)
        self.assertLess(result[13]['width_ppm'], 100)
        self.assertTrue(all(p['survived'] is None for p in result))

    def test_contexts_do_not_borrow_online_samples(self):
        values = references(30)
        values[-1]['row']['activity_state'] = 'active'
        output = reprice(values, prior(), spec('rolling', 'residual'))
        self.assertEqual(output[-1]['nonfrozen_mature'], 0)
        self.assertEqual(output[-1]['width_ppm'], 100)

    def test_period_reset_and_expired_pool(self):
        values = references(40)
        values += [prediction(20_000_000), prediction(20_030_000, period='next')]
        output = reprice(values, prior(), spec('rolling', 'residual'))
        self.assertEqual(output[-2]['nonfrozen_mature'], 0)
        self.assertEqual(output[-1]['nonfrozen_mature'], 0)
        self.assertEqual(output[-1]['nonfrozen_correction'], 1)

    def test_correction_rate_bounds_and_memory(self):
        output = reprice(references(300), prior(), spec('rolling', 'residual', memory=20))
        for p in output:
            self.assertLessEqual(p['nonfrozen_mature'], 20)
            self.assertTrue(.05 <= p['nonfrozen_correction'] <= 2)
        for a, b in zip(output, output[1:]):
            self.assertGreaterEqual(b['nonfrozen_correction'], .98 * a['nonfrozen_correction'] - 1e-12)
            self.assertLessEqual(b['nonfrozen_correction'], 1.02 * a['nonfrozen_correction'] + 1e-12)

    def test_hurdle_uses_floor_atom_and_positive_quantile(self):
        s = spec('hurdle', 'hurdle', prior=4, step=10)
        s.update(minimum_mature=1, minimum_correction=.001)
        model = prior()
        model['states']['sparse'].update(minimum_width_floor=.25, positive_ratios=[2, 4])
        values = references(3)
        result = reprice(values, model, s)
        self.assertAlmostEqual(result[2]['nonfrozen_floor'], .4)
        self.assertEqual(result[2]['width_ppm'], 200)
        result = reprice(values, model, dict(s, prior_mass=1))
        self.assertGreater(result[2]['nonfrozen_floor'], .48)
        self.assertEqual(result[2]['width_ppm'], 1)

    def test_feedback_uses_new_width_outcome_instead_of_old_shadow_label(self):
        values = references(10, move=75)
        # Old shadow says survival; the new initial static width is 50 and fails.
        model = prior()
        model['states']['sparse']['static_factor'] = .5
        s = spec('feedback', 'feedback', step=1, gain=.1)
        s['minimum_mature'] = 1
        output = reprice(values, model, s)
        self.assertEqual(output[0]['width_ppm'], 50)
        self.assertGreater(output[2]['width_ppm'], 50)
        self.assertAlmostEqual(output[2]['nonfrozen_correction'], math.exp(.1 * .48))
        changed = deepcopy(values)
        for p in changed:
            p['shadow_survived'] = False
        self.assertEqual([p['width_ppm'] for p in output], [p['width_ppm'] for p in reprice(changed, model, s)])

    def test_quiet_scope_preserves_active_prices(self):
        values = references(50)
        for i, p in enumerate(values):
            if i % 2:
                p['row']['activity_state'] = 'active'
        for name in ('engine_floor10_quiet', 'hurdle_quiet120'):
            s = next(s for s in SPECS if s['name'] == name)
            output = reprice(values, prior(), s, fit(training(), ENGINE_SPEC))
            self.assertTrue(all(output[i]['width_ppm'] == 100 for i in range(1, 50, 2)))

    def test_prior_parent_fallback_period_balance_and_positive_grid(self):
        values = references(100, move=0)
        values[-1]['row']['move'] = 999
        model = fit_prior(values)
        self.assertTrue(model['states']['sparse']['used_parent'])
        self.assertAlmostEqual(model['parent']['minimum_width_floor'], .99)
        self.assertEqual(model['parent']['positive_ratios'], [10] * 128)
        self.assertEqual(quantile_grid([(1, 1), (3, 3)], 4), [1, 3, 3, 3])
        with self.assertRaises(ValueError):
            quantile_grid([(1, 0)])
        with self.assertRaises(ValueError):
            fit_prior([])

    def test_outer_changes_cannot_select_candidate(self):
        dates = [f'day-{i:02}' for i in range(24)]
        rows = [dict(r, period=dates[d], start=d * 10_000_000 + r['start'],
                     expiry=d * 10_000_000 + r['expiry'])
                for d in range(24) for r in training()[:60]]
        # Realistic chronological ordering per period; no source observations needed.
        sessions = []
        for d in range(24):
            values = references(60, move=20 + d * 5)
            for p in values:
                p['row']['period'] = dates[d]
            sessions.append(dict(id=dates[d], period=dates[d], source='normalized', split='train',
                                 mode='restart', intervals=[dict(start=0, end=1_800_000, hour=0)], values=values))
        from research_frozen_pricing import SPECS as FROZEN
        overlay = next(s for s in FROZEN if s['name'] == 'hurdle_all_120')
        before = choose(rows, dates, sessions, overlay)[:3]
        changed = deepcopy(sessions)
        for session in changed[14:]:
            for p in session['values']:
                p['row'].update(move=999999, valid=False)
        changed_rows = deepcopy(rows)
        for r in changed_rows:
            if r['period'] in dates[14:]:
                r.update(move=999999, valid=False)
        self.assertEqual(before, choose(changed_rows, dates, changed, overlay)[:3])

    def test_fixed_mask_preserves_pre_entry_and_censored_counts(self):
        values = references(4)
        values[0].update(paused=True, survived=None)
        values[1].update(shadow_survived=None, survived=None)
        values[1]['row']['valid'] = False
        altered = reprice(values, prior(), spec('static', 'static'))
        combined = fixed_mask(altered, values)
        session = dict(id='case', source='raw', period='day', split='test', mode='restart',
                       intervals=[dict(start=0, end=120_000, hour=0)])
        a, b = measures(session, values, 'base', 'rule')[0], measures(session, combined, 'new', 'rule')[0]
        for k in ('windows', 'eligible_outcomes', 'pre_entry_predictions', 'offered_pre_entry_decisions', 'grid_windows'):
            self.assertEqual(a[k], b[k])


if __name__ == '__main__':
    unittest.main()
