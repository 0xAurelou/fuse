from copy import deepcopy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from canonical_capture_policy import canonical_policy
from freeze_adaptive_capture_v2 import ROOT, freeze
from prospective_capture_v2 import digest, verify_artifacts


RECORDER = os.environ.get('FUSE_TEST_RECORDER')
POLICY = os.environ.get('FUSE_TEST_POLICY')


@unittest.skipUnless(RECORDER and POLICY, 'set exact native recorder and policy for offline integration')
class NativeCanonicalPolicyTests(unittest.TestCase):
    def setUp(self):
        self.policy = json.loads(Path(POLICY).read_text())

    def test_native_roundtrip_expands_only_omitted_zeros_and_preserves_input(self):
        original = deepcopy(self.policy)
        with tempfile.TemporaryDirectory() as tmp:
            canonical, report = canonical_policy(self.policy, RECORDER, Path(tmp)/'first')
            again, second = canonical_policy(canonical, RECORDER, Path(tmp)/'second')
            self.assertEqual(self.policy, original)
            self.assertEqual(again, canonical)
            self.assertTrue(report['native_policy_roundtrip_passed'])
            self.assertEqual(report['market_observations'], 0)
            self.assertFalse(report['native_receipt_chain_verification'])
            self.assertTrue(second['comparison']['exact_json_object_match'])
            self.assertEqual(second['comparison']['explicit_zero_fields_added'], [])
            self.assertTrue(all(canonical['model'][k] == 0 for k in
                                ('base_width_bps', 'control_width_bps', 'max_drift_bps', 'volatility_factor')))

    def test_native_decoder_rejects_unknown_fields_and_wrong_integer_types(self):
        for field, value in (('unexpected_field', 0), ('max_drift_bps', False), ('max_drift_bps', 0.0)):
            with self.subTest(field=field, value=repr(value)), tempfile.TemporaryDirectory() as tmp:
                policy = deepcopy(self.policy)
                policy['model'][field] = value
                evidence = Path(tmp)/'bad'
                with self.assertRaisesRegex(ValueError, 'expected terminal gate'):
                    canonical_policy(policy, RECORDER, evidence)
                self.assertFalse((evidence/'report.json').exists())

    def test_probe_never_reuses_prior_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            evidence = Path(tmp)/'probe'
            canonical_policy(self.policy, RECORDER, evidence)
            before = (evidence/'report.json').read_bytes()
            with self.assertRaisesRegex(ValueError, 'preserve prior policy probe'):
                canonical_policy(self.policy, RECORDER, evidence)
            self.assertEqual(before, (evidence/'report.json').read_bytes())

    def test_future_freezer_binds_canonical_policy_and_keeps_original_analyzer(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            research = root/'research'
            research.mkdir()
            result = dict(selected='market:priceable_open')
            for name in ('research.json', 'audit.json', 'selection.json'):
                (research/name).write_text(json.dumps(result))
            policy = root/'source-policy.json'
            policy.write_text(json.dumps(self.policy))
            target = root/'future-software-fixture'
            with patch('freeze_adaptive_capture_v2.bindings', return_value=(result, {}, {}, 1)):
                spec = freeze(target, research, policy, Path(RECORDER))
            self.assertEqual(verify_artifacts(target), spec)
            canonical = json.loads((target/'frozen-policy.json').read_text())
            emitted = json.loads((target/'policy-probe/canonical-roundtrip/empty-native-probe/manifest.json').read_text())
            self.assertEqual(canonical, emitted['policy'])
            self.assertFalse((target/'manifest.json').exists())
            self.assertFalse((target/'receipts.jsonl').exists())
            self.assertEqual((target/'analyze.py').read_bytes(), (ROOT/'scripts/analyze_adaptive_capture.py').read_bytes())
            self.assertIn('canonical_capture_policy.py', spec['files_sha256'])
            self.assertIn('freeze_adaptive_capture_v2.py', spec['files_sha256'])
            binding = json.loads((target/'freeze.json').read_text())
            self.assertTrue(binding['native_policy_canonicalized'])
            self.assertEqual(binding['policy_probe_report_sha256'], digest(target/'policy-probe/report.json'))
            canonical['model']['max_drift_bps'] = 1
            (target/'frozen-policy.json').write_text(json.dumps(canonical))
            with self.assertRaisesRegex(ValueError, 'frozen plan or policy changed'):
                verify_artifacts(target)
