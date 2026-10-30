from copy import deepcopy
import unittest

from research_nonfrozen_pricing import measures
from research_preentry_bursty import retention,fit_prefix
from test_preentry_bursty import paths


class PreentryResearchTests(unittest.TestCase):
    def test_availability_constraints_do_not_reward_removing_populated_cases(self):
        session=dict(id='x',source='raw',period='2025-01-01',split='test',mode='restart',
                     intervals=[dict(start=0,end=3000000,hour=0)])
        v=paths(100);base=measures(session,v,'baseline','policy')
        self.assertTrue(retention(base,base)['feasible'])
        for p in v[:6]:p.update(paused=True,survived=None)
        r=retention(measures(session,v,'gate','policy'),base)
        self.assertEqual(r['pooled'],.94);self.assertFalse(r['feasible'])

    def test_own_and_future_training_dates_are_rejected_before_any_model_fit(self):
        bundle=dict(training_periods=['2025-01-01'],cutoff='2025-01-01')
        with self.assertRaises(ValueError):fit_prefix([],{},bundle,{}, {})


if __name__=='__main__':unittest.main()
