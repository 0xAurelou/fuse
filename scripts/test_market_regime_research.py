from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from adaptive_corridor import fit_scale
from capture_dataset import file_hash
from research_market_regimes import (episodes, fit_research_models, parse_candle,
                                     partition, regime, verify_archive, windows)


def stream(stop=720_000):
    return [dict(at=at, open=100_000_000, high=100_000_000,
                 low=100_000_000, close=100_000_000) for at in range(0, stop, 1000)]


def sample(at, kind, move=200, vol=100):
    return dict(start=at, expiry=at + 30_000, valid=True, entry=1_000_000,
                move=move, market_regime=kind,
                adaptive_features=dict(vol_60_ppm=vol, vol_300_ppm=vol,
                                       trend_60_ppm=0, jump_60_ppm=0))


class MarketRegimeResearchTests(unittest.TestCase):
    def test_millisecond_and_microsecond_archives_parse_identically(self):
        at = 1_725_000_000_000
        ms = [str(at), '100.00000000', '101', '99', '100', '1', str(at + 999), '100', '1', '1', '1', '0']
        us = list(ms)
        us[0], us[6] = str(at * 1000), str((at + 1000) * 1000 - 1)
        self.assertEqual(parse_candle(ms), parse_candle(us))
        us[0] = str(at * 1000 + 1)
        with self.assertRaises(ValueError):
            parse_candle(us)
        ms[2] = '98'
        with self.assertRaises(ValueError):
            parse_candle(ms)

    def test_future_wick_changes_outcome_without_changing_entry_or_features(self):
        before = stream()
        changed = deepcopy(before)
        changed[330]['high'] += 10_000
        a = list(windows(before))[11]
        b = list(windows(changed))[11]
        self.assertIsNotNone(a['adaptive_features'])
        self.assertEqual(a['adaptive_features'], b['adaptive_features'])
        self.assertEqual(a['entry'], b['entry'])
        self.assertEqual(a['move'], 0)
        self.assertEqual(b['move'], 10_000)

    def test_missing_second_censors_window_and_requires_history_rebuild(self):
        rows = list(windows(c for c in stream() if c['at'] != 200_000))
        by_time = {r['start']: r for r in rows}
        self.assertFalse(by_time[180_000]['valid'])
        self.assertIsNone(by_time[480_000]['adaptive_features'])
        self.assertIsNotNone(by_time[510_000]['adaptive_features'])
        with self.assertRaises(ValueError):
            list(windows(stream(2000) + stream(1000)))

    def test_directional_and_range_definitions_have_explicit_boundaries(self):
        self.assertEqual(regime(dict(net_300_bps=20, directional_strength=1.5)), 'pump')
        self.assertEqual(regime(dict(net_300_bps=-20, directional_strength=1.5)), 'dump')
        self.assertEqual(regime(dict(net_300_bps=5, directional_strength=.5)), 'range')
        self.assertEqual(regime(dict(net_300_bps=19.9, directional_strength=2)), 'mixed')
        self.assertEqual(regime(None), 'missing_history')

    def test_overlapping_directional_contexts_are_clustered(self):
        rows = [sample(300_000, 'pump'), sample(600_000, 'pump'),
                sample(1_000_000, 'pump'), sample(1_100_000, 'dump')]
        groups = episodes(rows)
        self.assertEqual([e['regime'] for e in groups], ['pump', 'pump', 'dump'])
        self.assertEqual(groups[0]['windows'], 2)
        self.assertEqual((groups[0]['start_ms'], groups[0]['end_ms']), (0, 630_000))

    def test_later_prices_and_labels_never_fit_regime_scales(self):
        day = 86_400_000
        rows = [sample(i * 30_000, 'range' if i % 2 else 'pump', 100 + i % 21)
                for i in range(500)]
        rows += [sample(19 * day, 'dump'), sample(26 * day, 'mixed')]
        partition(rows, 0)
        fitted = fit_research_models([r for r in rows if r['split'] == 'train'], .48, 50_000)
        rows[-1]['move'] *= 1000
        rows[-2]['market_regime'] = 'pump'
        after = fit_research_models([r for r in rows if r['split'] == 'train'], .48, 50_000)
        self.assertEqual(fitted, after)
        fallback = fitted['regime_volatility']['fallback']['scale']
        self.assertEqual(fitted['regime_volatility']['groups']['dump']['scale'], fallback)

    def test_published_checksum_and_manifest_must_both_match(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / 'sample.zip'
            archive.write_bytes(b'archive bytes')
            digest = file_hash(archive)
            checksum = root / 'sample.zip.CHECKSUM'
            checksum.write_text(digest + '  sample.zip\n')
            manifest = dict(provider='Binance', market='spot', symbol='BTCUSDT',
                            interval='1s', archive_sha256=digest)
            (root / 'download-manifest.json').write_text(json.dumps(manifest))
            self.assertEqual(verify_archive(archive)['archive_sha256'], digest)
            archive.write_bytes(b'changed bytes')
            with self.assertRaisesRegex(ValueError, 'checksum'):
                verify_archive(archive)


if __name__ == '__main__':
    unittest.main()
