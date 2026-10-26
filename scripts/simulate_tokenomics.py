#!/usr/bin/env python3
"""Integer-ledger tokenomics research. Demand, correlation and bids are assumptions."""
import argparse
from dataclasses import asdict, dataclass, replace
import json
import math
from pathlib import Path
import random

ROOT=Path(__file__).resolve().parent.parent
USDC=10**6; TOKEN=10**18; GENESIS=10**9*TOKEN; MINING=600_000_000*TOKEN; TREASURY=400_000_000*TOKEN
PAYOUT=[10**9,1778279410,3162277660,5623413251,10**10,17782794100,31622776602,56234132519,10**11]

@dataclass(frozen=True)
class Scenario:
    survival_bps:int=4800
    allocation_bps:int=3500
    half_life_days:int=20
    penalty_bps:int=1000
    unlock_day:int=7
    initial_lp_usdc:int=250000
    behavior:str='mixed'
    demand_elasticity:float=.5
    correlation:float=.8
    stage_survival_shape:str='flat'
    market_depth_usdc:int=0
    days:int=180
    seed:int=20261025


def reserve_amount(profit,hwm,consumed,equity,capital,cap):
    if profit<hwm or profit<=consumed or equity<2*capital or cap==0:return 0,0
    alpha=cap if capital==0 or equity>=3*capital else (2*cap*(equity-capital)//capital-cap)//3
    if alpha<=0:return 0,0
    amount=min((profit-consumed)*alpha//10000,equity-2*capital)
    return amount,(amount*10000+alpha-1)//alpha


def emission_budgets(days,half_life):
    weights=[2**(-d/half_life) for d in range(days)]
    total=sum(weights)
    result=[];remaining=MINING
    for w in weights:
        budget=min(remaining,int(MINING*w/total));result.append(budget);remaining-=budget
    return result


def run(scenario,keep_daily=False):
    s=scenario;r=random.Random(s.seed)
    lp=s.initial_lp_usdc*USDC; initial=lp;reserve=profit=hwm=consumed=0
    emitted=burned=penalties=reserve_funded=0
    balances={k:0 for k in ['organic','early-miners','late-miners','buyers']}
    pnl={k:0 for k in balances}; mining_by_cohort={k:0 for k in balances}
    market=s.market_depth_usdc*USDC; initial_market=market
    budgets=emission_budgets(s.days,s.half_life_days)
    minimum_lp=lp; peak=lp; drawdown=0;rejected=accepted=0;outcomes={'survived':0,'failed':0,'voided':0};timeline=[]
    exposure_peak=0; unused=0
    for day in range(s.days):
        edge=max(0,1-s.survival_bps/10000*PAYOUT[1]/10**9)
        activity=0 if s.behavior=='no-demand' else max(0,int(100*math.exp(-s.demand_elasticity*edge*5)))
        if s.behavior=='farming-collapse' and day>=s.unlock_day: activity=activity*30//100
        positions=[];score={k:0 for k in balances};capital=100*USDC
        for i in range(activity):
            farmer=s.behavior!='organic-only' and i%5<2
            cohort=('early-miners' if day<30 else 'late-miners') if farmer else 'organic'
            target=[1,2,3,4,8][i%5]
            positions.append({'cohort':cohort,'initial':500*USDC,'stake':500*USDC,'target':target,'farmer':farmer})
        for stage in range(1,9):
            if not positions:break
            admitted=[];reserved=0
            for pos in positions:
                payout=pos['initial']*PAYOUT[stage]//10**9
                risk=payout-pos['stake']
                if reserved+risk+100*USDC>lp:
                    rejected+=1;continue
                reserved+=risk;admitted.append((pos,payout))
            exposure_peak=max(exposure_peak,reserved);capital=max(capital,reserved+100*USDC)
            common=r.random(); survivors=[]
            for pos,payout in admitted:
                accepted+=1
                if s.behavior=='oracle-interruption' and day in (7,30,90):outcomes['voided']+=1;continue
                u=common if r.random()<s.correlation else r.random()
                p=s.survival_bps/10000
                if s.stage_survival_shape!='flat':p=min(.54,max(.40,p+(stage-4.5)*(.01 if s.stage_survival_shape=='back-loaded' else -.01)))
                won=u<p
                if s.behavior=='correlated-winners' and day==0:won=True
                if s.behavior=='deliberate-loss-farming' and pos['farmer']:won=False
                duration=30000 if won else (1 if s.behavior=='deliberate-loss-farming' and pos['farmer'] else r.randint(1,29999))
                score[pos['cohort']]+=pos['stake']*duration*(10000 if won else 2000)
                if won:
                    delta=payout-pos['stake'];lp-=delta;profit-=delta;pnl[pos['cohort']]+=delta;outcomes['survived']+=1
                    pos['stake']=payout
                    if stage<pos['target']:survivors.append(pos)
                else:
                    lp+=pos['stake'];profit+=pos['stake'];pnl[pos['cohort']]-=pos['stake'];outcomes['failed']+=1
                hwm=max(hwm,profit)
            positions=survivors
            assert lp>=0
        if s.behavior=='drawdown' and day==30:
            shock=lp//5;lp-=shock;profit-=shock;pnl['organic']+=shock
        amount,used=reserve_amount(max(profit,0),hwm,consumed,lp,capital,s.allocation_bps)
        lp-=amount;reserve+=amount;consumed+=used;reserve_funded+=amount
        total=sum(score.values())
        # 100 research FUSE per USDC risked for a full 30s at weight 1.0.
        eligible=total*(100*TOKEN)//(USDC*30000*10000)
        # Published distress rule throttles only future, unearned emissions.
        distress=min(10000,lp*10000//max(1,2*capital))
        budget=min(budgets[day],eligible,MINING-emitted)*distress//10000
        distributed=0
        if total:
            for cohort,value in score.items():
                tokens=budget*value//total;balances[cohort]+=tokens;mining_by_cohort[cohort]+=tokens;distributed+=tokens
        emitted+=distributed;unused+=budgets[day]-distributed
        # Baseline has no secondary bid. Depth scenarios assume a disclosed
        # external buyer book at 80% of executable intrinsic value, with impact.
        if day>=s.unlock_day and market and reserve:
            for cohort in ['early-miners','late-miners']:
                tokens=balances[cohort]//2
                notional=tokens*reserve*(10000-s.penalty_bps)*8000//max(1,(GENESIS-burned)*10000*10000)
                payment=market*notional//(market+notional) if notional else 0
                if payment:
                    balances[cohort]-=tokens;balances['buyers']+=tokens;market-=payment;pnl[cohort]+=payment
        if day>=s.unlock_day and reserve:
            snapshot_supply=GENESIS-burned;snapshot_reserve=reserve
            requests={k:(tokens if 'miners' in k else tokens//5) for k,tokens in balances.items()}
            total_tokens=sum(requests.values())
            assert total_tokens<snapshot_supply # 400M treasury never released
            for cohort,tokens in requests.items():
                paid=tokens*(10000-s.penalty_bps)*snapshot_reserve//(snapshot_supply*10000)
                gross=tokens*snapshot_reserve//snapshot_supply
                balances[cohort]-=tokens;burned+=tokens;reserve-=paid;pnl[cohort]+=paid;penalties+=gross-paid
        minimum_lp=min(minimum_lp,lp);peak=max(peak,lp);drawdown=max(drawdown,(peak-lp)/peak if peak else 0)
        # Economic PnL may be negative; these are not spendable wallet balances.
        assert lp+reserve+sum(pnl.values())+market==initial+initial_market
        assert sum(balances.values())+(MINING-emitted)+TREASURY==GENESIS-burned
        assert reserve>=0 and 0<=emitted<=MINING and lp>=0
        if keep_daily:timeline.append({'day':day,'lp_usdc_units':lp,'reserve_usdc_units':reserve,'emitted_fuse_units':str(emitted),'burned_fuse_units':str(burned),'supply_fuse_units':str(GENESIS-burned),'reserve_funded_usdc_units':reserve_funded})
    supply=GENESIS-burned
    economic_pnl=dict(pnl)
    economic_pnl['buyers']-=initial_market-market
    assert lp+reserve+sum(economic_pnl.values())==initial
    intrinsic={k:reserve*tokens//supply for k,tokens in balances.items()}
    intrinsic['locked-treasury']=reserve*TREASURY//supply
    intrinsic['unreleased-mining']=reserve*(MINING-emitted)//supply
    return {'scenario':asdict(s),'lp_final_usdc_units':lp,'lp_min_usdc_units':minimum_lp,'max_drawdown':drawdown,'reserve_usdc_units':reserve,'reserve_funded_usdc_units':reserve_funded,'retained_penalty_usdc_units':penalties,'emitted_fuse_units':str(emitted),'unallocated_fuse_units':str(unused),'burned_fuse_units':str(burned),'outstanding_supply_fuse_units':str(supply),'cohort_tokens':{k:str(v) for k,v in balances.items()},'cohort_mined_tokens':{k:str(v) for k,v in mining_by_cohort.items()},'cohort_economic_pnl_usdc_units':economic_pnl,'cohort_remaining_intrinsic_backing_usdc_units':intrinsic,'market_remaining_usdc_units':market,'accepted_stages':accepted,'rejected_stages':rejected,'outcomes':outcomes,'peak_accepted_exposure_usdc_units':exposure_peak,'gross_backing_usdc_per_fuse':reserve/USDC/(supply/TOKEN),'contract_supported_allocation':s.allocation_bps<=5000,'conservation_verified':True,'daily':timeline}


def scenarios(seed):
    base=Scenario(seed=seed);result=[base]
    dimensions={'survival_bps':list(range(4000,5401,100)),'allocation_bps':[0,1000,3500,5000,7000],'half_life_days':[10,20,22,30,35],'penalty_bps':[0,500,1000,1500,2000,3000],'unlock_day':[3,7,14,30],'initial_lp_usdc':[100000,250000,500000,1000000,5000000,10000000],'behavior':['organic-only','mixed','farming-collapse','no-demand','correlated-winners','oracle-interruption','drawdown','deliberate-loss-farming'],'market_depth_usdc':[0,1000,10000,100000],'demand_elasticity':[0,.5,1,2],'correlation':[0,.5,.8,1],'stage_survival_shape':['flat','front-loaded','back-loaded']}
    for field,values in dimensions.items():result.extend(replace(base,**{field:value}) for value in values)
    # Cover joint parameter interactions without presenting one-way sweeps as
    # exhaustive Cartesian optimization. All sampled values are published.
    r=random.Random(seed)
    for _ in range(160):result.append(replace(base,**{field:r.choice(values) for field,values in dimensions.items()}))
    return list(dict.fromkeys(result)),dimensions


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,default=ROOT/'.local/tokenomics-research');parser.add_argument('--seed',type=int,default=20261025);args=parser.parse_args()
    cases,dimensions=scenarios(args.seed);results=[run(s,keep_daily=(i==0)) for i,s in enumerate(cases)]
    # Conditional frontier: enforce model solvency and compare reserve growth,
    # drawdown and rejected stages. This does not establish real user demand.
    eligible=[x for x in results if x['contract_supported_allocation'] and x['scenario']['behavior']=='organic-only' and x['max_drawdown']<=.25]
    frontier=[]
    for x in eligible:
        if not any(y['reserve_funded_usdc_units']>=x['reserve_funded_usdc_units'] and y['max_drawdown']<=x['max_drawdown'] and y['rejected_stages']<=x['rejected_stages'] and (y['reserve_funded_usdc_units']>x['reserve_funded_usdc_units'] or y['max_drawdown']<x['max_drawdown'] or y['rejected_stages']<x['rejected_stages']) for y in eligible):frontier.append(x)
    args.output.mkdir(parents=True,exist_ok=True)
    report={'research_only':True,'empirical_demand_calibration':False,'grid_method':'baseline + one-factor coverage + 160 seeded joint combinations; not exhaustive Cartesian optimization','dimensions':dimensions,'assumptions':{'days':180,'nominal_games_per_day':100,'initial_stake_usdc':500,'cross_player_correlation_model':'seeded common-draw mixture; parameter is an assumption','external_bids':'absent in baseline; depth variants synthetic, externally funded; bid=80% intrinsic executable value with impact','retention':'explicit scenario assumption; not inferred from Papertrade TVL','elasticity':'games/day = floor(100 * exp(-elasticity * positive USDC house edge * 5)); unmeasured research response curve','score':'linear real-at-risk stake*time, survive1.0/fail0.2; no streak bonus','activity_rate_fuse_per_usdc_30s':100,'treasury':'400M locked, included in denominator','market_and_customer_pnl':'includes redeemed USDC and subtracts actual buyer purchases; no unexecuted FUSE mark-to-market; remaining intrinsic backing is separately disclosed and is not cash proceeds'},'results':results,'conditional_organic_frontier':frontier,'production_approved':False}
    (args.output/'results.json').write_text(json.dumps(report,indent=2)+'\n')
    lines=['# Tokenomics research scenarios','',f"{len(results)} integer-ledger scenarios; all USDC and FUSE conservation checks passed. This is a conditional model, not empirical economic validation.",'','The grid covers survival 40–54%, allocations 0/10/35/50/70%, half-lives 10/20/22/30/35 days, penalties 0/5/10/15/20/30%, unlocks 3/7/14/30 days and LP $100k/$250k/$500k/$1M/$5M/$10M. Allocation 70% is research-only and is excluded from contract-supported frontier results.','',f"Method: {report['grid_method']}",'','| Behavior | LP start USDC | LP final USDC | Reserve USDC | Max drawdown | Rejected stages |','|---|---:|---:|---:|---:|---:|']
    for x in results:
        s=x['scenario']
        if all(s[k]==asdict(Scenario(seed=args.seed))[k] for k in s if k!='behavior'):
            lines.append(f"| {s['behavior']} | {s['initial_lp_usdc']:,} | {x['lp_final_usdc_units']/USDC:,.2f} | {x['reserve_usdc_units']/USDC:,.2f} | {x['max_drawdown']:.1%} | {x['rejected_stages']} |")
    lines+=['',f"Conditional organic-only frontier points: {len(frontier)}; inspect results.json for each full parameter set and cohort PnL. They are not recommended launch settings.",'','Baseline has no external buyers. No mined token is valued at an imagined listing price. Demand, retention, correlations and synthetic market depth are disclosed assumptions; repository data does not supply Papertrade TVL or measured FUSE demand elasticity. Long chronological oracle calibration and real user behavior data remain necessary.']
    (args.output/'report.md').write_text('\n'.join(lines)+'\n');print(args.output/'report.md');print(json.dumps({'scenarios':len(results),'conservation_verified':True,'frontier_points':len(frontier)}))

if __name__=='__main__':main()
