from copy import deepcopy
import unittest

from research_activity_calibration import SPECS as ENGINE_SPECS, fit, predict
from research_flat_pause import SPECS, apply_pause, choose, diagnostics, episodes
from test_oracle_activity import row, training


def candidate(name):
    return next(s for s in SPECS if s['name'] == name)


def prediction(at, idle=0, changes=0, period='day', valid=True):
    r = row(at, period, activity='frozen' if idle >= 30_000 else 'sparse')
    r['valid'] = valid
    r['activity_features'].update(idle_ms=idle, changes_30=changes, changes_60=changes)
    return dict(row=r, width_ppm=100, correction=1, local_outcomes=0,
                predicted_floor=0, paused=False, floor_reason='',
                shadow_survived=True if valid else None,
                survived=True if valid else None, capped=False)


class FlatPauseTests(unittest.TestCase):
    def test_exact_idle_boundary_does_not_use_outcome_eligibility(self):
        values = [prediction(0, 59_999), prediction(30_000, 60_000, valid=False),
                  prediction(60_000, 60_001)]
        result = apply_pause(values, candidate('idle_60s'))
        self.assertEqual([p['paused'] for p in result], [False, True, True])
        self.assertEqual(diagnostics(result)['paused_pre_entry_decisions'], 2)
        self.assertEqual(diagnostics(result)['paused_eligible_outcomes'], 1)
        self.assertEqual(diagnostics(result)['eligible_outcomes'], 2)
        self.assertEqual(diagnostics(result)['pre_entry_predictions'], 3)

    def test_recovery_requires_two_changes_and_survives_missing_features(self):
        values = [prediction(0, 60_000), prediction(30_000, 1000, 1),
                  prediction(60_000), prediction(90_000, 1000, 2),
                  prediction(120_000, 60_000)]
        values[2]['width_ppm'] = None
        values[2]['row']['activity_features'] = None
        values[2]['shadow_survived'] = None
        result = apply_pause(values, candidate('idle_60s_recover_2_in_30s'))
        self.assertEqual([p['paused'] for p in result], [True, True, False, False, True])
        # A new day resets the latch even if no two-change recovery was observed.
        reset = [prediction(0, 60_000), prediction(30_000, 1000, 1, period='next')]
        self.assertEqual([p['paused'] for p in apply_pause(reset, candidate('idle_60s_recover_2_in_30s'))], [True, False])

    def test_floor_requires_frozen_context_and_mature_minimum(self):
        values = [prediction(i * 30_000, 30_000) for i in range(4)]
        for p in values:
            p.update(local_outcomes=30, predicted_floor=.54)
        values[0]['local_outcomes'] = 29
        values[1]['predicted_floor'] = .53
        values[2]['row']['activity_state'] = 'sparse'
        self.assertEqual([p['paused'] for p in apply_pause(values, candidate('frozen_floor_53'))],
                         [False, False, False, True])

    def test_existing_parity_and_no_pause_ablation_preserve_shadow_paths(self):
        values = [prediction(0), prediction(30_000)]
        values[0].update(paused=True, survived=None, floor_reason='old_rule')
        self.assertEqual(apply_pause(values, candidate('existing')), values)
        for s in SPECS:
            result = apply_pause(values, s)
            self.assertEqual([(p['width_ppm'], p['correction'], p['shadow_survived']) for p in values],
                             [(p['width_ppm'], p['correction'], p['shadow_survived']) for p in result])
        result = apply_pause(values, candidate('no_pause'))
        self.assertTrue(all(not p['paused'] and p['survived'] for p in result))
        self.assertTrue(values[0]['paused'])  # Never mutate the retained input.

    def test_current_and_future_outcomes_cannot_change_earlier_decisions(self):
        model = fit(training(), next(s for s in ENGINE_SPECS if s['name'] == 'activity_pause_wide'))
        rows = [row(i * 30_000, activity='frozen', move=0) for i in range(80)]
        for r in rows:
            r['activity_features']['idle_ms'] = 60_000
        changed = deepcopy(rows)
        for r in changed[50:]:
            r.update(valid=False, move=1_000_000)
        a, b = predict(rows, model), predict(changed, model)
        for s in SPECS:
            pa, pb = apply_pause(a, s), apply_pause(b, s)
            # Row 50 matures only at row 52, including the post-expiry delay.
            self.assertEqual([p['paused'] for p in pa[:52]], [p['paused'] for p in pb[:52]])

    def test_episode_grid_gaps_and_missing_history_do_not_count_as_refused(self):
        values = [prediction(0, 60_000), prediction(30_000, 60_000),
                  prediction(90_000, 60_000), prediction(120_000)]
        result = episodes(apply_pause(values, candidate('idle_60s')))
        self.assertEqual([e['decisions'] for e in result], [2, 1])
        self.assertEqual([e['grid_duration_ms'] for e in result], [60_000, 30_000])
        with self.assertRaises(ValueError):
            apply_pause(list(reversed(values)), candidate('existing'))

    def test_outer_and_native_rows_cannot_select_the_pause(self):
        dates = [f'day-{i:02d}' for i in range(24)]
        rows = [row(day * 10_000_000 + i * 30_000, date, move=100 + i % 31)
                for day, date in enumerate(dates) for i in range(60)]
        a = choose(rows, dates)
        changed = deepcopy(rows)
        for r in changed:
            if r['period'] in dates[14:]:
                r.update(valid=False, move=0, activity_state='frozen')
                r['activity_features']['idle_ms'] = 999_000
        changed.append(row(999_000_000, 'native'))
        self.assertEqual(a, choose(changed, dates))


if __name__ == '__main__':
    unittest.main()
