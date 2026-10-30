"""Causal adaptive-research inputs from natively verified paired receipts.

The caller must verify the recorder chain before calling this pure adapter.
Market features use receiver a; both receivers adjudicate oracle health/paths.
"""
from adaptive_corridor import features
from investigate_capture import reconstruct
from oracle_activity_features import annotate, state
from oracle_gap_features import attach, positive
from research_market_regimes import price_units
from research_oracle_history import add_regimes

SPEC=dict(grid_ms=30000,history_ms=300000,market_source='a',
    entry='Receipts strictly before the grid boundary; both receivers fresh and equal',
    market='Receiver a mark/oracle context, strictly before entry and entry-minus-30s, fresh within 8s',
    outcome='Original paired recorder/analyzer rules; no interpolation or proxy price substitution',
    reset='One private capture period, including UTC midnight; no calendar-date reset')


def build_rows(receipts,policy,start,end,period):
    if end<=start or (end-start)%30000 or policy.get('duration_ms',30000)!=30000:
        raise ValueError('a complete 30-second grid is required')
    records=[];market=[];previous=start
    for receipt in receipts:
        at=receipt['at'];source=receipt['source']
        if not start<at<end or at<previous or source not in ('a','b'):
            raise ValueError('receipt outside original horizon, unordered, or invalid source')
        previous=at;raw=receipt['raw']
        if raw.get('channel')!='activeAssetCtx' or raw['data']['coin']!='BTC':
            raise ValueError('BTC oracle context required')
        ctx=raw['data']['ctx'];price=price_units(ctx['oraclePx'])
        records.append(dict(at=at,source=source,price=price))
        if source=='a':market.append((at,price,positive(ctx.get('markPx')),positive(ctx.get('midPx'))))
    rows,paired=reconstruct(records,policy,start,end)
    features(rows,paired,start);add_regimes(rows);annotate(rows,paired)
    for row in rows:
        # These two reason flags are set only at window construction, using the
        # prior receipt state. Later outage reasons cannot alter entry health.
        entry_healthy=(row['entry'] is not None and 'startup_no_paired_entry' not in row['reasons']
                       and 'unhealthy_entry' not in row['reasons'])
        row.update(period=period,split='prospective_native',entry_healthy=entry_healthy)
        if not entry_healthy:
            row['adaptive_features']=None;row['activity_features']=None
            row['market_regime']='missing_history'
        row['activity_state']=state(row)
    eligible=[r for r in rows if r['entry_healthy'] and r['adaptive_features'] is not None]
    annotated=attach(eligible,market,start)
    contexts={r['start']:r['oracle_gap'] for r in annotated}
    return [dict(r,oracle_gap=contexts.get(r['start'])) for r in rows]
