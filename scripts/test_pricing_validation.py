import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from validate_pricing import digest, freeze_experiment, pricing_decision, validate, healthy_windows, aggregate
from calibrate_pricing import observations, windows


class PricingValidationTests(unittest.TestCase):
    def test_combined_runs_purge_overlap_and_reject_duplicate_or_changed_candidates(self):
        first = {'calibration_sha256': 'fit', 'policy_sha256': 'policy', 'frozen_width_ppm': 117,
                 'target_survival': .48, 'tolerance': .05, 'minimum_windows': 400,
                 'journal_sha256': 'run-a', 'integration_passed': True, 'limits': 'research',
                 'window_outcomes': [{'start': 0, 'expiry': 30000, 'survived': True}]}
        second = dict(first, journal_sha256='run-b', window_outcomes=[
            {'start': 10000, 'expiry': 40000, 'survived': False},
            {'start': 40000, 'expiry': 70000, 'survived': False}])
        result = aggregate([first, second])
        self.assertEqual(result['nonoverlapping_windows'], 2)
        self.assertEqual(result['survived_windows'], 1)
        self.assertEqual(result['purged_overlapping_windows'], 1)
        self.assertEqual(result['pricing_decision'], 'insufficient_evidence')
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            aggregate([first, first])
        with self.assertRaisesRegex(ValueError, 'different frozen'):
            aggregate([first, dict(second, policy_sha256='retuned')])

    def fixture(self, root):
        source = root/'training'
        source.mkdir()
        rows = []
        for at in range(0, 91000, 1000):
            for side in ('a', 'b'):
                rows.append({'command': {'kind': 'oracle', 'source': side, 'at': at,
                             'raw': {'data': {'ctx': {'oraclePx': '80000'}}}}})
        (source/'journal.jsonl').write_text(''.join(json.dumps(row)+'\n' for row in rows))
        calibration = root/'calibration.json'
        calibration.write_text(json.dumps({'selected': {'width_ppm': 117, 'target_survival': .48},
                                          'dataset': [{'path': str(source), 'sha256': digest(source/'journal.jsonl')}]}))
        policy = root/'policy.json'
        policy.write_text(json.dumps({'mode': 'local', 'model': {'base_width_ppm': 117, 'valid_until': 10000000}}))
        parameters = {'traders': 300, 'seed': 1, 'capture_seconds': 600,
                      'cohort_size': 100, 'cohort_interval_seconds': 180, 'control_every': 2}
        return calibration, policy, parameters

    def test_decision_never_confuses_small_sample_with_target_support(self):
        self.assertEqual(pricing_decision(10, 20), 'insufficient_evidence')
        self.assertEqual(pricing_decision(0, 0), 'insufficient_evidence')
        self.assertEqual(pricing_decision(0, 20), 'candidate_missed_target')
        self.assertEqual(pricing_decision(20, 20), 'candidate_missed_target')
        self.assertEqual(pricing_decision(480, 1000), 'research_target_supported')
        self.assertEqual(pricing_decision(200, 400), 'inconclusive')

    def test_freeze_pins_candidate_and_refuses_overwrite_or_tampering(self):
        with tempfile.TemporaryDirectory() as tmp, patch('validate_pricing.time.time', return_value=1000):
            root = Path(tmp)
            calibration, policy, params = self.fixture(root)
            dest = root/'run'
            spec = freeze_experiment(calibration, policy, dest, params)
            self.assertEqual(spec['training_cutoff_ms'], 90000)
            self.assertEqual(spec['minimum_nonoverlapping_windows'], 400)
            self.assertEqual(spec['policy_sha256'], digest(dest/'frozen-policy.json'))
            with self.assertRaises(FileExistsError):
                freeze_experiment(calibration, policy, dest, params)
            (dest/'frozen-policy.json').write_text('{}')
            with self.assertRaisesRegex(ValueError, 'changed'):
                validate(dest/'experiment.json', dest/'evidence')

    def test_freeze_rejects_changed_training_or_different_width(self):
        with tempfile.TemporaryDirectory() as tmp, patch('validate_pricing.time.time', return_value=1000):
            root = Path(tmp)
            calibration, policy, params = self.fixture(root)
            original = policy.read_text()
            policy.write_text(original.replace('117', '118'))
            with self.assertRaisesRegex(ValueError, 'exact fitted'):
                freeze_experiment(calibration, policy, root/'run', params)
            policy.write_text(original)
            (root/'training/journal.jsonl').write_text('{}')
            with self.assertRaisesRegex(ValueError, 'source journal changed'):
                freeze_experiment(calibration, policy, root/'run', params)

    def test_freeze_rejects_candidate_expiring_during_cohorts(self):
        with tempfile.TemporaryDirectory() as tmp, patch('validate_pricing.time.time', return_value=1000):
            root = Path(tmp)
            calibration, policy, params = self.fixture(root)
            policy.write_text(policy.read_text().replace('10000000', '1500000'))
            with self.assertRaisesRegex(ValueError, 'validity ends'):
                freeze_experiment(calibration, policy, root/'run', params)

    def test_disagreement_invalidates_window_even_when_paired_gap_is_short(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            events = []
            for at in range(100000, 162000, 1000):
                # Two seconds of different prices exceeds the published 1.5s
                # disagreement rule, while paired receipts are only 3s apart.
                for side in ('a', 'b'):
                    price = '80001' if side == 'a' and at in (110000, 111000) else '80000'
                    events.append({'command': {'kind': 'oracle', 'source': side, 'at': at,
                                   'raw': {'data': {'ctx': {'oraclePx': price}}}}})
                events.append({'command': {'kind': 'tick', 'at': at+500}})
            (root/'journal.jsonl').write_text(''.join(json.dumps(row)+'\n' for row in events))
            observed = observations(root)
            self.assertEqual(len(windows(observed)), 2)
            eligible = healthy_windows(root, {'max_gap_ms': 8000, 'disagreement_ms': 1500}, observed)
            self.assertEqual(len(eligible), 1)
            self.assertEqual(eligible[0]['start'], 130000)

    def test_transient_mismatch_at_entry_cannot_admit_hypothetical_stage(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            events = []
            for at in range(100000, 192000, 1000):
                for side in ('a', 'b'):
                    price = '80001' if side == 'a' and at == 130000 else '80000'
                    events.append({'command': {'kind': 'oracle', 'source': side, 'at': at,
                                   'raw': {'data': {'ctx': {'oraclePx': price}}}}})
            (root/'journal.jsonl').write_text(''.join(json.dumps(row)+'\n' for row in events))
            observed = observations(root)
            self.assertEqual(len(windows(observed)), 3)
            eligible = healthy_windows(root, {'max_gap_ms': 8000, 'disagreement_ms': 1500}, observed)
            self.assertEqual([row['start'] for row in eligible], [100000, 160000])


if __name__ == '__main__':
    unittest.main()
