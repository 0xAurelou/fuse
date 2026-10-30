"""Counterfactual preset tickets on original native receipts and the Go reducer.

No fitted width, resampling, synthetic paired feed, live execution or deployment.
The scope is the shipped fixed-volatility Brownian research policy, not the
separately frozen 48% adaptive challenger.
"""
from collections import Counter
from copy import deepcopy
from fractions import Fraction

from contract_lp_model import LPModel,USDC
from native_adaptive_data import build_rows
from replay_lp_economics import Bridge,cost_sensitivity

PROFILES=(dict(name='uniform_one',accounts=1,frozen_only=False),
          dict(name='frozen_one',accounts=1,frozen_only=True),
          dict(name='uniform_three',accounts=3,frozen_only=False))
SPEC=dict(prefix_ms=1800000,grid_ms=30000,stake_usdc=1,customer_deposit_usdc=1000,
    initial_lp_usdc=250000,external_lp_usdc=50000,external_lp_owners=25,
    settlement_ms=300000,profiles=PROFILES,
    policy='Unchanged shipped single-stage Brownian assumptions and all nine payouts; paper mode, no recovery policy',
    strategy='Fixed funded deposit and fixed one-USDC stake per account at each eligible grid entry. Frozen-only uses pre-entry activity. Accounts enter the same corridor at the same timestamp; no independent outcome draws.',
    input='First thirty minutes of each identified completed native recording, including five-minute history startup. Original receiver messages/order/times only. No live trial receipts or proxy observations.',
    fee='LPModel share economics, virtual rounding, high-water accrual and capitalization ramp; no fee funding, LP exits or reward projection in this bounded probe',
    recovery='Not evaluated. Current paper policy has no recovery controller. Direct research sync_lp fee projection does not invoke recovery fee accounting, so combining it with recovery would be invalid.',
    cost='Pinned illustrative gas/native/operating assumptions, actual simulated operation counts. Allocated economics only; no fabricated onchain costs or operator withdrawals.')


def intends(row,profile):
    return row['adaptive_features'] is not None and (not profile['frozen_only'] or row['activity_state']=='frozen')


