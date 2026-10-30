from copy import deepcopy
from datetime import datetime, timezone
import gzip
import json
from pathlib import Path
import tempfile
import unittest

from payout_risk import (SPEC, VARIANTS, conditional_width, decision, features, fit_positive,
                         fit_risk, required_width, risk, risk_series)
from research_payout_risk import choose_risk, study_asset, summary


def row(day, i, flat=False):
    at = int(datetime.fromisoformat(day).replace(tzinfo=timezone.utc).timestamp()*1000)+i*30000
    part = 'train' if day < '2026-01-01' else 'validation' if day < '2026-06-01' else 'test'
    return dict(asset='ETH', start=at, expiry=at+30000, period=day, split=part,
                valid=True, entry=100000000, move=0 if flat else 1000+i%23,
                activity_state='frozen' if flat else 'active', market_regime='mixed',
                adaptive_features=dict(vol_60_ppm=100., vol_300_ppm=120., net_300_bps=1., directional_strength=.2),
                activity_features=dict(idle_ms=40000 if flat else 500, changes_30=0 if flat else 20,
                    changes_60=0 if flat else 40, changes_300=50, empty_bins_300=.8 if flat else .1,
                    largest_variance_share_300=.1, idle_is_lower_bound=False), oracle_gap=None)


def fixture():
    return [row(day, i, i%5 == 0) for day in ('2025-09-01', '2025-10-01', '2025-11-01', '2025-12-01',
                                            '2026-01-01', '2026-06-01') for i in range(80)]


class PayoutRiskTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = fixture()
        cls.train = [r for r in cls.data if r['split'] == 'train']
        cls.model = fit_risk(cls.train, 'ETH', '2026-01-01', 'market_calendar', .0001)
        cls.positive = fit_positive(cls.train, 'ETH', '2026-01-01', 'market_calendar')

    def test_features_exclude_current_outcomes_and_reject_stale_market_context(self):
        a = deepcopy(self.data[1]); b = deepcopy(a)
        b.update(move=99999999, valid=False, split='fake', market_regime='dump', activity_state='frozen')
        for family in ('timing', 'calendar', 'market_calendar'):
            self.assertEqual(features(a, family), features(b, family))
        a['oracle_gap'] = dict(values=[5.]*5, observed_at=a['start'], lag_observed_at=a['start']-31000)
        self.assertEqual(features(a, 'market_calendar')[-6:], [0.]*5+[1.])
        a['oracle_gap']['observed_at'] -= 1
        self.assertEqual(features(a, 'market_calendar')[-6:], [5.]*5+[0.])

    def test_asset_and_training_cutoff_boundaries(self):
        with self.assertRaisesRegex(ValueError, 'asset-specific'):
            fit_risk(self.train, 'HYPE', '2026-01-01', 'timing', .0001)
        with self.assertRaisesRegex(ValueError, 'mature strictly'):
            fit_risk(self.data, 'ETH', '2026-01-01', 'timing', .0001)
        cross = deepcopy(self.train); cross[-1]['expiry'] = int(datetime(2026,1,1,tzinfo=timezone.utc).timestamp()*1000)-1000
        with self.assertRaisesRegex(ValueError, 'mature strictly'):
            fit_risk(cross, 'ETH', '2026-01-01', 'timing', .0001)

    def test_floor_probabilities_recover_preentry_signal_and_remain_nested(self):
        flat, moving = risk(self.data[0], self.model), risk(self.data[1], self.model)
        self.assertGreater(flat[0], moving[0])
        for p0, floor in (flat, moving):
            self.assertTrue(0 < p0 <= floor < 1)

    def test_delayed_calibration_ignores_current_and_unmatured_future_labels(self):
        rows = [row('2026-06-01', i, False) for i in range(80)]
        changed = deepcopy(rows)
        for r in changed[30:]:
            r.update(move=0, valid=False)
        a, b = risk_series(rows, self.model, True), risk_series(changed, self.model, True)
        self.assertEqual(a[:32], b[:32])
        self.assertEqual(a[1]['mature'], 0)
        self.assertEqual(a[2]['mature'], 1)
        with self.assertRaisesRegex(ValueError, 'chronological'):
            risk_series(rows+rows, self.model, True)

    def test_positive_training_retains_every_permitted_positive_reference(self):
        expected = sum(required_width(r)>1 for r in self.train)
        self.assertEqual(self.positive['fitted_windows'], expected)
        self.assertEqual(self.positive['full_positive_windows'], expected)

    def test_gate_decisions_are_preentry_and_do_not_change_widths_or_reference_learning(self):
        r = self.data[1]
        p = dict(p0=.002, floor=.002)
        c = dict(width=10, positive_q=.005, tail_mass=100, supported=True)
        base = next(v for v in VARIANTS if v[0] == 'conditional_static_open')
        gated = next(v for v in VARIANTS if v[0] == 'conditional_static_gate25')
        a, b = decision(r,p,c,20,base,100), decision(r,p,c,20,gated,100)
        self.assertEqual(a['width'], b['width'])
        # .002 is below .25 * .0095, so this case remains offered.
        self.assertTrue(b['offered'])
        p['floor'] = .004
        b = decision(r,p,c,20,gated,100)
        self.assertFalse(b['offered'])
        changed = dict(r, move=0, valid=False)
        other = decision(changed,p,c,20,gated,100)
        self.assertEqual((b['width'],b['offered'],b['reason']), (other['width'],other['offered'],other['reason']))

    def test_payout_feasibility_and_rare_tail_support(self):
        r = self.data[1]
        c = conditional_width(r, dict(floor=.02), self.positive, .0095)
        self.assertEqual(c['width'], 1)
        self.assertFalse(c['supported'])
        gate = next(v for v in VARIANTS if v[0] == 'conditional_static_gate100')
        self.assertFalse(decision(r,dict(p0=.02,floor=.02),c,20,gate,100)['offered'])
        c = conditional_width(r, dict(floor=0.), self.positive, .00095)
        self.assertFalse(c['supported'])  # Tiny fixture has inadequate tail references.

    def test_empty_quote_set_is_reported_without_successful_calibration(self):
        r = self.data[1]
        p = dict(width=1, offered=False, shadow=True, survived=None, floor=.5)
        result = summary([r], [p], 1000)
        self.assertEqual(result['availability'], 0.)
        self.assertIsNone(result['survival'])
        self.assertFalse(result['at_least_20_target_expected_wins'])

    def test_touch_is_loss_and_width_zero_is_refused(self):
        r = dict(self.data[1], move=100)
        variant = VARIANTS[0]
        a = decision(r,dict(floor=.01),dict(width=1),1,variant,100)
        self.assertFalse(a['shadow'])  # Atomic delta = 100, equal to the move.
        r.update(entry=100, move=0)
        a = decision(r,dict(floor=.01),dict(width=1),1,variant,100)
        self.assertFalse(a['offered'])
        self.assertIn('unrepresentable', a['reason'])

    def test_future_diagnostics_cannot_select_risk_family(self):
        a = choose_risk(self.data, 'ETH')[1]
        changed = deepcopy(self.data)
        for r in changed:
            if r['split'] == 'test':
                r.update(move=99999999, valid=False)
        b = choose_risk(changed, 'ETH')[1]
        self.assertEqual(a, b)

    def test_end_to_end_asset_exports_all_variants_and_payouts(self):
        later = [r for r in self.data if r['split'] != 'train']
        baseline = {m:{r['start']:20 for r in later} for m in (100,1000)}
        with tempfile.TemporaryDirectory() as tmp:
            result = study_asset('ETH', self.data, baseline, Path(tmp))
            self.assertEqual(len(result['primary_test']), len(VARIANTS)*2)
            self.assertTrue((Path(tmp)/'ETH'/'metrics.csv').stat().st_size > 0)
            with gzip.open(Path(tmp)/'ETH'/'predictions.jsonl.gz','rt') as stream:
                self.assertEqual(sum(1 for _ in stream), len(later)*len(VARIANTS)*2)
            model = json.loads((Path(tmp)/'ETH'/'models.json').read_text())
            self.assertEqual(model['selected'], result['selected_risk'])
            from audit_payout_risk import audit_asset
            audited = audit_asset('ETH', self.data, baseline, Path(tmp)/'ETH')
            self.assertEqual(audited['trace_rows'], len(later)*len(VARIANTS)*2)
            self.assertTrue(audited['reference_learning_reconstructed'])


if __name__ == '__main__':
    unittest.main()
