from datetime import datetime, timezone
from pathlib import Path
import tempfile
import gzip
import unittest
from unittest.mock import patch

from probe_oxarchive_liquidity import Client, NoRedirect, decode_payload, load_key, next_cursor, quality, stamp, validate, windows


class OxarchiveLiquidityTests(unittest.TestCase):
    def test_pagination_does_not_infer_completion_from_short_page(self):
        self.assertEqual(next_cursor(dict(meta=dict(request_id='abc',has_more=True,next_cursor=42)),None),42)
        self.assertIsNone(next_cursor(dict(meta=dict(request_id='abc',has_more=False)),42))
        for meta in (dict(request_id='abc',has_more=True,next_cursor=42),
                     dict(request_id='abc'),dict(has_more=False)):
            with self.assertRaises(ValueError):next_cursor(dict(meta=meta),42)

    def test_sparse_oracle_is_not_filled_forward_or_interpolated(self):
        start=1793059200000
        values=quality(list(range(start,start+3600001,60000)),start,start+3600000,8000)
        self.assertEqual(values['median_gap_ms'],60000)
        self.assertEqual(values['prior_source_fresh_grid_fraction'],0)
        dense=quality(list(range(start,start+3600001,1000)),start,start+3600000,8000)
        self.assertEqual(dense['prior_source_fresh_grid_fraction'],1)

    def test_entry_equality_is_excluded(self):
        start=1793059200000
        self.assertEqual(quality([start+30000],start,start+60000,5000)['prior_source_fresh_grid_fraction'],0)
        self.assertEqual(quality([start+29999],start,start+60000,5000)['prior_source_fresh_grid_fraction'],1)

    def test_wrong_asset_node_source_and_invalid_oracle_rejected(self):
        start=1793059200000
        for row,kind in ((dict(symbol='BTC',timestamp=start,oracle_price='2'),'oracle_context'),
                         (dict(symbol='ETH',timestamp=start,oracle_price='NaN'),'oracle_context'),
                         (dict(symbol='ETH',timestamp=start,source='node'),'books')):
            with self.assertRaises(ValueError):validate([row],'ETH',kind,start,start+60000)
        self.assertEqual(validate([dict(symbol='ETH',timestamp=start,oracle_price='2')],
                                  'ETH','oracle_context',start,start+60000),[start])

    def test_fixed_samples_include_both_calendar_types_in_free_window(self):
        now=datetime(2026,10,28,18,tzinfo=timezone.utc)
        selected=windows(now)
        self.assertEqual(len(selected),4)
        dates=[datetime.fromtimestamp(v/1000,timezone.utc) for v in selected]
        self.assertEqual({d.hour for d in dates},{0,12})
        self.assertEqual({d.weekday()>=5 for d in dates},{True,False})
        self.assertTrue(all(0<(now-d).total_seconds()<7*86400 for d in dates))

    def test_missing_key_and_budget_stop_before_network(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict('os.environ',{},clear=True):
            path=Path(tmp)/'key.env'
            with self.assertRaises(ValueError):load_key(path)
            path.write_text('OXARCHIVE_API_KEY=example-test-value\n')
            self.assertEqual(load_key(path),'example-test-value')
        client=Client('example-test-value',max_requests=0)
        with patch.object(client.opener,'open') as request:
            with self.assertRaises(ValueError):client.get('/v1/hyperliquid/orderbook/ETH/history',{})
            request.assert_not_called()
        self.assertIsNone(NoRedirect().redirect_request(None,None,302,'',{},'https://example.com'))

    def test_timestamp_units_and_timezone_are_required(self):
        self.assertEqual(stamp('2026-10-27T00:00:00Z'),1793059200000)
        for value in (True,1793059200,'2026-10-27T00:00:00'):
            with self.assertRaises(ValueError):stamp(value)

    def test_gzip_transport_has_independent_encoded_and_decoded_bounds(self):
        body=b'{"success":true}'
        self.assertEqual(decode_payload(gzip.compress(body),'gzip'),body)
        self.assertEqual(decode_payload(body,''),body)
        with self.assertRaisesRegex(ValueError,'Decoded'):
            decode_payload(gzip.compress(b'x'*8000001),'gzip')
        with self.assertRaisesRegex(ValueError,'Encoded'):
            decode_payload(b'x'*8000001,'')


if __name__=='__main__':unittest.main()
