import json
import os
from pathlib import Path
import tempfile
import unittest

from contract_lp_model import LPModel, USDC, DAY, BUDGET, scheduled_budget
from generate_lp_model_vectors import render
from replay_lp_economics import choose_wallets, cost_sensitivity, Bridge, Replay, verify_audit, DEFAULT_COSTS

ROOT = Path(__file__).resolve().parent.parent


class ContractLPTests(unittest.TestCase):
    def model(self):
        m = LPModel(1000)
        m.deposit('protocol', 200000*USDC)
        m.finalize(0, 100*USDC, 0)
        m.set_phase(1)
        m.set_phase(2)
        m.publish_capacity(50000*USDC, m.now+3600)
        m.deposit('alice', 50000*USDC)
        return m

    def test_generated_contract_vectors_are_current(self):
        self.assertEqual((ROOT/'test/fixtures/LPModelVectors.sol').read_text(), render())

    def test_linear_schedule_is_exact_and_not_old_half_life(self):
        budgets = [scheduled_budget(i) for i in range(1,91)]
        self.assertEqual(sum(budgets), BUDGET)
        self.assertTrue(all(a > b for a,b in zip(budgets,budgets[1:])))
        self.assertEqual(scheduled_budget(0), 0)
        self.assertEqual(scheduled_budget(91), 0)
        self.assertEqual(budgets[0], BUDGET*179//8100)

    def test_claimable_exit_is_not_underwriting_and_payment_preserves_nav(self):
        m = self.model()
        request = m.request_exit('alice', m.shares['alice'])
        m.clock(m.start+2*DAY)
        with self.assertRaises(ValueError):
            m.fulfill(request)  # older checkpoint, despite elapsed delay
        m.finalize(-10000*USDC, 100*USDC, 0)
        self.assertEqual(m.fulfill(request), 48000*USDC)
        self.assertEqual(m.assets, 192000*USDC)
        self.assertEqual(m.cash, 240000*USDC)
        before = m.assets
        m.claim_exit(request, assets=1)
        m.claim_exit(request)
        self.assertEqual(m.assets, before)
        self.assertEqual(m.reserved, 0)
        self.assertEqual(m.paid_exits, 48000*USDC)

    def test_pending_and_protocol_shares_cannot_earn_rewards(self):
        m = self.model()
        m.request_exit('alice', m.shares['alice'])
        m.clock(m.start+DAY)
        m.liability_seconds[1] = 250000*USDC*DAY//5
        m.resume()
        self.assertGreater(m.publish(1), 0)
        self.assertEqual(m.earned(1,'alice'), 0)
        self.assertEqual(m.earned(1,'protocol'), 0)
        self.assertEqual(m.earned(1,'vault'), 0)

    def test_epoch_end_vesting_publication_deadline_and_dedup(self):
        m = self.model()
        m.clock(m.start+DAY)
        m.liability_seconds[1] = 250000*USDC*DAY//5
        m.resume()
        m.publish(1)
        earned = m.earned(1,'alice')
        self.assertGreater(earned, 0)
        m.clock(m.start+31*DAY-1)
        with self.assertRaises(ValueError): m.claim_reward(1,'alice')
        m.clock(m.start+31*DAY)
        self.assertEqual(m.claim_reward(1,'alice'), earned)
        with self.assertRaises(ValueError): m.claim_reward(1,'alice')
        with self.assertRaises(ValueError): m.publish(2)

    def test_no_utilization_never_creates_rewards(self):
        m = self.model()
        m.clock(m.start+DAY)
        m.resume()
        self.assertEqual(m.publish(1), 0)
        self.assertEqual(m.earned(1,'alice'), 0)

    def test_fee_funding_segregates_cash_and_preserves_equity(self):
        m = self.model()
        m.finalize(10000*USDC, 100*USDC, 0)
        self.assertEqual(m.fee,3500*USDC)
        equity = m.assets
        m.resume()
        m.fund_reserve(m.fee)
        self.assertEqual(m.assets, equity)
        m.finalize(-5000*USDC, 100*USDC, 0)
        m.publish_capacity(60000*USDC,m.now+3600)
        m.deposit('bob',1000*USDC)
        m.finalize(4000*USDC,100*USDC,0)
        self.assertEqual(m.fee,0)

    def test_capital_buffer_and_fifo_fail_closed(self):
        m = self.model()
        m.publish_capacity(100000*USDC,m.now+3600)
        m.deposit('bob',10000*USDC)
        a=m.request_exit('alice',m.shares['alice'])
        b=m.request_exit('bob',m.shares['bob'])
        m.clock(m.start+2*DAY)
        m.finalize(0,110000*USDC,0)
        with self.assertRaises(ValueError):m.fulfill(b)
        with self.assertRaises(ValueError):m.fulfill(a)
        m.finalize(0,100*USDC,0)
        m.fulfill(a)
        m.fulfill(b)
        m.check()

    def test_stale_capacity_or_open_exposure_blocks_deposit(self):
        m=self.model()
        m.clock(m.now+3601)
        self.assertEqual(m.max_deposit('bob'),0)
        m.finalize(0,100*USDC,1)
        m.publish_capacity(100000*USDC,m.now+3600)
        self.assertEqual(m.max_deposit('bob'),0)
        with self.assertRaises(ValueError):m.finalize(0,0,1)

    def test_resume_or_generic_pause_invalidates_settlement_window(self):
        m=self.model()
        m.resume()
        m.pause()
        m.publish_capacity(100000*USDC,m.now+3600)
        self.assertEqual(m.max_deposit('bob'),0)
        m.finalize(0,100*USDC,0)
        self.assertGreater(m.max_deposit('bob'),0)
        m.clock(m.start+DAY)
        with self.assertRaises(ValueError):m.publish(1)
        m.resume()
        m.publish(1)

    def test_demand_is_nested_wallet_attrition_not_new_cash_or_outcomes(self):
        wallets = {str(i) for i in range(300)}
        half=choose_wallets(wallets,5000)
        tenth=choose_wallets(wallets,1000)
        self.assertEqual(len(half),150)
        self.assertEqual(len(tenth),30)
        self.assertLessEqual(tenth,half)
        self.assertEqual(choose_wallets(wallets,0),set())
        self.assertEqual(choose_wallets(wallets,10000),wallets)

    def test_cost_allocation_uses_decimal_units_and_not_share_nav(self):
        costs=[dict(name='example',gas_price_gwei='1',native_usd='50',operating_usd_per_day='100')]
        row=cost_sensitivity({'settlement':2},43200.0,100*USDC,35*USDC,costs)[0]
        self.assertEqual(row['assumed_gas_cost_usdc_units'],25000)
        self.assertEqual(row['assumed_operating_cost_usdc_units'],50*USDC)
        self.assertEqual(row['lp_profit_after_fee_and_allocated_cost_usdc_units'],14975000)


@unittest.skipUnless(os.environ.get('FUSE_RESEARCH_BINARY'),'set FUSE_RESEARCH_BINARY for offline Go bridge integration')
class BridgeTests(unittest.TestCase):
    def test_full_recorded_action_adapter_through_fee_funding_and_runoff(self):
        # A tiny synthetic adapter fixture, not market evidence. Actual Go
        # quotes/stages supply IDs and terms; confirmed effects feed the adapter.
        binary=Path(os.environ['FUSE_RESEARCH_BINARY'])
        p=json.loads((ROOT/'engine/testdata/legacy-ladder-policy.json').read_text())
        p['model'].update(base_width_bps=1,control_width_bps=1,volatility_factor=0)
        source=Bridge(binary)
        rows=[]
        serial=0

        def command(kind,**kwargs):
            nonlocal serial
            serial+=1
            c=dict(kind=kind,key=str(serial),at=1000000+serial*1000,**kwargs)
            v=source.send(dict(kind='command',command=c))['value']
            return dict(command=c,result=v.get('result'))

        def effects(values):
            return dict(command=dict(kind='local_block',at=1000000+serial*1000,raw=dict(effects=values)))

        try:
            source.send(dict(kind='init',policy=p))
            source.send(dict(kind='sync_lp',cash=250000*USDC,fee=0,exit=0))
            command('deposit',actor='alice',id='1',amount=1000*USDC)
            command('ack_deposit',id='1')
            rows.append(effects([dict(module='CustomerCustodyVault',event='Deposited',id='1',account='alice',amount=1000*USDC),
                                 dict(module='CustomerCustodyVault',event='DepositCredited',id='1')]))
            raw=lambda price:dict(channel='activeAssetCtx',data=dict(coin='BTC',ctx=dict(oraclePx=price)))
            for receiver in ('a','b'):rows.append(command('oracle',source=receiver,raw=raw('80000')))
            q=command('quote',actor='alice',amount=100*USDC)
            rows.append(q)
            rows.append(command('enter',actor='alice',id=q['result']['id']))
            for receiver in ('a','b'):rows.append(command('oracle',source=receiver,raw=raw('80008')))
            command('paper_settle')
            rows.append(effects([dict(module='SettlementController',event='CheckpointFinalized')]))
            original=source.send(dict(kind='snapshot'))['value']
        finally:source.close()
        with tempfile.TemporaryDirectory() as temporary:
            directory=Path(temporary)/'case/evidence'
            directory.mkdir(parents=True)
            (directory/'initial-policy.json').write_text(json.dumps(p))
            (directory/'final-state.json').write_text(json.dumps(original))
            (directory/'journal.jsonl').write_text(''.join(json.dumps(row)+'\n' for row in rows))
            bridge=Bridge(binary)
            try:
                replay=Replay(bridge,directory,10000,DEFAULT_COSTS)
                result=replay.run()
            finally:bridge.close()
            self.assertEqual(result['lp_trading_pnl_usdc_units'],100*USDC)
            self.assertEqual(result['final']['reserve'],35*USDC)
            self.assertEqual(result['final']['fee'],0)
            self.assertTrue(result['funded_exit_claims'])
            self.assertEqual(result['recorded_outcome_mismatches'],[])
            self.assertEqual(result['recorded_term_mismatches'],[])
            self.assertEqual(result['accepted_stages'],1)
            self.assertGreater(int(result['lp_reward_claimed_units']),0)

    def test_recorded_oracle_drives_settlement_and_fee_excludes_next_admission(self):
        p=json.loads((ROOT/'engine/testdata/legacy-ladder-policy.json').read_text())
        p['model'].update(base_width_bps=1,control_width_bps=1,volatility_factor=0)
        b=Bridge(Path(os.environ['FUSE_RESEARCH_BINARY']))
        m=LPModel(1000)
        m.deposit('protocol',250000*USDC)
        m.finalize(0,100*USDC,0)
        m.set_phase(1)
        serial=0

        def command(kind,**kwargs):
            nonlocal serial
            serial+=1
            return b.send(dict(kind='command',command=dict(key=str(serial),kind=kind,at=1000000,**kwargs)))['value']

        try:
            b.send(dict(kind='init',policy=p))
            b.send(dict(kind='sync_lp',cash=m.cash,fee=0,exit=0))
            command('deposit',actor='alice',id='d',amount=1000*USDC)
            command('ack_deposit',id='d')
            raw=lambda price:dict(channel='activeAssetCtx',data=dict(coin='BTC',ctx=dict(oraclePx=price)))
            for source in ('a','b'):command('oracle',source=source,raw=raw('80000'))
            q=command('quote',actor='alice',amount=100*USDC)['result']
            command('enter',actor='alice',id=q['id'])
            # Exact upper-bound touch must lose, using oraclePx, without BBO.
            for source in ('a','b'):command('oracle',source=source,raw=raw('80008'))
            v=command('paper_settle')
            self.assertEqual(v['lp_profit'],100*USDC)
            m.finalize(v['lp_profit'],v['result']['required_lp'],v['exposure'])
            self.assertEqual(m.fee,35*USDC)
            b.send(dict(kind='sync_lp',cash=m.cash,fee=m.fee,exit=0))
            # Projected fee cannot be treated as available underwriting cash.
            bad=b.send(dict(kind='sync_lp',cash=35*USDC-1,fee=m.fee,exit=0),allow_reject=True)
            self.assertFalse(bad['ok'])
            state=b.send(dict(kind='snapshot'))['value']
            self.assertEqual(next(iter(state['stages'].values()))['status'],'exploded')
        finally:b.close()

    def test_audit_replays_rejections_and_detects_tampering(self):
        p=json.loads((ROOT/'engine/testdata/legacy-ladder-policy.json').read_text())
        binary=Path(os.environ['FUSE_RESEARCH_BINARY'])
        with tempfile.TemporaryDirectory() as temporary:
            path=Path(temporary)/'audit.jsonl'
            with path.open('w') as audit:
                b=Bridge(binary,audit)
                try:
                    b.send(dict(kind='init',policy=p))
                    b.send(dict(kind='sync_lp',cash=100,fee=200,exit=0),allow_reject=True)
                    b.send(dict(kind='sync_lp',cash=100,fee=20,exit=30))
                finally:b.close()
            verify_audit(binary,path)
            data=path.read_text().replace('"cash":100','"cash":101',1)
            path.write_text(data)
            with self.assertRaisesRegex(ValueError,'hash mismatch'):verify_audit(binary,path)


if __name__=='__main__':unittest.main()
