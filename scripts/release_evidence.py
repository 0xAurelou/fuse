#!/usr/bin/env python3
"""Assemble reproducible release evidence, preserving every unmet release gate.

Read-only with respect to existing captures and implementations. Writes a new
output directory only; never starts a capture, trades, deploys or funds anything.
"""
import argparse
from fractions import Fraction
import hashlib
import json
from pathlib import Path

from release_accounting import DAY, PAYOUTS, Ledger, Limits
from release_lp_bootstrap import bootstrap_evidence

ROOT = Path(__file__).resolve().parent.parent
USDC = 1_000_000
PACKET = ROOT / '.local/capture-readiness/20261029-prospective-quote-economics-v1'
SOURCE_FILES = (
    'docs/RELEASE_ECONOMIC_SPEC.md', 'docs/RELEASE_READINESS.md',
    'docs/RELEASE_RUNBOOK.md', 'docs/release/operating-budget.json',
    'scripts/release_accounting.py', 'scripts/test_release_accounting.py',
    'scripts/release_evidence.py', 'scripts/test_release_evidence.py',
    'src/LPVault.sol', 'src/LPShareVault.sol', 'src/RedemptionReserve.sol',
    'src/FUSEToken.sol', 'src/RewardDistributor.sol',
    'engine/internal/engine/accounting.go', 'engine/internal/engine/reducer.go',
    'engine/internal/engine/types.go', 'engine/internal/engine/pricing.go',
    'engine/internal/rewards/rewards.go', 'frontend/lib/trading.ts',
    'docs/RELEASE_PRICING_VALIDATION.md',
    'scripts/release_pricing.py', 'scripts/research_release_pricing.py',
    'scripts/audit_release_pricing.py', 'scripts/test_release_pricing.py',
    'scripts/test_release_pricing_audit.py',
    'docs/RELEASE_EMPIRICAL_PRICING.md',
    'scripts/release_empirical_pricing.py', 'scripts/research_release_empirical.py',
    'scripts/audit_release_empirical.py', 'scripts/test_release_empirical.py',
    'engine/cmd/fuse-research/main.go', 'engine/cmd/fuse-research/main_test.go',
    'docs/RELEASE_LP_BOOTSTRAP.md', 'scripts/release_lp_bootstrap.py',
    'scripts/test_release_lp_bootstrap.py', 'src/LPIncentiveDistributor.sol',
    'src/AllocationEscrows.sol',
    'docs/NATIVE_PPB_INTEGRATION.md', 'docs/REDEMPTION_PAUSE_INTEGRATION.md',
    'docs/release/lp-bootstrap-review.json', 'docs/release/redemption-pause-review.json',
    'docs/LP_PARTICIPATION.md', 'scripts/research_adaptive_native_ppb.py',
    'scripts/test_release_native_ppb.py', 'scripts/audit_native_ppb.py',
    'scripts/test_release_native_audit.py', 'scripts/verify_ppb_legacy.py',
    'scripts/release_native_evidence.py', 'scripts/test_release_native_evidence.py',
    'scripts/generate_lp_bootstrap_vectors.py', 'test/fixtures/LPBootstrapVectors.sol',
    'test/LPBootstrap.t.sol', 'test/RedemptionPause.t.sol',
    'engine/internal/engine/ppb_table_test.go', 'engine/internal/localdev/tokenomics.go',
    'engine/internal/localdev/tokenomics_pause_test.go',
    'docs/RELEASE_CAPITAL_INTEGRATION.md',
    'engine/internal/engine/capital.go', 'engine/internal/engine/capital_test.go',
    'engine/internal/engine/capital_invariants_test.go', 'engine/internal/engine/oracle.go',
    'engine/internal/api/server.go', 'engine/internal/api/capital_metrics_test.go',
    'docs/release/native-capital-review.json',
    'docs/RELEASE_DAILY_LP_INTEGRATION.md', 'docs/release/daily-lp-review.json',
    'src/DailyLPVault.sol', 'src/DailyBetCustody.sol', 'test/DailyLP.t.sol',
    'engine/internal/engine/settlement_outcome.go',
    'engine/internal/engine/settlement_outcome_test.go',
    'scripts/generate_daily_accounting_vectors.py',
    'scripts/test_daily_accounting_vectors.py', 'test/fixtures/DailyAccountingVectors.sol',
    'docs/RELEASE_DAILY_RELAY.md', 'engine/internal/contracts/daily_typed.go',
    'engine/internal/contracts/daily_typed_test.go',
    'engine/internal/dailyrelay/journal.go', 'engine/internal/dailyrelay/journal_test.go',
    'engine/internal/dailyrelay/reader.go', 'engine/internal/dailyrelay/plan.go',
    'engine/internal/dailyrelay/reconcile.go', 'engine/internal/dailyrelay/store.go',
    'engine/internal/dailyrelay/proof_test.go',
    'engine/internal/engine/financial_source_test.go',
    'engine/internal/engine/sequencer.go', 'engine/internal/storage/postgres.go',
    'docs/release/daily-relay-source-review.json',
    'engine/internal/dailyrelay/outbox.go', 'engine/internal/dailyrelay/outbox_test.go',
    'engine/internal/contracts/rpc.go', 'engine/internal/contracts/rpc_test.go',
    'engine/internal/localdev/daily_outbox_e2e_test.go',
    'docs/release/daily-outbound-review.json',
    'engine/internal/dailyrelay/void.go', 'engine/internal/dailyrelay/void_store.go',
    'engine/internal/dailyrelay/void_test.go',
    'engine/internal/localdev/daily_void_e2e_test.go', 'docs/release/daily-void-review.json',
    'engine/internal/dailyrelay/replacement.go', 'engine/internal/dailyrelay/replacement_test.go',
    'engine/internal/localdev/daily_replacement_e2e_test.go', 'docs/release/daily-replacement-review.json',
    'engine/internal/dailyrelay/external.go', 'engine/internal/dailyrelay/external_test.go',
    'engine/internal/dailyrelay/historical_generation.go',
    'engine/internal/localdev/daily_external_e2e_test.go', 'docs/release/daily-external-review.json',
    'engine/internal/localdev/daily_relay_e2e_test.go', 'scripts/daily_settlement_e2e.py',
)


