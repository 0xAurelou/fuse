#!/usr/bin/env python3
"""Exploratory capture-gap attribution and width-independent regime comparison.

Reads completed, verified captures. Never changes frozen artifacts, fits a next
candidate, starts collection or claims independent oracle/production validation.
"""
import argparse
from bisect import bisect_left, bisect_right
from collections import Counter, defaultdict
import csv
from datetime import datetime, timedelta, timezone
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import shutil

from capture_dataset import file_hash, load_capture
from prospective_capture import verify_artifacts

ZONE=timezone(timedelta(hours=8))
WIDTHS=(100,117,150,200,250,275,300,314,350,400,450,500,600,800,1000)
LOOKBACK=300000


def stamp(at):
    return datetime.fromtimestamp(at/1000,ZONE).isoformat(timespec='milliseconds')


def reason_flags(feeds,mismatch,at,policy):
    flags=set()
    for source in ('a','b'):
        if source not in feeds:flags.add('missing_'+source)
        elif at-feeds[source][0]>policy['max_gap_ms']:flags.add('stale_'+source)
    if mismatch is not None and at-mismatch>=policy['disagreement_ms']:
        flags.add('sustained_disagreement')
    return flags


def reconstruct(receipts,policy,start,end):
    """Attribute the existing frozen analyzer's exact eligibility decisions."""
    feeds={};mismatch=None;current=None;paired=[];rows=[]
    window=dict(start=start,expiry=start+30000,entry=None,last=None,move=0,step=0,
                reasons={'startup_no_paired_entry'})
    def healthy(at):
        return len(feeds)==2 and all(0<=at-v[0]<=policy['max_gap_ms'] for v in feeds.values()) and feeds['a'][1]==feeds['b'][1]
    def boundary(at,kind):
        flags=reason_flags(feeds,mismatch,at,policy)
        if not healthy(at):
            flags.add('unhealthy_'+kind)
            if len(feeds)==2 and feeds['a'][1]!=feeds['b'][1]:flags.add(kind+'_disagreement')
        return flags
    def finish():
        window['reasons'].update(boundary(window['expiry'],'expiry'))
        out=dict(window,reasons=sorted(window['reasons']),valid=not window['reasons'])
        rows.append(out)
        at=window['expiry']
        return dict(start=at,expiry=at+30000,entry=current,last=current,move=0,step=0,reasons=boundary(at,'entry'))
    for receipt in receipts:
        at=receipt['at'];source=receipt['source'];price=receipt['price']
        while at>=window['expiry']:
            window=finish()
        window['reasons'].update(reason_flags(feeds,mismatch,at,policy))
        feeds[source]=(at,price)
        if len(feeds)==2 and feeds['a'][1]!=feeds['b'][1]:
            if mismatch is None:mismatch=at
        else:mismatch=None
        if not healthy(at):continue
        current=price;paired.append((at,price))
        if window['entry'] is None:continue
        window['move']=max(window['move'],abs(price-window['entry']))
        window['step']=max(window['step'],abs(price-window['last']))
        window['last']=price
    while window['expiry']<=end:window=finish()
    return rows,paired


def union(intervals):
    result=[]
    for start,end in sorted(intervals):
        if end<=start:continue
        if result and start<=result[-1][1]:result[-1]=(result[-1][0],max(end,result[-1][1]))
        else:result.append((start,end))
    return result


def intersect(a,b):
    result=[];i=j=0
    while i<len(a) and j<len(b):
        start=max(a[i][0],b[j][0]);end=min(a[i][1],b[j][1])
        if start<end:result.append((start,end))
        if a[i][1]<b[j][1]:i+=1
        else:j+=1
    return result


def overlaps(intervals,start,end):
    return any(a<end and b>start for a,b in intervals)


def silence_intervals(receipts,start,end,max_gap):
    gaps=[];stale={};by_source=defaultdict(list)
    for r in receipts:by_source[r['source']].append(r['at'])
    for source in ('a','b'):
        times=by_source[source];stale[source]=[]
        if not times:
            stale[source]=[(start,end)];continue
        for before,after in zip(times,times[1:]+[end]):
            if after-before>max_gap:
                gaps.append(dict(source=source,last_receipt_ms=before,next_receipt_or_end_ms=after,
                                 silence_ms=after-before,stale_ms=max(0,after-before-max_gap-1),terminal=after==end))
                stale[source].append((before+max_gap+1,after))
    return gaps,stale


