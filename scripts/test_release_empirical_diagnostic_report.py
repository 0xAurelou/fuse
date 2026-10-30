from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from diagnose_release_empirical import SPEC
from release_pricing import ASSETS,DAY,DELAYS,EDGES,GRID,PAYOUTS
from report_release_empirical_diagnostics import ADDITIVE,check_row,check_sum,inspect,report
from research_release_pricing import sha


def sample():
    return dict(multiplier=5,edge_bps=850,grid=6,oracle_quote_available=6,quote_available=6,
        accepted=5,censored=1,resolved=4,wins=2,flat_wins=1,moving_wins=1,touch_losses=1,other_losses=1,
        flat_payout_usdc_units=5_000_000,moving_payout_usdc_units=5_000_000,
        gross_lp_refund_usdc_units=-6_000_000,gross_lp_if_censored_all_fail_usdc_units=-5_000_000,
        flat_only_lp_upper_usdc_units=0,after_hindsight_flat_removal_lp_upper_usdc_units=-1_000_000,
        historical_expected_wins=dict(numerator=2,denominator=5),
        target_expected_wins=dict(numerator=183,denominator=250),
        observed_minus_historical_wins=dict(numerator=8,denominator=5),
        newest_training_label_age_min_ms=1000,newest_training_label_age_max_ms=1000,
        offered_training_groups={'exact':6},current_probability_validated=False)


def empty_fixture(root):
    parent=root/'parent';parent.mkdir()
    out=root/'diagnostics';out.mkdir();(out/'protocol.json').write_text('{}\n')
    daily=[];summary=[];cash=[]
    for a in ASSETS:
        for m in PAYOUTS:
            for e in EDGES:
                for d in DELAYS:
                    for g in SPEC['groups']:
                        x=dict(asset=a,multiplier=m,edge_bps=e,delay_ms=d,group=g,**{k:0 for k in ADDITIVE})
                        x.update(grid=DAY//GRID if g in ('all','missing_history') else 0,
                            historical_expected_wins=None,target_expected_wins=None,observed_minus_historical_wins=None,
                            offered_training_groups={},newest_training_label_age_min_ms=None,newest_training_label_age_max_ms=None,
                            current_probability_validated=False)
                        daily.append(dict(day='2026-01-01',**x));summary.append(x)
                        if g=='all':cash.append(dict(strategy='all_offered',**x))
    (parent/'result.json').write_text(json.dumps(dict(summary=cash)))
    plan=dict(days=['2026-01-01'],parent=str(parent))
    result=dict(protocol_sha256=sha(out/'protocol.json'),days=plan['days'],summary=summary,
        daily_diagnostic_cases=len(daily),delayed_forecasts=len(ASSETS)*len(PAYOUTS)*len(EDGES)*len(DELAYS)*DAY//GRID,
        post_result_diagnostic=True,new_model_evaluated=False,fresh_holdout=False,production_pricing_validated=False,goal_complete=False)
    def save():
        (out/'daily.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in daily))
        result['daily_sha256']=sha(out/'daily.jsonl')
        (out/'result.json').write_text(json.dumps(result))
    save()
    return out,plan,result,daily,save


class DiagnosticReportTests(unittest.TestCase):
    def test_independent_cash_checker_accepts_partition_and_rejects_tampering(self):
        good=sample();check_row(good)
        for name in ('flat_wins','moving_wins','touch_losses','gross_lp_refund_usdc_units',
                     'flat_only_lp_upper_usdc_units','after_hindsight_flat_removal_lp_upper_usdc_units'):
            changed=deepcopy(good);changed[name]+=1
            with self.assertRaises(ValueError):check_row(changed)
        changed=deepcopy(good);changed['flat_payout_usdc_units']=5_000_000.0
        with self.assertRaisesRegex(ValueError,'count'):check_row(changed)

    def test_unsupported_forecast_claim_and_future_training_age_are_rejected(self):
        for change in (lambda r:r.update(current_probability_validated=True),
                       lambda r:r.update(newest_training_label_age_min_ms=0),
                       lambda r:r.update(historical_expected_wins={'numerator':1,'denominator':1}),
                       lambda r:r.update(offered_training_groups={'unknown':6})):
            r=sample();change(r)
            with self.assertRaises(ValueError):check_row(r)

    def test_exact_aggregation_checks_rationals_training_groups_and_age(self):
        a,b=sample(),sample();b['newest_training_label_age_max_ms']=2000
        merged=sample()
        for k in ADDITIVE:merged[k]*=2
        for k in ('historical_expected_wins','target_expected_wins','observed_minus_historical_wins'):
            merged[k]['numerator']*=2
        merged['offered_training_groups']={'exact':12};merged['newest_training_label_age_max_ms']=2000
        check_sum(merged,[a,b]);check_row(merged)
        for key in ('newest_training_label_age_max_ms','wins'):
            r=deepcopy(merged);r[key]+=1
            with self.assertRaises(ValueError):check_sum(r,[a,b])

    def test_full_empty_menu_is_visible_and_cannot_be_promoted(self):
        with tempfile.TemporaryDirectory() as directory:
            out,plan,result,daily,save=empty_fixture(Path(directory))
            with patch('report_release_empirical_diagnostics.verify',return_value=plan):
                got=inspect(out);self.assertEqual(len(got['summary']),2700)
                result['production_pricing_validated']=True;save()
                with self.assertRaisesRegex(ValueError,'scope'):inspect(out)

    def test_missing_duplicate_and_rewritten_cash_cases_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            out,plan,result,daily,save=empty_fixture(Path(directory))
            with patch('report_release_empirical_diagnostics.verify',return_value=plan):
                last=daily.pop();save()
                with self.assertRaisesRegex(ValueError,'coverage'):inspect(out)
                daily.append(last);daily[-1]=deepcopy(daily[0]);save()
                with self.assertRaisesRegex(ValueError,'coverage'):inspect(out)
                daily[-1]=last;daily[0]['flat_only_lp_upper_usdc_units']=1;save()
                with self.assertRaisesRegex(ValueError,'flat bound'):inspect(out)

    def test_report_keeps_no_quotes_as_unavailable_and_seals_artifacts(self):
        with tempfile.TemporaryDirectory() as directory:
            out,plan,result,daily,save=empty_fixture(Path(directory))
            with patch('report_release_empirical_diagnostics.verify',return_value=plan):
                facts=report(out)
                self.assertEqual((facts['immediate_with_offers'],facts['immediate_no_offers']),(0,108))
                self.assertIsNone(facts['newest_training_label_age_min_ms'])
                self.assertIn('No quotes were offered',(out/'report.md').read_text())
                self.assertFalse(json.loads((out/'checks.json').read_text())['independent_path_reconstruction'])
                bindings=json.loads((out/'manifest.json').read_text())
                self.assertTrue(all(sha(out/n)==h for n,h in bindings.items()))
                with self.assertRaises(FileExistsError):report(out)


if __name__=='__main__':unittest.main()
