from copy import deepcopy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from analyze_capture import windows
from replay_lp_economics import Bridge
from research_adaptive_native_ppb import GRID, ROOT, Replay, fixed_policy, sha, verify, write
from research_release_pricing import verify_plan


class NativePPBTests(unittest.TestCase):
    def test_adapter_has_explicit_single_payout_and_does_not_modify_frozen_policy(self):
        source = json.loads((ROOT/'engine/config/paper.json').read_text())
        original = deepcopy(source)
        policy = fixed_policy(source)
        self.assertEqual(source, original)
        self.assertEqual(policy['multipliers'], [2])
        self.assertEqual(policy['model']['multiplier_widths_ppb'], {'2': 1000})
        self.assertNotIn('dnt', policy['model'])
        self.assertNotIn('markets', policy)
        self.assertNotIn('recovery', policy)

    def test_archived_pricing_verification_distinguishes_current_drift_from_snapshot_tampering(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            live, packet = root/'live', root/'packet'
            live.mkdir(); (packet/'source').mkdir(parents=True)
            (live/'code.py').write_text('old')
            (packet/'source/code.py').write_text('old')
            (packet/'native-vectors.json').write_text('[]')
            (root/'binary').write_text('binary')
            write(packet/'protocol.json', dict(source_sha256={'code.py':sha(live/'code.py')}, catalogs=[],
                native_binary=str(root/'binary'), native_binary_sha256=sha(root/'binary'),
                native_vectors_sha256=sha(packet/'native-vectors.json')))
            write(packet/'freeze.json', dict(protocol_sha256=sha(packet/'protocol.json')))
            with patch('research_release_pricing.ROOT', live):
                verify_plan(packet)
                (live/'code.py').write_text('new')
                with self.assertRaisesRegex(ValueError, 'source changed'):
                    verify_plan(packet)
                verify_plan(packet, require_current_sources=False)
                (packet/'source/code.py').write_text('tampered')
                with self.assertRaisesRegex(ValueError, 'source changed'):
                    verify_plan(packet, require_current_sources=False)

    def test_native_packet_tampered_protocol_fails_before_opening_inputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write(root/'protocol.json', dict(source_sha256={}))
            write(root/'freeze.json', dict(protocol_sha256=sha(root/'protocol.json')))
            (root/'protocol.json').write_text('{}')
            with self.assertRaisesRegex(ValueError, 'protocol changed'):
                verify(root)

    def native_replay(self, accounts=1, outage=False):
        binary = os.environ.get('FUSE_NATIVE_PPB_BINARY')
        if not binary:
            self.skipTest('set FUSE_NATIVE_PPB_BINARY to run exact native adapter fixtures')
        policy = fixed_policy(json.loads((ROOT/'engine/config/paper.json').read_text()))
        start, end = 1_000_000, 1_000_000+4*GRID
        receipts = []
        for at in range(start+1, end, 1000):
            if outage and at >= start+GRID:
                break
            price = '100000' if at < start+2*GRID else '100001'
            for source in ('a','b'):
                receipts.append(dict(at=at, source=source, raw=dict(channel='activeAssetCtx',
                    data=dict(coin='BTC',ctx=dict(oraclePx=price)))))
        rows = {r['start']:r for r in windows(iter(receipts), policy, start, end)}
        quotes, decisions = {}, {}
        for at, row in rows.items():
            selected = at in (start+GRID, start+2*GRID) and (not outage or at == start+GRID)
            width = 1 if at == start+GRID else 8
            quotes[at] = dict(width_ppm=width if selected else None, paused=False,
                shadow_survived=(row['move'] < row['entry']*width//1_000_000) if row['valid'] else None)
            decisions[at] = dict(strategies=['all_offered'] if selected else [])
        plan = dict(start_ms=start, duration_ms=end-start, settlement_interval_ms=300_000,
            initial_lp_usdc_units=250_000_000_000, customer_deposit_usdc_units=1_000_000_000,
            stake_usdc_units=1_000_000)
        bridge = Bridge(Path(binary))
        try:
            return Replay(bridge, policy, plan, dict(name='fixture',strategy='all_offered',accounts=accounts),
                receipts, quotes, decisions, rows).run()
        finally:
            bridge.close()

    def test_exact_native_one_ppm_win_then_eight_ppm_touch_and_cash_conservation(self):
        result, state = self.native_replay()
        self.assertEqual(result['outcomes'], {'survived':1, 'exploded':1})
        self.assertEqual(result['healthy_outcome_comparisons'], 2)
        self.assertEqual(result['lp_gross_pnl_usdc_units'], 0)
        self.assertEqual(result['exact_width_policy_injections'], 1)
        self.assertEqual(state['lp'], 250_000_000_000)
        self.assertEqual(sorted(s['terms']['width_ppb'] for s in state['stages'].values()), [1000,8000])

    def test_synchronized_native_accounts_have_shared_outcomes_and_triple_exposure(self):
        result, _ = self.native_replay(accounts=3)
        self.assertEqual(result['outcomes'], {'survived':3, 'exploded':3})
        self.assertEqual(result['accepted_stages'], 6)
        # The earlier 3m winning debt remains reserved while the next three
        # bets add another 3m. Simultaneous account paths are not diversified.
        self.assertEqual(result['peak_exposure_usdc_units'], 6_000_000)
        self.assertEqual(result['peak_unfunded_debt_usdc_units'], 3_000_000)
        self.assertEqual(result['accepted_turnover_usdc_units'], 6_000_000)

    def test_native_future_outage_voids_without_synthetic_terminal_price(self):
        result, state = self.native_replay(outage=True)
        self.assertEqual(result['outcomes'], {'voided':1})
        self.assertEqual(result['healthy_outcome_comparisons'], 0)
        self.assertEqual(result['accepted_censored_path_stages'], 1)
        self.assertEqual(result['lp_gross_pnl_usdc_units'], 0)
        self.assertEqual(state['accounts']['trader-0']['available'], 1_000_000_000)


if __name__ == '__main__':
    unittest.main()
