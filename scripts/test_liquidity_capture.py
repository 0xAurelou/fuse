from copy import deepcopy
from datetime import datetime,timezone
import gzip
import hashlib
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest import mock

from liquidity_archive import Archive, canonical, sha, verify
from liquidity_features import MarketState, book_metrics
import collect_liquidity as collector


def book(asset='ETH', at=100000):
    return dict(coin=asset,time=at,levels=[
        [dict(px=str(100-i/100),sz='2',n=1) for i in range(20)],
        [dict(px=str(100.02+i/100),sz='3',n=2) for i in range(20)]])


def oracle(asset='ETH', price='100'):
    return dict(coin=asset,ctx=dict(oraclePx=price,markPx='100.01',midPx='100.01',openInterest='1000',funding='.0001'))


def trade(tid, at=100000):return dict(coin='ETH',time=at,tid=tid,px='100',sz='2',side='B')


class LiquidityFeaturesTests(unittest.TestCase):
    def test_spread_uses_latest_fresh_bbo_or_book_without_relabeling_depth(self):
        s=MarketState('ETH');s.reset(99*10**9);b=book()
        s.observe('l2Book',b,100*10**9)
        bbo=dict(coin='ETH',time=101000,bbo=[dict(px='100.005',sz='2',n=1),dict(px='100.015',sz='3',n=1)])
        s.observe('bbo',bbo,101*10**9)
        p=s.sample(102*10**9)
        self.assertEqual(p['spread_source'],'bbo')
        self.assertLess(p['spread_bps'],p['book']['spread_bps'])
        self.assertEqual(p['book']['exchange_at_ms'],100000)
        self.assertIsNone(s.sample(107*10**9)['spread_bps'])
        s.reset(107*10**9);self.assertIsNone(s.sample(108*10**9)['bbo'])

    def test_spread_and_visible_depth_and_truncation(self):
        values=book_metrics(book())
        self.assertAlmostEqual(values['spread_bps'],.02/100.01*10000)
        self.assertEqual(values['top1_bid_usd'],200)
        self.assertEqual(values['top1_ask_usd'],300.06)
        self.assertTrue(values['depth']['5']['bid_band_covered'])
        self.assertIsNotNone(values['depth']['5']['bid_usd'])
        self.assertFalse(values['depth']['50']['bid_band_covered'])
        self.assertIsNone(values['depth']['50']['bid_usd'])
        self.assertGreater(values['depth']['50']['bid_captured_usd'],0)
        self.assertIsNone(values['depth']['50']['imbalance'])

    def test_invalid_books_rejected(self):
        for mutate in (lambda b:b['levels'][0].clear(),lambda b:b['levels'][0].reverse(),
                       lambda b:b['levels'][0][0].update(px='NaN'),
                       lambda b:b['levels'][0][0].update(px='101'),
                       lambda b:b['levels'][1][0].update(sz='-1'),
                       lambda b:b['levels'][1][0].update(n=True)):
            b=book();mutate(b)
            with self.assertRaises(ValueError):book_metrics(b)

    def test_receipt_and_exchange_freshness_boundaries_and_no_future_receipt(self):
        s=MarketState('ETH');s.reset(99*10**9)
        s.observe('l2Book',book(),100*10**9);s.observe('activeAssetCtx',oracle(),100*10**9)
        self.assertIsNone(s.sample(100*10**9)['book'])
        self.assertTrue(s.sample(105*10**9)['joint_fresh'])
        self.assertFalse(s.sample(105*10**9+1000000)['book_fresh'])
        self.assertTrue(s.sample(108*10**9)['oracle_fresh'])
        self.assertFalse(s.sample(108*10**9+1000000)['oracle_fresh'])
        old=MarketState('ETH');old.reset(99*10**9);old.observe('l2Book',book(at=90000),100*10**9)
        self.assertFalse(old.sample(100*10**9+1000000)['book_fresh'])

    def test_nonmonotone_book_and_cross_asset_messages_rejected(self):
        s=MarketState('ETH');s.observe('l2Book',book(),100*10**9)
        with self.assertRaisesRegex(ValueError,'regressing'):s.observe('l2Book',book(at=99999),101*10**9)
        with self.assertRaisesRegex(ValueError,'asset differs'):s.observe('activeAssetCtx',oracle('HYPE'),101*10**9)

    def test_disconnect_reset_never_carries_old_liquidity_or_oracle(self):
        s=MarketState('ETH');s.reset(99*10**9);s.observe('l2Book',book(),100*10**9)
        s.observe('activeAssetCtx',oracle(),100*10**9)
        self.assertTrue(s.sample(101*10**9)['joint_fresh'])
        s.reset(101*10**9);p=s.sample(102*10**9)
        self.assertIsNone(p['book']);self.assertIsNone(p['oracle']);self.assertFalse(p['joint_fresh'])
        self.assertFalse(p['trade_window_transport_covered'])

    def test_oracle_idle_is_lower_bound_until_first_observed_change(self):
        s=MarketState('ETH');s.reset(99*10**9)
        for n in (100,101,102):s.observe('activeAssetCtx',oracle(),n*10**9)
        self.assertTrue(s.sample(103*10**9)['oracle_idle_is_lower_bound'])
        s.observe('activeAssetCtx',oracle(price='100.1'),103*10**9)
        p=s.sample(104*10**9)
        self.assertFalse(p['oracle_idle_is_lower_bound']);self.assertEqual(p['oracle_idle_ms'],1000)

    def test_bootstrap_deduplication_and_receipt_time_trade_expiry(self):
        s=MarketState('ETH');s.reset(99*10**9);s.acknowledge('trades')
        p=s.observe('trades',[trade(1)],100*10**9)
        self.assertTrue(p['bootstrap_batch']);self.assertEqual(p['new_rolling_trades'],0)
        p=s.observe('trades',[trade(1),trade(2,101000)],101*10**9)
        self.assertEqual(p['duplicates'],1);self.assertEqual(p['new_rolling_trades'],1)
        self.assertEqual(s.sample(102*10**9)['trade_observed_notional_usd_60s'],200)
        self.assertFalse(s.sample(102*10**9)['trade_window_transport_covered'])
        self.assertTrue(s.sample(160*10**9)['trade_window_transport_covered'])
        self.assertEqual(s.sample(162*10**9)['trade_observed_count_60s'],0)
        s.reset(162*10**9);self.assertFalse(s.sample(163*10**9)['trade_window_transport_covered'])


class LiquidityArchiveTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.genesis='a'*64
    def tearDown(self):self.tmp.cleanup()
    def record(self,i):return dict(kind='synthetic',received_at_ns=(100+i)*10**9,session_id='test',n=i)

    def test_rotation_restart_and_full_independent_digest_replay(self):
        a=Archive(self.root,self.genesis,'one',segment_seconds=2)
        for i in range(6):a.append(self.record(i))
        a.rotate();self.assertEqual(len(a.segments),3)
        b=Archive(self.root,self.genesis,'two');b.append(self.record(6));b.rotate()
        p=verify(self.root,self.genesis)
        self.assertEqual(p['sequence'],7);self.assertEqual(p['last_hash'],b.head)

    def test_partial_last_receipt_recovered_without_erasing_original(self):
        a=Archive(self.root,self.genesis,'one');a.append(self.record(0));a.flush();path=a.path;a.stream.close()
        with path.open('ab') as stream:stream.write(b'{"sequence":2')
        b=Archive(self.root,self.genesis,'two');self.assertEqual(b.sequence,1)
        self.assertEqual(b.recoveries[0]['partial_tail_bytes'],13)
        originals=list((self.root/'recovery').glob('*.interrupted'));self.assertEqual(len(originals),1)
        self.assertTrue(originals[0].read_bytes().endswith(b'{"sequence":2'))
        b.append(self.record(1));b.rotate();self.assertEqual(verify(self.root,self.genesis)['sequence'],2)

    def test_corrupt_complete_row_is_never_silently_skipped(self):
        a=Archive(self.root,self.genesis,'one');a.append(self.record(0));a.flush();a.stream.close()
        with a.path.open('ab') as stream:stream.write(b'{"bad":"complete"}\n')
        with self.assertRaises((ValueError,KeyError)):Archive(self.root,self.genesis,'two')

    def test_compressed_segment_tamper_rejected(self):
        a=Archive(self.root,self.genesis,'one');a.append(self.record(0));a.rotate()
        p=self.root/a.segments[0]['path']
        with p.open('ab') as stream:stream.write(b'x')
        with self.assertRaisesRegex(ValueError,'segment differs'):verify(self.root,self.genesis)

    def test_uncommitted_gzip_and_partial_index_can_be_adopted(self):
        a=Archive(self.root,self.genesis,'one');a.append(self.record(0));a.flush()
        raw=a.path.read_bytes();raw_path=a.path;a.stream.close()
        with gzip.open(raw_path.with_suffix('.jsonl.gz'),'wb') as stream:stream.write(raw)
        (self.root/'segments.jsonl').write_bytes(b'{"partial":')
        b=Archive(self.root,self.genesis,'two')
        self.assertEqual(b.sequence,1);self.assertTrue(list((self.root/'recovery').glob('*.tail')))
        self.assertEqual(verify(self.root,self.genesis)['sequence'],1)

    def test_active_prefix_does_not_require_stopping_the_writer(self):
        a=Archive(self.root,self.genesis,'one');a.append(self.record(0));a.flush()
        self.assertEqual(verify(self.root,self.genesis,True)['sequence'],1)
        a.append(self.record(1));a.rotate()
        self.assertEqual(verify(self.root,self.genesis)['sequence'],2)


