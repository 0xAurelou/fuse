#!/usr/bin/env python3
"""Check free-tier native ETH/HYPE history without buying or upgrading anything.

Samples fixed weekday/weekend UTC hours, paginates to completion, retains raw
responses and checks source timestamps. This is a data-access/QC probe, not a
corridor backtest. A minute-sampled oracle cannot label thirty-second paths.
"""
import argparse
from datetime import datetime, timedelta, timezone
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import statistics
import time
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener

from liquidity_features import book_metrics, number

BASE = 'https://api.0xarchive.io'
ASSETS = ('ETH', 'HYPE')
KEY_FILE = Path(__file__).resolve().parents[1] / '.local/secrets/oxarchive.env'
DAY = 86400000


def decode_payload(wire, encoding):
    if len(wire)>8000000:
        raise ValueError('Encoded response exceeded 8 MB bound')
    if encoding=='gzip':
        with gzip.GzipFile(fileobj=io.BytesIO(wire)) as stream:
            raw=stream.read(8000001)
    elif encoding in ('','identity'):
        raw=wire
    else:
        raise ValueError('Unsupported response transport encoding')
    if len(raw)>8000000:
        raise ValueError('Decoded response exceeded 8 MB bound')
    return raw


def dump(path, value):
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(value, indent=2, allow_nan=False) + '\n')
    temp.replace(path)


def load_key(path=KEY_FILE):
    value = os.environ.get('OXARCHIVE_API_KEY') or os.environ.get('OXA_API_KEY')
    if not value and path.exists():
        for line in path.read_text().splitlines():
            name, sep, candidate = line.strip().partition('=')
            if sep and name == 'OXARCHIVE_API_KEY':
                value = candidate.strip().strip('\"\'')
    if not value or value in ('your_key', '0xa_your_api_key'):
        raise ValueError('Free API key missing; set OXARCHIVE_API_KEY or use .local/secrets/oxarchive.env')
    if any(c.isspace() for c in value):
        raise ValueError('API key contains whitespace')
    return value


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Do not forward the authentication header to any redirect destination.
        return None


class Client:
    def __init__(self, key, max_requests=80):
        self.key = key
        self.opener = build_opener(NoRedirect())
        self.requests = 0
        self.max_requests = max_requests
        self.last_call = 0
        self.remaining = None

    def get(self, route, query):
        if not route.startswith('/v1/hyperliquid/') or '?' in route:
            raise ValueError('Only fixed Hyperliquid market-data GET routes allowed')
        if self.requests >= self.max_requests or self.remaining is not None and self.remaining < 100:
            raise ValueError('Probe request/credit reserve reached')
        time.sleep(max(0, .5 - (time.monotonic() - self.last_call)))
        self.last_call = time.monotonic()
        self.requests += 1
        request = Request(BASE + route + '?' + urlencode(query), headers={
            'X-API-Key': self.key, '0xArchive-Version': '2026-10-01',
            'User-Agent': 'fuse-liquidity-preflight/1.0', 'Accept': 'application/json',
            'Accept-Encoding': 'gzip'})
        try:
            with self.opener.open(request, timeout=30) as response:
                raw = decode_payload(response.read(8000001),response.headers.get('Content-Encoding',''))
                headers = {k.lower(): v for k, v in response.headers.items()
                           if k.lower().startswith(('x-credits-', 'x-ratelimit-'))
                           or k.lower() == 'x-request-id'}
        except HTTPError as exc:
            # Never include the request headers or echoed server body in logs.
            raise ValueError('0xArchive HTTP %s; stop, do not upgrade or retry authentication errors' % exc.code) from None
        if len(raw) > 8000000:
            raise ValueError('Response exceeded 8 MB probe bound')
        if 'x-credits-remaining' in headers:
            self.remaining = int(headers['x-credits-remaining'])
        payload = json.loads(raw)
        if payload.get('success') is not True:
            raise ValueError('API response did not confirm success')
        return raw, payload, headers


def stamp(value):
    if isinstance(value, bool):
        raise ValueError('Invalid source timestamp')
    if isinstance(value, int):
        if value < 10**12:
            raise ValueError('Expected Unix milliseconds, not seconds')
        return value
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        raise ValueError('Source timestamp has no timezone')
    return int(parsed.timestamp() * 1000)


def next_cursor(payload, previous):
    meta = payload['meta']
    if not meta.get('request_id'):
        raise ValueError('Missing provider request ID')
    cursor = meta.get('next_cursor')
    more = meta.get('has_more')
    if more is not None and not isinstance(more, bool):
        raise ValueError('Invalid has_more flag')
    if more is False or more is None and cursor is None and 'next_cursor' in meta:
        return None
    if cursor is None or cursor == previous:
        raise ValueError('Missing, repeated or ambiguous pagination cursor')
    return cursor


def validate(rows, asset, kind, start, end):
    times = []
    for row in rows:
        if row.get('symbol', row.get('coin')) != asset or row.get('coin', asset) != asset:
            raise ValueError('Returned asset differs')
        at = stamp(row['timestamp'])
        if not start <= at <= end or times and at < times[-1]:
            raise ValueError('Source timestamp outside query or regresses')
        if kind == 'books':
            if row.get('source') != 'venue':
                raise ValueError('Native venue source must be explicit; node books are separate')
            values = book_metrics(dict(levels=[row['bids'], row['asks']]))
            if min(values['bid_levels'], values['ask_levels']) < 5:
                raise ValueError('Fewer than five actual levels per side')
        else:
            number(row['oracle_price'])
        times.append(at)
    return times


