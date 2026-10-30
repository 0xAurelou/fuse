#!/usr/bin/env python3
"""Iterate payout pricing with chronological probability calibration and CDFs."""
import argparse
import gzip
import json
from pathlib import Path
import shutil
import time

import payout_risk
import research_payout_risk
from payout_risk import conditional_width, risk
from payout_empirical import (CONTROLS, PRIORS, SPEC, EmpiricalPredictor, calibrated,
    entry, fit_calibrator, fit_movement, out_of_fold, policies, selection_score)
from research_payout_risk import (ASSETS, FIELDS, MULTIPLIERS, digest, dump,
                                  grouped_metrics, load_parent, write_csv)

PLAN = dict(spec=SPEC, assets=ASSETS, multipliers=MULTIPLIERS,
            policies=policies(), diagnostic_controls=CONTROLS,
            parent_template='Reuse v1 selected feature family/ridge and final risk coefficients; v1 selection dates have already been inspected. Refit only OOF coefficient prefixes for calibration references.',
            coefficients='Movement CDFs and calibrators use pre-2026 data only; choose policy on January-May 2026; pin before June-October diagnostics',
            no_live_changes=True, no_capture=True, no_promotion=True,
            support='Maintain the preceding global >=20 positive-tail reference screen. No sampling or lower support threshold creates apparent availability.',
            interpretation='Repeated development selection; no independent holdout, prospective or net LP claim')


def inputs(parent, preceding):
    rows, baseline, binding = load_parent(parent)
    old = json.loads((preceding/'research.json').read_text())
    audit = json.loads((preceding/'audit.json').read_text())
    if not audit['passed'] or audit['research_sha256'] != digest(preceding/'research.json'):
        raise ValueError('matching preceding audit required')
    if old['protocol']['parent_sha256'] != digest(parent/'research.json'):
        raise ValueError('risk packet has a different source dataset')
    for module in (payout_risk,research_payout_risk):
        path=Path(module.__file__)
        if digest(path) != old['protocol']['source_sha256'][path.name]:
            raise ValueError('preceding implementation changed')
    templates={}
    for asset in ASSETS:
        directory=preceding/asset
        if digest(directory/'research.json') != old['research_sha256'][asset]:
            raise ValueError('preceding asset research differs')
        meta=json.loads((directory/'research.json').read_text())
        for name in ('models.json','selection.json'):
            if digest(directory/name) != meta['artifact_sha256'][name]:
                raise ValueError('preceding model/selection differs')
        templates[asset]=json.loads((directory/'models.json').read_text())
    binding.update(preceding_sha256=digest(preceding/'research.json'))
    return rows,baseline,templates,binding


def context(rows, packet):
    model=packet['risk']; raw=[]
    for r in rows:
        raw.append(risk(r,model) if r['adaptive_features'] is not None else (None,None))
    forecasts={prior:[calibrated(p,packet['calibrators'][str(prior)]) for p in raw] for prior in PRIORS}
    legacy={m:[conditional_width(r,dict(floor=p[1]),packet['v1_positive'],.95/m) for r,p in zip(rows,raw)] for m in MULTIPLIERS}
    return raw,forecasts,legacy,EmpiricalPredictor(packet['movement'])


def predict(rows, baseline, packet, multiplier, policy, ctx):
    raw,forecasts,legacy,predictor=ctx
    return [entry(r,multiplier,policy,raw[i],{prior:v[i] for prior,v in forecasts.items()},
                  baseline[multiplier][r['start']],legacy[multiplier][i],predictor) for i,r in enumerate(rows)]


def select(rows, baseline, packet):
    validation=[r for r in rows if r['split']=='validation']
    ctx=context(validation,packet)
    result={}
    for multiplier in MULTIPLIERS:
        rankings=[]; baseline_loss=None
        for index, policy in enumerate(policies()):
            records=predict(validation,baseline,packet,multiplier,policy,ctx)
            score=selection_score(validation,records,multiplier,baseline_loss)
            if index==0:baseline_loss=score['full_reference_pinball_ppm']
            rankings.append(dict(policy=policy,index=index,**score))
        rankings.sort(key=lambda r:(r['score'],r['index']))
        result[str(multiplier)]=dict(policy=rankings[0]['policy'],ranking=rankings,
                                     any_meets_availability_reference=any(r['meets_availability_reference'] for r in rankings))
    return result


