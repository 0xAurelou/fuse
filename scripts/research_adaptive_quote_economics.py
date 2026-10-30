#!/usr/bin/env python3
"""Selection-sensitive 2x economics on already archived adaptive quote tapes."""
import argparse
from collections import defaultdict
from datetime import datetime,timezone
import gzip
import json
from pathlib import Path
import shutil

from adaptive_quote_economics import SPEC,evaluate
from capture_dataset import file_hash
from prospective_capture_v2 import write_new
from research_startup_admission import verify_code

ROOT=Path(__file__).resolve().parent.parent
CANDIDATES=('market:priceable_open','retained_open','timing:priceable_open')
SOURCES=('adaptive_quote_economics.py','research_adaptive_quote_economics.py','test_adaptive_quote_economics.py')


def binding(archive):
    research=json.loads((archive/'research.json').read_text());verify_code(archive,research)
    audit=json.loads((archive/'audit.json').read_text())
    if not audit['completed'] or audit['research_sha256']!=file_hash(archive/'research.json'):
        raise ValueError('completed matching pricing audit required')
    names={'later-predictions.jsonl.gz':research['later_predictions_sha256']}
    names.update({f'selection-predictions-{begin}.jsonl.gz':digest for begin,digest in research['selection_prediction_sha256'].items()})
    for name,digest in names.items():
        if file_hash(archive/name)!=digest:raise ValueError('archived prediction file changed: '+name)
    return research,names


def read_sessions(archive,names):
    sessions=defaultdict(list)
    for name in sorted(names):
        with gzip.open(archive/name,'rt') as f:
            for line in f:
                r=json.loads(line)
                if r['candidate'] not in CANDIDATES:continue
                key=(name,r['candidate'],r['session']);sessions[key].append(r)
    return sessions


def compute(sessions):
    cases=[];traces=[]
    for (tape,candidate,session),rows in sorted(sessions.items()):
        parts=session.split(':');source,day,mode=parts[:3]
        if mode not in ('continuous','restart') or source not in ('raw_temporal','normalized_temporal'):
            raise ValueError('unsupported archived session')
        origin=int(datetime.fromisoformat(day).replace(tzinfo=timezone.utc).timestamp()*1000)
        expected=2880 if mode=='continuous' else 960
        if len(rows)!=expected:raise ValueError('incomplete historical session')
        result,chosen=evaluate(rows,origin)
        header=dict(tape=tape,candidate=candidate,session=session,source=source,period=day,mode=mode,
                    data_role='later_development' if tape.startswith('later') else 'earlier_selection_development')
        cases.extend(dict(header,**r) for r in result)
        traces.extend(dict(header,**d) for d in chosen)
    return cases,traces


def run(archive,output):
    archive=archive.resolve();output=output.resolve();research,names=binding(archive)
    if output.exists():raise ValueError('preserve previous economics results')
    output.mkdir(parents=True);(output/'source').mkdir()
    sources={name:file_hash(ROOT/'scripts'/name) for name in SOURCES}
    for name in SOURCES:shutil.copyfile(ROOT/'scripts'/name,output/'source'/name)
    protocol=dict(archive=str(archive),archive_research_sha256=file_hash(archive/'research.json'),
        archive_audit_sha256=file_hash(archive/'audit.json'),prediction_files_sha256=names,
        source_sha256=sources,spec=SPEC,candidates=CANDIDATES,
        pricing_refitted=False,current_prospective_receipts_used=False,prospective_evidence=False,
        existing_calibration_selection_not_changed=True,primary_candidate=research['selected'])
    write_new(output/'protocol.json',protocol)
    cases,traces=compute(read_sessions(archive,names))
    with gzip.open(output/'entry-decisions.jsonl.gz','xt',compresslevel=5) as f:
        for r in traces:f.write(json.dumps(r,allow_nan=False)+'\n')
    with (output/'cases.jsonl').open('x') as f:
        for r in cases:f.write(json.dumps(r,allow_nan=False)+'\n')
    for name,digest in names.items():
        if file_hash(archive/name)!=digest:raise ValueError('prediction tape changed during economics replay')
    for name,digest in sources.items():
        if file_hash(ROOT/'scripts'/name)!=digest:raise ValueError('economics source changed during replay')
    summary=dict(protocol,completed=True,protocol_sha256=file_hash(output/'protocol.json'),
        cases_sha256=file_hash(output/'cases.jsonl'),entry_decisions_sha256=file_hash(output/'entry-decisions.jsonl.gz'),
        eight_hour_cases=len(cases),quote_decision_rows=len(traces),independent_holdout=False,
        interpretation='All declared outcomes are development diagnostics. Entry selection is causal given the archived quote tape; it does not make the already selected pricing models or historical sample independent. No actual liquidity, recovery budget, reserve fee or product economics validation follows.',
        production_approved=False,economics_validated=False,goal_complete=False)
    write_new(output/'research.json',summary)
    print(json.dumps(dict(completed=True,eight_hour_cases=len(cases),quote_decision_rows=len(traces)),indent=2))
    return summary


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--archive',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);a=p.parse_args();run(a.archive,a.output)
