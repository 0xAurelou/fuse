"""Append-only, hash-linked market receipts with recoverable compressed segments."""
import gzip
import hashlib
import json
import os
from pathlib import Path
import time
import uuid


def canonical(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()


def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(1048576),b''):h.update(block)
    return h.hexdigest()


def atomic(path, value):
    temp=path.with_name(path.name+'.tmp')
    with temp.open('w') as stream:
        json.dump(value,stream,indent=2,allow_nan=False);stream.write('\n');stream.flush();os.fsync(stream.fileno())
    temp.replace(path)


def check_row(raw, sequence, previous):
    saved=json.loads(raw)
    if saved['sequence']!=sequence+1 or saved['previous_hash']!=previous:
        raise ValueError('receipt sequence or previous hash differs')
    value={k:v for k,v in saved.items() if k!='hash'}
    if set(value)!={'sequence','previous_hash','record'} or hashlib.sha256(canonical(value)).hexdigest()!=saved['hash']:
        raise ValueError('receipt digest differs')
    return saved['sequence'],saved['hash']


class Archive:
    def __init__(self, root, genesis, session, segment_seconds=300):
        self.root=Path(root);self.genesis=genesis;self.session=session
        self.segment_seconds=segment_seconds;self.sequence=0;self.head=genesis
        self.stream=None;self.path=None;self.segment_start_ns=0;self.last_flush=0
        self.index=self.root/'segments.jsonl';self.segments=[];self.recoveries=[]
        self._load_index()
        self._recover()

    def _load_index(self):
        if not self.index.exists():return
        raw=self.index.read_bytes();lines=raw.splitlines(keepends=True)
        if lines and not lines[-1].endswith(b'\n'):
            # A process can die during the index append. Preserve that exact tail.
            recovery=self.root/'recovery';recovery.mkdir(exist_ok=True)
            (recovery/('index-'+uuid.uuid4().hex+'.tail')).write_bytes(lines.pop())
            with self.index.open('r+b') as stream:
                stream.truncate(sum(map(len,lines)));stream.flush();os.fsync(stream.fileno())
        previous=self.genesis
        for line in lines:
            entry=json.loads(line);digest=entry.pop('index_hash')
            if entry['previous_index_hash']!=previous or hashlib.sha256(canonical(entry)).hexdigest()!=digest:
                raise ValueError('segment index digest differs')
            path=self.root/entry['path']
            if not path.resolve().is_relative_to(self.root.resolve()):raise ValueError('archive path escapes root')
            if entry['first_sequence']!=self.sequence+1 or entry['first_previous_hash']!=self.head or sha(path)!=entry['sha256']:
                raise ValueError('segment file binding or sequence differs')
            if entry['last_sequence']<entry['first_sequence'] or entry['records']!=entry['last_sequence']-entry['first_sequence']+1:
                raise ValueError('segment count differs')
            entry['index_hash']=digest;self.segments.append(entry)
            self.sequence,self.head=entry['last_sequence'],entry['last_hash'];previous=digest

    def _recover(self):
        indexed={e['path'] for e in self.segments}
        for path in sorted(self.root.glob('data/*/*.open')):
            compressed=path.with_suffix('.jsonl.gz')
            relative=str(compressed.relative_to(self.root))
            if relative in indexed:
                # Committed gzip/index survived but cleanup did not.
                match=next(e for e in self.segments if e['path']==relative)
                if sha(path)!=match['uncompressed_sha256']:raise ValueError('committed raw duplicate differs')
                path.unlink();continue
            # Only the last receipt may be incomplete. Never silently skip a bad complete row.
            data=path.read_bytes();lines=data.splitlines(keepends=True)
            tail=lines.pop() if lines and not lines[-1].endswith(b'\n') else b''
            sequence,head=self.sequence,self.head
            for line in lines:sequence,head=check_row(line,sequence,head)
            if tail:
                recovery=self.root/'recovery';recovery.mkdir(exist_ok=True)
                retained=recovery/(path.name+'.'+uuid.uuid4().hex+'.interrupted')
                path.replace(retained)
                with path.open('xb') as stream:stream.write(b''.join(lines));stream.flush();os.fsync(stream.fileno())
                self.recoveries.append(dict(path=str(retained.relative_to(self.root)),partial_tail_bytes=len(tail)))
            if not lines:path.unlink();continue
            first=self.sequence+1;previous=self.head;self.sequence,self.head=sequence,head
            self._commit(path,first,previous,len(lines))
        unexpected=[p for p in self.root.glob('data/*/*.jsonl.gz') if str(p.relative_to(self.root)) not in {e['path'] for e in self.segments}]
        if unexpected:raise ValueError('unindexed compressed segment without recoverable raw file')

    def append(self, record):
        at_ns=record['received_at_ns']
        if self.stream and (at_ns-self.segment_start_ns>=self.segment_seconds*10**9 or at_ns<self.segment_start_ns):self.rotate()
        if self.stream is None:
            from datetime import datetime,timezone
            stamp=datetime.fromtimestamp(at_ns/10**9,timezone.utc)
            folder=self.root/'data'/stamp.strftime('%Y-%m-%d');folder.mkdir(parents=True,exist_ok=True)
            self.path=folder/(stamp.strftime('%H%M%S')+'-'+self.session[:12]+f'-{self.sequence+1:012}.open')
            self.stream=self.path.open('xb');self.segment_start_ns=at_ns
            self.first_sequence=self.sequence+1;self.first_previous=self.head;self.segment_records=0
        row=dict(sequence=self.sequence+1,previous_hash=self.head,record=record)
        digest=hashlib.sha256(canonical(row)).hexdigest();row['hash']=digest
        self.stream.write(canonical(row)+b'\n')
        self.sequence+=1;self.head=digest;self.segment_records+=1
        if time.monotonic()-self.last_flush>=5:self.flush()

    def flush(self):
        if self.stream:self.stream.flush();os.fsync(self.stream.fileno())
        self.last_flush=time.monotonic()

    def _commit(self, raw, first, previous, count):
        destination=raw.with_suffix('.jsonl.gz');temp=raw.with_suffix('.gz.tmp')
        raw_sha=sha(raw)
        if destination.exists():
            with gzip.open(destination,'rb') as stream:
                h=hashlib.sha256()
                for block in iter(lambda:stream.read(1048576),b''):h.update(block)
            if h.hexdigest()!=raw_sha:raise ValueError('uncommitted gzip differs from recoverable raw receipts')
        else:
            with raw.open('rb') as source, temp.open('wb') as target:
                with gzip.GzipFile(filename='',fileobj=target,mode='wb',compresslevel=3,mtime=0) as zipped:
                    for block in iter(lambda:source.read(1048576),b''):zipped.write(block)
                target.flush();os.fsync(target.fileno())
            temp.replace(destination)
        entry=dict(path=str(destination.relative_to(self.root)),sha256=sha(destination),
            uncompressed_sha256=raw_sha,compressed_bytes=destination.stat().st_size,
            first_sequence=first,first_previous_hash=previous,last_sequence=self.sequence,
            last_hash=self.head,records=count,closed_at_ms=time.time_ns()//1000000,
            previous_index_hash=self.segments[-1]['index_hash'] if self.segments else self.genesis)
        entry['index_hash']=hashlib.sha256(canonical(entry)).hexdigest()
        with self.index.open('ab') as stream:stream.write(canonical(entry)+b'\n');stream.flush();os.fsync(stream.fileno())
        self.segments.append(entry);raw.unlink()

    def rotate(self):
        if self.stream is None:return
        self.flush();self.stream.close();self.stream=None
        self._commit(self.path,self.first_sequence,self.first_previous,self.segment_records)
        self.path=None

    def bytes_written(self):
        return sum(e['compressed_bytes'] for e in self.segments)+(self.path.stat().st_size if self.path and self.path.exists() else 0)


