#!/usr/bin/env python3
"""Collect public ETH/HYPE liquidity beside (and independently of) engine captures."""
import argparse
from datetime import datetime, timedelta, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import plistlib
import shutil
import signal
import subprocess
import sys
import threading
import time
import uuid

from liquidity_archive import Archive, atomic, sha, verify
from liquidity_features import ASSETS, BANDS, MarketState

ENDPOINT='wss://api.hyperliquid.xyz/ws'
CHANNELS=('activeAssetCtx','l2Book','bbo','trades')
SOURCES=('collect_liquidity.py','liquidity_archive.py','liquidity_features.py','inspect_liquidity_capture.py')
SPEC=dict(version='eth-hype-liquidity-v1',assets=ASSETS,channels=CHANNELS,
    venue='Hyperliquid native ETH and HYPE perpetuals, not spot @107',
    endpoint=ENDPOINT,connections=1,upstream_independent=False,
    book='Unaggregated slow L2 snapshots, default up to 20 price levels per side. No nSigFigs/mantissa; not the entire order book.',
    spread='Dedicated BBO changes plus L2-derived spread; use most recently received fresh source. BBO silence alone is not an outage because BBO is pushed on changes only.',
    depth_bands_bps=BANDS,sample_interval_seconds=1,segment_seconds=300,
    timestamps='Original book/trade exchange milliseconds plus client receipt wall nanoseconds, monotonic nanoseconds and session ID. Oracle activeAssetCtx has no exchange timestamp.',
    features='Spread in bps; captured bid/ask notional and coverage at fixed bands; top 1/5/10/20-level notional; imbalance only for fully covered bands; trailing observed trade count/notional; oracle update/change/idle metrics. All receipt-time past-only.',
    missing_data='No interpolation or backfill. Reconnect, loop/clock gaps and invalid messages reset state. Missing/stale books and oracle are null, never zero liquidity. Initial trade batch excluded from rolling features; per-session (coin,time,tid) dedupe; full raw batches retained.',
    freshness=dict(book_ms=5000,oracle_ms=8000,future_book_tolerance_ms=2000,
                   loop_gap_ms=5000,status_liveness_ms=15000),
    storage=dict(max_capture_gib=20,minimum_free_gib=5,fsync_interval_seconds=5),
    transport='Ping every 20 seconds, reconnect after 30 seconds of total silence or 15 seconds of required per-asset feed silence; bounded 1..30 second retries. Trades need not arrive in quiet markets.',
    primary_hypothesis='Pre-entry measured liquidity adds explanatory value for next-30-second zero oracle movement beyond past oracle activity, volatility, UTC hour and weekend indicator. Associational test; not causal identification.',
    future_analysis=dict(grid='Fixed UTC 30-second boundaries; strictly earlier receipts only. Build next-30-second outcomes offline after the collection horizon.',
        primary_outcome='Next-30-second zero oracle movement; oracle receipt freshness required throughout each outcome interval. Book freshness is a pre-entry condition only, never a future-outcome filter.',
        secondary_outcomes=['maximum absolute oracle excursion','one-ppm corridor survival'],
        predictors=['log spread bps','log top5 bid/ask visible notional','fully covered 1/5-bps depth and missingness','60-second observed trade notional/count'],
        controls=['past oracle idle/update/change counts','past oracle volatility','UTC hour','UTC weekend'],
        split='First seven complete UTC days development; final seven complete UTC days frozen chronological evaluation. Today partial excluded from primary split. No retuning on final seven days.',
        uncertainty='Report per-day coverage and weekday/weekend strata; use day/episode blocks, never independent-trial confidence from every 30-second path.',
        no_early_success_stopping=True),
    collection_only=True,pricing_models_changed=False,trading_enabled=False,
    limits='One public venue/connection, local host and network dependency; no canonical two-receiver settlement validation, guaranteed feed completeness, multi-venue liquidity or causal claim.')


