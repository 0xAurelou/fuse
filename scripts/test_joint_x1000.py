from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from audit_payout_walkforward import same
from joint_x1000 import TARGET,VARIANTS,budget,cdf,fit,forecast,guard,levels,quote,reference,vector
from research_joint_x1000 import independent_quote,study_asset,verify_levels
from research_trial_liquidity import WARMUP_DATES
from test_trial_payout import matched


class JointX1000Tests(unittest.TestCase):
    def packet(self):
        return dict(model={},levels={g:dict(supported=False) for g in ('global','weekday','weekend') for _ in (0,) }|{g+':risk'+str(b):dict(supported=False) for g in ('global','weekday','weekend') for b in range(4)})

    def refs(self):
        refs=[]
        for b in (0,3):
            for i in range(3000):
                refs.append(dict(asset='ETH',period=WARMUP_DATES[i%3],start=b*10000+i,expiry=b*10000+i+30000,weekend=False,bucket=b,p0=.00001 if b==0 else .0001,admission=.00002 if b==0 else .0002,win_threshold=.0002 if b==3 and i%150==0 else .8))
        return refs

    def test_joint_budgets_use_conditional_risk_instead_of_blanket_closing(self):
        refs=self.refs();cal=levels(refs,'ETH','2026-09-01');verify_levels(cal,refs,'ETH','2026-09-01')
        r=matched('2026-09-01',12);packet=dict(levels=cal);p=dict(p0=.00001,mu=0.,scale=.25,bucket=0)
        local,source=budget(r,p,packet,'joint_local');global_,_=budget(r,p,packet,'joint_global')
        self.assertEqual(source,'weekday:risk0');self.assertGreater(local,global_)
        self.assertTrue(cal[source]['supported']);self.assertGreaterEqual(cal[source]['selected']['offered'],200)
        self.assertLessEqual(cal[source]['selected']['smoothed_survival'],TARGET)

    def test_native_quotes_barrier_touch_and_future_outcome_invariance(self):
        r=matched('2026-09-01',12);packet=self.packet();p=dict(p0=.00001,mu=0.,scale=.25,bucket=0)
        for v in VARIANTS:
            a=quote(r,v,packet,p);self.assertTrue(a['offered']);self.assertGreater(a['barrier_delta_units'],0);self.assertNotEqual(a['width_ppb']%1000,0);self.assertLessEqual(a['model_survival'],TARGET+1e-10)
            d=a['barrier_delta_units'];inside=quote(dict(r,move=d-1),v,packet,p);touch=quote(dict(r,move=d),v,packet,p);unknown=quote(dict(r,move=999999999,valid=False),v,packet,p)
            self.assertTrue(inside['survived']);self.assertFalse(touch['survived']);self.assertIsNone(unknown['shadow'])
            self.assertEqual({k:x for k,x in a.items() if k not in ('shadow','survived')},{k:x for k,x in unknown.items() if k not in ('shadow','survived')})
            same(a,independent_quote(r,v,packet,p))

    def test_flat_stale_missing_and_unrepresentable_risk_never_force_quotes(self):
        r=matched('2026-09-01',12);packet=self.packet();p=dict(p0=.00001,mu=0.,scale=.25,bucket=0)
        flat=deepcopy(r);flat['activity_features'].update(changes_30=0,idle_ms=30000)
        stale=deepcopy(r);stale['liquidity']['received_at_ms']=r['start']-5001
        equal=deepcopy(r);equal['liquidity']['received_at_ms']=r['start']
        for bad in (flat,stale,equal,dict(r,liquidity=None),dict(r,adaptive_features=None)):
            for v in VARIANTS:self.assertFalse(quote(bad,v,packet,p)['offered'])
        for f in (dict(p,p0=.001),dict(p,mu=-30,scale=.08)):
            self.assertFalse(quote(r,'joint_raw',packet,f)['offered'])
        self.assertFalse(quote(r,'joint_raw',packet,p)['empirical_rare_tail_evidence'])

    def test_joint_features_are_allowlisted_and_include_all_three_signal_families(self):
        r=matched('2026-09-01',12);v=vector(r);changed=dict(r,move=99999999,valid=False);self.assertEqual(v,vector(changed))
        for field in ('volatility','activity','liquidity'):
            changed=deepcopy(r)
            if field=='volatility':changed['adaptive_features']['vol_60_ppm']*=2
            elif field=='activity':changed['activity_features']['changes_30']+=5
            else:changed['liquidity']['spread_bps']*=2;changed['liquidity']['values'][0]*=2
            self.assertNotEqual(v,vector(changed))

    def test_fit_is_asset_specific_past_only_and_uses_last_ten_dates(self):
        rows=[matched(d,i,i%7==0) for d in WARMUP_DATES for i in range(64)];a=fit(rows,'ETH','2026-09-01');self.assertEqual(a['training_dates'],list(WARMUP_DATES[-10:]));changed=deepcopy(rows)
        for r in changed:
            if r['period']<WARMUP_DATES[-10]:r['move']=9999999
        same(a,fit(changed,'ETH','2026-09-01'))
        later=[matched('2026-09-01',i,True) for i in range(64)];same(a,fit(rows+later,'ETH','2026-09-01'))
        with self.assertRaisesRegex(ValueError,'asset-specific'):fit(rows,'HYPE','2026-09-01')
        model=fit(rows,'ETH','2025-07-01');p=forecast(matched('2026-09-01',12),model);self.assertTrue(0<p['p0']<1)

    def test_reference_identity_maturity_and_native_quantization(self):
        refs=self.refs();a=levels(refs,'ETH','2026-09-01')
        with self.assertRaisesRegex(ValueError,'duplicate'):levels(refs+[refs[0]],'ETH','2026-09-01')
        with self.assertRaisesRegex(ValueError,'Future'):levels([dict(refs[0],period='2026-09-01')],'ETH','2026-09-01')
        with self.assertRaisesRegex(ValueError,'cross-asset'):levels([dict(refs[0],asset='HYPE')],'ETH','2026-09-01')
        immature=dict(refs[0],start=9999999,expiry=9999999999999);self.assertEqual(a,levels(refs+[immature],'ETH','2026-09-01'))
        r=matched('2026-09-01',12);p=dict(p0=.00001,mu=0.,scale=.25,bucket=0);ref=reference(r,p);self.assertLessEqual(ref['admission'],ref['win_threshold']);self.assertEqual(ref['bucket'],0)

    def test_full_fit_calibration_export_independent_replay_and_tamper(self):
        earlier=[matched(d,i,i%7==0) for d in WARMUP_DATES for i in range(64)];dates=('2026-09-04','2026-09-05');oof=('2025-07-01','2025-08-01');rows=[matched(d,i,i%7==0) for d in dates for i in range(64)]
        with tempfile.TemporaryDirectory() as tmp,patch('research_joint_x1000.DATES',dates),patch('research_joint_x1000.OOF_DATES',oof),patch('research_active_tail.OOF_DATES',oof),patch('builtins.print'):
            root=Path(tmp);r=study_asset('ETH',earlier,rows,root);self.assertEqual(r['decisions'],256*len(VARIANTS));same(r,study_asset('ETH',earlier,rows,root,True))
            path=root/'ETH/predictions.jsonl.gz';path.write_bytes(path.read_bytes()+b'tamper')
            with self.assertRaisesRegex(ValueError,'differs'):study_asset('ETH',earlier,rows,root,True)


if __name__=='__main__':unittest.main()
