from copy import deepcopy
import unittest
import gzip
import json
from pathlib import Path
import tempfile
from unittest.mock import patch

from frozen_conditional_cdf import fit as old_fit
from frozen_context_cdf import fit,forecast,series,supported,fit_prefix
from test_frozen_conditional_cdf import rows,values


def market_rows(count=400):
    data=rows(count)
    base=deepcopy(data[1])
    for i,r in enumerate(data):
        r['activity_features']=deepcopy(base['activity_features'])
        r['adaptive_features']=deepcopy(base['adaptive_features'])
        gap=4. if i%2==0 else .1
        r['oracle_gap']=dict(values=[gap,gap,0.,0.,0.],observed_at=r['start']-1000,lag_observed_at=r['start']-31000)
    return data


class FrozenContextCDFTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data=market_rows();cls.models={f:fit(cls.data,f) for f in ('timing','market')}

    def test_matched_support_and_exact_timing_fit_equivalence(self):
        data=deepcopy(self.data);data[0]['oracle_gap']=None
        data[1]['oracle_gap']['observed_at']=data[1]['start']
        timing=fit(data,'timing');market=fit(data,'market')
        self.assertEqual(timing['windows'],398);self.assertEqual(market['windows'],398)
        old=old_fit(data[2:],'path')
        for field in ('center','sd','floor_coefficients','positive_coefficients'):
            self.assertEqual(timing[field],old[field])

    def test_market_information_recovers_signal_absent_from_timing(self):
        a,b=self.data[0],self.data[1]
        self.assertAlmostEqual(forecast(a,self.models['timing'])[1],forecast(b,self.models['timing'])[1])
        self.assertGreater(forecast(a,self.models['market'])[1],.6)
        self.assertLess(forecast(b,self.models['market'])[1],.4)

    def test_unpriceable_forecasts_teach_floor_but_not_priceable_coverage_level(self):
        model=deepcopy(self.models['timing']);model['floor_coefficients']=[30]+[0]*len(model['center'])
        ref=values([dict(r,move=50) for r in self.data[:40]])
        first=series(ref,model,'priceable',None);old=series(ref,model,'reference',None)
        self.assertTrue(all(p['frozen_level']==.48 for p in first))
        self.assertLess(first[-1]['frozen_logit_delta'],0.)
        self.assertGreater(old[-1]['frozen_level'],.48)

    def test_freshness_fallback_and_future_labels_never_control_entry(self):
        data=deepcopy(self.data[:80]);data[4]['oracle_gap']['observed_at']=data[4]['start']
        self.assertFalse(supported(data[4]))
        ref=values(data);out=series(ref,self.models['market'],'priceable',.53)
        self.assertEqual(out[4]['width_ppm'],ref[4]['width_ppm']);self.assertFalse(out[4]['paused'])
        changed=[dict(p,row=dict(p['row'],move=999999,valid=False)) if i>=30 else p for i,p in enumerate(ref)]
        other=series(changed,self.models['market'],'priceable',.53)
        fields=lambda part:[(p['width_ppm'],p['paused'],p.get('frozen_floor')) for p in part[:32]]
        self.assertEqual(fields(out),fields(other))
        open_=series(ref,self.models['market'],'priceable',None)
        self.assertEqual([(p['width_ppm'],p.get('frozen_level')) for p in open_],[(p['width_ppm'],p.get('frozen_level')) for p in out])

    def test_future_training_is_excluded_and_quantiles_keep_absolute_bounds(self):
        future=[dict(r,period='2026-08-01',move=999999) for r in self.data]
        actual=fit_prefix(self.data+future,{},['2026-01-01'],'2026-08-01','market')
        expected=fit_prefix(self.data,{},['2026-01-01'],'2026-08-01','market')
        self.assertEqual(actual,expected)
        widths=[forecast(self.data[1],self.models['market'],level=q)[0] for q in (.1,.3,.48,.7,.95)]
        self.assertEqual(widths,sorted(widths));self.assertTrue(all(1<=w<=50000 for w in widths))

    def test_research_replay_records_market_support_for_every_variant(self):
        from research_frozen_market import replay
        data=[dict(r,market_regime='range') for r in self.data[:10]]
        ref=values(data)
        session=dict(id='fixture',source='fixture',period=data[0]['period'],split='selection',mode='restart',rows=data,
                     intervals=[dict(start=data[0]['start'],end=data[-1]['expiry'],hour=0)])
        models={f:{'model':m} for f,m in self.models.items()}
        with tempfile.TemporaryDirectory() as tmp,patch('research_frozen_market.price',return_value=([],ref)):
            path=Path(tmp)/'predictions.gz';result=replay([session],models,{},path)
            with gzip.open(path,'rt') as stream:records=[json.loads(line) for line in stream]
        self.assertEqual(len(records),130)
        self.assertTrue(all(p['market_supported'] for p in records))
        self.assertTrue(result['cases'])
