from copy import deepcopy
import unittest

from research_frozen_pricing import (SPECS, choose, fit_overlay, reprice, spec)
from test_flat_pause import prediction
from test_oracle_activity import row


def trained(candidate):
    values = [prediction(day * 10_000_000 + i * 30_000, 30_000, period=str(day))
              for day in range(3) for i in range(100)]
    return fit_overlay(values, candidate)


class FrozenPricingTests(unittest.TestCase):
    def test_frozen_only_and_pause_mask_are_unchanged(self):
        values = [prediction(i * 30_000, 30_000 if i % 2 else 1000) for i in range(100)]
        values[20].update(paused=True, survived=None)
        for s in SPECS:
            result = reprice(values, trained(s))
            self.assertEqual([p['paused'] for p in values], [p['paused'] for p in result])
            for a, b in zip(values, result):
                if a['row']['activity_state'] != 'frozen':
                    self.assertEqual(a['width_ppm'], b['width_ppm'])
                    self.assertEqual(a['shadow_survived'], b['shadow_survived'])
                if b['width_ppm'] is not None:
                    self.assertTrue(1 <= b['width_ppm'] <= 50_000)
            if s['name'] == 'baseline':
                self.assertEqual([p['width_ppm'] for p in values], [p['width_ppm'] for p in result])
        self.assertEqual(values[1]['width_ppm'], 100)

    def test_only_mature_past_eligibility_and_outcomes_change_prices(self):
        values = [prediction(i * 30_000, 30_000) for i in range(80)]
        for p in values:
            p['row']['move'] = 0
        changed = deepcopy(values)
        for p in changed[40:]:
            p['row'].update(valid=False, move=100_000)
        for s in SPECS:
            a, b = reprice(values, trained(s)), reprice(changed, trained(s))
            self.assertEqual([p['width_ppm'] for p in a[:42]], [p['width_ppm'] for p in b[:42]])
            self.assertTrue(all(p['width_ppm'] is not None for p in b[40:]))

    def test_offered_pool_does_not_learn_from_refused_outcomes(self):
        values = [prediction(i * 30_000, 30_000) for i in range(80)]
        for p in values[:40]:
            p.update(paused=True, survived=None)
            p['row']['move'] = 0
        offered = reprice(values, trained(next(s for s in SPECS if s['name'] == 'offered_frozen_120')))
        all_rows = reprice(values, trained(next(s for s in SPECS if s['name'] == 'all_frozen_120')))
        self.assertEqual(offered[40]['frozen_mature_outcomes'], 0)
        self.assertEqual(all_rows[40]['frozen_mature_outcomes'], 39)
        self.assertEqual(offered[42]['frozen_mature_outcomes'], 1)

    def test_hurdle_mixture_and_minimum_width(self):
        s = spec('hurdle', memory=120, offered=False, prior=4, step=1, hurdle=True)
        s['minimum'] = 1
        model = trained(s)
        model.update(training_floor=.25, training_positive_ratios=[(2, 1), (4, 1)], minimum_correction=.001)
        values = [prediction(i * 30_000, 30_000) for i in range(3)]
        values[0]['row']['move'] = 0
        output = reprice(values, model)
        self.assertAlmostEqual(output[2]['frozen_floor_estimate'], .4)
        self.assertEqual(output[2]['width_ppm'], 200)
        model['spec'] = dict(s, prior_mass=1)
        output = reprice(values, model)
        self.assertGreater(output[2]['frozen_floor_estimate'], .48)
        self.assertEqual(output[2]['width_ppm'], 1)

    def test_entry_clock_updates_private_correction_without_repricing_other_states(self):
        s = spec('hurdle', memory=120, offered=False, prior=.1, hurdle=True)
        s['minimum'] = 1
        model = trained(s)
        values = [prediction(0, 30_000)] + [prediction(i * 30_000, 1000) for i in range(1, 12)] + [prediction(360_000, 30_000)]
        values[0]['row']['move'] = 0
        slow = reprice(values, model)
        model['spec'] = dict(s, entry_clock=True)
        clock = reprice(values, model)
        self.assertLess(clock[-1]['width_ppm'], slow[-1]['width_ppm'])
        self.assertTrue(all(p['width_ppm'] == 100 for p in clock[1:-1]))
        for a, b in zip(clock[2:], clock[3:]):
            self.assertGreaterEqual(b['frozen_correction'], a['frozen_correction'] * .98 - 1e-12)

    def test_period_reset_and_four_hour_memory_expiry(self):
        s = spec('rolling', memory=120, offered=False)
        values = [prediction(i * 30_000, 30_000) for i in range(40)]
        values += [prediction(20_000_000, 30_000), prediction(20_030_000, 30_000, period='next')]
        result = reprice(values, trained(s))
        self.assertEqual(result[-2]['frozen_mature_outcomes'], 0)
        self.assertEqual(result[-1]['frozen_mature_outcomes'], 0)
        self.assertEqual(result[-1]['frozen_correction'], 1)

    def test_future_periods_cannot_choose_overlay(self):
        dates = [f'day-{i:02d}' for i in range(24)]
        rows = [row(day * 10_000_000 + i * 30_000, date, activity='frozen' if i % 3 == 0 else 'active', move=100 + i % 31)
                for day, date in enumerate(dates) for i in range(60)]
        before = choose(rows, dates)
        changed = deepcopy(rows)
        for r in changed:
            if r['period'] in dates[14:]:
                r.update(move=0, valid=False)
        self.assertEqual(before, choose(changed, dates))

    def test_perfectly_flat_shadow_loss_does_not_divide_by_zero(self):
        dates = [f'day-{i:02d}' for i in range(24)]
        rows = [row(day * 10_000_000 + i * 30_000, date, activity='frozen', move=0)
                for day, date in enumerate(dates) for i in range(60)]
        chosen, ranking, folds = choose(rows, dates)
        self.assertEqual(chosen['name'], 'baseline')
        self.assertTrue(all(f['loss_guard_penalty'] == 0 for f in folds))


if __name__ == '__main__':
    unittest.main()