def write_new(path,value):
    with path.open('x') as stream:json.dump(value,stream,indent=2,allow_nan=False);stream.write('\n');stream.flush();os.fsync(stream.fileno())


def prepare(root, full_days=14, seconds=None):
    if full_days!=14 and seconds is None:raise ValueError('primary specification fixes fourteen complete UTC days')
    if seconds is not None and not 10<=seconds<=300:raise ValueError('smoke horizon must be 10..300 seconds')
    if root.exists():raise ValueError('use a new dedicated directory')
    if shutil.disk_usage(root.parent if root.parent.exists() else Path.cwd()).free<10*1024**3:
        raise ValueError('at least 10 GiB free disk required to prepare')
    root.mkdir(parents=True,mode=0o700);(root/'source').mkdir()
    for name in SOURCES:shutil.copyfile(Path(__file__).with_name(name),root/'source'/name)
    import websocket
    from importlib.metadata import distribution
    vendor=root/'source'/'vendor'/'websocket'
    shutil.copytree(Path(websocket.__file__).parent,vendor,ignore=shutil.ignore_patterns('__pycache__','*.pyc','tests'))
    dependency=distribution('websocket-client')
    for name in ('LICENSE','METADATA'):
        text=dependency.read_text(name)
        if text is None:raise ValueError('missing websocket-client dependency metadata: '+name)
        (vendor.parent/('websocket-client-'+name+'.txt')).write_text(text)
    now=datetime.now(timezone.utc);first_day=(now+timedelta(days=1)).replace(hour=0,minute=0,second=0,microsecond=0)
    deadline=now+timedelta(seconds=seconds) if seconds is not None else first_day+timedelta(days=full_days)
    frozen={str(p.relative_to(root)):sha(p) for p in sorted((root/'source').rglob('*')) if p.is_file()}
    plan=dict(spec=SPEC,prepared_at_ms=int(now.timestamp()*1000),deadline_ms=int(deadline.timestamp()*1000),
        first_complete_utc_day=first_day.date().isoformat(),complete_utc_days=full_days if seconds is None else 0,
        role='transport_smoke_only' if seconds is not None else 'fresh_consecutive_liquidity_collection',
        python_executable=sys.executable,python_version=sys.version.split()[0],websocket_client_version=websocket.__version__,
        source_sha256=frozen,collection_root=str(root.resolve()),
        service_label='dev.fuse.eth-hype-liquidity.'+now.strftime('%Y%m%d%H%M%S')+'-'+uuid.uuid4().hex[:6],
        subscriptions=[dict(type=c,coin=a) for a in ASSETS for c in CHANNELS],
        source_docs=['https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/websocket/subscriptions',
          'https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/websocket/timeouts-and-heartbeats',
          'https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/rate-limits-and-user-limits'])
    write_new(root/'collection-plan.json',plan)
    write_new(root/'freeze.json',dict(plan_sha256=sha(root/'collection-plan.json')))
    return plan


def verify_plan(root):
    binding=json.loads((root/'freeze.json').read_text());plan=json.loads((root/'collection-plan.json').read_text())
    if sha(root/'collection-plan.json')!=binding['plan_sha256']:raise ValueError('collection plan changed')
    if str(root.resolve())!=plan['collection_root']:raise ValueError('collection directory moved')
    for name,digest in plan['source_sha256'].items():
        if sha(root/name)!=digest:raise ValueError('frozen source changed: '+name)
    if sys.version.split()[0]!=plan['python_version']:raise ValueError('Python runtime version differs')
    if sha(Path(__file__))!=plan['source_sha256']['source/collect_liquidity.py']:
        raise ValueError('recorder differs from frozen source')
    for name in ('liquidity_archive.py','liquidity_features.py'):
        if sha(Path(__file__).with_name(name))!=plan['source_sha256']['source/'+name]:raise ValueError('imported module differs')
    return plan,binding['plan_sha256']


