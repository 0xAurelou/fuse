from copy import deepcopy
import unittest

from bursty_startup_admission import SPECS,admit,spec
from test_bursty_episodes import model
from test_bursty_pricing import references


class BurstyStartupAdmissionTests(unittest.TestCase):
    def test_warmup_learns_paused_references_only_when_mature(self):
        values=references(10,move=50);out=admit(values,spec('warm',warm=3),model())
        self.assertEqual([p['burst_admission_mature'] for p in out[:5]],[0,0,1,2,3])
        self.assertEqual([p['paused'] for p in out[:5]],[True,True,True,True,False])
        self.assertTrue(all(p['shadow_survived']==v['shadow_survived'] for p,v in zip(out,values)))
        values[0]['row']['valid']=False;values[0]['shadow_survived']=None
        out=admit(values,spec('warm',warm=3),model())
        self.assertTrue(out[4]['paused']);self.assertFalse(out[5]['paused'])

    def test_current_and_future_validity_movement_cannot_gate_earlier_quotes(self):
        values=references(60,move=0);changed=deepcopy(values)
        for p in changed[30:]:p['row'].update(valid=False,move=99999999)
        m=model()
        for rule in SPECS:
            a,b=admit(values,rule,m),admit(changed,rule,m)
            self.assertEqual([p['paused'] for p in a[:32]],[p['paused'] for p in b[:32]])
            self.assertEqual([p['burst_admission_episode'] for p in a],[p['burst_admission_episode'] for p in b])

    def test_non_bursty_prices_and_existing_refusals_never_change(self):
        values=references(25,move=50)
        for i,p in enumerate(values):p['row']['activity_state']=('bursty','active','frozen','sparse')[i%4]
        values[0].update(paused=True,survived=None,floor_reason='existing')
        before=deepcopy(values);m=model()
        for rule in SPECS:
            out=admit(values,rule,m)
            for p,b in zip(out,values):
                self.assertEqual((p['width_ppm'],p['shadow_survived']),(b['width_ppm'],b['shadow_survived']))
                if b['row']['activity_state']!='bursty':self.assertEqual(p['paused'],b['paused'])
                if b['paused']:self.assertTrue(p['paused'])
        self.assertEqual(values,before)

    def test_floor_guard_uses_minimum_width_not_candidate_survival(self):
        values=references(15,move=0)
        out=admit(values,spec('floor',floor=True),model())
        self.assertFalse(out[6]['paused']);self.assertTrue(out[7]['paused'])
        changed=deepcopy(values)
        for p in changed:p['shadow_survived']=False
        self.assertEqual([p['paused'] for p in out],[p['paused'] for p in admit(changed,spec('floor',floor=True),model())])
        for p in values:p['row']['move']=1000
        self.assertFalse(any(p['paused'] for p in admit(values,spec('floor',floor=True),model())))

    def test_episode_boundary_rearms_and_discards_old_pending_evidence(self):
        values=references(10,move=50)
        for p in values[5:]:p['row']['adaptive_features']['vol_300_ppm']*=3
        out=admit(values,spec('episode',warm=2,scope='episode'),model())
        self.assertEqual(out[5]['burst_admission_mature'],0)
        self.assertEqual(out[6]['burst_admission_mature'],0)
        self.assertTrue(out[7]['paused']);self.assertFalse(out[8]['paused'])

    def test_prior_shrinkage_and_hysteresis_are_distinct_controls(self):
        values=references(20,move=0);m=model()
        m['states']['bursty']['minimum_width_floor']=0
        simple=admit(values,spec('floor',floor=True),m)
        shrink=admit(values,spec('prior',floor=True,prior=12),m)
        self.assertTrue(simple[7]['paused']);self.assertFalse(shrink[7]['paused'])
        for p in values[6:]:p['row']['move']=1000
        rule=spec('hysteresis',floor=True,resume=.43);rule['memory']=6
        out=admit(values,rule,m)
        self.assertTrue(any(p['paused'] and .43<p['burst_admission_floor']<=.53 for p in out))
        self.assertFalse(out[-1]['paused'])

    def test_context_cannot_borrow_from_another_pre_entry_context(self):
        values=references(8,move=50)
        for p in values[5:]:p['row']['activity_features']['idle_ms']=6000
        out=admit(values,spec('context',warm=2,scope='context'),model())
        self.assertEqual(out[5]['burst_admission_mature'],0)
        self.assertTrue(out[-1]['paused'])

    def test_expired_history_and_new_period_rearm_startup(self):
        values=references(10,move=50)
        for p in values[8:]:
            p['row']['start']+=4_000_000;p['row']['expiry']+=4_000_000
        values[-1]['row']['period']='next'
        out=admit(values,spec('warm',warm=2),model())
        self.assertTrue(out[-2]['paused']);self.assertTrue(out[-1]['paused'])
        self.assertEqual(out[-2]['burst_admission_mature'],0)
        with self.assertRaises(ValueError):admit(list(reversed(values)),spec('warm',warm=2),model())

    def test_continuous_run_does_not_reset_at_scoring_interval_boundary(self):
        values=references(30,move=50);m=model();rule=spec('warm',warm=6)
        full=admit(values,rule,m);restart=admit(values[15:],rule,m)
        self.assertFalse(full[15]['paused']);self.assertTrue(restart[0]['paused'])


if __name__=='__main__':unittest.main()
