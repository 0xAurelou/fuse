from datetime import datetime,timezone
import gzip
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs,urlsplit

from fetch_tardis_liquidity_trial import ASSETS,CHANNELS,DATES,decode,declare,load_key,origin,request_url


class TardisTrialTests(unittest.TestCase):
    def test_only_selected_assets_channels_and_dates_are_requested(self):
        url=request_url('2026-09-02',10)
        parts=urlsplit(url);query=parse_qs(parts.query)
        self.assertEqual(parts.netloc,'api.tardis.dev')
        self.assertEqual(query['from'],['2026-09-02T00:00:00.000Z'])
        self.assertEqual(query['offset'],['10'])
        filters=json.loads(query['filters'][0])
        self.assertEqual([v['channel'] for v in filters],list(CHANNELS))
        self.assertTrue(all(v['symbols']==list(ASSETS) for v in filters))
        self.assertNotIn('key',query)

    def test_declaration_contains_all_1440_slices_and_preserves_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'data';p=declare(root)
            self.assertEqual(len(p['requests']),1440)
            self.assertEqual(p['dates'],DATES)
            self.assertEqual(p['requests'][0]['at_ms'],origin('2026-09-01'))
            self.assertEqual(p['requests'][-1]['at_ms']+600000,origin('2026-09-11'))
            self.assertTrue((root/'fetch-source.py').is_file())
            with self.assertRaises(ValueError):declare(root)

    def test_key_file_is_parsed_without_executing_it(self):
        with tempfile.TemporaryDirectory() as tmp,patch.dict('os.environ',{},clear=True):
            path=Path(tmp)/'key.env';path.write_text('TARDIS_API_KEY=\n')
            with self.assertRaises(ValueError):load_key(path)
            path.write_text('TARDIS_API_KEY=example_test_value\nUNRELATED=ignored\n')
            self.assertEqual(load_key(path),'example_test_value')

    def test_decompression_is_bounded_and_crc_checked(self):
        self.assertEqual(decode(gzip.compress(b'abc'),3),b'abc')
        with self.assertRaisesRegex(ValueError,'bound'):decode(gzip.compress(b'abcdef'),3)
        broken=bytearray(gzip.compress(b'abc'));broken[-8]^=1
        with self.assertRaises((OSError,EOFError)):decode(bytes(broken),100)


if __name__=='__main__':unittest.main()