def power_events(path):
    if path is None:return []
    result=[]
    pattern=re.compile(r'^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d [+-]\d{4}) (Sleep|Wake|DarkWake) (.+)$')
    for line in path.read_text().splitlines():
        match=pattern.match(line)
        if not match or match[3].startswith('Requests'):continue
        at=int(datetime.strptime(match[1],'%Y-%m-%d %H:%M:%S %z').timestamp()*1000)
        result.append(dict(at=at,kind=match[2],detail=match[3]))
    return sorted(result,key=lambda e:e['at'])


def sleep_intervals(events):
    intervals=[];since=None
    for event in events:
        if event['kind']=='Sleep' and since is None:since=event['at']
        elif event['kind'] in ('Wake','DarkWake') and since is not None:
            intervals.append((since,event['at']));since=None
    return union(intervals)


def capture_errors(path,start,end):
    inside=[];after=[]
    pat=re.compile(r'^(\d{4}/\d\d/\d\d \d\d:\d\d:\d\d) WARN .* source=([ab]) error="(.*)"$')
    for line in path.read_text().splitlines():
        m=pat.match(line)
        if not m:continue
        at=int(datetime.strptime(m[1],'%Y/%m/%d %H:%M:%S').replace(tzinfo=ZONE).timestamp()*1000)
        error=m[3]
        category=('upstream_connection_expired' if 'Expired' in error else
                  'address_unavailable' if "assign requested address" in error else
                  'timeout' if 'timeout' in error else
                  'connection_reset' if 'reset by peer' in error else 'other')
        row=dict(at=at,source=m[2],category=category,error=error)
        if start<=at<end:inside.append(row)
        elif at>=end:after.append(row)
    return inside,after


def lagged_features(rows,paired,start,lookback=LOOKBACK):
    times=[v[0] for v in paired];prices=[v[1] for v in paired]
    steps=[0.0]+[math.log(b/a)*10000 for a,b in zip(prices,prices[1:])]
    squares=[0.0];absolute=[0.0]
    for value in steps:squares.append(squares[-1]+value*value);absolute.append(absolute[-1]+abs(value))
    bad=[(r['start'],r['expiry']) for r in rows if not r['valid']]
    for row in rows:
        at=row['start'];begin=at-lookback
        row['lag_features']=None
        if begin<start or overlaps(bad,begin,at):continue
        i=bisect_right(times,begin)-1;j=bisect_left(times,at)-1
        if i<0 or j<=i:continue
        path=absolute[j+1]-absolute[i+1]
        net=math.log(prices[j]/prices[i])*10000
        row['lag_features']=dict(vol_bps=math.sqrt(max(0,squares[j+1]-squares[i+1])),
                                 net_bps=net,efficiency=min(1,abs(net)/path) if path else 0,
                                 max_step_bps=max(abs(v) for v in steps[i+1:j+1]))


def quantile(values,q):
    values=sorted(values)
    if not values:raise ValueError('no eligible training history for regime thresholds')
    at=(len(values)-1)*q;lo=int(at);hi=min(lo+1,len(values)-1)
    return values[lo]+(values[hi]-values[lo])*(at-lo)


def regime_thresholds(first):
    healthy=[r for r in first if r['valid']]
    train=healthy[:int(len(healthy)*.6)]
    features=[r['lag_features'] for r in train if r['lag_features'] is not None]
    return dict(lookback_ms=LOOKBACK,vol_low_max_bps=quantile([f['vol_bps'] for f in features],1/3),
                vol_mid_max_bps=quantile([f['vol_bps'] for f in features],2/3),
                jump_min_bps=quantile([f['max_step_bps'] for f in features],.95),
                trend_efficiency_min=.6,training_windows=len(train),clean_history_training_windows=len(features),
                training_end_ms=train[-1]['expiry'],
                selection='Exploratory regime thresholds fitted only to prior five-minute features in the first 60% of healthy windows of the first capture; frozen across widths and the second capture.')


