"""Metamorphic date-boundary checks; synthetic prices are test fixtures only."""
from datetime import datetime,timezone
import unittest

from frozen_context_cdf import series,LEVELS,TIMING_NAMES
from native_adaptive_data import build_rows
from test_native_adaptive_data import receipts,POLICY


class NativeTimeTranslationTests(unittest.TestCase):
    def rows(self,start):
        raw=receipts()
        for p in raw:
            price=100000+(p['at']//120000)%2
            p['raw']['data']['ctx'].update(oraclePx=str(price),markPx=str(price+.1),midPx=str(price+.2))
            p['at']+=start
        return build_rows(raw,POLICY,start,start+900000,'private-capture')

    def test_preentry_features_and_health_translate_across_utc_midnight(self):
        noon=int(datetime(2026,10,28,12,tzinfo=timezone.utc).timestamp()*1000)
        late=int(datetime(2026,10,28,23,52,30,tzinfo=timezone.utc).timestamp()*1000)
        a,b=self.rows(noon),self.rows(late)
        def fields(rows):
            return [(r['entry_healthy'],r['valid'],r['move'],r['entry'],r['activity_features'],
                r['adaptive_features'],r['market_regime'],r['activity_state'],
                r['oracle_gap']['values'] if r['oracle_gap'] else None) for r in rows]
        self.assertEqual(fields(a),fields(b));self.assertEqual({r['period'] for r in b},{'private-capture'})

    def test_frozen_feedback_keeps_private_state_at_utc_midnight(self):
        noon=int(datetime(2026,10,28,12,tzinfo=timezone.utc).timestamp()*1000)
        late=int(datetime(2026,10,28,23,52,30,tzinfo=timezone.utc).timestamp()*1000)
        def values(rows):
            return [dict(row=r,width_ppm=100 if r['adaptive_features'] is not None else None,
                shadow_survived=(r['move']<r['entry']*100//1000000) if r['valid'] and r['adaptive_features'] is not None else None,
                survived=None,paused=False,capped=False) for r in rows]
        n=len(TIMING_NAMES)
        model=dict(family='timing',center=[0]*n,sd=[1]*n,floor_coefficients=[0]*(n+1),
            positive_coefficients=[[1]+[0]*n for _ in LEVELS])
        a=series(values(self.rows(noon)),model,'priceable',None)
        b=series(values(self.rows(late)),model,'priceable',None)
        fields=lambda part:[(p['width_ppm'],p.get('frozen_floor'),p.get('frozen_level'),p.get('frozen_logit_delta')) for p in part]
        self.assertEqual(fields(a),fields(b))
        midnight=int(datetime(2026,10,29,tzinfo=timezone.utc).timestamp()*1000)
        first=next(p for p in b if p['row']['start']==midnight)
        self.assertIsNotNone(first.get('frozen_logit_delta'))
        self.assertNotEqual(first['frozen_logit_delta'],0.)