def feed_health(states, now_ns):
    result={}
    for a,s in states.items():
        sample=s.sample(now_ns)
        result[a]={k:sample[k] for k in ('oracle_receive_age_ms','book_receive_age_ms','joint_fresh')}
    return result


def run(root):
    root=root.resolve();plan,genesis=verify_plan(root)
    # Import the frozen, vendored WS client for the installed long-running job.
    sys.path.insert(0,str(root/'source'/'vendor'))
    import websocket
    if websocket.__version__!=plan['websocket_client_version']:raise ValueError('WS runtime version differs')
    lock=(root/'collector.lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    if time.time_ns()//1000000>=plan['deadline_ms']:return
    previous=json.loads((root/'status.json').read_text()) if (root/'status.json').exists() else None
    session=uuid.uuid4().hex;stop=threading.Event();states={a:MarketState(a) for a in ASSETS}
    for sig in (signal.SIGTERM,signal.SIGINT):signal.signal(sig,lambda *_:stop.set())
    archive=Archive(root,genesis,session)
    ws=None;attempt=0;connected_ns=None;last_message_ns=None;last_loop_ns=time.time_ns()
    last_loop_mono=time.monotonic_ns();last_ping=last_sample=last_status=last_disk=0.
    retry_at=0.;messages={a:{c:0 for c in CHANNELS} for a in ASSETS};counts={};reason=None
    state='starting'
    def event(kind,**values):
        archive.append(dict(kind=kind,received_at_ns=time.time_ns(),monotonic_ns=time.monotonic_ns(),session_id=session,**values))
    def save(state,**extra):
        archive.flush();now_ns=time.time_ns()
        atomic(root/'status.json',dict(state=state,updated_at_ms=now_ns//1000000,pid=os.getpid(),
            session_id=session,deadline_ms=plan['deadline_ms'],plan_sha256=genesis,
            archive_sequence=archive.sequence,archive_head=archive.head,
            compressed_segments=len(archive.segments),capture_bytes=archive.bytes_written(),
            session_channel_messages=messages,session_event_counts=counts,
            feed_health=feed_health(states,now_ns),collection_only=True,**extra))
    def disconnect(why):
        nonlocal ws,connected_ns,retry_at,attempt,state
        event('disconnect',reason=why)
        if ws:
            try:ws.close(timeout=1)
            except Exception:pass
        ws=None;connected_ns=None
        for s in states.values():s.reset(time.time_ns())
        attempt+=1;retry_at=time.monotonic()+min(30,2**min(5,attempt-1));state='reconnecting'
        counts['disconnects']=counts.get('disconnects',0)+1
    event('session_start',previous_status=previous,recovered=archive.recoveries)
    try:
        save('starting')
        while not stop.is_set():
            now_ns=time.time_ns();mono_ns=time.monotonic_ns();mono=mono_ns/10**9;now=now_ns//1000000
            wall_delta=now_ns-last_loop_ns;mono_delta=mono_ns-last_loop_mono
            if wall_delta<0 or wall_delta>5*10**9 or abs(wall_delta-mono_delta)>2*10**9:
                event('host_or_clock_gap',wall_elapsed_ns=wall_delta,monotonic_elapsed_ns=mono_delta)
                if ws:disconnect('host_or_clock_gap')
                else:
                    for s in states.values():s.reset(now_ns)
                counts['host_or_clock_gaps']=counts.get('host_or_clock_gaps',0)+1
            last_loop_ns,last_loop_mono=now_ns,mono_ns
            if now>=plan['deadline_ms']:reason='frozen_deadline';break
            if (root/'STOP').exists():reason='requested_stop';break
            if mono-last_disk>=10:
                last_disk=mono
                if shutil.disk_usage(root).free<5*1024**3:reason='disk_free_floor';break
                if archive.bytes_written()>=20*1024**3:reason='capture_storage_limit';break
            if mono-last_sample>=1:
                if ws:
                    for a,s in states.items():
                        archive.append(dict(kind='features',received_at_ns=now_ns,monotonic_ns=mono_ns,
                            session_id=session,values=s.sample(now_ns)))
                last_sample=mono
            if mono-last_status>=5:save(state);last_status=mono
            if ws is None:
                if mono<retry_at:stop.wait(min(.5,retry_at-mono));continue
                try:
                    ws=websocket.create_connection(ENDPOINT,timeout=10,enable_multithread=True)
                    ws.settimeout(.5);connected_ns=time.time_ns();last_message_ns=connected_ns
                    for s in states.values():s.reset(connected_ns)
                    for sub in plan['subscriptions']:ws.send(json.dumps(dict(method='subscribe',subscription=sub)))
                    event('connected',subscriptions=plan['subscriptions']);state='recording';last_ping=mono
                    # Handshake duration is accounted separately from host sleep.
                    last_loop_ns=time.time_ns();last_loop_mono=time.monotonic_ns()
                except Exception as exc:disconnect('connect: '+type(exc).__name__+': '+str(exc))
                continue
            if mono-last_ping>=20:
                try:ws.send('{"method":"ping"}');last_ping=mono
                except Exception as exc:disconnect('ping: '+str(exc));continue
            if last_message_ns and now_ns-last_message_ns>30*10**9:disconnect('socket_receive_silence');continue
            if connected_ns and now_ns-connected_ns>15*10**9:
                stale=[]
                for a,s in states.items():
                    for c,v in (('oracle',s.oracle),('book',s.book)):
                        if v is None or now_ns-v['received_at_ns']>15*10**9:stale.append(a+':'+c)
                if stale:disconnect('required_feed_silence:'+','.join(stale));continue
                attempt=0
            try:raw=ws.recv()
            except websocket.WebSocketTimeoutException:continue
            except (OSError,websocket.WebSocketException) as exc:
                disconnect(type(exc).__name__+': '+str(exc));continue
            received=time.time_ns();received_mono=time.monotonic_ns()
            if received>=plan['deadline_ms']*1000000:reason='frozen_deadline';break
            if isinstance(raw,bytes):raw=raw.decode('utf-8')
            if not raw or len(raw)>2*1024**2:
                disconnect('empty socket frame or message exceeds 2 MiB limit');continue
            archive.append(dict(kind='websocket',received_at_ns=received,monotonic_ns=received_mono,
                                session_id=session,payload_text=raw))
            try:
                # Never let a buffered pre-sleep message revive the prior session.
                if received-last_loop_ns>5*10**9:
                    disconnect('receive_returned_after_loop_gap');continue
                value=json.loads(raw);channel=value['channel'];data=value.get('data')
                last_message_ns=received
                if channel=='error':raise ValueError('upstream error: '+str(data))
                if channel=='subscriptionResponse':
                    sub=data.get('subscription',data)
                    if sub.get('coin') in states:states[sub['coin']].acknowledge(sub.get('type'))
                    continue
                if channel in ('pong',):continue
                if channel not in CHANNELS:raise ValueError('unexpected channel: '+str(channel))
                if channel=='trades' and not data:continue
                asset=data[0]['coin'] if channel=='trades' else data['coin']
                if asset not in states:raise ValueError('unsubscribed asset')
                states[asset].acknowledge(channel)
                result=states[asset].observe(channel,data,received)
                messages[asset][channel]+=1
                if channel=='trades' and result.get('bootstrap_batch'):
                    event('trade_bootstrap_excluded',asset=asset,trades=len(data))
            except (ValueError,KeyError,TypeError,AttributeError) as exc:
                disconnect(type(exc).__name__+': '+str(exc))
        if reason is None:reason='signal'
        state='horizon_finished' if reason=='frozen_deadline' else 'stopped'
        event('session_end',reason=reason)
        if ws:ws.close(timeout=1);ws=None
        archive.rotate();save(state,stop_reason=reason)
        return 0
    except Exception as exc:
        # Storage/codec failures are fatal. launchd may resume the preserved prefix.
        try:save('failed',error=type(exc).__name__+': '+str(exc))
        except Exception:pass
        raise
    finally:
        if ws:
            try:ws.close(timeout=1)
            except Exception:pass
        if archive.stream:
            archive.flush();archive.stream.close()
        lock.close()


def status(root):
    plan,_=verify_plan(root);path=root/'status.json'
    if not path.exists():return dict(state='prepared',deadline_ms=plan['deadline_ms'])
    value=json.loads(path.read_text());now=time.time_ns()//1000000
    value['status_age_ms']=now-value['updated_at_ms']
    value['recorder_heartbeat_fresh']=0<=value['status_age_ms']<=15000 and value['state'] in ('starting','recording','reconnecting')
    value['checked_at_ms']=now
    # Re-evaluate saved ages against the caller's wall clock.
    for asset,h in value['feed_health'].items():
        for field in ('oracle_receive_age_ms','book_receive_age_ms'):
            if h[field] is not None:h[field]+=value['status_age_ms']
        h['joint_fresh_now']=bool(value['recorder_heartbeat_fresh'] and h['joint_fresh']
            and h['oracle_receive_age_ms'] is not None and h['book_receive_age_ms'] is not None
            and 0<=h['oracle_receive_age_ms']<=8000 and 0<=h['book_receive_age_ms']<=5000)
    return value


def service_file(root):
    plan,_=verify_plan(root)
    args=[plan['python_executable'],'-B',str(root/'source'/'collect_liquidity.py'),'run','--directory',str(root)]
    if sys.platform=='darwin':args=['/usr/bin/caffeinate','-i',*args]
    value=dict(Label=plan['service_label'],ProgramArguments=args,WorkingDirectory=str(root),
        RunAtLoad=True,KeepAlive={'SuccessfulExit':False},ThrottleInterval=30,ExitTimeOut=15,
        EnvironmentVariables={'PYTHONDONTWRITEBYTECODE':'1','PYTHONUNBUFFERED':'1'},
        StandardOutPath=str(root/'launchd.log'),StandardErrorPath=str(root/'launchd.log'))
    path=root/'agent.plist'
    if path.exists():
        if plistlib.loads(path.read_bytes())!=value:raise ValueError('service definition changed')
    else:
        with path.open('xb') as stream:plistlib.dump(value,stream)
    return path,plan['service_label']


def install(root):
    if sys.platform!='darwin':raise ValueError('this service installer targets macOS launchd')
    path,label=service_file(root)
    target=Path.home()/'Library'/'LaunchAgents'/(label+'.plist')
    target.parent.mkdir(parents=True,exist_ok=True)
    if target.exists() and target.read_bytes()!=path.read_bytes():raise ValueError('installed service differs')
    if not target.exists():shutil.copyfile(path,target)
    domain='gui/'+str(os.getuid())
    existing=subprocess.run(['/bin/launchctl','print',domain+'/'+label],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    if existing.returncode:subprocess.run(['/bin/launchctl','bootstrap',domain,str(target)],check=True)
    receipt=dict(label=label,installed_plist=str(target),prepared_plist_sha256=sha(path),
        installed_at_ms=time.time_ns()//1000000,idle_sleep_prevention='caffeinate -i for this job only; does not prevent lid-close sleep or loss of network')
    atomic(root/'service.json',receipt)
    return receipt


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['prepare','run','status','verify','service-file','install'])
    parser.add_argument('--directory',type=Path,required=True);parser.add_argument('--smoke-seconds',type=int)
    args=parser.parse_args();root=args.directory.resolve()
    if args.action=='prepare':result=prepare(root,seconds=args.smoke_seconds)
    elif args.action=='run':sys.exit(run(root) or 0)
    elif args.action=='status':result=status(root)
    elif args.action=='verify':
        _,genesis=verify_plan(root);result=verify(root,genesis,include_open=True)
    elif args.action=='service-file':p,label=service_file(root);result=dict(path=str(p),label=label)
    else:result=install(root)
    print(json.dumps(result,indent=2))
