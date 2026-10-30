from unittest.mock import patch
import unittest

from audit_payout_walkforward import same
from flat_aware_payout import build_predictors
from flat_risk_overlay import quote
from research_flat_risk_overlay import independent_quote
from test_trial_payout import matched


def packet():
    cdf=dict(n=50000,dates=['2025-01-01','2025-02-01','2025-03-01'],value=[.1,1.],weight=[.005,.995])
    m=dict(anchors={'slow':dict(global_distribution=cdf,families={'activity':{}})})
    return dict(floor={},risk={},movement={name:m for name in ('previous','activity','calendar')})


class ConservativeOverlayTests(unittest.TestCase):
    def test_new_floor_tightens_old_width_and_never_uses_future_outcome(self):
        r=matched('2026-09-01',12);p=packet();predictors=build_predictors(p)
        base=dict(p0=.0001,floor=.0001,calibrated0=False,calibrated_floor=False)
        with patch('flat_risk_overlay.floor_forecast',return_value=dict(p0=.008,floor=.008)):
            a=quote(r,100,p,predictors,base);b=quote(dict(r,move=99999999,valid=False),100,p,predictors,base)
        self.assertTrue(a['offered']);self.assertLess(a['width'],a['previous_width_ppm'])
        self.assertEqual(a['floor'],.008)
        self.assertEqual({k:v for k,v in a.items() if k not in ('shadow','survived')},{k:v for k,v in b.items() if k not in ('shadow','survived')})

    def test_lower_new_estimate_cannot_lower_old_risk_or_relax_missing_book(self):
        r=matched('2026-09-01',12);p=packet();base=dict(p0=.005,floor=.005,calibrated0=False,calibrated_floor=False)
        with patch('flat_risk_overlay.floor_forecast',return_value=dict(p0=.00001,floor=.00001)):
            a=quote(r,100,p,build_predictors(p),base)
        self.assertEqual(a['floor'],.005);self.assertEqual(a['width'],a['previous_width_ppm'])
        with patch('flat_risk_overlay.floor_forecast') as estimator:
            b=quote(dict(r,liquidity=None),100,p,build_predictors(p),dict(p0=None,floor=None,calibrated0=False,calibrated_floor=False))
            self.assertFalse(b['offered']);estimator.assert_not_called()

    def test_independent_replay_matches_across_floors_payouts_and_flat_states(self):
        r=matched('2026-09-01',12);p=packet()
        for old in (.0001,.005,.1):
            for new in (.00001,.002,.02):
                for m in (100,1000):
                    for frozen in (False,True):
                        row=dict(r,activity_features=dict(r['activity_features'],idle_ms=90000 if frozen else 500,changes_30=0 if frozen else 20))
                        base=dict(p0=old,floor=old,calibrated0=False,calibrated_floor=False)
                        with patch('flat_risk_overlay.floor_forecast',return_value=dict(p0=new,floor=new)),patch('research_flat_risk_overlay.manual',return_value=dict(p0=old,floor=old)),patch('research_flat_risk_overlay.manual_floor',return_value=(new,new)):
                            actual=quote(row,m,p,build_predictors(p),base);expected=independent_quote(row,m,p,{})
                            same(actual,expected)
                            if actual['offered']:
                                self.assertTrue(actual['previous_offered']);self.assertLessEqual(actual['width'],actual['previous_width_ppm'])


if __name__=='__main__':unittest.main()
