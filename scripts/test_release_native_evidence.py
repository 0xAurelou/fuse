import copy
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from release_native_evidence import PROFILES, ROOT, USDC, native_evidence, observed_capital, sha


def write(path,data):
    Path(path).write_text(json.dumps(data)+'\n')


def fixture(root):
    files = ['engine/internal/engine/types.go','engine/internal/engine/reducer.go',
             'engine/internal/engine/pricing.go','engine/cmd/fuse-research/main.go',
             'scripts/research_adaptive_native_ppb.py']
    for n in files:
        dest = root/'source'/n
        dest.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(ROOT/n,dest)
    (root/'fuse-research').write_text('fixture binary only, not a native test')
    (root/'auditor-source.py').write_text('fixture auditor only')
    plan = dict(source_sha256={n:sha(ROOT/n) for n in files},binary_sha256=sha(root/'fuse-research'),
        profiles=list(PROFILES),collection_quality_met=False,original_target_edge_bps=400,multiplier=2,
        receipt_count=10,initial_lp_usdc_units=250_000*USDC)
    write(root/'protocol.json',plan)
    ph=sha(root/'protocol.json')
    write(root/'freeze.json',dict(protocol_sha256=ph))
    cases, checks, artifacts = [], [], {}
    for profile in PROFILES:
        name=profile['name']
        row=dict(profile=profile,audit_records=20,all_original_receipts=10,
            intended_grid_entries=2,quote_attempts=2,accepted_stages=2,
            accepted_turnover_usdc_units=2*USDC,lp_gross_pnl_usdc_units=0,
            trader_gross_pnl_usdc_units=0,healthy_outcome_comparisons=2,
            peak_exposure_usdc_units=USDC,peak_unfunded_debt_usdc_units=USDC,
            accepted_censored_path_stages=0,cost_sensitivity=[dict(cost_bps=b,
                assumed_expense_usdc_units=2*USDC*b//10000,
                lp_gross_less_assumed_expense_usdc_units=-2*USDC*b//10000) for b in (0,10,50,100)])
        state=dict(lp=250_000*USDC,lp_profit=0,stages={str(i):dict(status=s,terms=dict(stake=USDC,payout=2*USDC))
            for i,s in enumerate(('exploded','survived'))})
        response=dict(request=dict(kind='command',command=dict(kind='lp_fund')),
            response=dict(ok=True,value=dict(lp=250_000*USDC,exposure=USDC,debt=USDC)))
        (root/(name+'-audit.jsonl')).write_text((json.dumps(response)+'\n')*20)
        write(root/(name+'-state.json'),state); write(root/(name+'-result.json'),row)
        for suffix in ('-audit.jsonl','-state.json','-result.json'):
            artifacts[name+suffix]=sha(root/(name+suffix))
        cases.append(row)
        checks.append(dict(profile=name,all_records_reexecuted=20,all_original_receipts=10,
            selected_grid_entries=2,quote_attempts=2,independent_cash_verified=True,exact_barriers_verified=True))
    result=dict(protocol_sha256=ph,completed=True,actual_paired_reducer_admission=True,
        funded_hypothetical_deposits=True,collection_quality_met=False,live_adaptive_service_implemented=False,
        release_7_to_10_percent_model=False,daily_fee_or_rewards_evaluated=False,production_approved=False,
        economics_validated=False,original_trial_state='failed',results=cases,artifacts_sha256=artifacts)
    write(root/'result.json',result)
    audit=dict(protocol_sha256=ph,result_sha256=sha(root/'result.json'),auditor_sha256=sha(root/'auditor-source.py'),
        passed=True,independent_external_review=False,production_approved=False,economics_validated=False,
        cases=checks,all_original_receipt_replays=40,all_native_responses_reexecuted=80)
    write(root/'audit.json',audit)
    return result,audit


class NativeEvidenceTests(unittest.TestCase):
    def test_complete_binding_does_not_promote_old_failed_quality_four_percent_trial(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp); fixture(p)
            got=native_evidence(p)
            self.assertEqual(got['independent_cash_cases'],4)
            self.assertEqual(got['cost_checks'],16)
            self.assertFalse(got['production_approved'])
            self.assertFalse(got['release_7_to_10_percent_model'])
            self.assertFalse(got['independent_external_review'])
            self.assertEqual(got['observed_capital'][0]['minimum_observed_cash_headroom_usdc_units'],249_999*USDC)
            self.assertFalse(got['observed_capital'][0]['stress_calibrated'])

    def test_observed_debt_cannot_be_funded_twice_or_hidden_by_a_smaller_peak_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp); result,audit=fixture(p)
            row=result['results'][0]; row['peak_exposure_usdc_units']=0
            write(p/'all_one-result.json',row)
            result['artifacts_sha256']['all_one-result.json']=sha(p/'all_one-result.json')
            write(p/'result.json',result); audit['result_sha256']=sha(p/'result.json'); write(p/'audit.json',audit)
            with self.assertRaisesRegex(ValueError,'observed capital differs'): native_evidence(p)
            path=p/'unfunded.jsonl'
            for exposure,debt in ((10,11),(11,10),(True,0)):
                write(path,dict(request=dict(kind='command',command=dict(kind='lp_fund')),
                    response=dict(ok=True,value=dict(lp=10,exposure=exposure,debt=debt))))
                with self.assertRaisesRegex(ValueError,'unfunded or invalid'): observed_capital(path,1)

    def test_partial_audit_or_relabelled_review_is_rejected(self):
        for change in (lambda a:a['cases'].pop(),
                       lambda a:a.update(independent_external_review=True),
                       lambda a:a['cases'][0].update(all_records_reexecuted=19)):
            with tempfile.TemporaryDirectory() as tmp:
                p=Path(tmp); _,audit=fixture(p); change(audit); write(p/'audit.json',audit)
                with self.assertRaises(ValueError): native_evidence(p)

    def test_auditor_snapshot_and_case_artifact_tampering_are_rejected(self):
        for name in ('auditor-source.py','all_three-state.json','source/engine/internal/engine/reducer.go'):
            with tempfile.TemporaryDirectory() as tmp:
                p=Path(tmp); fixture(p); (p/name).write_text('changed')
                with self.assertRaises(ValueError): native_evidence(p)

    def test_even_rebound_wrong_cash_or_missing_cost_grid_fails(self):
        for field,value in (('lp_gross_pnl_usdc_units',USDC),('cost_sensitivity',[])):
            with tempfile.TemporaryDirectory() as tmp:
                p=Path(tmp); result,audit=fixture(p)
                row=result['results'][0]; row[field]=value
                write(p/'all_one-result.json',row)
                result['artifacts_sha256']['all_one-result.json']=sha(p/'all_one-result.json')
                write(p/'result.json',result); audit['result_sha256']=sha(p/'result.json'); write(p/'audit.json',audit)
                with self.assertRaises(ValueError): native_evidence(p)


if __name__ == '__main__': unittest.main()
