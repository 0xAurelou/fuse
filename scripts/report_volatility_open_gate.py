#!/usr/bin/env python3
"""Audited volatility gates with independently counted open-entry exposure."""
import argparse
import json
from pathlib import Path

from audit_payout_walkforward import same
from research_active_tail import evaluation_rows
from research_flat_aware_payout import inputs as previous_inputs,selected
from research_payout_risk import digest,dump
from research_volatility_open_gate import verify_plan
from trial_payout import clean
from volatility_open_gate import BASES,GATES,opens


def pct(x):return '—' if x is None else f'{100*x:.3f}%'
def rate(p):return f'{p["wins"]:,} / {p["offered"]:,} ({pct(p["survival"])})'


def exposure(root):
    plan=verify_plan(root);meta=json.loads((root/'research.json').read_text());audit=json.loads((root/'audit.json').read_text())
    if not audit['passed'] or audit['research_sha256']!=digest(root/'research.json'):raise ValueError('Matching volatility-gate audit required')
    active=json.loads((Path(plan['active'])/'protocol.json').read_text());earlier,rows,_,_,binding=previous_inputs(json.loads((Path(active['parent'])/'protocol.json').read_text()));same(binding,meta['bindings']);result={}
    for a in ('ETH','HYPE'):
        later=evaluation_rows(earlier[a],rows[a]);directory=root/a;research=json.loads((directory/'research.json').read_text());models=json.loads((directory/'origins.json').read_text())
        if digest(directory/'research.json')!=meta['research_sha256'][a] or digest(directory/'origins.json')!=research['origins_sha256']:raise ValueError('Exposure gate artifact differs')
        result[a]={}
        # Two independently expressed opening predicates must agree on every row.
        for r in later:
            for gate in GATES:
                f=r['adaptive_features'];model=models[r['period']];manual=gate=='none' or f is not None and f['vol_60_ppm' if gate.startswith('fast') else 'vol_300_ppm']>=model['thresholds'][gate]
                if opens(r,gate,model)!=manual:raise ValueError('Exposure predicate differs')
        for phase in ('earlier_oof','trial'):
            result[a][phase]={}
            for cohort in ('matched','all_clean'):
                result[a][phase][cohort]={}
                for g in ('overall','weekday','weekend'):
                    ids=selected(later,phase,cohort,g);part=[later[i] for i in ids if clean(later[i])];values={}
                    for gate in GATES:
                        opened=[r for r in part if opens(r,gate,models[r['period']])];daily=[]
                        for day in sorted({r['period'] for r in part}):
                            n=sum(r['period']==day for r in part);k=sum(r['period']==day for r in opened);daily.append(dict(period=day,eligible=n,open=k,open_share=k/n if n else None))
                        values[gate]=dict(eligible=len(part),open=len(opened),open_share=len(opened)/len(part) if part else None,daily=daily)
                        for m in ('100','1000'):
                            for b in BASES:
                                summary=research['results'][phase][m][b][gate][cohort][g];p=summary['pooled']
                                if p['eligible']!=len(part) or p['offered']>len(opened):raise ValueError('Inconsistent offered/open exposure')
                                for s in summary['daily']:
                                    e=next(x for x in daily if x['period']==s['period'])
                                    if s['eligible']!=e['eligible'] or s['offered']>e['open']:raise ValueError('Inconsistent daily exposure')
                    result[a][phase][cohort][g]=values
    packet=dict(gate_research_sha256=digest(root/'research.json'),gate_audit_sha256=digest(root/'audit.json'),source_sha256=digest(Path(__file__)),bindings=binding,opening_predicate_independently_checked=True,results=result)
    path=root/'opening-exposure.json'
    if path.exists():same(json.loads(path.read_text()),packet)
    else:dump(path,packet)
    return result


