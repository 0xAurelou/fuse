#!/usr/bin/env python3
"""Recorded HyperCore + actual Go reducer + contract-matched LP economics.

No market resampling, invented prices, parameter fitting, RPC or transactions.
Demand variants retain nested subsets of recorded wallets, including their real
funding and decisions. Rejected dependent actions stay rejected. LP runoff is
explicitly zero trading, not 31 days of observed market evidence.
"""
import argparse
from collections import Counter
from copy import deepcopy
from decimal import Decimal
from fractions import Fraction
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

from contract_lp_model import LPModel, USDC, DAY, BUDGET, ceildiv
from calibrate_pricing import observations, healthy_windows, survival, wilson

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_RUNS = ('20261026-002626', '20261026-012628')
GAS_ASSUMPTIONS = dict(settlement=250000, trader_deposit=80000,
                       trader_withdrawal=100000, lp_deposit=180000,
                       exit_request=120000, exit_fulfill=180000, exit_claim=100000,
                       reserve_funding=140000, lp_reward_publish=180000,
                       lp_reward_claim=150000)
DEFAULT_COSTS = [
    dict(name='zero-cost reference', gas_price_gwei='0', native_usd='0', operating_usd_per_day='0'),
    dict(name='assumed low costs', gas_price_gwei='0.1', native_usd='30', operating_usd_per_day='100'),
    dict(name='assumed high costs', gas_price_gwei='1', native_usd='60', operating_usd_per_day='1000'),
]


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'))


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def read_jsonl(path):
    with path.open() as stream:
        for line in stream:
            yield json.loads(line)


