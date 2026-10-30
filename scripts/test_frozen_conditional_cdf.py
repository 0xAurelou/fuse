from copy import deepcopy
import math
import unittest

from frozen_conditional_cdf import fit, fit_prefix, forecast, series, LEVELS
from temporal_oracle_data import origin


def rows(count=480,day='2026-01-01'):
    start=origin(day);out=[]
    for i in range(count):
        risky=i%2==0
        floor=i%10<8 if risky else i%10==9
        required=1 if floor else 10+(i*37)%250
        activity=dict(idle_ms=240000 if risky else 40000,changes_30=0,changes_60=0 if risky else 2,
            changes_300=1 if risky else 15,empty_bins_300=.9 if risky else .3,
            largest_variance_share_300=.9 if risky else .2,idle_is_lower_bound=False)
        adaptive=dict(vol_60_ppm=1 if risky else 10,vol_300_ppm=20,net_300_bps=0,
                      directional_strength=.1)
        out.append(dict(period=day,start=start+i*30000,expiry=start+(i+1)*30000,entry=1000000,
            move=required-1,valid=True,activity_state='frozen',activity_features=activity,adaptive_features=adaptive))
    return out


def values(data):
    return [dict(row=r,width_ppm=100,shadow_survived=r['move']<100,survived=r['move']<100,
                 paused=False,floor_reason='',capped=False) for r in data]


class FrozenConditionalCDFTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data=rows();cls.model=fit(cls.data,'path')

    def test_context_separates_different_minimum_width_probabilities(self):
        high=forecast(self.data[0],self.model)[1];low=forecast(self.data[1],self.model)[1]
        self.assertGreater(high,.53)
        self.assertLess(low,.3)
        self.assertEqual(self.model['windows'],480)

    def test_positive_quantiles_are_monotone_even_with_crossing_fits(self):
        model=deepcopy(self.model)
        model['floor_coefficients']=[-30]+[0]*len(model['center'])
        model['positive_coefficients']=list(reversed(model['positive_coefficients']))
        widths=[forecast(self.data[1],model,level=q)[0] for q in (.05,.2,.48,.7,.95)]
        self.assertEqual(widths,sorted(widths))
        self.assertTrue(all(2<=w<=50000 for w in widths))

    def test_floor_and_upper_bound_use_exact_declared_widths(self):
        model=deepcopy(self.model)
        model['floor_coefficients']=[30]+[0]*len(model['center'])
        self.assertEqual(forecast(self.data[1],model)[0],1)
        model['floor_coefficients'][0]=-30
        model['positive_coefficients']=[[100]+[0]*len(model['center']) for _ in LEVELS]
        width,_,capped,_=forecast(self.data[1],model)
        self.assertEqual(width,50000);self.assertTrue(capped)

    def test_future_outcomes_change_no_forecast_before_label_maturity(self):
        ref=values(self.data[:80]);actual=series(ref,self.model,True,.53)
        changed=[dict(p,row=dict(p['row'],move=999999,valid=False)) if i>=30 else p for i,p in enumerate(ref)]
        other=series(changed,self.model,True,.53)
        fields=lambda part:[(p['width_ppm'],p['paused'],p['frozen_floor']) for p in part[:32]]
        self.assertEqual(fields(actual),fields(other))
        self.assertEqual(forecast(self.data[1],self.model),forecast(dict(self.data[1],move=999999,valid=False),self.model))

    def test_refusals_do_not_select_learning_and_other_states_do_not_learn(self):
        ref=values(self.data[:80])
        open_=series(ref,self.model,True,None);gated=series(ref,self.model,True,.53)
        fields=lambda part:[(p['width_ppm'],p['frozen_floor'],p['frozen_level']) for p in part]
        self.assertEqual(fields(open_),fields(gated))
        self.assertTrue(any(p['paused'] for p in gated))
        mixed=[dict(p,row=dict(p['row'],activity_state='active')) if i%3==0 else p for i,p in enumerate(ref)]
        changed=[dict(p,row=dict(p['row'],move=999999)) if p['row']['activity_state']=='active' else p for p in mixed]
        first=series(mixed,self.model,True,None);second=series(changed,self.model,True,None)
        self.assertEqual([(p['width_ppm'],p.get('frozen_floor')) for p in first],
                         [(p['width_ppm'],p.get('frozen_floor')) for p in second])

    def test_private_restart_and_stale_feedback_reset(self):
        ref=values(self.data[:80]);restart=ref[:40]+[dict(p,row=dict(p['row'],period='restart')) for p in ref[40:]]
        out=series(restart,self.model,True,None)
        self.assertEqual(out[40]['frozen_logit_delta'],0.)
        self.assertEqual(out[40]['frozen_level'],.48)
        gap=5*3600000
        stale=ref[:40]+[dict(p,row=dict(p['row'],start=p['row']['start']+gap,expiry=p['row']['expiry']+gap)) for p in ref[40:]]
        out=series(stale,self.model,True,None)
        self.assertEqual(out[40]['frozen_logit_delta'],0.)
        invalid=series([dict(p,row=dict(p['row'],valid=False)) for p in ref],self.model,True,None)
        self.assertTrue(all(p['frozen_level']==.48 and p['frozen_logit_delta']==0. for p in invalid))

    def test_prefix_fitting_excludes_own_future_dates_and_deduplicates_sources(self):
        earlier=rows(80);future=rows(80,'2026-08-01')
        first=fit_prefix(earlier+future,{},['2026-01-01'],'2026-08-01','path')
        altered=fit_prefix(earlier+[dict(r,move=999999,valid=False) for r in future],
            {'2026-08-01':future},['2026-01-01'],'2026-08-01','path')
        self.assertEqual(first,altered)
        self.assertEqual(first['model']['windows'],80)
        with self.assertRaises(ValueError):fit_prefix(earlier,{},['2026-01-01']*2,'2026-08-01','path')
