from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from replay_lp_economics import Bridge,DEFAULT_COSTS
from single_stage_economics import Replay,PROFILES,intends
from test_native_adaptive_data import receipts

ROOT=Path(__file__).resolve().parent.parent


class SingleStageEconomicsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory(prefix='fuse-single-stage-tests-')
        cls.binary=Path(cls.temp.name)/'fuse-research'
        env=dict(os.environ,GOCACHE='/private/tmp/fuse-go-cache')
        subprocess.run(['go','build','-o',str(cls.binary),'./cmd/fuse-research'],cwd=ROOT/'engine',env=env,check=True)
        cls.policy=json.loads((ROOT/'engine/config/paper.json').read_text())

    @classmethod
    def tearDownClass(cls):cls.temp.cleanup()

    def replay(self,profile=0,missing=(),volatility=1000):
        raw=receipts(missing=missing)
        for p in raw:p['at']+=1000000
        policy=deepcopy(self.policy);policy['model']['dnt']['volatility_30s_ppm']=volatility
        bridge=Bridge(self.binary)
        try:return Replay(bridge,policy,raw,1000000,1900000,PROFILES[profile],2,DEFAULT_COSTS).run()
        finally:bridge.close()

    def test_strategy_is_preentry_only_and_recovery_fee_projection_is_rejected(self):
        row=dict(adaptive_features={},activity_state='frozen',valid=False,move=999999)
        changed=dict(row,valid=True,move=0)
        for profile in PROFILES:self.assertEqual(intends(row,profile),intends(changed,profile))
        self.assertFalse(intends(dict(row,adaptive_features=None),PROFILES[0]))
        self.assertFalse(intends(dict(row,activity_state='active'),PROFILES[1]))
        policy=dict(self.policy,recovery={})
        with self.assertRaisesRegex(ValueError,'fee/recovery projection'):
            Replay(None,policy,[],1000000,1900000,PROFILES[0],2,DEFAULT_COSTS)

    def test_actual_go_presets_conserve_and_correlated_accounts_share_paths(self):
        one,state=self.replay();three,cohort=self.replay(profile=2)
        # The first five-minute lookback includes the censored startup window;
        # clean history becomes available at 330s, not at 300s.
        self.assertEqual(one['accepted_stages'],19);self.assertEqual(three['accepted_stages'],57)
        self.assertEqual(three['lp_trading_pnl_usdc_units'],3*one['lp_trading_pnl_usdc_units'])
        self.assertEqual(three['peak_total_exposure_usdc_units'],3*one['peak_total_exposure_usdc_units'])
        self.assertTrue(three['conservation_verified']);self.assertFalse(three['healthy_outcome_mismatches'])
        self.assertEqual(three['terminal_exposure_usdc_units'],0);self.assertEqual(three['terminal_debt_usdc_units'],0)
        for start in {s['start'] for s in cohort['stages'].values()}:
            stages=[s for s in cohort['stages'].values() if s['start']==start]
            self.assertEqual(len(stages),3);self.assertEqual(len({s['status'] for s in stages}),1)

    def test_future_outage_censors_outcome_without_deleting_a_healthy_entry(self):
        result,state=self.replay(missing=range(455000,475000,1000))
        stage=next(s for s in state['stages'].values() if s['start']==1450000)
        self.assertEqual(stage['status'],'voided')
        self.assertGreater(result['outcomes'].get('voided',0),0)
        self.assertTrue(result['zero_terminal_active']);self.assertTrue(result['conservation_verified'])

    def test_profit_fees_use_contract_model_and_preserve_funded_cash(self):
        result,state=self.replay(volatility=1)
        self.assertGreater(result['lp_trading_pnl_usdc_units'],0)
        self.assertGreater(result['reserve_fee_accrued_usdc_units'],0)
        self.assertEqual(result['lp_terminal']['cash'],250000000000+result['lp_trading_pnl_usdc_units'])
        self.assertEqual(result['lp_terminal']['assets'],result['lp_terminal']['cash']-result['reserve_fee_accrued_usdc_units'])