class Replay:
    def __init__(self,bridge,policy,receipts,start,end,profile,multiplier,costs):
        if policy.get('recovery') is not None:raise ValueError('fee/recovery projection is outside this probe')
        if policy.get('product')!='single-stage-v1' or policy['model'].get('dnt') is None:
            raise ValueError('shipped preset Brownian research policy required')
        self.bridge=bridge;self.policy=deepcopy(policy);self.profile=profile;self.multiplier=multiplier
        self.receipts=receipts;self.start=start;self.end=end;self.costs=costs
        self.rows=build_rows(receipts,self.policy,start,end,'retained-native-prefix')
        self.model=LPModel(start//1000);self.serial=0;self.view=None
        self.counts=Counter();self.rejects=Counter();self.entries=[];self.snapshots=[]
        self.peak_exposure=0;self.peak_debt=0;self.peak_nav=Fraction(1,10**12);self.drawdown=Fraction(0)
        self.grid_intents=0;self.quote_attempts=0;self.accounts=[f'trader-{i}' for i in range(profile['accounts'])]

    def command(self,kind,at,optional=False,**fields):
        self.serial+=1;self.advance(at)
        got=self.bridge.send(dict(kind='command',command=dict(kind=kind,at=at,key=f'probe/{self.serial}',**fields)),allow_reject=optional)
        if not got['ok']:
            self.rejects[kind+': '+got['error']]+=1;return None
        self.view=got['value'];self.peak_exposure=max(self.peak_exposure,self.view['exposure'])
        self.peak_debt=max(self.peak_debt,self.view['debt'])
        return self.view.get('result')

    def advance(self,at):
        second=at//1000
        if second<self.model.now:raise ValueError('regressing replay time')
        self.model.integrate_liability(self.model.now,second,self.view['exposure'] if self.view else 0)
        self.model.clock(second)

    def sync(self):
        self.view=self.bridge.send(dict(kind='sync_lp',cash=self.model.cash,fee=self.model.fee,exit=self.model.reserved))['value']
        nav=Fraction(self.model.assets+1,self.model.supply+10**12)
        self.peak_nav=max(self.peak_nav,nav);self.drawdown=max(self.drawdown,(self.peak_nav-nav)/self.peak_nav)

    def bootstrap(self):
        self.view=self.bridge.send(dict(kind='init',policy=self.policy))['value']
        self.model.deposit('protocol',200000*USDC)
        self.model.finalize(0,self.policy['lp_buffer'],0);self.model.set_phase(1);self.model.set_phase(2)
        self.model.publish_capacity(50000*USDC,self.model.now+3600)
        for i in range(25):
            owner=f'lp-{i}';self.model.whitelist.add(owner);self.model.deposit(owner,2000*USDC)
            self.counts['lp_deposit']+=1
        self.sync()
        for i,owner in enumerate(self.accounts):
            self.command('deposit',self.start,actor=owner,id=f'fund-{i}',amount=1000*USDC)
            self.command('ack_deposit',self.start,id=f'fund-{i}')
            self.counts['trader_deposit']+=1

    def settlement(self,at):
        old=self.view['lp_profit'];result=self.command('paper_settle',at)
        pnl=self.view['lp_profit']-old;self.model.finalize(pnl,result['required_lp'],self.view['exposure'])
        if self.model.cash!=self.view['lp']:raise ValueError('Go/LP settlement cash mismatch')
        self.counts['settlement']+=1;self.sync()
        self.snapshots.append(dict(at=at,lp_profit=self.view['lp_profit'],**self.model.snapshot()))

    def entry(self,row):
        at=row['start'];self.command('tick',at)
        if at>self.start and (at-self.start)%SPEC['settlement_ms']==0:self.settlement(at)
        if not intends(row,self.profile):return
        self.grid_intents+=1
        for owner in self.accounts:
            self.quote_attempts+=1
            quote=self.command('quote',at,optional=True,actor=owner,amount=USDC,multiplier=self.multiplier)
            if quote is None:continue
            stage=self.command('enter',at,optional=True,actor=owner,id=quote['id'])
            if stage is not None:self.entries.append(dict(row=row,quote=quote,stage=stage))

    def run(self):
        self.bootstrap();index=0
        for row in self.rows:
            at=row['start']
            while index<len(self.receipts) and self.receipts[index]['at']<at:
                p=self.receipts[index];self.command('oracle',p['at'],source=p['source'],raw=p['raw']);index+=1
            self.entry(row)
        while index<len(self.receipts):
            p=self.receipts[index];self.command('oracle',p['at'],source=p['source'],raw=p['raw']);index+=1
        # No invented terminal price. Original prior-state expiry first, then
        # deterministic pending refunds after the declared void grace.
        self.command('tick',self.end);self.command('tick',self.end+self.policy['void_delay_ms'])
        if self.view['active'] or self.view['exposure']<self.view['debt']:raise ValueError('unresolved terminal stage')
        self.settlement(self.end+self.policy['void_delay_ms'])
        state=self.bridge.send(dict(kind='snapshot'))['value'];mismatches=[];comparison=0
        for entry in self.entries:
            row=entry['row'];stage=state['stages'][entry['stage']['id']];terms=stage['terms']
            if terms['stake']!=USDC or terms['payout']!=USDC*self.multiplier or terms['multiplier']!=self.multiplier:
                raise ValueError('accepted payout differs from declared preset')
            if row['valid']:
                comparison+=1;delta=terms['upper']-terms['entry_price']
                expected='survived' if row['move']<delta else 'exploded'
                if terms['entry_price']!=row['entry'] or stage['status']!=expected:
                    mismatches.append(dict(start=row['start'],stage=stage['id'],expected=expected,actual=stage['status']))
        if mismatches:raise ValueError('healthy native path/reducer outcome mismatch: '+str(mismatches[:3]))
        stages=list(state['stages'].values());outcomes=Counter(s['status'] for s in stages)
        customer=sum(a['available']+a['unfunded']+a['earned_funded']+a['earned_unfunded']+
            a['withdrawal_funded']+a['withdrawal_unfunded']+a['withdrawn'] for a in state['accounts'].values())
        customer-=sum(d['amount'] for d in state['deposits'].values())
        terminal_pnl=sum(s['terms']['stake'] if s['status']=='exploded' else
            -(s['terms']['payout']-s['terms']['stake']) if s['status']=='survived' else 0 for s in stages)
        if customer!=-self.model.pnl or terminal_pnl!=self.model.pnl:raise ValueError('economic conservation failure')
        turnover=sum(s['terms']['stake'] for s in stages);resolved=outcomes['survived']+outcomes['exploded']
        result=dict(profile=self.profile['name'],accounts=len(self.accounts),multiplier=self.multiplier,
            start=self.start,end=self.end,grid_windows=len(self.rows),history_eligible=sum(r['adaptive_features'] is not None for r in self.rows),
            intended_grid_entries=self.grid_intents,quote_attempts=self.quote_attempts,accepted_stages=len(stages),
            acceptance_fraction=len(stages)/self.quote_attempts if self.quote_attempts else None,
            grid_ticket_availability=len(stages)/(len(self.rows)*len(self.accounts)),rejected_actions=dict(self.rejects),
            outcomes=dict(outcomes),survival=outcomes['survived']/resolved if resolved else None,
            configured_survival_target=(10000-self.policy['model']['dnt']['house_edge_bps'])/(10000*self.multiplier),
            accepted_turnover_usdc_units=turnover,lp_trading_pnl_usdc_units=self.model.pnl,
            gross_return_per_stake=self.model.pnl/turnover if turnover else None,
            reserve_fee_accrued_usdc_units=self.model.fee,lp_profit_after_fee_usdc_units=self.model.pnl-self.model.fee,
            peak_total_exposure_usdc_units=self.peak_exposure,peak_unfunded_debt_usdc_units=self.peak_debt,
            settlement_nav_max_drawdown=float(self.drawdown),healthy_outcome_comparisons=comparison,
            healthy_outcome_mismatches=mismatches,conservation_verified=True,zero_terminal_active=True,
            terminal_exposure_usdc_units=self.view['exposure'],terminal_debt_usdc_units=self.view['debt'],
            operation_counts=dict(self.counts),lp_terminal=self.model.snapshot(),
            cost_sensitivities=cost_sensitivity(self.counts,(self.end-self.start)/1000,self.model.pnl,self.model.fee,self.costs),
            audit_records=self.bridge.count,audit_head=self.bridge.head,prospective_evidence=False,
            adaptive_candidate_evaluated=False,production_approved=False)
        return result,state
