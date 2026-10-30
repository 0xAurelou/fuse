from copy import deepcopy
import csv
import gzip
from pathlib import Path
import tempfile
import unittest

from research_oracle_history import fit_history, observations, recorded_windows


def observed(end=720_000):
    return [(at, 100_000_000 + (at // 1000) % 17 * 100) for at in range(1000, end, 1000)]


class OracleHistoryResearchTests(unittest.TestCase):
    def test_entry_and_features_never_use_boundary_or_future_observations(self):
        original = observed()
        changed = [(at, price if at < 360_000 else price * 2) for at, price in original]
        a = recorded_windows(original, 0, 720_000)[12]
        b = recorded_windows(changed, 0, 720_000)[12]
        self.assertIsNotNone(a['adaptive_features'])
        self.assertEqual(a['entry'], b['entry'])
        self.assertEqual(a['adaptive_features'], b['adaptive_features'])
        self.assertGreater(b['move'], a['move'])

    def test_stale_paths_and_their_future_feature_histories_are_excluded(self):
        samples = [(at, price) for at, price in observed() if not 200_000 <= at < 225_000]
        rows = {r['start']: r for r in recorded_windows(samples, 0, 720_000)}
        self.assertFalse(rows[180_000]['valid'])
        self.assertFalse(rows[210_000]['valid'])
        self.assertIsNone(rows[510_000]['adaptive_features'])
        self.assertIsNotNone(rows[540_000]['adaptive_features'])

    def test_timestamp_order_and_horizon_are_enforced(self):
        with self.assertRaises(ValueError):
            recorded_windows([(2000, 100), (1000, 100)], 0, 30_000)
        with self.assertRaises(ValueError):
            recorded_windows([(30_000, 100)], 0, 30_000)
        with self.assertRaises(ValueError):
            recorded_windows([], 0, 30_001)

    def test_mark_price_is_never_substituted_for_missing_oracle(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'ticker.csv.gz'
            with gzip.open(path, 'wt', newline='') as stream:
                writer = csv.DictWriter(stream, fieldnames=['exchange', 'symbol', 'local_timestamp', 'index_price', 'mark_price'])
                writer.writeheader()
                writer.writerow(dict(exchange='hyperliquid', symbol='BTC', local_timestamp=1_000_000,
                                     index_price='', mark_price='999'))
                writer.writerow(dict(exchange='hyperliquid', symbol='BTC', local_timestamp=2_000_000,
                                     index_price='100', mark_price='999'))
            samples, missing = observations(path, 0, 30_000)
            self.assertEqual(samples, [(2000, 100_000_000)])
            self.assertEqual(missing, 1)

    def test_later_days_do_not_fit_historical_formula(self):
        dates = ['2025-01-01', '2025-02-01', '2025-03-01', '2025-04-01', '2025-05-01']
        rows = []
        for day in dates:
            for i in range(100):
                rows.append(dict(date=day, start=i * 30_000, expiry=(i + 1) * 30_000,
                                 entry=1_000_000, move=100 + i % 31, valid=True,
                                 market_regime='range', adaptive_features=dict(vol_60_ppm=100,
                                     vol_300_ppm=100, trend_60_ppm=0, jump_60_ppm=0)))
        original = fit_history(deepcopy(rows), dates, .48, 50_000)[0]
        for row in rows[300:]:
            row['move'] *= 100
            row['adaptive_features']['vol_60_ppm'] *= 100
        changed = fit_history(rows, dates, .48, 50_000)[0]
        self.assertEqual(original, changed)


if __name__ == '__main__':
    unittest.main()
