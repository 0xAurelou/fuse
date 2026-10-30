from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from audit_payout_walkforward import same
from online_joint_x1000 import VARIANTS,Feedback,quote,reference
from research_joint_x1000 import study_asset as parent_study
from research_online_joint_x1000 import manual_state,manual_quote,study_asset
from research_trial_liquidity import WARMUP_DATES
from test_trial_payout import matched


class OnlineJointTests(unittest.TestCase):
    def ref(self,i,valid=True,zero=False):return dict(asset='ETH',start=i*30000,expiry=i*30000+30000,valid=valid,zero=zero,p0=.02,positive_score=None if zero or not valid else .5)

    def test_strict_maturity_invalid_paths_refused_references_and_gap_expiry(self):
        state=Feedback('ETH');state.advance(0);r=self.ref(0);state.push(r)
        self.assertEqual(state.advance(60000)['references'],0)
        self.assertEqual(state.advance(60001)['references'],1)
        bad=dict(self.ref(3,False),start=90000);state.advance(90000);state.push(bad)
        self.assertEqual(state.advance(150001)['references'],1)
        self.assertEqual(state.advance(21600000+30001)['references'],0)
        with self.assertRaisesRegex(ValueError,'chronological'):state.advance(21600000+30001)
        with self.assertRaisesRegex(ValueError,'identity'):state.push(dict(self.ref(4),asset='HYPE'))

    def test_forward_feedback_matches_independent_offline_slices(self):
        state=Feedback('ETH');all_refs=[self.ref(i,valid=i%13!=0,zero=i%29==0) for i in range(600)];valid=[r for r in all_refs if r['valid']];expiry=[r['expiry'] for r in valid];maturity=[t+30000 for t in expiry]
        for r in all_refs:
            at=r['start'];same(state.advance(at),manual_state(valid,expiry,maturity,at));state.push(r)
        value=state.advance(600*30000+60001);self.assertEqual(value['references'],480);self.assertGreaterEqual(value['flat_factor'],.1);self.assertLessEqual(value['tail_factor'],4.)

    def test_current_and_future_labels_cannot_change_present_state_or_admission(self):
        p=dict(p0=.00001,mu=0.,scale=.25,bucket=0);packet=dict(model={},levels={});r=matched('2026-09-01',12);state=dict(references=480,positive_references=475,flat_factor=.5,tail_factor=2.)
        for v in VARIANTS:
            a=quote(r,v,packet,p,state);same(a,manual_quote(r,v,packet,p,state))
            b=quote(dict(r,move=None,valid=False),v,packet,p,state)
            self.assertEqual({k:x for k,x in a.items() if k not in ('shadow','survived')},{k:x for k,x in b.items() if k not in ('shadow','survived')})
        self.assertIsNone(reference(dict(r,move=None,valid=False),p)['positive_score'])
        changed=dict(state,tail_factor=4.);narrow=quote(r,'joint_online_full',packet,p,changed);wide=quote(r,'joint_online_full',packet,p,dict(state,tail_factor=.25));self.assertLess(narrow['width_ppb'],wide['width_ppb'])

    def test_full_parent_static_reproduction_export_audit_and_tamper(self):
        earlier=[matched(d,i,i%7==0) for d in WARMUP_DATES for i in range(64)];dates=('2026-09-04','2026-09-05');oof=('2025-07-01','2025-08-01');rows=[matched(d,i,i%7==0) for d in dates for i in range(64)]
        with tempfile.TemporaryDirectory() as tmp,patch('research_joint_x1000.DATES',dates),patch('research_joint_x1000.OOF_DATES',oof),patch('research_active_tail.OOF_DATES',oof),patch('builtins.print'):
            parent=Path(tmp)/'parent';parent.mkdir();out=Path(tmp)/'out';out.mkdir();meta=parent_study('ETH',earlier,rows,parent)
            from research_payout_risk import dump,digest
            dump(parent/'research.json',dict(research_sha256={'ETH':digest(parent/'ETH/research.json')}))
            r=study_asset('ETH',earlier,rows,parent,out);self.assertEqual(r['decisions'],256*len(VARIANTS));same(r,study_asset('ETH',earlier,rows,parent,out,True))
            path=out/'ETH/predictions.jsonl.gz';path.write_bytes(path.read_bytes()+b'tamper')
            with self.assertRaisesRegex(ValueError,'differs'):study_asset('ETH',earlier,rows,parent,out,True)


if __name__=='__main__':unittest.main()