class LiquidityCollectorTests(unittest.TestCase):
    def test_freeze_bounds_horizon_and_rejects_source_tampering(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'capture';p=collector.prepare(root)
            start=datetime.fromisoformat(p['first_complete_utc_day']).replace(tzinfo=timezone.utc)
            self.assertEqual(p['deadline_ms']-int(start.timestamp()*1000),14*86400000)
            self.assertEqual(len(p['subscriptions']),8)
            self.assertTrue(all('nSigFigs' not in s for s in p['subscriptions']))
            collector.verify_plan(root)
            (root/'source'/'liquidity_features.py').write_text('tampered')
            with self.assertRaisesRegex(ValueError,'frozen source changed'):collector.verify_plan(root)

    def test_service_is_scoped_restartable_and_uses_frozen_sources(self):
        import plistlib
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'capture';p=collector.prepare(root)
            path,label=collector.service_file(root);service=plistlib.loads(path.read_bytes())
            self.assertEqual(service['KeepAlive'],{'SuccessfulExit':False})
            self.assertIn(str(root/'source'/'collect_liquidity.py'),service['ProgramArguments'])
            self.assertEqual(label,p['service_label']);self.assertEqual(service['ThrottleInterval'],30)

    def test_mock_transport_writes_verifiable_both_asset_receipts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'capture';collector.prepare(root,seconds=10)
            payloads=[]
            for asset in ('ETH','HYPE'):
                b=book(asset,int(time.time()*1000))
                for channel,data in (('l2Book',b),('bbo',dict(coin=asset,time=b['time'],bbo=[b['levels'][0][0],b['levels'][1][0]])),('activeAssetCtx',oracle(asset)),
                    ('trades',[dict(trade(1,int(time.time()*1000)),coin=asset)])):
                    payloads.append(json.dumps(dict(channel=channel,data=data)))
            class Socket:
                def settimeout(self,*a):pass
                def send(self,*a):pass
                def close(self,*a,**k):pass
                def recv(self):
                    raw=payloads.pop(0)
                    if not payloads:(root/'STOP').touch()
                    return raw
            with mock.patch('websocket.create_connection',return_value=Socket()):collector.run(root)
            p=collector.status(root)
            self.assertEqual(p['state'],'stopped');self.assertEqual(p['stop_reason'],'requested_stop')
            self.assertFalse(p['recorder_heartbeat_fresh'])
            self.assertTrue(all(p['session_channel_messages'][a][c]==1 for a in ('ETH','HYPE') for c in collector.CHANNELS))
            _,genesis=collector.verify_plan(root);self.assertTrue(verify(root,genesis)['passed'])
            from inspect_liquidity_capture import inspect
            quality=inspect(root)
            self.assertEqual(quality['messages']['ETH']['bbo'],1)
            self.assertEqual(quality['messages']['HYPE']['trades'],1)
            self.assertFalse(quality['forward_price_outcomes_inspected'])

    def test_storage_failure_is_fatal_not_disguised_as_network_reconnect(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'capture';collector.prepare(root,seconds=10)
            original=Archive.append
            def fail(archive,record):
                if record['kind']=='websocket':raise OSError('synthetic disk failure')
                return original(archive,record)
            ws=mock.Mock();ws.recv.return_value=json.dumps(dict(channel='pong'))
            with mock.patch('websocket.create_connection',return_value=ws),mock.patch.object(Archive,'append',fail):
                with self.assertRaisesRegex(OSError,'synthetic disk failure'):collector.run(root)
            self.assertEqual(collector.status(root)['state'],'failed')


if __name__=='__main__':unittest.main()
