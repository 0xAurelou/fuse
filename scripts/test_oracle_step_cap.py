from copy import deepcopy
import unittest

from audit_payout_walkforward import same
from joint_x1000 import quote
from oracle_step_cap import apply,step_features
from research_hype_step_cap import independent_cap,independent_steps
from test_trial_payout import matched


class OracleStepCapTests(unittest.TestCase):
    def observations(self):return [(i*1000,100000000+(i%2)*500) for i in range(800)]

    def test_step_is_strictly_pre_entry_and_matches_independent_slices(self):
        observed=self.observations();starts=list(range(0,800000,30000));markers=[dict(known_at=350000),dict(known_at=699500)];a=step_features(observed,markers,starts);same(a,independent_steps(observed,markers,starts));s=step_features(observed,[],[330000])[0];self.assertEqual(s['step_units'],500);self.assertTrue(s['supported'])
        changed=[(t,px if t<330000 else px+123) for t,px in observed];same(s,step_features(changed,[],[330000])[0])
        gap=[p for p in observed if not 350000<=p[0]<370000];same(step_features(gap,[],starts),independent_steps(gap,[],starts))

    def test_cap_preserves_admission_narrows_width_and_touch_loses(self):
        r=matched('2026-09-01',12);r['asset']='HYPE';r['entry']=84000000;p=dict(p0=.00001,mu=0.,scale=.25,bucket=0);base=quote(r,'joint_raw',dict(model={},levels={}),p);step=dict(step_units=500,supported=True)
        a=apply(r,base,step,p);same(a,independent_cap(r,base,step,p));self.assertTrue(a['offered']);self.assertLessEqual(a['barrier_delta_units'],500);self.assertGreater(a['barrier_delta_units'],0);self.assertLessEqual(a['model_survival'],base['model_survival']+1e-12)
        for move in (0,500):
            row=dict(r,move=move);b=quote(row,'joint_raw',dict(model={},levels={}),p);value=apply(row,b,step,p)
            self.assertEqual(value['offered'],b['offered']);self.assertEqual(value['survived'],move==0)
        unknown=dict(r,valid=False,move=None);b=quote(unknown,'joint_raw',dict(model={},levels={}),p);value=apply(unknown,b,step,p)
        self.assertEqual(a['width_ppb'],value['width_ppb']);self.assertIsNone(value['shadow'])
        refusal=dict(base,offered=False,survived=None,reason='risk');self.assertFalse(apply(r,refusal,step,p)['offered'])

    def test_equal_millisecond_receipts_keep_original_order(self):
        from oracle_step_cap_v2 import step_features as stable_steps
        observed=self.observations();observed=[p for p in observed if p[0]!=329000]
        # The larger price arrives first; sorting by price would fabricate steps.
        observed.extend([(329000,100000500),(329000,100000000)]);observed.sort(key=lambda p:p[0]);starts=[330000]
        same(stable_steps(observed,[],starts),independent_steps(observed,[],starts))
        self.assertNotEqual(step_features(observed,[],starts),stable_steps(observed,[],starts))

    def test_unsupported_or_unrepresentable_step_never_forces_width_or_refusal(self):
        r=matched('2026-09-01',12);p=dict(p0=.00001,mu=0.,scale=.25,bucket=0);base=quote(r,'joint_raw',dict(model={},levels={}),p)
        for step in (dict(step_units=None,supported=False),dict(step_units=1,supported=True)):
            v=apply(r,base,step,p);self.assertEqual(v['offered'],base['offered']);self.assertGreater(v['barrier_delta_units'],0);self.assertLessEqual(v['width_ppb'],base['width_ppb'])


if __name__=='__main__':unittest.main()