def render(root,output):
    exposed=exposure(root);data={a:json.loads((root/a/'research.json').read_text()) for a in ('ETH','HYPE')};audit=json.loads((root/'audit.json').read_text())
    names={'none':'No added gate','fast25':'60s volatility ≥ prior Q25','fast50':'60s volatility ≥ prior Q50','fast75':'60s volatility ≥ prior Q75','slow25':'300s volatility ≥ prior Q25','slow50':'300s volatility ≥ prior Q50','slow75':'300s volatility ≥ prior Q75'}
    lines=['# ETH and HYPE volatility opening gate test','',
        'This paired test asks whether recent asset volatility can govern admission to a thirty-second corridor. It uses the oracle volatility already available before each entry, with separate ETH/HYPE thresholds. It does not use the Cboe VIX: that index measures thirty-day expected S&P 500 volatility ([Cboe](https://www.cboe.com/tradable-products/volatility-trading/)). The data here supports a realized-volatility gate, not an options-implied volatility index.','',
        'The gate uses the existing thirty-second-scaled oracle volatility estimates derived from the preceding sixty-second and five-minute windows. It changes admission while retaining the underlying formula’s widths and flat-oracle/book/risk checks. Existing corridors still settle normally. High volatility is a hypothesis to test, not an assurance that the oracle will keep updating. Since these formulas already scale widths with volatility, a volatility gate only helps pricing if their residual errors depend on that regime.','',
        f'The mild sixty-second gate illustrates a useful tradeoff for HYPE X100 weekdays: survival falls from {pct(data["HYPE"]["results"]["trial"]["100"]["active_hybrid"]["none"]["matched"]["weekday"]["pooled"]["survival"])} to {pct(data["HYPE"]["results"]["trial"]["100"]["active_hybrid"]["fast25"]["matched"]["weekday"]["pooled"]["survival"])}; total quote availability falls from {pct(data["HYPE"]["results"]["trial"]["100"]["active_hybrid"]["none"]["matched"]["weekday"]["pooled"]["availability"])} to {pct(data["HYPE"]["results"]["trial"]["100"]["active_hybrid"]["fast25"]["matched"]["weekday"]["pooled"]["availability"])}. The stricter Q75 gate reaches {pct(data["HYPE"]["results"]["trial"]["100"]["active_hybrid"]["fast75"]["matched"]["weekday"]["pooled"]["survival"])} survival but retains only {pct(data["HYPE"]["results"]["trial"]["100"]["active_hybrid"]["fast75"]["matched"]["weekday"]["pooled"]["availability"])} availability. This is a historical comparison, not a threshold recommendation. X1000 remains miscalibrated or too sparse at usable availability.','',
        f'For the HYPE X100 strict sixty-second gate, the weekday open share is {pct(exposed["HYPE"]["trial"]["matched"]["weekday"]["fast75"]["open_share"])} and quotes are available on {pct(data["HYPE"]["results"]["trial"]["100"]["active_hybrid"]["fast75"]["matched"]["weekday"]["pooled"]["offered"] / exposed["HYPE"]["trial"]["matched"]["weekday"]["fast75"]["open"])} of those open entries. This can inform an intermittent-admission product, but does not preserve all-day availability or establish a validated safe regime.','',
        '## Frozen policy and comparison','',
        'Each UTC midnight, fit exact date-balanced 25th, 50th and 75th percentiles using only matured admissible paths on the last three observed earlier training dates. Test preceding sixty-second volatility and preceding five-minute volatility separately. Early training can use monthly samples; no interpolation fills the intervals. The thresholds and seven gate variants were declared before replay, and no gate is selected from September outcomes.','',
        'Two fixed underlying formulas are compared: `active_hybrid` uses the active-state empirical tail at X100 and the native parametric marginal-calibrated tail at X1000; `conditional_recent` uses the previous conditional-tail revision at both payouts. The hybrid was declared before gate replay, after observing that the empirical X1000 model lacked rare-tail support and that the parametric X100 fit regressed. This is outcome-informed development, not an untouched comparison.','',
        'The full replay retains fourteen earlier monthly out-of-sample dates and September 1–10, 2026. All rules use the same clean-path denominators. Zero wins on a tiny quote set do not establish calibration. Opening is evaluated on the thirty-second entry grid, without hysteresis, minimum dwell time or execution costs.','',
        '## Weekday and weekend results','',
        'Targets are 0.950% trader survival at X100 and 0.095% at X1000. The table uses clean oracle paths with fresh strictly prior books. Quote availability remains measured across every eligible entry, including entries when the gate closes.','']
    for a in ('ETH','HYPE'):
        for m in ('100','1000'):
            lines += [f'### {a} X{m}','', '| Formula | Gate | Weekday wins / quotes (rate) | Weekday quote availability | Weekend wins / quotes (rate) | Weekend quote availability |','| --- | --- | ---: | ---: | ---: | ---: |']
            for b in BASES:
                for gate in GATES:
                    r=data[a]['results']['trial'][m][b][gate]['matched'];w=r['weekday']['pooled'];e=r['weekend']['pooled'];lines.append(f'| {b} | {names[gate]} | {rate(w)} | {pct(w["availability"])} | {rate(e)} | {pct(e["availability"])} |')
            lines.append('')
    lines += ['## Open share versus quotes while open','',
        'Open share is the fraction of clean eligible sampled entries where the volatility gate allows admission. It is not uninterrupted wall-clock uptime. Quotes while open divide accepted quotes by that open count; existing book and risk vetoes can still refuse. These two rates are reported alongside total availability to keep closed periods visible. Values below are for `active_hybrid`; open share is identical for both bases and payouts.','',
        '| Asset | Gate | Weekday open share | X100 weekday quotes while open | X1000 weekday quotes while open | Weekend open share | X100 weekend quotes while open | X1000 weekend quotes while open |','| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |']
    for a in ('ETH','HYPE'):
        for gate in GATES:
            cells=[]
            for g in ('weekday','weekend'):
                e=exposed[a]['trial']['matched'][g][gate];cells.append(pct(e['open_share']))
                for m in ('100','1000'):
                    p=data[a]['results']['trial'][m]['active_hybrid'][gate]['matched'][g]['pooled'];cells.append(pct(p['offered']/e['open'] if e['open'] else None))
            lines.append(f'| {a} | {names[gate]} | '+' | '.join(cells)+' |')
    lines += ['', '## Earlier monthly comparisons','',
        'These fourteen dates span July 2025–August 2026. The initial six monthly dates are fit warmup. They are not a consecutive sample and do not select a cutoff.','',
        '| Asset / payout | Formula | Gate | Wins / quotes (rate) | Total quote availability | Worst date availability |','| --- | --- | --- | ---: | ---: | ---: |']
    for a in ('ETH','HYPE'):
        for m in ('100','1000'):
            for b in BASES:
                for gate in GATES:
                    s=data[a]['results']['earlier_oof'][m][b][gate]['matched']['overall'];p=s['pooled'];lines.append(f'| {a} X{m} | {b} | {names[gate]} | {rate(p)} | {pct(p["availability"])} | {pct(s["minimum_daily_availability"])} |')
    lines += ['', '## Screens, evidence and reproducibility','',
        'The inherited descriptive screens are unchanged: nonempty quotes every date, at least 85% quote availability every date, pooled survival within 75–125% of target, nonnegative zero-cost gross and at least twenty target-expected evaluated wins. Deliberately closing the protocol changes the product’s availability tradeoff; quotes while open do not satisfy that original all-entry requirement. The complete packet retains daily counts, open exposure, all clean-oracle denominators, refusals, unresolved offers, gross stake arithmetic and screen reasons.','',
        'This sample contains only two September weekend dates and repeatedly inspected outcomes. It can measure historical associations and identify bad gates; it cannot ensure future thirty-second survival probabilities or establish that low liquidity causes weekend wins. X1000 tails remain especially sparse. No rule is deployed, and the ongoing fresh recorder remains unchanged.','',
        f'The audit independently reconstructed {sum(x["gate_decisions_replayed"] for x in audit["assets"]):,} paired gate decisions, refitted all earlier-only thresholds using independent exact weighted quantiles, checked that gating never adds an offer or changes a width, and reconciled every daily/calendar/cohort result. A separate exposure pass independently checked both opening predicates on every row. Thirty-eight regression tests pass across the research stack.','',
        f'Packet: `{root.resolve()}`. Research SHA-256: `{digest(root/"research.json")}`. Audit SHA-256: `{digest(root/"audit.json")}`. Exposure SHA-256: `{digest(root/"opening-exposure.json")}`. Complete local sources and input hashes were frozen before gate replay. Underlying formula development is documented in [ACTIVE_TAIL_PAYOUT_RESEARCH.md](/Volumes/dev/fuse/docs/ACTIVE_TAIL_PAYOUT_RESEARCH.md).','',
        '```sh',
        'python3 -B scripts/research_volatility_open_gate.py --declare --active .local/adaptive-corridor/20261029-active-tail-payout-v1 --conditional .local/adaptive-corridor/20261029-conditional-tail-payout-v1 --output .local/adaptive-corridor/NEW-VOLATILITY-GATE',
        'OPENBLAS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 OMP_NUM_THREADS=1 python3 -B scripts/research_volatility_open_gate.py --output .local/adaptive-corridor/NEW-VOLATILITY-GATE',
        'OPENBLAS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 OMP_NUM_THREADS=1 python3 -B scripts/research_volatility_open_gate.py --audit --output .local/adaptive-corridor/NEW-VOLATILITY-GATE',
        'python3 -B scripts/report_volatility_open_gate.py --research .local/adaptive-corridor/NEW-VOLATILITY-GATE --output docs/VOLATILITY_OPEN_GATE_RESEARCH.md',
        'PYTHONPATH=scripts OPENBLAS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 OMP_NUM_THREADS=1 python3 -B -m unittest scripts.test_historical_liquidity scripts.test_trial_liquidity scripts.test_trial_payout scripts.test_flat_aware_payout scripts.test_flat_risk_overlay scripts.test_active_tail_payout scripts.test_conditional_tail_payout scripts.test_volatility_open_gate',
        '```','']
    output.write_text('\n'.join(lines));return dict(output=str(output),gate_decisions=sum(x['gate_decisions_replayed'] for x in audit['assets']))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--research',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();print(json.dumps(render(a.research,a.output)))
