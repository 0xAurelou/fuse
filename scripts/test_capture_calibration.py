from copy import deepcopy
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from calibrate_capture import fit_candidate
from capture_dataset import load_capture, validate_source, file_hash


class CaptureCalibrationTests(unittest.TestCase):
    def test_candidate_selection_does_not_use_later_split_outcomes(self):
        rows=[dict(start=i*30000,expiry=(i+1)*30000,entry=1000000,max_move_units=i+5) for i in range(20)]
        first=fit_candidate(rows,50000)
        changed=deepcopy(rows)
        for row in changed[12:]:row['max_move_units']=0
        second=fit_candidate(changed,50000)
        self.assertEqual(first['selected']['width_ppm'],second['selected']['width_ppm'])
        self.assertNotEqual(first['selected']['test_survival'],second['selected']['test_survival'])
        self.assertEqual(first['counts'],dict(train=12,validation=4,test=4))
        self.assertLessEqual(first['split_ranges']['train']['end_ms'],first['split_ranges']['validation']['start_ms'])
        self.assertFalse(first['fresh_prospective_validation'])

    def test_overlapping_windows_are_purged_and_touch_is_not_survival(self):
        rows=[dict(start=i*30000,expiry=(i+1)*30000,entry=1000000,max_move_units=i) for i in range(10)]
        rows.append(dict(rows[1],start=rows[1]['start']+1))
        result=fit_candidate(rows,50000)
        self.assertEqual(result['eligible_windows'],10)
        self.assertEqual(result['purged_overlapping_windows'],1)
        # Six training thresholds are 1..6. Width three survives exactly three,
        # since a move of three at a three-ppm corridor is a touch.
        self.assertEqual(result['selected']['width_ppm'],3)
        self.assertEqual(result['selected']['train_survival'],.5)

    def fixture(self,root):
        source=root/'capture';source.mkdir()
        (source/'fuse-capture').write_bytes(b'verifier fixture')
        (source/'analysis-spec.json').write_text(json.dumps({'files_sha256':{'fuse-capture':file_hash(source/'fuse-capture')}}))
        start=time.time_ns()//1000000-300000
        policy=dict(duration_ms=30000,max_gap_ms=8000,disagreement_ms=1500,model={'base_width_ppm':117})
        manifest=dict(frozen_at_ms=start,duration_ms=120000,policy=policy)
        rows=[]
        for at in range(start+1000,start+120000,1000):
            for side in ('a','b'):
                rows.append(dict(sequence=len(rows)+1,at=at,source=side,hash='h'+str(len(rows)+1),raw={'data':{'ctx':{'oraclePx':'100000'}}}))
        (source/'receipts.jsonl').write_text(''.join(json.dumps(row)+'\n' for row in rows))
        (source/'manifest.json').write_text(json.dumps(manifest))
        (source/'status.json').write_text(json.dumps({'state':'completed','sequence':len(rows),'last_receipt_hash':rows[-1]['hash']}))
        return source,dict(manifest=manifest,head=rows[-1])

    def test_completed_capture_provenance_and_freshness_are_rechecked(self):
        with tempfile.TemporaryDirectory() as tmp:
            path,proof=self.fixture(Path(tmp))
            with patch('capture_dataset.subprocess.check_output',return_value=json.dumps(proof)):
                rows,source,_=load_capture(path)
                self.assertEqual(len(rows),3)
                self.assertEqual(source['completed_windows'],4)
                self.assertEqual(source['censored_windows'],1)
                end,checked=validate_source(source)
                self.assertEqual(end,source['collection_end_ms'])
                self.assertEqual(checked['sha256'],file_hash(path/'receipts.jsonl'))
                altered=dict(source,sha256='tampered')
                with self.assertRaisesRegex(ValueError,'fitted capture changed'):validate_source(altered)
                status=json.loads((path/'status.json').read_text());status['state']='recording';(path/'status.json').write_text(json.dumps(status))
                with self.assertRaisesRegex(ValueError,'completed'):load_capture(path)

    def test_changed_verifier_and_moving_receipts_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            path,proof=self.fixture(Path(tmp))
            with patch('capture_dataset.subprocess.check_output',return_value=json.dumps(proof)):
                with (path/'receipts.jsonl').open('a') as stream:stream.write(json.dumps(dict(proof['head'],sequence=999,hash='new'))+'\n')
                with self.assertRaisesRegex(ValueError,'changed after'):load_capture(path)
            (path/'fuse-capture').write_bytes(b'changed verifier')
            with self.assertRaisesRegex(ValueError,'frozen executable'):load_capture(path)
