import unittest
from copy import deepcopy

from temporal_oracle_data import complete_day, origin, preceding
from temporal_pricing import apply_policy, date_rows, sessions


class TemporalResearchTests(unittest.TestCase):
    def test_complete_day_rejects_partial_duplicate_and_shifted_grids(self):
        day='2026-01-01';start=origin(day)
        rows=[dict(period=day,start=start+i*30000,expiry=start+(i+1)*30000) for i in range(2880)]
        complete_day(rows,day)
        with self.assertRaises(ValueError):complete_day(rows[:960],day)
        with self.assertRaises(ValueError):complete_day(rows[:100]+rows[99:-1],day)
        with self.assertRaises(ValueError):complete_day([dict(r,expiry=r['expiry']+1) for r in rows],day)

    def test_later_cutoffs_allow_january_but_exclude_own_august_raw_labels(self):
        jan=dict(period='2026-01-01',start=origin('2026-01-01'),expiry=origin('2026-01-01')+30000)
        aug=dict(period='2026-08-01',start=origin('2026-08-01'),expiry=origin('2026-08-01')+30000)
        raw={'2026-01-01':[dict(jan,version='raw')],'2026-08-01':[dict(aug,version='future')]}
        selected,provenance=preceding([jan,aug],raw,['2026-01-01'],'2026-08-01')
        self.assertEqual(selected,[dict(jan,version='raw')])
        self.assertEqual(len(provenance),1)
        with self.assertRaises(ValueError):preceding([jan,aug],raw,['2026-08-01'],'2026-08-01')

    def test_scoring_uses_one_source_and_restart_has_no_hidden_quote_history(self):
        day='2026-01-01';start=origin(day)
        rows=[dict(period=day,start=start+i*30000,expiry=start+(i+1)*30000) for i in range(2880)]
        self.assertEqual(date_rows([], {day:rows},[day])[0][1],rows)
        out=sessions(day,rows,'raw_temporal','selection')
        self.assertEqual(len(out),4)
        self.assertEqual(len(out[0]['rows']),2880)
        for item,hour in zip(out[1:],(0,8,16)):
            self.assertEqual(len(item['rows']),960)
            self.assertEqual(item['rows'][0]['start'],start+hour*3600000)

    def test_short_gate_uses_delayed_floor_labels_and_keeps_prices_fixed(self):
        values=[]
        for i in range(40):
            row=dict(period='one',start=i*30000,expiry=(i+1)*30000,entry=1000000,move=0,
                     valid=True,activity_state='frozen',activity_features={'idle_ms':30000,'empty_bins_300':.5})
            values.append(dict(row=row,width_ppm=10,shadow_survived=True,survived=True,paused=False,floor_reason=''))
        original=deepcopy(values)
        actual=apply_policy(values,values,'warm6_floor12')
        altered=[dict(p,row=dict(p['row'],move=100)) if i>=20 else p for i,p in enumerate(values)]
        other=apply_policy(altered,altered,'warm6_floor12')
        self.assertEqual(values,original)
        self.assertEqual([p['width_ppm'] for p in actual],[10]*40)
        self.assertEqual([p['paused'] for p in actual[:22]],[p['paused'] for p in other[:22]])
        self.assertNotEqual([p['paused'] for p in actual[35:]],[p['paused'] for p in other[35:]])
