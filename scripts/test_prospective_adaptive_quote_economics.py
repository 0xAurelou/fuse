from copy import deepcopy
import gzip
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

import prospective_adaptive_quote_economics as paper


FIXTURE = os.environ.get('FUSE_TEST_SYNTHETIC_FOLLOWUP')
HISTORICAL = os.environ.get('FUSE_TEST_HISTORICAL_ECONOMICS')


def stage_synthetic(root, fixture, historical):
    """Copy only a declared software fixture; publish sealed results after prepare."""
    fixture, historical = Path(fixture), Path(historical)
    if not (fixture/'SYNTHETIC-trial/SYNTHETIC_FIXTURE.json').exists():
        raise ValueError('a declared synthetic follow-up fixture is required')
    trial, compatibility, followup = (root/n for n in ('trial', 'compatibility', 'followup'))
    shutil.copytree(fixture/'SYNTHETIC-trial', trial)
    shutil.copytree(fixture/'SYNTHETIC-compatibility', compatibility)
    shutil.copytree(fixture/'SYNTHETIC-followup', followup)
    for name in ('analysis.json', 'analysis-predictions.jsonl.gz'):
        (compatibility/name).unlink()
    (followup/'result.json').unlink()
    compat = paper.read(compatibility/'compatibility-spec.json')
    compat['original_directory'] = str(trial.resolve())
    (compatibility/'compatibility-spec.json').write_text(json.dumps(compat, indent=2)+'\n')
    completion = paper.read(followup/'followup-spec.json')
    completion.update(original_directory=str(trial.resolve()), compatibility_directory=str(compatibility.resolve()),
                      compatibility_spec_sha256=paper.sha(compatibility/'compatibility-spec.json'))
    (followup/'followup-spec.json').write_text(json.dumps(completion, indent=2)+'\n')
    manifest = paper.read(trial/'manifest.json')
    packet = root/'paper-protocol'
    simulated_preparation = manifest['frozen_at_ms']+3_600_000
    with patch.object(paper, 'wall_ms', return_value=simulated_preparation):
        protocol = paper.prepare(trial, compatibility, followup, historical, packet)
    return packet, protocol


def publish_synthetic(packet, fixture):
    fixture = Path(fixture)
    protocol = paper.read(packet/'protocol.json')
    compatibility = Path(protocol['compatibility_directory'])
    followup = Path(protocol['followup_directory'])
    for name in ('analysis.json', 'analysis-predictions.jsonl.gz'):
        shutil.copyfile(fixture/'SYNTHETIC-compatibility'/name, compatibility/name)
    shutil.copyfile(fixture/'SYNTHETIC-followup/result.json', followup/'result.json')


class ProspectiveEconomicsGridTests(unittest.TestCase):
    def data(self):
        start = 1000000
        protocol = dict(modes=['continuous', 'restart_half'], candidates=['fixture'])
        predictions, summaries = [], []
        for mode in protocol['modes']:
            predictions.extend(dict(mode=mode, candidate='fixture', start=start+i*30000,
                width_ppm=10, shadow_survived=True, floor=.5, paused=False, activity='frozen') for i in range(960))
            for interval, n in [('full', 960)]+[('quarter'+str(i), 240) for i in range(4)]:
                for axis, group in (('all', 'all'), ('activity', 'frozen')):
                    summaries.append(dict(mode=mode, candidate='fixture', interval=interval, axis=axis,
                        group=group, offered_pre_entry_decisions=n, windows=n, survived=n))
        return protocol, predictions, dict(summaries=summaries), start

    def test_private_restart_resets_only_at_half_not_reporting_blocks(self):
        protocol, predictions, analysis, start = self.data()
        cases, traces = paper.compute(predictions, protocol, start, analysis)
        index = {(r['mode'], r['start']):r['strategies'] for r in traces}
        for i in (240, 480, 481):
            self.assertIn('last_matured_survived', index['continuous', start+i*30000])
        self.assertIn('last_matured_survived', index['restart_half', start+240*30000])
        for i in (480, 481):
            self.assertNotIn('last_matured_survived', index['restart_half', start+i*30000])
        self.assertIn('last_matured_survived', index['restart_half', start+482*30000])
        self.assertEqual(len(cases), 260)

    def test_missing_grid_or_disagreement_with_pricing_denominator_rejects(self):
        protocol, predictions, analysis, start = self.data()
        with self.assertRaisesRegex(ValueError, 'complete original quote grid'):
            paper.compute(predictions[1:], protocol, start, analysis)
        bad = deepcopy(analysis)
        bad['summaries'][0]['offered_pre_entry_decisions'] -= 1
        with self.assertRaisesRegex(ValueError, 'pricing denominator differs'):
            paper.compute(predictions, protocol, start, bad)


@unittest.skipUnless(FIXTURE and HISTORICAL, 'set retained synthetic follow-up and historical economics fixture')
class ProspectiveEconomicsIntegrationTests(unittest.TestCase):
    def test_early_horizon_never_reads_results_or_invokes_native_verification(self):
        with tempfile.TemporaryDirectory() as tmp:
            packet, protocol = stage_synthetic(Path(tmp), FIXTURE, HISTORICAL)
            with patch.object(paper, 'wall_ms', return_value=protocol['original_deadline_ms']-1), \
                    patch.object(paper.subprocess, 'check_output') as native:
                with self.assertRaisesRegex(ValueError, 'horizon has not elapsed'):
                    paper.run(packet)
                native.assert_not_called()
            self.assertFalse((packet/'cases.jsonl').exists())

    def test_nonempty_native_fixture_replays_all_cases_and_preserves_terminal_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            packet, protocol = stage_synthetic(Path(tmp), FIXTURE, HISTORICAL)
            publish_synthetic(packet, FIXTURE)
            status = Path(protocol['original_directory'])/'status.json'
            before = status.read_bytes()
            result = paper.run(packet)
            self.assertTrue(result['software_fixture'])
            self.assertFalse(result['economics_validated'])
            self.assertEqual(result['cases'], 780)
            self.assertEqual(result['quote_decisions'], 5760)
            self.assertEqual(status.read_bytes(), before)
            with gzip.open(packet/'entry-decisions.jsonl.gz', 'rt') as stream:
                self.assertEqual(sum(1 for _ in stream), 5760)
            with self.assertRaisesRegex(ValueError, 'preserve existing economics'):
                paper.run(packet)

    def test_frozen_model_and_completed_tape_tampering_rejects(self):
        for mutation in ('model', 'predictions'):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as tmp:
                packet, protocol = stage_synthetic(Path(tmp), FIXTURE, HISTORICAL)
                publish_synthetic(packet, FIXTURE)
                target = (Path(protocol['original_directory'])/'adaptive-models.json' if mutation == 'model'
                          else Path(protocol['compatibility_directory'])/'analysis-predictions.jsonl.gz')
                with target.open('ab') as stream:
                    stream.write(b' ')
                with self.assertRaisesRegex(ValueError, 'frozen file changed|pricing output changed'):
                    paper.run(packet)
                self.assertFalse((packet/'cases.jsonl').exists())
