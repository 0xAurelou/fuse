"""Past-only summaries of public ETH/HYPE perp books, trades and oracle receipts."""
from collections import deque
from decimal import Decimal, InvalidOperation
import math

ASSETS = ('ETH', 'HYPE')
BANDS = (1, 5, 10, 25, 50)
BOOK_FRESH_MS = 5000
ORACLE_FRESH_MS = 8000
FUTURE_TOLERANCE_MS = 2000


def number(value, positive=True):
    try:
        x = Decimal(str(value))
    except InvalidOperation:
        raise ValueError('invalid decimal')
    if not x.is_finite() or (x <= 0 if positive else x < 0):
        raise ValueError('nonfinite or invalid signed market quantity')
    if not math.isfinite(float(x)):
        raise ValueError('market quantity exceeds numeric summary range')
    return x


def book_metrics(data):
    levels = data['levels']
    if len(levels) != 2 or any(not side or len(side) > 20 for side in levels):
        raise ValueError('nonempty at-most-20-level sides required')
    sides = [[(number(l['px']), number(l['sz']), l['n']) for l in side] for side in levels]
    bids, asks = sides
    if any(isinstance(n,bool) or not isinstance(n,int) or n < 1 for side in sides for _,_,n in side):
        raise ValueError('positive integer order counts required')
    if any(a[0] <= b[0] for a,b in zip(bids,bids[1:])) or any(a[0] >= b[0] for a,b in zip(asks,asks[1:])):
        raise ValueError('book levels must be strictly ordered')
    bid, ask = bids[0][0], asks[0][0]
    if bid >= ask:raise ValueError('locked or crossed book')
    mid = (bid+ask)/2
    result = dict(best_bid=str(bid),best_ask=str(ask),mid=str(mid),
        spread_usd=float(ask-bid),spread_bps=float((ask-bid)/mid*10000),
        bid_levels=len(bids),ask_levels=len(asks),
        bid_visible_span_bps=float((mid-bids[-1][0])/mid*10000),
        ask_visible_span_bps=float((asks[-1][0]-mid)/mid*10000),
        depth={})
    for band in BANDS:
        lower,upper=mid*(1-Decimal(band)/10000),mid*(1+Decimal(band)/10000)
        bn=sum((p*s for p,s,_ in bids if p>=lower),Decimal(0))
        an=sum((p*s for p,s,_ in asks if p<=upper),Decimal(0))
        total=bn+an
        # Outside the visible book, captured depth is only a lower bound.
        bc,ac=bids[-1][0]<=lower,asks[-1][0]>=upper
        result['depth'][str(band)]=dict(bid_captured_usd=float(bn),ask_captured_usd=float(an),
            bid_band_covered=bc,ask_band_covered=ac,
            bid_usd=float(bn) if bc else None,ask_usd=float(an) if ac else None,
            imbalance=float((bn-an)/total) if total and bc and ac else None)
    for n in (1,5,10,20):
        result[f'top{n}_bid_usd']=float(sum((p*s for p,s,_ in bids[:n]),Decimal(0)))
        result[f'top{n}_ask_usd']=float(sum((p*s for p,s,_ in asks[:n]),Decimal(0)))
    return result


