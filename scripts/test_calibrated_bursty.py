from copy import deepcopy
import unittest
import numpy as np

from calibrated_bursty import (fit_floor,fit_calibration,fit,series,all_series,admit,PRICING,GATES,effective_mass)
from preentry_bursty import fit as oldfit
from test_preentry_bursty import paths


def training(days=4):
    values=[]
    for d in range(days):
        for p in paths(90):
            p['row'].update(period=str(d),start=d*10_000_000+p['row']['start'],expiry=d*10_000_000+p['row']['expiry'])
            values.append(p)
    return values


class CalibrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        values=training();cls.static=oldfit(values);cls.model=fit(values,values,cls.static)

    def test_binary_fit_matches_pinned_fit_and_does_not_read_quoted_width(self):
        values=training();a=fit_floor(values);b=oldfit(values)
        for k in ('center','sd','floor_coefficients'):self.assertTrue(np.allclose(a[k],b[k]))
        changed=deepcopy(values)
        for p in changed:p['width_ppm']*=3
        self.assertEqual(a,fit_floor(changed))

    def test_chronological_calibration_never_fits_a_scoring_day(self):
        values=training();a=fit_calibration(values)
        self.assertTrue(all(max(f['training_periods'])<f['scoring_period'] for f in a['folds']))
        changed=deepcopy(values)
        for p in changed:
            if p['row']['period']>='2':p['row']['move']=0
        b=fit_calibration(changed)
        self.assertEqual(a['folds'][0]['predicted_sum'],b['folds'][0]['predicted_sum'])
        self.assertNotEqual(a['folds'][0]['floor_count'],b['folds'][0]['floor_count'])
        early=fit_calibration([p for p in values if p['row']['period']<'2'])
        self.assertTrue(early['identity_fallback']);self.assertEqual(early['bursty']['coefficients'],[0,1])

    def test_effective_count_cannot_transfer_arbitrarily_tiny_similarity_mass(self):
        self.assertEqual(effective_mass(.001,100,6),0)
        self.assertEqual(effective_mass(2,5.99,6),0)
        self.assertEqual(effective_mass(2,10,6),10)
        self.assertEqual(effective_mass(2,100,6),24)

    def test_shared_replay_is_identical_to_independent_method_replays(self):
        v=paths(20);batch=all_series(v,v,self.model)
        for method in PRICING:self.assertEqual(batch[method],series(v,v,self.model,method))

    def test_oof_scoring_cannot_use_an_unmatured_earlier_label(self):
        v=training(3);v[0]['row']['expiry']=20_000_000
        with self.assertRaises(ValueError):fit_calibration(v)

    def test_labels_wait_until_maturity_for_risk_and_prices(self):
        v=paths(50);changed=deepcopy(v)
        for p in changed[25:]:p['row'].update(move=999999999,valid=False)
        for method in PRICING:
            a,b=series(v,v,self.model,method),series(changed,changed,self.model,method)
            self.assertEqual([p['width_ppm'] for p in a[:27]],[p['width_ppm'] for p in b[:27]])
            self.assertEqual([p['risk_context'] for p in a[:27]],[p['risk_context'] for p in b[:27]])
            for gate in GATES:self.assertEqual([p['paused'] for p in admit(a,gate)[:27]],[p['paused'] for p in admit(b,gate)[:27]])

    def test_refused_references_teach_both_adapters_and_period_resets(self):
        v=paths(35);changed=deepcopy(v)
        for p in changed:p.update(paused=True,survived=None)
        a,b=series(v,v,self.model,'ess6_residual'),series(changed,changed,self.model,'ess6_residual')
        self.assertEqual([p['width_ppm'] for p in a],[p['width_ppm'] for p in b])
        self.assertEqual([p['risk_context'] for p in a],[p['risk_context'] for p in b])
        tail=deepcopy(v[15:])
        for p in tail:p['row']['period']='next'
        full=series(v[:15]+tail,v[:15]+tail,self.model,'ess6_residual')
        fresh=series(tail,tail,self.model,'ess6_residual')
        self.assertEqual(full[15:],fresh)
        with self.assertRaises(ValueError):series(list(reversed(v)),v,self.model,'ess6_residual')

    def test_other_states_and_all_widths_remain_fixed_under_admission(self):
        v=paths(20)
        for i,p in enumerate(v):p['row']['activity_state']=('active','sparse','frozen','bursty')[i%4]
        for method in PRICING:
            priced=series(v,v,self.model,method)
            for gate in GATES:
                gated=admit(priced,gate)
                self.assertEqual([(p['width_ppm'],p['shadow_survived']) for p in gated],[(p['width_ppm'],p['shadow_survived']) for p in priced])
                for p,base in zip(gated,v):
                    if base['row']['activity_state']!='bursty':self.assertEqual((p['width_ppm'],p['paused']),(base['width_ppm'],base['paused']))
                    self.assertTrue(1<=p['width_ppm']<=50000)


if __name__=='__main__':unittest.main()
