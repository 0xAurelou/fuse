import unittest
from unittest.mock import patch

from research_frozen_pricing import SPECS as PRICING
from research_startup_admission import choose, measures, priced, summarize
from startup_admission import SPECS, admit, spec
from validate_admission_controls import joint_checks
from test_flat_pause import prediction
from test_oracle_activity import row


def paths(count=100):
    result = [prediction(i * 30_000, 30_000) for i in range(count)]
    for p in result:
        p['width_ppm'] = 200  # move=100 survives, but fails the 1-ppm minimum.
    return result


class StartupAdmissionTests(unittest.TestCase):
    def test_warmup_uses_only_mature_eligible_references_even_while_paused(self):
        rule = spec('warm', warm=3)
        values = paths(8)
        output = admit(values, rule)
        self.assertEqual([p['admission_mature'] for p in output[:5]], [0, 0, 1, 2, 3])
        self.assertEqual([p['paused'] for p in output[:5]], [True, True, True, True, False])
        values[0]['row']['valid'] = False
        values[0]['shadow_survived'] = None
        output = admit(values, rule)
        self.assertTrue(output[4]['paused'])
        self.assertFalse(output[5]['paused'])

    def test_current_and_future_outcomes_do_not_change_earlier_decisions(self):
        values, changed = paths(), paths()
        for p in changed[50:]:
            p['row'].update(move=0, valid=False)
            p['shadow_survived'] = None
        for rule in SPECS:
            a, b = admit(values, rule), admit(changed, rule)
            self.assertEqual([p['paused'] for p in a[:52]], [p['paused'] for p in b[:52]], rule['name'])

    def test_hysteresis_needs_lower_floor_and_new_mature_outcomes(self):
        values = paths(18)
        for p in values[:4]:
            p['row']['move'] = 0
        rule = spec('hysteresis', warm=2, memory=4, resume=.25, recovery=2)
        output = admit(values, rule)
        self.assertTrue(output[7]['paused'])  # floor=.5, already below entry threshold.
        self.assertFalse(output[8]['paused'])  # floor=.25 plus sufficient new evidence.
        rule['recovery_outcomes'] = 10
        output = admit(values, rule)
        self.assertTrue(output[8]['paused'])
        self.assertFalse(output[13]['paused'])

    def test_shadow_guard_is_separate_from_minimum_width_floor(self):
        values = paths(12)
        for p in values[:4]:
            p['row']['move'] = 500
            p['shadow_survived'] = False
        rule = spec('shadow', warm=2, memory=4, shadow=True, recovery=2)
        rule['shadow_minimum'] = 4
        output = admit(values, rule)
        self.assertEqual(output[5]['admission_floor'], 0)
        self.assertIn('recent_shadow_calibration', output[5]['floor_reason'])
        self.assertTrue(output[6]['paused'])
        self.assertFalse(output[7]['paused'])

    def test_missing_history_reset_flushes_pending_and_rearms_warmup(self):
        values = paths(12)
        values[5]['width_ppm'] = None
        values[5]['row']['activity_features'] = None
        values[5]['shadow_survived'] = None
        output = admit(values, spec('reset', warm=3, reset=True))
        self.assertEqual(output[6]['admission_mature'], 0)
        self.assertTrue(output[9]['paused'])
        self.assertFalse(output[10]['paused'])

    def test_outcome_age_and_period_boundary_rearm_startup(self):
        values = paths(20)
        extra = prediction(20_000_000, 30_000)
        extra['width_ppm'] = 200
        values.append(extra)
        values.append(prediction(20_030_000, 30_000, period='next'))
        output = admit(values, spec('warm', warm=3))
        self.assertTrue(output[-2]['paused'])
        self.assertEqual(output[-2]['admission_mature'], 0)
        self.assertTrue(output[-1]['paused'])

    def test_dual_memory_catches_new_floor_while_slow_pool_is_low(self):
        values = paths(125)
        for p in values[80:]:
            p['row']['move'] = 0
        slow = admit(values, spec('slow'))
        dual = admit(values, spec('dual', fast=30))
        self.assertLess(dual[119]['admission_slow_floor'], .53)
        self.assertGreater(dual[119]['admission_fast_floor'], .53)
        self.assertFalse(slow[119]['paused'])
        self.assertTrue(dual[119]['paused'])

    def test_conditional_startup_uses_only_pre_entry_flatness(self):
        rule = spec('risk', risky=True)
        values = paths(4)
        values[1]['row']['activity_features']['idle_ms'] = 60_000
        values[2]['row']['activity_features']['empty_bins_300'] = .5
        output = admit(values, rule)
        self.assertEqual([p['paused'] for p in output], [False, True, True, False])

    def test_time_weighted_floor_discounts_older_regime(self):
        values = paths(125)
        for p in values[80:]:
            p['row']['start'] += 3_600_000
            p['row']['expiry'] += 3_600_000
            p['row']['move'] = 0
        uniform = admit(values, spec('uniform'))
        weighted = admit(values, spec('weighted', ewma=True))
        self.assertGreater(weighted[-1]['admission_floor'], uniform[-1]['admission_floor'])
        self.assertTrue(weighted[-1]['paused'])
        self.assertFalse(uniform[-1]['paused'])

    def test_floor_boundary_is_strict_and_pool_size_is_bounded(self):
        values = paths(130)
        for p in values[:53]:
            p['row']['move'] = 0
        output = admit(values, spec('boundary', warm=100, memory=100))
        self.assertEqual(output[101]['admission_floor'], .53)
        self.assertFalse(output[101]['paused'])
        self.assertEqual(max(p['admission_mature'] for p in output), 100)

    def test_baseline_non_frozen_widths_and_full_shadow_denominator_are_preserved(self):
        values = paths(40)
        values[0].update(paused=True, survived=None, floor_reason='previous')
        values[5]['row']['activity_state'] = 'active'
        for rule in SPECS:
            output = admit(values, rule)
            self.assertEqual([(p['width_ppm'], p['shadow_survived']) for p in values],
                             [(p['width_ppm'], p['shadow_survived']) for p in output])
            self.assertEqual(output[5]['paused'], values[5]['paused'])
        output = admit(values, SPECS[0])
        self.assertEqual([p['paused'] for p in output], [p['paused'] for p in values])
        session = dict(id='test', source='raw', period='day', split='test', mode='restart',
                       intervals=[dict(start=0, end=8 * 3_600_000, hour=0)])
        cells = measures(session, admit(paths(20), spec('warm', warm=30)), 'warm')
        frozen = next(r for r in summarize(cells) if r['activity'] == 'frozen')
        self.assertEqual(frozen['eligible_outcomes'], 20)
        self.assertEqual(frozen['quoted_outcomes'], 0)
        self.assertEqual(frozen['cases_pass_with_at_least20'], 0)
        self.assertEqual(frozen['zero_quote_cases'], 1)
        with self.assertRaises(ValueError):
            admit(list(reversed(values)), rule)

    def test_outer_rows_and_observations_cannot_select_rule(self):
        dates = [f'day-{i:02d}' for i in range(24)]
        rows = [row(day * 10_000_000 + i * 30_000, date, move=100 + i % 31)
                for day, date in enumerate(dates) for i in range(60)]
        class OnlyEarlier(dict):
            def __getitem__(self, day):
                if day not in dates[:14]:
                    raise AssertionError('outer observations read during selection')
                return []
        def sessions(day, observed, engine, overlay, source, split, **kwargs):
            part = [r for r in rows if r['period'] == day]
            return [dict(id=day, source=source, period=day, split=split, mode='restart',
                         intervals=[dict(start=part[0]['start'], end=part[-1]['expiry'], hour=0)],
                         values=priced(part, engine, overlay))]
        pricing = next(s for s in PRICING if s['name'] == 'hurdle_all_120')
        with patch('research_startup_admission.day_sessions', side_effect=sessions):
            first = choose(rows, dates, OnlyEarlier(), pricing)
            for r in rows:
                if r['period'] in dates[14:]:
                    r.update(valid=False, move=0, activity_state='frozen')
            self.assertEqual(first, choose(rows, dates, OnlyEarlier(), pricing))

    def test_joint_pass_requires_actual_offered_samples_and_ignores_continuous_duplicates(self):
        session = dict(id='case', source='raw', period='day', split='test', mode='restart',
                       intervals=[dict(start=0, end=8 * 3_600_000, hour=0)])
        name = SPECS[0]['name']
        empty = measures(session, admit(paths(20), spec('warm', warm=30)), name)
        result = next(r for r in joint_checks(empty) if r['policy'] == name)
        self.assertEqual(result['both_pass'], 0)
        self.assertFalse(result['all_cases_pass'])
        values = paths(20)
        for p in values[:10]:
            p['row']['move'] = 500
            p['shadow_survived'] = False
        measured = measures(session, admit(values, SPECS[0]), name)
        duplicates = [dict(r, mode='continuous') for r in measured]
        result = next(r for r in joint_checks(measured + duplicates) if r['policy'] == name)
        self.assertEqual(result['cases'], 1)
        self.assertEqual(result['both_pass'], 1)
        self.assertTrue(result['all_cases_pass'])


if __name__ == '__main__':
    unittest.main()
