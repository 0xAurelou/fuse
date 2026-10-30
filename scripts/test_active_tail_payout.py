from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from active_tail_payout import (VARIANTS,admissible,calibration_level,cdf,fit,forecast,levels,quote)
from audit_payout_walkforward import same
from payout_empirical import EmpiricalPredictor
from research_active_tail import independent_quote,study_asset,audit_asset
from research_trial_liquidity import WARMUP_DATES
from test_trial_payout import matched


def packet():
    d=dict(n=1000,dates=list(WARMUP_DATES[:6]),value=[.1,1.],weight=[.001,.999])
    return dict(model=dict(positive_rows=1000),empirical=dict(anchors={'slow':dict(global_distribution=d,families={'activity':{}})}),
        levels={str(m):{g:dict(level=.95/m,supported=False) for g in ('global','weekday','weekend')} for m in (100,1000)})


class ActiveTailTests(unittest.TestCase):
    def test_x1000_can_offer_with_parametric_support_but_not_fake_empirical_support(self):
        r=matched('2026-09-01',12);p=packet();f=dict(p0=.00001,floor=.00001,mu=0.,sigma=.3)
        value=quote(r,1000,'active_parametric',p,EmpiricalPredictor(p['empirical']),f)
        self.assertTrue(value['offered']);self.assertFalse(value['old_tail_supported']);self.assertIsNone(value['tail_supported'])
        self.assertLessEqual(value['model_survival'],.00095+1e-10)
        control=quote(r,1000,'active_empirical',p,EmpiricalPredictor(p['empirical']),f)
        self.assertFalse(control['offered']);self.assertIn('insufficient_positive_tail_support',control['reason'])

    def test_native_ppb_touch_and_future_outcome_invariance(self):
        r=matched('2026-09-01',12);p=packet();f=dict(p0=.00001,floor=.00001,mu=0.,sigma=.3);predictor=EmpiricalPredictor(p['empirical'])
        a=quote(r,1000,'active_parametric',p,predictor,f);delta=a['barrier_delta_units']
        self.assertNotEqual(a['width_ppb']%1000,0)
        inside=quote(dict(r,move=delta-1),1000,'active_parametric',p,predictor,f)
        touch=quote(dict(r,move=delta),1000,'active_parametric',p,predictor,f)
        invalid=quote(dict(r,move=999999999,valid=False),1000,'active_parametric',p,predictor,f)
        self.assertTrue(inside['survived']);self.assertFalse(touch['survived']);self.assertIsNone(invalid['shadow'])
        self.assertEqual({k:v for k,v in a.items() if k not in ('shadow','survived')},{k:v for k,v in invalid.items() if k not in ('shadow','survived')})

    def test_flat_or_unrepresentable_risk_cannot_force_an_offer(self):
        r=matched('2026-09-01',12);p=packet();predictor=EmpiricalPredictor(p['empirical'])
        f=dict(p0=.001,floor=.001,mu=0.,sigma=.3)
        self.assertFalse(quote(r,1000,'active_parametric',p,predictor,f)['offered'])
        f=dict(p0=.00001,floor=.00001,mu=-30.,sigma=.15)
        self.assertEqual(quote(r,1000,'active_parametric',p,predictor,f)['reason'],'minimum_width_budget')
        r['activity_features'].update(idle_ms=90000,changes_30=0)
        for variant in VARIANTS:self.assertFalse(quote(r,1000,variant,p,predictor,dict(p0=0.,floor=0.,mu=0.,sigma=.3))['offered'])

    def test_calibration_support_identity_and_maturity_are_explicit(self):
        refs=[dict(asset='ETH',period=WARMUP_DATES[i%3],start=i,expiry=i+30000,weekend=False,score=(i+.5)/2400) for i in range(2400)]
        level=calibration_level(refs,100,'global')
        self.assertTrue(level['supported']);self.assertAlmostEqual(level['level'],.0095,delta=.001)
        self.assertFalse(calibration_level(refs,1000,'global')['supported'])
        all_levels=levels(refs,'2026-09-01');self.assertEqual(all_levels['1000']['global']['level'],.00095)
        with self.assertRaisesRegex(ValueError,'duplicate'):levels(refs+[refs[0]],'2026-09-01')
        with self.assertRaisesRegex(ValueError,'Future'):levels([dict(refs[0],period='2026-09-01')],'2026-09-01')

    def test_only_earlier_admissible_asset_paths_fit_the_model(self):
        rows=[matched(d,i,i%7==0) for d in WARMUP_DATES for i in range(64)]
        a=fit(rows,'ETH','2025-07-01');changed=deepcopy(rows)
        for r in changed:
            if r['period']>='2025-07-01':r['move']=9999999
        self.assertEqual(a,fit(changed,'ETH','2025-07-01'))
        self.assertEqual(a['rows'],sum(r['period']<'2025-07-01' and admissible(r) for r in rows))
        with self.assertRaisesRegex(ValueError,'asset-specific'):fit(rows,'HYPE','2025-07-01')

    def test_independent_native_quote_replay(self):
        r=matched('2026-09-01',12);p=packet();f=dict(p0=.00001,floor=.00001,mu=0.,sigma=.3)
        for m in (100,1000):
            for v in VARIANTS:
                actual=quote(r,m,v,p,EmpiricalPredictor(p['empirical']),f)
                same(actual,independent_quote(r,m,v,p,{},f))

    def test_complete_causal_fit_export_calibration_and_audit(self):
        earlier=[matched(d,i,i%7==0) for d in WARMUP_DATES for i in range(64)]
        dates=('2026-09-04','2026-09-05');oof=('2025-07-01','2025-08-01');rows=[matched(d,i,i%7==0) for d in dates for i in range(64)]
        with tempfile.TemporaryDirectory() as tmp,patch('research_active_tail.DATES',dates),patch('research_active_tail.OOF_DATES',oof),patch('builtins.print'):
            root=Path(tmp);result=study_asset('ETH',earlier,rows,root);self.assertEqual(len(result['origins']),4)
            a=audit_asset('ETH',earlier,rows,root/'ETH');self.assertEqual(a['decisions_independently_replayed'],256*2*len(VARIANTS))
            path=root/'ETH/predictions.jsonl.gz';path.write_bytes(path.read_bytes()+b'tamper')
            with self.assertRaisesRegex(ValueError,'differs'):audit_asset('ETH',earlier,rows,root/'ETH')


if __name__=='__main__':unittest.main()
