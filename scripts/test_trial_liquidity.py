from copy import deepcopy
from datetime import datetime,timezone
import gzip
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fetch_tardis_liquidity_trial import ASSETS,DATES,digest,origin
from historical_liquidity import snapshot,vector
from research_trial_liquidity import (WARMUP_DATES,SPEC,audit_asset,fitted,study_asset)
from test_liquidity_capture import book,oracle
from test_payout_risk import row
from trial_liquidity import parse_day


class TrialLiquidityTests(unittest.TestCase):
    def fixture(self,root,changed=False,disconnect=False,stale=False):
        day=DATES[0];start=origin(day);lines=[]
        for second in range(391):
            at=start+second*1000
            stamp=datetime.fromtimestamp(at/1000,timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.000Z')
            if second==330 and disconnect:lines.append('\n')
            for a in ASSETS:
                price='101' if changed and second>=330 else '100'
                lines.append(stamp+' '+json.dumps(dict(channel='activeAssetCtx',data=oracle(a,price)))+'\n')
            if second in ((324,330) if stale else (329,330)):
                for a in ASSETS:lines.append(stamp+' '+json.dumps(dict(channel='l2Book',data=book(a,at)))+'\n')
        path=root/'raw.gz'
        with gzip.open(path,'wt') as stream:stream.writelines(lines)
        item=dict(day=day,at_ms=start,duration_ms=600000,path=path.name,status='downloaded',sha256=digest(path))
        return item

    def test_native_combined_reader_grid_and_strict_entry_book(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);item=self.fixture(root);rows,qc=parse_day([item],root,DATES[0])
            for a in ASSETS:
                self.assertEqual(len(rows[a]),2880);r=rows[a][11]
                self.assertTrue(r['valid']);self.assertIsNotNone(r['adaptive_features'])
                self.assertEqual(r['move'],0);self.assertEqual(r['liquidity']['age_ms'],1000)
                self.assertEqual(r['liquidity']['received_at_ms'],origin(DATES[0])+329000)
            self.assertEqual(qc[0]['oracle_gap_median_ms'],1000)
            self.assertEqual(qc[0]['oracle_messages'],391)

    def test_future_oracle_changes_label_without_changing_entry_features(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);item=self.fixture(root);before,_=parse_day([item],root,DATES[0])
            item=self.fixture(root,changed=True);after,_=parse_day([item],root,DATES[0])
            for a in ASSETS:
                self.assertNotEqual(before[a][11]['move'],after[a][11]['move'])
                self.assertEqual(vector(before[a][11],'calendar_liquidity'),vector(after[a][11],'calendar_liquidity'))

    def test_disconnect_and_stale_books_are_excluded_not_flat_wins(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);item=self.fixture(root,disconnect=True);rows,_=parse_day([item],root,DATES[0])
            for a in ASSETS:
                self.assertFalse(rows[a][11]['valid']);self.assertIsNone(rows[a][11]['liquidity'])
            item=self.fixture(root,stale=True);rows,_=parse_day([item],root,DATES[0])
            self.assertEqual(rows['ETH'][11]['join_reason'],'stale_receipt')

    def test_reader_rejects_hash_changes_and_unexpected_channel(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);item=self.fixture(root);bad=dict(item,sha256='0'*64)
            with self.assertRaisesRegex(ValueError,'hash'):parse_day([bad],root,DATES[0])
            path=root/item['path'];raw=gzip.decompress(path.read_bytes()).replace(b'activeAssetCtx',b'badChannel')
            path.write_bytes(gzip.compress(raw));item['sha256']=digest(path)
            with self.assertRaisesRegex(ValueError,'Unexpected'):parse_day([item],root,DATES[0])

    def test_all_trial_days_scored_earlier_only_and_audited(self):
        rows=[]
        for day in WARMUP_DATES+DATES:
            for i in (list(range(12))+([2877,2878,2879] if day in DATES else [])):
                r=row(day,i,i%5==0);r['liquidity']=snapshot((r['start']-400,book(at=r['start']-500)),r['start'])[0];rows.append(r)
        self.assertEqual(len(WARMUP_DATES),20);self.assertTrue(all(d<DATES[0] for d in WARMUP_DATES))
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            with patch('builtins.print'):result=study_asset('ETH',rows,root)
            self.assertEqual(result['evaluated_dates'],list(DATES));self.assertEqual(result['strata']['weekend']['calendar']['dates'],['2026-09-05','2026-09-06'])
            packet=json.loads((root/'ETH/origins'/('2026-09-01.json')).read_text());model=packet['models']['calendar_liquidity']
            self.assertEqual(model['training_dates'],list(WARMUP_DATES));self.assertEqual(model['spec'],json.loads(json.dumps(SPEC)))
            following=json.loads((root/'ETH/origins'/('2026-09-02.json')).read_text())
            self.assertEqual(following['models']['calendar']['rows'],20*12+13)
            changed=deepcopy(rows)
            for r in changed:
                if r['period']>=DATES[0]:r['move']=9999999
            train=[r for r in changed if r['period']<DATES[0]]
            self.assertEqual(model['zero_coefficients'],fitted(train,'ETH',DATES[0],'calendar_liquidity')['zero_coefficients'])
            report=audit_asset('ETH',rows,root/'ETH');self.assertEqual(report['models_refit'],40)


if __name__=='__main__':unittest.main()
