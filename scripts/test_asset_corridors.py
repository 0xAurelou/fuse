import gzip
import json
from pathlib import Path
import tempfile
import unittest
from copy import deepcopy

from capture_dataset import file_hash
from research_asset_corridors import (PAYOUTS, TARGETS, baseline_series, fit_asset, fit_target, origin,
                                      parse_day, retention_bound, split, target_series, training_rows)
from fractions import Fraction
from test_oracle_activity import row


class AssetCorridorTests(unittest.TestCase):
    def test_raw_assets_keep_separate_prices_and_touch_outcomes(self):
        day = '2026-01-01'
        messages = []
        for sec in range(0, 600, 3):
            for asset, px in (('ETH', '3000' if sec < 330 else '3003'), ('HYPE', '40')):
                stamp = f'{day}T00:{sec//60:02d}:{sec%60:02d}.0000000Z'
                messages.append(stamp + ' ' + json.dumps(dict(channel='activeAssetCtx',
                    data=dict(coin=asset, ctx=dict(oraclePx=px, markPx=px)))))
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / 'slice.bin'
            path.write_bytes(gzip.compress(('\n'.join(messages) + '\n').encode()))
            item = dict(path=path.name, status='downloaded', sha256=file_hash(path),
                        at_ms=origin(day), duration_ms=600000)
            rows, profiles = parse_day([item], root, day, ['ETH', 'HYPE'])
            self.assertEqual(len(rows['ETH']), 2880)
            eth = rows['ETH'][11]
            hype = rows['HYPE'][11]
            self.assertEqual(eth['entry'], 3000_000000)
            self.assertEqual(hype['entry'], 40_000000)
            self.assertEqual(eth['move'], 3_000000)
            self.assertEqual(hype['move'], 0)
            model = dict(family='fixed', scale=1000, maximum_width_ppm=50000)
            self.assertFalse(baseline_series([eth], model)[0]['survived'])
            self.assertTrue(baseline_series([hype], model)[0]['survived'])
            self.assertEqual([p['asset'] for p in profiles], ['ETH', 'HYPE'])
            self.assertFalse(rows['ETH'][100]['valid'])  # Missing raw history stays missing.
            with self.assertRaisesRegex(ValueError, 'wrong raw channel or asset'):
                parse_day([item], root, day, ['ETH'])
            path.write_bytes(path.read_bytes() + b'corruption')
            with self.assertRaisesRegex(ValueError, 'missing or changed'):
                parse_day([item], root, day, ['ETH', 'HYPE'])

    def test_chronology_and_training_maturity_are_required(self):
        row = dict(period='2025-12-01', start=origin('2025-12-01'),
                   expiry=origin('2025-12-01') + 30000)
        selected, provenance = training_rows([], {'2025-12-01': [row]}, ['2025-12-01'], '2026-01-01', True)
        self.assertEqual(selected, [row])
        self.assertEqual(provenance[0]['source'], 'raw')
        with self.assertRaisesRegex(ValueError, 'strictly before'):
            training_rows([], {}, ['2026-01-01'], '2026-01-01', True)
        cross = dict(row, expiry=origin('2026-01-01') - 1000)
        with self.assertRaisesRegex(ValueError, 'mature before'):
            training_rows([], {'2025-12-01': [cross]}, ['2025-12-01'], '2026-01-01', True)

    def test_payout_targets_and_split_boundaries(self):
        self.assertEqual(split('2025-12-01'), 'train')
        self.assertEqual(split('2026-01-01'), 'validation')
        self.assertEqual(split('2026-05-01'), 'validation')
        self.assertEqual(split('2026-06-01'), 'test')
        self.assertEqual(len(TARGETS), 10)
        for (_, q, m), payout in zip(TARGETS[1:], PAYOUTS):
            self.assertEqual(m, payout)
            self.assertAlmostEqual(q, .95 / payout)
        self.assertEqual(retention_bound(100, 40, Fraction(19, 100)), .74)
        self.assertEqual(retention_bound(100, 0, Fraction(19, 100)), 1)
        self.assertIsNone(retention_bound(0, 0, Fraction(19, 100)))

    def test_assembled_payout_pipeline_is_causal_and_keeps_refused_references(self):
        train = [row(day*10_000_000 + i*30000, str(day), activity='frozen' if i % 2 else 'active',
                     move=0 if i % 3 == 0 else 100+i) for day in range(3) for i in range(100)]
        model = fit_target(train, .19)
        rows = [row(i*30000, activity='frozen' if i % 2 else 'active', move=1000)
                for i in range(100)]
        changed = deepcopy(rows)
        for r in changed[50:]:
            r.update(move=0, valid=False)
        a, b = target_series(rows, model), target_series(changed, model)
        # The changed path at t=50 matures at t=52, never before.
        self.assertEqual([p['width_ppm'] for p in a[:52]], [p['width_ppm'] for p in b[:52]])
        self.assertTrue(all(not p['paused'] for p in a))
        self.assertTrue(all(p['survived'] == p['shadow_survived'] for p in a))
        self.assertEqual(model['engine']['target_survival'], .19)
        self.assertEqual(model['overlay']['target_survival'], .19)

    def test_complete_asset_fit_exports_models_metrics_and_all_payouts(self):
        dates = ('2025-10-01', '2025-11-01', '2025-12-01', '2026-01-01', '2026-06-01', '2026-07-01')
        days = {}
        for day in dates:
            days[day] = []
            for i in range(80):
                r = row(origin(day)+i*30000, day, activity='frozen' if i % 4 == 0 else 'active',
                        move=0 if i % 5 == 0 else 100+i)
                r.update(asset='ETH', split=split(day), oracle_gap=None)
                r['adaptive_features'].update(trend_60_ppm=0, jump_60_ppm=100)
                days[day].append(r)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = fit_asset('ETH', days, root)
            self.assertEqual(len(result['payout_test']), 9)
            self.assertEqual(result['training_dates'], list(dates[:3]))
            self.assertEqual(len(json.loads((root/'ETH'/'models.json').read_text())['targets']), 10)
            self.assertTrue((root/'ETH'/'metrics.csv').stat().st_size > 0)
            self.assertTrue((root/'ETH'/'feasibility.csv').stat().st_size > 0)


if __name__ == '__main__':
    unittest.main()
