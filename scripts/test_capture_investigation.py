from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from analyze_capture import windows
from investigate_capture import reconstruct, intersect, union, silence_intervals, lagged_features, label, score, power_events, target_range

POLICY=dict(max_gap_ms=8000,disagreement_ms=1500)


def stream(stop=90001,missing=(),mismatch=False):
    result=[]
    for at in range(1000,stop,1000):
        if at in missing:continue
        for source in ('a','b'):
            price=100000000+(1000000 if mismatch and source=='a' and 40000<=at<43000 else 0)
            result.append(dict(at=at,source=source,price=price))
    return result


def raw(rows):
    for r in rows:
        price=r['price'];text=f'{price//1000000}.{price%1000000:06d}'
        yield dict(at=r['at'],source=r['source'],raw={'data':{'ctx':{'oraclePx':text}}})


class CaptureInvestigationTests(unittest.TestCase):
    def test_diagnostics_match_original_window_eligibility_and_paths(self):
        for records in (stream(),stream(missing=range(38000,51000,1000)),stream(mismatch=True)):
            actual,_=reconstruct(records,POLICY,1,90001)
            expected=list(windows(raw(records),POLICY,1,90001))
            for a,b in zip(actual,expected):
                for key in ('start','expiry','entry','last','move','step','valid'):
                    self.assertEqual(a[key],b[key],(key,a,b))
        rows,_=reconstruct(stream(mismatch=True),POLICY,1,90001)
        self.assertIn('sustained_disagreement',rows[1]['reasons'])
        rows,_=reconstruct(stream(missing=range(38000,51000,1000)),POLICY,1,90001)
        self.assertIn('stale_a',rows[1]['reasons'])
        self.assertIn('stale_b',rows[1]['reasons'])

    def test_interval_union_intersection_and_freshness_equality(self):
        self.assertEqual(union([(1,3),(2,5),(8,10)]),[(1,5),(8,10)])
        self.assertEqual(intersect([(1,5),(8,10)],[(2,9)]),[(2,5),(8,9)])
        records=[dict(source='a',at=1000),dict(source='a',at=9000),dict(source='b',at=1000),dict(source='b',at=9001)]
        gaps,stale=silence_intervals(records,0,9001,8000)
        self.assertEqual(len(gaps),1)
        self.assertEqual(gaps[0]['source'],'b')
        self.assertFalse(stale['a'])
        self.assertEqual(stale['b'],[(9001,9001)])

    def test_past_only_regime_features_ignore_future_prices(self):
        rows=[dict(start=i*30000,expiry=(i+1)*30000,valid=True) for i in range(15)]
        paired=[(at,100000000+at//1000*100) for at in range(0,450000,1000)]
        before=deepcopy(rows);after=deepcopy(rows)
        changed=[(at,price if at<360000 else price*2) for at,price in paired]
        lagged_features(before,paired,0);lagged_features(after,changed,0)
        self.assertEqual(before[12]['lag_features'],after[12]['lag_features'])
        self.assertNotEqual(before[13]['lag_features'],after[13]['lag_features'])
        thresholds=dict(vol_low_max_bps=1,vol_mid_max_bps=2,jump_min_bps=1,trend_efficiency_min=.6)
        self.assertEqual(label(before[12],thresholds),label(after[12],thresholds))

    def test_scores_use_exact_touch_and_are_monotone_across_widths(self):
        rows=[dict(entry=1000000,move=100),dict(entry=1000000,move=200)]
        self.assertEqual(score(rows,100)['survived'],0)
        self.assertEqual(score(rows,101)['survived'],1)
        self.assertEqual(score(rows,201)['survived'],2)

    def test_power_requests_are_not_wake_events(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'events.txt'
            p.write_text('2026-10-27 00:10:29 +0800 Sleep Entering Sleep state due to Clamshell Sleep\n'
                         '2026-10-27 00:10:29 +0800 Wake Requests maintenance\n'
                         '2026-10-27 00:14:20 +0800 Wake Wake from Deep Idle\n')
            events=power_events(p)
            self.assertEqual([e['kind'] for e in events],['Sleep','Wake'])

    def test_exact_feasible_width_ranges_handle_touch_ties_and_legal_bounds(self):
        rows=[dict(entry=1000000,move=i) for i in range(100)]
        self.assertEqual(target_range(rows),dict(minimum_ppm=43,maximum_ppm=53))
        self.assertEqual(target_range(rows,maximum=50),dict(minimum_ppm=43,maximum_ppm=50))
        self.assertIsNone(target_range([dict(entry=1000000,move=99)]*10))
