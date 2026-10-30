from copy import deepcopy
import unittest
from unittest.mock import patch

from chronological_raw_priors import training_rows, fit_bundle, replay, VARIANTS
from test_bursty_pricing import references, model


class ChronologicalRawPriorTests(unittest.TestCase):
    def rows(self):
        return [dict(period=day,start=i*1000+j,expiry=i*1000+j+30)
                for i,day in enumerate(('2025-01-01','2025-02-01','2025-03-01')) for j in range(3)]

    def test_replaces_one_date_without_double_counting_or_adding_future_dates(self):
        original=self.rows();raw={'2025-01-01':[dict(original[0],move=9)],
                                 '2025-03-01':[dict(original[-1],move=999)]}
        out,provenance=training_rows(list(reversed(original)),raw,
            ['2025-02-01','2025-01-01'],'2025-03-01',True)
        self.assertEqual([r['start'] for r in out],[0,1000,1001,1002])
        self.assertEqual([r['source'] for r in provenance],['raw','normalized'])
        changed=deepcopy(raw);changed['2025-03-01'][0]['move']=1
        self.assertEqual((out,provenance),training_rows(original,changed,
            ['2025-02-01','2025-01-01'],'2025-03-01',True))

    def test_own_day_and_duplicate_dates_are_rejected(self):
        for periods in (['2025-03-01'],['2025-01-01','2025-01-01']):
            with self.assertRaises(ValueError):training_rows(self.rows(),{},periods,'2025-03-01',True)

    def test_maturity_crossing_cutoff_is_rejected_even_with_earlier_period_label(self):
        from datetime import datetime,timezone
        boundary=int(datetime(2025,2,1,tzinfo=timezone.utc).timestamp()*1000)
        raw={'2025-01-01':[dict(self.rows()[0],expiry=boundary-30_000)]}
        with self.assertRaises(ValueError):
            training_rows(self.rows(),raw,['2025-01-01'],'2025-02-01',True)

    def test_duplicate_references_and_mislabelled_raw_days_are_rejected(self):
        r=self.rows()[0]
        for rows in ([r,r],[dict(r,period='2025-02-01')]):
            with self.assertRaises(ValueError):
                training_rows(self.rows(),{'2025-01-01':rows},['2025-01-01'],'2025-02-01',True)

    def test_fit_uses_target_engine_instead_of_cached_training_widths(self):
        original=self.rows();engine={'target':'engine'};overlay={'fixed':'overlay'}
        prices=references(3);floors=references(3,move=90)
        with patch('chronological_raw_priors.priced',return_value=prices) as price, \
             patch('chronological_raw_priors.floor_values',return_value=floors) as floor, \
             patch('chronological_raw_priors.fit_model',return_value={'fitted':True}) as fit:
            result=fit_bundle(original,{},['2025-01-01'],'2025-02-01',engine,overlay,True)
        price.assert_called_once_with(original[:3],engine,overlay)
        floor.assert_called_once_with(prices,engine);fit.assert_called_once_with(floors)
        self.assertEqual(result['model'],{'fitted':True})

    def test_prior_variants_preserve_other_states_and_future_outcome_causality(self):
        values=references(60,move=50);m=model()
        for i,p in enumerate(values):p['row']['activity_state']=('bursty','active','frozen','sparse')[i%4]
        changed=deepcopy(values)
        for p in changed[30:]:p['row'].update(move=99999,valid=False)
        for _,method in VARIANTS:
            a,b=replay(values,m,method),replay(changed,m,method)
            self.assertEqual([p['width_ppm'] for p in a[:32]],[p['width_ppm'] for p in b[:32]])
            for p,base in zip(a,values):
                if base['row']['activity_state']!='bursty':self.assertEqual(p['width_ppm'],base['width_ppm'])


if __name__=='__main__':unittest.main()
