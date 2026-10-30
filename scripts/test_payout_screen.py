from copy import deepcopy
import unittest

from screen_payout_candidates import assess,screen


def candidate(name='valid',survival=.0095,availability=.9,offered=10000,index=0):
    return dict(policy=dict(name=name),pooled_survival=survival,availability=availability,
                minimum_daily_availability=availability,offered=offered,eligible=12000,index=index,
                daily=[dict(offered=offered,availability=availability)])


class PayoutScreenTests(unittest.TestCase):
    def test_best_score_is_not_accepted_when_economically_invalid(self):
        bad=candidate('low_score_bad',.02,.99,index=0);good=candidate(index=1)
        result=screen(dict(policy=bad['policy'],ranking=[bad,good]),100)
        self.assertEqual(result['accepted_research_candidate']['policy']['name'],'valid')
        self.assertIn('negative_zero_cost_gross',result['assessments'][0]['reasons'])

    def test_no_qualifying_candidate_has_no_fallback_acceptance(self):
        bad=candidate(survival=.02)
        result=screen(dict(policy=bad['policy'],ranking=[bad]),100)
        self.assertIsNone(result['accepted_research_candidate'])
        self.assertEqual(result['qualifying'],0)

    def test_rare_event_data_and_empty_quotes_cannot_pass(self):
        x=candidate(survival=.00095,offered=13000)
        self.assertIn('insufficient_rare_event_evidence',assess(x,1000)['reasons'])
        x=candidate(survival=None,offered=0)
        self.assertFalse(assess(x,1000)['eligible'])
        self.assertIn('empty_quote_set',assess(x,1000)['reasons'])

    def test_later_diagnostic_fields_do_not_affect_screen(self):
        x=dict(policy={'name':'valid'},ranking=[candidate()])
        before=screen(x,100);changed=deepcopy(x)
        changed['later_outcomes']=[True]*100000
        self.assertEqual(before,screen(changed,100))

    def test_worst_day_availability_and_gross_constraints_are_separate(self):
        x=candidate(survival=.0105)
        self.assertIn('negative_zero_cost_gross',assess(x,100)['reasons'])
        self.assertNotIn('survival_outside_reference_band',assess(x,100)['reasons'])
        x=candidate();x['minimum_daily_availability']=.1
        self.assertIn('insufficient_quote_availability',assess(x,100)['reasons'])


if __name__=='__main__':unittest.main()