def read(path):
    return json.loads(Path(path).read_text())


def sha(path):
    result = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1 << 20), b''):
            result.update(block)
    return result.hexdigest()


def verify_hash(path, expected):
    if sha(path) != expected:
        raise ValueError('evidence hash mismatch: ' + str(path))


def audit_cash(row):
    """Independent integer cash check against sealed hypothetical ticket cases."""
    accounts = row['accounts']
    placed, resolved, censored = (row[k] for k in
        ('selected_grid_entries', 'resolved_grid_entries', 'censored_grid_entries'))
    wins = row['survived_grid_entries']
    if accounts not in (1, 3) or not 0 <= wins <= resolved or placed != resolved + censored:
        raise ValueError('invalid ticket counts')
    gross = (resolved - 2 * wins) * accounts * USDC
    turnover = placed * accounts * USDC
    if (row['lp_gross_assuming_censored_refund_usdc_units'] != gross or
            row['customer_gross_usdc_units'] != -gross or
            row['placed_turnover_usdc_units'] != turnover or
            row['placed_tickets'] != placed * accounts):
        raise ValueError('paper cash conservation mismatch')
    costs = row['cost_sensitivity']
    if [c['expense_bps'] for c in costs] != [0, 10, 50, 100]:
        raise ValueError('incomplete expense sensitivity')
    for cost in costs:
        expense = turnover * cost['expense_bps'] // 10_000
        net = gross - expense
        if (cost['allocated_expense_usdc_units'] != expense or
                cost['lp_net_assuming_censored_refund_usdc_units'] != net or
                cost['lp_net_lower_if_all_censored_survive_usdc_units'] != net - censored * accounts * USDC or
                cost['lp_net_upper_if_all_censored_fail_usdc_units'] != net + censored * accounts * USDC):
            raise ValueError('expense/censoring cash mismatch')


