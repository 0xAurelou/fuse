'use client';

import { memo, useEffect, useMemo, useRef, useState } from 'react';
import { Icon } from './icons';
import { CharacterStage } from './character-stage';
import { ClubMusic } from './club-music';
import { ASSETS, DEFAULT_DNT, EngineError, MARKET_FIXTURES, PAYOUT_OPTIONS, demoObservations, engineRequest, formatUsdc, payoutTerms, previewCorridor, validMultiplier, type Asset, type Quote, type Stage } from '@/lib/trading';
import { engineEnabled, paperDesk, useTrading } from './trading-session';

type Draft = { stake: string; multiplier: number };
type Preview = { asset: Asset; end: number; entry: number; lower: number; upper: number; stake: bigint; payout: bigint; multiplier: number };
const INITIAL_DRAFTS: Record<Asset, Draft> = { BTC: { stake: '10', multiplier: 2 }, HYPE: { stake: '10', multiplier: 25 }, ETH: { stake: '10', multiplier: 10 } };
const MARKET_CAST = {
  BTC: { name: 'Rose', caption: 'Bitcoin', image: '/art/dancer-rose-card.webp', accent: '#f7a6cf', logo: '/art/bitcoin.svg' },
  HYPE: { name: 'Mint', caption: 'Hyperliquid', image: '/art/dancer-mint-card.webp', accent: '#70efd0', logo: null },
  ETH: { name: 'Violet', caption: 'Ethereum', image: '/art/dancer-violet-card.webp', accent: '#bda7ff', logo: '/art/ethereum.svg' },
} satisfies Record<Asset, { name: string; caption: string; image: string; accent: string; logo: string | null }>;
const priceText = (value: number, asset: Asset) => new Intl.NumberFormat('en-US', { minimumFractionDigits: asset === 'HYPE' ? 4 : 2, maximumFractionDigits: asset === 'HYPE' ? 4 : 2 }).format(value / 1_000_000);

const MarketChart = memo(function MarketChart({ asset, observations, lower, upper, entry, remaining, active, pending, finished, available }: { asset: Asset; observations: number[]; lower: number; upper: number; entry: number; remaining: number; active: boolean; pending: boolean; finished: boolean; available: boolean }) {
  const minimum = Math.min(lower, ...observations), maximum = Math.max(upper, ...observations);
  const pad = Math.max((maximum - minimum) * .3, 1);
  const y = (value: number) => 315 - (value - minimum + pad) / (maximum - minimum + 2 * pad) * 275;
  const path = observations.map((value, i) => `${i ? 'H' : 'M'}${observations.length === 1 ? 751 : 16 + i * 735 / Math.max(1, observations.length - 1)}${i ? ' V' : ' '}${y(value)}`).join(' ');
  const seconds = active ? remaining : finished ? 0 : 30;
  return <div className={`market-chart ${active ? 'running' : ''}`}>
    <div className="chart-instruments"><span>oraclePx <span className="chart-interval">30s</span></span><span className="chart-clock" role="timer" aria-label={`${asset}: ${pending ? 'awaiting resolution' : `${seconds} seconds ${active ? 'remaining' : 'stage duration'}`}`}><Icon name="clock" size={12}/>{pending ? 'Resolving' : `00:${String(seconds).padStart(2, '0')}`}</span></div>
    {available ? <><svg className="market-plot" viewBox="0 0 900 360" preserveAspectRatio="none" role="img" aria-label={`${asset} ${engineEnabled ? 'polled' : 'demo'} oracle chart. Lower ${formatUsdc(lower)}, upper ${formatUsdc(upper)}.`}>
      {[75, 135, 195, 255, 315].map(value => <line key={value} x1="0" x2="900" y1={value} y2={value} stroke="#25262a" strokeDasharray="2 5"/>)}
      <rect x="0" y={y(upper)} width="900" height={Math.max(0, y(lower) - y(upper))} fill="currentColor" opacity=".045"/>
      {[upper, lower].map((value, i) => <line key={i} x1="0" x2="900" y1={y(value)} y2={y(value)} stroke="currentColor" strokeWidth="1" strokeDasharray="5 5"/>)}
      <line x1="0" x2="900" y1={y(entry)} y2={y(entry)} stroke="#5b5c62" strokeDasharray="2 5"/>
      <path className="chart-line-shadow" d={path} stroke="#0a1028" strokeWidth="4.5" vectorEffect="non-scaling-stroke" fill="none"/>
      <path d={path} stroke="#e8e7e2" strokeWidth="1.6" vectorEffect="non-scaling-stroke" fill="none"/>
      <circle cx="751" cy={y(observations.at(-1) || entry)} r="3" fill="currentColor"/>
    </svg><span className="barrier-price upper" style={{ top: `${y(upper) / 360 * 100}%` }}>{priceText(upper, asset)}</span><span className="barrier-price lower" style={{ top: `${y(lower) / 360 * 100}%` }}>{priceText(lower, asset)}</span><div className="chart-axis"><span>Recent observations</span><span>Now</span></div></> : <div className="market-feed-empty">Waiting for {asset} oracle<span>Entry unavailable until both feeds agree</span></div>}
    <div className="market-time-track" aria-hidden="true"><i style={{ width: `${active ? seconds / 30 * 100 : finished ? 0 : 100}%` }}/></div>
  </div>;
});