class MarketState:
    def __init__(self, asset):
        if asset not in ASSETS:raise ValueError('unsupported asset')
        self.asset=asset;self.reset(0)

    def reset(self, at_ns):
        self.since_ns=at_ns;self.book=None;self.oracle=None;self.bbo=None
        self.last_trade_message_ns=None;self.trade_ack=False
        self.first_trade_batch=True;self.trades=deque();self.trade_ids={};self.id_order=deque()
        self.oracle_path=deque();self.last_change_ns=None;self.observed_change=False

    def acknowledge(self, channel):
        if channel=='trades':self.trade_ack=True

    def observe(self, channel, data, at_ns):
        at=at_ns//1000000
        if channel=='bbo':
            if data['coin']!=self.asset:raise ValueError('BBO asset differs')
            source=data['time']
            if isinstance(source,bool) or not isinstance(source,int) or source<=0:raise ValueError('invalid BBO timestamp')
            if self.bbo and source<self.bbo['exchange_at_ms']:raise ValueError('regressing BBO timestamp')
            if len(data['bbo'])!=2 or any(v is None for v in data['bbo']):raise ValueError('empty BBO side')
            values=book_metrics(dict(levels=[[data['bbo'][0]],[data['bbo'][1]]]))
            self.bbo=dict(received_at_ns=at_ns,exchange_at_ms=source,
                          **{k:values[k] for k in ('best_bid','best_ask','mid','spread_usd','spread_bps','top1_bid_usd','top1_ask_usd')})
            return dict(accepted=True)
        if channel=='l2Book':
            if data['coin']!=self.asset:raise ValueError('book asset differs')
            source=data['time']
            if isinstance(source,bool) or not isinstance(source,int) or source <= 0:raise ValueError('invalid book timestamp')
            values=book_metrics(data)
            if self.book and source<self.book['exchange_at_ms']:raise ValueError('regressing book timestamp')
            self.book=dict(received_at_ns=at_ns,exchange_at_ms=source,**values)
            return dict(accepted=True)
        if channel=='activeAssetCtx':
            if data['coin']!=self.asset:raise ValueError('oracle asset differs')
            ctx=data['ctx'];price=number(ctx['oraclePx']);mark=number(ctx['markPx'])
            if self.oracle is not None and self.oracle['oracle_px']!=str(price):self.observed_change=True
            if self.oracle is None or self.oracle['oracle_px']!=str(price):self.last_change_ns=at_ns
            self.oracle=dict(received_at_ns=at_ns,oracle_px=str(price),mark_px=str(mark),
                             mid_px=ctx.get('midPx'),funding=ctx.get('funding'),
                             open_interest=ctx.get('openInterest'),day_notional_volume=ctx.get('dayNtlVlm'))
            self.oracle_path.append((at_ns,str(price)))
            while self.oracle_path and at_ns-self.oracle_path[0][0]>300*10**9:self.oracle_path.popleft()
            return dict(accepted=True)
        if channel!='trades':raise ValueError('unexpected market channel')
        self.last_trade_message_ns=at_ns
        bootstrap=self.first_trade_batch;self.first_trade_batch=False
        self.expire(at_ns)
        added=duplicates=0
        for trade in data:
            if trade['coin']!=self.asset:raise ValueError('trade asset differs')
            px,sz=number(trade['px']),number(trade['sz'])
            when,tid=trade['time'],trade['tid']
            if any(isinstance(v,bool) or not isinstance(v,int) or v < 0 for v in (when,tid)) or trade['side'] not in ('B','A'):
                raise ValueError('invalid trade identity or side')
            identity=(when,tid)
            if identity in self.trade_ids:duplicates+=1;continue
            self.trade_ids[identity]=at_ns;self.id_order.append((at_ns,identity))
            if not bootstrap and at-60000 < when <= at+FUTURE_TOLERANCE_MS:
                self.trades.append((at_ns,when,float(px*sz),trade['side']));added+=1
        return dict(accepted=True,bootstrap_batch=bootstrap,new_rolling_trades=added,duplicates=duplicates)

    def expire(self, at_ns):
        while self.trades and at_ns-self.trades[0][0]>60*10**9:self.trades.popleft()
        while self.id_order and at_ns-self.id_order[0][0]>300*10**9:
            old,identity=self.id_order.popleft()
            if self.trade_ids.get(identity)==old:self.trade_ids.pop(identity,None)

    def sample(self, at_ns):
        self.expire(at_ns);at=at_ns//1000000
        book=self.book if self.book and self.book['received_at_ns']<at_ns else None
        oracle=self.oracle if self.oracle and self.oracle['received_at_ns']<at_ns else None
        bbo=self.bbo if self.bbo and self.bbo['received_at_ns']<at_ns else None
        ba=(at_ns-book['received_at_ns'])/1000000 if book else None
        oa=(at_ns-oracle['received_at_ns'])/1000000 if oracle else None
        exchange_age=at-book['exchange_at_ms'] if book else None
        bf=ba is not None and 0<=ba<=BOOK_FRESH_MS and -FUTURE_TOLERANCE_MS<=exchange_age<=BOOK_FRESH_MS
        of=oa is not None and 0<=oa<=ORACLE_FRESH_MS
        bbo_fresh=bool(bbo and 0<=at_ns-bbo['received_at_ns']<=BOOK_FRESH_MS*1000000
                       and -FUTURE_TOLERANCE_MS<=at-bbo['exchange_at_ms']<=BOOK_FRESH_MS)
        spreads=[(source,value) for source,value in (('l2Book',book if bf else None),('bbo',bbo if bbo_fresh else None)) if value]
        spread=max(spreads,key=lambda p:p[1]['received_at_ns']) if spreads else None
        # Reconnect/bootstrap can omit prints. Silence alone never implies lost trades.
        complete=self.trade_ack and not self.first_trade_batch and at_ns-self.since_ns>=60*10**9
        trades=[t for t in self.trades if t[0]<at_ns and at-60000<t[1]<=at]
        path=[p for p in self.oracle_path if 0<at_ns-p[0]<=30*10**9]
        return dict(asset=self.asset,sample_at_ms=at,sample_at_ns=at_ns,
            session_age_ms=(at_ns-self.since_ns)/1000000,
            oracle_fresh=of,book_fresh=bf,joint_fresh=of and bf,
            oracle_receive_age_ms=oa,book_receive_age_ms=ba,book_exchange_age_ms=exchange_age,
            book_exchange_minus_receive_ms=book['exchange_at_ms']-book['received_at_ns']//1000000 if book else None,
            oracle=oracle if of else None,book=book if bf else None,
            bbo=bbo if bbo_fresh else None,bbo_fresh=bbo_fresh,
            bbo_change_age_ms=(at_ns-bbo['received_at_ns'])/1000000 if bbo else None,
            spread_bps=spread[1]['spread_bps'] if spread else None,spread_source=spread[0] if spread else None,
            oracle_observations_30s=len(path),oracle_changes_30s=sum(a[1]!=b[1] for a,b in zip(path,path[1:])),
            oracle_idle_ms=(at_ns-self.last_change_ns)/1000000 if self.last_change_ns is not None else None,
            oracle_idle_is_lower_bound=not self.observed_change,
            trade_observed_count_60s=len(trades),trade_observed_notional_usd_60s=sum(t[2] for t in trades),
            trade_observed_buy_usd_60s=sum(t[2] for t in trades if t[3]=='B'),
            trade_observed_sell_usd_60s=sum(t[2] for t in trades if t[3]=='A'),
            trade_window_transport_covered=complete,
            trade_last_message_age_ms=(at_ns-self.last_trade_message_ns)/1000000 if self.last_trade_message_ns else None)
