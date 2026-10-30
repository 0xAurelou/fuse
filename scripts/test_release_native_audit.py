from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from audit_native_ppb import checked_case, terminal_cash


def state():
    return dict(stages={'stage':dict(status='survived', funded=1_000_000, debt=0,
        terms=dict(multiplier=2, stake=1_000_000,payout=2_000_000,
            pricing_rule='fixed-width-ppb-v1',width_ppb=1000))},
        accounts={'trader':dict(available=11_000_000,unfunded=0,earned_funded=0,
            earned_unfunded=0,withdrawal_funded=0,withdrawal_unfunded=0,withdrawn=0)},
        lp=99_000_000,lp_profit=-1_000_000,custody=11_000_000,reserve=0,loss_clearing=0)


class NativeAuditTests(unittest.TestCase):
    def test_completed_case_reuse_requires_same_protocol_binary_source_and_case_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in ('protocol.json','fuse-research','one-audit.jsonl','one-state.json','one-result.json'):
                (root/name).write_text(name)
            result = dict(profile='one',all_records_reexecuted=100,
                all_original_receipts=90,selected_grid_entries=2,quote_attempts=2,
                independent_cash_verified=True,exact_barriers_verified=True)
            with patch('audit_native_ppb.audit_case',return_value=result) as execute:
                self.assertEqual(checked_case(root,{},dict(name='one'),[],{},{}),result)
                self.assertEqual(checked_case(root,{},dict(name='one'),[],{},{}),result)
                self.assertEqual(execute.call_count,1)
                original = (root/'one-state.json').read_text()
                (root/'one-state.json').write_text('different')
                with self.assertRaisesRegex(ValueError,'binding changed'):
                    checked_case(root,{},dict(name='one'),[],{},{})
                (root/'one-state.json').write_text(original)
                (root/'fuse-research').write_text('changed executable')
                with self.assertRaisesRegex(ValueError,'binding changed'):
                    checked_case(root,{},dict(name='one'),[],{},{})

    def test_win_debt_and_cash_match_exact_terminal_payout(self):
        got = terminal_cash(state(),100_000_000,10_000_000)
        self.assertEqual(got['lp_gross_pnl_usdc_units'],-1_000_000)
        self.assertEqual(got['trader_gross_pnl_usdc_units'],1_000_000)

    def test_omitted_winner_or_custody_drift_cannot_pass(self):
        for change in (lambda s:s.update(lp=100_000_000),
                       lambda s:s.update(custody=10_000_000),
                       lambda s:s['accounts']['trader'].update(available=10_000_000),
                       lambda s:s.update(reserve=1)):
            s=state(); change(s)
            with self.assertRaisesRegex(ValueError,'cash reconciliation'):
                terminal_cash(s,100_000_000,10_000_000)

    def test_live_stage_or_incorrect_reward_rule_cannot_be_reported_as_terminal(self):
        for change in (lambda s:s['stages']['stage'].update(status='active'),
                       lambda s:s['stages']['stage']['terms'].update(payout=3_000_000),
                       lambda s:s['stages']['stage']['terms'].update(pricing_rule='brownian-first-mode-v1'),
                       lambda s:s['stages']['stage'].update(funded=0)):
            s=state(); change(s)
            with self.assertRaises(ValueError):
                terminal_cash(s,100_000_000,10_000_000)


if __name__ == '__main__':
    unittest.main()
