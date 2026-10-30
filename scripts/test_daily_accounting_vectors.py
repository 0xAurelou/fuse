import unittest

from generate_daily_accounting_vectors import ROOT, render, vectors


class DailyAccountingVectorTests(unittest.TestCase):
    def test_committed_solidity_vectors_match_current_independent_ledger(self):
        self.assertEqual((ROOT/'test/fixtures/DailyAccountingVectors.sol').read_text(), render())

    def test_vectors_cover_real_fee_backing_ownership_and_delayed_close_transitions(self):
        actions, states = vectors()
        self.assertEqual(len(actions), len(states))
        self.assertGreater(len(actions), 30)
        self.assertEqual({row[0] for row in actions}, set(range(10)))
        self.assertTrue(any(row[2] > 0 and row[3] > 0 for row in states))
        self.assertTrue(any(row[6] < 0 for row in states))
        self.assertTrue(any(row[11] < 0 and row[21] > 0 for row in states))
        self.assertTrue(any(a[0] == 3 and a[1]//86400 > a[2]//86400 for a in actions))


if __name__ == '__main__':
    unittest.main()
