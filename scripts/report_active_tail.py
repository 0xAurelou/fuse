#!/usr/bin/env python3
"""Render audited active/conditional-tail development comparisons."""
import argparse
import json
from pathlib import Path

from research_payout_risk import digest

LABELS={'overlay':'Previous conservative overlay','active_empirical':'Active-state empirical control','active_parametric':'Native parametric, raw budget','active_calibrated':'Marginal CDF calibration','conditional_all':'Offer-conditional, full history','conditional_recent':'Offer-conditional, recent history'}


def load(root):
    audit=json.loads((root/'audit.json').read_text());meta=json.loads((root/'research.json').read_text())
    if not audit['passed'] or audit['research_sha256']!=digest(root/'research.json'):raise ValueError('Matching passed audit required')
    data={}
    for a,sha in meta['research_sha256'].items():
        if digest(root/a/'research.json')!=sha:raise ValueError('Report asset differs')
        data[a]=json.loads((root/a/'research.json').read_text())
    return data,audit


def pct(x):return '—' if x is None else f'{100*x:.3f}%'
def rate(p):return f"{p['wins']:,} / {p['offered']:,} ({pct(p['survival'])})"


def render(previous,active,conditional,output):
    old,oa=load(previous);raw,ra=load(active);new,na=load(conditional)
    models=lambda a,m,phase:[('overlay',old[a]['results'][phase][str(m)])]+list(raw[a]['results'][phase][str(m)].items())+list(new[a]['results'][phase][str(m)].items())
    lines=['# Active-state and conditional-tail ETH/HYPE corridor revision','',
        'This development revision restores positive native-width X1000 quotes and recalibrates survival on the paths that a budget would actually offer. Separate asset fits, the explicit pre-entry flat-oracle veto, strict barrier settlement and common availability denominators are retained. The daily replay covers September 1–10, 2026 UTC; fourteen earlier monthly dates are reported separately. These are repeatedly inspected historical outcomes, not a fresh holdout.','',
        'The primary declared candidate is `conditional_recent`. The full-history conditional version is an ablation, not an outcome-selected replacement. No policy passes all existing availability, calibration and evidence screens. The live engine and ongoing fresh collector were not changed.','',
        'The recent primary revision misses the HYPE objective: weekday X100 survival is 1.875% versus the previous overlay’s 1.799%, while availability falls from 59.640% to 32.429%. It should not replace the previous rule. X1000 quotes return, but HYPE still has an excessive observed win rate, and one weekend date has no HYPE X1000 quotes. The first marginal-calibration attempt offers more X1000 quotes but is also overpriced.','',
        '## Formula and causal calibration','',
        'The previous empirical hurdle was too restrictive for X1000. The new models fit only states eligible to quote: a healthy five-minute feature history, a fresh strictly prior book, known idle age below thirty seconds, and at least one price change in the preceding thirty seconds. The blanket X1000 four-change/three-second recovery rule is replaced by learned risk. The flat veto remains. Models for ETH and HYPE are fitted independently; neither reuses BTC coefficients.','',
        'Two date-weighted logistic heads estimate zero-motion and one-ppm survival from calendar/activity features and six measured liquidity inputs. A separate ridge regression fits the logarithm of positive required width, normalized by preceding five-minute volatility, with a Gaussian residual. Positive-tail fits require 200 paths across five earlier dates. This lognormal tail is an extrapolation assumption; it does not manufacture twenty empirical rare-tail observations. The empirical comparator retains that original support gate.','',
        'For width `w > 0`, the native model estimates `F(w) = p0 + (1 − p0) Φ((log(w / slow_vol_ppb) − μ) / σ)`. At budget `b`, invert the positive component at `(b − p0) / (1 − p0)`, round width downward to integer ppb and retain the 50,000-ppm maximum. Refuse if a strictly positive representable barrier already exceeds budget. Settlement uses the actual integer price delta; touching loses. Native ppb precision allows positive corridors below the old one-ppm floor.','',
        'The first calibration attempt inverted the marginal CDF of scores over all admissible paths. It restored many X1000 quotes but worsened HYPE weekday pricing. Its denominator included states that the resulting budget would refuse. The correction estimates historical wins divided by historical offers at each candidate budget, with native minimum/maximum width and quantization included. Refused paths remain available to teach future budgets, but do not dilute the conditional survival estimate.','',
        'The two conditional variants examine 81 fixed budgets: `(0.95 / M) × 2^(k/8)` for integer `k = −48 … 32`. Dates have equal mass. The historical conditional rate is shrunk toward the candidate budget with identity prior mass 32. Choose the largest budget whose estimate does not exceed `0.95 / M`, requiring 200 offered references across three dates. These are fit-support conditions, not rare-event confidence. If the matching weekday/weekend calibration is unsupported, use global history; if that is unsupported, retain the raw model budget and record identity fallback. A failed calibration does not silently count as a supported estimate.','',
        'The recent variant uses the last three observed matching calendar dates at X100 and the last ten at X1000; the full-history variant retains all earlier reference dates. These are observed dates, so the early fallback can still include nonconsecutive monthly history. The shorter X100 window is intended to track regime changes; the longer X1000 window retains more sparse-tail observations. All thresholds and variants were frozen before their replay.','',
        'Daily model fits use only strictly earlier matched paths whose expiry plus thirty seconds precedes the origin. Calibration uses earlier out-of-sample forecasts and all matured admissible outcomes, including previously refused quotes; no current-date labels enter. Calibration is frozen at UTC midnight. Missing or disconnected paths are censored, not treated as flat wins.','',
        '## Consecutive weekday and weekend results','',
        'Trader survival targets are 0.950% at X100 and 0.095% at X1000. Availability is resolved accepted quotes divided by the same clean oracle paths with fresh pre-entry books. Eight weekday dates and two weekend dates are included. Empty quote sets have no estimated win rate.','']
    for a in ('ETH','HYPE'):
        lines += [f'### {a}','', '| Payout | Formula | Weekday wins / quotes (rate) | Weekday availability | Weekend wins / quotes (rate) | Weekend availability |','| --- | --- | ---: | ---: | ---: | ---: |']
        for m in (100,1000):
            for v,r in models(a,m,'trial'):
                x=r['matched']['weekday']['pooled'];y=r['matched']['weekend']['pooled']
                lines.append(f'| X{m} | {LABELS[v]} | {rate(x)} | {pct(x["availability"])} | {rate(y)} | {pct(y["availability"])} |')
        lines.append('')
    lines += ['## Primary revision versus the previous overlay','', '| Asset / payout | Weekday rate, before → after | Weekday availability, before → after | Weekend rate, before → after | Weekend availability, before → after |','| --- | ---: | ---: | ---: | ---: |']
    for a in ('ETH','HYPE'):
        for m in (100,1000):
            before=old[a]['results']['trial'][str(m)]['matched'];after=new[a]['results']['trial'][str(m)]['conditional_recent']['matched']
            cells=[]
            for g in ('weekday','weekend'):
                b=before[g]['pooled'];x=after[g]['pooled'];cells.extend([pct(b['survival'])+' → '+pct(x['survival']),pct(b['availability'])+' → '+pct(x['availability'])])
            lines.append(f'| {a} X{m} | '+' | '.join(cells)+' |')
    lines += ['', '## Primary revision: daily X1000 offers','', '| UTC date | ETH quotes | ETH availability | HYPE quotes | HYPE availability |','| --- | ---: | ---: | ---: | ---: |']
    ed=new['ETH']['results']['trial']['1000']['conditional_recent']['matched']['overall']['daily'];hd=new['HYPE']['results']['trial']['1000']['conditional_recent']['matched']['overall']['daily']
    for e,h in zip(ed,hd):
        if e['period']!=h['period']:raise ValueError('Daily report mismatch')
        lines.append(f'| {e["period"]} | {e["offered"]:,} | {pct(e["availability"])} | {h["offered"]:,} | {pct(h["availability"])} |')
    lines += ['', '## Primary revision: pooled support and economics','', '| Asset / payout | Wins / quotes (rate) | Flat-path wins | Availability | Worst date availability | Target expected wins | LP gross per stake | Screen failures |','| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |']
    for a in ('ETH','HYPE'):
        for m in (100,1000):
            r=new[a]['results']['trial'][str(m)]['conditional_recent'];s=r['matched']['overall'];p=s['pooled']
            lines.append(f'| {a} X{m} | {rate(p)} | {p["zero_motion_wins"]} | {pct(p["availability"])} | {pct(s["minimum_daily_availability"])} | {p["target_expected_wins"]:.3f} | {pct(p["gross_lp_per_stake"])} | {", ".join(r["screen"]["reasons"])} |')
    lines += ['', 'LP gross assumes one stake per resolved accepted quote and total payout including returned stake: `(quotes − M × wins) / quotes`. It excludes fees, hedging, funding, latency, capital requirements and correlated losses. A positive sample gross is not established net profitability.','',
        'The unchanged necessary screens require nonempty quotes on every date, 85% availability on every date, pooled survival within 75–125% of target, nonnegative zero-cost gross, and twenty target-expected evaluated wins. X1000 needs at least 21,053 accepted quotes for that final reference; parametric extrapolation does not waive it. A zero-win weekend with few quotes is not evidence of accurately priced X1000 risk.','',
        '## Earlier monthly results','',
        'These fourteen first-of-month out-of-sample dates span July 2025–August 2026. The initial six monthly dates are warmup. This is distinct from the consecutive September period, and no candidate is selected from these comparisons.','',
        '| Asset / payout | Formula | Wins / quotes (rate) | Availability | Worst date availability |','| --- | --- | ---: | ---: | ---: |']
    for a in ('ETH','HYPE'):
        for m in (100,1000):
            for v,r in models(a,m,'earlier_oof'):
                s=r['matched']['overall'];p=s['pooled'];lines.append(f'| {a} X{m} | {LABELS[v]} | {rate(p)} | {pct(p["availability"])} | {pct(s["minimum_daily_availability"])} |')
    lines += ['', '## Availability with missing books retained','',
        'The secondary denominator includes every clean oracle path, including paths without fresh books. Every formula still requires measured liquidity to quote. Full daily, weekday and weekend summaries for both cohorts are retained in the packet.','',
        '| Asset / payout | Primary weekday availability | Primary weekend availability |','| --- | ---: | ---: |']
    for a in ('ETH','HYPE'):
        for m in (100,1000):
            r=new[a]['results']['trial'][str(m)]['conditional_recent']['all_clean'];lines.append(f'| {a} X{m} | {pct(r["weekday"]["pooled"]["availability"])} | {pct(r["weekend"]["pooled"]["availability"])} |')
    count=lambda audit:sum(x['decisions_independently_replayed'] for x in audit['assets'])
    lines += ['', '## Verification and remaining limits','',
        f'The active-tail audit refitted {sum(x["models_refit"] for x in ra["assets"])} earlier-only origin models and independently replayed {count(ra):,} decisions. The conditional-tail audit verified every calibration population, candidate budget and chosen level, then independently replayed {count(na):,} additional decisions. All origin/source/input hashes, accepted/refused/unresolved traces and daily/cohort metrics reconcile. Thirty-five tests passed across historical liquidity, trial liquidity, payout settlement, flat vetoes, overlay, active tails and conditional calibration, including native touch boundaries, future-outcome invariance, midnight maturity, asset isolation and tamper rejection.','',
        'X1000 now supplies actual positive-width quotes, but availability and sparse-tail evidence remain limitations. The target-versus-availability tradeoff is reported without relaxing the existing screen. HYPE weekday results must be read against both the 0.950% target and the prior overlay availability. Only two September weekend dates are available; weekday/weekend differences cannot establish a causal liquidity effect. These outcomes have informed repeated formula changes, so a future frozen evaluation on fresh data remains necessary. No model is promoted to the live engine.','',
        f'Active packet: `{active.resolve()}`. Conditional packet: `{conditional.resolve()}`. Prior overlay: `{previous.resolve()}`. Each packet retains a declaration, complete imported local source snapshot, per-origin models or calibration levels, complete decisions and independent audit.','',
        '```sh',
        'PYTHONPATH=scripts OPENBLAS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 OMP_NUM_THREADS=1 python3 -B -m unittest scripts.test_historical_liquidity scripts.test_trial_liquidity scripts.test_trial_payout scripts.test_flat_aware_payout scripts.test_flat_risk_overlay scripts.test_active_tail_payout scripts.test_conditional_tail_payout',
        'python3 -B scripts/research_active_tail.py --declare --parent .local/adaptive-corridor/20261029-flat-aware-payout-v1 --comparison .local/adaptive-corridor/20261029-flat-risk-overlay-v1 --output .local/adaptive-corridor/NEW-ACTIVE',
        'OPENBLAS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 OMP_NUM_THREADS=1 python3 -B scripts/research_active_tail.py --output .local/adaptive-corridor/NEW-ACTIVE',
        'OPENBLAS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 OMP_NUM_THREADS=1 python3 -B scripts/research_active_tail.py --audit --output .local/adaptive-corridor/NEW-ACTIVE',
        'python3 -B scripts/research_conditional_tail.py --declare --parent .local/adaptive-corridor/NEW-ACTIVE --output .local/adaptive-corridor/NEW-CONDITIONAL',
        'OPENBLAS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 OMP_NUM_THREADS=1 python3 -B scripts/research_conditional_tail.py --output .local/adaptive-corridor/NEW-CONDITIONAL',
        'OPENBLAS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 OMP_NUM_THREADS=1 python3 -B scripts/research_conditional_tail.py --audit --output .local/adaptive-corridor/NEW-CONDITIONAL',
        'python3 -B scripts/report_active_tail.py --previous .local/adaptive-corridor/20261029-flat-risk-overlay-v1 --active .local/adaptive-corridor/NEW-ACTIVE --conditional .local/adaptive-corridor/NEW-CONDITIONAL --output docs/ACTIVE_TAIL_PAYOUT_RESEARCH.md',
        '```','',f'Active research SHA-256: `{digest(active/"research.json")}`. Audit SHA-256: `{digest(active/"audit.json")}`.',
        f'Conditional research SHA-256: `{digest(conditional/"research.json")}`. Audit SHA-256: `{digest(conditional/"audit.json")}`.','']
    output.write_text('\n'.join(lines));return dict(output=str(output),active_decisions=count(ra),conditional_decisions=count(na))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--previous',type=Path,required=True);p.add_argument('--active',type=Path,required=True);p.add_argument('--conditional',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();print(json.dumps(render(a.previous,a.active,a.conditional,a.output)))
