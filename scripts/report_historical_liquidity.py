#!/usr/bin/env python3
"""Summarize the audited, matched historical book/oracle experiment."""
import argparse
from datetime import date
import json
from pathlib import Path

from historical_liquidity import VARIANTS
from research_payout_risk import digest


def pct(x,digits=2):return '—' if x is None else f'{x:.{digits}%}'


def report(root,output):
    research=json.loads((root/'research.json').read_text());audit=json.loads((root/'audit.json').read_text())
    if not audit['passed'] or audit['research_sha256']!=digest(root/'research.json'):raise ValueError('matching completed audit required')
    verification=json.loads((root/'verification.json').read_text())
    if verification['suite_exit_code']!=0 or verification['tests_log_sha256']!=digest(root/'tests.log') or verification['audit_sha256']!=digest(root/'audit.json'):
        raise ValueError('verification bindings differ')
    assets={a:json.loads((root/a/'research.json').read_text()) for a in ('ETH','HYPE')}
    coverage=json.loads((root/'coverage.json').read_text())
    for a in assets:
        if digest(root/a/'research.json')!=research['research_sha256'][a]:raise ValueError('asset report differs')
    statements=[]
    for asset,p in assets.items():
        effect=p['paired_primary'];lo,hi=effect['bootstrap_interval']
        verdict='improves the declared paired prediction score' if lo>0 else 'worsens the declared paired prediction score' if hi<0 else 'has an uncertain paired prediction effect'
        statements.append(f'{asset}: adding the fixed liquidity features {verdict} in these historical development samples.')
    lines=['# Historical ETH/HYPE liquidity-effect test — 29 October 2026','',
        'Historical spread and visible-depth data is available and was downloaded and tested immediately. Fresh consecutive recording can continue alongside it; a historical first pass does not require waiting for the fresh horizon.','',
        *statements,'',
        '## Sources and sample','',
        'The study downloads every native `l2Book` slice for ETH and HYPE on the first UTC day of each month from January 2025 through October 2026. These 22 full sample days per asset match the existing raw-oracle archive. The 3,168 ten-minute gzip payloads are retained with request URLs, hashes, metadata and an immutable source snapshot. No API key, paid subscription or AWS billing credentials were used.','',
        '[Tardis Hyperliquid documentation](https://docs.tardis.dev/historical-data-details/hyperliquid) confirms raw native 20-level book history, asset coverage, BBO history and the switch to a separate fast five-level channel. The raw 20-level channel is used throughout. Normalized `book_snapshot_25` must not be interpreted as 25 actual levels: the provider documents that its newer normalized snapshots are built from the five-level fast stream.','',
        'The [Tardis raw API](https://docs.tardis.dev/api/http-api-reference) makes first-of-month histories available without authentication. Continuous dates beyond those free samples require another access route. [Hyperliquid also publishes historical L2 snapshots](https://hyperliquid.gitbook.io/hyperliquid-docs/historical-data) in its requester-pays S3 archive, with variable completeness and transfer charges. That paid route was not activated here.','',
        '| Asset | Matched source dates | Clean oracle paths | Paths with usable prior book | Match rate | Evaluated dates | Evaluated matched paths | Weekend / weekday evaluation dates |',
        '| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |']
    for asset,p in assets.items():
        c=[r for r in coverage if r['asset']==asset];n=sum(r['clean_oracle_paths'] for r in c);k=sum(r['matched_paths'] for r in c)
        weekends=sum(date.fromisoformat(d).weekday()>=5 for d in p['evaluated_dates'])
        lines.append(f"| {asset} | {len(c)} | {n:,} | {k:,} | {pct(k/n)} | {len(p['evaluated_dates'])} | {p['unique_matched_evaluated_paths']:,} | {weekends} / {len(p['evaluated_dates'])-weekends} |")
    lines += ['',
        'Each thirty-second entry joins the latest book received strictly before entry. Both receipt age and exchange timestamp must meet the frozen five-second freshness rule, with at most two seconds of forward exchange-clock tolerance. Disconnect markers clear book state conservatively before the next recorded message. Initial missing history, stale books, fewer than five visible levels and invalid books remain explicitly unavailable. No gap is interpolated and no book after entry is used. Raw order and entry-equality boundaries are tested.','',
        'Depth features are USD notional in the top five and twenty visible bid/ask levels, plus top-five imbalance. Spread is derived from the native book. The complete-case cohort is identical for all four models; book availability is not filled with zero. Full 1/5-bps band coverage is retained separately, and incomplete band depth is never presented as complete. These quantities measure one venue’s visible liquidity. They are not total market depth or execution costs.','',
        '## Paired chronological prediction','',
        'Each asset warms up on January–June 2025. July 2025–October 2026 are scored once per matched entry, with coefficients and standardization refitted only on earlier matured matched paths. Every fixed model uses ridge 0.003, equal training mass per date and standardized features clipped to ±5. The four comparisons are oracle activity, activity plus calendar, activity plus liquidity, and activity plus calendar plus liquidity. No model or feature combination is selected from the results.','',
        'The primary label is zero oracle movement over the next thirty seconds, because that was the main driver of the earlier high-payout wins. The one-ppm minimum-width label is secondary. This is an experiment about the flat-path mechanism; it does not fit payout widths, claim a calibrated 100×/1,000× quote or establish net LP returns.','',
        'The primary score is the equal-date average paired log-loss improvement when adding liquidity to the calendar/activity baseline. Positive improvement favors the added liquidity features. The descriptive interval resamples whole scored days 2,000 times with a frozen seed. It preserves within-day dependence but does not establish causal effects or independence across monthly market episodes.','',
        '| Asset | Mean daily baseline log loss | Mean daily with liquidity | Paired improvement | Relative improvement | Day-block 95% interval | Improved dates |',
        '| --- | ---: | ---: | ---: | ---: | --- | ---: |']
    for asset,p in assets.items():
        e=p['paired_primary'];daily=p['daily'];base=sum(r['calendar']['p0']['log_loss'] for r in daily.values())/len(daily)
        aug=sum(r['calendar_liquidity']['p0']['log_loss'] for r in daily.values())/len(daily)
        lo,hi=e['bootstrap_interval']
        lines.append(f"| {asset} | {base:.6f} | {aug:.6f} | {e['mean_improvement']:+.6f} | {pct(e['mean_improvement']/base)} | [{lo:+.6f}, {hi:+.6f}] | {e['improved_dates']} / {e['dates']} |")
    lines += ['',
        '| Asset | Fixed model | Pooled log loss | Pooled Brier score | Observed zero-motion rate | Mean forecast |',
        '| --- | --- | ---: | ---: | ---: | ---: |']
    for asset,p in assets.items():
        for variant in VARIANTS:
            r=p['pooled'][variant]['p0']
            lines.append(f"| {asset} | {variant} | {r['log_loss']:.6f} | {r['brier']:.6f} | {pct(r['observed'],4)} | {pct(r['predicted'],4)} |")
    lines += ['',
        '## Depth and calendar diagnostics','',
        'Low/middle/high depth groups use prior-training-only terciles of the minimum top-five side notional, separately for each asset and scoring origin. They are descriptive states, not recommended trading thresholds. The following observed rates can reflect volatility, oracle activity, market regime, timestamp and selection effects. Baseline versus augmented forecasts are included to show why a raw thin/deep rate difference alone is insufficient evidence.','',
        '| Asset | Group | Matched paths | Zero-motion rate | Calendar/activity forecast | With-liquidity forecast | Mean spread, bps | Mean minimum top-five side, USD |',
        '| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |']
    for asset,p in assets.items():
        for name in ('low','middle','high','weekday','weekend'):
            s=p['strata'][name];b=s['calendar'];a=s['calendar_liquidity'];l=s.get('liquidity_summary')
            lines.append(f"| {asset} | {name} | {b['n']:,} | {pct(b['p0']['observed'],4)} | {pct(b['p0']['predicted'],4)} | {pct(a['p0']['predicted'],4)} | {l['mean_spread_bps']:.4f} | {l['mean_minimum_top5_side_usd']:,.0f} |" if l else f'| {asset} | {name} | 0 | — | — | — | — | — |')
    lines += ['',
        'In these fixed cohorts, the low-depth group has a lower raw zero-motion rate than the high-depth group in both assets. Weekend spreads are wider and visible top-five depth is lower on average for both assets, while the weekend zero-motion rate rises for ETH and falls for HYPE. These descriptive patterns do not support a single thin-weekend-liquidity rule across both assets. They also do not prove that liquidity has no effect: the specified linear/logistic feature additions, visible depth bound, sample dates and oracle process limit the test.']
    lines += ['',
        'These are sampled first-of-month days, not consecutive weeks. Their oracle outcomes overlap an already inspected development research program. The coefficient fits are chronological, but this is not a pristine holdout of the entire research process. Only four evaluated weekend dates per asset are available. Neither the calendar comparison nor the depth strata identify liquidity as the cause of a weekend win cluster. The fresh consecutive collection remains useful for evaluating transfer and within-week variation.','',
        '## Artifacts and verification','',
        f"Research packet: `{root.as_posix()}`. Raw books: `{research['protocol']['books']}`. Original oracle fits and the fresh ETH/HYPE recorder were not changed.",'',
        '`protocol.json` freezes sources and the test before joining or fitting. `joined.jsonl.gz` retains all fixed-grid book matches/reasons and book provenance. `coverage.json` retains date/asset attrition. Each asset retains all origin models, predictions, paired daily scores, depth/calendar strata and research metadata.','',
        f"The audit reconstructs all {audit['joined_grid_rows']:,} grid joins from {audit['book_payloads_verified']:,} hashed raw book payloads, refits every saved model from strictly earlier labels, replays {sum(a['trace_rows'] for a in audit['assets']):,} forecasts and reconciles paired metrics and day-block intervals. Six focused tests cover timestamp equality, freshness, feed identity, disconnect censorship, future-label exclusion, paired model populations and complete fit/export/audit coverage. The full Python suite ran {verification['full_suite_tests']} tests, with {verification['skipped']} skips and all others passing.",'',
        '```sh',
        'python3 -B scripts/fetch_historical_liquidity.py --directory .local/market-history/NEW-BOOKS --metadata .local/market-history/tardis-hyperliquid-ETH-HYPE-monthly-raw-v1/exchange-metadata.json',
        'python3 -B scripts/fetch_historical_liquidity.py --directory .local/market-history/NEW-BOOKS --fetch',
        'python3 -B scripts/research_historical_liquidity.py --declare --parent .local/adaptive-corridor/20261028-ETH-HYPE-raw-fits-v2 --books .local/market-history/NEW-BOOKS --output .local/adaptive-corridor/NEW-LIQUIDITY',
        'OPENBLAS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 python3 -B scripts/research_historical_liquidity.py --output .local/adaptive-corridor/NEW-LIQUIDITY',
        'OPENBLAS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 python3 -B scripts/audit_historical_liquidity.py --research .local/adaptive-corridor/NEW-LIQUIDITY',
        'python3 -B -m unittest discover -s scripts -p test_historical_liquidity.py',
        '```','']
    output.write_text('\n'.join(lines));return dict(path=str(output),sha256=digest(output))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--research',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();print(json.dumps(report(args.research,args.output),indent=2))
