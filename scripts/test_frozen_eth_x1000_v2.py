import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from audit_payout_walkforward import same
from freeze_eth_x1000_v2 import declare
from native_liquidity_prefix import parse_eth as original_parse,snapshot_index
from native_liquidity_prefix_v2 import parse_eth,verify_books
from research_payout_risk import digest,dump
import test_frozen_eth_x1000 as fixtures
from test_liquidity_capture import oracle


class FrozenEthParserAmendmentTests(unittest.TestCase):
    def test_irrelevant_timestamp_backstep_keeps_exact_eth_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);p,start,a=fixtures.FrozenEthTests().fixture(root);before,_,_=parse_eth(root,p)
            a.append(dict(kind='websocket',received_at_ns=(start+700000-14)*10**6,payload_text=json.dumps(dict(channel='activeAssetCtx',data=oracle('HYPE','100')))));a.rotate();q=snapshot_index(root,p['genesis'])
            with self.assertRaisesRegex(ValueError,'Regressing'):original_parse(root,q)
            after,qc,books=parse_eth(root,q);same(before,after);verify_books(after,books);self.assertEqual(qc['counts']['raw_receipt_timestamp_backsteps'],1)
            a.append(dict(kind='websocket',received_at_ns=(start+700000-10)*10**6,payload_text=json.dumps(dict(channel='activeAssetCtx',data=oracle('ETH','100')))));a.rotate();q=snapshot_index(root,p['genesis'])
            with self.assertRaisesRegex(ValueError,'pricing/control'):parse_eth(root,q)

    def test_amendment_reuses_identical_candidate_and_prefix(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);old=root/'old';old.mkdir();new=root/'new';(old/'candidate.json.gz').write_bytes(b'frozen model bytes');dump(old/'protocol.json',dict(parent='parent',capture='capture',capture_prefix={'last_sequence':123},cutoff='2026-10-28'));dump(old/'freeze.json',dict(candidate_sha256=digest(old/'candidate.json.gz'),frozen_at_ns=1))
            with patch('freeze_eth_x1000_v2.verify_original',return_value=json.loads((old/'protocol.json').read_text())):p=declare(old,new)
            self.assertEqual((old/'candidate.json.gz').read_bytes(),(new/'candidate.json.gz').read_bytes());self.assertEqual(p['capture_prefix'],{'last_sequence':123});self.assertTrue(p['model_and_capture_prefix_unchanged'])


if __name__=='__main__':unittest.main()
