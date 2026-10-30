from copy import deepcopy
from datetime import datetime,timezone
import gzip
import json
from pathlib import Path
import tempfile
import unittest

from historical_liquidity import (VARIANTS,depth_group,fit,join_day,paired_result,
                                  predict,snapshot,summarize,vector,weighted_terciles)
from research_historical_liquidity import study_asset
from test_liquidity_capture import book
from test_payout_risk import row


def fixture():
    result=[]
    for m in range(1,10):
        for i in range(80):
            r=row(f'2025-{m:02d}-01',i,i%7==0)
            b=book(at=r['start']-500);value,reason=snapshot((r['start']-400,b),r['start'])
            assert reason is None
            r['liquidity']=value;result.append(r)
    return result


class HistoricalLiquidityTests(unittest.TestCase):
    def test_strict_entry_freshness_and_native_book_identity(self):
        b=book(at=100000)
        self.assertIsNone(snapshot((100000,b),100000)[0])
        self.assertIsNotNone(snapshot((100000,b),105000)[0])
        self.assertEqual(snapshot((100000,b),105001)[1],'stale_receipt')
        self.assertEqual(snapshot((104000,b),105001)[1],'stale_exchange_or_clock')
        with self.assertRaisesRegex(ValueError,'fastBook'):snapshot((100000,dict(b,fast=True)),100001)
        b['levels'][0]=b['levels'][0][:4]
        self.assertEqual(snapshot((100000,b),100001)[1],'insufficient_visible_levels')

    def test_streaming_join_excludes_entry_equality_and_future_messages(self):
        day='2025-01-01';origin=int(datetime(2025,1,1,tzinfo=timezone.utc).timestamp()*1000)
        def make(second,asset='ETH'):
            return f'{day}T00:00:{second:06.3f}Z '+json.dumps(dict(channel='l2Book',data=book(asset,origin+int(second*1000))))+'\n'
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);path=root/'slice.gz'
            with gzip.open(path,'wt') as stream:stream.write(make(29)+make(30)+make(31,'HYPE'))
            part,_=join_day(root,[dict(day=day,status='downloaded',path=path.name,at_ms=origin,duration_ms=600000)],day)
            self.assertEqual(part['ETH'][1]['liquidity']['received_at_ms'],origin+29000)
            self.assertIsNone(part['HYPE'][1]['liquidity'])
            self.assertIsNone(part['ETH'][2]['liquidity'])
            self.assertEqual(len(part['ETH']),2880)

    def test_disconnect_marker_censors_prior_books_without_interpolation(self):
        day='2025-01-01';origin=int(datetime(2025,1,1,tzinfo=timezone.utc).timestamp()*1000)
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);path=root/'slice.gz'
            with gzip.open(path,'wt') as stream:
                stream.write(day+'T00:00:29.000Z '+json.dumps(dict(channel='l2Book',data=book('ETH',origin+29000)))+'\n\n')
                stream.write(day+'T00:00:31.000Z '+json.dumps(dict(channel='l2Book',data=book('HYPE',origin+31000)))+'\n')
            part,counts=join_day(root,[dict(day=day,status='downloaded',path=path.name,at_ms=origin,duration_ms=600000)],day)
            self.assertIsNone(part['ETH'][1]['liquidity']);self.assertEqual(counts['disconnect_markers'],1)

    def test_paired_models_do_not_read_current_outcome_and_reject_future_training(self):
        rows=fixture();train=[r for r in rows if r['period']<'2025-07-01'];r=rows[-1]
        changed=dict(r,move=9999999,valid=False,split='ignored')
        for variant in VARIANTS:
            model=fit(train,'ETH','2025-07-01',variant)
            self.assertEqual(vector(r,variant),vector(changed,variant))
            self.assertEqual(predict(r,model),predict(changed,model))
        with self.assertRaisesRegex(ValueError,'mature strictly'):fit(rows,'ETH','2025-07-01','calendar_liquidity')
        wrong=deepcopy(train);wrong[0]['liquidity']=None
        with self.assertRaisesRegex(ValueError,'same matched cohort'):fit(wrong,'ETH','2025-07-01','calendar')

    def test_training_only_terciles_and_paired_day_bootstrap(self):
        rows=fixture();edges=weighted_terciles(rows[:240]);self.assertEqual(len(edges),2)
        self.assertIn(depth_group(rows[-1],edges),('low','middle','high'))
        daily={f'day{i}':dict(calendar={'p0':dict(log_loss=.2)},calendar_liquidity={'p0':dict(log_loss=.1)}) for i in range(5)}
        p=paired_result(daily)
        self.assertAlmostEqual(p['mean_improvement'],.1);self.assertEqual(p['improved_dates'],5)
        self.assertAlmostEqual(p['bootstrap_interval'][0],.1)

    def test_saved_origin_fit_is_unchanged_by_own_and_later_labels(self):
        # Expand fixture to the full declared date universe, with tiny days.
        from fetch_historical_liquidity import DATES
        rows=[]
        for day in DATES:
            for i in range(24):
                r=row(day,i,i%7==0);r['liquidity']=snapshot((r['start']-400,book(at=r['start']-500)),r['start'])[0];rows.append(r)
        with tempfile.TemporaryDirectory() as tmp:
            result=study_asset('ETH',rows,Path(tmp));directory=Path(tmp)/'ETH'
            self.assertEqual(result['unique_matched_evaluated_paths'],16*24)
            model=json.loads((directory/'origins'/'2025-07-01.json').read_text())
            self.assertTrue(all(d<'2025-07-01' for d in model['models']['calendar_liquidity']['training_dates']))
            changed=deepcopy(rows)
            for r in changed:
                if r['period']>='2025-07-01':r['move']=9999999
            train=[r for r in changed if r['period']<'2025-07-01']
            self.assertEqual(model['models']['calendar_liquidity']['zero_coefficients'],fit(train,'ETH','2025-07-01','calendar_liquidity')['zero_coefficients'])
            from audit_historical_liquidity import audit_asset
            report=audit_asset('ETH',rows,directory)
            self.assertEqual(report['trace_rows'],16*24*4)


if __name__=='__main__':unittest.main()
