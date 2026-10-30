from copy import deepcopy
from datetime import datetime,timezone
import gzip
import json
from pathlib import Path
import tempfile
import unittest

from fetch_oxarchive_liquidity import Budget, DAY, day, declare
from check_oxarchive_liquidity import calendar_summary, verify_day
from test_liquidity_capture import book


class FakeClient:
    def __init__(self,payloads):self.payloads=iter(payloads);self.calls=0
    def get(self,route,query):
        self.calls+=1;payload=next(self.payloads)
        return json.dumps(payload).encode(),payload,{'x-credits-remaining':'49000'}


def row(at):
    b=book('ETH',at)
    return dict(symbol='ETH',coin='ETH',timestamp=at,source='venue',bids=b['levels'][0],asks=b['levels'][1])


def response(rows,cursor=None):
    return dict(success=True,data=rows,meta=dict(count=len(rows),request_id='test',has_more=cursor is not None,next_cursor=cursor))


def protocol():
    return dict(max_requests=20,credit_reserve=1000,max_compressed_bytes=1000000)


class OxarchiveDownloadTests(unittest.TestCase):
    def test_pages_resumed_by_hash_and_exact_query_without_network(self):
        start=1790812800000
        rows=[row(start+1000),row(start+5000),row(start+DAY)]
        client=FakeClient([response(rows[:2],start+5000),response(rows[1:])])
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);p=protocol()
            result=day(root,p,'ETH',start,client,Budget(p))
            self.assertEqual(client.calls,2)
            self.assertEqual(result['duplicate_rows'],1)
            self.assertEqual(result['quality']['rows'],2)
            self.assertEqual(len(result['gaps_over_10s']),1)
            self.assertEqual(verify_day(root,result)['unique_books'],2)
            changed=deepcopy(result);changed['quality']['rows']=3
            with self.assertRaisesRegex(ValueError,'statistics differ'):verify_day(root,changed)
            changed=deepcopy(result);changed['observed_snapshot_means']['spread_bps']+=1
            with self.assertRaisesRegex(ValueError,'feature means differ'):verify_day(root,changed)
            unused=FakeClient([])
            self.assertEqual(day(root,p,'ETH',start,unused,Budget(p)),result)
            self.assertEqual(unused.calls,0)
            path=root/result['pages'][0]['path']
            path.write_bytes(gzip.compress(b'{}'))
            with self.assertRaisesRegex(ValueError,'hash differs'):
                day(root,p,'ETH',start,unused,Budget(p))

    def test_source_mismatch_and_conflicting_duplicate_are_rejected(self):
        start=1790812800000
        bad=row(start+1000);bad['source']='node'
        changed=row(start+1000);changed['bids'][0]['sz']='9999'
        with tempfile.TemporaryDirectory() as tmp:
            p=protocol();root=Path(tmp)
            with self.assertRaisesRegex(ValueError,'source differs'):
                day(root,p,'ETH',start,FakeClient([response([bad])]),Budget(p))
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError,'Conflicting'):
                day(Path(tmp),p,'ETH',start,FakeClient([response([row(start+1000),changed])]),Budget(p))

    def test_declaration_is_consecutive_completed_utc_days(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'dataset'
            p=declare(root,28,datetime(2026,10,28,19,tzinfo=timezone.utc))
            self.assertEqual(p['end_ms']-p['start_ms'],28*DAY)
            self.assertEqual(datetime.fromtimestamp(p['start_ms']/1000,timezone.utc).date().isoformat(),'2026-09-30')
            self.assertEqual(p['end_ms']%DAY,0)
            with self.assertRaises(ValueError):declare(root,28)

    def test_budget_stops_before_network_and_respects_reserve(self):
        p=protocol();p['max_requests']=1;b=Budget(p)
        b.before()
        with self.assertRaises(ValueError):b.before()
        b=Budget(protocol());b.account({'x-credits-remaining':'999'},1)
        with self.assertRaisesRegex(ValueError,'Credit reserve'):b.before()

    def test_calendar_comparison_gives_each_date_equal_weight(self):
        rows=[]
        for asset in ('ETH','HYPE'):
            for date,n,spread in (('2026-10-23',10,1),('2026-10-26',1000,3),('2026-10-25',20,4)):
                rows.append(dict(asset=asset,day=date,pages=[{}],minimum_levels=20,gaps_over_10s=[],
                    quality=dict(rows=n,max_gap_ms=5400,prior_source_fresh_grid_fraction=.92),
                    observed_snapshot_means=dict(spread_bps=spread,minimum_top5_side_usd=100)))
        result=calendar_summary(rows)
        self.assertEqual(result['ETH']['groups']['weekday']['mean_daily_spread_bps'],2)
        self.assertEqual(result['ETH']['weekend_changes']['mean_daily_spread_bps_weekend_change_pct'],100)


if __name__=='__main__':unittest.main()
