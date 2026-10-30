from copy import deepcopy
import unittest

from audit_payout_walkforward import same
from research_conditional_tail import summarize
from research_volatility_open_gate import manual_fit,replay
from research_trial_liquidity import WARMUP_DATES
from test_trial_payout import matched
from trial_payout import metrics
from volatility_open_gate import BASES,GATES,apply,fit,opens


class VolatilityGateTests(unittest.TestCase):
    def rows(self):
        rows=[matched(d,i,i%7==0) for d in WARMUP_DATES[:6] for i in range(128)]
        for i,r in enumerate(rows):r['adaptive_features'].update(vol_60_ppm=i%128,vol_300_ppm=2*(i%128))
        return rows

    def test_gate_thresholds_are_past_only_asset_specific_date_weighted(self):
        rows=self.rows();m=fit(rows,'ETH','2025-07-01');self.assertEqual(m['training_dates'],list(WARMUP_DATES[3:6]));same(m,manual_fit(rows,'ETH','2025-07-01'))
        later=[matched('2026-09-01',i,True) for i in range(300)];same(m,fit(rows+later,'ETH','2025-07-01'))
        with self.assertRaisesRegex(ValueError,'asset-specific'):fit(rows,'HYPE','2025-07-01')
        changed=deepcopy(rows)
        for r in changed:
            if r['period']<WARMUP_DATES[3]:r['adaptive_features']['vol_60_ppm']=9999999
        same(m,fit(changed,'ETH','2025-07-01'))

    def test_boundary_future_outcome_invariance_and_subset(self):
        model=fit(self.rows(),'ETH','2025-07-01');r=matched('2026-09-01',12);p=dict(width=5,offered=True,shadow=True,survived=True,reason='');threshold=model['thresholds']['fast50']
        r['adaptive_features']['vol_60_ppm']=threshold;self.assertTrue(opens(r,'fast50',model));self.assertIs(apply(r,p,'fast50',model),p)
        r['adaptive_features']['vol_60_ppm']=threshold-.001;q=apply(r,p,'fast50',model);self.assertFalse(q['offered']);self.assertEqual(q['width'],p['width'])
        changed=dict(r,move=99999999,valid=False);self.assertEqual(q,apply(changed,p,'fast50',model))
        refusal=dict(p,offered=False,reason='flat_oracle_veto');self.assertIs(apply(r,refusal,'fast50',model),refusal)
        self.assertIs(apply(r,p,'none',model),p)

    def test_complete_paired_replay_audit_and_none_reproduces_base(self):
        model=fit(self.rows(),'ETH','2025-07-01');rows=[matched('2026-09-04',i,i%7==0) for i in range(64)]
        for i,r in enumerate(rows):r['adaptive_features'].update(vol_60_ppm=i*2,vol_300_ppm=i*4)
        values=[dict(width=5.,offered=i%3!=0,shadow=i%7==0,survived=i%7==0 if i%3 else None,reason='' if i%3 else 'flat_oracle_veto') for i in range(64)]
        records={b:{m:values for m in (100,1000)} for b in BASES};models={'2026-09-04':model};result,n=replay(rows,records,models);audit,k=replay(rows,records,models,True);same(result,audit);self.assertEqual(n,k)
        for base in BASES:
            for m in (100,1000):
                part=result['trial'][str(m)][base];same(part['none']['matched']['overall'],metrics(rows,values,m))
                old=part['none']['matched']['overall']['pooled']
                for gate in GATES:self.assertLessEqual(part[gate]['matched']['overall']['pooled']['offered'],old['offered'])


if __name__=='__main__':unittest.main()
