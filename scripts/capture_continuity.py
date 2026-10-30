#!/usr/bin/env python3
"""Read-only receiver-timestamp continuity on a bounded active receipt prefix.

No oracle/mark fields, widths, survival labels, fitting or capture control.
Linkage checks are not native receipt-digest verification or oracle agreement.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import time

from capture_dataset import file_hash
from capture_policy_equivalence import compare_policy
from prospective_capture_v2 import verify_artifacts,status_report

GRID=30000


def intervals(times,start,until,max_gap):
    """Closed millisecond spans of missing/stale prior receiver state.

    Arrival at the right endpoint refreshes only after the prior-state check.
    Window entry and expiry health therefore both include that endpoint.
    """
    if not times:return [(start,until)]
    spans=[(start,times[0])]
    spans.extend((a+max_gap+1,b) for a,b in zip(times,times[1:]) if b-a>max_gap)
    if until-times[-1]>max_gap:spans.append((times[-1]+max_gap+1,until))
    return spans


def metadata(rows,start,end,now,max_gap):
    if end<=start or (end-start)%GRID or now<start or max_gap<=0:
        raise ValueError('invalid original horizon, observer clock or freshness rule')
    until=min(now,end);feeds={'a':[],'b':[]};previous=None;genesis=None;last=start;count=0
    for r in rows:
        count+=1;at=r['at'];digest=r['hash'];source=r['source']
        if count==1:
            genesis=r['previous_hash']
            if not isinstance(genesis,str) or len(genesis)!=64 or any(c not in '0123456789abcdef' for c in genesis):
                raise ValueError('invalid prefix genesis hash format')
            previous=genesis
        if (type(r['sequence']) is not int or r['sequence']!=count or r['previous_hash']!=previous
                or type(at) is not int or not start<at<end or at<last or at>now or source not in feeds
                or not isinstance(digest,str) or len(digest)!=64 or any(c not in '0123456789abcdef' for c in digest)):
            raise ValueError('invalid prefix linkage, time or receiver at sequence '+str(count))
        previous=digest;last=at;feeds[source].append(at)
    completed=min((until-start)//GRID,(end-start)//GRID);planned=(end-start)//GRID
    summaries={};all_spans=[]
    for source,times in feeds.items():
        spans=intervals(times,start,until,max_gap);all_spans.extend(spans)
        gaps=[dict(before_ms=a,after_ms=b,gap_ms=b-a,stale_ms=b-a-max_gap)
            for a,b in zip(times,times[1:]) if b-a>max_gap]
        age=now-times[-1] if times else None
        horizon_age=until-times[-1] if times else None
        summaries[source]=dict(receipts=len(times),first_receipt_ms=times[0] if times else None,
            last_receipt_ms=times[-1] if times else None,age_at_snapshot_ms=age,
            age_at_observed_horizon_ms=horizon_age,
            fresh_at_snapshot=age is not None and 0<=age<=max_gap,
            maximum_interreceipt_gap_ms=max((b-a for a,b in zip(times,times[1:])),default=None),
            completed_interreceipt_gaps_over_limit=gaps,
            open_stale_span=spans[-1] if not times or until-times[-1]>max_gap else None)
    affected=[i for i in range(completed)
        if any(left<=start+(i+1)*GRID and right>=start+i*GRID for left,right in all_spans)]
    missed=len(affected)
    return dict(snapshot_at_ms=now,observed_horizon_end_ms=until,planned_end_ms=end,
        elapsed_complete_grid_windows=completed,planned_grid_windows=planned,
        freshness_affected_complete_windows=missed,freshness_affected_grid_indices=affected,
        elapsed_healthy_fraction_upper_bound=(completed-missed)/completed if completed else None,
        best_possible_final_healthy_fraction_upper_bound=(planned-missed)/planned,
        receivers=summaries,prefix_sequence=count,prefix_last_hash=previous,prefix_genesis_hash=genesis,
        prefix_last_receipt_ms=last if count else None,
        prefix_linkage_checked=True,native_genesis_hash_verified=False,native_receipt_digests_verified=False,
        oracle_agreement_assessed=False,price_fields_used=False,pricing_outcomes_evaluated=False,
        interpretation='Receiver absence/staleness is a necessary health failure. Rates are upper bounds, not observed healthy outcomes: price agreement, digest validity and other censorship are not assessed. Final native verification and frozen analysis remain required.')


def inspect(directory):
    directory=directory.resolve();spec=verify_artifacts(directory)
    manifest=json.loads((directory/'manifest.json').read_text())
    policy=json.loads((directory/'frozen-policy.json').read_text())
    comparison=compare_policy(manifest['policy'],policy)
    if manifest['duration_ms']!=spec['duration_hours']*3600000:
        raise ValueError('native manifest differs from frozen plan')
    start=manifest['frozen_at_ms'];end=start+manifest['duration_ms'];path=directory/'receipts.jsonl'
    # Fix the byte horizon before reading. Never follow an actively growing EOF
    # or acquire the native writer lock; ignore a possible incomplete final line.
    digest=hashlib.sha256();counts=dict(read=0,complete=0)
    manifest_digest=file_hash(directory/'manifest.json')
    with path.open('rb') as stream:
        original=os.fstat(stream.fileno());size=original.st_size
        snapshot=time.time_ns()//1000000
        def records():
            remaining=size
            while remaining:
                line=stream.readline(remaining)
                if not line:raise ValueError('receipt prefix shrank during read')
                remaining-=len(line);counts['read']+=len(line)
                if not line.endswith(b'\n'):
                    if remaining:raise ValueError('receipt prefix shrank during read')
                    return
                digest.update(line);counts['complete']+=len(line)
                yield json.loads(line)
        result=metadata(records(),start,end,snapshot,policy['max_gap_ms'])
        current=path.stat()
        if (current.st_dev,current.st_ino)!=(original.st_dev,original.st_ino):
            raise ValueError('receipt path replaced during read')
    if file_hash(directory/'manifest.json')!=manifest_digest:raise ValueError('manifest changed during observation')
    verify_artifacts(directory)
    result.update(directory=str(directory),manifest_sha256=file_hash(directory/'manifest.json'),
        analysis_spec_sha256=file_hash(directory/'analysis-spec.json'),
        prefix_complete_bytes=counts['complete'],prefix_sha256=digest.hexdigest(),
        snapshot_read_bytes=counts['read'],partial_tail_bytes=counts['read']-counts['complete'],
        observer_source_sha256=file_hash(Path(__file__)),frozen_files_verified=len(spec['files_sha256']),
        policy_comparison=comparison,
        declared_minimum_full_horizon_coverage=spec['minimum_full_horizon_coverage'],
        coverage_still_possible_from_freshness_bound=result['best_possible_final_healthy_fraction_upper_bound']>=spec['minimum_full_horizon_coverage'],
        current_supervisor_status=status_report(directory))
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--directory',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);a=p.parse_args();r=inspect(a.directory)
    with a.output.open('x') as stream:json.dump(r,stream,indent=2);stream.write('\n')
    print(json.dumps({k:r[k] for k in ('prefix_sequence','elapsed_complete_grid_windows',
        'freshness_affected_complete_windows','elapsed_healthy_fraction_upper_bound',
        'best_possible_final_healthy_fraction_upper_bound','coverage_still_possible_from_freshness_bound')},indent=2))