def label(row,thresholds):
    f=row['lag_features']
    if f is None:return dict(volatility='insufficient_clean_history',trend='insufficient_clean_history',jump='insufficient_clean_history')
    vol=('flat' if f['vol_bps']==0 else 'quiet' if f['vol_bps']<=thresholds['vol_low_max_bps'] else
         'normal' if f['vol_bps']<=thresholds['vol_mid_max_bps'] else 'volatile')
    trend=('up' if f['net_bps']>0 else 'down') if f['efficiency']>=thresholds['trend_efficiency_min'] else 'choppy'
    jump='recent_jump' if f['max_step_bps']>0 and f['max_step_bps']>=thresholds['jump_min_bps'] else 'no_recent_jump'
    return dict(volatility=vol,trend=trend,jump=jump)


def score(rows,width):
    if any(r['entry']*width//1000000<=0 for r in rows):raise ValueError('zero rounded corridor')
    survived=sum(r['move']<r['entry']*width//1000000 for r in rows)
    return dict(windows=len(rows),survived=survived,survival=survived/len(rows) if rows else None)


def target_range(rows,maximum=50000):
    """Exact retrospective legal width interval with 43–53% path survival.

    A window survives when integer width reaches ceil((move+1)*1e6/entry).
    This is a descriptive feasibility check, not next-candidate selection.
    """
    if not rows:return None
    thresholds=sorted(((r['move']+1)*1000000+r['entry']-1)//r['entry'] for r in rows)
    n=len(rows);minimum_count=(43*n+99)//100;maximum_count=53*n//100
    if minimum_count>maximum_count:return None
    lower=max(1,thresholds[minimum_count-1])
    upper=min(maximum,thresholds[maximum_count]-1)
    return dict(minimum_ppm=lower,maximum_ppm=upper) if lower<=upper else None


def compare(rows,widths):
    good=[r for r in rows if r['valid']]
    result=[]
    groups=defaultdict(list)
    for row in good:
        for axis,value in row['regimes'].items():groups[(axis,value)].append(row)
    for width in widths:
        result.append(dict(group_axis='all',group='all',width_ppm=width,**score(good,width)))
        for (axis,name),values in sorted(groups.items()):
            result.append(dict(group_axis=axis,group=name,width_ppm=width,**score(values,width)))
    return result


def analyze_run(directory,events):
    spec=verify_artifacts(directory)
    verified_rows,source,manifest=load_capture(directory)
    source=dict(source,data_role='Exploratory diagnostic comparison; no next candidate fitted or selected.')
    receipts=[]
    from decimal import Decimal
    with (directory/'receipts.jsonl').open() as stream:
        for line in stream:
            r=json.loads(line)
            receipts.append(dict(at=r['at'],source=r['source'],price=int(Decimal(r['raw']['data']['ctx']['oraclePx'])*1000000)))
    start=manifest['frozen_at_ms'];end=start+manifest['duration_ms'];policy=manifest['policy']
    rows,paired=reconstruct(receipts,policy,start,end)
    frozen=importlib.util.spec_from_file_location('frozen_capture_analyzer',directory/'analyze.py')
    module=importlib.util.module_from_spec(frozen);frozen.loader.exec_module(module)
    with (directory/'receipts.jsonl').open() as stream:
        reference=list(module.windows((json.loads(line) for line in stream),policy,start,end))
    fields=('start','expiry','entry','last','move','step','valid')
    if len(rows)!=len(reference) or any(any(a[k]!=b[k] for k in fields) for a,b in zip(rows,reference)):
        raise ValueError('diagnostic reconstruction differs from frozen analyzer')
    official=json.loads((directory/'analysis.json').read_text())
    if len(verified_rows)!=sum(r['valid'] for r in rows) or len(rows)!=official['completed_windows']:
        raise ValueError('source eligibility count mismatch')
    original_width=policy['model']['base_width_ppm']
    if score([r for r in rows if r['valid']],original_width)['survived']!=official['survived_windows']:
        raise ValueError('original frozen outcome mismatch')
    gaps,stale=silence_intervals(receipts,start,end,policy['max_gap_ms'])
    common=intersect(stale['a'],stale['b']);asleep=sleep_intervals(events)
    errors,late_errors=capture_errors(directory/'capture.log',start,end)
    for gap in gaps:
        a,b=gap['last_receipt_ms'],gap['next_receipt_or_end_ms']
        gap['last_wita']=stamp(a);gap['next_wita']=stamp(b)
        gap['overlapping_power_events']=[e for e in events if a-2000<=e['at']<=b+2000]
        gap['overlaps_recorded_sleep']=overlaps(asleep,a,b)
    reason_counts=Counter(reason for row in rows if not row['valid'] for reason in row['reasons'])
    combinations=Counter(','.join(row['reasons']) for row in rows if not row['valid'])
    bad=[r for r in rows if not r['valid']]
    both_bad=sum(overlaps(common,r['start'],r['expiry']+1) for r in bad)
    lagged_features(rows,paired,start)
    status=json.loads((directory/'status.json').read_text())
    late_receipts=sum(r['at']>=end for r in receipts)
    return dict(name=directory.name,directory=str(directory.resolve()),source=source,manifest=manifest,
                rows=rows,official=official,gaps=gaps,stale_intervals=stale,both_stale_intervals=common,
                summary=dict(receipts=len(receipts),completed_windows=len(rows),healthy_windows=len(rows)-len(bad),
                             censored_windows=len(bad),coverage=(len(rows)-len(bad))/len(rows),
                             reason_counts=dict(reason_counts),reason_combinations=dict(combinations),
                             invalid_windows_overlapping_both_stale=both_bad,
                             both_stale_seconds=sum(b-a for a,b in common)/1000,
                             per_receiver_silence_events=len(gaps),
                             in_horizon_reconnects=dict(Counter(e['category'] for e in errors)),
                             post_deadline_reconnects=dict(Counter(e['category'] for e in late_errors)),
                             completion_delay_seconds=(status['updated_at_ms']-end)/1000,
                             post_deadline_retained_receipts=late_receipts,
                             frozen_reconstruction_verified=True),
                errors_in_horizon=errors)


def write_csv(path,rows,fields):
    with path.open('x',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=fields,extrasaction='ignore');writer.writeheader();writer.writerows(rows)


def plots(runs,widths,output,events):
    os.environ.setdefault('MPLCONFIGDIR','/private/tmp/fuse-matplotlib-cache')
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import matplotlib.dates as dates
    fig,axes=plt.subplots(1,3,figsize=(17,5),layout='constrained')
    for run in runs:
        all_rows=[r for r in run['comparison'] if r['group_axis']=='all']
        axes[0].plot([r['width_ppm']/100 for r in all_rows],[r['survival']*100 for r in all_rows],marker='o',label=run['name'].replace('20261026-',''))
    axes[0].axhspan(43,53,color='#d3e9d5',alpha=.7,label='Target 43–53%')
    axes[0].set(title='Same corridor widths on both recordings',xlabel='Half-width (bps)',ylabel='Healthy-window survival (%)',ylim=(0,100));axes[0].legend(fontsize=8)
    colors={'quiet':'#287eaf','normal':'#cb8c20','volatile':'#b23a48','flat':'#558f36'}
    for ax,run in zip(axes[1:],runs):
        for regime,color in colors.items():
            data=[r for r in run['comparison'] if r['group_axis']=='volatility' and r['group']==regime]
            if data and data[0]['windows']:
                ax.plot([r['width_ppm']/100 for r in data],[r['survival']*100 for r in data],color=color,marker='.',label=f"{regime}, n={data[0]['windows']}")
        ax.axhspan(43,53,color='#d3e9d5',alpha=.7)
        ax.set(title=run['name'].replace('20261026-','')+'\nRegime from prior 5 minutes',xlabel='Half-width (bps)',ylim=(0,100));ax.legend(fontsize=8)
    fig.suptitle('Exploratory comparisons — no next candidate selected',fontsize=15)
    fig.savefig(output/'corridor-comparison.png',dpi=170);plt.close(fig)
    run=runs[-1];start=run['manifest']['frozen_at_ms'];end=start+run['manifest']['duration_ms']
    fig,axes=plt.subplots(2,1,figsize=(13,6),layout='constrained')
    for level,source in enumerate(('a','b')):
        intervals=run['stale_intervals'][source]
        for a,b in intervals:axes[0].plot([datetime.fromtimestamp(a/1000,ZONE),datetime.fromtimestamp(b/1000,ZONE)],[level,level],lw=9,color='#be4350')
    for a,b in sleep_intervals(events):
        a=max(a,start);b=min(b,end)
        if a<b:axes[0].axvspan(datetime.fromtimestamp(a/1000,ZONE),datetime.fromtimestamp(b/1000,ZONE),color='gray',alpha=.17)
    axes[0].set(yticks=[0,1],yticklabels=['Receiver a stale','Receiver b stale'],ylim=(-.5,1.5),title='Round-2 receiver freshness failures; gray = recorded sleep intervals')
    zoom_start=max(start,min((a for a,b in run['both_stale_intervals']),default=start)-60000)
    axes[0].set_xlim(datetime.fromtimestamp(zoom_start/1000,ZONE),datetime.fromtimestamp(end/1000,ZONE))
    axes[0].set_xlabel('Late-run detail (WITA); original horizon remains eight hours')
    axes[0].xaxis.set_major_formatter(dates.DateFormatter('%d %b %H:%M',tz=ZONE))
    hourly=run['hourly'];axes[1].bar([r['hour'] for r in hourly],[r['coverage']*100 for r in hourly],color='#287eaf')
    axes[1].axhline(90,color='#be4350',ls='--',label='90% requirement');axes[1].set(xlabel='Hour from frozen start',ylabel='Healthy coverage (%)',ylim=(0,105),title='Frozen 30-second windows, including censored windows');axes[1].legend()
    fig.savefig(output/'gap-timeline.png',dpi=170);plt.close(fig)


def report(runs,thresholds,widths,output,events):
    lines=['# Capture gaps and corridor comparison','',
           'Exploratory investigation of two completed BTC recordings. Original manifests, receipts, candidates and prospective results are unchanged. No new candidate selected and no capture started. All times below are WITA (UTC+8).','',
           '## Data integrity and eligibility','',
           '| Recording | Verified receipts | Healthy / complete windows | Coverage | Censored | Both receivers stale (minutes) |',
           '| --- | ---: | ---: | ---: | ---: | ---: |']
    for run in runs:
        s=run['summary'];lines.append(f"| {run['name']} | {s['receipts']:,} | {s['healthy_windows']}/{s['completed_windows']} | {s['coverage']:.2%} | {s['censored_windows']} | {s['both_stale_seconds']/60:.2f} |")
    lines+=['','Each receipt chain was checked by its original frozen Go executable. The diagnostic reconstruction matches every entry, expiry, barrier-path move and eligibility flag from that recording’s frozen analyzer.','',
            '## Gap attribution','',
            'Reason counts overlap: a window can have stale receivers, disagreement and an unhealthy expiry. No missing price or barrier outcome was interpolated.','']
    for run in runs:
        s=run['summary'];lines += [f"### {run['name']}",'',f"Censoring reasons: `{json.dumps(s['reason_counts'],sort_keys=True)}`.",
        f"Invalid windows overlapping simultaneous receiver staleness: {s['invalid_windows_overlapping_both_stale']}/{s['censored_windows']}.",
        f"In-horizon reconnects: `{json.dumps(s['in_horizon_reconnects'],sort_keys=True)}`.",
        f"Post-deadline retained receipts: {s['post_deadline_retained_receipts']}; completion processing delay: {s['completion_delay_seconds']/3600:.2f} hours.",'']
    lines+=['### Largest round-2 receipt silences','',
            '| Receiver | Last receipt | Next receipt / frozen end | Silence | Sleep overlap |',
            '| --- | --- | --- | ---: | --- |']
    for gap in sorted(runs[-1]['gaps'],key=lambda g:g['silence_ms'],reverse=True)[:12]:
        lines.append(f"| {gap['source']} | {gap['last_wita']} | {gap['next_wita']} | {gap['silence_ms']/60_000:.2f} min | {gap['overlaps_recorded_sleep']} |")
    lines += ['', ('The power log records lid-closed (Clamshell) sleep beginning around 00:09–00:10 on 27 October, followed by repeated sleep/dark-wake periods. These line up with common-mode receiver silences. Capture logs also show read timeouts and an unavailable local address around network transitions. The two connections share one host and endpoint, so neither provides independent power/network availability.' if events else 'No host power events were supplied; receipt gaps alone cannot establish whether host sleep or network loss caused them.'),
              '', 'The recorder used a Go context deadline, while its submission path also checked the wall-clock deadline. Go/OS monotonic timer progress during host suspend can differ from wall-clock progress; this is consistent with late process completion. The verified stream nevertheless contains zero post-deadline receipts. Confirm timer behavior in a controlled suspend/wake drill before treating this as fully reproduced. `caffeinate -i` prevents idle sleep, not forced lid-closed sleep.',
              '', '![Receiver failures and coverage](gap-timeline.png)','',
              '## Corridor comparison on identical paths','',
              'All widths use the same eligible windows per recording and exact integer price rounding; touching either barrier fails. This is hypothetical first-stage path survival, not actual trader demand or a reconciled LP PnL experiment.','',
              '| Half-width (ppm / bps) | First capture | Round 2 |','| --- | ---: | ---: |']
    for width in widths:
        values=[next(v for v in run['comparison'] if v['group_axis']=='all' and v['width_ppm']==width) for run in runs]
        lines.append(f"| {width} / {width/100:.2f} | {values[0]['survival']:.2%} | {values[1]['survival']:.2%} |")
    ranges=[target_range([r for r in run['rows'] if r['valid']]) for run in runs]
    lines+=['','Exact retrospective widths reaching the 43–53% band on each recording’s healthy windows:','']
    for run,interval in zip(runs,ranges):
        text=f"{interval['minimum_ppm']}–{interval['maximum_ppm']} ppm" if interval else 'none'
        lines.append(f"- {run['name']}: **{text}**.")
    if all(ranges) and max(r['minimum_ppm'] for r in ranges)>min(r['maximum_ppm'] for r in ranges):
        lines+=['','There is **no fixed integer-ppm width** meeting the pooled 43–53% band in both observed healthy samples. This is a descriptive exact-count result, not an independent-sample safety test or a claim about unobserved windows.']
    lines += ['', 'The first recording supplied training data for round 2, so these cross-recording comparisons are exploratory. They are not a new prospective test of every width. Censoring is nonrandom and concentrated in the late part of round 2; healthy-only comparisons cannot establish what the missing windows would have done.','',
              '## Width-independent market regimes','',
              f"Labels use only prices strictly before entry over a five-minute lookback. Low/medium/high volatility cutoffs are {thresholds['vol_low_max_bps']:.3f} and {thresholds['vol_mid_max_bps']:.3f} bps of realized log-return variation. They were estimated from {thresholds['clean_history_training_windows']} clean-history windows in the first capture’s training portion and held fixed across both recordings and all widths. A lookback overlapping a censored window receives `insufficient_clean_history`; gaps are not interpolated.",
              '', f"Trend is a separate axis: signed five-minute net movement with directional efficiency ≥{thresholds['trend_efficiency_min']:.0%}. Recent jump is another axis with a training-only 95th-percentile step threshold of {thresholds['jump_min_bps']:.3f} bps. These are exploratory labels, not approved production regime definitions.",'',
              '| Recording / prior volatility | Windows | Survival at 117 ppm | Survival at 314 ppm |',
              '| --- | ---: | ---: | ---: |']
    for run in runs:
        groups=sorted({v['group'] for v in run['comparison'] if v['group_axis']=='volatility'})
        for group in groups:
            a=next(v for v in run['comparison'] if v['group_axis']=='volatility' and v['group']==group and v['width_ppm']==117)
            b=next(v for v in run['comparison'] if v['group_axis']=='volatility' and v['group']==group and v['width_ppm']==314)
            lines.append(f"| {run['name']} / {group} | {a['windows']} | {a['survival']:.2%} | {b['survival']:.2%} |")
    lines += ['', 'The original regime names were defined partly using the candidate corridor itself: for example, “volatile” required a move outside that corridor. That makes some conditional outcomes nearly tautological and changes group membership when the width changes. They remain in the original frozen reports but are not used for this comparison.',
              '', '![Corridor and prior-regime comparison](corridor-comparison.png)','',
              '## Next engineering and research steps','',
              '1. Use an always-on collector or keep the host on power with its lid open. Rehearse sleep/network disruption explicitly; two sockets on one laptop do not address host failure.',
              '2. Enforce and monitor the absolute wall-clock end in the supervisor and collector after resume, while keeping original input deadlines unchanged. Add per-receiver staleness/reconnect alerts, supervisor heartbeats and sleep/wake evidence for future runs.',
              '3. Diagnose sustained disagreement separately from transport loss. Preserve conservative eligibility and define/approve any change before collecting more data.',
              '4. Develop a prior-information-only volatility-conditioned width model using chronological training, then freeze the complete formula, limits, payout/fee assumptions and regime evaluation plan for fresh data. Do not choose a new global width from the best-looking cells in this table.',
              '5. Validate full-ladder conditional survival and complete LP economics separately. No survival table, sample minimum or descriptive effective-size estimate authorizes a launch.',
              '', 'Files: `summary.json`, `windows.csv`, `corridor-comparison.csv`, `hourly.csv`, `gaps.json`, source hashes and code in `investigation-spec.json`. Regime groups can have small counts and serial dependence. No independent-trial confidence claim, hidden-price imputation, next candidate or production approval is made.']
    (output/'report.md').write_text('\n'.join(lines)+'\n')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--captures',nargs=2,type=Path,required=True,help='first calibration recording, then round-2 evaluation')
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--power-events',type=Path)
    args=parser.parse_args();output=args.output.resolve();output.mkdir(parents=True,exist_ok=True)
    if (output/'summary.json').exists():raise ValueError('output already has a retained investigation')
    spec=dict(analysis_type='post-hoc exploratory, no candidate selection',widths_ppm=list(WIDTHS),lookback_ms=LOOKBACK,
              regime_method='past-only five-minute log-return variation; thresholds from first 60% of first capture only',
              source_code_sha256={name:file_hash(Path(__file__).with_name(name)) for name in ['investigate_capture.py','capture_dataset.py','analyze_capture.py','prospective_capture.py']},
              power_events_sha256=file_hash(args.power_events) if args.power_events else None,
              power_events_path=str(args.power_events.resolve()) if args.power_events else None,
              capture_directories=[str(p.resolve()) for p in args.captures],
              next_candidate=None,production_approved=False)
    (output/'source').mkdir()
    for name in spec['source_code_sha256']:shutil.copyfile(Path(__file__).with_name(name),output/'source'/name)
    if args.power_events:shutil.copyfile(args.power_events,output/'power-events.txt')
    with (output/'investigation-spec.json').open('x') as f:json.dump(spec,f,indent=2);f.write('\n')
    events=power_events(args.power_events)
    runs=[analyze_run(p.resolve(),events) for p in args.captures]
    thresholds=regime_thresholds(runs[0]['rows']);all_comparison=[];all_hourly=[];all_windows=[]
    for run in runs:
        for row in run['rows']:row['regimes']=label(row,thresholds)
        run['comparison']=compare(run['rows'],WIDTHS)
        for value in run['comparison']:value['run']=run['name']
        run['hourly']=[];start=run['manifest']['frozen_at_ms']
        for hour in range(8):
            rows=[r for r in run['rows'] if start+hour*3600000<=r['start']<start+(hour+1)*3600000]
            good=[r for r in rows if r['valid']]
            item=dict(run=run['name'],hour=hour+1,start_wita=stamp(start+hour*3600000),completed_windows=len(rows),
                      healthy_windows=len(good),coverage=len(good)/len(rows),
                      survival_117=score(good,117)['survival'],survival_314=score(good,314)['survival'])
            run['hourly'].append(item)
        all_comparison.extend(run['comparison']);all_hourly.extend(run['hourly'])
        for row in run['rows']:
            record=dict(run=run['name'],start_wita=stamp(row['start']),**{k:row[k] for k in ('start','expiry','entry','move','valid')},
                        reasons=';'.join(row['reasons']),**row['regimes'])
            record.update(row['lag_features'] or {});all_windows.append(record)
    summary=dict(next_candidate=None,production_approved=False,regime_thresholds=thresholds,
                 runs=[dict(name=r['name'],source=r['source'],summary=r['summary'],retrospective_target_range=target_range([v for v in r['rows'] if v['valid']])) for r in runs])
    with (output/'summary.json').open('x') as f:json.dump(summary,f,indent=2);f.write('\n')
    with (output/'gaps.json').open('x') as f:
        json.dump({r['name']:dict(gaps=r['gaps'],stale_intervals=r['stale_intervals'],both_stale_intervals=r['both_stale_intervals'],errors=r['errors_in_horizon']) for r in runs},f,indent=2);f.write('\n')
    write_csv(output/'corridor-comparison.csv',all_comparison,['run','group_axis','group','width_ppm','windows','survived','survival'])
    write_csv(output/'hourly.csv',all_hourly,['run','hour','start_wita','completed_windows','healthy_windows','coverage','survival_117','survival_314'])
    write_csv(output/'windows.csv',all_windows,['run','start_wita','start','expiry','entry','move','valid','reasons','volatility','trend','jump','vol_bps','net_bps','efficiency','max_step_bps'])
    plots(runs,WIDTHS,output,events);report(runs,thresholds,WIDTHS,output,events)
    print(output/'report.md')
    print(json.dumps(summary,indent=2))

if __name__=='__main__':main()
