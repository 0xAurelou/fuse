#!/usr/bin/env python3
"""Render the audited consecutive ETH/HYPE oracle and liquidity result."""
import argparse
import json
from pathlib import Path

from research_payout_risk import digest


def report(root):
    meta=json.loads((root/'research.json').read_text());audit=json.loads((root/'audit.json').read_text())
    plan=json.loads((root/'protocol.json').read_text());coverage=json.loads((root/'coverage.json').read_text())
    if not audit['passed'] or audit['research_sha256']!=digest(root/'research.json'):raise ValueError('Matching successful audit required')
    assets=tuple(meta['research_sha256']);results={}
    for a in assets:
        if digest(root/a/'research.json')!=meta['research_sha256'][a]:raise ValueError('Asset report binding differs')
        results[a]=json.loads((root/a/'research.json').read_text())
    raw=Path(plan['raw']);manifest=json.loads((raw/'download-manifest.json').read_text())
    if digest(raw/'download-manifest.json')!=meta['raw_manifest_sha256']:raise ValueError('Raw manifest binding differs')
    findings=[]
    for a,r in results.items():
        baseline=sum(d['calendar']['p0']['log_loss'] for d in r['daily'].values())/len(r['daily'])
        p=r['paired_primary'];lo,hi=p['bootstrap_interval']
        evidence='includes zero' if lo<=0<=hi else 'is above zero' if lo>0 else 'is below zero'
        findings.append(f"{a}: adding the fixed liquidity features improves mean daily prediction loss by {p['mean_improvement']/baseline:+.2%}; its descriptive day-bootstrap interval {evidence}.")
    lines=['# Consecutive ETH and HYPE oracle and liquidity test', '',
        'September 1–10, 2026 UTC provides ten consecutive dates of native Hyperliquid oracle updates and visible books. The study tests whether measured liquidity improves prediction of zero oracle movement over thirty seconds after accounting for oracle activity and UTC calendar. The evidence covers two weekend dates, September 5 and 6, and is historical development.', '',
        ' '.join(findings), '',
        '## Data and coverage', '',
        f"The authorized Tardis free trial supplied all {len(manifest['files']):,} requested ten-minute slices: {sum(f['bytes'] for f in manifest['files'])/1e6:.2f} MB compressed and {sum(f['decoded_bytes'] for f in manifest['files'])/1e9:.3f} GB decoded. The key remained local. No purchase, upgrade or billing change was made. These dates are earlier than the separate September 30–October 27 book archive; they supply the matched high-frequency oracle data needed for this immediate test.", '',
        '[Tardis raw Hyperliquid documentation](https://docs.tardis.dev/historical-data-details/hyperliquid) describes `activeAssetCtx` and native 20-level `l2Book`. The study uses actual `ctx.oraclePx`, with original receipt timestamps and disconnect markers. Mark prices, trades and candle prices never substitute for the oracle. [Trial terms](https://docs.tardis.dev/faq/billing-and-subscriptions) specify the first ten dates of the preceding UTC month.', '',
        '| Asset | Oracle messages | Native book messages | Grid paths | Clean oracle paths | With usable prior book | Match rate among clean |',
        '| --- | ---: | ---: | ---: | ---: | ---: | ---: |']
    for a in assets:
        q=[p for p in coverage if p['asset']==a];clean=sum(p['clean_oracle_paths'] for p in q);matched=sum(p['matched_paths'] for p in q)
        lines.append(f"| {a} | {sum(p['oracle_messages'] for p in q):,} | {sum(p['book_messages'] for p in q):,} | {sum(p['grid'] for p in q):,} | {clean:,} | {matched:,} | {matched/clean:.2%} |")
    lines+=['', 'Oracle cadence is approximately one update per second. Missing data is not a flat win: original eight-second oracle freshness and disconnect censorship apply to outcomes and history. Each entry uses the latest native book received strictly before entry, at most five seconds old by receipt and exchange timestamp, with at most two seconds of exchange-clock forward tolerance. Books at entry equality or later are excluded. Depth is visible top-five and top-twenty bid/ask USD notional, rather than whole-market or executable depth.', '',
        '| Asset | Median oracle gap across dates in ms | Largest oracle gap in seconds | Gaps over eight seconds | Oracle disconnect markers |',
        '| --- | --- | ---: | ---: | ---: |']
    for a in assets:
        q=[p for p in coverage if p['asset']==a]
        lines.append(f"| {a} | {min(p['oracle_gap_median_ms'] for p in q):g}–{max(p['oracle_gap_median_ms'] for p in q):g} | {max(p['oracle_gap_max_ms'] for p in q)/1000:.3f} | {sum(p['oracle_gaps_over_8s'] for p in q)} | {sum(p['disconnect_markers'] for p in q)} |")
    lines+=['', '## Chronological comparison', '',
        'Each asset starts with twenty matched first-of-month dates from January 2025 through August 2026. All ten trial dates are evaluated once. At each UTC daily origin, coefficients, normalization and depth terciles use only earlier labels whose expiry plus thirty seconds is strictly before the origin. Subsequent days add earlier trial data. Context resets daily. This preserves both weekend days for evaluation.', '',
        'Four fixed logistic models use the identical complete-case cohort: activity, activity plus calendar, activity plus liquidity, and activity plus calendar plus liquidity. Ridge is fixed at 0.003, training mass is equal per date and standardized features are clipped to ±5. No feature or model was selected from trial results. The primary score is the equal-day mean paired zero-motion log-loss improvement of calendar plus liquidity over calendar. Positive improvement favors liquidity. The interval resamples scored dates 2,000 times with a fixed seed and is descriptive.', '',
        '| Asset | Mean daily baseline loss | Mean daily loss with liquidity | Paired improvement | Relative improvement | Day bootstrap 95% interval | Improved dates |',
        '| --- | ---: | ---: | ---: | ---: | --- | ---: |']
    for a,r in results.items():
        p=r['paired_primary'];baseline=sum(d['calendar']['p0']['log_loss'] for d in r['daily'].values())/10;augmented=sum(d['calendar_liquidity']['p0']['log_loss'] for d in r['daily'].values())/10
        lo,hi=p['bootstrap_interval']
        lines.append(f"| {a} | {baseline:.6f} | {augmented:.6f} | {p['mean_improvement']:+.6f} | {p['mean_improvement']/baseline:+.2%} | [{lo:+.6f}, {hi:+.6f}] | {p['improved_dates']} / 10 |")
    lines+=['', '| Asset | Model | Pooled zero-motion log loss | Pooled Brier score | Observed zero-motion rate | Mean forecast |',
        '| --- | --- | ---: | ---: | ---: | ---: |']
    for a,r in results.items():
        for name,m in r['pooled'].items():
            p=m['p0'];lines.append(f"| {a} | {name} | {p['log_loss']:.6f} | {p['brier']:.6f} | {p['observed']:.4%} | {p['predicted']:.4%} |")
    lines+=['', 'The gains are small. HYPE has a positive descriptive interval for the primary log-loss improvement, while its pooled Brier score is slightly worse with liquidity. ETH’s interval includes zero. These results support further testing of the asset-specific fits rather than adopting a common weekend adjustment.']
    lines+=['', '## Weekend and depth diagnostics', '',
        'Zero-motion rates below pool matched paths. Liquidity averages give each included date equal weight. Low, middle and high depth groups use only earlier-training terciles of minimum top-five side notional. These are associations and do not identify liquidity as the cause of corridor wins.', '',
        '| Asset | Group | Dates | Matched paths | Zero-motion paths | Zero-motion rate | Calendar forecast | With liquidity forecast | Equal-day spread in bps | Equal-day minimum top-five side in USD |',
        '| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |']
    for a,r in results.items():
        for name in ('weekday','weekend','low','middle','high'):
            s=r['strata'][name];m=s['calendar'];b=s['liquidity_summary']
            lines.append(f"| {a} | {name} | {len(m['dates'])} | {m['n']:,} | {m['p0']['wins']:,} | {m['p0']['observed']:.4%} | {m['p0']['predicted']:.4%} | {s['calendar_liquidity']['p0']['predicted']:.4%} | {b['equal_day_spread_bps']:.4f} | {b['equal_day_minimum_top5_side_usd']:,.0f} |")
    lines+=['', 'Both assets have higher weekend zero-motion rates in these consecutive matched paths, and both also have zero-motion weekday paths. Weekend spreads are tighter and minimum visible top-five depth is only modestly lower. The low-depth strata do not have the highest flat-path rates. This combination does not support a universal thin-weekend-liquidity explanation.']
    lines+=['', 'Only two weekend dates are present. Adjacent dates can share a regime, and earlier monthly oracle outcomes, including September 1, were already inspected in this research program. Chronological fitting does not make the whole research process an untouched holdout. The specified feature additions can show predictive association; they cannot establish that weekend liquidity causes wins or that liquidity has no effect.', '',
        'Zero movement is the survival floor for any positive-width corridor under the original oracle settlement rule. The one-ppm floor metrics are retained as a secondary outcome in the packet. This experiment does not fit payout widths, test quoted 100× or 1,000× returns, or validate a live pricing change. The ongoing fresh collector and live formulas remain unchanged.', '',
        '## Artifacts and verification', '',
        f"Research packet: `{root.resolve()}`. Raw history: `{raw.resolve()}`. The packet retains its protocol and source snapshot, all 57,600 grid rows including exclusions, date-level coverage, eighty fitted origin models, paired forecasts, scores and a replay audit. Raw hashes and exact requests are bound to the frozen download declaration.", '',
        f"The audit passed: {audit['grid_rows_reconstructed']:,} grid rows reconstructed from {audit['raw_payloads_verified']:,} raw slices; {sum(r['models_refit'] for r in audit['assets'])} models refitted from earlier matured labels; {sum(r['predictions_manually_replayed'] for r in audit['assets']):,} predictions manually replayed. Paired metrics, training-only depth thresholds and all retained coverage were reconciled. Nine focused downloader/reader/model tests cover access bounds, gzip integrity, strict entry joins, stale/disconnected exclusions, future-price invariance and midnight label maturity.", '',
        'The initial implementation declaration remains in the sibling `20261029-consecutive-trial-liquidity-v1` packet. Its validator stopped at the second daily origin because the last two previous-day paths had not matured. Version 2 filters those candidates before validation and explicitly binds the earlier declaration; it preserves the original model and feature choices.', '',
        '```sh',
        'PYTHONPATH=scripts python3 -B -m unittest scripts.test_tardis_liquidity_trial scripts.test_trial_liquidity',
        f"python3 -B scripts/research_trial_liquidity.py --declare --parent {plan['parent']} --monthly {plan['monthly']} --raw {raw.resolve()} --output .local/adaptive-corridor/NEW-TRIAL-REPLAY",
        'OPENBLAS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 python3 -B scripts/research_trial_liquidity.py --output .local/adaptive-corridor/NEW-TRIAL-REPLAY',
        'OPENBLAS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 python3 -B scripts/research_trial_liquidity.py --audit --output .local/adaptive-corridor/NEW-TRIAL-REPLAY',
        '```', '',
        f"Research SHA-256: `{digest(root/'research.json')}`. Audit SHA-256: `{digest(root/'audit.json')}`.", '']
    return '\n'.join(lines)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--research',type=Path,required=True);parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    args.output.write_text(report(args.research));print(args.output)
