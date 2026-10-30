from copy import deepcopy
import unittest

from preentry_bursty import FEATURES,PRICING,GATES,fit,features,risk,reprice,admit
from test_bursty_pricing import references


def paths(count=90):
    values=references(count,move=50)
    for i,p in enumerate(values):
        p['row']['adaptive_features']['directional_strength']=(i%9)/3
        p['row']['activity_features'].update(changes_30=1+i%8,changes_60=4+i%13,
            idle_ms=1000*(i%20),largest_variance_share_300=.5+(i%5)/10)
        p['row']['move']=0 if i%7==0 else 20+i%80
    return values


def trained():
    values=[]
    for d in range(3):
        for p in paths():
            p['row'].update(period=str(d),start=p['row']['start']+d*10_000_000,expiry=p['row']['expiry']+d*10_000_000)
            values.append(p)
    return fit(values)


class PreentryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.model=trained()

    def test_feature_allowlist_ignores_current_outcome_and_fit_has_finite_outputs(self):
        p=paths(1)[0];r=deepcopy(p['row']);r.update(move=99999999,valid=False,entry=3)
        self.assertEqual(features(r),features(p['row']))
        self.assertEqual(risk(r,self.model),risk(p['row'],self.model))
        self.assertEqual(len(features(r)),len(FEATURES))
        self.assertTrue(0<risk(r,self.model)<1)

    def test_price_changes_only_bursty_and_preserves_every_shadow_eligibility(self):
        values=paths(30);before=deepcopy(values)
        for i,p in enumerate(values):p['row']['activity_state']=('active','sparse','frozen','bursty')[i%4]
        values[7].update(paused=True,survived=None)
        for method in PRICING:
            result=reprice(values,values,self.model,method)
            for p,b in zip(result,values):
                self.assertEqual(p['shadow_survived'] is None,b['shadow_survived'] is None)
                self.assertEqual(p['paused'],b['paused'])
                if b['row']['activity_state']!='bursty':self.assertEqual((p['width_ppm'],p['shadow_survived']),(b['width_ppm'],b['shadow_survived']))
                self.assertTrue(1<=p['width_ppm']<=50000)

    def test_current_and_future_labels_wait_for_maturity_in_online_pricing(self):
        values=paths(60);changed=deepcopy(values)
        for p in changed[30:]:p['row'].update(move=99999999,valid=False)
        for method in PRICING:
            a,b=reprice(values,values,self.model,method),reprice(changed,changed,self.model,method)
            self.assertEqual([p['width_ppm'] for p in a[:32]],[p['width_ppm'] for p in b[:32]])
            self.assertEqual([p['preentry_floor_risk'] for p in a],[p['preentry_floor_risk'] for p in b])
            for gate,_ in GATES:
                self.assertEqual([p['paused'] for p in admit(a,gate)],[p['paused'] for p in admit(b,gate)])

    def test_admission_needs_no_warmup_and_respects_strict_threshold_and_other_states(self):
        values=paths(4)
        for p,prob in zip(values,(.53,.53001,.9,.99)):p['preentry_floor_risk']=prob
        values[2]['row']['activity_state']='active'
        values[3].update(paused=True,survived=None)
        out=admit(values,'preentry_floor53')
        self.assertEqual([p['paused'] for p in out],[False,True,False,True])
        self.assertEqual([(p['width_ppm'],p['shadow_survived']) for p in out],[(p['width_ppm'],p['shadow_survived']) for p in values])

    def test_refused_paths_still_teach_online_price_and_periods_clear_state(self):
        values=paths(30);other=deepcopy(values)
        for p in other:p.update(paused=True,survived=None)
        a,b=(reprice(v,v,self.model,'conditional_residual') for v in (values,other))
        self.assertEqual([p['width_ppm'] for p in a],[p['width_ppm'] for p in b])
        self.assertGreater(a[-1]['residual_mass'],0)
        tail=deepcopy(values[15:])
        for p in tail:p['row']['period']='next'
        full=reprice(values[:15]+tail,values[:15]+tail,self.model,'conditional_residual')
        fresh=reprice(tail,tail,self.model,'conditional_residual')
        self.assertEqual([p['width_ppm'] for p in full[15:]],[p['width_ppm'] for p in fresh])
        with self.assertRaises(ValueError):reprice(list(reversed(values)),values,self.model,'conditional_residual')

    def test_slow_anchor_does_not_round_unchanged_quotes_up_by_one(self):
        values=paths(15)
        result=reprice(values,values,self.model,'slow_anchor')
        self.assertEqual([p['width_ppm'] for p in result],[p['width_ppm'] for p in values])


if __name__=='__main__':unittest.main()
