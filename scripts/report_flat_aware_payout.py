#!/usr/bin/env python3
"""Report flat-aware payout changes, availability and unchanged development gates."""
import argparse
import json
from pathlib import Path

from research_payout_risk import digest


def pct(x):return '—' if x is None else f'{x:.2%}'


def outcome(p):return f"{p['wins']:,} / {p['offered']:,} ({pct(p['survival'])})"


def report(root,overlay=None):
    meta=json.loads((root/'research.json').read_text());audit=json.loads((root/'audit.json').read_text());plan=json.loads((root/'protocol.json').read_text())
    if not audit['passed'] or audit['research_sha256']!=digest(root/'research.json') or meta['protocol_sha256']!=digest(root/'protocol.json'):raise ValueError('Matching flat-aware audit required')
    results={}
    for a,sha in meta['research_sha256'].items():
        if digest(root/a/'research.json')!=sha:raise ValueError('Flat-aware asset binding differs')
        results[a]=json.loads((root/a/'research.json').read_text())
    overlay_audit=None
    if overlay:
        om=json.loads((overlay/'research.json').read_text());op=json.loads((overlay/'protocol.json').read_text());overlay_audit=json.loads((overlay/'audit.json').read_text())
        if not overlay_audit['passed'] or overlay_audit['research_sha256']!=digest(overlay/'research.json') or op['parent']!=str(root.resolve()) or op['parent_sha256']!=digest(root/'research.json'):raise ValueError('Matching overlay audit and parent required')
        for a,sha in om['research_sha256'].items():
            if digest(overlay/a/'research.json')!=sha:raise ValueError('Overlay asset report differs')
            extra=json.loads((overlay/a/'research.json').read_text())
            for phase in ('earlier_oof','trial'):
                for m,values in extra['results'][phase].items():results[a]['results'][phase][m]['variants']['conservative_overlay']=values
    labels=dict(previous_formula='Previous fitted formula',flat_veto='Previous formula plus flat veto',activity_hurdle='Activity hurdle',calendar_hurdle='Calendar activity hurdle',conservative_overlay='Conservative flat risk overlay')
    lines=['# Flat aware ETH and HYPE payout formula iteration','',
        'This iteration adds a pre-entry flat-oracle veto and separate asset-specific estimates of flat-path probability. The revised formulas were tested at 100× and 1,000× on September 1–10, 2026 UTC, with the same weekday/weekend comparisons, strict barrier settlement, data exclusions and availability requirements as the previous backtest. Fourteen earlier monthly out-of-sample dates are reported separately. All evidence is historical development.','',
        'The diagnosed failure was specific: all eighteen ETH wins accepted by the previous raw liquidity formula at 1,000× occurred after the oracle had already been unchanged for more than a minute. The old logistic head assigned those entries probabilities below the 0.095 percent target despite zero price changes in both preceding thirty- and sixty-second windows. A positive-width corridor cannot defeat an actually flat future path by narrowing its barriers.','',
        '## Formula changes','',
        'The previous fitted formula remains an exact control. The veto-only comparison keeps its widths and probability estimates but refuses entries when the last price change was at least thirty seconds ago, there were no price changes in the preceding thirty seconds, or the recorded idle age is only a lower bound. This decision uses pre-entry features; it does not inspect the current outcome or future health.','',
        'The activity hurdle replaces the logistic floor estimate with two asset-specific empirical heads: zero-motion probability and probability of surviving the one-ppm minimum width. The hierarchy conditions on preceding thirty-second change count and idle age. The calendar hurdle adds a UTC weekend child. Each child gives dates equal weight, shrinks toward its parent with mass 32 plus a half-event, and falls back to the parent below 200 paths or three earlier dates. The two heads remain nested. These are smoothed development estimates, not confidence bounds.','',
        'Positive movement size is fitted separately using exact date-weighted empirical CDFs, with local groups matching the hurdle activity/idle state and optional weekend. The existing slow-volatility anchor, parent shrinkage, empirical quantile and integer-ppm rounding rules remain. For target `q = 0.95 / M` and estimated minimum-width survival `p_min`, the positive-component quantile is `(q − p_min) / (1 − p_min)`. Quotes are refused if the floor exceeds target or fewer than twenty positive-tail training references support that quantile.','',
        'Both new hurdle formulas apply the flat veto. At 1,000× they additionally require at least four price changes in the preceding thirty seconds and a last price change less than three seconds before entry. These fixed recovery conditions were declared before this replay. The veto-only ablation does not add this recovery condition.','',
        'Each daily origin fits all components from strictly earlier matured matched paths of that asset. Labels enter only when expiry plus thirty seconds is strictly before the origin. Features and context retain the existing daily reset. No probability coefficients, thresholds or model variants were selected from the new replay. Earlier monthly raw outcomes and September outcomes had already been inspected in the broader research program, so chronological fitting does not create an untouched research holdout.','',
        '## Consecutive weekday and weekend results','',
        'The tables use identical clean oracle paths with fresh pre-entry books for every formula. Trader wins are accepted quotes whose complete observed thirty-second paths remained strictly inside the integer barriers; touching either barrier loses. Targets are 0.95 percent at 100× and 0.095 percent at 1,000×. Availability is accepted resolved quotes divided by the common eligible paths.','']
    passes=[v['screen']['qualifies'] for r in results.values() for m in r['results']['trial'].values() for v in m['variants'].values()]
    if not any(passes):lines[4:4]=['No revised formula passes all existing development checks. The explicit veto removes the diagnosed already-flat admission failure; accepted-quote availability and payout calibration remain unresolved.','']
    if overlay:
        at=lines.index('## Consecutive weekday and weekend results')
        lines[at:at]=['The first replacement hurdle formulas worsened HYPE results. After inspecting that development regression, a fifth conservative overlay was declared and replayed. It retains the previous positive-movement CDF and uses the larger of the previous logistic and new empirical flat-risk estimates. The same flat and recovery vetoes apply. Every offered quote is checked to have been offered previously, with width no larger than the old width. This guarantees a subset of offers and no wider corridor per retained entry; it does not guarantee an improved win-rate ratio or probability calibration. This additional iteration is explicitly outcome-informed development.','']
        n=sum(r['results']['trial']['1000']['variants']['conservative_overlay']['matched']['overall']['pooled']['offered'] for r in results.values())
        if n==0:lines[6:6]=['The conservative overlay accepts no 1,000× entries for either asset. This prevents the old unsafe offers in this replay but supplies no estimate of a usable 1,000× win rate. At 100×, ETH becomes substantially more restrictive, while HYPE remains above break-even on weekdays.','']
    for a,r in results.items():
        lines += [f'### {a}','',
            '| Payout | Formula | Weekday wins / quotes and rate | Weekday availability | Weekend wins / quotes and rate | Weekend availability | Weekday LP gross per stake | Weekend LP gross per stake |',
            '| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |']
        for m,mm in r['results']['trial'].items():
            for v,vv in mm['variants'].items():
                d=vv['matched']['weekday']['pooled'];w=vv['matched']['weekend']['pooled']
                lines.append(f"| {int(m):,}× | {labels[v]} | {outcome(d)} | {pct(d['availability'])} | {outcome(w)} | {pct(w['availability'])} | {pct(d['gross_lp_per_stake'])} | {pct(w['gross_lp_per_stake'])} |")
        lines.append('')
    lines+=['## Flat wins and pooled results','',
        'The veto-only comparison isolates entries removed by the explicit pre-entry rule. New hurdle formulas also change conditional probability, movement groups and widths, so their accepted populations differ. Zero wins after refusing every entry would not demonstrate successful pricing.','',
        '| Asset | Payout | Formula | Wins / quotes and rate | Flat-oracle wins | Availability | Worst date availability | Target expected wins | Passes existing screens |',
        '| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | --- |']
    for a,r in results.items():
        for m,mm in r['results']['trial'].items():
            for v,vv in mm['variants'].items():
                s=vv['matched']['overall'];p=s['pooled']
                lines.append(f"| {a} | {int(m):,}× | {labels[v]} | {outcome(p)} | {p['zero_motion_wins']} | {pct(p['availability'])} | {pct(s['minimum_daily_availability'])} | {p['target_expected_wins']:.2f} | {'Yes' if vv['screen']['qualifies'] else 'No'} |")
    lines+=['','## Earlier monthly comparisons','',
        'July 2025 through August 2026 supplies fourteen earlier out-of-sample dates per asset. The first six months are fit warmup; every subsequent month is scored using only its preceding dates. These comparisons do not select a variant. First-of-month sampling is not consecutive recording, and early 1,000× origins can lack positive-tail training support. Empty quote dates remain failures under the unchanged screens.','',
        '| Asset | Payout | Formula | Wins / quotes and rate | Availability | Worst date availability | LP gross per stake |',
        '| --- | --- | --- | ---: | ---: | ---: | ---: |']
    for a,r in results.items():
        for m,mm in r['results']['earlier_oof'].items():
            for v,vv in mm['variants'].items():
                s=vv['matched']['overall'];p=s['pooled']
                lines.append(f"| {a} | {int(m):,}× | {labels[v]} | {outcome(p)} | {pct(p['availability'])} | {pct(s['minimum_daily_availability'])} | {pct(p['gross_lp_per_stake'])} |")
    lines+=['','## Availability without a book requirement','',
        'The secondary cohort includes all clean oracle paths. Missing books stay in the availability denominator, and every formula here refuses them because each requires measured liquidity inputs or the same common book requirement. No unavailable entry is silently treated as a flat win. Full daily and calendar results are retained for both cohorts.','',
        '| Asset | Payout | Formula | Weekday availability on all clean paths | Weekend availability on all clean paths |',
        '| --- | --- | --- | ---: | ---: |']
    for a,r in results.items():
        for m,mm in r['results']['trial'].items():
            for v,vv in mm['variants'].items():
                lines.append(f"| {a} | {int(m):,}× | {labels[v]} | {pct(vv['all_clean']['weekday']['pooled']['availability'])} | {pct(vv['all_clean']['weekend']['pooled']['availability'])} |")
    lines+=['','## Interpretation and verification','',
        'Refusing an already-flat oracle addresses the identified admission failure. It cannot predict every transition from active to flat, establish a rare-event probability from a small sample, or create a valid positive-width quote when estimated unavoidable survival already exceeds the payout target. Wider or narrower corridors do not remove a zero-motion winner.','',
        'The existing necessary screens are unchanged: quotes on every date, at least 85 percent availability on every date, pooled survival within 75–125 percent of target, nonnegative zero-cost LP gross and at least twenty target-expected evaluated wins. A 1,000× rule needs at least 21,053 accepted resolved quotes to reach the last count reference. These are descriptive checks, rather than proof of independent-event confidence or deployability. The two September weekend dates and repeatedly inspected outcomes remain material limits.','',
        'LP gross assumes one stake unit per accepted resolved quote, total payout including returned stake, and `quotes − M × trader wins`. Gross per stake divides this by quote count. It excludes fees, hedging, funding, latency, underwriting capacity and correlated capital losses. Empty quote sets have no estimated win rate or return. This is an oracle-path formula replay rather than a full production engine or canonical-admission simulation.','',
        f"The audit passed: {sum(x['floor_models_refit'] for x in audit['assets'])} earlier-only floor models refitted, all positive CDF points/date weights verified, {sum(x['decisions_independently_replayed'] for x in audit['assets']):,} decisions independently replayed, and all daily/calendar/cohort summaries reconciled. The previous September baseline was reproduced exactly. Five new focused tests cover the falsely safe frozen-oracle regression, recovery boundaries, asset/date isolation, future-label invariance, date weighting, midnight maturity and complete fit/export/audit/tamper rejection.",'',
        f"Research packet: `{root.resolve()}`. Previous payout packet: `{plan['previous']}`. The new protocol and complete local Python source snapshot were frozen before fitting and replay. Every origin model, refused/unresolved decision and cohort summary is retained. The live formula and ongoing fresh collector were not changed.",'',
        '```sh','PYTHONPATH=scripts OPENBLAS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 python3 -B -m unittest scripts.test_flat_aware_payout',
        f"python3 -B scripts/research_flat_aware_payout.py --declare --previous {plan['previous']} --output .local/adaptive-corridor/NEW-FLAT-AWARE-PAYOUT",
        'OPENBLAS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 python3 -B scripts/research_flat_aware_payout.py --output .local/adaptive-corridor/NEW-FLAT-AWARE-PAYOUT',
        'OPENBLAS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 python3 -B scripts/research_flat_aware_payout.py --audit --output .local/adaptive-corridor/NEW-FLAT-AWARE-PAYOUT','```','',
        f"Research SHA-256: `{digest(root/'research.json')}`. Audit SHA-256: `{digest(root/'audit.json')}`.",'']
    if overlay:
        lines+=['',f"Conservative overlay packet: `{overlay.resolve()}`. Its separate audit independently replayed {sum(a['decisions'] for a in overlay_audit['assets']):,} decisions and verified the subset/width invariant on every offered quote. Three additional tests cover risk non-decrease, width tightening, unchanged missing-book refusal, future-outcome invariance and independent replay across payout and flat states.",'',
            '```sh','PYTHONPATH=scripts OPENBLAS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 python3 -B -m unittest scripts.test_flat_risk_overlay',
            'python3 -B scripts/research_flat_risk_overlay.py --declare --parent .local/adaptive-corridor/NEW-FLAT-AWARE-PAYOUT --output .local/adaptive-corridor/NEW-FLAT-RISK-OVERLAY',
            'OPENBLAS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 python3 -B scripts/research_flat_risk_overlay.py --output .local/adaptive-corridor/NEW-FLAT-RISK-OVERLAY',
            'OPENBLAS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 python3 -B scripts/research_flat_risk_overlay.py --audit --output .local/adaptive-corridor/NEW-FLAT-RISK-OVERLAY','```','',
            f"Overlay research SHA-256: `{digest(overlay/'research.json')}`. Overlay audit SHA-256: `{digest(overlay/'audit.json')}`.",'']
    return '\n'.join(lines)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--research',type=Path,required=True);parser.add_argument('--output',type=Path,required=True);parser.add_argument('--overlay',type=Path);args=parser.parse_args()
    args.output.write_text(report(args.research,args.overlay));print(args.output)
