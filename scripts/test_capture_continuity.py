import json
import os
import random
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from capture_continuity import metadata,intervals,inspect


def policy_fixture():
    return dict(max_gap_ms=8000,model=dict(base_width_bps=0,control_width_bps=0,
                                        max_drift_bps=0,volatility_factor=0))


def rows(points):
    result=[];previous='0'*64
    for i,(at,source) in enumerate(sorted(points),1):
        digest=f'{i:064x}'
        result.append(dict(sequence=i,at=at,source=source,hash=digest,previous_hash=previous,
                           raw=dict(not_a_price='not read by observer')))
        previous=digest
    return result


class CaptureContinuityTests(unittest.TestCase):
    def test_freshness_bound_matches_original_health_on_synthetic_constant_oracles(self):
        from analyze_capture import windows
        generator=random.Random(62319)
        for _ in range(100):
            points=[]
            for source in ('a','b'):
                at=generator.randint(1,10000)
                while at<180000:
                    points.append((at,source));at+=generator.choice((1000,8000,8001,15000,30000))
            data=rows(points)
            for r in data:r['raw']=dict(data=dict(ctx=dict(oraclePx='100')))
            policy=dict(max_gap_ms=8000,disagreement_ms=1500)
            expected=[i for i,r in enumerate(windows(data,policy,0,180000)) if not r['valid']]
            observed=metadata(data,0,180000,180000,8000)
            self.assertEqual(observed['freshness_affected_grid_indices'],expected)

    def test_freshness_equality_late_arrival_and_window_boundary(self):
        self.assertEqual(intervals([1,8001],0,8001,8000),[(0,1)])
        self.assertEqual(intervals([1,8002],0,8002,8000),[(0,1),(8002,8002)])
        self.assertEqual(intervals([1,8001],0,16001,8000),[(0,1)])
        self.assertEqual(intervals([1,8001],0,16002,8000),[(0,1),(16002,16002)])
        # A stale state exactly at 30s invalidates prior expiry and new entry.
        times=[(at,s) for at in (1000,8000,16000,21999,30000,38000,46000,54000,59999) for s in ('a','b')]
        r=metadata(rows(times),0,90000,60000,8000)
        self.assertEqual(r['freshness_affected_grid_indices'],[0,1])

    def test_missing_and_silent_receivers_keep_full_horizon_denominator(self):
        r=metadata(rows([(at,'a') for at in range(1000,60000,1000)]),0,120000,60000,8000)
        self.assertEqual(r['elapsed_complete_grid_windows'],2)
        self.assertEqual(r['freshness_affected_complete_windows'],2)
        self.assertEqual(r['best_possible_final_healthy_fraction_upper_bound'],.5)
        self.assertFalse(r['receivers']['b']['fresh_at_snapshot'])
        self.assertIsNone(r['receivers']['b']['last_receipt_ms'])

    def test_payloads_do_not_change_health_and_linkage_is_not_digest_verification(self):
        raw=rows([(at,s) for at in range(1000,90000,1000) for s in ('a','b')])
        first=metadata(raw,0,120000,90000,8000)
        for r in raw:r['raw']=object()
        self.assertEqual(first,metadata(raw,0,120000,90000,8000))
        self.assertFalse(first['native_receipt_digests_verified']);self.assertFalse(first['oracle_agreement_assessed'])
        self.assertEqual(first['freshness_affected_complete_windows'],1) # startup only

    def test_invalid_metadata_rejects_and_deadline_caps_completed_windows(self):
        raw=rows([(1000,'a'),(1000,'b')])
        self.assertEqual(metadata(raw,0,60000,120000,8000)['elapsed_complete_grid_windows'],2)
        for field,value in (('sequence',3),('previous_hash','bad'),('source','c'),('at',60000),('hash','h')):
            changed=[dict(r) for r in raw];changed[1][field]=value
            with self.assertRaises(ValueError):metadata(changed,0,60000,60000,8000)
        with self.assertRaises(ValueError):metadata(raw,0,60000,500,8000)

    def test_end_of_horizon_health_is_distinct_from_later_receiver_silence(self):
        data=rows([(at,s) for at in range(1000,60000,1000) for s in ('a','b')])
        r=metadata(data,0,60000,120000,8000)
        self.assertEqual(r['freshness_affected_complete_windows'],1)
        self.assertEqual(r['receivers']['a']['age_at_observed_horizon_ms'],1000)
        self.assertEqual(r['receivers']['a']['age_at_snapshot_ms'],61000)
        self.assertFalse(r['receivers']['a']['fresh_at_snapshot'])

    def test_bounded_reader_ignores_partial_tail_without_mutating_source(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);policy=policy_fixture()
            manifest=dict(frozen_at_ms=1000,duration_ms=3600000,policy=policy)
            (root/'manifest.json').write_text(json.dumps(manifest))
            (root/'frozen-policy.json').write_text(json.dumps(policy));(root/'analysis-spec.json').write_text('{}')
            data=rows([(2000,'a'),(2000,'b')]);complete=''.join(json.dumps(r)+'\n' for r in data).encode()
            payload=complete+b'{"incomplete":';(root/'receipts.jsonl').write_bytes(payload)
            spec=dict(duration_hours=1,minimum_full_horizon_coverage=.9,files_sha256={})
            with patch('capture_continuity.verify_artifacts',return_value=spec), \
                    patch('capture_continuity.status_report',return_value={}), \
                    patch('capture_continuity.time.time_ns',return_value=61000*1000000):
                r=inspect(root)
            self.assertEqual(r['prefix_sequence'],2);self.assertEqual(r['prefix_complete_bytes'],len(complete))
            self.assertEqual(r['partial_tail_bytes'],len(payload)-len(complete))
            self.assertEqual((root/'receipts.jsonl').read_bytes(),payload)

    def test_growth_after_byte_snapshot_is_not_followed(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);policy=policy_fixture()
            (root/'manifest.json').write_text(json.dumps(dict(frozen_at_ms=1000,duration_ms=3600000,policy=policy)))
            (root/'frozen-policy.json').write_text(json.dumps(policy));(root/'analysis-spec.json').write_text('{}')
            data=rows([(2000,'a'),(2001,'b')]);first=(json.dumps(data[0])+'\n').encode();extra=(json.dumps(data[1])+'\n').encode()
            path=root/'receipts.jsonl';path.write_bytes(first);original=os.fstat
            def append_after_snapshot(fd):
                stat=original(fd)
                with path.open('ab') as writer:writer.write(extra)
                return stat
            spec=dict(duration_hours=1,minimum_full_horizon_coverage=.9,files_sha256={})
            with patch('capture_continuity.verify_artifacts',return_value=spec), \
                    patch('capture_continuity.status_report',return_value={}), \
                    patch('capture_continuity.time.time_ns',return_value=61000*1000000), \
                    patch('capture_continuity.os.fstat',side_effect=append_after_snapshot):
                r=inspect(root)
            self.assertEqual(r['prefix_sequence'],1);self.assertEqual(r['snapshot_read_bytes'],len(first))
            self.assertEqual(path.read_bytes(),first+extra)
