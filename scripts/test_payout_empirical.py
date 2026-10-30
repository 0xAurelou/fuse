from copy import deepcopy
from datetime import datetime, timezone
import gzip
import json
from pathlib import Path
import tempfile
import unittest

from payout_risk import fit_positive, fit_risk
from payout_empirical import (EmpiricalPredictor, calibrated, entry, fit_calibrator,
    fit_movement, out_of_fold, pava, policies, selection_score)
from research_payout_empirical import context, predict, select, study_asset
from test_payout_risk import row


def fixture():
    days=['2024-11-01','2024-12-01']+[f'2025-{m:02d}-01' for m in range(1,13)]+[f'2026-{m:02d}-01' for m in range(1,11)]
    return [row(day,i,i%5==0) for day in days for i in range(60)]


class EmpiricalPayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows=fixture();train=[r for r in cls.rows if r['split']=='train']
        cls.risk=fit_risk(train,'ETH','2026-01-01','timing',.0001)
        cls.old_positive=fit_positive(train,'ETH','2026-01-01','timing')
        cls.folds,cls.oof=out_of_fold(cls.rows,cls.risk)
        cls.packet=dict(asset='ETH',risk=cls.risk,v1_positive=cls.old_positive,
                        calibrators={str(p):fit_calibrator(cls.oof,p) for p in (32,128)},
                        movement=fit_movement(cls.rows,'ETH'))
        cls.baseline={m:{r['start']:10 for r in cls.rows if r['split']!='train'} for m in (100,1000)}

    def test_fold_coefficients_exclude_own_and_future_dates(self):
        self.assertEqual(set(self.folds),{'6','9','12'})
        for record in self.oof:
            model=self.folds[str(record['fold'])]
            self.assertNotIn(record['period'],model['training_dates'])
            self.assertTrue(all(day<record['period'] for day in model['training_dates']))
        changed=deepcopy(self.rows)
        for r in changed:
            if r['split']!='train':r.update(move=999999,valid=False)
        self.assertEqual((self.folds,self.oof),out_of_fold(changed,self.risk))

    def test_supported_probability_bins_are_monotone_and_nested(self):
        refs=[]
        for day in ('2025-01-01','2025-02-01','2025-03-01'):
            for i in range(100):
                refs.append(dict(period=day,p0=.0003,floor=.0003,zero=i%5==0,minimum=i%5==0))
                refs.append(dict(period=day,p0=.001,floor=.001,zero=i==0,minimum=i==0))
        model=fit_calibrator(refs,32)
        a,b=calibrated((.0003,.0003),model),calibrated((.001,.001),model)
        self.assertTrue(a['calibrated_floor'] and b['calibrated_floor'])
        self.assertLessEqual(a['floor'],b['floor'])
        self.assertTrue(0<a['p0']<=a['floor']<1)
        self.assertEqual(pava([.9,.1,.2],[1,1,4]),[.3,.3,.3])

    def test_unsupported_bins_fall_back_without_zero_probability_claim(self):
        refs=[dict(period='2025-01-01',p0=.001,floor=.001,zero=False,minimum=False)]*20
        model=fit_calibrator(refs,32)
        actual=calibrated((.001,.001),model)
        self.assertEqual(actual['floor'],.001)
        self.assertFalse(actual['calibrated_floor'])

    def test_exact_weighted_empirical_cdf_and_no_future_outcome_predictor(self):
        parent=dict(n=40000,dates=['a','b','c'],value=[2.,4.],weight=[.75,.25])
        model=dict(anchors={'slow':dict(global_distribution=parent,families={'activity':{}})})
        predictor=EmpiricalPredictor(model);r=row('2026-06-01',1,False)
        a=predictor.quote(r,dict(floor=0.),1000,'activity','slow',1.,1.)
        self.assertEqual(a['width'],240)
        self.assertTrue(a['tail_supported'])
        self.assertFalse(a['child_supported'])
        changed=dict(r,move=99999,valid=False)
        self.assertEqual(a,predictor.quote(changed,dict(floor=0.),1000,'activity','slow',1.,1.))

    def test_all_positive_references_and_global_tail_support_are_preserved(self):
        for anchor in ('slow','blend'):
            data=self.packet['movement']['anchors'][anchor]
            count=sum(r['split']=='train' and r['valid'] and r['move']>0 for r in self.rows)
            self.assertEqual(data['global_distribution']['n'],count)
            for family,leaves in data['families'].items():
                self.assertEqual(sum(g['n'] for g in leaves.values()),count)
        predictor=EmpiricalPredictor(self.packet['movement'])
        r=row('2026-06-01',1,False)
        a=predictor.quote(r,dict(floor=0.),1000,'activity','slow',1.,1.)
        self.assertFalse(a['tail_supported'])
        self.assertFalse(a['offered'])

    def test_controls_and_calibration_cannot_see_current_outcome(self):
        r=row('2026-06-01',0,True); raw=(.02,.02)
        forecasts={p:dict(p0=.001,floor=.001,calibrated0=True,calibrated_floor=True) for p in (32,128)}
        old=dict(width=1,supported=True)
        predictor=EmpiricalPredictor(self.packet['movement'])
        for policy in policies():
            a=entry(r,100,policy,raw,forecasts,10,old,predictor)
            b=entry(dict(r,move=99999,valid=False),100,policy,raw,forecasts,10,old,predictor)
            self.assertEqual((a['width'],a['offered'],a['reason']), (b['width'],b['offered'],b['reason']))

    def test_policy_selection_excludes_later_outcomes(self):
        a=select(self.rows,self.baseline,self.packet)
        changed=deepcopy(self.rows)
        for r in changed:
            if r['split']=='test':r.update(move=999999,valid=False)
        self.assertEqual(a,select(changed,self.baseline,self.packet))

    def test_zero_quote_policy_is_penalized_and_not_a_success(self):
        rows=[row('2026-01-01',1,False)]
        values=[dict(width=1,shadow=False,offered=False,survived=None)]
        score=selection_score(rows,values,100,.1)
        self.assertGreater(score['score'],1000)
        self.assertIsNone(score['pooled_survival'])
        self.assertFalse(score['meets_availability_reference'])

    def test_end_to_end_exports_both_selected_payouts_and_all_controls(self):
        old=dict(candidates={'fixture':self.risk},selected='fixture',positive=self.old_positive)
        with tempfile.TemporaryDirectory() as tmp:
            result=study_asset('ETH',self.rows,self.baseline,old,Path(tmp))
            self.assertEqual(set(result['selected']),{'100','1000'})
            self.assertEqual(len(result['primary_test']),20)
            with gzip.open(Path(tmp)/'ETH'/'predictions.jsonl.gz','rt') as stream:
                self.assertEqual(sum(1 for _ in stream),600*20)
            saved=json.loads((Path(tmp)/'ETH'/'selection.json').read_text())
            self.assertEqual(saved['100']['policy'],result['selected']['100'])
            from audit_payout_empirical import audit_asset
            audited=audit_asset('ETH',self.rows,self.baseline,Path(tmp)/'ETH')
            self.assertEqual(audited['trace_rows'],12000)
            self.assertTrue(audited['all_positive_cdf_paths_verified'])


if __name__=='__main__':unittest.main()
