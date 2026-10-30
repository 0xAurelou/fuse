import gzip
import json
from pathlib import Path
import tempfile
import unittest

from capture_dataset import file_hash
from research_raw_flat_panels import flat_stretches, parse_raw, prepare_rows


class RawFlatTests(unittest.TestCase):
    def test_seven_digit_timestamp_floor_and_disconnect_marker_position(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            body = json.dumps(dict(channel='activeAssetCtx', data=dict(coin='BTC', ctx=dict(oraclePx='100.123456'))))
            text = f'2025-01-01T00:00:00.1234567Z {body}\n\n2025-01-01T00:00:01.9999999Z {body}\n'
            path = root / 'minute.bin'
            path.write_bytes(gzip.compress(text.encode()))
            minute = dict(path=path.name, status='downloaded', sha256=file_hash(path), at_ms=1735689600000)
            observed, markers = parse_raw([minute], root)
            self.assertEqual([at - minute['at_ms'] for at, _ in observed], [123, 1999])
            self.assertEqual(markers[0]['known_at'], minute['at_ms'] + 1999)
            self.assertEqual(observed[0][1], 100123456)
            path.write_bytes(b'changed')
            with self.assertRaises(ValueError):
                parse_raw([minute], root)

    def test_disconnect_censors_outcome_without_retroactive_history_rejection(self):
        observed = [(at, 100_000_000) for at in range(0, 720_000, 1000)]
        panel = dict(fetch_start=0, fetch_end=720_000, day='test')
        rows = prepare_rows(observed, panel, [dict(known_at=365_000)])
        entry = next(r for r in rows if r['start'] == 360_000)
        later = next(r for r in rows if r['start'] == 390_000)
        self.assertFalse(entry['valid'])
        self.assertIsNotNone(entry['adaptive_features'])
        self.assertIsNone(later['adaptive_features'])

    def test_flat_spans_do_not_bridge_price_changes_gaps_or_disconnects(self):
        observed = [(at, 100) for at in range(0, 41_000, 1000)]
        self.assertEqual(flat_stretches(observed)[0]['duration_ms'], 40_000)
        self.assertEqual(flat_stretches(observed, [dict(known_at=20_000)]), [])
        gapped = [p for p in observed if not 15_000 <= p[0] < 26_000]
        self.assertEqual(flat_stretches(gapped), [])
        changed = [(at, 100 if at < 20_000 else 101) for at, _ in observed]
        self.assertEqual(flat_stretches(changed), [])


if __name__ == '__main__':
    unittest.main()