def pricing_evidence(packet):
    packet = Path(packet)
    protocol, frozen, result = (read(packet / n) for n in ('protocol.json', 'freeze.json', 'result.json'))
    verify_hash(packet / 'protocol.json', frozen['protocol_sha256'])
    if result['protocol_sha256'] != frozen['protocol_sha256']:
        raise ValueError('result uses different protocol')
    for name, expected in protocol['files_sha256'].items():
        verify_hash(packet / name, expected)
    for name, key in (('cases.jsonl', 'cases_sha256'),
                      ('entry-decisions.jsonl.gz', 'entry_decisions_sha256')):
        verify_hash(packet / name, result[key])
    compatibility = Path(protocol['compatibility_directory'])
    verify_hash(compatibility / 'analysis.json', result['analysis_sha256'])
    verify_hash(compatibility / 'analysis-predictions.jsonl.gz', result['predictions_sha256'])
    analysis = read(compatibility / 'analysis.json')
    trial = Path(protocol['original_directory'])
    verify_hash(trial / 'receipts.jsonl', analysis['receipts_sha256'])
    if (result['completed'] is not True or result['software_fixture'] is not False or
            result['original_terminal_status_preserved'] != read(trial / 'status.json')['state'] or
            result['collection_quality_met'] != analysis['collection_quality_met'] or
            result['economics_validated'] is not False or result['production_approved'] is not False):
        raise ValueError('inconsistent scope or completion evidence')
    cases = [json.loads(line) for line in (packet / 'cases.jsonl').open()]
    if len(cases) != result['cases'] or len(cases) != 780:
        raise ValueError('incomplete frozen case grid')
    for row in cases:
        audit_cash(row)
    selected = [r for r in cases if r['candidate'] == analysis['primary_candidate'] and
                r['mode'] == 'continuous' and r['interval'] == 'full' and r['accounts'] == 1]
    if len(selected) != 13 or len({r['strategy'] for r in selected}) != 13:
        raise ValueError('incomplete primary strategy report')
    return dict(protocol_sha256=result['protocol_sha256'], result_sha256=sha(packet/'result.json'),
        cases_sha256=result['cases_sha256'], predictions_sha256=result['predictions_sha256'],
        independent_cash_cases_checked=len(cases), expense_bounds_checked=4*len(cases),
        original_trial_state=result['original_terminal_status_preserved'],
        collection_quality_met=result['collection_quality_met'],
        healthy_windows=analysis['healthy_windows'], grid_windows=analysis['grid_windows'],
        actual_funded_admission=False, release_7_to_10_percent_model=False,
        primary_all_13_strategies=selected,
        coverage=[dict(asset=a, payout=m, duration_ms=30_000,
                       native_production_pricing_validated=False,
                       note='BTC 2x supplemental research only; original quality failed'
                       if a == 'BTC' and m == 2 else 'No release-validation evidence supplied')
                  for a in ('BTC', 'ETH', 'HYPE') for m in PAYOUTS])


def illustrative_limits():
    return Limits(per_bet=25_000*USDC,
                  per_market={a: 100_000*USDC for a in ('BTC', 'ETH', 'HYPE')},
                  total=200_000*USDC, admission_buffer=25_000*USDC,
                  distribution_buffer=50_000*USDC, backing_buffer=75_000*USDC)


