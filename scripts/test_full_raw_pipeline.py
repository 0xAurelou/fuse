from copy import deepcopy
from fractions import Fraction
import unittest
from unittest.mock import patch

from full_raw_pipeline import floor_bound, availability, mask, fit_bundle


class FullRawPipelineTests(unittest.TestCase):
    def test_integer_feasibility_and_august_refusal_bound(self):
        r=floor_bound(32,25)
        self.assertEqual(r['minimum_refusals'],18)
        self.assertEqual(r['maximum_retention'],14/32)
        self.assertFalse(r['fixed_quotes_feasible'])
        # 25/32 offered minimum survivors cannot be repaired by width tuning;
        # all 389 paths allow a less restrictive optimistic bound.
        self.assertEqual(floor_bound(389,241)['minimum_refusals'],75)
        self.assertTrue(floor_bound(25,8)['fixed_quotes_feasible'])
        self.assertIsNone(floor_bound(0,0)['fixed_quotes_feasible'])
        self.assertFalse(floor_bound(20,20)['fixed_quotes_feasible'])
        self.assertEqual(floor_bound(20,20)['maximum_retention'],0.)
        with self.assertRaises(ValueError):floor_bound(20,21)

    def test_bound_matches_exhaustive_small_path_subsets(self):
        from itertools import combinations
        for n in range(1,9):
            for floor in range(n+1):
                best=0
                for k in range(1,n+1):
                    for kept in combinations(range(n),k):
                        compulsory=sum(index<floor for index in kept)
                        if max(compulsory,-(-43*k//100))<=53*k//100:best=max(best,k)
                self.assertEqual(floor_bound(n,floor)['maximum_retention'],best/n)

    def test_retained_bundle_is_private_and_raw_fit_excludes_future_dates(self):
        retained={'engine':{'x':1},'overlay':{'spec':{'name':'fixture'}},'prior':{}}
        copy=fit_bundle([],{},[],'2025-01-01',retained,'retained')
        copy['engine']['x']=2
        self.assertEqual(retained['engine']['x'],1)
        rows=[dict(period='2024-12-01',start=0,expiry=30000,valid=True,activity_state='frozen')]
        future=dict(period='2025-01-01',start=100000,expiry=130000,valid=False,activity_state='bursty')
        with patch('full_raw_pipeline.fit',return_value={'new':True}) as fit, \
             patch('full_raw_pipeline.predict',return_value=[]),patch('full_raw_pipeline.apply_pause',return_value=[]), \
             patch('full_raw_pipeline.fit_overlay',return_value={}),patch('full_raw_pipeline.frozen_reprice',return_value=[]), \
             patch('full_raw_pipeline.floor_values',return_value=[]),patch('full_raw_pipeline.fit_bursty',return_value={}):
            actual=fit_bundle(rows+[future],{'2025-01-01':[future]},['2024-12-01'],'2025-01-01',retained,'raw_core')
            self.assertEqual(fit.call_args.args[0],rows)
            self.assertEqual(actual['training_periods'],['2024-12-01'])
            self.assertEqual(actual['training_frozen'],1)

    def test_raw_overlay_training_includes_refused_clean_reference_labels(self):
        rows=[dict(period='2024-12-01',start=0,expiry=30000,valid=True,activity_state='frozen')]
        refused=dict(row=rows[0],width_ppm=1,survived=None,shadow_survived=True,paused=True)
        retained={'engine':{},'overlay':{'spec':{'offered_only':False}},'prior':{}}
        with patch('full_raw_pipeline.predict',return_value=[refused]), \
             patch('full_raw_pipeline.apply_pause',return_value=[refused]), \
             patch('full_raw_pipeline.fit_overlay',return_value={}) as fit, \
             patch('full_raw_pipeline.frozen_reprice',return_value=[]), \
             patch('full_raw_pipeline.floor_values',return_value=[]),patch('full_raw_pipeline.fit_bursty',return_value={}):
            fit_bundle(rows,{},['2024-12-01'],'2025-01-01',retained,'raw_overlay')
            supplied=fit.call_args.args[0]
            self.assertEqual(len(supplied),1)
            self.assertTrue(supplied[0]['survived'])
            self.assertTrue(supplied[0]['paused'])
            self.assertIsNone(refused['survived'])

    def test_no_pause_preserves_predictions_and_availability_flags_hidden_refusals(self):
        values=[dict(width_ppm=1,paused=True,floor_reason='old',shadow_survived=True,survived=None)]
        original=deepcopy(values)
        out=mask(values,values,'no_pause')
        self.assertEqual(values,original)
        self.assertTrue(out[0]['survived']);self.assertFalse(out[0]['paused'])
        cases=[dict(activity='all',eligible_outcomes=901,eligible_quote_fraction=544/901),
               dict(activity='frozen',eligible_outcomes=389,eligible_quote_fraction=32/389)]
        self.assertFalse(availability(cases)['feasible'])
        self.assertTrue(availability([dict(r,eligible_quote_fraction=1.) for r in cases])['feasible'])
