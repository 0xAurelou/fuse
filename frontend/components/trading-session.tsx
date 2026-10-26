'use client';

import { createContext, useContext, useEffect, useRef, useState, type ReactNode, type RefObject } from 'react';
import { ASSETS, EngineError, engineRequest, type Account, type Asset, type Market, type Stage } from '@/lib/trading';
import { createAvatarCursor, observeAvatarStages, type AvatarReaction } from '@/lib/avatar-events';

type Provider = { request: (args: { method: string; params?: unknown[] }) => Promise<unknown>; on?: (event: string, handler: () => void) => void; removeListener?: (event: string, handler: () => void) => void };
type Session = { token: string; wallet: string };
type PaperCommand = { key: string; body: { asset: Asset; amount: number; multiplier: number } };
type PaperOrder = { pending: boolean; busy: boolean; error: string };
export const engineEnabled = process.env.NEXT_PUBLIC_ENGINE_ENABLED === 'true';
export const paperDesk = engineEnabled && process.env.NEXT_PUBLIC_PAPER_DESK === 'true';
type TradingState = {
  session: Session | null; markets: Partial<Record<Asset, Market>>; account: Account | null; stages: Stage[];
  observations: Record<Asset, number[]>; now: number; serverNow: number; connecting: boolean; error: string;
  identity: RefObject<number>; connect: () => Promise<void>; refresh: () => void;
  paperOrders: Partial<Record<Asset, PaperOrder>>; placePaper: (asset: Asset, amount: bigint, multiplier: number) => Promise<void>;
  avatarReaction: AvatarReaction | null; observeAcceptedStage: (stage: Stage) => void;
};
const TradingContext = createContext<TradingState | null>(null);

