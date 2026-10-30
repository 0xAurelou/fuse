from copy import deepcopy
import gzip
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from flat_aware_payout import (VARIANTS,activity_key,build_predictors,cell,fit_floor,
    floor_forecast,quote,veto)
from research_flat_aware_payout import study_asset,audit_asset
from research_trial_liquidity import WARMUP_DATES,training,fitted
from test_trial_payout import matched


class FlatAwareTests(unittest.TestCase):
    def test_already_flat_oracle_is_refused_despite_tiny_old_forecast(self):
        r=matched('2026-09-01',12,True);r['activity_features'].update(idle_ms=90000,changes_30=0)
        cdf=dict(n=50000,dates=['2025-01-01','2025-02-01','2025-03-01'],value=[.1,1],weight=[.001,.999])
        movement=dict(anchors={'slow':dict(global_distribution=cdf,families={'activity':{}})})
        packet=dict(movement={m:movement for m in ('previous','activity','calendar')})
        forecast=dict(p0=.0002,floor=.0002,calibrated0=False,calibrated_floor=False)
        predictors=build_predictors(packet)
        old=quote(r,1000,'previous_formula',packet,predictors,forecast)
        new=quote(r,1000,'flat_veto',packet,predictors,forecast)
        self.assertTrue(old['offered']);self.assertTrue(old['survived'])
        self.assertFalse(new['offered']);self.assertIsNone(new['survived']);self.assertEqual(new['flat_guard'],'flat_oracle_veto')
        changed=quote(dict(r,move=999999,valid=False),1000,'flat_veto',packet,predictors,forecast)
        self.assertEqual({k:v for k,v in new.items() if k not in ('shadow','survived')},{k:v for k,v in changed.items() if k not in ('shadow','survived')})

    def test_veto_and_recovery_exact_boundaries(self):
        r=matched('2026-09-01',12);a=r['activity_features'];a.update(idle_ms=2999,changes_30=4)
        self.assertIsNone(veto(r,1000,True));a['idle_ms']=3000
        self.assertEqual(veto(r,1000,True),'insufficient_recent_oracle_activity');self.assertIsNone(veto(r,100,True))
        a.update(idle_ms=500,changes_30=3);self.assertIsNotNone(veto(r,1000,True))
        a['changes_30']=0;self.assertEqual(veto(r,100,False),'flat_oracle_veto')
        a.update(changes_30=4,idle_ms=30000);self.assertEqual(veto(r,100,False),'flat_oracle_veto')
        a.update(idle_ms=500,idle_is_lower_bound=True);self.assertEqual(veto(r,100,False),'flat_oracle_veto')

    def test_hierarchy_is_asset_specific_past_only_and_date_balanced(self):
        rows=[matched(d,i,i%7==0) for d in WARMUP_DATES for i in range(24)]
        a=fit_floor(rows,'ETH','2025-07-01');changed=deepcopy(rows)
        for r in changed:
            if r['period']>='2025-07-01':r['move']=999999
        self.assertEqual(a,fit_floor(changed,'ETH','2025-07-01'))
        with self.assertRaisesRegex(ValueError,'asset-specific'):fit_floor(rows,'HYPE','2025-07-01')
        flat=matched('2025-01-01',1,True);active=matched('2025-02-01',1,False)
        self.assertAlmostEqual(cell([flat]*9+[active])['rates']['p0'],.5)
        model=fit_floor(rows,'ETH','2026-09-01')
        for r in rows:
            for cal in (False,True):
                p=floor_forecast(r,model,cal);self.assertTrue(0<p['p0']<=p['floor']<1)
        self.assertGreater(floor_forecast(rows[0],model)['p0'],floor_forecast(rows[1],model)['p0'])

    def test_midnight_labels_are_withheld_from_next_fit(self):
        rows=[matched(d,i,i%7==0) for d in WARMUP_DATES for i in range(12)]
        rows += [matched('2026-09-01',i,i%7==0) for i in (12,2877,2878,2879)]
        model=fit_floor(rows,'ETH','2026-09-02')
        self.assertEqual(model['rows'],20*12+2)

    def test_complete_fit_export_independent_replay_and_tamper_rejection(self):
        earlier=[matched(d,i,i%7==0) for d in WARMUP_DATES for i in range(24)]
        dates=('2026-09-04','2026-09-05');oof=('2025-07-01','2025-08-01')
        rows=[matched(d,i,i%7==0) for d in dates for i in range(24)];pool=earlier+rows
        def risk_at(asset,day,*args):
            train=training(pool,asset,day)
            return dict(models={'calendar_liquidity':fitted(train,asset,day,'calendar_liquidity')}),dict(path='test',sha256='test')
        with tempfile.TemporaryDirectory() as tmp,patch('research_flat_aware_payout.prior_risk',side_effect=risk_at),patch('research_flat_aware_payout.DATES',dates),patch('research_flat_aware_payout.OOF_DATES',oof),patch('builtins.print'):
            root=Path(tmp);r=study_asset('ETH',earlier,rows,root,root,root)
            self.assertEqual(len(r['origins']),4)
            p=r['results']['trial']['100']['variants']['calendar_hurdle']['matched']
            self.assertEqual(p['weekday']['pooled']['eligible'],24);self.assertEqual(p['weekend']['pooled']['eligible'],24)
            audit=audit_asset('ETH',earlier,rows,root,root,root/'ETH')
            self.assertEqual(audit['decisions_independently_replayed'],96*2*len(VARIANTS))
            file=root/'ETH/predictions.jsonl.gz';file.write_bytes(file.read_bytes()+b'tamper')
            with self.assertRaisesRegex(ValueError,'binding'):audit_asset('ETH',earlier,rows,root,root,root/'ETH')


if __name__=='__main__':unittest.main()