def choose_wallets(wallets, fraction_bps):
    if not 0 <= fraction_bps <= 10000:
        raise ValueError('invalid retained demand fraction')
    ordered = sorted(wallets, key=lambda owner: hashlib.sha256(owner.encode()).hexdigest())
    return set(ordered[:len(ordered) * fraction_bps // 10000])


class Bridge:
    def __init__(self, binary, audit=None):
        self.proc = subprocess.Popen([str(binary)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     text=True, bufsize=1)
        self.audit = audit
        self.head = ''
        self.count = 0

    def send(self, request, allow_reject=False):
        self.proc.stdin.write(canonical(request) + '\n')
        self.proc.stdin.flush()
        raw = self.proc.stdout.readline()
        if not raw:
            raise RuntimeError(f'research reducer stopped: {self.proc.poll()}')
        response = json.loads(raw)
        self.record(dict(request=request, response=response))
        if not response['ok'] and not allow_reject:
            raise ValueError(response['error'])
        return response

    def record(self, value):
        if self.audit is not None:
            record = dict(previous=self.head, **value)
            self.head = hashlib.sha256(canonical(record).encode()).hexdigest()
            self.audit.write(canonical(dict(hash=self.head, **record)) + '\n')
            self.count += 1

    def close(self):
        self.proc.stdin.close()
        self.proc.stdout.close()
        code = self.proc.wait(timeout=10)
        if code:
            raise RuntimeError(f'research reducer exit {code}')


def cost_sensitivity(counts, elapsed_seconds, pnl, fee, scenarios):
    gas = sum(counts.get(kind, 0) * units for kind, units in GAS_ASSUMPTIONS.items())
    result = []
    for scenario in scenarios:
        values = [Fraction(str(scenario[key])) for key in
                  ('gas_price_gwei', 'native_usd', 'operating_usd_per_day')]
        if any(x < 0 for x in values):
            raise ValueError('cost assumptions must be nonnegative')
        gas_units = ceildiv((gas * values[0] * values[1] * USDC).numerator,
                            (gas * values[0] * values[1] * USDC).denominator * 10**9)
        operating = values[2] * Fraction(str(elapsed_seconds)) * USDC / DAY
        operating_units = ceildiv(operating.numerator, operating.denominator)
        total = gas_units + operating_units
        result.append(dict(**scenario, estimated_gas_units=gas,
                           assumed_gas_cost_usdc_units=gas_units,
                           assumed_operating_cost_usdc_units=operating_units,
                           assumed_total_cost_usdc_units=total,
                           lp_profit_after_fee_and_allocated_cost_usdc_units=pnl - fee - total,
                           gross_profit_after_allocated_cost_usdc_units=pnl - total))
    return result


class Replay:
    def __init__(self, bridge, directory, retained_bps, costs, external_capital=50000 * USDC):
        self.bridge, self.directory, self.costs = bridge, directory, costs
        self.events = list(read_jsonl(directory / 'journal.jsonl'))
        self.initial = json.loads((directory / 'initial-policy.json').read_text())
        self.original = json.loads((directory / 'final-state.json').read_text())
        wallets = {s['terms']['account'] for s in self.original['stages'].values()}
        self.wallets = choose_wallets(wallets, retained_bps)
        self.retained_bps = retained_bps
        self.start_ms = self.events[0]['command']['at']
        self.end_ms = self.events[-1]['command']['at']
        self.model = LPModel(self.start_ms // 1000)
        self.external_capital = external_capital
        self.counts, self.rejects = Counter(), Counter()
        self.quote_map, self.stage_map, self.withdrawals = {}, {}, {}
        self.deposits = set()
        self.serial = 0
        self.view = None
        self.log = []
        self.max_exposure = 0
        self.last_second = self.start_ms // 1000
        self.exposure = 0
        self.peak_nav = Fraction(1, 10**12)
        self.max_drawdown = Fraction(0)
        self.capture_snapshot = None

    def command(self, c, optional=False):
        self.serial += 1
        c = dict(c, key=f'research/{self.serial}')
        self.advance(c['at'] // 1000)
        response = self.bridge.send(dict(kind='command', command=c), allow_reject=optional)
        if not response['ok']:
            self.rejects[c['kind'] + ': ' + response['error']] += 1
            return None
        self.view = response['value']
        self.exposure = self.view['exposure']
        self.max_exposure = max(self.max_exposure, self.exposure)
        return self.view.get('result')

    def advance(self, second):
        self.model.integrate_liability(self.last_second, second, self.exposure)
        self.model.clock(second)
        self.last_second = second

    def sync(self):
        self.view = self.bridge.send(dict(kind='sync_lp', cash=self.model.cash,
                                          fee=self.model.fee, exit=self.model.reserved))['value']
        nav = Fraction(self.model.assets + 1, self.model.supply + 10**12)
        self.peak_nav = max(self.peak_nav, nav)
        self.max_drawdown = max(self.max_drawdown, (self.peak_nav-nav)/self.peak_nav)

    def note(self, kind, **extra):
        row = dict(kind=kind, second=self.model.now, **self.model.snapshot(), **extra)
        self.log.append(row)
        self.bridge.record(dict(lp_projection=row))

    def settlement(self, at):
        before_profit = self.view['lp_profit']
        result = self.command(dict(kind='paper_settle', at=at))
        pnl = self.view['lp_profit'] - before_profit
        self.counts['settlement'] += 1
        self.model.finalize(pnl, result['required_lp'], self.view['exposure'])
        # The cash change must be the actual Go settlement, not an independent
        # payoff calculation. Only fee/exit liabilities are projected externally.
        if self.model.cash != self.view['lp']:
            raise ValueError('Go/LP cash mismatch at settlement')
        self.sync()
        self.note('settlement', net_lp_pnl=pnl, exposure=self.exposure)

    def bootstrap(self):
        p = deepcopy(self.initial)
        p['mode'] = 'paper'
        self.view = self.bridge.send(dict(kind='init', policy=p))['value']
        if not 0 <= self.external_capital < 250000 * USDC:
            raise ValueError('external capital must be less than initial 250k')
        self.model.deposit('protocol', 250000 * USDC - self.external_capital)
        self.model.finalize(0, p['lp_buffer'], 0)
        self.model.set_phase(1)
        self.model.finalize(0, p['lp_buffer'], 0)
        # Assumed new-deployment allocation, not measured external LP demand.
        self.model.publish_capacity(50000 * USDC, self.model.now + 3600)
        self.lp_owners = ['lp-%02d' % n for n in range(25)] if self.external_capital else []
        self.model.whitelist.update(self.lp_owners)
        for i, owner in enumerate(self.lp_owners):
            amount = self.external_capital // 25 + (i < self.external_capital % 25)
            if amount:
                self.model.deposit(owner, amount)
                self.counts['lp_deposit'] += 1
        self.sync()
        self.note('assumed_new_deployment_bootstrap')

    def apply_recorded(self, event):
        c = deepcopy(event['command'])
        at, kind = c['at'], c['kind']
        self.advance(at // 1000)
        if kind == 'local_block':
            for effect in c['raw']['effects']:
                name = effect['module'] + '.' + effect['event']
                if name == 'CustomerCustodyVault.Deposited' and effect['account'] in self.wallets:
                    self.command(dict(kind='deposit', at=at, actor=effect['account'],
                                      id=effect['id'], amount=effect['amount']))
                    self.deposits.add(effect['id'])
                    self.counts['trader_deposit'] += 1
                elif name == 'CustomerCustodyVault.DepositCredited' and effect['id'] in self.deposits:
                    self.command(dict(kind='ack_deposit', at=at, id=effect['id']))
                elif name == 'SettlementController.CheckpointFinalized':
                    self.settlement(at)
                elif name == 'WithdrawalGateway.Withdrawn' and effect['account'] in self.withdrawals:
                    self.command(dict(kind='paper_pay', at=at, id=self.withdrawals[effect['account']]))
                    self.counts['trader_withdrawal'] += 1
                    del self.withdrawals[effect['account']]
            return
        if kind in ('oracle', 'tick'):
            self.command(c)
        elif kind == 'policy_update':
            c['raw']['mode'] = 'paper'
            self.command(c)
        elif c.get('actor') in self.wallets:
            if kind == 'quote':
                if c.get('previous'):
                    c['previous'] = self.stage_map.get(c['previous'], 'missing-recorded-stage')
                got = self.command(c, optional=True)
                if got:
                    self.quote_map[event['result']['id']] = got['id']
            elif kind == 'enter':
                c['id'] = self.quote_map.get(c['id'], 'missing-recorded-quote')
                got = self.command(c, optional=True)
                if got:
                    self.stage_map[event['result']['id']] = got['id']
            elif kind == 'cashout':
                c['id'] = self.stage_map.get(c['id'], 'missing-recorded-stage')
                self.command(c, optional=True)
            elif kind == 'withdraw':
                got = self.command(c, optional=True)
                if got:
                    self.withdrawals[c['actor']] = got['id']

    def runoff(self):
        """Exercise exits/publication/vesting without generating more market paths."""
        if self.exposure or self.view['active']:
            raise ValueError('retained capture ends with outstanding market risk')
        self.settlement(self.end_ms)
        self.capture_snapshot = self.model.snapshot()
        requests = []
        for owner in self.lp_owners:
            if self.model.shares[owner]:
                requests.append(self.model.request_exit(owner, self.model.shares[owner]))
                self.counts['exit_request'] += 1
        self.note('runoff_exit_requests_no_further_trading')
        # Publish each completed epoch before moving across the next deadline.
        last_published = 0
        for day in range(1, 32):
            at = self.model.start + day * DAY
            if at < self.model.now:
                raise ValueError('capture spans a day; use an epoch scheduler before replaying this source')
            self.advance(at)
            self.model.resume()
            self.model.publish(day)
            last_published = day
            self.counts['lp_reward_publish'] += 1
            if day == 3:  # >48h after the short capture, fresh later zero-risk NAV.
                self.settlement(at * 1000)
                if self.model.fee and self.model.required <= self.model.assets // 2:
                    self.model.resume()
                    self.model.fund_reserve(self.model.fee)
                    self.counts['reserve_funding'] += 1
                    self.sync()
                    self.settlement(at * 1000)
                for request in requests:
                    self.model.fulfill(request)
                    self.counts['exit_fulfill'] += 1
                self.sync()
                self.note('runoff_exits_fulfilled_cash_still_reserved')
                for request in requests:
                    self.model.claim_exit(request)
                    self.counts['exit_claim'] += 1
                self.sync()
                self.note('runoff_exit_claims_paid')
        for owner in self.lp_owners:
            if self.model.earned(1, owner):
                self.model.claim_reward(1, owner)
                self.counts['lp_reward_claim'] += 1
        self.note('runoff_epoch_one_rewards_vested', latest_published=last_published)

    def run(self):
        self.bootstrap()
        for event in self.events:
            self.apply_recorded(event)
        self.runoff()
        state = self.bridge.send(dict(kind='snapshot'))['value']
        stages = state['stages']
        mismatches, term_mismatches = [], []
        for original_id, new_id in self.stage_map.items():
            original, new = self.original['stages'][original_id], stages[new_id]
            if original['status'] != new['status']:
                mismatches.append(dict(original=original_id, recorded=original['status'], replay=new['status']))
            for field in ('index', 'initial', 'stake', 'payout', 'entry_price', 'lower', 'upper', 'duration_ms'):
                if original['terms'][field] != new['terms'][field]:
                    term_mismatches.append(dict(original=original_id, field=field))
        source_stages = [s for s in self.original['stages'].values() if s['terms']['account'] in self.wallets]
        customer_pnl = sum(a['available'] + a['unfunded'] + a['earned_funded'] + a['earned_unfunded']
                           + a['withdrawal_funded'] + a['withdrawal_unfunded'] + a['withdrawn']
                           for a in state['accounts'].values()) - sum(d['amount'] for d in state['deposits'].values())
        if customer_pnl != -self.model.pnl:
            raise ValueError('customer/LP trading PnL conservation failure')
        self.model.check()
        result = dict(run=self.directory.parent.name, retained_bps=self.retained_bps,
                      retained_wallets=len(self.wallets), source_wallets=len({s['terms']['account'] for s in self.original['stages'].values()}),
                      initial_lp_usdc_units=250000 * USDC, assumed_external_lp_usdc_units=self.external_capital,
                      accepted_stages=len(stages), source_stages_in_subset=len(source_stages),
                      outcomes=dict(Counter(s['status'] for s in stages.values())),
                      recorded_outcome_mismatches=mismatches, recorded_term_mismatches=term_mismatches,
                      rejected_actions=dict(self.rejects), peak_exposure_usdc_units=self.max_exposure,
                      max_share_nav_drawdown_bps=float(self.max_drawdown * 10000),
                      customer_trading_pnl_usdc_units=customer_pnl, lp_trading_pnl_usdc_units=self.model.pnl,
                      capture=self.capture_snapshot, final=self.model.snapshot(),
                      operation_counts=dict(self.counts),
                      cost_sensitivities=cost_sensitivity(self.counts, (self.end_ms-self.start_ms)/1000,
                                                        self.model.pnl, self.capture_snapshot['fee'], self.costs),
                      conservation_verified=True, zero_terminal_exposure=self.exposure == 0,
                      funded_exit_claims=len(self.model.exits) == self.model.head and self.model.reserved == 0,
                      lp_reward_claimed_units=str(self.model.claimed),
                      lp_reward_unclaimed_published_units=str(self.model.published - self.model.claimed),
                      lp_reward_escrow_remaining_units=str(BUDGET - self.model.claimed),
                      audit_head=self.bridge.head, audit_records=self.bridge.count)
        return result


def source_metadata(directory):
    p = json.loads((directory/'initial-policy.json').read_text())
    obs = observations(directory)
    rows = healthy_windows(directory, p, obs)
    width = p['model'].get('base_width_ppm', p['model']['base_width_bps'] * 100)
    survived = sum(r['max_move_units'] < r['entry'] * width // 1_000_000 for r in rows)
    bbo = 0
    with (directory/'events.jsonl').open() as stream:
        for line in stream:
            bbo += json.loads(line)['kind'] == 'market_bbo'
    return dict(run=directory.parent.name,
                hashes={name:digest(directory/name) for name in
                        ('initial-policy.json', 'journal.jsonl', 'final-state.json', 'summary.json', 'events.jsonl')},
                first_oracle_ms=obs[0][0], last_oracle_ms=obs[-1][0], bbo_messages=bbo,
                nonoverlapping_healthy_windows=len(rows), frozen_reference_width_ppm=width,
                reference_survived=survived, reference_survival=survival(rows,width),
                descriptive_wilson_95=wilson(survived,len(rows)))


def money(value):
    return f'{Decimal(value)/USDC:,.6f}'


def report(manifest, results):
    lines = ['# Contract-matched recorded LP replay', '',
             'Research only. Public execution remains disabled. No deployment, signatures or transactions are produced.', '',
             'Recorded oraclePx drives the actual Go reducer; recorded BBO is counted as supporting evidence. '
             'Wallet funding, entry times, ladder choices, cashouts and historical policy changes are retained. '
             'Demand cases remove whole wallets deterministically (nested 100%, 50%, 10%, 0% subsets), '
             'without recycling market paths or inventing new customers. These are participation sensitivities, not measured organic demand.', '',
             'Initial LP cash is 250,000 USDC: assumed 200,000 protocol capital and 50,000 from 25 external LPs. '
             'This is a counterfactual new deployment with share economics enabled. It does not describe balances of the old recorded deployment.', '',
             'LP arithmetic includes virtual shares/assets, contribution-adjusted HWM, capitalization ramp, accrued reserve fees, '
             'FIFO 48-hour requests, segregated fulfillment, pull claims, linear 90-day budgets, '
             'capital/index rounding, protocol/pending exclusions, epoch publication deadlines and end-of-epoch + 30-day vesting.', '',
             '| Source | Role | Oracle span minutes | BBO messages | Healthy 30s windows | Reference survival |',
             '|---|---|---:|---:|---:|---:|']
    for i, source in enumerate(manifest['sources']):
        lines.append(f"| {source['run']} | {'development' if i==0 else 'chronological holdout'} | {(source['last_oracle_ms']-source['first_oracle_ms'])/60000:.1f} | {source['bbo_messages']} | {source['nonoverlapping_healthy_windows']} | {100*(source['reference_survival'] or 0):.1f}% |")
    lines += ['', 'The first recording is the development trace; later disjoint recordings are chronological holdout traces. '
              'No parameters are fitted or selected by this replay. All sources were already available before this work, so '
              'this is retrospective holdout, not new prospective validation. Each run resets the assumed initial capital; '
              'the recordings are not spliced into a continuous multi-day market path.', '',
              '| Source | Retained wallets | Stages | LP trading PnL USDC | Accrued fee USDC | Maximum NAV drawdown | Outcome differences |',
              '|---|---:|---:|---:|---:|---:|---:|']
    for r in results:
        lines.append(f"| {r['run']} | {r['retained_wallets']} | {r['accepted_stages']} | {money(r['lp_trading_pnl_usdc_units'])} | {money(r['capture']['fee'])} | {r['max_share_nav_drawdown_bps']/100:.2f}% | {len(r['recorded_outcome_mismatches'])} |")
    lines += ['', 'After the recording, an explicit mechanical runoff assumes **zero new trading and no new prices**. '
              'External LPs request exits, a later zero-exposure checkpoint enables fulfillment on day 3, '
              'claimable cash is segregated and paid, completed reward epochs are published, and epoch-1 rewards are claimed on day 31. '
              'Those dates test timing/accounting; they are not observations of future LP returns, exit availability under continuing risk, '
              'or recovery of a market drawdown. No return or annualized APY is extrapolated from these short captures.', '',
              '| Source / wallets | LP paid exits USDC | Funded reserve USDC | LP FUSE claimed | Remaining published FUSE |',
              '|---|---:|---:|---:|---:|']
    for r in results:
        paid_exits = 250000*USDC+r['lp_trading_pnl_usdc_units']-r['final']['reserve']-r['final']['cash']
        lines.append(f"| {r['run']} / {r['retained_wallets']} | {money(paid_exits)} | {money(r['final']['reserve'])} | {Decimal(r['lp_reward_claimed_units'])/10**18:.6f} | {Decimal(r['lp_reward_unclaimed_published_units'])/10**18:.6f} |")
    lines += ['', 'Costs below are **explicit assumptions**, not measured HyperEVM fees. '
              'Retained journals do not contain gasUsed/effectiveGasPrice receipts. Gas units per operation, '
              'native-token USD, gas price and operator costs are pinned in experiment.json. '
              'Costs use actual simulated operation counts plus the recorded elapsed service time, including the local claim workflow. '
              'Offchain entries are not charged fictitious onchain gas. Runoff transaction gas is included; '
              '30 idle days of continuing service costs are not projected. Costs are shown as an economic allocation '
              'and do not reduce onchain share NAV: the contracts have no operator-cost withdrawal rule.', '',
              '| Source / wallets | Cost assumption | Allocated total USDC | LP PnL after fee and costs USDC |',
              '|---|---|---:|---:|']
    for r in results:
        for c in r['cost_sensitivities']:
            lines.append(f"| {r['run']} / {r['retained_wallets']} | {c['name']} | {money(c['assumed_total_cost_usdc_units'])} | {money(c['lp_profit_after_fee_and_allocated_cost_usdc_units'])} |")
    lines += ['', 'Conservation and admitted obligations are checked by the Go reducer on every successful command, '
              'and cash/shares/reward escrow/exit liabilities are checked by the LP model on each economic transition. '
              'Source journals are independently replayed with full Go event/hash comparison before counterfactual replay. '
              'Research audit JSONL records commands, rejected actions, explicit external LP balance projections, '
              'responses and a hash chain; these files are not ordinary confirmed engine transaction journals.', '',
              'Remaining production gates: substantially more independent forward regimes; conditional ladder survival; '
              'actual voluntary funded demand; measured receipt and infrastructure costs; trader emissions/redemption demand '
              'under the new LP deployment; enforcement and stress testing of the selected recovery controller in the backend; '
              'live LP/oracle disruption tests, public-testnet inclusion and independent contract/security review. '
              'The earlier recovery-policy results remain synthetic and are not validated by this replay.', '']
    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', action='append', help='retained run ID, in chronological order (repeatable)')
    parser.add_argument('--output', type=Path, default=ROOT/'.local/contract-lp-replay')
    parser.add_argument('--binary', type=Path, help='prebuilt engine/cmd/fuse-research binary')
    parser.add_argument('--costs', type=Path, help='JSON array of explicit gas/native/operator cost assumptions')
    parser.add_argument('--verify-audit', type=Path, help='re-execute a research audit and verify its responses/hash chain')
    parser.add_argument('--reverify-sources', action='store_true', help='ignore matching successful source verification checkpoints')
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='fuse-research-') as temporary:
        binary = args.binary
        if binary is None:
            binary = Path(temporary)/'fuse-research'
            go = os.environ.get('FUSE_GO', shutil.which('go') or 'go')
            subprocess.run([go, 'build', '-o', str(binary), './cmd/fuse-research'], cwd=ROOT/'engine', check=True)
        if args.verify_audit:
            verify_audit(binary, args.verify_audit)
            return
        costs = json.loads(args.costs.read_text()) if args.costs else DEFAULT_COSTS
        if not isinstance(costs, list) or not costs:
            raise ValueError('at least one explicit cost scenario is required')
        cost_sensitivity({}, 0, 0, 0, costs)
        directories = [ROOT/'.local/live-runs'/run/'evidence' for run in (args.run or DEFAULT_RUNS)]
        sources = [source_metadata(d) for d in directories]
        for a, b in zip(sources, sources[1:]):
            if a['last_oracle_ms'] >= b['first_oracle_ms']:
                raise ValueError('sources must be chronological disjoint recordings')
        implementation = list((ROOT/'src').rglob('*.sol')) + list((ROOT/'engine/internal/engine').glob('*.go'))
        implementation += [Path(__file__), ROOT/'scripts/contract_lp_model.py',
                           ROOT/'scripts/calibrate_pricing.py', ROOT/'scripts/generate_lp_model_vectors.py',
                           ROOT/'test/LPModelDifferential.t.sol', ROOT/'test/fixtures/LPModelVectors.sol',
                           ROOT/'engine/cmd/fuse-research/main.go']
        implementation += [ROOT/'lib/openzeppelin-contracts/contracts'/p for p in
                           ('token/ERC20/extensions/ERC4626.sol', 'token/ERC20/ERC20.sol', 'utils/math/Math.sol')]
        manifest = dict(version='contract-lp-replay-v1', public_execution_approved=False,
                        model_scope='successful authorized LP economic operations; actual Go trading reducer',
                        sources=sources, retained_demand_bps=[10000,5000,1000,0],
                        initial_lp_usdc_units=250000*USDC, assumed_external_lp_usdc_units=50000*USDC,
                        external_lp_wallets=25, gas_units_assumptions=GAS_ASSUMPTIONS,
                        cost_assumptions=costs, measured_gas_receipts_available=False,
                        input_hashes={str(p.relative_to(ROOT)):digest(p) for p in sorted(implementation)},
                        candidate_selection='none; historical policies and timestamps retained',
                        model_clock='recorded receipt milliseconds floored to seconds; hypothetical block clock',
                        prospective_evidence=False)
        manifest['research_binary_sha256'] = digest(binary)
        # Pin the complete protocol before running any economic counterfactual.
        (args.output/'experiment.json').write_text(json.dumps(manifest, indent=2)+'\n')
        results = []
        verifier = Bridge(binary)
        try:
            for directory in directories:
                verification_path = args.output/(directory.parent.name+'-source-verification.json')
                source = next(s for s in sources if s['run'] == directory.parent.name)
                cache_key = dict(binary=manifest['research_binary_sha256'],
                                 journal=source['hashes']['journal.jsonl'],
                                 initial=source['hashes']['initial-policy.json'],
                                 final=source['hashes']['final-state.json'])
                initial = json.loads((directory/'initial-policy.json').read_text())
                cached = json.loads(verification_path.read_text()) if verification_path.exists() else {}
                if not args.reverify_sources and cached.get('inputs') == cache_key:
                    print('Reusing matching successful source verification:', directory.parent.name, flush=True)
                    verified = cached['verified']
                else:
                    print('Verifying original Go journal:', directory.parent.name, flush=True)
                    verified = verifier.send(dict(kind='verify', policy=initial, path=str(directory/'journal.jsonl'),
                                                  final_path=str(directory/'final-state.json')))['value']
                final = json.loads((directory/'final-state.json').read_text())
                with (directory/'journal.jsonl').open() as stream:
                    last_event = None
                    for line in stream:
                        last_event = json.loads(line)
                if (verified['state_hash'] != last_event['state_hash']
                        or verified['sequence'] != final['sequence']
                        or verified['journal_hash'] != final['journal_hash']):
                    raise ValueError('verified journal differs from retained final state')
                verification_path.write_text(json.dumps(dict(inputs=cache_key,verified=verified),indent=2)+'\n')
                for retained in manifest['retained_demand_bps']:
                    print(f'Replaying {directory.parent.name}: retained demand {retained/100:g}%', flush=True)
                    name = directory.parent.name + '-' + str(retained)
                    with (args.output/(name+'-audit.jsonl')).open('w') as audit:
                        bridge = Bridge(binary, audit)
                        try:
                            replay = Replay(bridge, directory, retained, costs)
                            result = replay.run()
                            results.append(result)
                            (args.output/(name+'-result.json')).write_text(json.dumps(result,indent=2)+'\n')
                            (args.output/(name+'-lp.jsonl')).write_text(''.join(canonical(r)+'\n' for r in replay.log))
                        finally:
                            bridge.close()
        finally:
            verifier.close()
        (args.output/'results.json').write_text(json.dumps(results, indent=2)+'\n')
        (args.output/'report.md').write_text(report(manifest, results))
        print(canonical(dict(cases=len(results), all_conserved=all(r['conservation_verified'] for r in results),
                             outcome_mismatches=sum(len(r['recorded_outcome_mismatches']) for r in results),
                             report=str(args.output/'report.md'), public_execution_approved=False)))


def verify_audit(binary, path):
    bridge = Bridge(binary)
    head, count = '', 0
    try:
        for row in read_jsonl(path):
            expected = row.pop('hash')
            if row['previous'] != head or hashlib.sha256(canonical(row).encode()).hexdigest() != expected:
                raise ValueError('research audit hash mismatch')
            head = expected
            if 'request' in row:
                got = bridge.send(row['request'], allow_reject=True)
                if got != row['response']:
                    raise ValueError(f'research audit response diverged at {count+1}')
            count += 1
    finally:
        bridge.close()
    print(canonical(dict(records=count, audit_head=head, replay_verified=True)))


if __name__ == '__main__':
    main()
