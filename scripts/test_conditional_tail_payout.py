from copy import deepcopy
import gzip
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from active_tail_payout import forecast
from conditional_tail_payout import VARIANTS,calibration,levels,quote,reference
from payout_empirical import EmpiricalPredictor
from research_active_tail import study_asset as parent_study
from research_conditional_tail import study_asset,verify_levels
from research_payout_risk import dump
from research_trial_liquidity import WARMUP_DATES
from test_active_tail_payout import packet
from test_trial_payout import matched


class ConditionalTailTests(unittest.TestCase):
    def refs(self):
        return [dict(asset='ETH',start=i,expiry=i+30000,period=WARMUP_DATES[i%3],weekend=False,p0=.00001 if i<1000 else .5,admission=.00002 if i<1000 else .51,win_threshold=.004 if i<10 else .8) for i in range(7000)]

    def test_refused_paths_cannot_dilute_conditional_calibration(self):
        refs=self.refs();cal=calibration(refs,100,'global',False)
        self.assertTrue(cal['supported']);self.assertLess(cal['level'],.004)
        raw=next(c for c in cal['candidates'] if c['level']==.0095)
        self.assertEqual(raw['offered'],1000);self.assertAlmostEqual(raw['conditional_survival'],.01,delta=1e-6)
        self.assertGreater(raw['smoothed_survival'],.0095)
        # It would incorrectly pass if ten wins were divided by all 7,000 paths.
        self.assertLess(10/7000,.0095)

    def test_calendar_recency_maturity_and_asset_isolation(self):
        refs=self.refs();refs.extend(dict(refs[i],start=10000+i,period='2026-08-01') for i in range(300))
        result=levels(refs,'2026-09-01','ETH');self.assertEqual(len(result['conditional_recent']['100']['global']['dates']),3)
        verify_levels(result,refs,'2026-09-01','ETH')
        for bad in (dict(refs[0],asset='HYPE'),dict(refs[0],period='2026-09-01')):
            with self.assertRaisesRegex(ValueError,'Future'):levels([bad],'2026-09-01','ETH')
        with self.assertRaisesRegex(ValueError,'duplicate'):levels(refs+[refs[0]],'2026-09-01','ETH')
        immature=dict(refs[0],start=999999,expiry=1798761600000,period='2026-08-01')
        a=levels(refs,'2026-09-01','ETH');b=levels(refs+[immature],'2026-09-01','ETH');self.assertEqual(a,b)

    def test_positive_native_quotes_flat_veto_and_outcome_invariance(self):
        r=matched('2026-09-01',12);p=packet();p['conditional_levels']={v:{str(m):{g:dict(supported=False) for g in ('global','weekday','weekend')} for m in (100,1000)} for v in VARIANTS};f=dict(p0=.00001,floor=.00001,mu=0.,sigma=.3);predictor=EmpiricalPredictor(p['empirical'])
        for v in VARIANTS:
            a=quote(r,1000,v,p,predictor,f);self.assertTrue(a['offered']);self.assertGreater(a['width_ppb'],0)
            b=quote(dict(r,move=99999999,valid=False),1000,v,p,predictor,f)
            self.assertEqual({k:x for k,x in a.items() if k not in ('shadow','survived')},{k:x for k,x in b.items() if k not in ('shadow','survived')})
            flat=deepcopy(r);flat['activity_features'].update(changes_30=0,idle_ms=30000)
            self.assertFalse(quote(flat,1000,v,p,predictor,f)['offered'])
        ref=reference(r,f);self.assertLessEqual(ref['admission'],ref['win_threshold'])

    def test_complete_export_replay_and_tamper_detection(self):
        earlier=[matched(d,i,i%7==0) for d in WARMUP_DATES for i in range(64)];dates=('2026-09-04','2026-09-05');oof=('2025-07-01','2025-08-01');rows=[matched(d,i,i%7==0) for d in dates for i in range(64)]
        with tempfile.TemporaryDirectory() as tmp,patch('research_active_tail.DATES',dates),patch('research_active_tail.OOF_DATES',oof),patch('builtins.print'):
            parent=Path(tmp)/'parent';parent.mkdir();out=Path(tmp)/'out';out.mkdir();p=parent_study('ETH',earlier,rows,parent)
            study_asset('ETH',earlier,rows,parent,out);a=study_asset('ETH',earlier,rows,parent,out,True);self.assertEqual(a['decisions'],256*4)
            path=out/'ETH/predictions.jsonl.gz';path.write_bytes(path.read_bytes()+b'tamper')
            with self.assertRaisesRegex(ValueError,'differs'):study_asset('ETH',earlier,rows,parent,out,True)


if __name__=='__main__':unittest.main()
