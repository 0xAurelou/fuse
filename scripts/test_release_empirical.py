from copy import deepcopy
from pathlib import Path
import subprocess
import tempfile
import unittest

from release_empirical_pricing import (PPB, SPEC, context, digest, fit, reference,
                                       replay, surface, threshold)
from release_pricing import PAYOUTS
from test_release_pricing import tape
from audit_release_empirical import verify_forecast
from research_release_empirical import copy_native_binary


def row(entry=PPB):
    return dict(day='2026-01-01',delay_ms=0,quote_at=10_000,accepted_at=10_000,
        expiry=40_000,entry=entry,move=3,quote_available=True,quote_age_ms=100,
        accepted=True,valid=True,prior_state='moving',mark_gap_ppm=10)


def references(n=3000, atom=False):
    return [dict(day=f'2025-0{1+i%3}-01',maturity=i,context=('moving','low','fresh'),
                 threshold=100 if atom else i+10) for i in range(n)]


class EmpiricalPricingTests(unittest.TestCase):
    def test_sealed_binary_preserves_execution_permission_and_content(self):
        with tempfile.TemporaryDirectory() as directory:
            source, target = (Path(directory)/name for name in ('source', 'sealed'))
            source.write_text('#!/bin/sh\nprintf native-bridge-ok\n')
            source.chmod(0o755)
            copy_native_binary(source, target)
            self.assertEqual(target.read_bytes(), source.read_bytes())
            self.assertEqual(subprocess.check_output([str(target)]), b'native-bridge-ok')
            source.chmod(0o644)
            with self.assertRaises(PermissionError):
                copy_native_binary(source, Path(directory)/'invalid')
            self.assertFalse((Path(directory)/'invalid').exists())

    def test_threshold_matches_native_floor_and_strict_touch(self):
        for entry in (1, 100_000_000, 3_000_000_000, 100_000_000_000):
            for move in (0,1,3,999):
                r=row(entry);r['move']=move;minimum=threshold(r)
                self.assertGreater(entry*minimum//PPB,move)
                self.assertLessEqual(entry*(minimum-1)//PPB,move)

    def test_daily_fit_excludes_own_future_and_exact_maturity(self):
        refs=references();initial=fit(refs,4000)
        later=refs+[dict(day='later',maturity=m,context=('moving','low','fresh'),threshold=10**8) for m in (4000,4001,9999)]
        self.assertEqual(initial,fit(later,4000))
        altered=deepcopy(later)
        for r in altered[len(refs):]:r['threshold']=1
        self.assertEqual(initial,fit(altered,4000))

    def test_refused_paths_still_supply_mature_reference_labels(self):
        r=row();ref=reference(r)
        self.assertIsNotNone(ref)
        self.assertEqual(ref['maturity'],70_000)
        self.assertFalse(surface({},r,850)[2]['offered'])
        self.assertEqual(fit([ref],70_000),{})
        self.assertTrue(fit([ref],70_001))
        r['valid']=False
        self.assertIsNone(reference(r))

    def test_all_presets_and_edges_remain_visible_and_rare_tail_is_not_extrapolated(self):
        model=fit(references(),4000)
        for edge in (500,700,850,1000):
            offers=surface(model,row(),edge)
            self.assertEqual(tuple(offers),PAYOUTS)
            self.assertTrue(offers[2]['offered'])
            self.assertFalse(offers[10000]['offered'])
            self.assertEqual(offers[10000]['reason'],'insufficient_tail_reference_rank')
            widths=[q['width_ppb'] for q in offers.values() if q['offered']]
            deltas=[q['delta'] for q in offers.values() if q['offered']]
            self.assertTrue(all(b<a for a,b in zip(widths,widths[1:])))
            self.assertTrue(all(b<a for a,b in zip(deltas,deltas[1:])))
            for m,q in offers.items():
                if q['offered']:
                    self.assertGreaterEqual(q['training_survivors'],20)
                    self.assertLessEqual(q['training_survivors']*10000*m,q['training_references']*(10000-edge))

    def test_atom_with_no_observed_tail_wins_is_refused_not_successful_calibration(self):
        q=surface(fit(references(atom=True),4000),row(),850)[2]
        self.assertFalse(q['offered'])
        self.assertEqual(q['training_survivors'],0)
        self.assertEqual(q['reason'],'insufficient_observed_tail_survivors')

    def test_minimum_dates_and_integer_price_width_refusals(self):
        refs=references()
        for ref in refs:ref['day']='2025-01-01'
        self.assertEqual(surface(fit(refs,4000),row(),850)[2]['reason'],'insufficient_earlier_reference_dates')
        q=surface(fit(references(),4000),row(1),850)[2]
        self.assertFalse(q['offered'])
        self.assertEqual(q['reason'],'native_minimum_width_exceeds_empirical_budget')

    def test_missing_current_context_never_inherits_global_quote(self):
        r=row();r['prior_state']='missing_history'
        self.assertTrue(all(not q['offered'] for q in surface(fit(references(),4000),r,850).values()))

    def test_public_history_matures_after_actual_delayed_expiry(self):
        source=tape(end=150_000)
        for delay,want in ((0,1),(250,0)):
            rows=[source.envelope(at,delay) for at in (30_000,60_000,90_000)]
            q=dict(multiplier=2,edge_bps=850,offered=True,reason='offered',delta=1)
            counts,codes,reasons,oracle=replay(rows,[q]*3,2,850)
            self.assertEqual(counts['last_matured_survived'].intended,want)
            self.assertEqual(list(codes),[3,3,3])
            self.assertEqual(oracle,3)

    def test_future_censoring_keeps_placement_and_full_payout_cash_bound(self):
        source=tape(end=90_000)
        rows=[source.envelope(60_000,250)]
        q=dict(multiplier=10000,edge_bps=850,offered=True,reason='offered',delta=1)
        counts,codes,_,_=replay(rows,[q],10000,850)
        result=counts['all_offered'].result(10000,850)
        self.assertEqual(list(codes),[1])
        self.assertEqual(result['accepted'],1)
        self.assertEqual(result['gross_lp_if_censored_all_win_usdc_units'],-9999_000_000)
        with self.assertRaises(ValueError):replay(rows,[],10000,850)
        with self.assertRaises(ValueError):replay(rows,[q],2,850)

    def test_independent_forecast_check_rejects_width_support_and_refusal_tampering(self):
        r=row();model=fit(references(),4000);offers=surface(model,r,850);first=offers[2]
        keys=('training_group','training_references','training_dates','maximum_label_maturity_ms','threshold_sha256')
        record=dict(model_id='fixed-model',entry=r['entry'],edge_bps=850,**{k:first[k] for k in keys},
            offers=[{k:q[k] for k in ('multiplier','offered','reason','width_ppb','delta','training_survivors')} for q in offers.values()])
        verify_forecast(record,r,model,SPEC,'fixed-model')
        for change in (lambda x:x['offers'][0].update(width_ppb=1),
                       lambda x:x.update(training_references=1),
                       lambda x:x['offers'][-1].update(offered=True),
                       lambda x:x['offers'].pop()):
            copy=deepcopy(record);change(copy)
            with self.assertRaises(ValueError):verify_forecast(copy,r,model,SPEC,'fixed-model')


if __name__=='__main__':unittest.main()
