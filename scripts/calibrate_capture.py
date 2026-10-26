#!/usr/bin/env python3
"""Fit a new fixed-width research candidate from completed, verified captures.

Uses the first 60% of eligible chronological windows only to choose the width.
The remaining 20/20% are retrospective diagnostics; fresh prospective evidence
must come from a new recording after the candidate is frozen.
"""
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import time

from capture_dataset import load_capture, file_hash
from calibrate_pricing import choose_width, survival, survival_frontier, wilson


def fit_candidate(rows, maximum):
    eligible=[]
    for row in sorted(rows,key=lambda r:(r['start'],r['expiry'])):
        if not eligible or row['start']>=eligible[-1]['expiry']:
            eligible.append(row)
    if len(eligible)<6:
        raise ValueError('at least six complete eligible windows required')
    a=max(1,int(len(eligible)*.6));b=max(a+1,int(len(eligible)*.8))
    splits={'train':eligible[:a],'validation':eligible[a:b],'test':eligible[b:]}
    frontier=survival_frontier(splits['train'],maximum=maximum)
    width=choose_width(frontier,.48)['width_ppm']
    selected={'target_survival':.48,'width_ppm':width}
    for name,part in splits.items():
        selected[name+'_survival']=survival(part,width)
    test=splits['test']
    selected['test_95pct_interval']=wilson(sum(r['max_move_units']<r['entry']*width//1000000 for r in test),len(test))
    return {'counts':{k:len(v) for k,v in splits.items()},'selected':selected,
            'split':'Chronological 60/20/20; nonoverlapping complete healthy 30s windows; width selected only on first 60%. Remaining splits are retrospective diagnostics, not a new prospective holdout.',
            'split_ranges':{k:{'start_ms':v[0]['start'],'end_ms':v[-1]['expiry']} for k,v in splits.items()},
            'eligible_windows':len(eligible),'purged_overlapping_windows':len(rows)-len(eligible),
            'optimizer':{'method':'exact integer survival frontier; closest empirical training survival to 48%, then narrowest width',
                         'maximum_width_ppm':maximum,'frontier_points':len(frontier)},
            'production_approved':False,'fresh_prospective_validation':False,
            'minimum_sample_gate_passed':len(splits['train'])>=200 and len(splits['validation'])>=100 and len(test)>=100,
            'limits':'Correlated retrospective observations from previously evaluated captures. Reuse is calibration, not fresh holdout evidence. First-stage reference windows do not validate conditional ladder survival, trading demand, costs or profitability.'}


def recalibrate(captures,output):
    if output.exists():
        raise ValueError('output already exists; never overwrite a retained calibration')
    rows=[];sources=[];base=None;seen=set()
    for directory in captures:
        directory=directory.resolve()
        if directory in seen:
            raise ValueError('duplicate source capture')
        seen.add(directory)
        data,source,manifest=load_capture(directory)
        policy=manifest['policy']
        if base is not None and any(policy[key]!=base[key] for key in ('duration_ms','max_gap_ms','disagreement_ms','void_delay_ms','gap_rule','admission')):
            raise ValueError('source captures have different oracle/window policies')
        base=deepcopy(policy);rows.extend(data);sources.append(source)
    if base is None:
        raise ValueError('at least one completed capture required')
    report=fit_candidate(rows,base['model']['max_width_bps']*100)
    report.update(dataset=sources,window_ms=30000,
                  training_data_role='Completed prior captures now used for retrospective calibration.',
                  source_code_sha256={name:file_hash(Path(__file__).with_name(name)) for name in ('calibrate_capture.py','capture_dataset.py','calibrate_pricing.py','analyze_capture.py')})
    dataset_hash=hashlib.sha256(json.dumps({'dataset':sources,'split':report['split'],'method':report['optimizer'],'target_survival':.48},sort_keys=True).encode()).hexdigest()
    selected=report['selected']
    base['version']='capture-calibration-'+dataset_hash[:12]
    base['mode']='paper'
    base['model'].update(version=base['version'],dataset='verified receipt captures '+dataset_hash,
                         training_window=str(report['counts'])+'; retrospective chronological 60/20/20',
                         out_of_sample_error=f"Retrospective diagnostics only: validation survival {selected['validation_survival']:.4f}; test {selected['test_survival']:.4f}; n={report['counts']['test']}; descriptive interval {selected['test_95pct_interval']}; new prospective holdout required",
                         base_width_bps=0,base_width_ppm=selected['width_ppm'],control_width_bps=0,
                         volatility_factor=0,valid_until=time.time_ns()//1000000+86400000)
    output.mkdir(parents=True)
    for name,value in [('calibration.json',report),('policy.json',base)]:
        with (output/name).open('x') as stream:json.dump(value,stream,indent=2);stream.write('\n')
    text=['# Recalibrated receipt-based research candidate','',
          f"Selected corridor half-width: **{selected['width_ppm']} ppm ({selected['width_ppm']/100:.2f} bps)**. Target: 48% first-stage reference-window survival.",'',
          '| Retrospective split | Eligible windows | Survival |','| --- | ---: | ---: |']
    for name,count in report['counts'].items():text.append(f"| {name} | {count} | {selected[name+'_survival']:.2%} |")
    text+=['',report['split'],'',report['limits'],'',
           'The previous candidate evaluation remains unchanged. These observations are now calibration data for the new candidate. A separately frozen new capture is required for prospective evaluation; production approval remains false.']
    with (output/'report.md').open('x') as stream:stream.write('\n'.join(text)+'\n')
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--captures',type=Path,nargs='+',required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    report=recalibrate(args.captures,args.output)
    print(json.dumps({'output':str(args.output),'counts':report['counts'],'selected':report['selected'],'production_approved':False},indent=2))

if __name__=='__main__':main()
