"""Verified receipt recordings as calibration data, preserving their provenance."""
import hashlib
import json
from pathlib import Path
import subprocess
import time

from analyze_capture import windows

FORMAT = 'oracle-receipts-v1'


def file_hash(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(1<<20),b''):
            h.update(block)
    return h.hexdigest()


def load_capture(directory):
    directory=Path(directory).resolve()
    # The recorder acquires its writer lock while verifying. An active stream
    # cannot be silently included in a fitted dataset.
    binary=directory/'fuse-capture'
    spec=json.loads((directory/'analysis-spec.json').read_text())
    if file_hash(binary)!=spec['files_sha256']['fuse-capture']:
        raise ValueError('capture verifier differs from its frozen executable')
    verified=json.loads(subprocess.check_output([str(binary),'-verify','-output',str(directory)],text=True))
    manifest,head=verified['manifest'],verified['head']
    status=json.loads((directory/'status.json').read_text())
    end=manifest['frozen_at_ms']+manifest['duration_ms']
    if status['state']!='completed' or end>time.time_ns()//1_000_000:
        raise ValueError('calibration requires a completed fixed-horizon recording')
    if status['sequence']!=head['sequence'] or status['last_receipt_hash']!=head['hash'] or head['sequence']==0:
        raise ValueError('capture completion status differs from verified receipts')
    if manifest['policy']['duration_ms']!=30000:
        raise ValueError('only 30-second windows are supported')
    rows=[];count=0;last=None;digest=hashlib.sha256()
    def receipts():
        nonlocal last
        with (directory/'receipts.jsonl').open('rb') as stream:
            for line in stream:
                digest.update(line);last=json.loads(line);yield last
    for row in windows(receipts(),manifest['policy'],manifest['frozen_at_ms'],end):
        count+=1
        if row['valid']:
            rows.append({'start':row['start'],'expiry':row['expiry'],'entry':row['entry'],
                         'max_move_units':row['move'],'run':directory.name})
    if last is None or last['hash']!=head['hash'] or last['sequence']!=head['sequence']:
        raise ValueError('capture changed after native verification')
    source={'path':str(directory),'format':FORMAT,'file':'receipts.jsonl',
            'sha256':digest.hexdigest(),'manifest_sha256':file_hash(directory/'manifest.json'),
            'verifier_sha256':file_hash(binary),'receipt_hash':head['hash'],
            'receipts':head['sequence'],'windows':len(rows),'completed_windows':count,
            'censored_windows':count-len(rows),'collection_end_ms':end,
            'previous_width_ppm':manifest['policy']['model'].get('base_width_ppm'),
            'data_role':'Previous prospective evaluation reused as retrospective calibration data; no longer a fresh holdout for this candidate.'}
    return rows,source,manifest


def validate_source(source):
    """Recheck the exact fitted recording immediately before a new freeze."""
    if source.get('format')!=FORMAT:
        raise ValueError('unsupported calibration source format')
    _,actual,_=load_capture(source['path'])
    for key in ('sha256','manifest_sha256','verifier_sha256','receipt_hash','receipts',
                'windows','completed_windows','censored_windows','collection_end_ms'):
        if actual[key]!=source.get(key):
            raise ValueError(f'fitted capture changed: {key}')
    return actual['collection_end_ms'],actual