def capital_evidence():
    start = 1792972800000  # 2026-10-26 00:00 UTC, fixed reproducible clock
    policy = illustrative_limits()
    ledger = Ledger(start, policy)
    ledger.deposit('assumed LP', 250_000*USDC, start)
    ledger.paused = False
    decisions = []
    for asset in ('BTC', 'ETH', 'HYPE'):
        for payout in PAYOUTS:
            key = asset + '-' + str(payout)
            try:
                ledger.accept(key, asset, 50*USDC, payout, start+1)
                accepted, rejection = True, None
            except ValueError as err:
                accepted, rejection = False, str(err)
            decisions.append(dict(asset=asset, payout=payout, stake_usdc_units=50*USDC,
                accepted=accepted, rejection=rejection,
                single_bet_stake_ceiling_from_net_liability_cap=policy.per_bet//(payout-1)))
    worst = ledger.open_exposure
    for key in ledger.bets:
        ledger.resolve(key, 'win', start+30_001)
    known = ledger.win_payable
    for key in ledger.bets:
        ledger.settle_cash(key, start+30_002)
    ledger.check()
    return dict(kind='deterministic fully funded simultaneous-maximum-winner reference stress',
        assumptions='Illustrative limits only; no market calibration, native integration or probability model.',
        calibrated_production_limits=False, bankroll_usdc_units=250_000*USDC,
        exposure_before_results=worst, recognized_unfunded_wins=known,
        final_cash_usdc_units=ledger.cash, accepted=sum(r['accepted'] for r in decisions),
        rejected=sum(not r['accepted'] for r in decisions),
        obligations_funded=True, backing_used_as_lp_capital=False, decisions=decisions)


def fraction(value):
    return dict(numerator=value.numerator, denominator=value.denominator, decimal=float(value))


def incentive_evidence():
    expected = []
    for edge in (700, 850, 1000):
        for payout in PAYOUTS:
            survival = Fraction(10_000-edge, 10_000*payout)
            for rate in (200, 1000):
                # Continuous-value expectation: integer ticket rounding, costs,
                # selection and future FUSE appreciation are deliberately absent.
                reward = Fraction(rate, 10_000) * (1-survival + survival/9)
                ev = reward - Fraction(edge, 10_000)
                expected.append(dict(assumed_edge_bps=edge, payout=payout, loss_reward_bps=rate,
                                     player_expected_return_before_costs=fraction(ev)))
    lp_player = []
    for recovery in (False, True):
        for rate in (200, 1000):
            start = 1792972800000
            ledger = Ledger(start, illustrative_limits())
            lot = ledger.deposit('LP also playing', 250_000*USDC, start)
            ledger.paused = False
            if recovery:
                ledger.accept('earlier external win', 'BTC', 1000*USDC, 2, start+1)
                ledger.resolve('earlier external win', 'win', start+30_001)
                ledger.settle_cash('earlier external win', start+30_002)
                ledger.close(ledger.cutoff, ledger.cutoff, 0, 0, 0)
            baseline = ledger.lots[lot].equity
            at = ledger.clock+1
            stake = 100*USDC
            ledger.accept('deliberate self loss', 'BTC', stake, 2, at)
            ledger.resolve('deliberate self loss', 'loss', at+1)
            ledger.settle_cash('deliberate self loss', at+2)
            row = ledger.close(ledger.cutoff, ledger.cutoff, 0, 0, 0)
            nominal_reward = stake*rate//10_000
            net = ledger.lots[lot].equity-baseline-stake+nominal_reward
            lp_player.append(dict(loss_carryforward_exists=recovery, stake_usdc_units=stake,
                loss_reward_bps=rate, daily_protocol_fee=row['fee'],
                nominal_reward_usdc_units=nominal_reward, joint_lp_player_change_usdc_units=net,
                conditions='100% LP ownership, genuinely losing bet, no additional backing gap, '
                           'funded nominal reward, zero costs; this is an attack diagnostic, not a verified live exploit'))
    return dict(assumed_probability_sensitivities=expected, deliberate_loss_lp_player_cases=lp_player,
        welcome_nominal_entitlement_cap_usdc_units=10_000*USDC,
        standard_initial_nominal_entitlement_cap_usdc_units=10_000*USDC,
        future_standard_credit_rule='floor(90% of each confirmed new backing transfer), credited once',
        global_cap_on_all_future_fuse_value_proven=False,
        limitation='Allowance bounds nominal accepted minima. Released FUSE rights may appreciate; '
                   'rounding and future reserve funding mean this is not a $10k cap on all future redemption value. '
                   'Onchain campaign and inventory reservations are not implemented.')


def release_pricing_evidence(packet):
    """Attach a source-bound software audit without promoting it to a review."""
    from research_release_pricing import verify_plan
    from release_pricing import ASSETS, DAY, DELAYS, EDGES, GRID, PAYOUTS, STRATEGIES
    packet = Path(packet).resolve()
    # Archived evidence remains about its immutable source snapshot. Subsequent
    # product changes must be visible, not invalidate or relabel that history.
    plan = verify_plan(packet, require_current_sources=False)
    result, audit = read(packet/'result.json'), read(packet/'audit.json')
    protocol_hash = sha(packet/'protocol.json')
    if (result['protocol_sha256'] != protocol_hash or audit['protocol_sha256'] != protocol_hash or
            audit['result_sha256'] != sha(packet/'result.json') or audit['passed'] is not True or
            audit['auditor_sha256'] != sha(ROOT/'scripts/audit_release_pricing.py') or
            audit['independent_external_review'] is not False or
            audit['production_pricing_validated'] is not False or
            result['production_pricing_validated'] is not False):
        raise ValueError('release pricing audit/scope binding differs')
    for name, expected in result['artifacts_sha256'].items():
        verify_hash(packet/name, expected)
    if (audit['raw_envelopes_reconstructed'] != result['path_envelopes'] or
            audit['strategy_cases_replayed'] != result['daily_strategy_cases'] or
            audit['joint_cases_replayed'] != result['daily_joint_cases'] or
            audit['native_formula_vectors'] != 108 or result['native_formula_vectors_verified'] != 108 or
            result['native_admission_replayed'] is not False or
            result['funded_liabilities_or_rewards_evaluated'] is not False):
        raise ValueError('release pricing audit coverage differs')
    days = result['complete_common_dates']
    if (not days or days != sorted(set(days)) or days != plan['days'] or
            result['unique_grid_opportunities'] != len(days)*len(ASSETS)*DAY//GRID or
            result['path_envelopes'] != len(days)*len(ASSETS)*len(DELAYS)*DAY//GRID or
            result['daily_strategy_cases'] != len(days)*len(ASSETS)*len(EDGES)*len(PAYOUTS)*len(DELAYS)*len(STRATEGIES) or
            result['daily_joint_cases'] != len(days)*len(EDGES)*len(PAYOUTS)*len(DELAYS)):
        raise ValueError('release pricing schedule coverage differs')
    immediate = [r for r in result['summary'] if r['delay_ms'] == 0 and r['strategy'] == 'all_offered']
    wanted = {(a, m, e) for a in ASSETS for m in PAYOUTS for e in EDGES}
    if (len(immediate) != len(wanted) or
            {(r['asset'], r['multiplier'], r['edge_bps']) for r in immediate} != wanted):
        raise ValueError('incomplete immediate release control grid')
    return dict(directory=str(packet), protocol_sha256=protocol_hash,
        result_sha256=sha(packet/'result.json'), audit_sha256=sha(packet/'audit.json'),
        audited_sources_sha256=plan['source_sha256'],
        current_sources_match=all(sha(ROOT/n) == h for n, h in plan['source_sha256'].items()),
        changed_current_sources=[n for n, h in plan['source_sha256'].items() if sha(ROOT/n) != h],
        unique_grid_opportunities=result['unique_grid_opportunities'],
        raw_envelopes_reconstructed=result['path_envelopes'],
        strategy_cases_replayed=result['daily_strategy_cases'],
        joint_cases_replayed=result['daily_joint_cases'],
        native_formula_vectors_verified=result['native_formula_vectors_verified'],
        days=result['complete_common_dates'], immediate_all_108_controls=immediate,
        immediate_lp_best_case_negative=sum(r['gross_lp_if_censored_all_fail_usdc_units'] < 0 for r in immediate),
        production_pricing_validated=False, independent_external_review=False,
        native_admission_replayed=False, funded_liabilities_or_rewards_evaluated=False)


def empirical_pricing_evidence(packet):
    """Retain the full fitted development grid, including refusals and failures."""
    from research_release_empirical import verify
    from release_pricing import ASSETS, DAY, DELAYS, EDGES, GRID, PAYOUTS, STRATEGIES
    packet = Path(packet).resolve()
    plan = verify(packet, current=False)
    baseline = release_pricing_evidence(plan['baseline_directory'])
    result, audit = read(packet/'result.json'), read(packet/'audit.json')
    protocol_hash = sha(packet/'protocol.json')
    scope = ('production_pricing_validated', 'goal_complete')
    if (result['protocol_sha256'] != protocol_hash or audit['protocol_sha256'] != protocol_hash or
            audit['passed'] is not True or audit['result_sha256'] != sha(packet/'result.json') or
            audit['auditor_sha256'] != plan['source_sha256']['scripts/audit_release_empirical.py'] or
            audit['independent_external_review'] is not False or
            any(record[k] is not False for record in (result, audit) for k in scope) or
            result['native_admission_replayed'] is not False or
            result['funded_bankroll_evaluated'] is not False or result['fresh_holdout'] is not False or
            result['previously_inspected_development_data'] is not True or
            plan['new_independent_holdout'] is not False or plan['paired_native_admission'] is not False or
            plan['funded_bankroll_replayed'] is not False or plan['production_policy_changed'] is not False):
        raise ValueError('empirical pricing audit/scope binding differs')
    artifacts = {'forecasts.jsonl.gz', 'models.jsonl.gz', 'cases.jsonl', 'joint.jsonl', 'native-quantization.jsonl'}
    if set(result['artifacts_sha256']) != artifacts:
        raise ValueError('empirical pricing artifacts incomplete')
    for name, expected in result['artifacts_sha256'].items():
        verify_hash(packet/name, expected)
    days = result['complete_common_dates']
    grids = len(days)*len(ASSETS)*DAY//GRID
    cases = len(days)*len(ASSETS)*len(PAYOUTS)*len(EDGES)*len(DELAYS)*len(STRATEGIES)
    joint = len(days)*len(PAYOUTS)*len(EDGES)*len(DELAYS)
    if (not days or days != sorted(set(days)) or days != plan['days'] or days != baseline['days'] or
            result['unique_asset_grid_opportunities'] != grids or
            result['forecasted_asset_payout_edge_opportunities'] != grids*len(PAYOUTS)*len(EDGES) or
            audit['forecasts_reconstructed'] != result['forecasted_asset_payout_edge_opportunities'] or
            audit['cash_cases_replayed'] != result['daily_strategy_cases'] or result['daily_strategy_cases'] != cases or
            audit['joint_cases_checked'] != result['daily_joint_cases'] or result['daily_joint_cases'] != joint or
            audit['native_arithmetic_vectors_reexecuted'] != result['native_quantization_vectors']):
        raise ValueError('empirical pricing audit coverage differs')
    wanted = {(a,m,e,d,s) for a in ASSETS for m in PAYOUTS for e in EDGES for d in DELAYS for s in STRATEGIES}
    if (len(result['summary']) != len(wanted) or
            {(r['asset'],r['multiplier'],r['edge_bps'],r['delay_ms'],r['strategy']) for r in result['summary']} != wanted):
        raise ValueError('empirical pricing full summary grid differs')
    immediate = [r for r in result['summary'] if r['delay_ms'] == 0 and r['strategy'] == 'all_offered']
    changed = [n for n,h in plan['source_sha256'].items() if sha(ROOT/n) != h]
    return dict(directory=str(packet), protocol_sha256=protocol_hash,
        result_sha256=sha(packet/'result.json'), audit_sha256=sha(packet/'audit.json'),
        baseline=baseline, audited_sources_sha256=plan['source_sha256'],
        current_sources_match=not changed, changed_current_sources=changed,
        days=days, unique_asset_grid_opportunities=grids,
        forecasted_asset_payout_edge_opportunities=result['forecasted_asset_payout_edge_opportunities'],
        cash_cases_replayed=cases, joint_cases_checked=joint,
        native_arithmetic_vectors_reexecuted=result['native_quantization_vectors'],
        immediate_all_108_challengers=immediate,
        immediate_combinations_with_no_offers=sum(r['quote_available'] == 0 for r in immediate),
        immediate_combinations_with_offers=sum(r['quote_available'] > 0 for r in immediate),
        immediate_lp_best_case_negative=sum(r['quote_available'] > 0 and
            r['gross_lp_if_censored_all_fail_usdc_units'] < 0 for r in immediate),
        previously_inspected_development_data=True, fresh_holdout=False,
        native_admission_replayed=False, funded_bankroll_evaluated=False,
        production_pricing_validated=False, independent_external_review=False, goal_complete=False)


def build(output, packet=PACKET, release_pricing_packet=None, native_packet=None, empirical_packet=None):
    output = Path(output)
    if output.exists():
        raise FileExistsError('preserve prior release evidence: ' + str(output))
    sources = {name: sha(ROOT/name) for name in SOURCE_FILES}
    pricing = pricing_evidence(packet)
    capital = capital_evidence()
    incentives = incentive_evidence()
    bootstrap = bootstrap_evidence()
    release_prices = release_pricing_evidence(release_pricing_packet) if release_pricing_packet else None
    empirical = empirical_pricing_evidence(empirical_packet) if empirical_packet else None
    native = None
    if native_packet:
        from release_native_evidence import native_evidence
        native = native_evidence(native_packet)
    if sources != {name: sha(ROOT/name) for name in SOURCE_FILES}:
        raise ValueError('release sources changed during evidence assembly')
    report = dict(version=4, production_approved=False, goal_complete=False,
                  gate_status={str(n): 'open' for n in range(1, 11)},
                  source_sha256=sources, pricing=pricing, release_pricing_controls=release_prices,
                  native_adaptive_replay=native,
                  empirical_pricing_challenger=empirical,
                  capital=capital, incentives=incentives, lp_bootstrap=bootstrap,
                  operating_budget=read(ROOT/'docs/release/operating-budget.json'))
    output.mkdir(parents=True)
    path = output/'evidence.json'
    path.write_text(json.dumps(report, indent=2, allow_nan=False)+'\n')
    lines = ['# Release evidence — candidate 1', '',
        '**Production approval: NO. All ten gates remain open.**', '',
        'Daily UTC closes, permanent loss carryforward and partial free LP withdrawals are the current candidate.', '',
        '## Sealed BTC 2× primary continuous replay', '',
        f"Independent cash checks: {pricing['independent_cash_cases_checked']} cases, "
        f"{pricing['expense_bounds_checked']} expense/censoring bounds. "
        f"Original trial: {pricing['original_trial_state']}; quality met: {pricing['collection_quality_met']}.", '',
        'All 13 predeclared rules follow. These reuse one dependent, quality-failed path; '
        'refund assumptions, illustrative costs and execution limitations remain. No release pricing is validated.', '',
        '| Rule | Tickets | Censored | Player gross with refunds ($) | LP gross with refunds ($) |',
        '| --- | ---: | ---: | ---: | ---: |']
    for r in pricing['primary_all_13_strategies']:
        lines.append(f"| {r['strategy']} | {r['placed_tickets']} | {r['censored_grid_entries']} | "
                     f"{r['customer_gross_usdc_units']/USDC:.2f} | {r['lp_gross_assuming_censored_refund_usdc_units']/USDC:.2f} |")
    if release_prices:
        lines += ['', '## Full-menu formula rejection controls', '',
            f"{release_prices['unique_grid_opportunities']:,} distinct asset/grid opportunities on "
            f"{len(release_prices['days'])} matched historical dates. All "
            f"{release_prices['native_formula_vectors_verified']} native formula settings were verified; "
            f"{release_prices['raw_envelopes_reconstructed']:,} raw envelopes, "
            f"{release_prices['strategy_cases_replayed']:,} strategy cases and "
            f"{release_prices['joint_cases_replayed']:,} joint-asset cases were cross-checked.", '',
            f"{release_prices['immediate_lp_best_case_negative']} of 108 immediate controls have negative LP gross "
            'even if every censored ticket loses for the player. This rejects the tested '
            'unfitted Brownian assumptions, including the 7–10% edge-label variants. '
            'It is not a funded replay, independent external review or validation of '
            'the separate adaptive model. Full controls remain in the bound pricing packet.']
    if empirical:
        lines += ['', '## Fitted historical challenger', '',
            f"All {empirical['forecasted_asset_payout_edge_opportunities']:,} asset/payout/edge opportunities, "
            f"{empirical['cash_cases_replayed']:,} daily strategy cases and "
            f"{empirical['joint_cases_checked']:,} joint cases were software-checked. "
            f"{empirical['immediate_combinations_with_no_offers']} of the 108 immediate combinations "
            'made no offers. '
            f"{empirical['immediate_lp_best_case_negative']} of the "
            f"{empirical['immediate_combinations_with_offers']} combinations with offers "
            'lose LP gross even under the LP-favorable censoring bound. '
            'Refused products remain in the denominator and do not count as calibrated. '
            'This fits strictly earlier matured paths on the same previously inspected nonconsecutive dates. '
            'All results and refusal reasons remain in the bound packet. Native checks cover integer '
            'quantization only; there is no paired admission, funded-bankroll replay, new holdout, '
            'independent external review or production approval.']
    if native:
        lines += ['', '## Exact-width funded native replay', '',
            'All four frozen profiles use the full original eight-hour paired tape, '
            'exact sealed BTC 2x widths, hypothetical $250k LP cash and $1,000 per '
            'trader. The original trial failed quality and targeted 4%, not 7–10%. '
            'This is retrospective integration evidence; daily fees, rewards, '
            'LP ownership/withdrawals and a live adaptive provider are not evaluated.', '',
            f"The software audit reexecuted {native['all_native_responses_reexecuted']:,} "
            f"native responses and {native['all_original_receipt_replays']:,} receipt "
            'applications across the four reused paths. Four independent cash checks '
            'and sixteen illustrative cost checks pass. This is not independent external review.', '',
            '| Profile | Accepted | Healthy comparisons | Censored-path stages | LP gross ($) | Peak liability ($) |',
            '| --- | ---: | ---: | ---: | ---: | ---: |']
        for r in native['cases']:
            lines.append(f"| {r['profile']['name']} | {r['accepted_stages']} | "
                f"{r['healthy_outcome_comparisons']} | {r['accepted_censored_path_stages']} | "
                f"{r['lp_gross_pnl_usdc_units']/USDC:.2f} | {r['peak_exposure_usdc_units']/USDC:.2f} |")
        lines += ['', 'Native adjudication retains observed losses on some paths '
            'the analyzer censored; those paths are not all assumed refunded. '
            'Synchronized wallets are dependent exposures. The maximum observed '
            'liability is only $27 against $250,000 hypothetical LP cash; this '
            'does not calibrate production capital limits. Exposure and known '
            'debt maxima are recomputed from every software-audited response, '
            'with observed cash headroom in evidence.json. The exact source snapshot '
            'and differences from current sources are bound in evidence.json; no release gate is closed.']
    lines += ['', '## Illustrative capital stress', '',
        f"27 concurrent $50 ticket attempts: {capital['accepted']} accepted and {capital['rejected']} rejected. "
        f"Every accepted ticket wins simultaneously: ${capital['recognized_unfunded_wins']/USDC:,.2f} "
        f"recognized net LP obligations; cash after funding all wins ${capital['final_cash_usdc_units']/USDC:,.2f}.", '',
        'These are explicit example caps and buffers, not calibrated production limits. '
        'The complete 27-pair pricing coverage grid in evidence.json remains unvalidated.', '',
        'The separate native capital-control candidate now enforces per-bet/market '
        'limits with market winning-debt attribution for custody-funded single-stage '
        'bets. Its synthetic stress fills $200k of liabilities against $250k LP '
        'cash and pays all customers during pause, leaving $50k: an 80% LP loss '
        'permitted by these unapproved example limits. Operator metrics expose '
        'the controls. Source and tests are bound here; see '
        'docs/RELEASE_CAPITAL_INTEGRATION.md and the capital verification packet. '
        'The archived eight-hour replay did not enable this rule. Daily LP '
        'capital-account contracts and free withdrawals remain unreconciled.', '',
        '## LP/player incentive cases', '',
        '| Existing loss recovery | Loss reward rate | Nominal reward ($) | Protocol fee ($) | Joint LP/player change ($) |',
        '| --- | ---: | ---: | ---: | ---: |']
    for r in incentives['deliberate_loss_lp_player_cases']:
        lines.append(f"| {r['loss_carryforward_exists']} | {r['loss_reward_bps']/100:g}% | "
                     f"{r['nominal_reward_usdc_units']/USDC:.2f} | {r['daily_protocol_fee']/USDC:.2f} | "
                     f"{r['joint_lp_player_change_usdc_units']/USDC:.2f} |")
    lines += ['', 'Assumes 100% LP ownership, no backing gap and zero costs; no live exploit is claimed. '
        'The $10k welcome plus $10k standard seed allowances bound nominal accepted minima only. '
        'Future token appreciation/redemption proceeds are not bounded by those labels.', '',
        '## Below-$3M LP bootstrap candidate', '',
        'The user selected $250k LP and $125k backing funding targets and requested '
        'LP incentives below $3M aggregate equity. The offline candidate tapers '
        'eligible capital-time rewards to zero at $3M, subject to actual liability-time. '
        'It preserves the existing maximum 50M FUSE allocation, 90-day campaign '
        'and 30-day vesting; withdrawals cannot restart or extend the campaign. '
        'An opt-in configureBootstrapCampaign contract path implements the taper '
        'and has local verification. It is not activated or approved for production; '
        'its legacy share vault still needs reconciliation with daily capital '
        'accounts and free withdrawals. The numeric grid here is the exact offline reference.', '',
        'The full tranche is $6,250 at the assumed initial 125k/1B backing ratio, '
        'not a future dollar guarantee or a token market price. Even wholly '
        'self-funded LP/player qualifying activity remains bounded by 50M tokens; '
        'utilization does not prove organic demand. Exact grid amounts and '
        'limitations are in evidence.json and the linked specification.', '',
        '## Launch funding and distribution', '',
        'LP/backing funding targets are selected but unverified. Operations '
        'cash amounts and monthly spending limits are omitted at the user\'s '
        'request; funding verification remains open. Worldwide distribution '
        'is recorded as intent, with no jurisdiction or channel approval evidenced.', '',
        'Source SHA-256 bindings and the original evidence bindings are in evidence.json. '
        'Independent reviews, real funding and economic sign-off remain missing.', '']
    (output/'report.md').write_text('\n'.join(lines))
    manifest = {n: sha(output/n) for n in ('evidence.json', 'report.md')}
    (output/'manifest.json').write_text(json.dumps(manifest, indent=2)+'\n')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--pricing-packet', type=Path, default=PACKET)
    parser.add_argument('--release-pricing-packet', type=Path)
    parser.add_argument('--native-packet', type=Path)
    parser.add_argument('--empirical-packet', type=Path)
    args = parser.parse_args()
    result = build(args.output, args.pricing_packet, args.release_pricing_packet, args.native_packet, args.empirical_packet)
    print(json.dumps(dict(production_approved=False, goal_complete=False,
                          pricing_cash_cases=result['pricing']['independent_cash_cases_checked'],
                          output=str(args.output))))
