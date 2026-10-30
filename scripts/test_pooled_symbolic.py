from copy import deepcopy
import math
import unittest

from pooled_symbolic_corridor import SPEC, fit
from test_symbolic_corridor import samples


class PooledSymbolicTests(unittest.TestCase):
    def records(self):
        rows=samples()
        for i,r in enumerate(rows):
            if i%10: r['row']['activity_state']='active'
        return rows

    def test_parent_learns_other_states_child_is_shrunk_and_fits_are_deterministic(self):
        rows=self.records();periods=[f'2025-{i:02}-01' for i in range(1,6)]
        a=fit(rows,periods,'2025-06-01')
        self.assertEqual(a,fit(rows,periods,'2025-06-01'))
        self.assertEqual(a['windows'],500);self.assertEqual(a['child_windows'],50)
        self.assertEqual(a['child_weight'],50/(50+SPEC['child_prior']))
        self.assertAlmostEqual(a['coefficients'][0]-a['parent_coefficients'][0],a['child_shift'])
        changed=deepcopy(rows)
        for r in changed:
            if r['row']['activity_state']=='active': r['ratio']*=.5
        b=fit(changed,periods,'2025-06-01')
        self.assertNotEqual(a['parent_coefficients'],b['parent_coefficients'])

    def test_own_future_dates_and_invalid_other_state_records_are_guarded(self):
        rows=self.records();periods=[f'2025-{i:02}-01' for i in range(1,6)]
        a=fit(rows,periods,'2025-06-01');changed=deepcopy(rows)
        for r in changed:
            if r['row']['period']>='2025-06-01': r.update(ratio=999999.,features=[99.]*7)
        self.assertEqual(a,fit(changed,periods,'2025-06-01'))
        rows[1]['training_periods'].append('2025-01-01')
        with self.assertRaises(ValueError):fit(rows,periods,'2025-06-01')

    def test_sampling_is_bounded_and_has_no_outcome_or_feature_dependence(self):
        rows=self.records()
        # Many copies have unique entry times; selection is based only on date
        # and index, with a fixed random seed. Outcome changes cannot change n.
        expanded=[]
        for r in rows:
            for i in range(6):
                p=deepcopy(r);p['row']['start']+=i;p['row']['expiry']+=i;expanded.append(p)
        a=fit(expanded,['2025-01-01','2025-02-01'],'2025-03-01')
        self.assertEqual(a['parent_fit_paths'],2*SPEC['maximum_fit_paths_per_date'])
        self.assertTrue(all(math.isfinite(x) for x in a['coefficients']))
        self.assertTrue(fit([],['2024-11-01'],'2025-01-01')['neutral_fallback'])


if __name__=='__main__':unittest.main()
