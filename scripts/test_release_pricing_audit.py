from copy import deepcopy
import random
import unittest

from audit_release_pricing import (check_cash, check_configuration, check_joint,
                                   manual_envelope)
from release_pricing import Counts, OracleTape, STRATEGIES, USDC, joint, replay


def fixture():
    tape = OracleTape([(at, 100*USDC, 100*USDC) for at in range(0, 180_000, 1000)], 0, 180_000)
    paths = [tape.envelope(q, 0) for q in (30_000, 60_000, 90_000, 120_000)]
    counts, strata, codes = replay(paths, 1_000_000, 1000, 850)
    cases = {s: dict(c.result(1000, 850),
                     strata=[dict(axis=a, group=g, **n.result(1000, 850))
                             for (a, g), n in sorted(strata.items())] if s == 'all_offered' else [])
             for s, c in counts.items()}
    return tape, paths, cases, codes


class ReleasePricingAuditTests(unittest.TestCase):
    def test_full_strategy_replay_detects_premature_public_history(self):
        _, paths, cases, codes = fixture()
        got, _ = check_configuration(paths, 1_000_000, 1000, 850, cases)
        self.assertEqual(got, codes)
        corrupted = deepcopy(cases)
        corrupted['last_matured_survived']['intended'] += 1
        with self.assertRaisesRegex(ValueError, 'ticket counts'):
            check_configuration(paths, 1_000_000, 1000, 850, corrupted)

    def test_independent_cash_rejects_2x_censoring_formula_at_1000x(self):
        count = Counts(grid=1, quote_available=1, intended=1, accepted=1, censored=1)
        row = count.result(1000, 850)
        expected = [1, 1, 1, 1, 0, 0, 0, 1]
        check_cash(row, expected, 1000, 850)
        row['gross_lp_if_censored_all_win_usdc_units'] = -USDC
        with self.assertRaisesRegex(ValueError, 'censoring'):
            check_cash(row, expected, 1000, 850)

    def test_independent_joint_check_rejects_invented_independent_patterns(self):
        codes = [bytearray([3, 3, 2]), bytearray([3, 3, 2]), bytearray([3, 3, 2])]
        row = joint(codes, 100)
        check_joint(row, codes, 100)
        row['clean_coaccepted_win_count_histogram'] = [0, 1, 1, 1]
        with self.assertRaisesRegex(ValueError, 'patterns'):
            check_joint(row, codes, 100)

    def test_empty_cases_preserve_unknown_rates(self):
        count = Counts(grid=5)
        row = count.result(10000, 1000)
        check_cash(row, [5, 0, 0, 0, 0, 0, 0, 0], 10000, 1000)
        self.assertIsNone(row['survival'])

    def test_independent_raw_reconstruction_on_random_paths_and_timing_boundaries(self):
        rng = random.Random(801)
        points = []
        price = 100*USDC
        for at in range(0, 300_000, 1000):
            if rng.randrange(5) == 0:
                price += rng.choice((-10000, 10000))
            points.append((at, price, price+rng.randrange(-100, 100)))
        # An actual quote-price round trip and a gap; no fabricated second feed.
        points += [(60_050, 110*USDC, 110*USDC), (60_100, points[60][1], points[60][2])]
        points = [p for p in points if not 150_000 <= p[0] < 170_000]
        source = OracleTape(sorted(points), 0, 300_000, [(89_000, 91_000), (239_000, 241_000)])
        for q in range(0, 300_000, 30_000):
            for delay in (0, 250, 1000, 1999, 2000):
                self.assertEqual(manual_envelope(source, q, delay), source.envelope(q, delay))


if __name__ == '__main__':
    unittest.main()