def quality(times, start, end, fresh_ms):
    ordered = sorted(set(times))
    gaps = [b-a for a,b in zip(ordered, ordered[1:])]
    # No receipt timestamp is fabricated; availability is by source time only.
    cursor = 0
    eligible = 0
    grid = range(start + 30000, end, 30000)
    for entry in grid:
        while cursor < len(ordered) and ordered[cursor] < entry:
            cursor += 1
        eligible += bool(cursor and 0 < entry-ordered[cursor-1] <= fresh_ms)
    return dict(rows=len(times), unique_timestamps=len(ordered),
                first_ms=ordered[0] if ordered else None,
                last_ms=ordered[-1] if ordered else None,
                median_gap_ms=statistics.median(gaps) if gaps else None,
                max_gap_ms=max(gaps) if gaps else None,
                prior_source_fresh_grid_fraction=eligible/len(grid) if grid else None,
                freshness_ms=fresh_ms)


def windows(now):
    today = now.astimezone(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    candidates = [today-timedelta(days=i) for i in range(1,8)]
    selected = [next(d for d in candidates if d.weekday()<5),
                next(d for d in candidates if d.weekday()>=5)]
    return [int((d+timedelta(hours=h)).timestamp()*1000)
            for d in selected for h in (0,12)]


def run(root, key):
    if root.exists():
        raise ValueError('Use a new probe output directory')
    root.mkdir(parents=True)
    starts = windows(datetime.now(timezone.utc))
    protocol = dict(assets=ASSETS, starts_ms=starts, duration_ms=3600000,
                    page_limit=1000, max_requests=80, max_response_bytes=8000000,
                    source='venue', authentication='header; key never archived',
                    source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                    interpretation='Access and cadence QC only. No interpolation, no model fitting, no PnL.',
                    receipt_time='Unavailable in this API; source timestamps are not receipt timestamps')
    dump(root/'protocol.json', protocol)
    client = Client(key)
    results = []
    try:
        for asset in ASSETS:
            for start in starts:
                for kind in ('books', 'oracle_context'):
                    route = '/v1/hyperliquid/' + ('orderbook/'+asset+'/history' if kind=='books' else 'openinterest/'+asset)
                    query = dict(start=start, end=start+3600000, limit=1000)
                    if kind=='books':
                        query.update(depth=20, source='venue')
                    times, pages, cursor, seen = [], [], None, set()
                    while True:
                        if cursor is not None:
                            query['cursor'] = cursor
                        raw, payload, headers = client.get(route, query)
                        path = '%s-%s-%s-%03d.json.gz' % (asset, start, kind, len(pages))
                        compressed = gzip.compress(raw, mtime=0)
                        (root/path).write_bytes(compressed)
                        pages.append(dict(path=path, route=route, query=dict(query), headers=headers,
                                          sha256=hashlib.sha256(compressed).hexdigest(),
                                          request_id=payload.get('meta',{}).get('request_id')))
                        dump(root/'pages.json', dict(requests=client.requests,
                             completed=results, current=dict(asset=asset, kind=kind, pages=pages)))
                        rows = payload['data']
                        if not isinstance(rows, list) or len(rows)>1000:
                            raise ValueError('Expected at most 1000 history rows')
                        part = validate(rows, asset, kind, start, start+3600000)
                        if times and part and part[0] < times[-1]:
                            raise ValueError('Page timestamp order regressed')
                        times.extend(part)
                        cursor = next_cursor(payload, cursor)
                        if cursor is None:
                            break
                        identity = json.dumps(cursor, sort_keys=True)
                        if identity in seen or not rows:
                            raise ValueError('Cursor loop or empty incomplete page')
                        seen.add(identity)
                    results.append(dict(asset=asset, start_ms=start, kind=kind, pages=pages,
                        quality=quality(times,start,start+3600000,5000 if kind=='books' else 8000)))
                    dump(root/'results.json', dict(complete=False, requests=client.requests, windows=results))
    except Exception as exc:
        dump(root/'status.json', dict(complete=False, requests=client.requests,
             error_type=type(exc).__name__, error=str(exc).replace(key,'[redacted]')))
        raise
    # This is deliberately only a candidate gate. Dense timestamps alone do not
    # prove every oracle update, source receipt timing or uninterrupted paths.
    oracles = [r['quality'] for r in results if r['kind']=='oracle_context']
    candidate = all(q['rows']>=2 and q['max_gap_ms']<=8000
                    and q['prior_source_fresh_grid_fraction']>=.98 for q in oracles)
    result = dict(complete=True, requests=client.requests, windows=results,
                  oracle_cadence_candidate=candidate, corridor_backtest_validated=False,
                  next_step='Verify high-frequency oracle provenance before corridor outcomes' if candidate
                  else 'Oracle history is too sparse for the original thirty-second corridor test')
    dump(root/'results.json',result)
    dump(root/'status.json', dict(complete=True,requests=client.requests))
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--key-file',type=Path,default=KEY_FILE)
    args = parser.parse_args()
    try:
        result = run(args.output, load_key(args.key_file))
        print(json.dumps({k:v for k,v in result.items() if k!='windows'}))
    except Exception as exc:
        # Avoid traceback locals containing credentials or raw HTTP objects.
        print(json.dumps(dict(complete=False,error_type=type(exc).__name__,
                              error='Probe stopped; see local status if created')))
        raise SystemExit(1)
