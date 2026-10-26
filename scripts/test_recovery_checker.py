from copy import deepcopy
import unittest
from check_recovery import check, DAY

class RecoveryCheckerTests(unittest.TestCase):
    def fixture(self):
        config=dict(daily_loss=10,rolling_loss=20,rolling_ms=7*DAY,pause_drawdown=3,hard_drawdown=20,resume_drawdown=1,cooldown_ms=1000,probe_loss=1)
        terms=dict(id='q',payout=9,stake=5)
        stage=dict(id='s',terms=terms,status='active',start=1000,expiry=31000)
        finalstage=dict(stage,status='survived',resolved=31000)
        def event(n,kind,at,result,stages,**extra):
            return dict(sequence=n,previous_hash='' if n==1 else 'h'+str(n-1),hash='h'+str(n),command=dict(kind=kind,at=at,**extra),result=result,notices={'alice':{'stages':stages}})
        events=[event(1,'quote',1000,terms,[]),event(2,'enter',1000,stage,[stage],id='q'),event(3,'tick',31000,None,[finalstage])]
        final=dict(sequence=3,journal_hash='h3',stages={'s':finalstage},recovery=dict(mode='paused',reopen_at=32000,pnl=-4,peak=0,losses=[dict(at=31000,amount=4)]))
        return events,dict(recovery=config),final

    def test_reconstructs_loss_and_pause_without_reducer(self):
        result=check(*self.fixture())
        self.assertTrue(result['arithmetic_verified'])
        self.assertEqual(result['admissions_checked'],1)
        self.assertFalse(result['independent_production_controller'])

    def test_altered_snapshot_and_excess_admission_are_rejected(self):
        events,policy,final=self.fixture()
        changed=deepcopy(final);changed['recovery']['losses']=[]
        with self.assertRaisesRegex(ValueError,'recovery state'):check(events,policy,changed)
        policy['recovery']['daily_loss']=3
        with self.assertRaisesRegex(ValueError,'exceeds'):check(events,policy,final)

    def test_changed_accepted_terms_are_rejected(self):
        events,policy,final=self.fixture()
        events[-1]=deepcopy(events[-1]);events[-1]['notices']['alice']['stages'][0]['terms']['payout']=10
        with self.assertRaisesRegex(ValueError,'terms changed'):check(events,policy,final)
