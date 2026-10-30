from copy import deepcopy
import gzip
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from historical_liquidity import snapshot,predict
from payout_empirical import EmpiricalPredictor
from research_trial_liquidity import DATES,WARMUP_DATES,fitted,training
from research_trial_payout import study_asset,audit_asset
from test_liquidity_capture import book
from test_payout_risk import row
from trial_payout import (RISKS,VARIANTS,brownian_width,forecasts,origin_packet,quote,
                         shipped_width,summary)


def matched(day,i,flat=False):
    r=row(day,i,flat);r['liquidity']=snapshot((r['start']-400,book(at=r['start']-500)),r['start'])[0];return r


class TrialPayoutTests(unittest.TestCase):
    def test_exact_integer_formula_matches_all_native_reference_vectors(self):
        vectors=json.loads((Path(__file__).resolve().parents[1]/'engine/testdata/brownian-pricing-vectors.json').read_text())
        self.assertEqual(len(vectors),90)
        for v in vectors:self.assertEqual(brownian_width(v['volatility_30s_ppm'],v['multiplier'],v['house_edge_bps']),v['width_ppb'])
        self.assertGreater(shipped_width('HYPE',100),shipped_width('ETH',100))
        self.assertGreater(shipped_width('ETH',100),shipped_width('ETH',1000))

    def test_native_touch_loses_and_admission_ignores_future_outcome(self):
        r=matched(DATES[0],12);forecast=dict(p0=None,floor=None,calibrated0=False,calibrated_floor=False)
        width=shipped_width('ETH',100);delta=r['entry']*width//10**9
        a=quote(dict(r,move=delta-1),forecast,100,'shipped_formula',None)
        b=quote(dict(r,move=delta),forecast,100,'shipped_formula',None)
        c=quote(dict(r,move=999999999,valid=False),forecast,100,'shipped_formula',None)
        self.assertTrue(a['survived']);self.assertFalse(b['survived']);self.assertIsNone(c['shadow'])
        self.assertEqual({k:v for k,v in a.items() if k not in ('shadow','survived')},{k:v for k,v in c.items() if k not in ('shadow','survived')})

    def test_empirical_x1000_quotes_require_real_positive_tail_support(self):
        r=matched(DATES[0],12);cdf=dict(n=50000,dates=['2025-01-01','2025-02-01','2025-03-01'],value=[.1,1.],weight=[.001,.999])
        movement=dict(anchors={'slow':dict(global_distribution=cdf,families={'activity':{}})})
        predictor=EmpiricalPredictor(movement);forecast=dict(p0=.0001,floor=.0001,calibrated0=False,calibrated_floor=False)
        a=quote(r,forecast,1000,'calendar_raw_cdf',predictor)
        self.assertTrue(a['offered']);self.assertGreaterEqual(a['tail_mass'],20)
        cdf=dict(cdf,n=100);movement['anchors']['slow']['global_distribution']=cdf
        b=quote(r,forecast,1000,'calendar_raw_cdf',EmpiricalPredictor(movement))
        self.assertFalse(b['offered']);self.assertIn('insufficient_positive_tail_support',b['reason'])

    def test_missing_book_is_refusal_in_common_denominator_and_empty_is_unknown(self):
        rows=[matched(DATES[0],12),matched(DATES[0],13)];rows[1]['liquidity']=None
        yes=dict(width=1,offered=True,shadow=False,reason='');no=dict(width=None,offered=False,shadow=None,reason='missing_liquidity')
        s=summary(rows,[yes,no],1000)
        self.assertEqual(s['eligible'],2);self.assertEqual(s['availability'],.5);self.assertEqual(s['refusals'],{'missing_liquidity':1})
        empty=summary(rows,[no,no],1000);self.assertIsNone(empty['survival']);self.assertIsNone(empty['gross_lp_per_stake'])
        # Two one-unit stakes, one winner: total payout includes returned stake.
        winner=dict(yes,shadow=True)
        self.assertEqual(summary(rows,[yes,winner],100)['gross_lp_stake_units'],-98)
        self.assertEqual(summary(rows,[yes,winner],100)['gross_lp_per_stake'],-49)
        self.assertEqual(summary(rows,[yes,winner],1000)['gross_lp_stake_units'],-998)

    def test_daily_models_calibration_maturity_and_full_payout_replay_audit(self):
        earlier=[matched(d,i,i%7==0) for d in WARMUP_DATES for i in range(12)]
        rows=[matched(d,i,i%7==0) for d in DATES for i in list(range(12))+[2878,2879]];pool=earlier+rows
        refs={f:[] for f in RISKS}
        def risk_at(root,asset,day):
            train=training(pool,asset,day)
            return dict(asset=asset,cutoff=day,models={f:fitted(train,asset,day,f) for f in RISKS}),dict(path='test',sha256='test')
        first,binding=risk_at(None,'ETH',DATES[0]);packet=origin_packet(pool,'ETH',DATES[0],first,refs,binding)
        changed=deepcopy(pool)
        for r in changed:
            if r['period']>=DATES[0]:r['move']=9999999
        self.assertEqual(packet,origin_packet(changed,'ETH',DATES[0],first,refs,binding))
        wrong={f:[dict(asset='ETH',start=rows[0]['start'],expiry=rows[0]['expiry'],period=DATES[0])] for f in RISKS}
        with self.assertRaisesRegex(ValueError,'future contamination'):origin_packet(pool,'ETH',DATES[0],first,wrong,binding)
        with tempfile.TemporaryDirectory() as tmp,patch('research_trial_payout.monthly_references',side_effect=lambda *a,**k:{f:[] for f in RISKS}),patch('research_trial_payout.risk_origin',side_effect=risk_at),patch('builtins.print'):
            root=Path(tmp);result=study_asset('ETH',earlier,rows,root,root,root)
            self.assertEqual(result['matched_clean_paths'],140)
            with gzip.open(root/'ETH/origins'/('2026-09-02.json.gz'),'rt') as stream:second=json.load(stream)
            self.assertEqual(second['calibration_counts']['calendar'],12)
            report=audit_asset('ETH',earlier,rows,root,root,root/'ETH')
            self.assertEqual(report['decisions_replayed'],140*2*len(VARIANTS))
            path=root/'ETH/predictions.jsonl.gz';path.write_bytes(path.read_bytes()+b'changed')
            with self.assertRaisesRegex(ValueError,'binding'):audit_asset('ETH',earlier,rows,root,root,root/'ETH')


if __name__=='__main__':unittest.main()
