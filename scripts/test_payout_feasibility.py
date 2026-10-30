from fractions import Fraction
import unittest

from payout_feasibility import retention_bound,target,batch_return,maximum_liability,rare_event_diagnostic


class PayoutFeasibilityTests(unittest.TestCase):
    def test_bound_matches_exhaustive_subsets_for_small_populations(self):
        for n in range(1,10):
            for flat in range(n+1):
                for upper in (Fraction(0),Fraction(19,200),Fraction(12,25),Fraction(53,100),Fraction(1)):
                    possible=[k for k in range(1,n+1) if Fraction(max(0,flat-(n-k)),k)<=upper]
                    expected=max(possible,default=0)
                    self.assertEqual(retention_bound(n,flat,upper)['maximum_kept'],expected)

    def test_empty_all_flat_and_integer_boundary(self):
        self.assertIsNone(retention_bound(0,0,Fraction(1,2))['maximum_retention'])
        self.assertEqual(retention_bound(10,10,Fraction(1,2))['maximum_kept'],0)
        self.assertEqual(retention_bound(390,241,Fraction(53,100))['maximum_kept'],317)
        with self.assertRaises(ValueError):retention_bound(10,11,Fraction(1,2))

    def test_payout_includes_stake_and_costs_reduce_available_edge(self):
        self.assertEqual(target(2),Fraction(19,40));self.assertEqual(target(10000),Fraction(19,200000))
        self.assertEqual(target(2,500,100),Fraction(47,100))
        self.assertIsNone(target(2,10000,1))
        result=batch_return(Fraction(12,25),2,100,3500)
        self.assertEqual(result['gross'],Fraction(1,25));self.assertEqual(result['net'],Fraction(2,125))
        loss=batch_return(Fraction(12,25),5,100,3500)
        self.assertEqual(loss['allocation'],0);self.assertEqual(loss['net'],Fraction(-141,100))

    def test_correlated_tickets_reserve_full_maximum_without_netting_debt(self):
        self.assertEqual(maximum_liability(10_000_000,10000,10),999_900_000_000)
        self.assertEqual(maximum_liability(10_000_000,10000,10,funded=0),1_000_000_000_000)
        with self.assertRaises(ValueError):maximum_liability(10,2,funded=11)

    def test_rare_event_count_is_minimal_and_not_calibration_evidence(self):
        p=target(10000);r=rare_event_diagnostic(p);n=r['independent_windows_for_requested_chance_one_survivor']
        self.assertLess(r['chance_of_at_least_one_survivor'],.1)
        self.assertGreaterEqual(1-(1-float(p))**n,.95)
        self.assertLess(1-(1-float(p))**(n-1),.95)
        self.assertEqual(rare_event_diagnostic(0)['chance_of_at_least_one_survivor'],0)
        self.assertEqual(rare_event_diagnostic(1)['chance_of_at_least_one_survivor'],1)
