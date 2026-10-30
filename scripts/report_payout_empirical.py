#!/usr/bin/env python3
"""Summarize the audited calibrated-risk / empirical-tail iteration."""
import argparse
import json
from pathlib import Path

from research_payout_risk import digest


def pct(x,digits=2):return '—' if x is None else f'{x:.{digits}%}'


def report(root,screen_root,output):
    audit=json.loads((root/'audit.json').read_text());result=json.loads((root/'research.json').read_text())
    if not audit['passed'] or audit['research_sha256']!=digest(root/'research.json'):raise ValueError('matching completed audit required')
    screen=json.loads((screen_root/'screen.json').read_text());screen_protocol=screen['protocol']
    if screen_protocol['study_sha256']!=digest(root/'research.json') or screen['later_results_used']:
        raise ValueError('screen study binding or evidence boundary differs')
    if digest(screen_root/'screen-source.py')!=screen_protocol['source_sha256']:
        raise ValueError('screen source differs')
    checks=json.loads((root/'verification.json').read_text())
    if checks['suite_exit_code']!=0 or digest(root/'tests.log')!=checks['tests_log_sha256']:
        raise ValueError('verification evidence differs')
    assets={r['asset']:r for r in result['assets']}
    def cell(asset,multiplier,variant):return next(r for r in assets[asset]['primary_test'] if r['multiplier']==multiplier and r['variant']==variant)
    lines=['# Calibrated risk and empirical payout tails — 29 October 2026','',
        'This iteration increases the availability of one fixed 1,000× risk-filter comparator, but does not establish calibrated high-payout pricing. The empirical-width candidates do not win earlier selection. The scalar ranking can prefer broad availability despite economically unacceptable survival, so an explicit validation-only eligibility layer now rejects every candidate rather than accepting the least-bad diagnostic. No model, gate, payout, horizon or capture is promoted or changed live.','',
        '## Changes and evidence boundaries','',
        'The study reuses the same ETH/HYPE raw dataset and the preceding frozen risk family/ridge. No new data is downloaded. Each calibration prediction is made by a model fitted on the first 6/9/12 permitted training dates and scored on the next 3/3/2 dates, wherever available. Coefficients exclude their own and later scoring dates and labels must mature before the training cutoff. These references remain development data: the template family/ridge came from the preceding experiment, whose January–May 2026 selection dates were already inspected. This is not an independent validation of the full model-discovery process.','',
        'Six fixed score bins calibrate zero-motion and one-ppm-floor probabilities separately. Supported bins need at least 200 references across three dates. They receive equal date weights, shrink toward the mean out-of-fold forecast with prior mass 32 or 128, and add half an event. Weighted monotone pooling joins supported bins whose estimates cross. Unsupported bins retain the raw risk forecast; no empty bin is interpreted as zero risk. The final minimum-width probability is constrained to be at least the zero-motion probability.','',
        '| Asset | Chronological calibration references | Calibration dates |','| --- | ---: | ---: |']
    for asset in ('ETH','HYPE'):
        a=assets[asset];lines.append(f"| {asset} | {a['oof_rows']:,} | {len(a['oof_periods'])} |")
    lines += ['',
        'The new movement model uses exact, date-weighted empirical CDFs of required positive width divided by either slow volatility or a 50/50 fast/slow blend. Activity-state and idle/change-count groups shrink toward the global positive CDF with 200 parent references. A local group needs 200 positive paths across three dates; otherwise it uses the parent. All positive training paths are retained. The global count-times-requested-tail support screen remains twenty, as in the previous experiment; neither data subsampling nor a relaxed screen creates apparent availability.','',
        'Each asset/payout compares 57 declared policies on January–May 2026: nine controls plus 48 combinations of calibrated risk prior, movement grouping, volatility anchor, requested quantile factor and risk-budget fraction. Only the selected policy and the nine fixed controls are replayed on June–October. The empirical policies are rejected in earlier selection rather than searched again on the later outcomes. Models, out-of-fold predictions and choice hashes stay fixed throughout diagnostics.','',
        'The controls include original-width idle/change-count rules, the preceding risk gate, two calibrated risk gates, and the preceding conditional-price comparator. The new CDF policies choose positive quantile `(level_factor × 0.95/M − p_min)/(1 − p_min)`. The requested-quantile factors are 0.5/0.75/1 and the risk-budget fractions are 0.5/1. All entry decisions use only pre-entry features. Current validity and realized movement are labels used after that decision.','',
        '## Fixed calibration comparison','',
        'The following rows keep the original payout widths and the same gate rule: refuse when predicted minimum-width survival exceeds `0.95/M`. They change only the probability calibration, using the predeclared prior-32 comparator. These favorable later rows do not select or promote that comparator.','',
        '| Asset | Payout | Previous quotes kept | Calibrated quotes kept | Calibrated win rate | Wins / kept quotes | Target-expected wins |',
        '| --- | ---: | ---: | ---: | ---: | ---: | ---: |']
    for asset in ('ETH','HYPE'):
        for multiplier in (100,1000):
            a,b=cell(asset,multiplier,'v1_parent_gate100'),cell(asset,multiplier,'calibrated32_parent')
            lines.append(f"| {asset} | {multiplier:,}× | {pct(a['availability'])} | {pct(b['availability'])} | {pct(b['survival'],4)} | {b['wins']} / {b['offered']:,} | {b['target_expected_wins']:.2f} |")
    lines += ['',
        'The 1,000× target remains 0.095%. ETH now retains about 3.8 times as many quotes, and HYPE about 2.9 times as many, under this fixed comparison. However, ETH has zero retained wins and HYPE only two. At target probability, the retained sample would produce only about two/five expected wins. This is inadequate rare-event evidence, not a validated house edge. The worst-day retained fractions are lower than the pooled averages.','',
        'The 100× target remains 0.95%. Calibrating the risk gate barely changes 100× pricing: ETH is still conservative with many refusals; HYPE still exceeds both its target and the 1% zero-cost break-even win rate. The new probability map alone does not repair the moving-path price.','',
        '## Earlier-selected policies','',
        'The declared score charges pooled/daily relative survival errors, lost mean availability, a large penalty below 85% worst-day availability, empty quoted days and deterioration in full-reference quantile loss. Full-reference loss includes refused shadow paths. Nevertheless, this scalar objective does not enforce economic feasibility. The selected rules are research diagnostics only:','',
        '| Asset | Payout | Earlier-selected policy | Later quotes kept | Later win rate | Target |','| --- | ---: | --- | ---: | ---: | ---: |']
    for asset in ('ETH','HYPE'):
        for multiplier in (100,1000):
            a=cell(asset,multiplier,'selected_policy');p=assets[asset]['selected'][str(multiplier)]
            lines.append(f"| {asset} | {multiplier:,}× | {p['name']} | {pct(a['availability'])} | {pct(a['survival'],4)} | {pct(a['target'],3)} |")
    lines += ['',
        'ETH 100× and both HYPE selected rules still pay winners too frequently. ETH 1,000× has sparse retained evidence and low availability. No selected rule is accepted. In particular, a lowest-score idle rule must not replace a failed profitability check. Empirical widths do not beat the controls under the frozen earlier objective; their complete candidate scores and models are retained.','',
        '## What this changes','',
        'Out-of-fold calibration corrects part of the old classifier\'s overly high estimates in some earlier low-score bins. That can preserve more potentially priceable high-payout entries. It is a useful improvement in the risk-filter frontier, with substantial uncertainty about transfer and rare-event frequencies.','',
        'The added `screen_payout_candidates.py` separates research eligibility from scalar ranking. On earlier validation only, a candidate must have nonempty quotes on every date, at least 85% availability in every date, pooled survival within 75–125% of its target, nonnegative zero-cost gross arithmetic, and at least twenty target-expected wins. These remain necessary descriptive research references, not production thresholds or statistical confidence. Among qualifying candidates the layer prefers availability, then target closeness; when none qualifies it returns no accepted candidate and preserves the scalar winner only as a diagnostic. Later outcomes never choose these screens or candidates.','',
        'The frozen eligibility analysis returns zero qualifying candidates for all four asset/payout combinations. In particular, all 13,810 eligible validation quotes would imply only about 13.12 expected wins at the 1,000× target; no policy can reach the twenty-expected-win reference in that cohort. This is an evidence limitation, not proof that no future 1,000× policy can work. More independently observed low-risk paths are needed; repeating or pooling fitted calibration references cannot manufacture fresh evidence.','',
        'Dates overlap the existing research program and all results here are historical development diagnostics. Thirty-second entries share longer lookbacks and market episodes. Counts are not independent trials. Zero oracle movement imposes a floor for every valid positive corridor, while the extra one-ppm floor is specific to this research bound. No order-book liquidity, trader selection, stake-weighted joint exposure, fees, reserves or net LP economics are modeled.','',
        '## Artifacts and verification','',
        f"Archive: `{root.as_posix()}`. Eligibility packet: `{screen_root.as_posix()}`. The source dataset and preceding risk packet remain unchanged.",'',
        '- Each asset retains `models.json`, `oof.jsonl.gz`, `selection.json`, `predictions.jsonl.gz`, `metrics.csv` and `research.json`.',
        '- `models.json` contains the preceding template, strictly earlier coefficient fits, two probability maps, complete positive CDFs and all training counts/date weights.',
        '- The independent audit checks source bindings, OOF population/cutoffs and labels, calibration posterior/monotonic pooling, every positive CDF training point and date weight, complete policy selection, saved entry decisions, barrier outcomes and metric reconciliation.','',
        f"The audit replays {sum(r['trace_rows'] for r in audit['assets']):,} saved diagnostic decisions. Nine focused model tests and five eligibility tests pass, including complete fit/export/audit coverage and explicit no-fallback/no-later-outcomes checks. The final full Python suite ran {checks['full_suite_tests']} tests: {checks['skipped']} existing skips and all others passed. `tests.log` and `verification.json` retain that evidence.",'',
        'Reproduce in a new output directory:','',
        '```sh',
        'python3 -B scripts/research_payout_empirical.py --declare \\',
        '  --parent .local/adaptive-corridor/20261028-ETH-HYPE-raw-fits-v2 \\',
        '  --preceding .local/adaptive-corridor/20261029-payout-flat-risk-v1 \\',
        '  --output .local/adaptive-corridor/NEW-PAYOUT-EMPIRICAL',
        'OPENBLAS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 python3 -B scripts/research_payout_empirical.py \\',
        '  --parent .local/adaptive-corridor/20261028-ETH-HYPE-raw-fits-v2 \\',
        '  --preceding .local/adaptive-corridor/20261029-payout-flat-risk-v1 \\',
        '  --output .local/adaptive-corridor/NEW-PAYOUT-EMPIRICAL',
        'python3 -B scripts/audit_payout_empirical.py --research .local/adaptive-corridor/NEW-PAYOUT-EMPIRICAL',
        'python3 -B -m unittest discover -s scripts -p test_payout_empirical.py',
        'python3 -B scripts/screen_payout_candidates.py --declare \\',
        '  --study .local/adaptive-corridor/NEW-PAYOUT-EMPIRICAL \\',
        '  --output .local/adaptive-corridor/NEW-PAYOUT-SCREEN',
        'python3 -B scripts/screen_payout_candidates.py --output .local/adaptive-corridor/NEW-PAYOUT-SCREEN',
        'python3 -B -m unittest discover -s scripts -p test_payout_screen.py',
        '```','']
    output.write_text('\n'.join(lines));return dict(report=str(output),sha256=digest(output))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--research',type=Path,required=True);parser.add_argument('--screen',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();print(json.dumps(report(args.research,args.screen,args.output),indent=2))
