import json
from pathlib import Path
import tempfile
import time
import unittest
from prospective_capture import ROOT, digest, freeze, verify_artifacts

class ProspectiveFreezeTests(unittest.TestCase):
    def fixture(self,root):
        source=root/'training';source.mkdir()
        (source/'journal.jsonl').write_text(json.dumps({'command':{'at':time.time_ns()//1000000-10000}})+'\n')
        calibration=root/'calibration.json'
        calibration.write_text(json.dumps({'selected':{'width_ppm':117,'target_survival':.48},'dataset':[{'path':str(source),'sha256':digest(source/'journal.jsonl')}]}))
        policy=json.loads((ROOT/'engine/config/paper.json').read_text())
        policy['model'].update(base_width_bps=0,control_width_bps=0,volatility_factor=0,base_width_ppm=117)
        path=root/'policy.json';path.write_text(json.dumps(policy))
        dest=root/'run';dest.mkdir();(dest/'fuse-capture').write_bytes(b'fixture binary')
        return calibration,path,dest

    def test_freeze_pins_artifacts_candidate_and_rejects_retuning(self):
        with tempfile.TemporaryDirectory() as tmp:
            calibration,policy,dest=self.fixture(Path(tmp))
            freeze(dest,calibration,policy,72)
            spec=verify_artifacts(dest)
            self.assertEqual(spec['duration_hours'],72)
            self.assertFalse(spec['production_approved'])
            frozen=json.loads((dest/'frozen-policy.json').read_text())
            self.assertEqual(frozen['model']['base_width_ppm'],117)
            self.assertIn(digest(dest/'analysis-spec.json'),frozen['model']['dataset'])
            with self.assertRaisesRegex(ValueError,'already frozen'):freeze(dest,calibration,policy,72)
            (dest/'analyze.py').write_text('retuned')
            with self.assertRaisesRegex(ValueError,'artifact changed'):verify_artifacts(dest)

    def test_changed_training_is_rejected_before_freeze(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);calibration,policy,dest=self.fixture(root)
            (root/'training/journal.jsonl').write_text('{}\n')
            with self.assertRaisesRegex(ValueError,'training journal changed'):freeze(dest,calibration,policy,72)
            self.assertFalse((dest/'analysis-spec.json').exists())

    def test_candidate_mismatch_and_unbounded_duration_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            calibration,policy,dest=self.fixture(Path(tmp))
            p=json.loads(policy.read_text());p['model']['base_width_ppm']=118;policy.write_text(json.dumps(p))
            with self.assertRaisesRegex(ValueError,'differs'):freeze(dest,calibration,policy,72)
            with self.assertRaisesRegex(ValueError,'hours'):freeze(dest,calibration,policy,169)

    def test_receipt_source_and_updated_width_are_bound_into_a_new_eight_hour_plan(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as tmp:
            calibration,policy,dest=self.fixture(Path(tmp))
            data=json.loads(calibration.read_text());data['selected']['width_ppm']=480
            source={'path':'verified-recording','format':'oracle-receipts-v1','sha256':'receipts'}
            data['dataset']=[source];calibration.write_text(json.dumps(data))
            p=json.loads(policy.read_text());p['model']['base_width_ppm']=480;policy.write_text(json.dumps(p))
            cutoff=time.time_ns()//1000000-10000
            with patch('capture_dataset.validate_source',return_value=(cutoff,source)) as verify:
                freeze(dest,calibration,policy,8)
                verify.assert_called_once_with(source)
            spec=verify_artifacts(dest)
            frozen=json.loads((dest/'frozen-policy.json').read_text())
            self.assertEqual(spec['duration_hours'],8)
            self.assertEqual(spec['training_cutoff_ms'],cutoff)
            self.assertEqual(spec['candidate_width_ppm'],480)
            self.assertIn('Frozen 480-ppm',spec['scope'])
            self.assertTrue(frozen['model']['version'].endswith('-480ppm'))
