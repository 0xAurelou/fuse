#!/usr/bin/env python3
"""Pin September/October raw comparisons before expanding the temporal study."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
from urllib.parse import urlencode

from capture_dataset import file_hash
import fetch_flat_samples
from research_startup_admission import verify_code

DAYS=('2026-09-01','2026-10-01')
PLAN=dict(folds=[dict(training_days=14,scoring_indices=[14,17]),
                 dict(training_days=17,scoring_indices=[17,20]),
                 dict(training_days=20,scoring_indices=[20,22])],
          later_indices=[22,24],stages=['fixed_retained','expanding_raw_core'],
          policies=['previous_floor_53','warm6_floor12','warm6_floor30','warm12_floor30','no_pause'],
          target=.48,band=[.43,.53],availability=dict(overall=.85,populated_frozen=.50),
          score='Same full-state score, phase charge, availability charges and full-reference loss guards as the preceding full raw comparison',
          late_raw_role='Later diagnostics only; no model or guard selection from September/October raw outcomes',
          initial_raw_replacements='Eight existing earlier full raw dates plus complete retained January/August 2026; only dates before each cutoff can train')


def prepare(previous,output):
    if output.exists():raise ValueError('preserve prior downloads; fetch resumes the pinned list')
    result=json.loads((previous/'research.json').read_text());verify_code(previous,result)
    panels=[];requests=[]
    for day in DAYS:
        origin=int(datetime.fromisoformat(day).replace(tzinfo=timezone.utc).timestamp()*1000)
        panels.append(dict(day=day,start=origin,end=origin+86400000,fetch_start=origin,fetch_end=origin+86400000,
                           selection='Complete later raw sample day; fixed before download; not outcome-selected intervals'))
        for offset in range(1440):
            query=urlencode({'from':day+'T00:00:00.000Z','offset':offset,
                             'filters':json.dumps([dict(channel='activeAssetCtx',symbols=['BTC'])],separators=(',',':'))})
            requests.append(dict(day=day,at_ms=origin+offset*60000,path=f'{day}/{offset:04d}.bin',
                                 url='https://api.tardis.dev/v1/data-feeds/hyperliquid?'+query))
    protocol=dict(previous=str(previous.resolve()),previous_sha256=file_hash(previous/'research.json'),plan=PLAN,
        panels=panels,requests=requests,authentication='none',maximum_bytes_per_response=200000,workers=8,
        source_sha256=file_hash(Path(fetch_flat_samples.__file__)),preparer_sha256=file_hash(Path(__file__)),
        documentation='https://docs.tardis.dev/api/http-api-reference',
        source_role='New raw coverage on previously inspected normalized development dates; not native receipts or independent calendar-date holdouts',
        capture_started=False,live_candidate_promoted=False)
    output.mkdir(parents=True)
    (output/'download-protocol.json').write_text(json.dumps(protocol,indent=2)+'\n')
    shutil.copyfile(Path(fetch_flat_samples.__file__),output/'fetch-source.py')
    shutil.copyfile(Path(__file__),output/'prepare-source.py')
    return dict(days=DAYS,requests=len(requests),output=str(output))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--previous',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    args=p.parse_args();print(json.dumps(prepare(args.previous,args.output),indent=2))
