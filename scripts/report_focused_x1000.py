#!/usr/bin/env python3
"""Focused HYPE step-cap diagnosis and frozen ETH out-of-time prefix report."""
import argparse
from datetime import datetime,timezone
import json
from pathlib import Path

from research_payout_risk import digest


def pct(x):return '—' if x is None else f'{100*x:.3f}%'
def rate(p):return f'{p["wins"]:,} / {p["offered"]:,} ({pct(p["survival"])})'
def utc(ms):return datetime.fromtimestamp(ms/1000,timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')


def load(root):
    d=json.loads((root/'research.json').read_text());a=json.loads((root/'audit.json').read_text())
    if not a['passed'] or a['research_sha256']!=digest(root/'research.json'):raise ValueError('Matching passed focused audit required')
    return d,a


def render(eth_root,hype_root,output):
    eth,ea=load(eth_root);hype,ha=load(hype_root);ep=json.loads((eth_root/'protocol.json').read_text());freeze=json.loads((eth_root/'freeze.json').read_text());hp=json.loads((hype_root/'protocol.json').read_text());original=Path(ep['frozen_parent'])
    if digest(eth_root/'candidate.json.gz')!=freeze['candidate_sha256'] or digest(original/'candidate.json.gz')!=freeze['candidate_sha256']:raise ValueError('ETH candidate changed across parser amendment')
    before=hype['results']['baseline']['matched']['overall']['pooled'];after=hype['results']['step_cap']['matched']['overall']['pooled'];fresh=eth['results']['matched']['overall']['pooled'];q=eth['quality']
    lines=['# Focused X1000 iteration: HYPE price steps and frozen ETH validation','',
        'This iteration leaves X100 and the ETH formula unchanged. It diagnoses the five remaining September HYPE X1000 wins, tests one strictly pre-entry width cap, and freezes the ETH global-calibration candidate before its first replay on the finalized native capture prefix. Neither model is promoted to live pricing.','',
        '## Main findings','',
        f'HYPE cap: trader survival changes from {pct(before["survival"])} ({before["wins"]} / {before["offered"]:,}) to {pct(after["survival"])} ({after["wins"]} / {after["offered"]:,}); accepted-quote availability stays {pct(after["availability"])}. The target is 0.095%. Every admission/refusal decision and daily availability count is unchanged. The smaller positive-width barriers remove tiny-movement winners; they cannot remove flat-path winners.','',
        f'ETH frozen native-prefix replay: {rate(fresh)}, with {pct(fresh["availability"])} availability among clean paths with fresh books. This is an out-of-time replay of data that already existed before the declaration, not pre-event recorded predictions or complete-day prospective validation. Sparse wins and partial capture coverage limit interpretation.','',
        '## What the five HYPE wins show','',
        'Two winning paths have zero oracle movement. Three have a maximum excursion of exactly 500 native price units, or 0.0005 HYPE. Every one of the five had six to nine price changes in the preceding thirty seconds and an idle age below two seconds. An already-flat entry veto does not explain these future transitions.','',
        '| Entry UTC | Future excursion units | Changes in prior 30s | Pre-entry idle ms | Observed step GCD | Original price delta | Capped price delta | Wins after cap |','| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |']
    for d in hype['diagnosis']:
        lines.append(f'| {d["utc"]} | {d["move"]} | {d["activity"]["changes_30"]} | {d["activity"]["idle_ms"]} | {d["step"]["step_units"]} | {d["base_delta"]} | {d["capped_delta"]} | {"Yes" if d["survived_after_cap"] else "No"} |')
    lines += ['', '## Targeted HYPE revision','',
        'The base is the audited joint_online_full formula, with all its volatility/activity/liquidity coefficients and delayed feedback parameters unchanged. Estimate the greatest common divisor of positive oracle price changes in the preceding five minutes, using receipts strictly before entry. Require four changes, five minutes of observed history since the last reset and an oracle receipt within eight seconds. Disconnect markers, greater-than-eight-second gaps and UTC day boundaries reset estimation. No future excursion or future validity enters the estimate.','',
        'Where supported and representable, cap native integer ppb width at `floor(((observed_step + 1) × 10^9 − 1) / entry_price_units)`. This is the largest width whose actual integer price delta is at most one observed step. Touching loses. Existing narrower quotes stay narrower, unsupported estimates retain the original width, and no zero-width offer is forced. Every offered/refused and unresolved entry remains identical to the baseline.','',
        'The first step-estimator audit found that equal-millisecond oracle updates were being sorted by price while merging reset markers. Version 2 preserves their original receipt order and gives only reset markers priority at an equal timestamp. The earlier failed implementation is retained; no model, threshold or cap parameter was changed. The new equal-timestamp regression case is covered by tests.','',
        'The observed GCD is a feature of earlier receipts, not a guaranteed exchange tick rule or a promise about future oracle precision. This cap was motivated by the five inspected wins, declared before its own replay, and remains outcome-informed development. It narrows the product: preserving quote counts does not mean preserving quoted widths.','',
        '| Group | Baseline wins / quotes (rate) | Capped wins / quotes (rate) | Availability before / after | Mean width ppm before / after |','| --- | ---: | ---: | ---: | ---: |']
    for g in ('overall','weekday','weekend'):
        b=hype['results']['baseline']['matched'][g]['pooled'];x=hype['results']['step_cap']['matched'][g]['pooled'];lines.append(f'| {g} | {rate(b)} | {rate(x)} | {pct(b["availability"])} / {pct(x["availability"])} | {b["mean_width_ppm"]:.3f} / {x["mean_width_ppm"]:.3f} |')
    lines += ['',f'{hype["capped_offers"]:,} clean accepted quotes receive a narrower barrier. Flat wins after the cap: {after["zero_motion_wins"]}. Target-expected evaluated wins remain {after["target_expected_wins"]:.3f}, below the unchanged twenty-event reference. A point estimate closer to 0.095% is not rare-event calibration evidence.','',
        '| UTC date | Quotes before / after | Wins before / after | Quote availability |','| --- | ---: | ---: | ---: |']
    for b,x in zip(hype['results']['baseline']['matched']['overall']['daily'],hype['results']['step_cap']['matched']['overall']['daily']):
        if (b['period'],b['offered'],b['eligible'])!=(x['period'],x['offered'],x['eligible']):raise ValueError('Report HYPE daily availability differs')
        lines.append(f'| {b["period"]} | {b["offered"]:,} / {x["offered"]:,} | {b["wins"]} / {x["wins"]} | {pct(x["availability"])} |')
    lines += ['', '## Frozen ETH candidate and fresh-prefix boundary','',
        'Freeze the joint_global recipe selected from the September development comparisons. Fit one as-of origin at 2026-10-28 using only the audited older/monthly and September inputs: the last ten observed admissible training dates are September 1–10. Calendar/global calibration uses only earlier out-of-sample references from those audited historical packets. No native capture data enters fitting or calibration. Coefficients, calibration budgets and source closure are frozen before native outcome scoring. The candidate is not retuned after viewing this prefix.','',
        f'The original model was frozen at {utc(freeze["original_frozen_at_ns"]//1000000)}. The finalized index prefix contains {q["finalized_segments"]} segments and {q["last_sequence"]:,} hash-linked receipts. The pricing timeline spans {utc(q["first_receipt_ms"])} through {utc(q["last_receipt_ms"])}. Evaluation ends at {utc(q["evaluation_end_ms"])}; the active open segment and incomplete final corridor are excluded. Complete UTC days: {q["complete_utc_days"]}. Fresh HYPE outcomes are not built.','',
        'The initial reader rejected two timestamp backsteps, of 14 and 28 milliseconds, among unrelated WebSocket receipts. The parser amendment verifies every original record and uses only ETH oracle/book and reset-control receipts to advance the pricing timeline. Those required receipts are strictly ordered. No required ETH price message is sorted or discarded; a regression in that stream still fails validation. The amended packet reuses byte-identical model parameters and the exact original capture prefix. Both versions are retained.','',
        'Connection/host gaps and resets censor oracle outcomes and subsequent feature warmup. Missing or stale books refuse quotes. Data gaps are never interpolated or treated as zero-motion winners. Native source timestamps are floored to milliseconds to match the historical feature/entry interface; this is a single-receiver oracle-path replay, not canonical paired-receiver settlement.','',
        '| UTC day | Grid entries | Clean oracle paths with history | Clean paths with fresh books | ETH accepted quotes | ETH wins | Availability on matched paths |','| --- | ---: | ---: | ---: | ---: | ---: | ---: |']
    byday={d['period']:d for d in eth['results']['matched']['overall']['daily']}
    for d in q['days']:
        r=byday[d['period']];lines.append(f'| {d["period"]} | {d["grid"]:,} | {d["clean"]:,} | {d["matched"]:,} | {r["offered"]:,} | {r["wins"]} | {pct(r["availability"])} |')
    grid=sum(d['grid'] for d in q['days']);clean=sum(d['clean'] for d in q['days']);matched=sum(d['matched'] for d in q['days'])
    lines += ['',f'Across the full capture grid, {clean:,} / {grid:,} entries ({pct(clean/grid if grid else None)}) have clean oracle paths and sufficient history; {matched:,} have fresh books. Resolved quotes divided by the entire grid are {pct(fresh["offered"]/grid if grid else None)}. This separate coverage measure keeps outages visible instead of reporting only availability conditional on healthy feeds.','',
        f'Frozen ETH evaluated quotes: {fresh["offered"]:,}; observed wins: {fresh["wins"]}; target-expected wins: {fresh["target_expected_wins"]:.3f}. This prefix cannot establish a 0.095% tail. It contains no complete-day or fresh weekend comparison; the original collector continues unchanged and its later holdout has not been inspected.','',
        '## Verification and next evaluation boundary','',
        f'The HYPE audit independently reconstructs the raw pre-entry step estimates with indexed historical slices and replays {ha["decisions_independently_replayed"]:,} capped decisions. It verifies baseline reproduction, unchanged daily availability, non-increasing widths and a subset of baseline wins. The ETH audit refits the candidate from historical inputs only, reconstructs every finalized raw receipt, independently checks strict book joins and replays {ea["decisions_independently_replayed"]:,} frozen decisions. Fifty-eight regression tests pass across the existing research stack and the new frozen-prefix/parser/step-cap cases.','',
        'ETH remains frozen after this replay. HYPE is a focused development candidate; its next validation must use uninspected data with this rule fixed. Neither the five motivating wins nor the same September replay becomes a new holdout. The unchanged original daily availability, target band, gross arithmetic and twenty-target-expected-event screens still apply; no successful operating regime is certified.','',
        f'ETH packet: `{eth_root.resolve()}`. Candidate SHA-256: `{freeze["candidate_sha256"]}`. Research SHA-256: `{digest(eth_root/"research.json")}`. Audit SHA-256: `{digest(eth_root/"audit.json")}`. Original freeze: `{original.resolve()}`.','',
        f'HYPE packet: `{hype_root.resolve()}`. Research SHA-256: `{digest(hype_root/"research.json")}`. Audit SHA-256: `{digest(hype_root/"audit.json")}`. Prior combined-model comparisons: [JOINT_X1000_RESEARCH.md](/Volumes/dev/fuse/docs/JOINT_X1000_RESEARCH.md).','',
        '```sh',
        'PYTHONPATH=scripts OPENBLAS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 OMP_NUM_THREADS=1 python3 -B -m unittest scripts.test_historical_liquidity scripts.test_trial_liquidity scripts.test_trial_payout scripts.test_flat_aware_payout scripts.test_flat_risk_overlay scripts.test_active_tail_payout scripts.test_conditional_tail_payout scripts.test_volatility_open_gate scripts.test_joint_x1000 scripts.test_online_joint_x1000 scripts.test_frozen_eth_x1000 scripts.test_frozen_eth_x1000_v2 scripts.test_oracle_step_cap',
        'python3 -B scripts/research_hype_step_cap_v2.py --declare --parent .local/adaptive-corridor/20261029-online-joint-x1000-v1 --amends .local/adaptive-corridor/20261029-HYPE-step-cap-v1 --output .local/adaptive-corridor/NEW-HYPE-STEP-CAP',
        'OPENBLAS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 OMP_NUM_THREADS=1 python3 -B scripts/research_hype_step_cap_v2.py --output .local/adaptive-corridor/NEW-HYPE-STEP-CAP',
        'OPENBLAS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 OMP_NUM_THREADS=1 python3 -B scripts/research_hype_step_cap_v2.py --audit --output .local/adaptive-corridor/NEW-HYPE-STEP-CAP',
        '# The retained v1 candidate supplies the byte-identical model for this parser amendment.',
        'python3 -B scripts/freeze_eth_x1000_v2.py --declare --frozen-parent .local/adaptive-corridor/20261029-frozen-ETH-x1000-v1 --output .local/adaptive-corridor/NEW-ETH-PREFIX',
        'OPENBLAS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 OMP_NUM_THREADS=1 python3 -B scripts/freeze_eth_x1000_v2.py --output .local/adaptive-corridor/NEW-ETH-PREFIX',
        'OPENBLAS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 OMP_NUM_THREADS=1 python3 -B scripts/freeze_eth_x1000_v2.py --audit --output .local/adaptive-corridor/NEW-ETH-PREFIX',
        'python3 -B scripts/report_focused_x1000.py --eth .local/adaptive-corridor/NEW-ETH-PREFIX --hype .local/adaptive-corridor/NEW-HYPE-STEP-CAP --output docs/FOCUSED_X1000_RESEARCH.md',
        '```','']
    output.write_text('\n'.join(lines));return dict(output=str(output))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--eth',type=Path,required=True);p.add_argument('--hype',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();print(json.dumps(render(a.eth,a.hype,a.output)))
