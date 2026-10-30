from copy import deepcopy
from decimal import Decimal
import unittest

from analyze_capture import windows
from native_adaptive_data import build_rows


POLICY=dict(max_gap_ms=8000,disagreement_ms=1500,duration_ms=30000)


def receipts(end=900000,missing=()):
    result=[]
    for at in range(1000,end,1000):
        if at in missing:continue
        price=100000+(at//30000)%3
        for source in ('a','b'):
            result.append(dict(at=at,source=source,raw=dict(channel='activeAssetCtx',
                data=dict(coin='BTC',ctx=dict(oraclePx=str(price),markPx=str(price+.1),midPx=str(price+.2))))))
    return result


class NativeAdaptiveDataTests(unittest.TestCase):
    def test_native_path_and_eligibility_match_frozen_analyzer(self):
        raw=receipts(missing=range(550000,570000,1000))
        actual=build_rows(raw,POLICY,0,900000,'capture')
        old=list(windows(iter(raw),POLICY,0,900000))
        for a,b in zip(actual,old):
            self.assertEqual((a['valid'],a['entry'],a['move'],a['last']),
                             (b['valid'],b['entry'],b['move'],b['last']))
        self.assertEqual(len(actual),30)
        self.assertTrue(any(r['oracle_gap'] is not None for r in actual))
        self.assertEqual({r['period'] for r in actual},{'capture'})

    def test_future_receipts_cannot_change_entry_features_or_entry_health(self):
        raw=receipts();boundary=480000
        changed=deepcopy(raw)
        for p in changed:
            if p['at']>=boundary:
                p['raw']['data']['ctx'].update(oraclePx='999999',markPx='1000001',midPx='1000000')
        original=build_rows(raw,POLICY,0,900000,'capture')
        other=build_rows(changed,POLICY,0,900000,'capture')
        fields=lambda rows:[(r['entry_healthy'],r['adaptive_features'],r['activity_features'],r['oracle_gap'])
                            for r in rows if r['start']<=boundary]
        self.assertEqual(fields(original),fields(other))

    def test_entry_outage_blocks_quote_using_prior_state_without_future_gate(self):
        raw=receipts(missing=range(410000,435000,1000))
        rows=build_rows(raw,POLICY,0,900000,'one_capture')
        bad=next(r for r in rows if r['start']==420000)
        self.assertFalse(bad['entry_healthy']);self.assertIsNone(bad['adaptive_features'])
        self.assertIsNone(bad['oracle_gap'])
        # An outage beginning after a healthy entry censors the eventual outcome
        # without retroactively removing that entry's known feature history.
        later=receipts(missing=range(455000,475000,1000))
        rows=build_rows(later,POLICY,0,900000,'one_capture')
        first=next(r for r in rows if r['start']==450000)
        self.assertTrue(first['entry_healthy']);self.assertFalse(first['valid'])
        self.assertIsNotNone(first['adaptive_features'])
