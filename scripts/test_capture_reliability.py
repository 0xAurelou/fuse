import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
import subprocess
from prospective_capture_v2 import health, monitor_capture, progress, status_report, freeze, verify_artifacts, supervise


class CaptureReliabilityTests(unittest.TestCase):
    def test_completed_run_cannot_restart_or_overwrite_final_status(self):
        from test_prospective_capture import ProspectiveFreezeTests
        with tempfile.TemporaryDirectory() as tmp:
            calibration,policy,directory = ProspectiveFreezeTests().fixture(Path(tmp))
            freeze(directory,calibration,policy,8)
            retained = json.dumps(dict(state='completed',last_receipt_hash='retained'))
            (directory/'status.json').write_text(retained)
            with patch('prospective_capture_v2.subprocess.Popen') as child:
                with self.assertRaisesRegex(ValueError,'already completed'):supervise(directory)
            child.assert_not_called()
            self.assertEqual((directory/'status.json').read_text(),retained)

    def test_new_freeze_pins_v2_supervisor_and_preserves_old_protocol(self):
        from test_prospective_capture import ProspectiveFreezeTests
        with tempfile.TemporaryDirectory() as tmp:
            calibration,policy,directory = ProspectiveFreezeTests().fixture(Path(tmp))
            freeze(directory,calibration,policy,8)
            spec = verify_artifacts(directory)
            self.assertEqual(spec['duration_hours'],8)
            self.assertEqual((directory/'supervisor.py').read_bytes(),
                             Path(__file__).with_name('prospective_capture_v2.py').read_bytes())
            self.assertIn('monitor_capture',(directory/'supervisor.py').read_text())
            self.assertEqual(spec['candidate_width_ppm'],117)

    def test_health_exposes_one_silent_receiver_and_expired_supervisor(self):
        status = dict(state='recording',updated_at_ms=100000,
                      receiver_last_receipt_ms={'a':100000,'b':80000})
        report = health(status,{'max_gap_ms':8000},now=100001)
        self.assertEqual(report['receiver_fresh'],{'a':True,'b':False})
        self.assertEqual(report['receiver_age_ms']['b'],20001)
        self.assertFalse(report['all_receivers_fresh'])
        self.assertTrue(report['supervisor_fresh'])
        later = health(status,{'max_gap_ms':8000},now=120000)
        self.assertEqual(later['continuity_state'],'supervisor_stale')
        self.assertTrue(later['both_receivers_stale'])

    def test_missing_receivers_freshness_boundary_and_clock_regression(self):
        status = dict(state='recording',updated_at_ms=10000,
                      receiver_last_receipt_ms={'a':2000,'b':2000})
        self.assertTrue(health(status,{'max_gap_ms':8000},10000)['all_receivers_fresh'])
        self.assertTrue(health(status,{'max_gap_ms':8000},10001)['both_receivers_stale'])
        status['receiver_last_receipt_ms'] = {'a':10001}
        report = health(status,{'max_gap_ms':8000},10000)
        self.assertFalse(report['all_receivers_fresh'])
        self.assertIsNone(report['receiver_age_ms']['b'])
        self.assertFalse(report['receiver_fresh']['a'])

    def test_bounded_tail_retains_silent_receiver_age(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            rows = [dict(source='a',at=10000+i,sequence=i+1,hash='h',padding='x'*1000)
                    for i in range(100)]
            (directory/'receipts.jsonl').write_text(''.join(json.dumps(row)+'\n' for row in rows))
            report = progress(directory,{'b':1000})
            self.assertEqual(report['receiver_last_receipt_ms'],{'a':10099,'b':1000})
            self.assertEqual(report['sequence'],100)

    def test_status_reader_rechecks_saved_health_against_current_time(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            (directory/'status.json').write_text(json.dumps(dict(state='recording',updated_at_ms=1000,
                health={'continuity_state':'healthy'},receiver_last_receipt_ms={'a':1000,'b':1000})))
            (directory/'frozen-policy.json').write_text(json.dumps({'max_gap_ms':8000}))
            with patch('prospective_capture_v2.wall_ms',return_value=30000):
                report = status_report(directory)
            self.assertEqual(report['health']['continuity_state'],'supervisor_stale')
            self.assertTrue(report['health']['both_receivers_stale'])

    def watch(self, directory, child, times, interrupted=False, disk_free=20*1024**3):
        status = {}; saves = []
        def save(state, **extra):
            status.update(state=state,**extra);saves.append(dict(status))
        with patch('prospective_capture_v2.wall_ms',side_effect=times), \
             patch('prospective_capture_v2.time.sleep') as sleep, \
             patch('prospective_capture_v2.shutil.disk_usage',return_value=Mock(free=disk_free)):
            reason = monitor_capture(child,directory,status,[interrupted],save)
        return reason,status,saves,sleep

    def test_resume_after_deadline_stops_stalled_child_without_extending_horizon(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            manifest = dict(frozen_at_ms=1000,duration_ms=8*3600000)
            path = directory/'manifest.json';path.write_text(json.dumps(manifest))
            child = Mock();child.poll.return_value = None;child.returncode = 0
            reason,status,saves,sleep = self.watch(directory,child,[2000,30*3600000])
            self.assertEqual(reason,'deadline')
            self.assertTrue(status['deadline_enforced'])
            self.assertEqual(status['deadline_ms'],1000+8*3600000)
            child.terminate.assert_called_once();child.kill.assert_not_called()
            self.assertEqual(len(saves),2);sleep.assert_called_once_with(5)
            self.assertEqual(json.loads(path.read_text()),manifest)

    def test_deadline_kills_unresponsive_child_after_bounded_grace(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            (directory/'manifest.json').write_text(json.dumps(dict(frozen_at_ms=1000,duration_ms=1000)))
            child = Mock();child.poll.return_value = None
            child.wait.side_effect = [subprocess.TimeoutExpired('fixture',10),0]
            reason,_,_,_ = self.watch(directory,child,[2000])
            self.assertEqual(reason,'deadline');child.kill.assert_called_once()

    def test_interruption_and_disk_floor_remain_failures_to_complete(self):
        with tempfile.TemporaryDirectory() as tmp:
            for interrupted,free,expected in [(True,20*1024**3,'interrupted'),(False,0,'disk_floor')]:
                child = Mock();child.poll.return_value = None
                reason,_,saves,_ = self.watch(Path(tmp),child,[],interrupted,free)
                self.assertEqual(reason,expected)
                self.assertEqual(saves,[]);child.terminate.assert_called_once()

    def test_clean_early_exit_does_not_become_a_deadline_stop(self):
        with tempfile.TemporaryDirectory() as tmp:
            child = Mock();child.poll.return_value = 0
            reason,_,saves,_ = self.watch(Path(tmp),child,[])
            self.assertEqual(reason,'exited');self.assertEqual(saves,[])
            child.terminate.assert_not_called()

    def test_failed_native_verification_after_deadline_never_marks_completed(self):
        from test_prospective_capture import ProspectiveFreezeTests
        with tempfile.TemporaryDirectory() as tmp:
            calibration,policy,directory = ProspectiveFreezeTests().fixture(Path(tmp))
            freeze(directory,calibration,policy,8)
            (directory/'manifest.json').write_text(json.dumps(dict(frozen_at_ms=1000,duration_ms=1000)))
            child = Mock();child.poll.side_effect = [None,0];child.returncode = 0;child.pid = 12345
            with patch('prospective_capture_v2.subprocess.Popen',return_value=child), \
                 patch('prospective_capture_v2.subprocess.run',side_effect=subprocess.CalledProcessError(1,'verify')) as verify, \
                 patch('prospective_capture_v2.sys.platform','linux'), \
                 patch('prospective_capture_v2.signal.signal'):
                with self.assertRaises(subprocess.CalledProcessError):supervise(directory)
            status = json.loads((directory/'status.json').read_text())
            self.assertEqual(status['state'],'failed')
            self.assertTrue(status['deadline_enforced'])
            self.assertEqual(verify.call_count,1)
            self.assertFalse((directory/'analysis.json').exists())

