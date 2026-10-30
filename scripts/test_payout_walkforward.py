from copy import deepcopy
import gzip
import json
from pathlib import Path
import tempfile
import unittest

from payout_empirical import EmpiricalPredictor
from payout_walkforward import (FAMILIES, VARIANTS, fit_origin, floor_bound,
    forecasts, metrics, quote, research_screen, schedule)
from research_payout_walkforward import study_asset
from test_payout_risk import row


def fixture():
    return [row(f'2025-{m:02d}-01',i,i%5==0) for m in range(1,10) for i in range(60)]


class WalkForwardPayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows=fixture();cls.refs={f:[] for f in FAMILIES}
        cls.packet=fit_origin(cls.rows,'ETH','2025-07-01',cls.refs)

    def test_schedule_ignores_old_split_and_never_duplicates_entries(self):
        self.assertEqual(schedule(self.rows,'ETH'),['2025-07-01','2025-08-01','2025-09-01'])
        changed=deepcopy(self.rows)
        for r in changed:r['split']='ignored'
        self.assertEqual(schedule(changed,'ETH'),schedule(self.rows,'ETH'))
        with self.assertRaisesRegex(ValueError,'unique chronological'):schedule(self.rows+self.rows,'ETH')
        with self.assertRaisesRegex(ValueError,'one nonempty asset'):schedule(self.rows,'HYPE')

    def test_own_and_future_labels_cannot_change_origin_fit(self):
        changed=deepcopy(self.rows)
        for r in changed:
            if r['period']>='2025-07-01':r.update(move=999999,valid=False)
        self.assertEqual(self.packet,fit_origin(changed,'ETH','2025-07-01',self.refs))
        self.assertTrue(all(d<'2025-07-01' for d in self.packet['risk']['calendar']['training_dates']))
        self.assertEqual(self.packet['calibration_counts']['timing'],0)

    def test_calibrator_rejects_own_date_and_duplicate_references(self):
        ref=dict(start=self.rows[-1]['start'],expiry=self.rows[-1]['expiry'],period='2025-09-01',
                 p0=.001,floor=.001,zero=False,minimum=False)
        with self.assertRaisesRegex(ValueError,'mature before origin'):
            fit_origin(self.rows,'ETH','2025-07-01',{f:[ref] for f in FAMILIES})
        ref.update(period='2025-01-01',expiry=self.rows[0]['expiry'])
        with self.assertRaisesRegex(ValueError,'duplicate calibration'):
            fit_origin(self.rows,'ETH','2025-07-01',{f:[ref,ref] for f in FAMILIES})

    def test_quotes_do_not_read_current_outcome_or_validity(self):
        r=row('2025-07-01',1);changed=dict(r,move=99999999,valid=False)
        _,a=forecasts(r,self.packet);_,b=forecasts(changed,self.packet)
        self.assertEqual(a,b)
        predictor=EmpiricalPredictor(self.packet['movement'])
        for m in (100,1000):
            for variant in VARIANTS:
                p=quote(r,a.get(variant,dict(p0=None,floor=None,calibrated0=False,calibrated_floor=False)),m,variant,predictor)
                q=quote(changed,b.get(variant,dict(p0=None,floor=None,calibrated0=False,calibrated_floor=False)),m,variant,predictor)
                self.assertEqual({k:v for k,v in p.items() if k not in ('shadow','survived')},
                                 {k:v for k,v in q.items() if k not in ('shadow','survived')})

    def test_floor_bound_matches_exhaustive_best_possible_rejections(self):
        for n in (0,1,10,40):
            for wins in range(n+1):
                for m in (2,100,1000):
                    for target in (False,True):
                        a,b=(19,20*m) if target else (1,m)
                        exact=max(k for k in range(n+1) if max(0,wins-(n-k))*b<=a*k)
                        self.assertEqual(floor_bound(n,wins,m,target),exact)

    def test_empty_or_minimum_width_diagnostic_cannot_qualify(self):
        r=row('2025-07-01',1)
        p=dict(width=1,offered=False,shadow=False,survived=None,p0=.1,floor=.1)
        result=metrics([r],[p],1000)
        self.assertFalse(research_screen(result,1000,'timing_raw_cdf')['qualifies'])
        self.assertIn('lower_bound_diagnostic_only',research_screen(result,1000,'minimum_width_floor')['reasons'])
        self.assertEqual(metrics([],[],1000)['minimum_daily_availability'],0.)

    def test_end_to_end_earlier_only_refit_independent_audit_and_tamper_rejection(self):
        from audit_payout_walkforward import audit_asset
        with tempfile.TemporaryDirectory() as tmp:
            result=study_asset('ETH',self.rows,Path(tmp))
            self.assertEqual(result['unique_evaluated_entries'],180)
            self.assertEqual(result['origins'][0]['calibration_counts']['timing'],0)
            self.assertEqual(result['origins'][1]['calibration_counts']['timing'],60)
            report=audit_asset('ETH',self.rows,Path(tmp)/'ETH')
            self.assertEqual(report['trace_rows'],1800)
            self.assertTrue(report['coefficients_refit_from_earlier_only'])
            directory=Path(tmp)/'ETH';meta=json.loads((directory/'research.json').read_text())
            meta['origins'][0]['training_dates'].append('2025-07-01')
            (directory/'research.json').write_text(json.dumps(meta))
            with self.assertRaisesRegex(ValueError,'training contamination'):
                audit_asset('ETH',self.rows,directory)


if __name__=='__main__':unittest.main()
