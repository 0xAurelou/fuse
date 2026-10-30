from copy import deepcopy
from datetime import datetime, timezone
import unittest
from unittest.mock import patch

from research_expanded_bursty import expanded_bundle, candidate, SOURCES, VARIANTS
from test_preentry_bursty import paths


def day_rows(day, count=40):
    origin = int(datetime.fromisoformat(day).replace(tzinfo=timezone.utc).timestamp() * 1000)
    result = []
    for p in paths(count):
        r = deepcopy(p['row'])
        r.update(period=day, start=origin + r['start'], expiry=origin + r['expiry'])
        result.append(r)
    return result


def reference_prices(rows, engine, overlay):
    return [dict(row=r, width_ppm=50, shadow_survived=bool(r['move'] < r['entry'] * 50 // 1_000_000) if r['valid'] else None,
                 survived=bool(r['move'] < r['entry'] * 50 // 1_000_000) if r['valid'] else None,
                 paused=False, capped=False) for r in rows]


class ExpandedRawTests(unittest.TestCase):
    def fit_context(self, ctx, bundle):
        # Isolate the acquisition/fit boundary from unrelated engine fitting;
        # all prior, binary and chronological calibrator fits remain real.
        with patch('chronological_raw_priors.priced', side_effect=reference_prices), \
             patch('chronological_raw_priors.floor_values', side_effect=lambda v, e: v), \
             patch('research_expanded_bursty.priced', side_effect=reference_prices), \
             patch('research_expanded_bursty.floor_values', side_effect=lambda v, e: v):
            return expanded_bundle(ctx, bundle, {}, {})

    def test_full_numeric_fit_ignores_own_and_future_raw_labels(self):
        dates = ['2024-11-01', '2024-12-01', '2025-01-01', '2025-02-01']
        original = [r for d in dates for r in day_rows(d)]
        ctx = dict(original=original, expanded_rawdays={d: day_rows(d, 50) for d in dates})
        bundle = dict(training_periods=dates[:3], cutoff=dates[3])
        first = self.fit_context(ctx, bundle)
        changed = deepcopy(ctx)
        for r in changed['expanded_rawdays'][dates[3]]:
            r.update(move=999999999, valid=False)
        self.assertEqual(first, self.fit_context(changed, bundle))
        self.assertEqual([p['rows'] for p in first['provenance']], [50, 50, 50])
        self.assertEqual(first['prior']['bursty_windows_by_period'], {d: 50 for d in dates[:3]})

    def test_expanded_raw_changes_numeric_fit_without_duplicating_dates(self):
        dates = ['2024-11-01', '2024-12-01', '2025-01-01']
        original = [r for d in dates for r in day_rows(d)]
        bundle = dict(training_periods=dates, cutoff='2025-02-01')
        before = self.fit_context(dict(original=original, expanded_rawdays={}), bundle)
        raw = day_rows(dates[1], 60)
        for r in raw:
            r['move'] = 0 if r['start'] % 3 else 20
        after = self.fit_context(dict(original=original, expanded_rawdays={dates[1]: raw}), bundle)
        self.assertEqual([p['rows'] for p in after['provenance']], [40, 60, 40])
        self.assertNotEqual(before['model']['static'], after['model']['static'])
        self.assertEqual(after['training_periods'], dates)

    def test_maturity_is_checked_before_any_numeric_fit(self):
        dates = ['2024-11-01', '2024-12-01']
        boundary = int(datetime(2025, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
        raw = day_rows(dates[0])
        raw[0]['expiry'] = boundary - 30_000
        with self.assertRaises(ValueError):
            self.fit_context(dict(original=day_rows(dates[1]), expanded_rawdays={dates[0]: raw}),
                             dict(training_periods=dates, cutoff='2025-01-01'))

    def test_unchanged_formulas_are_crossed_with_exactly_two_data_sources(self):
        names = [candidate(s, m, g) for s in SOURCES for m, g in VARIANTS]
        self.assertEqual(len(set(names)), 32)
        self.assertEqual(set(n.removeprefix('expanded:') for n in names if n.startswith('expanded:')),
                         set(n.removeprefix('existing:') for n in names if n.startswith('existing:')))


if __name__ == '__main__':
    unittest.main()
