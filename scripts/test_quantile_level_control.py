import unittest

from bursty_optimizer import anchors, replay
from quantile_level_control import all_series, series, SPEC


def fixture(count=80):
    values = []
    for i in range(count):
        at = i * 30000
        row = dict(period='one',start=at,expiry=at+30000,activity_state='bursty',oracle_gap={},
                   entry=1000000,move=99,valid=True)
        values.append(dict(row=row,width_ppm=100,shadow_survived=True,survived=True,paused=False))
    return values, [(100,.1)] * count, {'bursty':{'knots':[.5,1.,2.,4.]}}, anchors()[0]


class QuantileLevelControlTests(unittest.TestCase):
    def test_zero_gain_exactly_reconstructs_previous_controller(self):
        values,cache,prior,params = fixture()
        self.assertEqual(series(values,cache,prior,params,0.), replay(values,cache,prior,params))

    def test_delayed_own_feedback_changes_only_after_label_maturity(self):
        values,cache,prior,params = fixture(12)
        first = series(values,cache,prior,params,.1)
        changed = [dict(p,row=dict(p['row'],move=100000)) if i == 0 else p for i,p in enumerate(values)]
        other = series(changed,cache,prior,params,.1)
        self.assertEqual([p['cdf_level'] for p in first[:2]],[p['cdf_level'] for p in other[:2]])
        self.assertLess(first[2]['cdf_level'],other[2]['cdf_level'])
        self.assertEqual(first[2]['cdf_evidence'],1)

    def test_refused_clean_references_learn_and_invalid_references_do_not(self):
        values,cache,prior,params = fixture()
        actual = series(values,cache,prior,params,.03)
        refused = series([dict(p,paused=True,survived=None) for p in values],cache,prior,params,.03)
        self.assertEqual([(p['width_ppm'],p['cdf_level']) for p in actual],
                         [(p['width_ppm'],p['cdf_level']) for p in refused])
        invalid = series([dict(p,row=dict(p['row'],valid=False)) for p in values],cache,prior,params,.03)
        self.assertTrue(all(p['cdf_evidence']==0 and p['cdf_level']==.48 for p in invalid))

    def test_future_labels_and_unsupported_states_cannot_update_past_prices(self):
        values,cache,prior,params = fixture()
        actual = series(values,cache,prior,params,.03)
        changed = [dict(p,row=dict(p['row'],move=100000,valid=False)) if i >= 20 else p
                   for i,p in enumerate(values)]
        other = series(changed,cache,prior,params,.03)
        self.assertEqual([p['width_ppm'] for p in actual[:22]],[p['width_ppm'] for p in other[:22]])
        mixed = [dict(p,row=dict(p['row'],activity_state='active')) if i%2 else p for i,p in enumerate(values)]
        mixed_cache = [None if i%2 else item for i,item in enumerate(cache)]
        out = series(mixed,mixed_cache,prior,params,.03)
        self.assertTrue(all(out[i] == mixed[i] for i in range(1,len(out),2)))
        with self.assertRaisesRegex(ValueError,'support differs'):series(mixed,cache,prior,params,.03)

    def test_private_restart_and_stale_resets_do_not_reset_continuous_intervals(self):
        values,cache,prior,params = fixture()
        reset = values[:40]+[dict(p,row=dict(p['row'],period='two')) for p in values[40:]]
        out = series(reset,cache,prior,params,.03)
        self.assertEqual(out[40]['cdf_level'],.48)
        self.assertEqual(out[40]['cdf_evidence'],0)
        continuous = series(values,cache,prior,params,.03)
        self.assertNotEqual(continuous[40]['cdf_level'],.48)
        gap = int(params['half_life_minutes'] * 60000 * params['age_halflives'])+100000
        stale = values[:40]+[dict(p,row=dict(p['row'],start=p['row']['start']+gap,expiry=p['row']['expiry']+gap)) for p in values[40:]]
        out = series(stale,cache,prior,params,.03)
        self.assertEqual(out[40]['cdf_level'],.48)
        self.assertEqual(out[40]['cdf_evidence'],0)

    def test_relaxed_correction_remains_bounded_by_absolute_width(self):
        values,cache,_,params = fixture()
        prior = {'bursty':{'knots':[100000.]}}
        out = series(values,cache,prior,params,.1,True)
        self.assertTrue(all(1 <= p['width_ppm'] <= 50000 for p in out))
        self.assertTrue(any(p['capped'] for p in out))
        self.assertTrue(all(SPEC['levels'][0] <= p['cdf_level'] <= SPEC['levels'][1] for p in out))
        with self.assertRaisesRegex(ValueError,'declared gain'):series(values,cache,prior,params,.07)

    def test_persistent_distribution_shift_changes_quantile_level(self):
        values,cache,prior,params = fixture(320)
        prior = {'bursty':{'knots':[i/100 for i in range(1,401)]}}
        values = [dict(p,row=dict(p['row'],move=((i*53)%200+1 if i<160 else (i*53)%200+151)-1))
                  for i,p in enumerate(values)]
        params = dict(params,prior_mass=24.)
        out = all_series(values,cache,prior,params)
        static = out['optimized'][240:]
        adaptive = out['cdf_medium_bounded'][240:]
        error = lambda part: abs(sum(p['shadow_survived'] for p in part)/len(part)-.48)
        self.assertLess(error(adaptive),error(static))
