import unittest
from analyze_capture import describe, effective_size, windows

class CaptureAnalysisTests(unittest.TestCase):
    def receipts(self, stop=91000, missing=()):
        for at in range(1000, stop, 1000):
            if at in missing:
                continue
            for side in ('a','b'):
                yield {'at': at, 'source': side, 'raw': {'data': {'ctx': {'oraclePx':'100000'}}}}

    def test_flat_regime_does_not_manufacture_effective_samples(self):
        rows = windows(self.receipts(), {'max_gap_ms':8000, 'disagreement_ms':1500})
        result = describe(rows, 117)
        self.assertEqual(result['healthy_windows'], 2)
        self.assertEqual(result['regime_windows']['flat_oracle'], 2)
        self.assertFalse(result['research_minimum_met'])
        self.assertFalse(result['production_approved'])
        self.assertEqual(effective_size([1]*1000), 1)

    def test_gaps_censor_windows_and_no_partial_terminal_window(self):
        rows = list(windows(self.receipts(missing=range(10000,25000,1000)), {'max_gap_ms':8000, 'disagreement_ms':1500}))
        self.assertEqual(len(rows), 2)
        self.assertFalse(rows[0]['valid'])
        self.assertTrue(rows[1]['valid'])

    def test_all_regimes_are_reported(self):
        rows=[]
        for move, step, last in [(0,0,10000),(101,101,10000),(101,50,10000),(60,20,10060),(20,10,10010)]:
            rows.append(dict(valid=True,entry=10000,move=move,step=step,last=last))
        result=describe(rows,10000)
        self.assertEqual(set(result['regime_windows']), {'flat_oracle','jumping','volatile','trending','quiet'})

if __name__ == '__main__':
    unittest.main()

class FrozenHorizonTests(unittest.TestCase):
    def test_missing_leading_and_trailing_observations_cannot_inflate_coverage(self):
        receipts = []
        for at in range(61000, 121000, 1000):
            for side in ('a','b'):
                receipts.append({'at':at,'source':side,'raw':{'data':{'ctx':{'oraclePx':'100000'}}}})
        result=describe(windows(receipts, {'max_gap_ms':8000,'disagreement_ms':1500}, 1000, 181000),117)
        self.assertEqual(result['completed_windows'],6)
        self.assertEqual(result['healthy_windows'],1)
        self.assertEqual(result['regime_windows']['censored'],5)

    def test_no_receipts_still_counts_the_declared_horizon(self):
        result=describe(windows([], {'max_gap_ms':8000,'disagreement_ms':1500}, 1000, 181000),117)
        self.assertEqual(result['completed_windows'],6)
        self.assertEqual(result['healthy_windows'],0)
        self.assertEqual(result['coverage'],0)
