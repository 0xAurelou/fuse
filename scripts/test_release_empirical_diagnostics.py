from copy import deepcopy
from fractions import Fraction
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from diagnose_release_empirical import (DiagnosticCounts,SPEC,rational,same_parent_cash,verify)
from research_release_pricing import sha


def forecast():
    return dict(training_references=100,maximum_label_maturity_ms=9000,training_group=['exact','moving','low','fresh'])


def offer():
    return dict(offered=True,delta=3,training_survivors=10)


def row(move=0):
    return dict(quote_at=10_000,quote_available=True,accepted=True,valid=True,move=move)


class EmpiricalDiagnosticTests(unittest.TestCase):
    def test_cash_partition_and_hindsight_bound_include_censored_placements(self):
        c=DiagnosticCounts()
        rows=[row(x) for x in (0,2,3,9)]
        censored=row(None);censored['valid']=False;rows.append(censored)
        rejected=row(None);rejected['valid']=False;rejected['accepted']=False;rows.append(rejected)
        for r in rows:c.add(r,offer(),forecast())
        x=c.result(5,850)
        self.assertEqual((x['accepted'],x['resolved'],x['censored']),(5,4,1))
        self.assertEqual((x['flat_wins'],x['moving_wins'],x['touch_losses'],x['other_losses']),(1,1,1,1))
        self.assertEqual(x['gross_lp_refund_usdc_units'],-6_000_000)
        self.assertEqual(x['flat_payout_usdc_units']+x['moving_payout_usdc_units'],10_000_000)
        self.assertEqual(x['flat_only_lp_upper_usdc_units'],0)
        self.assertEqual(x['after_hindsight_flat_removal_lp_upper_usdc_units'],-1_000_000)
        self.assertEqual(x['historical_expected_wins'],rational(Fraction(2,5)))
        self.assertEqual(x['observed_minus_historical_wins'],rational(Fraction(8,5)))
        self.assertEqual(x['newest_training_label_age_min_ms'],1000)

    def test_zero_motion_can_alone_break_even_while_moving_cohort_is_profitable(self):
        c=DiagnosticCounts()
        for move in (0,0,9):c.add(row(move),offer(),forecast())
        x=c.result(5,850)
        self.assertLess(x['flat_only_lp_upper_usdc_units'],0)
        self.assertEqual(x['after_hindsight_flat_removal_lp_upper_usdc_units'],1_000_000)

    def test_refused_and_censored_paths_cannot_become_resolved_flat_wins(self):
        for changed_move in (None,0,1000):
            c=DiagnosticCounts();r=row(changed_move);r['valid']=False
            c.add(r,offer(),forecast())
            c.add(row(0),dict(offered=False),{})
            x=c.result(5,850)
            self.assertEqual((x['grid'],x['quote_available'],x['accepted'],x['resolved'],x['censored']),(2,1,1,0,1))
            self.assertEqual(x['flat_wins'],0)
            self.assertIsNone(x['historical_expected_wins'])
            self.assertFalse(x['current_probability_validated'])

    def test_empty_and_rejected_cohorts_have_no_calibration_estimate(self):
        c=DiagnosticCounts();r=row(None);r['accepted']=False;r['valid']=False
        c.add(r,offer(),forecast())
        for x in (c.result(5,850),DiagnosticCounts().result(10000,1000)):
            self.assertIsNone(x['historical_expected_wins'])
            self.assertIsNone(x['target_expected_wins'])
            self.assertIsNone(x['observed_minus_historical_wins'])
            self.assertFalse(x['current_probability_validated'])

    def test_merging_preserves_exact_rationals_age_extrema_and_cash(self):
        whole=DiagnosticCounts();merged=DiagnosticCounts()
        for i,move in enumerate((0,2,3,9)):
            f=forecast();f['training_references']+=i;f['maximum_label_maturity_ms']-=i
            whole.add(row(move),offer(),f)
            c=DiagnosticCounts();c.add(row(move),offer(),f);merged.merge(c)
        self.assertEqual(merged.result(5,850),whole.result(5,850))
        self.assertEqual(whole.result(5,850)['newest_training_label_age_max_ms'],1003)

    def test_future_training_invalid_width_and_historical_budget_are_rejected(self):
        for maturity in (10000,10001):
            f=forecast();f['maximum_label_maturity_ms']=maturity
            with self.assertRaises(ValueError):DiagnosticCounts().add(row(),offer(),f)
        q=offer();q['delta']=0
        with self.assertRaises(ValueError):DiagnosticCounts().add(row(),q,forecast())
        q=offer();q['training_survivors']=99
        c=DiagnosticCounts();c.add(row(),q,forecast())
        with self.assertRaises(AssertionError):c.result(5,850)

    def test_parent_reconciliation_rejects_count_and_cash_tampering(self):
        c=DiagnosticCounts();c.add(row(),offer(),forecast());x=c.result(5,850)
        same_parent_cash(x,x)
        for key in ('quote_available','censored','wins','gross_lp_if_censored_all_fail_usdc_units'):
            changed=deepcopy(x);changed[key]+=1
            with self.assertRaises(ValueError):same_parent_cash(x,changed)

    def test_source_and_input_bindings_reject_changed_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);out=root/'packet';(out/'source').mkdir(parents=True)
            (root/'tool.py').write_text('tool\n');(out/'source/tool.py').write_text('tool\n')
            data=root/'parent.json';data.write_text('{}\n')
            plan=dict(spec=SPEC,source_sha256={'tool.py':sha(root/'tool.py')},
                input_sha256={str(data):sha(data)},python_version=sys.version)
            (out/'protocol.json').write_text(json.dumps(plan))
            (out/'freeze.json').write_text(json.dumps(dict(protocol_sha256=sha(out/'protocol.json'))))
            with patch('diagnose_release_empirical.ROOT',root):
                self.assertEqual(verify(out),plan)
                data.write_text('{"changed":true}\n')
                with self.assertRaisesRegex(ValueError,'input changed'):verify(out)
                data.write_text('{}\n');(root/'tool.py').write_text('changed\n')
                with self.assertRaisesRegex(ValueError,'source changed'):verify(out)


if __name__=='__main__':unittest.main()
