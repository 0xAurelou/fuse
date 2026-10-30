import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from release_evidence import (ROOT, USDC, audit_cash, build, capital_evidence,
                              empirical_pricing_evidence, incentive_evidence,
                              release_pricing_evidence, verify_hash, sha)


def cash_case():
    row = dict(accounts=1, selected_grid_entries=10, resolved_grid_entries=8,
               censored_grid_entries=2, survived_grid_entries=3,
               lp_gross_assuming_censored_refund_usdc_units=2*USDC,
               customer_gross_usdc_units=-2*USDC, placed_turnover_usdc_units=10*USDC,
               placed_tickets=10, cost_sensitivity=[])
    for bps in (0, 10, 50, 100):
        cost = 10*USDC*bps//10_000
        row['cost_sensitivity'].append(dict(expense_bps=bps,
            allocated_expense_usdc_units=cost,
            lp_net_assuming_censored_refund_usdc_units=2*USDC-cost,
            lp_net_lower_if_all_censored_survive_usdc_units=-cost,
            lp_net_upper_if_all_censored_fail_usdc_units=4*USDC-cost))
    return row


class ReleaseEvidenceTests(unittest.TestCase):
    def test_empirical_attachment_requires_full_audit_and_preserves_unsupported_products(self):
        from release_pricing import ASSETS, DELAYS, EDGES, PAYOUTS, STRATEGIES
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            (root/'protocol.json').write_text('{}\n')
            artifacts={}
            for name in ('forecasts.jsonl.gz','models.jsonl.gz','cases.jsonl','joint.jsonl','native-quantization.jsonl'):
                (root/name).write_text('fixture\n');artifacts[name]=sha(root/name)
            summary=[dict(asset=a,multiplier=m,edge_bps=e,delay_ms=d,strategy=s,quote_available=0)
                for a in ASSETS for m in PAYOUTS for e in EDGES for d in DELAYS for s in STRATEGIES]
            result=dict(protocol_sha256=sha(root/'protocol.json'),artifacts_sha256=artifacts,
                complete_common_dates=['2026-01-01'],unique_asset_grid_opportunities=8640,
                forecasted_asset_payout_edge_opportunities=311040,daily_strategy_cases=4320,
                daily_joint_cases=180,native_quantization_vectors=0,summary=summary,
                native_admission_replayed=False,funded_bankroll_evaluated=False,fresh_holdout=False,
                previously_inspected_development_data=True,production_pricing_validated=False,goal_complete=False)
            plan=dict(source_sha256={'scripts/audit_release_empirical.py':sha(ROOT/'scripts/audit_release_empirical.py')},
                baseline_directory='unused',days=['2026-01-01'],new_independent_holdout=False,
                paired_native_admission=False,funded_bankroll_replayed=False,production_policy_changed=False)
            audit=dict(passed=True,protocol_sha256=sha(root/'protocol.json'),
                auditor_sha256=plan['source_sha256']['scripts/audit_release_empirical.py'],
                forecasts_reconstructed=311040,cash_cases_replayed=4320,joint_cases_checked=180,
                native_arithmetic_vectors_reexecuted=0,independent_external_review=False,
                production_pricing_validated=False,goal_complete=False)
            def save():
                (root/'result.json').write_text(json.dumps(result))
                audit['result_sha256']=sha(root/'result.json')
                (root/'audit.json').write_text(json.dumps(audit))
            save()
            with patch('research_release_empirical.verify',return_value=plan), \
                    patch('release_evidence.release_pricing_evidence',return_value={'days':plan['days']}):
                got=empirical_pricing_evidence(root)
                self.assertEqual(got['immediate_combinations_with_no_offers'],108)
                self.assertEqual(got['immediate_combinations_with_offers'],0)
                self.assertEqual(got['immediate_lp_best_case_negative'],0)
                self.assertEqual(len(got['immediate_all_108_challengers']),108)
                self.assertFalse(got['production_pricing_validated'])
                for key in ('fresh_holdout','native_admission_replayed','production_pricing_validated'):
                    result[key]=True;save()
                    with self.assertRaisesRegex(ValueError,'scope binding'):empirical_pricing_evidence(root)
                    result[key]=False
                audit['cash_cases_replayed']-=1;save()
                with self.assertRaisesRegex(ValueError,'coverage'):empirical_pricing_evidence(root)
                audit['cash_cases_replayed']+=1
                last=result['summary'].pop();save()
                with self.assertRaisesRegex(ValueError,'summary grid'):empirical_pricing_evidence(root)
                result['summary'].append(last);save()
                (root/'cases.jsonl').write_text('changed\n')
                with self.assertRaisesRegex(ValueError,'hash mismatch'):empirical_pricing_evidence(root)

    def test_new_pricing_attachment_requires_complete_bound_audit_without_external_review_claim(self):
        from release_pricing import ASSETS, EDGES, PAYOUTS
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root/'protocol.json').write_text('{}\n')
            controls = [dict(asset=a, multiplier=m, edge_bps=e, delay_ms=0, strategy='all_offered',
                             gross_lp_if_censored_all_fail_usdc_units=-1)
                        for a in ASSETS for m in PAYOUTS for e in EDGES]
            result = dict(protocol_sha256=sha(root/'protocol.json'), artifacts_sha256={},
                          path_envelopes=43200, daily_strategy_cases=4320, daily_joint_cases=180,
                          native_formula_vectors_verified=108, native_admission_replayed=False,
                          funded_liabilities_or_rewards_evaluated=False, production_pricing_validated=False,
                          complete_common_dates=['2026-01-01'], unique_grid_opportunities=8640,
                          summary=controls)
            (root/'result.json').write_text(json.dumps(result))
            audit = dict(protocol_sha256=sha(root/'protocol.json'), result_sha256=sha(root/'result.json'),
                         passed=True, auditor_sha256=sha(ROOT/'scripts/audit_release_pricing.py'),
                         independent_external_review=False, production_pricing_validated=False,
                         raw_envelopes_reconstructed=43200, strategy_cases_replayed=4320,
                         joint_cases_replayed=180, native_formula_vectors=108)
            (root/'audit.json').write_text(json.dumps(audit))
            plan = dict(source_sha256={}, days=['2026-01-01'])
            with patch('research_release_pricing.verify_plan', return_value=plan):
                got = release_pricing_evidence(root)
                self.assertEqual(got['immediate_lp_best_case_negative'], 108)
                self.assertFalse(got['production_pricing_validated'])
                audit['independent_external_review'] = True
                (root/'audit.json').write_text(json.dumps(audit))
                with self.assertRaisesRegex(ValueError, 'scope binding'):
                    release_pricing_evidence(root)
                audit['independent_external_review'] = False
                audit['raw_envelopes_reconstructed'] -= 1
                (root/'audit.json').write_text(json.dumps(audit))
                with self.assertRaisesRegex(ValueError, 'coverage'):
                    release_pricing_evidence(root)
                audit['raw_envelopes_reconstructed'] += 1
                result['summary'] = result['summary'][:-1]
                (root/'result.json').write_text(json.dumps(result))
                audit['result_sha256'] = sha(root/'result.json')
                (root/'audit.json').write_text(json.dumps(audit))
                with self.assertRaisesRegex(ValueError, 'incomplete immediate'):
                    release_pricing_evidence(root)
    def test_independent_case_audit_rejects_wrong_winning_debt_and_expense_denominator(self):
        row = cash_case()
        audit_cash(row)
        corrupt = copy.deepcopy(row)
        corrupt['lp_gross_assuming_censored_refund_usdc_units'] += USDC
        with self.assertRaisesRegex(ValueError, 'conservation'):
            audit_cash(corrupt)
        corrupt = copy.deepcopy(row)
        corrupt['cost_sensitivity'][1]['allocated_expense_usdc_units'] = 8*USDC*10//10_000
        with self.assertRaisesRegex(ValueError, 'expense'):
            audit_cash(corrupt)

    def test_censored_ticket_bounds_cannot_be_replaced_by_assumed_refund(self):
        row = cash_case()
        row['cost_sensitivity'][0]['lp_net_lower_if_all_censored_survive_usdc_units'] = 2*USDC
        with self.assertRaisesRegex(ValueError, 'censoring'):
            audit_cash(row)

    def test_evidence_tamper_and_overwrite_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'data'
            path.write_text('sealed')
            expected = sha(path)
            path.write_text('changed')
            with self.assertRaisesRegex(ValueError, 'hash mismatch'):
                verify_hash(path, expected)
            with self.assertRaises(FileExistsError):
                build(Path(tmp), Path(tmp)/'absent')

    def test_capital_rejects_high_payouts_at_fifty_dollars_and_funds_all_accepted_wins(self):
        result = capital_evidence()
        self.assertEqual((result['accepted'], result['rejected']), (21, 6))
        self.assertEqual(result['exposure_before_results'], 65_250*USDC)
        self.assertEqual(result['recognized_unfunded_wins'], 65_250*USDC)
        self.assertEqual(result['final_cash_usdc_units'], 184_750*USDC)
        self.assertFalse(result['calibrated_production_limits'])

    def test_lp_player_can_extract_subsidy_without_winning_a_bet(self):
        result = incentive_evidence()
        cases = {(r['loss_carryforward_exists'], r['loss_reward_bps']): r
                 for r in result['deliberate_loss_lp_player_cases']}
        self.assertEqual(cases[False, 200]['joint_lp_player_change_usdc_units'], -3*USDC)
        self.assertEqual(cases[False, 1000]['joint_lp_player_change_usdc_units'], 5*USDC)
        self.assertEqual(cases[True, 200]['joint_lp_player_change_usdc_units'], 2*USDC)
        self.assertEqual(cases[True, 1000]['joint_lp_player_change_usdc_units'], 10*USDC)
        self.assertFalse(result['global_cap_on_all_future_fuse_value_proven'])

    def test_assumed_edge_does_not_prevent_high_payout_welcome_positive_ev(self):
        rows = incentive_evidence()['assumed_probability_sensitivities']
        by_key = {(r['assumed_edge_bps'], r['payout'], r['loss_reward_bps']):
                  r['player_expected_return_before_costs']['numerator'] for r in rows}
        self.assertLess(by_key[700, 2, 1000], 0)
        self.assertGreater(by_key[700, 5, 1000], 0)
        self.assertGreater(by_key[850, 10, 1000], 0)
        self.assertTrue(all(r['player_expected_return_before_costs']['numerator'] < 0
                            for r in rows if r['loss_reward_bps'] == 200))


if __name__ == '__main__':
    unittest.main()
