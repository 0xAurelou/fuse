from copy import deepcopy
from datetime import datetime, timezone
import math
import unittest

import numpy as np

from symbolic_corridor import SPEC, check_tree, expression_text, features, fit, formula_log, series, size, term_value
from test_gap_quantile import gap_paths


def samples():
    records=[]
    for month in range(1,7):
        day=f'2025-{month:02}-01'; origin=int(datetime.fromisoformat(day).replace(tzinfo=timezone.utc).timestamp()*1000)
        for i in range(100):
            drift=(i-49.5)/50; value=.1+.8*abs(drift)
            records.append(dict(source='gap',row=dict(period=day,start=origin+i*30000,expiry=origin+(i+1)*30000,activity_state='bursty'),
                model_cutoff='2025-01-01',training_periods=['2024-11-01','2024-12-01'],
                features=[0.,drift,0.,0.,0.,0.,0.],regime='pump' if drift>.5 else 'dump' if drift<-.5 else 'range',
                ratio=math.exp(value)))
    return records


def paths():
    values=gap_paths(90)
    for p in values: p['row']['adaptive_features']['net_300_bps']=8.
    return values


class SymbolicFitTests(unittest.TestCase):
    def test_discovers_nonlinear_structure_with_chronological_validation(self):
        rows=samples(); periods=[f'2025-{i:02}-01' for i in range(1,6)]
        a=fit(rows,periods,'2025-06-01'); b=fit(rows,periods,'2025-06-01')
        self.assertEqual(a,b)
        self.assertTrue(a['terms']); self.assertIn('abs',expression_text(a))
        self.assertLess(max(a['fitting_dates']),min(a['validation_dates']))
        self.assertLessEqual(len(a['terms'])+sum(size(t) for t in a['terms']),SPEC['max_nodes'])
        x=np.asarray([r['features'] for r in rows[-100:]])
        predicted=a['coefficients'][0]+sum(c*term_value(t,x) for c,t in zip(a['coefficients'][1:],a['terms']))
        y=np.log([r['ratio'] for r in rows[-100:]])
        self.assertLess(np.mean(np.abs(y-predicted)),.7*np.mean(np.abs(y-a['constant_coefficients'][0])))

    def test_future_outcomes_cannot_change_structure_or_coefficients(self):
        rows=samples(); periods=[f'2025-{i:02}-01' for i in range(1,6)]
        a=fit(rows,periods,'2025-06-01'); changed=deepcopy(rows)
        for r in changed:
            if r['row']['period']>='2025-06-01': r.update(ratio=999999.,features=[99.]*7)
        self.assertEqual(a,fit(changed,periods,'2025-06-01'))

    def test_early_fallback_and_bad_forecasts_duplicates_and_unmatured_labels(self):
        self.assertTrue(fit([],['2024-11-01'],'2025-01-01')['neutral_fallback'])
        periods=['2025-01-01','2025-02-01']; rows=samples()
        self.assertFalse(fit(rows,periods,'2025-03-01')['terms'])
        for fault in ('duplicate','own_fit','future_model','unmatured','nonfinite'):
            changed=deepcopy(rows)
            if fault=='duplicate': changed.append(deepcopy(changed[0]))
            if fault=='own_fit': changed[0]['training_periods'].append('2025-01-01')
            if fault=='future_model': changed[0]['model_cutoff']='2025-02-01'
            if fault=='unmatured': changed[0]['row']['expiry']=int(datetime(2025,3,1,tzinfo=timezone.utc).timestamp()*1000)-30000
            if fault=='nonfinite': changed[0]['features'][0]=math.nan
            with self.assertRaises(ValueError): fit(changed,periods,'2025-03-01')

    def test_data_tree_grammar_rejects_code_and_unbounded_nesting(self):
        for tree in (('eval','anything'),('x',99),('x',True),('mul',('x',0)),('abs',('abs',('abs',('x',0))))):
            with self.assertRaises(ValueError): check_tree(tree)
        x=np.zeros((2,7))
        self.assertTrue(np.isfinite(term_value(('div',('x',0),('x',1)),x)).all())


class SymbolicReplayTests(unittest.TestCase):
    def setUp(self):
        self.model=dict(terms=[('abs',('x',1))],coefficients=[.1,.4],constant_coefficients=[.2])

    def run_paths(self,values,adaptive=True,constant=False):
        cached=[(100,.1) if p['width_ppm'] is not None and p['row']['activity_state']=='bursty' and p['row'].get('oracle_gap') else None for p in values]
        return series(values,cached,self.model,adaptive,constant)

    def test_feature_allowlist_ignores_outcome_and_regime_label(self):
        row=paths()[0]['row']; changed=deepcopy(row)
        changed.update(move=999999,entry=1,valid=False,market_regime='invented')
        self.assertEqual(features(row),features(changed))
        self.assertEqual(formula_log(row,self.model),formula_log(changed,self.model))

    def test_label_maturity_other_state_isolation_and_refused_learning(self):
        values=paths()
        for i,p in enumerate(values):
            if i%3: p['row']['activity_state']='active'
        a=self.run_paths(values); changed=deepcopy(values)
        for p in changed:
            if p['row']['activity_state']=='active': p['row']['move']=0
        b=self.run_paths(changed)
        self.assertEqual([p['width_ppm'] for p in a],[p['width_ppm'] for p in b])
        changed=deepcopy(values)
        for p in changed[20:]: p['row'].update(move=999999,valid=False)
        b=self.run_paths(changed)
        self.assertEqual([p['width_ppm'] for p in a[:22]],[p['width_ppm'] for p in b[:22]])
        changed=deepcopy(values)
        for p in changed: p.update(paused=True,survived=None)
        self.assertEqual([p['width_ppm'] for p in a],[p['width_ppm'] for p in self.run_paths(changed)])

    def test_fallback_masks_width_bounds_static_and_restart(self):
        values=paths()
        for i,p in enumerate(values):
            if i%4==0: p['row']['activity_state']='frozen'
            if i%4==1: p['row']['oracle_gap']=None
        for adaptive in (False,True):
            for constant in (False,True):
                a=self.run_paths(values,adaptive,constant)
                for p,old in zip(a,values):
                    self.assertEqual(p['paused'],old['paused']); self.assertTrue(1<=p['width_ppm']<=50000)
                    if old['row']['activity_state']!='bursty' or old['row']['oracle_gap'] is None: self.assertEqual(p,old)
                    elif not adaptive: self.assertEqual(p['symbolic_online'],0.)
        for p in values[45:]: p['row']['period']='next'
        self.assertEqual(self.run_paths(values)[45:],self.run_paths(values[45:]))
        with self.assertRaises(ValueError): self.run_paths(list(reversed(values)))


if __name__=='__main__': unittest.main()
