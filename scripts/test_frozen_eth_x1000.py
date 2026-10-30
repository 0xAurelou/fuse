from copy import deepcopy
from datetime import datetime,timezone
import gzip
import json
from pathlib import Path
import tempfile
import unittest

from audit_payout_walkforward import same
from freeze_eth_x1000 import make_candidate,score
from liquidity_archive import Archive
from native_liquidity_prefix import snapshot_index,parse_eth,verify_books,records
from test_liquidity_capture import book,oracle
from test_trial_payout import matched
from research_trial_liquidity import WARMUP_DATES


class FrozenEthTests(unittest.TestCase):
    def fixture(self,root,changed=False,disconnect=False):
        start=int(datetime(2026,10,28,tzinfo=timezone.utc).timestamp()*1000);genesis='a'*64;a=Archive(root,genesis,'fixture',segment_seconds=10000)
        a.append(dict(kind='session_start',received_at_ns=start*10**6))
        for second in range(701):
            at=start+second*1000
            if second==350 and disconnect:a.append(dict(kind='disconnect',received_at_ns=at*10**6))
            px='101' if changed and second>=330 else '100'
            a.append(dict(kind='websocket',received_at_ns=at*10**6,payload_text=json.dumps(dict(channel='activeAssetCtx',data=oracle('ETH',px)))))
            if second%2==0:a.append(dict(kind='websocket',received_at_ns=at*10**6,payload_text=json.dumps(dict(channel='l2Book',data=book('ETH',at)))))
        a.rotate();return snapshot_index(root,genesis),start,a

    def test_native_finalized_prefix_strict_book_join_and_future_invariance(self):
        with tempfile.TemporaryDirectory() as t:
            r=Path(t);a=r/'a';a.mkdir();b=r/'b';b.mkdir();c=r/'c';c.mkdir();p,start,_=self.fixture(a);q,_,_=self.fixture(b,changed=True);z,_,_=self.fixture(c,disconnect=True)
            rows,quality,books=parse_eth(a,p);verify_books(rows,books);other,_,_=parse_eth(b,q);gap,_,_=parse_eth(c,z)
            i=11;self.assertTrue(rows[i]['valid']);self.assertIsNotNone(rows[i]['adaptive_features']);self.assertEqual(rows[i]['liquidity']['received_at_ms'],start+328000)
            self.assertNotEqual(rows[i]['move'],other[i]['move']);self.assertEqual(rows[i]['adaptive_features'],other[i]['adaptive_features']);self.assertEqual(rows[i]['activity_features'],other[i]['activity_features'])
            self.assertFalse(gap[i]['valid']);self.assertEqual(rows[i]['adaptive_features'],gap[i]['adaptive_features']);self.assertEqual(quality['complete_utc_days'],0)

    def test_prefix_allows_appends_but_rejects_segment_tampering(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);p,start,a=self.fixture(root);n=len(list(records(root,p)))
            a.append(dict(kind='later',received_at_ns=(start+800000)*10**6));a.rotate();self.assertEqual(len(list(records(root,p))),n)
            path=root/p['entries'][0]['path'];path.write_bytes(path.read_bytes()+b'tamper')
            with self.assertRaisesRegex(ValueError,'changed'):list(records(root,p))

    def test_frozen_recipe_uses_only_historical_inputs_and_scores_unchanged(self):
        pool=[matched(d,i,i%7==0) for d in WARMUP_DATES for i in range(64)];packet=make_candidate(pool,[],'2026-10-28');later=[matched('2026-10-29',i) for i in range(64)];same(packet,make_candidate(pool+later,[],'2026-10-28'))
        values,result=score(later,packet);manual,summary=score(later,packet,True);same(values,manual);same(result,summary)
        changed=deepcopy(later)
        for r in changed:r.update(move=99999999,valid=False)
        other,_=score(changed,packet)
        for a,b in zip(values,other):same({k:v for k,v in a.items() if k not in ('shadow','survived')},{k:v for k,v in b.items() if k not in ('shadow','survived')})
        with self.assertRaisesRegex(ValueError,'as-of'):score([matched('2026-09-01',12)],packet)


if __name__=='__main__':unittest.main()