def study_asset(asset, rows, baseline, preceding, output):
    directory=output/asset;directory.mkdir()
    template=preceding['candidates'][preceding['selected']]
    fold_models,oof=out_of_fold(rows,template)
    calibrators={str(prior):fit_calibrator(oof,prior) for prior in PRIORS}
    movement=fit_movement(rows,asset)
    packet=dict(asset=asset,risk=template,v1_positive=preceding['positive'],
                fold_models=fold_models,calibrators=calibrators,movement=movement,spec=SPEC)
    dump(directory/'models.json',packet)
    with gzip.open(directory/'oof.jsonl.gz','wt',compresslevel=5) as stream:
        for p in oof:stream.write(json.dumps(p,separators=(',',':'),allow_nan=False)+'\n')
    choices=select(rows,baseline,packet)
    dump(directory/'selection.json',choices)
    pinned={n:digest(directory/n) for n in ('models.json','oof.jsonl.gz','selection.json')}
    later=[r for r in rows if r['split']!='train'];ctx=context(later,packet)
    metrics=[]
    with gzip.open(directory/'predictions.jsonl.gz','wt',compresslevel=5) as stream:
        for multiplier in MULTIPLIERS:
            comparison=[(n,dict(name=n,kind='control')) for n in CONTROLS]
            comparison.append(('selected_policy',choices[str(multiplier)]['policy']))
            for variant,policy in comparison:
                records=predict(later,baseline,packet,multiplier,policy,ctx)
                metrics.extend(grouped_metrics(asset,later,records,multiplier,variant))
                for i,(r,p) in enumerate(zip(later,records)):
                    stream.write(json.dumps(dict(asset=asset,multiplier=multiplier,variant=variant,
                        policy=policy['name'],start=r['start'],period=r['period'],split=r['split'],
                        raw_p0=ctx[0][i][0],raw_floor=ctx[0][i][1],**p),separators=(',',':'),allow_nan=False)+'\n')
            print(json.dumps(dict(asset=asset,multiplier=multiplier,selected=choices[str(multiplier)]['policy']['name'])),flush=True)
    for name,sha in pinned.items():
        if digest(directory/name)!=sha:raise ValueError('choice or fitted model changed during diagnostics')
    write_csv(directory/'metrics.csv',metrics,FIELDS)
    primary=[r for r in metrics if r['period']=='pooled' and r['split']=='test' and r['axis']=='overall']
    daily=[r for r in metrics if r['period']!='pooled' and r['split']=='test' and r['axis']=='overall']
    report=dict(asset=asset,selected={m:r['policy'] for m,r in choices.items()},
                selection_scores={m:r['ranking'][0] for m,r in choices.items()},
                oof_rows=len(oof),oof_periods=sorted({r['period'] for r in oof}),
                primary_test=primary,daily_test=daily,
                artifact_sha256={p.name:digest(p) for p in directory.iterdir()},
                no_promotion=True,live_policy_changed=False)
    dump(directory/'research.json',report)
    return report


def declare(parent, preceding, output):
    if output.exists():raise ValueError('preserve earlier experiments; use a new directory')
    output.mkdir(parents=True);(output/'source').mkdir()
    names=('payout_empirical.py','research_payout_empirical.py','payout_risk.py','research_payout_risk.py')
    hashes={}
    for name in names:
        path=Path(__file__).with_name(name);shutil.copyfile(path,output/'source'/name);hashes[name]=digest(path)
    protocol=dict(PLAN,parent=str(parent.resolve()),preceding=str(preceding.resolve()),
                  parent_sha256=digest(parent/'research.json'),preceding_sha256=digest(preceding/'research.json'),
                  source_sha256=hashes)
    dump(output/'protocol.json',protocol)
    return protocol


def run(parent,preceding,output):
    start=time.monotonic();protocol=json.loads((output/'protocol.json').read_text())
    for name,sha in protocol['source_sha256'].items():
        if digest(Path(__file__).with_name(name))!=sha or digest(output/'source'/name)!=sha:
            raise ValueError('source changed after declaration')
    if digest(parent/'research.json')!=protocol['parent_sha256'] or digest(preceding/'research.json')!=protocol['preceding_sha256']:
        raise ValueError('source packet changed')
    rows,baseline,templates,bindings=inputs(parent,preceding)
    results=[study_asset(a,rows[a],baseline[a],templates[a],output) for a in ASSETS]
    result=dict(protocol=protocol,protocol_sha256=digest(output/'protocol.json'),bindings=bindings,
                assets=results,research_sha256={a:digest(output/a/'research.json') for a in ASSETS},
                elapsed_seconds=time.monotonic()-start,no_promotion=True,live_policy_changed=False)
    dump(output/'research.json',result)
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--parent',type=Path,required=True);parser.add_argument('--preceding',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True);parser.add_argument('--declare',action='store_true')
    args=parser.parse_args()
    r=declare(args.parent,args.preceding,args.output) if args.declare else run(args.parent,args.preceding,args.output)
    print(json.dumps(dict(output=str(args.output),completed='elapsed_seconds' in r)))