def verify(root, genesis, include_open=False):
    """Read-only full replay; an active last segment is explicitly a prefix."""
    root=Path(root);seq=0;head=genesis;previous=genesis;segments=0
    index_raw=(root/'segments.jsonl').read_bytes() if (root/'segments.jsonl').exists() else b''
    if index_raw and not index_raw.endswith(b'\n'):raise ValueError('partial segment index; retry after writer flush')
    paths=[]
    for raw in index_raw.splitlines():
        e=json.loads(raw);digest=e.pop('index_hash')
        if e['previous_index_hash']!=previous or hashlib.sha256(canonical(e)).hexdigest()!=digest:raise ValueError('index chain differs')
        p=root/e['path']
        if not p.resolve().is_relative_to(root.resolve()):raise ValueError('archive path escapes root')
        if sha(p)!=e['sha256']:raise ValueError('compressed segment differs')
        with gzip.open(p,'rb') as stream:
            h=hashlib.sha256();first=seq+1;first_previous=head;count=0
            for line in stream:
                h.update(line);seq,head=check_row(line,seq,head);count+=1
        if (e['first_sequence'],e['first_previous_hash'],e['last_sequence'],e['last_hash'],e['records'],e['uncompressed_sha256'])!=(first,first_previous,seq,head,count,h.hexdigest()):raise ValueError('segment receipts differ')
        paths.append(e['path']);previous=digest;segments+=1
    closed_sequence=seq;open_tail_bytes=0
    if include_open:
        for p in sorted(root.glob('data/*/*.open')):
            # A rotation can race this read. A caller can retry; never acquire writer lock.
            if str(p.with_suffix('.jsonl.gz').relative_to(root)) in paths:continue
            data=p.read_bytes();lines=data.splitlines(keepends=True)
            if lines and not lines[-1].endswith(b'\n'):open_tail_bytes+=len(lines.pop())
            for line in lines:seq,head=check_row(line,seq,head)
    return dict(passed=True,segments=segments,closed_sequence=closed_sequence,
                sequence=seq,last_hash=head,active_prefix=include_open,partial_tail_bytes=open_tail_bytes)
