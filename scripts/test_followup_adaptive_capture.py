import subprocess
import unittest
from unittest.mock import patch

from followup_adaptive_capture import phase,process


class AdaptiveFollowupTests(unittest.TestCase):
    def test_deadline_and_both_process_handles_gate_analysis(self):
        self.assertEqual(phase(999,1000,False,False,'failed'),'original_ended_before_deadline')
        self.assertEqual(phase(1000,1000,True,False,'failed'),'waiting_original_supervisor')
        self.assertEqual(phase(1000,1000,False,True,'failed'),'orphaned_recorder_requires_attention')
        self.assertEqual(phase(1000,1000,False,False,'recording'),'original_terminal_state_requires_attention')
        self.assertEqual(phase(1000,1000,False,False,'failed'),'ready_for_supplemental_verification')

    def test_process_inspection_errors_do_not_become_terminal_handles(self):
        with patch('followup_adaptive_capture.subprocess.run',return_value=subprocess.CompletedProcess([],1,'','denied')):
            with self.assertRaises(RuntimeError):process(100,'recorder')
        with patch('followup_adaptive_capture.subprocess.run',side_effect=subprocess.TimeoutExpired([],5)):
            with self.assertRaises(subprocess.TimeoutExpired):process(100,'recorder')

    def test_process_identity_missing_and_zombie_are_distinguished(self):
        for code,stdout,expected in ((0,'S /path/recorder -config frozen',True),
                (0,'S another-process',False),(0,'Z /path/recorder',False),(1,'',False)):
            with patch('followup_adaptive_capture.subprocess.run',return_value=subprocess.CompletedProcess([],code,stdout,'')):
                self.assertEqual(process(100,'/path/recorder'),expected)
