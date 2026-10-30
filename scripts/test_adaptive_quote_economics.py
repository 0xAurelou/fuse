from copy import deepcopy
import unittest

from adaptive_quote_economics import decisions,summarize,evaluate,STRATEGIES


def fixture(n=960):
    return [dict(start=i*30000,activity='frozen' if i%2==0 else 'active',width=1 if i%3==0 else 20,
                 floor=.6 if i%2==0 else None,shadow=i%4<2,paused=False) for i in range(n)]


class AdaptiveQuoteEconomicsTests(unittest.TestCase):
    def test_no_current_or_future_label_can_change_pre_maturity_entry(self):
        rows=fixture(100);original=decisions(rows);changed=deepcopy(rows)
        for r in changed[40:]:r['shadow']=not r['shadow']
        other=decisions(changed)
        self.assertEqual(original[:42],other[:42])
        self.assertNotEqual(original[42:],other[42:])
        self.assertNotIn('last_matured_survived',original[0]['strategies'])
        self.assertIn('last_matured_survived',original[2]['strategies'])

    def test_selected_censorship_keeps_denominator_costs_and_two_sided_bounds(self):
        rows=fixture(3)
        for r,label in zip(rows,(True,False,None)):r['shadow']=label
        case=summarize(rows,decisions(rows),'all_offered')
        self.assertEqual(case['placed_tickets'],3);self.assertEqual(case['resolved_grid_entries'],2)
        self.assertEqual(case['censored_grid_entries'],1);self.assertEqual(case['survival'],.5)
        self.assertEqual(case['lp_gross_assuming_censored_refund_usdc_units'],0)
        net=case['cost_sensitivity'][-1]
        self.assertEqual(net['allocated_expense_usdc_units'],30000)
        self.assertEqual(net['lp_net_lower_if_all_censored_survive_usdc_units'],-1030000)
        self.assertEqual(net['lp_net_upper_if_all_censored_fail_usdc_units'],970000)

    def test_synchronized_accounts_scale_same_path_pnl_and_drawdown_exactly(self):
        rows=fixture(20);ds=decisions(rows)
        one=summarize(rows,ds,'all_offered',1);three=summarize(rows,ds,'all_offered',3)
        for field in ('placed_tickets','lp_gross_assuming_censored_refund_usdc_units',
                      'customer_gross_usdc_units','settlement_pnl_drawdown_usdc_units','gross_survivor_losses_usdc_units'):
            self.assertEqual(three[field],3*one[field])
        self.assertEqual(three['survival'],one['survival']);self.assertFalse(three['shared_outcomes_independent'])

    def test_reporting_blocks_preserve_continuous_trader_history_and_restart_clears_it(self):
        rows=fixture(1920);result,chosen=evaluate(rows,0)
        self.assertEqual(len(result),2*len(STRATEGIES)*2)
        self.assertIn('last_matured_failed',chosen[960]['strategies'])
        restart=decisions(rows[960:])
        self.assertNotIn('last_matured_failed',restart[0]['strategies'])

    def test_invalid_clock_labels_width_and_forecast_are_rejected(self):
        for key,value in (('start',30001),('shadow',1),('width',0),('floor',float('nan')),('paused',0)):
            rows=fixture(3);rows[1][key]=value
            with self.assertRaises(ValueError):decisions(rows)
        with self.assertRaises(ValueError):evaluate(fixture(959),0)
