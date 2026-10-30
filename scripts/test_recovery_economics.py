from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from prepare_recovery_research import prepare,ROOT
from recovery_economics import Replay
from single_stage_economics import Replay as CapitalReplay,PROFILES
from replay_lp_economics import Bridge,DEFAULT_COSTS
from test_native_adaptive_data import receipts


class RecoveryEconomicsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory(prefix='fuse-recovery-economics-tests-')
        root=Path(cls.temp.name);report=prepare(root/'isolated')
        cls.binary=root/'isolated/fuse-research-v2';cls.old=root/'old-bridge'
        env=dict(os.environ,GOCACHE='/private/tmp/fuse-go-cache')
        subprocess.run([report['go'],'build','-o',str(cls.old),'./cmd/fuse-research'],cwd=ROOT/'engine',env=env,check=True)
        cls.policy=json.loads((ROOT/'engine/config/paper-recovery.json').read_text())
        cls.raw=receipts()
        for p in cls.raw:p['at']+=1000000

    @classmethod
    def tearDownClass(cls):cls.temp.cleanup()

    def replay(self,policy,multiplier=2,binary=None,capital=False):
        bridge=Bridge(binary or self.binary)
        try:
            klass=CapitalReplay if capital else Replay
            return klass(bridge,policy,self.raw,1000000,1900000,PROFILES[0],multiplier,DEFAULT_COSTS).run()
        finally:bridge.close()

    def test_old_bridge_is_rejected_and_no_recovery_control_matches_original(self):
        with self.assertRaisesRegex(ValueError,'fee-aware v2'):self.replay(self.policy,binary=self.old)
        policy=deepcopy(self.policy);policy.pop('recovery')
        old,old_state=self.replay(policy,binary=self.old,capital=True)
        new,new_state=self.replay(policy)
        self.assertEqual(old_state,new_state)
        for field in ('outcomes','lp_trading_pnl_usdc_units','reserve_fee_accrued_usdc_units','peak_total_exposure_usdc_units'):
            self.assertEqual(old[field],new[field])

    def test_risk_controller_limits_losses_and_preserves_refusal_denominators(self):
        result,state=self.replay(self.policy)
        self.assertEqual(result['outcomes'],{'survived':15})
        self.assertEqual(result['quote_attempts'],19);self.assertEqual(result['accepted_stages'],15)
        self.assertEqual(result['recovery_final']['pnl'],-15000000)
        self.assertEqual(result['recovery_final']['mode'],'paused')
        self.assertEqual(result['lp_trading_pnl_usdc_units'],-15000000)
        self.assertEqual(result['rejected_actions']['quote: command rejected: recovery cooldown'],4)
        self.assertEqual(result['terminal_exposure_usdc_units'],0)

    def test_high_payout_can_have_zero_availability_before_any_risk(self):
        result,state=self.replay(self.policy,multiplier=10000)
        self.assertEqual(result['quote_attempts'],19);self.assertEqual(result['accepted_stages'],0)
        self.assertEqual(result['lp_trading_pnl_usdc_units'],0)
        self.assertEqual(result['rejected_actions']['quote: command rejected: rolling 24h loss budget'],19)
        self.assertIsNone(result['survival'])

    def test_positive_profit_fee_debits_recovery_once_and_reconciles(self):
        policy=deepcopy(self.policy);policy['model']['dnt']['volatility_30s_ppm']=1
        result,state=self.replay(policy)
        self.assertGreater(result['reserve_fee_accrued_usdc_units'],0)
        self.assertEqual(result['recovery_final']['pnl'],result['lp_trading_pnl_usdc_units']-result['reserve_fee_accrued_usdc_units'])
        self.assertEqual(sum(c['fee_delta'] for c in result['fee_projection_checks']),result['reserve_fee_accrued_usdc_units'])
        self.assertTrue(result['fee_projection_verified']);self.assertTrue(result['conservation_verified'])
