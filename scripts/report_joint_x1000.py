#!/usr/bin/env python3
"""Render audited joint-state X1000 comparisons without outcome selection."""
import argparse
import json
from pathlib import Path

from joint_x1000 import TARGET,VARIANTS
from research_payout_risk import digest
from research_joint_x1000 import verify_plan


def load(root):
    meta=json.loads((root/'research.json').read_text());audit=json.loads((root/'audit.json').read_text())
    if not audit['passed'] or audit['research_sha256']!=digest(root/'research.json'):raise ValueError('Matching passed audit required')
    data={}
    for a,sha in meta['research_sha256'].items():
        if digest(root/a/'research.json')!=sha:raise ValueError('Report asset differs')
        data[a]=json.loads((root/a/'research.json').read_text())
    return data,audit


def pct(x):return '—' if x is None else f'{100*x:.3f}%'
def pp(x):return '—' if x is None else f'{100*x:.3f} pp'
def rate(p):return f'{p["wins"]:,} / {p["offered"]:,} ({pct(p["survival"])})'


def render(root,gate_root,output,online_root=None):
    plan=verify_plan(root);new,audit=load(root);old,_=load(Path(plan['active']));conditional,_=load(Path(plan['conditional']));gates,_=load(gate_root)
    online,online_audit=load(online_root) if online_root else (None,None)
    if online_root:
        op=json.loads((online_root/'protocol.json').read_text())
        if Path(op['parent'])!=root.resolve() or op['parent_sha256']!=digest(root/'research.json'):raise ValueError('Online comparison parent differs')
    labels={'joint_online_flat':'Joint model, delayed flat feedback','joint_online_full':'Joint model, delayed flat and tail feedback (second declared primary)','previous':'Previous native calibration','volatility':'Previous mild volatility gate','conditional':'Previous conditional calibration','joint_raw':'Joint model, raw budget','joint_global':'Joint model, global calibration','joint_local':'Joint model, local risk calibration (declared primary)'}
    def variants(a,phase):
        return [('previous',old[a]['results'][phase]['1000']['active_calibrated']),('volatility',gates[a]['results'][phase]['1000']['active_hybrid']['fast25']),('conditional',conditional[a]['results'][phase]['1000']['conditional_recent'])]+list(new[a]['results'][phase].items())+([(v,online[a]['results'][phase][v]) for v in ('joint_online_flat','joint_online_full')] if online else [])
    # Never compare different oracle/book denominators as an availability gain.
    for a in ('ETH','HYPE'):
        for phase in ('trial','earlier_oof'):
            for cohort in ('matched','all_clean'):
                for g in ('overall','weekday','weekend'):
                    ns={r[cohort][g]['pooled']['eligible'] for _,r in variants(a,phase)}
                    if len(ns)!=1:raise ValueError('Comparison denominators differ')
    lines=['# Joint volatility, oracle activity and liquidity: X1000 revision','',
        'This revision fits native thirty-second X1000 corridor risk from the combined state of volatility, oracle price-change activity and measured book liquidity. ETH and HYPE are fitted separately. The target trader survival is 0.095%. The replay scores September 1–10, 2026 UTC, with weekday/weekend comparisons, and fourteen earlier monthly out-of-sample dates. All outcomes belong to repeatedly inspected historical development.','',
        'The first declared primary is `joint_local`; `joint_global` and `joint_raw` are fixed ablations. After inspecting that replay, a separate delayed-feedback revision was declared with `joint_online_full` primary and a flat-only ablation. Both packets preserve their declarations. The report does not silently select a different asset-specific winner from later results. Live pricing and the ongoing fresh collector remain unchanged.','',
        '## Consecutive results','',
        'Availability divides resolved accepted quotes by the same clean oracle paths with fresh strictly prior books. Missing books are retained in the secondary all-clean denominator. A zero-win quote set is reported as observed zero, not as a proven risk-free price.','']
    if online:
        lines += ['The delayed-feedback primary moves both assets closer to the target, with an availability cost. The following pooled comparison uses the original native calibrated model as the baseline; it is not a fresh validation sample.','',
            '| Asset | Previous rate / availability | Delayed-feedback rate / availability | Wins / quotes after feedback |','| --- | ---: | ---: | ---: |']
        for a in ('ETH','HYPE'):
            b=old[a]['results']['trial']['1000']['active_calibrated']['matched']['overall']['pooled'];x=online[a]['results']['trial']['joint_online_full']['matched']['overall']['pooled'];lines.append(f'| {a} | {pct(b["survival"])} / {pct(b["availability"])} | {pct(x["survival"])} / {pct(x["availability"])} | {x["wins"]} / {x["offered"]:,} |')
        e=new['ETH']['results']['trial']['joint_global']['matched']['overall']['pooled'];h=online['HYPE']['results']['trial']['joint_online_full']['matched']['overall']['pooled']
        lines += ['',f'The ETH global-calibration ablation offers a stronger availability tradeoff in this development sample: {pct(e["survival"])} survival at {pct(e["availability"])} availability. This does not retrospectively change the declared primary. HYPE delayed-feedback survival remains {h["survival"]/TARGET:.2f} times target. No tested rule meets all existing evidence and availability screens.','']
    for a in ('ETH','HYPE'):
        lines += [f'### {a}','', '| Formula | Weekday wins / quotes (rate) | Weekday availability | Weekend wins / quotes (rate) | Weekend availability |','| --- | ---: | ---: | ---: | ---: |']
        for v,r in variants(a,'trial'):
            w=r['matched']['weekday']['pooled'];e=r['matched']['weekend']['pooled'];lines.append(f'| {labels[v]} | {rate(w)} | {pct(w["availability"])} | {rate(e)} | {pct(e["availability"])} |')
        lines.append('')
    lines += ['## Pricing versus availability','', '| Asset | Formula | Pooled wins / quotes (rate) | Total availability | Availability versus previous native | Absolute target error | Worst date availability | Target expected wins |','| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |']
    for a in ('ETH','HYPE'):
        before=old[a]['results']['trial']['1000']['active_calibrated']['matched']['overall']['pooled']
        for v,r in variants(a,'trial'):
            s=r['matched']['overall'];p=s['pooled'];retention=p['availability']/before['availability'] if before['availability'] else None;error=abs(p['survival']-TARGET) if p['survival'] is not None else None
            lines.append(f'| {a} | {labels[v]} | {rate(p)} | {pct(p["availability"])} | {pct(retention)} | {pp(error)} | {pct(s["minimum_daily_availability"])} | {p["target_expected_wins"]:.3f} |')
    lines += ['', 'Availability versus previous native is a retention ratio: 100% means the same total quote availability. Target error is the absolute difference in probability, shown in percentage points. Neither is statistical confidence. No entry is forced open to meet an availability objective.','',
        '## Formula changes','',
        'The prior model already included individual volatility/activity/liquidity inputs. The new feature map adds three idle-age hinges, two oracle-change-count hinges and nine joint interactions. These include recent volatility by activity, activity by spread and minimum-side top-five depth, idle by those liquidity measures, and idle by absolute book imbalance. Calendar and fresh market/oracle context remain available. Feature construction reads only pre-entry observations; current survival and future data validity are excluded.','',
        'The zero-motion logistic head uses ridge 0.0003. Its fitted probability ranks each entry into four groups, with quartile boundaries computed solely from date-weighted earlier training predictions. This rank combines the three signal families; it does not require closing an entire volatility quartile. The same fitted feature map conditions the positive-movement tail.','',
        'The old single lognormal positive tail is replaced by a log-logistic tail. Fit a ridge-0.01 location model to positive log required native width divided by preceding five-minute volatility. Set logistic residual scale to the weighted residual standard deviation times sqrt(3)/pi, with minimum 0.08. For native width `w > 0`, the modeled survival is `p0 + (1 − p0) × sigmoid((log(w / slow_vol_ppb) − μ) / s)`. This is a parametric tail assumption, not twenty empirical rare-tail observations.','',
        'Invert the positive component at `(budget − p0) / (1 − p0)`, round width downward to integer ppb, and retain the 50,000-ppm maximum. The model refuses an entry when predicted flat risk or minimum-representable-width risk exceeds its budget. Corridors have a strictly positive integer price delta; touching either barrier loses. The flat-oracle veto, five-minute history and strictly prior book freshness remain required. A stale book or unknown idle-age lower bound cannot create a quote.','',
        'Each daily origin fits from the last ten observed earlier admissible dates of that asset, with equal date mass. At least 200 total paths and 200 positive paths across five earlier dates are required. These are observed sample dates, not necessarily consecutive calendar days: early warmup includes monthly history. Training labels enter only if expiry plus thirty seconds is strictly before the daily origin.','',
        '## Joint calibration and controls','',
        'All clean admissible out-of-sample outcomes enter future calibration, including previously refused paths. Native quantization is included in each reference’s admission and win threshold. At each origin, only earlier-date references with expiry plus thirty seconds strictly before UTC midnight are permitted. There is no within-day outcome update.','',
        'Evaluate 81 predeclared model budgets: `0.00095 × 2^(k/8)` for integer k from −48 through 32. Estimate wins divided by offers at each budget, date-balanced over the last ten matching observed reference dates, with identity prior mass 32. Require at least 200 offered references across three dates. Choose the highest passing budget whose smoothed conditional estimate is at most 0.00095. This is sparse-reference model calibration, not a confidence bound; 200 references and prior mass 32 do not establish a 0.095% tail.','',
        '`joint_raw` uses the raw target budget. `joint_global` tries the entry’s weekday/weekend reference group, then global, then recorded raw-identity fallback. `joint_local` first tries weekday/weekend plus risk-rank group, then that risk group across calendars, then the calendar group, global, and identity. Supported local groups can preserve useful states that a single hard volatility cutoff would remove. They can also overfit sparse tail references; the ablations expose that tradeoff.','',
        'This iteration changes interactions, fit recency, tail shape and calibration together. Its comparisons cannot attribute an improvement solely to liquidity or establish why weekends differ. The three new ablations isolate calibration within the same new fitted model, not every bundled modeling choice.','',
        '## Daily primary and global-calibration quotes','', '| UTC date | ETH primary quotes / wins | ETH global quotes / wins | HYPE primary quotes / wins | HYPE global quotes / wins |','| --- | ---: | ---: | ---: | ---: |']
    daily={a:{v:new[a]['results']['trial'][v]['matched']['overall']['daily'] for v in ('joint_local','joint_global')} for a in ('ETH','HYPE')}
    for i,e in enumerate(daily['ETH']['joint_local']):
        cells=[]
        for a in ('ETH','HYPE'):
            for v in ('joint_local','joint_global'):
                x=daily[a][v][i]
                if x['period']!=e['period']:raise ValueError('Daily comparison differs')
                cells.append(f'{x["offered"]:,} / {x["wins"]}')
        lines.append(f'| {e["period"]} | '+' | '.join(cells)+' |')
    lines += ['', '## Screens and flat-path exposure','', '| Asset | Formula | Flat-path wins | Gross LP per stake | Identity-fallback offers | Screen failures |','| --- | --- | ---: | ---: | ---: | --- |']
    for a in ('ETH','HYPE'):
        for v in VARIANTS:
            r=new[a]['results']['trial'][v];s=r['matched']['overall'];p=s['pooled'];lines.append(f'| {a} | {labels[v]} | {p["zero_motion_wins"]} | {pct(p["gross_lp_per_stake"])} | {s["identity_fallback_offers"]:,} | {", ".join(r["screen"]["reasons"]) or "None"} |')
    if online:
        lines += ['', '## Delayed within-day revision','',
            'The first HYPE local calibration misses the goal: 0.525% pooled survival at 8.023% availability, with eight of its ten wins on the first trial date. Older low-risk monthly reference groups initially allow wider budgets, then later observations can suppress most quotes. The second revision reuses the frozen joint models, returns to the raw 0.00095 mixture budget, and corrects the component probabilities using only recently matured observations. It does not refit coefficients or use the current path.', '',
            'Flat correction multiplies raw zero-motion odds by `(1 + recent observed zero paths) / (1 + sum recent raw p0)`, bounded from 0.1 to 10 and enabled after sixty matured references. All healthy admissible outcomes contribute, even when no quote was offered. This can correct overestimated flat risk while retaining the explicit pre-entry flat veto.', '',
            'The full correction also evaluates the raw positive-component CDF at each observed native required width. Among positive paths, multiply positive-CDF odds by `(1 + scores at or below 0.01) / (1 + 0.01 × positive count)`, bounded from 0.25 to 4 and enabled after one hundred positive references. The fixed one-percent anchor supplies more observations than the X1000 extreme tail. The equivalent log-logistic location shift is `mu_corrected = mu − scale × log(tail_factor)`. Extrapolation from that anchor remains a modeling assumption.', '',
            'Memory retains the last 480 matured valid admissible references whose expiry is within six hours. References enter only when expiry plus thirty seconds is strictly earlier than entry. State carries across consecutive days and ages out monthly gaps. Raw forecasts at each reference entry remain frozen; feedback does not compare labels with retrospectively corrected probabilities. Invalid/disconnected paths never count as zero wins. The one-event prior prevents a zero probability estimate, but supplies no rare-event confidence guarantee.', '',
            'The static second-packet control exactly reproduces every parent joint_raw quote. The independent auditor uses offline indexed maturity slices to reconstruct the forward pending/recent queues at every entry. This checks the principal lookahead risk with a different data flow.', '',
            '| Asset / variant | Wins / quotes (rate) | Availability | Flat-path wins | Offers with active feedback | Screen failures |',
            '| --- | ---: | ---: | ---: | ---: | --- |']
        for a in ('ETH','HYPE'):
            for v in ('joint_online_flat','joint_online_full'):
                r=online[a]['results']['trial'][v];s=r['matched']['overall'];p=s['pooled'];lines.append(f'| {a} / {v} | {rate(p)} | {pct(p["availability"])} | {p["zero_motion_wins"]} | {s["offers_with_active_feedback"]:,} | {", ".join(r["screen"]["reasons"]) or "None"} |')
        lines += ['', '| UTC date | ETH full feedback quotes / wins | HYPE full feedback quotes / wins |','| --- | ---: | ---: |']
        for e,h in zip(online['ETH']['results']['trial']['joint_online_full']['matched']['overall']['daily'],online['HYPE']['results']['trial']['joint_online_full']['matched']['overall']['daily']):
            if e['period']!=h['period']:raise ValueError('Online daily dates differ')
            lines.append(f'| {e["period"]} | {e["offered"]:,} / {e["wins"]} | {h["offered"]:,} / {h["wins"]} |')
    lines += ['', 'The unchanged descriptive screens require a nonempty quote set every date, at least 85% availability every date, pooled survival within 75–125% of target, nonnegative zero-cost gross, and at least twenty target-expected evaluated wins. X1000 needs at least 21,053 accepted quotes to reach that last count reference. Sparse parametric or local calibration support does not waive it. Quotes are measured across all eligible entries; no closed-period denominator adjustment is used.','',
        'LP gross assumes one stake per resolved accepted quote and total payout including the returned stake: `(quotes − 1000 × wins) / quotes`. It excludes fees, hedging, funding, latency, capacity and correlated losses. Even near-target sample survival or positive sample gross does not establish future calibration or net profitability.','',
        '## Earlier monthly results','',
        'These fourteen first-of-month out-of-sample dates span July 2025–August 2026, after six monthly warmup dates. They are reported separately and do not select the primary.','',
        '| Asset | Formula | Wins / quotes (rate) | Availability | Worst date availability |','| --- | --- | ---: | ---: | ---: |']
    for a in ('ETH','HYPE'):
        for v,r in variants(a,'earlier_oof'):
            s=r['matched']['overall'];p=s['pooled'];lines.append(f'| {a} | {labels[v]} | {rate(p)} | {pct(p["availability"])} | {pct(s["minimum_daily_availability"])} |')
    lines += ['', '## All clean oracle paths','',
        'Missing books remain in these secondary denominators and are refused. The complete packet retains every daily and calendar summary for both cohorts.','',
        '| Asset | Formula | Weekday availability | Weekend availability |','| --- | --- | ---: | ---: |']
    for a in ('ETH','HYPE'):
        for v in list(VARIANTS)+(['joint_online_flat','joint_online_full'] if online else []):
            r=(online if v.startswith('joint_online') else new)[a]['results']['trial'][v]['all_clean'];lines.append(f'| {a} | {labels[v]} | {pct(r["weekday"]["pooled"]["availability"])} | {pct(r["weekend"]["pooled"]["availability"])} |')
    lines += ['', '## Verification and evidence limits','',
        f'The independent audit refitted {sum(x["models_refit"] for x in audit["assets"])} earlier-only joint models, reconstructed every calendar/risk calibration candidate, replayed {sum(x["decisions_independently_replayed"] for x in audit["assets"]):,} decisions, and reconciled all daily/calendar/cohort metrics. Source, origin, trace and input hashes match. Forty-nine regression tests pass across the research stack. Seven new tests cover joint feature/outcome isolation, native positive width and touch settlement, stale/flat/missing vetoes, date and asset isolation, last-ten-date fitting, calibration maturity/group fallback, complete export/replay and tamper rejection.','',
        'September provides eight weekday dates and only two weekend dates. These repeatedly inspected outcomes are development evidence, not a fresh holdout or proof of a safe operating regime. A zero-win weekend or a point estimate near target can be uninformative at the available quote count. The frozen formula must be evaluated on new data before any promotion. Neither live pricing nor the ongoing fresh recorder is modified.','',
        f'Research packet: `{root.resolve()}`. Research SHA-256: `{digest(root/"research.json")}`. Audit SHA-256: `{digest(root/"audit.json")}`. Volatility comparison packet: `{gate_root.resolve()}`, research SHA-256 `{digest(gate_root/"research.json")}` and audit SHA-256 `{digest(gate_root/"audit.json")}`. Complete imported source snapshots, per-origin models/calibration grids and all accepted, refused and unresolved decisions are retained.','',
        '```sh',
        'PYTHONPATH=scripts OPENBLAS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 OMP_NUM_THREADS=1 python3 -B -m unittest scripts.test_historical_liquidity scripts.test_trial_liquidity scripts.test_trial_payout scripts.test_flat_aware_payout scripts.test_flat_risk_overlay scripts.test_active_tail_payout scripts.test_conditional_tail_payout scripts.test_volatility_open_gate scripts.test_joint_x1000 scripts.test_online_joint_x1000',
        'python3 -B scripts/research_joint_x1000.py --declare --active .local/adaptive-corridor/20261029-active-tail-payout-v1 --conditional .local/adaptive-corridor/20261029-conditional-tail-payout-v1 --output .local/adaptive-corridor/NEW-JOINT-X1000',
        'OPENBLAS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 OMP_NUM_THREADS=1 python3 -B scripts/research_joint_x1000.py --output .local/adaptive-corridor/NEW-JOINT-X1000',
        'OPENBLAS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 OMP_NUM_THREADS=1 python3 -B scripts/research_joint_x1000.py --audit --output .local/adaptive-corridor/NEW-JOINT-X1000',
        'python3 -B scripts/report_joint_x1000.py --research .local/adaptive-corridor/NEW-JOINT-X1000 --volatility .local/adaptive-corridor/20261029-volatility-open-gate-v1 --output docs/JOINT_X1000_RESEARCH.md',
        '```','']
    if online:
        lines += [f'Online packet: `{online_root.resolve()}`. Its independent audit replays {sum(x["decisions_independently_replayed"] for x in online_audit["assets"]):,} additional decisions, verifies static-parent reproduction and checks every causal feedback state against offline maturity slices. Research SHA-256: `{digest(online_root/"research.json")}`. Audit SHA-256: `{digest(online_root/"audit.json")}`. Four additional tests cover strict maturity, invalid paths, gap expiry, bounded memory, independent state reconstruction, future-label invariance, corrected width direction and complete static/export/audit/tamper rejection.','',
            '```sh',
            'python3 -B scripts/research_online_joint_x1000.py --declare --parent .local/adaptive-corridor/NEW-JOINT-X1000 --output .local/adaptive-corridor/NEW-ONLINE-JOINT-X1000',
            'OPENBLAS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 OMP_NUM_THREADS=1 python3 -B scripts/research_online_joint_x1000.py --output .local/adaptive-corridor/NEW-ONLINE-JOINT-X1000',
            'OPENBLAS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 OMP_NUM_THREADS=1 python3 -B scripts/research_online_joint_x1000.py --audit --output .local/adaptive-corridor/NEW-ONLINE-JOINT-X1000',
            'python3 -B scripts/report_joint_x1000.py --research .local/adaptive-corridor/NEW-JOINT-X1000 --online .local/adaptive-corridor/NEW-ONLINE-JOINT-X1000 --volatility .local/adaptive-corridor/20261029-volatility-open-gate-v1 --output docs/JOINT_X1000_RESEARCH.md',
            '```','']
    output.write_text('\n'.join(lines));return dict(output=str(output),decisions=sum(x['decisions_independently_replayed'] for x in audit['assets']))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--research',type=Path,required=True);p.add_argument('--online',type=Path);p.add_argument('--volatility',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();print(json.dumps(render(a.research,a.volatility,a.output,a.online)))
