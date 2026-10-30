from copy import deepcopy
from dataclasses import asdict
import json
import os
from pathlib import Path
import tempfile
import unittest

from release_pricing import (ASSETS, Counts, DELAYS, EDGES, GRID, PAYOUTS,
                             STRATEGIES, USDC, OracleTape, joint, replay, selected)
from research_release_pricing import (ROOT, child, complete, export_vectors,
                                      inventory, origin, price, sha, timestamp)


def tape(end=300_000, changes=None, disconnects=()):
    changes = changes or {}
    points = []
    current = 100*USDC
    for at in range(0, end, 1000):
        current = changes.get(at, current)
        points.append((at, current, current))
    return OracleTape(points, 0, end, disconnects)


class ReleasePricingTests(unittest.TestCase):
    def test_touch_is_a_loss_and_full_payout_includes_original_stake(self):
        source = tape(changes={40_000: 101*USDC})
        env = source.envelope(30_000, 0)
        counts, _, code = replay([env], 10_000_000, 100, 700)
        row = counts['all_offered'].result(100, 700)
        self.assertEqual(list(code), [2])
        self.assertEqual((row['accepted'], row['wins'], row['gross_lp_refund_usdc_units']), (1, 0, USDC))
        # One ppb wider makes the same full path survive and costs 99 stakes.
        counts, _, code = replay([env], 10_000_001, 100, 700)
        # Integer barriers still quantize to exactly one dollar at this width.
        self.assertEqual(list(code), [2])
        counts, _, code = replay([env], 10_000_010, 100, 700)
        self.assertEqual(list(code), [3])
        self.assertEqual(counts['all_offered'].result(100, 700)['gross_lp_refund_usdc_units'], -99*USDC)

    def test_price_roundtrip_invalidates_delayed_quote_even_if_final_price_matches(self):
        points = [(at, 100*USDC, 100*USDC) for at in range(0, 90_000, 1000)]
        points += [(30_050, 101*USDC, 101*USDC), (30_100, 100*USDC, 100*USDC)]
        source = OracleTape(sorted(points), 0, 90_000)
        row = source.envelope(30_000, 250)
        self.assertTrue(row['quote_available'])
        self.assertFalse(row['accepted'])
        self.assertEqual(row['reason'], 'oracle_sequence_changed')

    def test_same_price_refresh_keeps_quote_valid_and_ttl_boundary_is_strict(self):
        source = tape()
        for delay in (0, 250, 1000, 1999):
            self.assertTrue(source.envelope(30_000, delay)['accepted'])
        row = source.envelope(30_000, 2000)
        self.assertTrue(row['quote_available'])
        self.assertEqual(row['reason'], 'quote_expired')
        self.assertFalse(row['accepted'])

    def test_receipt_exactly_at_quote_is_not_used_until_after_action(self):
        source = tape(changes={30_000: 101*USDC})
        row = source.envelope(30_000, 0)
        self.assertEqual(row['entry'], 100*USDC)
        self.assertTrue(row['accepted'])
        later = source.envelope(30_000, 250)
        self.assertEqual(later['reason'], 'oracle_sequence_changed')

    def test_real_staleness_at_quote_and_no_price_substitution(self):
        source = OracleTape([(0, 100*USDC, 1000*USDC), (50_000, 100*USDC, 1000*USDC)], 0, 60_000)
        row = source.envelope(9000, 0)
        self.assertEqual(row['entry'], 100*USDC)
        self.assertFalse(row['quote_available'])
        self.assertEqual(row['reason'], 'missing_or_stale_quote_oracle')

    def test_future_disconnect_censors_outcome_without_leaking_into_entry(self):
        normal = tape()
        broken = tape(disconnects=[(59_000, 61_000)])
        a, b = normal.envelope(60_000, 0), broken.envelope(60_000, 0)
        for key in ('quote_available', 'accepted', 'entry', 'prior_state', 'mark_gap_ppm'):
            self.assertEqual(a[key], b[key])
        self.assertTrue(a['valid'])
        self.assertFalse(b['valid'])
        self.assertEqual(b['reason'], 'censored_gap_or_disconnect')

    def test_right_censoring_keeps_accepted_ticket_and_high_payout_bounds(self):
        source = tape(end=90_000)
        row = source.envelope(60_000, 250)
        self.assertTrue(row['accepted'])
        self.assertFalse(row['valid'])
        counts, _, codes = replay([row], 1_000_000, 10000, 850)
        result = counts['all_offered'].result(10000, 850)
        self.assertEqual(list(codes), [1])
        self.assertEqual((result['accepted'], result['censored']), (1, 1))
        self.assertEqual(result['gross_lp_if_censored_all_win_usdc_units'], -9999*USDC)
        self.assertEqual(result['gross_lp_if_censored_all_fail_usdc_units'], USDC)
        self.assertEqual(result['costs'][-1]['expense_usdc_units'], 10_000)

    def test_preentry_jump_rule_does_not_use_future_movement(self):
        quiet = tape()
        jump = tape(changes={61_000: 110*USDC})
        a, b = quiet.envelope(60_000, 0), jump.envelope(60_000, 0)
        self.assertFalse(selected('prior30_jump_100ppm', a, None))
        self.assertFalse(selected('prior30_jump_100ppm', b, None))
        self.assertTrue(b['observed_path_jump_100ppm'])
        self.assertEqual(a['prior_state'], b['prior_state'])

    def test_public_history_requires_expiry_plus_thirty_seconds(self):
        source = tape()
        rows = [source.envelope(q, 0) for q in (30_000, 60_000, 90_000)]
        counts, _, _ = replay(rows, 1_000_000, 2, 700)
        self.assertEqual(counts['last_matured_survived'].intended, 1)
        self.assertEqual(counts['last_matured_failed'].intended, 0)
        rows = [source.envelope(q, 250) for q in (30_000, 60_000, 90_000)]
        counts, _, _ = replay(rows, 1_000_000, 2, 700)
        self.assertEqual(counts['last_matured_survived'].intended, 0)

    def test_censored_or_unaccepted_opportunities_never_publish_clean_labels(self):
        source = tape(disconnects=[(40_000, 41_000)])
        rows = [source.envelope(q, 0) for q in (30_000, 60_000, 90_000)]
        counts, _, _ = replay(rows, 1_000_000, 2, 700)
        self.assertEqual(counts['last_matured_survived'].intended, 0)
        rows = [tape().envelope(q, 2000) for q in (30_000, 60_000, 90_000)]
        counts, _, _ = replay(rows, 1_000_000, 2, 700)
        self.assertEqual(counts['all_offered'].rejected, 3)
        self.assertEqual(counts['all_offered'].accepted, 0)
        self.assertEqual(counts['last_matured_survived'].intended, 0)

    def test_joint_path_patterns_refusals_and_wallet_scaling_preserve_denominators(self):
        states = [bytearray((3, 2, 1, 0)), bytearray((3, 3, 2, 2)), bytearray((3, 2, 2, 3))]
        row = joint(states, 100)
        self.assertEqual((row['grid'], row['coaccepted'], row['coresolved']), (4, 3, 2))
        self.assertEqual(row['clean_coaccepted_win_count_histogram'], [0, 1, 0, 1])
        self.assertEqual((row['accepted_tickets'], row['resolved_tickets'], row['censored_tickets']), (11, 10, 1))
        self.assertEqual(row['trader_wins'], 5)
        self.assertEqual(row['gross_lp_refund_usdc_units'], -490*USDC)
        self.assertEqual(row['three_wallets_per_asset']['gross_lp_refund_usdc_units'], -1470*USDC)
        self.assertFalse(row['shared_paths_independent'])

    def test_decimal_timestamp_and_raw_path_safety(self):
        self.assertEqual(price('1.000001'), 1_000_001)
        for value in ('1.0000001', '1e3', '-1', '0', 'nan', 1.0):
            with self.assertRaises(ValueError):
                price(value)
        self.assertEqual(timestamp('2026-01-01T00:00:00.1234567Z'), origin('2026-01-01')+123)
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                child(tmp, '../outside')

    def test_complete_day_selection_rejects_partial_duplicate_and_unavailable_slices(self):
        day = '2026-01-01'
        files = [dict(at_ms=origin(day)+i*600_000, duration_ms=600_000, status='downloaded') for i in range(144)]
        self.assertTrue(complete(files, day))
        self.assertFalse(complete(files[:-1], day))
        self.assertFalse(complete(files+[files[-1]], day))
        changed = deepcopy(files)
        changed[1]['status'] = 'error'
        self.assertFalse(complete(changed, day))

    def test_raw_inventory_rejects_manifest_protocol_tampering(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            protocol = root/'download-protocol.json'
            protocol.write_text(json.dumps(dict(requests=[])))
            (root/'download-manifest.json').write_text(json.dumps(dict(protocol_sha256=sha(protocol), files=[])))
            inventory(root)
            protocol.write_text(json.dumps(dict(requests=[], extra=True)))
            with self.assertRaisesRegex(ValueError, 'binding'):
                inventory(root)

    def test_native_research_export_parity_for_all_108_release_vectors(self):
        binary = os.environ.get('FUSE_RELEASE_PRICING_BINARY')
        if not binary:
            self.skipTest('set FUSE_RELEASE_PRICING_BINARY for all 108 cross-language vectors')
        rows = export_vectors(Path(binary))
        self.assertEqual(len(rows), 108)
        self.assertEqual({r['house_edge_bps'] for r in rows}, set(EDGES))
        self.assertEqual({r['asset'] for r in rows}, set(ASSETS))
        self.assertEqual({r['multiplier'] for r in rows}, set(PAYOUTS))


if __name__ == '__main__':
    unittest.main()
