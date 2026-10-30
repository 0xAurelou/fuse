from copy import deepcopy
import unittest

from research_bursty_startup_raw import phase_cells,phase_error,availability_charge,paired
from research_nonfrozen_pricing import measures
from test_bursty_pricing import references


def session(mode='restart'):
    return dict(id=mode,source='raw',period='day',split='test',mode=mode,
                intervals=[dict(start=0,end=900000,hour=0)])


class BurstyStartupResearchTests(unittest.TestCase):
    def test_phase_membership_survives_refusal_and_censoring(self):
        values=references(30,move=50)
        for p in values[:5]:p.update(paused=True,survived=None)
        values[0]['row']['valid']=False;values[0]['shadow_survived']=None
        cells=phase_cells(session(),values,'gate','policy')
        self.assertEqual(cells[0]['grid_windows'],12)
        self.assertEqual(cells[0]['eligible_outcomes'],11)
        self.assertEqual(cells[0]['windows'],7)
        self.assertEqual(cells[1]['grid_windows'],18)
        for p in values:p.update(paused=True,survived=None)
        empty=phase_cells(session(),values,'gate','policy')
        self.assertEqual(phase_error(empty),52)
        self.assertEqual(empty[0]['eligible_outcomes'],11)
        self.assertIsNone(empty[0]['survival'])

    def test_lost_quotes_and_removed_populated_cases_are_charged(self):
        values=references(30,move=50)
        baseline=measures(session(),values,'base','policy')
        self.assertEqual(availability_charge(baseline,baseline),0)
        for p in values[:20]:p.update(paused=True,survived=None)
        masked=measures(session(),values,'gate','policy')
        self.assertGreater(availability_charge(masked,baseline),50)
        burst=next(r for r in masked if r['activity']=='bursty')
        self.assertEqual((burst['eligible_outcomes'],burst['windows']),(30,10))

    def test_pairing_reports_common_eligibility_and_both_offered_paths(self):
        a=references(5,move=50);b=deepcopy(a)
        for p in a[:2]:p.update(paused=True,survived=None)
        for p in b[2:4]:p.update(paused=True,survived=None)
        result=paired([session('restart'),session('continuous')],
                      {'restart':a,'continuous':b},'gate','policy')[0]
        self.assertEqual(result['common_paths'],5)
        self.assertEqual(result['both_offered'],1)
        self.assertEqual(result['pause_disagreements'],4)
        self.assertEqual((result['restart_offered_common'],result['continuous_offered_common']),(3,3))
        b[0]['row']['move']+=1
        with self.assertRaises(ValueError):paired([session('restart'),session('continuous')],
                      {'restart':a,'continuous':b},'gate','policy')


if __name__=='__main__':unittest.main()
