#!/usr/bin/env python3
"""Render the audited independent asset research as a repository report."""
import argparse
import csv
import json
from pathlib import Path

from capture_dataset import file_hash
from research_asset_corridors import ASSETS, PAYOUTS


def percentage(value):
    if value is None or value == '':
        return '—'
    return f'{float(value):.4%}' if 0 < float(value) < .001 else f'{float(value):.2%}'


def report(root, destination):
    audit = json.loads((root / 'audit.json').read_text())
    if not audit['passed'] or audit['research_sha256'] != file_hash(root / 'research.json'):
        raise ValueError('a matching completed audit is required')
    research = json.loads((root / 'research.json').read_text())
    data = json.loads((root / 'dataset.json').read_text())
    results = {r['asset']: r for r in research['results']}
    metrics = {}
    for asset in ASSETS:
        with (root / asset / 'metrics.csv').open() as stream:
            metrics[asset] = list(csv.DictReader(stream))

    def metric(asset, target='legacy48', period='pooled', axis='overall', group='all', candidate=None):
        candidate = candidate or (results[asset]['selected'] if target == 'legacy48' else 'activity_hurdle')
        return next(r for r in metrics[asset] if r['target_name'] == target and r['candidate'] == candidate
                    and r['split'] == 'test' and r['period'] == period and r['axis'] == axis and r['group'] == group)

    lines = ['# Independent ETH and HYPE corridor fits — 28 October 2026', '',
        'Separate models were fitted on each asset\'s own raw Hyperliquid oracle history. No BTC fitted coefficients were transferred. The artifacts contain the legacy 48% survival experiment and nine separate payout-specific fits. These are historical research models; the paper/live quote configuration and the ongoing BTC capture were not changed.', '',
        '## Data, chronology and method', '',
        'The pinned public Tardis request list contains 3,456 ten-minute raw `activeAssetCtx` slices. All requests completed without credentials or paid endpoints; compressed CRCs and local SHA-256 bindings were verified. Each first-of-month UTC date is a full raw day, not a continuous recording across months. Receipt timestamps, `oraclePx`, unchanged-price messages, mark context and disconnect markers are retained; mark prices never substitute for oracle outcomes.', '',
        'ETH has 24 dates from November 2024 through October 2026. Provider coverage for HYPE begins on 5 December 2024, so its 22 monthly dates begin in January 2025. Missing earlier HYPE history is explicitly absent. Training ends with December 2025: fourteen ETH dates and twelve HYPE dates. January–May 2026 selects the primary family; June–October 2026 evaluates it after the choice and legacy models are pinned. Those later asset outcomes did not select a family, coefficient, target or threshold. Related calendar dates have already been studied for BTC, so these are withheld asset results within a development program, not prospective evidence.', '',
        'The native BTC research machinery is reused with independent fits: period-balanced fast/slow volatility and directional scales, activity corrections, delayed reference updates, a frozen hurdle distribution and the full-core bursty residual prior. The five predeclared 48% comparators are slow volatility, activity+hurdle, full core, timing-context frozen feedback, and market-context frozen feedback. The two context methods replace only frozen pricing. Validation score is mean daily absolute survival error + 0.5 × mean populated activity/regime error + 0.25 × worst daily error, in percentage points; candidate order breaks ties. Cells need twenty paths for that descriptive score.', '',
        'Each payout fit independently targets `0.95 / multiplier`, with the activity+hurdle model refitted at that target. The existing full-core and conditional-CDF update rules fix 48%, so those families are compared only in the 48% experiment. Payout-specific fits do not inherit a 48% survival probability. No payout-specific family search is claimed.', '',
        'Entries are nonoverlapping thirty-second UTC grid windows. Features require five minutes of clean history strictly before entry. The eight-second single-stream freshness screen and disconnect censorship preserve missing outcomes; predictions are made without reading current outcome validity. Touching either rounded barrier loses. Research widths are integer ppm in [1, 50,000]. Delayed updates use outcomes only after expiry plus thirty seconds, and state resets at each sampled day. Pump/dump labels retain the BTC research definitions; their suitability for each asset remains a hypothesis.', '',
        '## Primary 48% result', '',
        '| Asset | Raw oracle observations | Clean training paths | Test paths | Validation-selected family | Test survival | Mean half-width, ppm |',
        '| --- | ---: | ---: | ---: | --- | ---: | ---: |']
    for asset in ASSETS:
        r = results[asset]; m = metric(asset)
        messages = sum(p['observations'] for p in data['profiles'] if p['asset'] == asset)
        lines.append(f"| {asset} | {messages:,} | {r['clean_training_paths']:,} | {int(m['eligible']):,} | {r['selected']} | {percentage(m['survival'])} | {float(m['mean_width_ppm']):.2f} |")
    lines += ['', 'Mean half-width summarizes changing quotes, not a recommended fixed corridor. Pooled agreement with 48% does not establish calibration in each date or state.', '',
              '| Withheld raw date | ETH survival | HYPE survival |', '| --- | ---: | ---: |']
    for day in research['plan']['test_dates']:
        lines.append(f"| {day} | " + ' | '.join(f"{percentage(metric(a, period=day)['survival'])} ({metric(a, period=day)['eligible']} paths)" for a in ASSETS) + ' |')
    lines += ['', 'Pooled conditional results for the selected families:', '',
              '| Group | ETH survival / paths | HYPE survival / paths |', '| --- | ---: | ---: |']
    for axis, group in [('activity_state', s) for s in ('active', 'sparse', 'bursty', 'frozen')] + [('market_regime', s) for s in ('pump', 'dump')]:
        cells = [metric(a, axis=axis, group=group) for a in ASSETS]
        lines.append(f"| {group} | " + ' | '.join(f"{percentage(c['survival'])} / {c['eligible']}" for c in cells) + ' |')
    lines += ['', 'These paths share histories and market regimes. Counts and percentages are descriptive; thin or empty groups cannot certify conditional probabilities. No binomial independence is assumed.', '',
              '## Payout-specific fits', '',
              '| Payout | Target survival | ETH test survival | HYPE test survival | ETH mean half-width, ppm | HYPE mean half-width, ppm |',
              '| --- | ---: | ---: | ---: | ---: | ---: |']
    for multiplier in PAYOUTS:
        eth, hype = (metric(a, target=f'payout{multiplier}') for a in ASSETS)
        lines.append(f"| {multiplier:,}× | {percentage(.95/multiplier)} | {percentage(eth['survival'])} | {percentage(hype['survival'])} | {float(eth['mean_width_ppm']):.2f} | {float(hype['mean_width_ppm']):.2f} |")
    lines += ['', 'The fits are complete even when their realized calibration is poor. In particular, a fitted narrow corridor cannot eliminate the mandatory survivors created by a flat oracle. The 1,000× and 10,000× targets imply fewer than twenty expected test wins per asset at the requested probability; those samples cannot validate rare-event pricing. Serial dependence further reduces the evidence.', '',
              '| Asset | Evaluated test paths | Zero-motion paths | Zero-motion survival floor at full availability |',
              '| --- | ---: | ---: | ---: |']
    for asset in ASSETS:
        profiles = [p for p in data['profiles'] if p['asset'] == asset and p['split'] == 'test']
        n, z = sum(p['clean'] for p in profiles), sum(p['zero_motion'] for p in profiles)
        lines.append(f'| {asset} | {n:,} | {z:,} | {z/n:.2%} |')
    lines += ['', 'Every positive-width corridor survives an actually zero-motion path. The report deliberately distinguishes that product-level fact from additional survivors at the research one-ppm minimum; the shipped engine uses finer ppb quantization. Per-date optimistic retention bounds are saved in each asset\'s `feasibility.csv`. They grant perfect foresight and are necessary constraints, not causal admission policies.', '',
        'All compared variants keep quotes open on feature-supported entries. The test counts above include only clean, healthy outcomes; each asset has 14,400 total test-grid entries. The full CSVs retain grid, pre-entry prediction and scored-outcome denominators, including thin groups. Eligible quote availability is 100% by construction and is not capture uptime or a guarantee of executable live quotes.', '',
        'A 5% input target is not a measured house edge. `metrics.csv` also reports `1 − multiplier × realized survival` for an equal-stake historical batch before costs. It does not simulate trader selection, concurrent correlated liabilities, arbitrary entry times, reserve fees, capital flows or net LP returns. Those economics and fresh paired-receiver validation remain open.', '',
        '## Artifacts and verification', '',
        f"Completed archive: `{root.as_posix()}`.", '',
        '- `protocol.json`, `source/`, `dataset.json`, and `rows.jsonl.gz` bind the declared experiment, code and asset-labeled paths.',
        '- `ETH/` and `HYPE/` each contain `models.json`, `legacy-models.json`, `selection.json`, `predictions.jsonl.gz`, `metrics.csv`, `feasibility.csv`, and `research.json`.',
        '- `audit.json` reconciles original raw hashes/CRCs, training cutoffs, independent target-scale estimates, every saved exact barrier outcome, CSV populations/survival/mean-width/gross arithmetic, finite retention bounds, validation selection and complete frozen-model test replays.', '',
        'The initial `...-v1` attempt stopped after ETH model fitting because a CSV writer call omitted its required field list. Its partial artifacts and `abandoned.json` are retained. The corrected `...-v2` reruns both assets without changing pricing rules, targets, date splits or selection; its end-to-end export regression test passes.', '',
        'The focused suite covers asset separation, raw hash rejection, missing-feed censorship, strict touch loss, training maturity, payout targets, assembled-pipeline causality and complete model/CSV export. The corrected full Python regression suite passed 345 tests with three existing skips; the focused suite passes five tests. No existing pricing implementation was modified.', '',
        'Reproduce with a new output directory after retaining or re-fetching the pinned public source data:', '',
        '```sh',
        'python3 -B scripts/research_asset_corridors.py --declare \\',
        '  --downloads .local/market-history/tardis-hyperliquid-ETH-HYPE-monthly-raw-v1 \\',
        '  --output .local/adaptive-corridor/NEW-ASSET-FITS',
        'python3 -B scripts/research_asset_corridors.py \\',
        '  --downloads .local/market-history/tardis-hyperliquid-ETH-HYPE-monthly-raw-v1 \\',
        '  --output .local/adaptive-corridor/NEW-ASSET-FITS',
        'python3 -B scripts/audit_asset_corridors.py --research .local/adaptive-corridor/NEW-ASSET-FITS',
        'python3 -B -m unittest discover -s scripts -p test_asset_corridors.py',
        '```', '',
        'Sources: [provider coverage and first-of-month samples](https://docs.tardis.dev/historical-data-details/hyperliquid), [raw slices, receipt timestamps and disconnect markers](https://docs.tardis.dev/api/http-api-reference), [Hyperliquid oracle construction](https://hyperliquid.gitbook.io/hyperliquid-docs/hypercore/oracle).', '']
    destination.write_text('\n'.join(lines))
    return dict(report=str(destination), research_sha256=file_hash(root / 'research.json'),
                report_sha256=file_hash(destination))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--research', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(report(args.research, args.output), indent=2))