export function TradingProvider({ children, enabled }: { children: ReactNode; enabled: boolean }) {
  const [session, setSession] = useState<Session | null>(null);
  const [markets, setMarkets] = useState<Partial<Record<Asset, Market>>>({});
  const [account, setAccount] = useState<Account | null>(null);
  const [stages, setStages] = useState<Stage[]>([]);
  const [observations, setObservations] = useState<Record<Asset, number[]>>({ BTC: [], ETH: [], HYPE: [] });
  const [now, setNow] = useState(0);
  const [connecting, setConnecting] = useState(false);
  const [error, setError] = useState('');
  const identity = useRef(0), offset = useRef(0);
  const [revision, setRevision] = useState(0);
  const connectingRef = useRef(false);
  const commands = useRef<Partial<Record<Asset, PaperCommand>>>({});
  const inFlight = useRef<Partial<Record<Asset, boolean>>>({});
  const accepted = useRef<Partial<Record<Asset, Stage>>>({});
  const [paperOrders, setPaperOrders] = useState<Partial<Record<Asset, PaperOrder>>>({});
  const avatarCursor = useRef(createAvatarCursor());
  const [avatarReaction, setAvatarReaction] = useState<AvatarReaction | null>(null);

  useEffect(() => { avatarCursor.current = createAvatarCursor(); setAvatarReaction(null); }, [session?.wallet]);
  function observeAcceptedStage(stage: Stage) {
    const reaction = observeAvatarStages(avatarCursor.current, [stage], Date.now(), true);
    if (reaction) setAvatarReaction(reaction);
  }

  useEffect(() => { setNow(Date.now()); const timer = setInterval(() => setNow(Date.now()), 250); return () => clearInterval(timer); }, []);
  useEffect(() => {
    if (paperDesk) return;
    const provider = (window as Window & { ethereum?: Provider }).ethereum;
    const reset = () => { identity.current++; setSession(null); setStages([]); setAccount(null); setConnecting(false); };
    provider?.on?.('accountsChanged', reset); provider?.on?.('chainChanged', reset);
    return () => { provider?.removeListener?.('accountsChanged', reset); provider?.removeListener?.('chainChanged', reset); };
  }, []);

  useEffect(() => {
    if (!paperDesk || !enabled) return;
    try { if (sessionStorage.getItem('fuse:paper-secret:v1')) void connect(); } catch { /* The start button also works without preference storage. */ }
    // A stored account resumes once on mount. A 401 waits for an explicit reconnect.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled]);

  useEffect(() => {
    if (!engineEnabled || !enabled) return;
    const controller = new AbortController(); let timer: ReturnType<typeof setTimeout>;
    async function marketSnapshot() {
      try { return await engineRequest<{ markets: Market[]; server_time: number }>('markets', { signal: controller.signal }); }
      catch (cause) {
        if (!(cause instanceof EngineError) || cause.status !== 404) throw cause;
        const btc = await engineRequest<Market>('oracle', { signal: controller.signal });
        return { markets: [{ ...btc, asset: 'BTC' as Asset }], server_time: btc.server_time };
      }
    }
    async function poll() {
      try {
        const [snapshot, balance, positions] = await Promise.all([
          marketSnapshot(),
          session ? engineRequest<Account>('account', { token: session.token, signal: controller.signal }) : Promise.resolve(null),
          session ? engineRequest<Stage[]>('stages', { token: session.token, signal: controller.signal }) : Promise.resolve([]),
        ]);
        if (controller.signal.aborted) return;
        offset.current = snapshot.server_time - Date.now();
        setMarkets(Object.fromEntries(snapshot.markets.map(market => [market.asset, market])));
        const merged = [...positions];
        for (const receipt of Object.values(accepted.current)) if (!merged.some(stage => stage.accepted_sequence >= receipt.accepted_sequence && stage.terms.asset === receipt.terms.asset)) merged.push(receipt);
        merged.sort((a, b) => a.accepted_sequence - b.accepted_sequence);
        const reaction = observeAvatarStages(avatarCursor.current, merged, Date.now());
        if (reaction) setAvatarReaction(reaction);
        setAccount(balance); setStages(merged); setError('');
        setObservations(previous => {
          const next = { ...previous };
          for (const market of snapshot.markets) if (ASSETS.includes(market.asset) && market.oracle.price > 0) next[market.asset] = [...previous[market.asset].slice(-119), market.oracle.price];
          return next;
        });
      } catch (cause) {
        if (!controller.signal.aborted) {
          setMarkets({});
          if (cause instanceof EngineError && cause.status === 401) { identity.current++; accepted.current = {}; setSession(null); setAccount(null); setStages([]); }
          setError(cause instanceof Error ? cause.message : 'Gateway unavailable.');
        }
      } finally { if (!controller.signal.aborted) timer = setTimeout(poll, 1000); }
    }
    void poll(); return () => { controller.abort(); clearTimeout(timer); };
  }, [session, enabled, revision]);

  async function connect() {
    if (connectingRef.current) return;
    if (!engineEnabled) { setError('Wallet trading is available when the engine is connected. This is a demo.'); return; }
    connectingRef.current = true; setConnecting(true); setError('');
    try {
      if (paperDesk) {
        let secret: string | null = null;
        try { secret = sessionStorage.getItem('fuse:paper-secret:v1'); } catch { /* In-memory account still works. */ }
        if (!secret) {
          secret = Array.from(crypto.getRandomValues(new Uint8Array(32)), n => n.toString(16).padStart(2, '0')).join('');
          try { sessionStorage.setItem('fuse:paper-secret:v1', secret); } catch { /* Optional persistence. */ }
        }
        const generation = identity.current;
        const paper = await engineRequest<Session>('paper/session', { body: { secret } });
        if (generation === identity.current) { accepted.current = {}; setSession(paper); setRevision(value => value + 1); }
        return;
      }
      const provider = (window as Window & { ethereum?: Provider }).ethereum;
      if (!provider) throw new Error('Use an Ethereum wallet extension to connect.');
      const wallets = await provider.request({ method: 'eth_requestAccounts' }) as string[];
      const wallet = wallets[0]; if (!wallet) throw new Error('No wallet selected.');
      const generation = identity.current;
      const challenge = await engineRequest<{ id: string; message: string }>('auth/challenge', { body: { account: wallet } });
      const message = `0x${Array.from(new TextEncoder().encode(challenge.message), n => n.toString(16).padStart(2, '0')).join('')}`;
      const signature = await provider.request({ method: 'personal_sign', params: [message, wallet] });
      const verified = await engineRequest<{ token: string }>('auth/verify', { body: { id: challenge.id, signature } });
      if (generation === identity.current) setSession({ token: verified.token, wallet });
    } catch (cause) { setError(cause instanceof Error ? cause.message : 'Wallet connection failed.'); }
    finally { connectingRef.current = false; setConnecting(false); }
  }

  async function placePaper(asset: Asset, amount: bigint, multiplier: number) {
    if (!paperDesk || !session || inFlight.current[asset]) return;
    const command = commands.current[asset] || { key: crypto.randomUUID(), body: { asset, amount: Number(amount), multiplier } };
    commands.current[asset] = command; inFlight.current[asset] = true;
    setPaperOrders(previous => ({ ...previous, [asset]: { pending: true, busy: true, error: '' } }));
    const generation = identity.current;
    try {
      const receipt = await engineRequest<{ result: Stage }>('paper/entries', { token: session.token, key: command.key, body: command.body });
      if (generation !== identity.current) return;
      accepted.current[asset] = receipt.result;
      observeAcceptedStage(receipt.result);
      setStages(previous => [...previous.filter(stage => stage.id !== receipt.result.id), receipt.result].sort((a, b) => a.accepted_sequence - b.accepted_sequence));
      delete commands.current[asset];
      setPaperOrders(previous => ({ ...previous, [asset]: { pending: false, busy: false, error: '' } }));
      setRevision(value => value + 1);
    } catch (cause) {
      if (generation !== identity.current) return;
      if (cause instanceof EngineError && cause.status >= 400 && cause.status < 500) delete commands.current[asset];
      setPaperOrders(previous => ({ ...previous, [asset]: { pending: Boolean(commands.current[asset]), busy: false, error: cause instanceof Error ? cause.message : 'Entry uncertain. Retry the same entry.' } }));
    } finally { inFlight.current[asset] = false; }
  }

  return <TradingContext.Provider value={{ session, markets, account, stages, observations, now, serverNow: now + offset.current, connecting, error, identity, connect, refresh: () => setRevision(value => value + 1), paperOrders, placePaper, avatarReaction, observeAcceptedStage }}>{children}</TradingContext.Provider>;
}

export function useTrading() {
  const context = useContext(TradingContext);
  if (!context) throw new Error('TradingProvider is required.');
  return context;
}
