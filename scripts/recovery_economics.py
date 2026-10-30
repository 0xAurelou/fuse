"""Fee-aware recovery replay, gated on the isolated v2 research bridge."""
from copy import deepcopy

from single_stage_economics import Replay as CapitalReplay


class Replay(CapitalReplay):
    def __init__(self,bridge,policy,receipts,start,end,profile,multiplier,costs):
        capability=bridge.send(dict(kind='capabilities'),allow_reject=True)
        if (not capability['ok'] or capability['value'].get('version')!='fee-recovery-research-v2'
                or not capability['value'].get('fee_accrual_recovery')):
            raise ValueError('verified fee-aware v2 research bridge required')
        # The parent constructor only builds causal market rows and empty
        # accounting objects. Health inputs do not use the recovery policy.
        # Restore the actual policy before bootstrap initializes the Go state.
        health=deepcopy(policy);health.pop('recovery',None)
        super().__init__(bridge,health,receipts,start,end,profile,multiplier,costs)
        self.policy=deepcopy(policy);self.fee_checks=[];self.recovery_modes=[]

    def sync(self):
        before=deepcopy(self.view.get('recovery'))
        old_fee=self.view.get('lp_fee_accrued',0)
        super().sync()
        delta=self.model.fee-old_fee
        if delta<0:raise ValueError('fee funding/reduction is outside this version')
        after=self.view.get('recovery')
        if self.policy.get('recovery') is not None:
            if before is None or after is None or after['pnl']!=before['pnl']-delta:
                raise ValueError('recovery did not debit exactly the newly accrued fee')
            self.fee_checks.append(dict(at=self.view['at'],fee_delta=delta,
                recovery_pnl_before=before['pnl'],recovery_pnl_after=after['pnl']))

    def command(self,kind,at,optional=False,**fields):
        result=super().command(kind,at,optional,**fields)
        recovery=self.view.get('recovery')
        if recovery is not None and (not self.recovery_modes or self.recovery_modes[-1]['mode']!=recovery['mode']):
            self.recovery_modes.append(dict(at=at,mode=recovery['mode'],pnl=recovery['pnl']))
        return result

    def run(self):
        result,state=super().run();recovery=state.get('recovery')
        if self.policy.get('recovery') is not None:
            if recovery['pnl']!=self.model.pnl-self.model.fee:
                raise ValueError('terminal recovery PnL differs from trading minus actual fee accrual')
            gross_losses=sum(s['terms']['payout']-s['terms']['stake'] for s in state['stages'].values()
                if s['status']=='survived')+self.model.fee
            if sum(r['amount'] for r in recovery['losses'])!=gross_losses:
                raise ValueError('short-horizon gross loss/fee budget does not reconcile')
        result.update(recovery_enabled=self.policy.get('recovery') is not None,recovery_final=recovery,
            recovery_mode_transitions=self.recovery_modes,fee_projection_checks=self.fee_checks,
            fee_projection_verified=True,allocated_operating_costs_charged_to_controller=False,
            fee_reductions_or_lp_exit_lifecycle_evaluated=False)
        return result,state