function MarketTerminal({ asset, draft, setDraft, preview, setPreview, degen, hidden, source }: { asset: Asset; draft: Draft; setDraft: (value: Draft) => void; preview?: Preview; setPreview: (value: Preview | undefined) => void; degen: boolean; hidden: boolean; source: (label: string) => void }) {
  const trading = useTrading();
  const { session, markets, observations, now, serverNow, identity } = trading;
  const market = markets[asset], fixture = MARKET_FIXTURES[asset];
  const [quote, setQuote] = useState<Quote | null>(null);
  const [accepted, setAccepted] = useState<Stage | null>(null);
  const [pendingEntry, setPendingEntry] = useState<{ quote: Quote; key: string } | null>(null);
  const [busy, setBusy] = useState(false), [error, setError] = useState('');
  const paperOrder = trading.paperOrders[asset];
  const inFlight = useRef(false);
  const remote = trading.stages.filter(stage => (stage.terms.asset || 'BTC') === asset).at(-1);
  const stage = accepted && (!remote || accepted.accepted_sequence > remote.accepted_sequence) ? accepted : remote;
  const active = engineEnabled ? stage?.status === 'active' || stage?.status === 'pending' : Boolean(preview && preview.end > now);
  const tick = Math.floor(now / 1000);
  const demo = useMemo(() => demoObservations(asset, tick), [asset, tick]);
  const values = engineEnabled ? observations[asset] : demo;
  const price = engineEnabled ? market?.oracle.price || 0 : demo.at(-1)!;
  const terms = payoutTerms(draft.stake, draft.multiplier);
  const visibleQuote = (active ? stage?.terms : null) || pendingEntry?.quote || quote;
  const model = visibleQuote?.pricing_rule === DEFAULT_DNT.rule && visibleQuote.volatility_30s_ppm
    ? { rule: visibleQuote.pricing_rule, volatility_30s_ppm: visibleQuote.volatility_30s_ppm, house_edge_bps: visibleQuote.house_edge_bps ?? 0 }
    : market?.policy.model.dnt || { ...DEFAULT_DNT, volatility_30s_ppm: fixture.volatility };
  const indicative = previewCorridor(draft.multiplier, price || fixture.price, model);
  const lower = visibleQuote?.lower ?? preview?.lower ?? indicative.lower;
  const upper = visibleQuote?.upper ?? preview?.upper ?? indicative.upper;
  const entry = visibleQuote?.entry_price ?? preview?.entry ?? indicative.price;
  const levelsAvailable = !engineEnabled || price > 0 || Boolean(visibleQuote);
  const remaining = Math.min(30, Math.max(0, Math.ceil(((engineEnabled ? stage?.expiry || 0 : preview?.end || 0) - (engineEnabled ? serverNow : now)) / 1000)));
  const locked = busy || active || pendingEntry !== null || Boolean(paperOrder?.pending || paperOrder?.busy);
  const valid = terms !== null && (!engineEnabled || Boolean(market && terms.stake >= BigInt(market.policy.min_stake) && terms.stake <= BigInt(market.policy.max_stake)));
  const fresh = Boolean(quote && serverNow < quote.valid_until && quote.policy_version === market?.policy.version && quote.oracle_sequence === market?.oracle.sequence);
  const payout = visibleQuote ? BigInt(visibleQuote.payout) : preview?.payout ?? terms?.payout;
  const stake = visibleQuote ? BigInt(visibleQuote.stake) : preview?.stake ?? terms?.stake;
  const finished = engineEnabled ? Boolean(stage && !active && !quote) : Boolean(preview && !active);
  const performer = MARKET_CAST[asset];
  const color = degen ? performer.accent : '#ff5059';

  useEffect(() => { setQuote(null); setAccepted(null); setPendingEntry(null); setBusy(false); setError(''); inFlight.current = false; }, [session?.wallet]);
  useEffect(() => {
    if (stage && (stage.status === 'active' || stage.status === 'pending')) {
      const amount = BigInt(stage.terms.stake);
      const fraction = (amount % 1_000_000n).toString().padStart(6, '0').replace(/0+$/, '');
      setDraft({ stake: `${amount / 1_000_000n}${fraction ? `.${fraction}` : ''}`, multiplier: validMultiplier(stage.terms.multiplier) ? stage.terms.multiplier : 2 });
      setQuote(null);
      if (pendingEntry?.quote.id === stage.terms.id) setPendingEntry(null);
    }
    // Accepted receipt changes are the only reason to restore a ticket.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [stage?.id, stage?.status]);

  function edit(value: Draft) { setDraft(value); setPreview(undefined); setQuote(null); setError(''); }
  async function requestQuote() {
    if (!session || !terms || locked || inFlight.current) return;
    inFlight.current = true; setBusy(true); setError(''); setQuote(null);
    const generation = identity.current;
    try {
      const receipt = await engineRequest<{ result: Quote }>('quotes', { token: session.token, key: crypto.randomUUID(), body: { amount: Number(terms.stake), multiplier: draft.multiplier, ...(asset === 'BTC' ? {} : { asset }) } });
      if (generation === identity.current) setQuote(receipt.result);
    } catch (cause) { if (generation === identity.current) setError(cause instanceof Error ? cause.message : 'Quote unavailable.'); }
    finally { inFlight.current = false; setBusy(false); }
  }
  async function enter() {
    if (!session || busy || inFlight.current || (!pendingEntry && (!quote || !fresh))) return;
    const command = pendingEntry || { quote: quote!, key: crypto.randomUUID() };
    inFlight.current = true; setPendingEntry(command); setBusy(true); setError('');
    const generation = identity.current;
    try {
      const receipt = await engineRequest<{ result: Stage }>('stages', { token: session.token, key: command.key, body: { id: command.quote.id } });
      if (generation === identity.current) { setAccepted(receipt.result); setQuote(null); setPendingEntry(null); trading.observeAcceptedStage(receipt.result); }
    } catch (cause) {
      if (generation !== identity.current) return;
      if (cause instanceof EngineError && cause.status >= 400 && cause.status < 500) { setPendingEntry(null); setQuote(null); }
      setError(cause instanceof Error ? cause.message : 'Entry uncertain. Retry this request.');
    } finally { inFlight.current = false; setBusy(false); }
  }
  function startPreview() {
    if (!terms || active) return;
    setPreview({ asset, end: Date.now() + 30_000, entry: indicative.price, lower: indicative.lower, upper: indicative.upper, stake: terms.stake, payout: terms.payout, multiplier: draft.multiplier });
  }
  return <section className={`market-terminal ${active ? 'has-position' : ''}`} data-asset={asset} hidden={hidden} style={{ '--market-accent': color } as React.CSSProperties} aria-label={`${asset} market`}>
    <header className="market-header"><div className="market-symbol"><span className="asset-code">{degen && performer.logo ? <img src={performer.logo} width="20" height="20" alt=""/> : asset.slice(0, 1)}</span><div><h2>{asset}<span>/ USDC</span></h2><span className="market-name">{fixture.name}</span></div></div><div className={`feed-state ${engineEnabled && !market?.healthy ? 'unavailable' : ''}`}><i/>{engineEnabled ? market?.healthy ? 'LIVE' : price > 0 ? 'SYNCING' : 'OFFLINE' : 'Demo'}</div></header>
    {degen ? <div className="market-world">
      <img className="market-world-image" src={performer.image} alt="" width="648" height="864" decoding="async"/>
      <div className="market-world-caption"><span>{performer.caption}</span><strong>{performer.name}</strong></div>
      <span className="market-world-index" aria-hidden="true">{String(ASSETS.indexOf(asset) + 1).padStart(2, '0')} / FUSE</span>
    </div> : null}
    <div className="market-body"><div className="market-chart-column"><div className="market-price-row"><strong>{price > 0 ? priceText(price, asset) : '—'}</strong><span>USD</span><button onClick={() => source('Payout multipliers')} className="market-info" aria-label={`${asset} barrier pricing details`}><Icon name="info" size={13}/></button></div>
      <MarketChart asset={asset} observations={values} lower={lower} upper={upper} entry={entry} remaining={remaining} active={active} pending={engineEnabled && active && (stage?.status === 'pending' || remaining === 0)} finished={finished && !engineEnabled} available={!engineEnabled || price > 0}/>
      <dl className="market-levels"><div><dt>Upper</dt><dd>{levelsAvailable ? priceText(upper, asset) : '—'}</dd></div><div><dt>Entry</dt><dd>{levelsAvailable ? priceText(entry, asset) : '—'}</dd></div><div><dt>Lower</dt><dd>{levelsAvailable ? priceText(lower, asset) : '—'}</dd></div></dl>
      <div className="chart-bottom-line"><span>{visibleQuote ? active ? 'Live stage barriers' : 'Quoted barriers' : preview ? 'Demo barriers fixed' : 'Next stage · indicative'}</span><button onClick={() => source('Payout multipliers')}>Rules <Icon name="external" size={10}/></button></div>
    </div><div className="market-ticket">
      <div className="ticket-topline"><h3>{active ? 'Fuse lit' : paperDesk ? 'Light the fuse' : 'Place a stage'}</h3><span>30s</span></div>
      {engineEnabled && stage && !active ? <div className="market-outcome" role="status">{stage.status === 'survived' ? `${formatUsdc(stage.terms.payout)} credited · ${stage.terms.multiplier}×` : stage.status === 'exploded' ? 'Barrier touched · stake lost' : 'Voided · stake returned'}</div> : finished && !engineEnabled ? <div className="market-outcome" role="status">Demo complete · no funds moved</div> : null}
      <label htmlFor={`stake-${asset}`}>Stake <span>USDC</span></label><div className="terminal-input"><input id={`stake-${asset}`} aria-label={`${asset} stake`} inputMode="decimal" maxLength={19} value={draft.stake} disabled={locked} onChange={e => edit({ ...draft, stake: e.target.value })}/><span>USDC</span></div>
      <div className="terminal-amounts">{['10', '25', '50', '100'].map(amount => <button key={amount} disabled={locked} onClick={() => edit({ ...draft, stake: amount })}>{amount}</button>)}</div>
      <label htmlFor={`payout-${asset}`}>Payout <span>includes stake</span></label><div className="terminal-select"><select id={`payout-${asset}`} aria-label={`${asset} payout`} value={draft.multiplier} disabled={locked} onChange={e => edit({ ...draft, multiplier: Number(e.target.value) })}>{PAYOUT_OPTIONS.map(value => <option key={value} value={value}>{value}×</option>)}</select><Icon name="down" size={13}/></div>
      <dl className="terminal-payoff"><div><dt>{degen ? 'Total return' : 'If you survive'}</dt><dd>{payout !== undefined ? formatUsdc(payout) : '—'}</dd></div><div><dt>Profit</dt><dd>{payout !== undefined && stake !== undefined ? `+${formatUsdc(payout - stake)}` : '—'}</dd></div><div><dt>Max loss</dt><dd>{stake !== undefined ? formatUsdc(stake) : '—'}</dd></div></dl>
      {!valid ? <p className="terminal-error" role="alert">{terms ? 'Outside market stake limits.' : 'Enter a positive stake, up to 6 decimals.'}</p> : null}
      {error ? <p className="terminal-error" role="alert">{error}</p> : null}
      {paperOrder?.error ? <p className="terminal-error" role="alert">{paperOrder.error}</p> : null}
      {engineEnabled ? !session ? <button className="terminal-submit" disabled={trading.connecting} onClick={trading.connect}>{paperDesk ? trading.connecting ? 'Starting…' : degen ? 'Start paper' : 'Start with 1,000 paper USDC' : 'Connect wallet'}</button> : paperDesk ? <button className="terminal-submit" disabled={paperOrder?.busy || active || (!paperOrder?.pending && (!valid || !market?.healthy))} onClick={() => terms && void trading.placePaper(asset, terms.stake, draft.multiplier)}>{paperOrder?.busy ? 'Lighting…' : active ? stage?.status === 'pending' || remaining === 0 ? 'Resolving…' : `${asset} fuse is lit` : paperOrder?.pending ? 'Retry same paper entry' : degen ? `Enter ${asset}` : `Send it · ${draft.multiplier}×`}<Icon name="bolt" size={13}/></button> : pendingEntry ? <button className="terminal-submit" disabled={busy} onClick={enter}>{busy ? 'Confirming…' : 'Retry same entry'}</button> : active ? <button className="terminal-submit" disabled>{stage?.status === 'pending' || remaining === 0 ? 'Resolving…' : 'Stage in progress'}</button> : <><button className={`terminal-submit ${quote ? 'secondary' : ''}`} disabled={!valid || busy || !market?.healthy || market.policy.product !== 'single-stage-v1'} onClick={requestQuote}>{busy ? 'Requesting…' : quote ? 'Refresh quote' : `Quote ${asset} · ${draft.multiplier}×`}</button>{quote ? <button className="terminal-submit" disabled={!fresh || busy || !market?.healthy} onClick={enter}>{fresh ? `Enter ${asset} · ${formatUsdc(quote.stake)}` : 'Quote expired · refresh'}</button> : null}</> : <><button className="terminal-submit" disabled={!valid || active} onClick={startPreview}>{active ? `${asset} preview running` : `Demo entry · ${draft.multiplier}×`}{!active ? <Icon name="arrow" size={14}/> : null}</button>{active ? <button className="terminal-stop" onClick={() => setPreview(undefined)}>Stop {asset} preview</button> : null}</>}
      <p className="terminal-fineprint">{degen ? 'Payout includes stake. ' : ''}Touch either barrier and lose the stake.</p>
    </div></div>
  </section>;
}

export function Trade({ source, degen, enableDegen }: { source: (label: string) => void; degen: boolean; enableDegen: () => void }) {
  const trading = useTrading();
  const [selectedAsset, setSelectedAsset] = useState<Asset>('BTC');
  const [drafts, setDrafts] = useState(INITIAL_DRAFTS);
  const [previews, setPreviews] = useState<Partial<Record<Asset, Preview>>>({});
  const [positionsTab, setPositionsTab] = useState<'open' | 'history'>('open');
  const [music, setMusic] = useState(true);
  const activeStages = trading.stages.filter(stage => stage.status === 'active' || stage.status === 'pending');
  const previewStages = Object.values(previews).filter((stage): stage is Preview => Boolean(stage && stage.end > trading.now));
  const activeCount = engineEnabled ? activeStages.length : previewStages.length;
  const exposure = engineEnabled ? activeStages.reduce((total, stage) => total + BigInt(stage.terms.stake), 0n) : previewStages.reduce((total, stage) => total + stage.stake, 0n);
  const visibleAssets: readonly Asset[] = degen ? ASSETS : [selectedAsset];
  const ticketStake = visibleAssets.reduce((total, asset) => total + (payoutTerms(drafts[asset].stake, drafts[asset].multiplier)?.stake || 0n), 0n);
  const allPayout = visibleAssets.reduce((total, asset) => total + (payoutTerms(drafts[asset].stake, drafts[asset].multiplier)?.payout || 0n), 0n);
  const otherCount = engineEnabled ? activeStages.filter(stage => (stage.terms.asset || 'BTC') !== selectedAsset).length : previewStages.filter(stage => stage.asset !== selectedAsset).length;
  const completed = trading.stages.filter(stage => stage.status !== 'active' && stage.status !== 'pending').slice().reverse();
  const displayedStages = positionsTab === 'history' ? completed : activeStages;
  const readyAll = paperDesk && Boolean(trading.session) && activeCount === 0 && ASSETS.every(asset => {
    const terms = payoutTerms(drafts[asset].stake, drafts[asset].multiplier), market = trading.markets[asset];
    return terms && market?.healthy && terms.stake >= BigInt(market.policy.min_stake) && terms.stake <= BigInt(market.policy.max_stake) && !trading.paperOrders[asset]?.pending;
  });
  const balance = trading.account?.account;
  async function enterAll() {
    if (!readyAll) return;
    await Promise.allSettled(ASSETS.map(asset => {
      const terms = payoutTerms(drafts[asset].stake, drafts[asset].multiplier)!;
      return trading.placePaper(asset, terms.stake, drafts[asset].multiplier);
    }));
  }
  return <div className={`trading-desk ${degen ? 'degen-desk' : 'standard-desk'} ${music ? 'party-on' : 'party-off'}`}>
    <h1 className="sr-only">{degen ? 'Degen trading desk: BTC, HYPE and ETH' : `${selectedAsset} trading terminal`}</h1>
    <div className="desk-toolbar"><div className="desk-tabs">{degen ? <span className="desk-tab selected">DEGEN</span> : <div className="desk-tab selected market-picker"><label htmlFor="standard-market" className="sr-only">Market</label><select id="standard-market" value={selectedAsset} onChange={event => setSelectedAsset(event.target.value as Asset)}>{ASSETS.map(asset => <option key={asset} value={asset}>{asset} / USDC</option>)}</select><Icon name="down" size={13}/></div>}<span className="desk-contract">{degen ? 'AFTER HOURS / 30s' : '30s double-no-touch'}</span>{degen ? <button className="club-motion" aria-label={music ? 'Pause DJ music' : 'Play DJ music'} aria-pressed={music} onClick={() => setMusic(value => !value)}><img src="/art/dj-cat.png" alt="" width="40" height="40"/><span>{music ? 'DJ ON' : 'DJ OFF'}</span></button> : null}</div><div className="desk-status"><span className={engineEnabled ? 'live-label' : 'demo-label'}>{engineEnabled ? `${ASSETS.filter(asset => trading.markets[asset]?.healthy).length}/3 FEEDS READY` : 'DEMO'}</span><span>{paperDesk ? 'PAPER FUNDS' : !engineEnabled ? 'No funds move' : 'USDC settlement'}</span></div></div>
    {degen ? <div className="degen-lounge"><ClubMusic playing={music}/><CharacterStage reaction={trading.avatarReaction}/></div> : null}
    <div className={degen ? 'degen-overview' : undefined}>
    {paperDesk ? <div className="paper-account-strip"><div><span>Paper equity</span><strong>{balance ? formatUsdc(balance.economic_balance) : '—'}</strong></div><div><span>Available</span><b>{balance ? formatUsdc(balance.balances.available + balance.balances.unfunded) : '—'}</b></div><div><span>Stakes in play</span><b>{formatUsdc(exposure)}</b></div><div><span>Realized P&amp;L</span><b className={balance && balance.economic_balance < 1_000_000_000 ? 'pnl-negative' : 'pnl-positive'}>{balance ? `${balance.economic_balance < 1_000_000_000 ? '−' : '+'}${formatUsdc(Math.abs(balance.economic_balance - 1_000_000_000))}` : '—'}</b></div><span className="paper-account-caption">Live prices.<br/>Zero real money.</span></div> : null}
    {degen ? <div className="degen-summary"><span className="degen-market-label">BTC / HYPE / ETH <span>·</span> 3 independent fuses</span><div><span>Total stake <b>{formatUsdc(ticketStake)}</b></span><span>If all survive <b>{formatUsdc(allPayout)}</b></span>{paperDesk ? <button className="enter-all" disabled={!readyAll} onClick={() => void enterAll()}>Enter all 3 <Icon name="arrow" size={13}/></button> : <span className="risk-total">{engineEnabled ? 'At risk' : 'Demo stake'} <b>{formatUsdc(exposure)}</b></span>}</div></div> : otherCount > 0 ? <button className="background-positions" onClick={enableDegen}>{otherCount} other market stage{otherCount > 1 ? 's' : ''} running · Open Degen mode <Icon name="arrow" size={12}/></button> : null}
    </div>
    {engineEnabled && trading.account && !paperDesk ? <div className="desk-balances"><span>Funded USDC <b>{formatUsdc(trading.account.account.balances.available)}</b></span><span>Winnings awaiting funding <b>{formatUsdc(trading.account.account.balances.unfunded)}</b></span></div> : null}
    {trading.error ? <p className="desk-error" role="alert">{trading.error}</p> : null}
    <div className={`market-grid ${degen ? 'three-markets' : 'one-market'}`}>
      {ASSETS.map(asset => <MarketTerminal key={asset} asset={asset} draft={drafts[asset]} setDraft={value => setDrafts(previous => ({ ...previous, [asset]: value }))} preview={previews[asset]} setPreview={value => setPreviews(previous => ({ ...previous, [asset]: value }))} degen={degen} hidden={!degen && asset !== selectedAsset} source={source}/>)}
    </div>
    <section className="positions-panel" aria-label="Stages and history"><div className="positions-heading"><div className="position-tabs" role="tablist" aria-label="Trading activity"><button role="tab" aria-selected={positionsTab === 'open'} onClick={() => setPositionsTab('open')}>Positions <span>{activeCount}</span></button><button role="tab" aria-selected={positionsTab === 'history'} onClick={() => setPositionsTab('history')}>History <span>{completed.length}</span></button></div><span>{engineEnabled ? `At risk ${formatUsdc(exposure)}` : 'Demo positions'}</span></div><div className="positions-scroll"><table><thead><tr><th>MARKET</th><th>STAKE</th><th>PAYOUT</th><th>{positionsTab === 'history' ? 'RETURNED' : 'TIME LEFT'}</th><th>STATUS</th></tr></thead><tbody>{engineEnabled ? displayedStages.map(stage => <tr key={stage.id}><td><i className="market-dot" style={{ background: MARKET_FIXTURES[stage.terms.asset].color }}/>{stage.terms.asset} / USDC</td><td>{formatUsdc(stage.terms.stake)}</td><td>{stage.terms.multiplier}× · {formatUsdc(stage.terms.payout)}</td><td>{positionsTab === 'history' ? formatUsdc(stage.status === 'survived' ? stage.terms.payout : stage.status === 'voided' ? stage.terms.stake : 0) : `${Math.max(0, Math.ceil((stage.expiry - trading.serverNow) / 1000))}s`}</td><td><span className={`stage-status status-${stage.status}`}>{stage.status === 'survived' ? 'WON' : stage.status === 'exploded' ? 'BUST' : stage.status === 'voided' ? 'REFUNDED' : stage.status === 'pending' ? 'RESOLVING' : 'IN PLAY'}</span></td></tr>) : positionsTab === 'open' ? previewStages.map(stage => <tr key={stage.asset}><td>{stage.asset} / USDC</td><td>{formatUsdc(stage.stake)}</td><td>{stage.multiplier}× · {formatUsdc(stage.payout)}</td><td>{Math.max(0, Math.ceil((stage.end - trading.now) / 1000))}s</td><td>Preview</td></tr>) : null}</tbody></table>{(engineEnabled ? displayedStages.length === 0 : positionsTab === 'history' || activeCount === 0) ? <div className="positions-empty"><strong>{positionsTab === 'history' ? 'Every fuse leaves a mark.' : 'Nothing on the line. Yet.'}</strong><span>{positionsTab === 'history' ? 'Finished stages and their actual returns appear here.' : paperDesk ? 'Choose your payouts above. Paper stakes, real market moves.' : 'Your open stages appear here.'}</span></div> : null}</div></section>
    <div className="desk-bottom"><span>{paperDesk ? 'HyperCore oraclePx · live market prices · virtual USDC only' : engineEnabled ? 'Quotes and outcomes are server-authoritative.' : 'Sample market replay. Prices and entries are demonstrations.'}</span><button onClick={() => source('Payout multipliers')}>The rules <Icon name="external" size={10}/></button></div>
  </div>;
}
