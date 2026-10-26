import { parseUsdc } from './demo.ts';

export const PAYOUT_OPTIONS: readonly number[] = [2, 5, 10, 25, 50, 100, 250, 1000, 10000];
export const MIN_MULTIPLIER = PAYOUT_OPTIONS[0];
export const MAX_MULTIPLIER = PAYOUT_OPTIONS[PAYOUT_OPTIONS.length - 1];
export const DEFAULT_DNT = { rule: 'brownian-first-mode-v1', volatility_30s_ppm: 1000, house_edge_bps: 500 } as const;
export const ENGINE_LIMIT = 1_000_000_000_000_000n;
export const ASSETS = ['BTC', 'HYPE', 'ETH'] as const;
export type Asset = typeof ASSETS[number];
export const MARKET_FIXTURES: Record<Asset, { name: string; price: number; volatility: number; color: string }> = {
  BTC: { name: 'Bitcoin', price: 68_492_500_000, volatility: 1000, color: '#e7a64d' },
  HYPE: { name: 'Hyperliquid', price: 38_420_000, volatility: 3000, color: '#8fe1c4' },
  ETH: { name: 'Ethereum', price: 3_482_750_000, volatility: 1500, color: '#a3abdd' },
};

export function demoObservations(asset: Asset, tick: number): number[] {
  const market = MARKET_FIXTURES[asset];
  const seed = ASSETS.indexOf(asset) * 7919 + 127;
  const noise = (index: number) => {
    let value = Math.imul(index + seed, 0x45d9f3b);
    value = Math.imul(value ^ (value >>> 16), 0x45d9f3b);
    return ((value ^ (value >>> 16)) >>> 0) / 0xffffffff * 2 - 1;
  };
  return Array.from({ length: 64 }, (_, i) => {
    const at = Math.max(64, tick) - 63 + i;
    const segment = Math.floor(at / 9), progress = at % 9 / 9;
    const sample = noise(segment) * (1 - progress) + noise(segment + 1) * progress + noise(at * 31) * .16;
    return market.price + Math.floor(market.price * sample * market.volatility / 1_000_000);
  });
}

export function validMultiplier(value: number): boolean {
  return PAYOUT_OPTIONS.includes(value);
}

// Payout includes the stake. All money stays in integer USDC atomic units.
export function payoutTerms(stake: string, multiplier: number) {
  const amount = parseUsdc(stake);
  if (amount === null || !validMultiplier(multiplier)) return null;
  const payout = amount * BigInt(multiplier);
  if (payout > ENGINE_LIMIT) return null;
  return { stake: amount, payout, profit: payout - amount };
}

export function formatUsdc(amount: bigint | number): string {
  const value = BigInt(amount);
  const fraction = (value % 1_000_000n).toString().padStart(6, '0').replace(/0+$/, '').padEnd(2, '0');
  return `$${(value / 1_000_000n).toLocaleString('en-US')}.${fraction}`;
}

export type DNTModel = { rule: string; volatility_30s_ppm: number; house_edge_bps: number };
const Q = 1_000_000_000_000n;
const PI = 3_141_592_653_590n;
const LN2 = 693_147_180_560n;

function integerSqrt(value: bigint): bigint {
  if (value < 2n) return value;
  let result = value, next = (result + 1n) / 2n;
  while (next < result) { result = next; next = (result + value / result) / 2n; }
  return result;
}

// Same bounded Q12 logarithm and integer square root as the Go quote engine.
export function brownianWidthPPB(multiplier: number, model: DNTModel = DEFAULT_DNT): number {
  if (!validMultiplier(multiplier)) throw new Error('Choose 2×, 5×, 10×, 25×, 50×, 100×, 250×, 1000× or 10000×.');
  if (model.rule !== DEFAULT_DNT.rule || !Number.isInteger(model.volatility_30s_ppm) || model.volatility_30s_ppm < 1 || model.volatility_30s_ppm > 100_000 || !Number.isInteger(model.house_edge_bps) || model.house_edge_bps < 0 || model.house_edge_bps > 5000) throw new Error('Invalid barrier pricing assumptions.');
  const retainedPi = PI * BigInt(10_000 - model.house_edge_bps) / 10_000n;
  let ratio = 4n * BigInt(multiplier) * Q * Q / retainedPi, powers = 0n;
  while (ratio >= 2n * Q) { ratio /= 2n; powers++; }
  const z = (ratio - Q) * Q / (ratio + Q), z2 = z * z / Q;
  let term = z, sum = z;
  for (let n = 3n; n <= 63n; n += 2n) { term = term * z2 / Q; sum += term / n; }
  const logarithm = 2n * sum + powers * LN2;
  return Number(BigInt(model.volatility_30s_ppm) * 1000n * PI / integerSqrt(8n * logarithm * Q));
}

export function previewCorridor(multiplier: number, price = 68_492_500_000, model: DNTModel = DEFAULT_DNT) {
  const widthPPB = brownianWidthPPB(multiplier, model);
  const delta = Number(BigInt(price) * BigInt(widthPPB) / 1_000_000_000n);
  return { price, lower: price - delta, upper: price + delta, widthPPB };
}

export type Quote = {
  asset: Asset; id: string; product: 'single-stage-v1'; multiplier: number; stake: number; payout: number;
  oracle_sequence: number; entry_price: number; lower: number; upper: number; duration_ms: number;
  valid_until: number; policy_version: string; model_version: string;
  pricing_rule?: string; volatility_30s_ppm?: number; house_edge_bps?: number; target_survival_ppb?: number; width_ppb?: number;
};
export type Stage = {
  id: string; accepted_sequence: number; terms: Quote; start: number; expiry: number;
  status: 'active' | 'pending' | 'survived' | 'exploded' | 'voided';
};
export type Market = {
  asset: Asset;
  server_time: number; healthy: boolean; oracle: { price: number; sequence: number };
  policy: { product?: string; mode: string; min_stake: number; max_stake: number; version: string; model: { dnt?: DNTModel } };
};
export type Account = { account: { economic_balance: number; balances: { available: number; unfunded: number } } };

export class EngineError extends Error {
  status: number;
  constructor(message: string, status: number) { super(message); this.status = status; }
}

export async function engineRequest<T>(path: string, options: { token?: string; body?: unknown; key?: string; signal?: AbortSignal } = {}): Promise<T> {
  const response = await fetch(`/engine/v1/${path}`, {
    method: options.body === undefined ? 'GET' : 'POST', cache: 'no-store', signal: options.signal,
    headers: { ...(options.body === undefined ? {} : { 'Content-Type': 'application/json' }), ...(options.token ? { Authorization: `Bearer ${options.token}` } : {}), ...(options.key ? { 'Idempotency-Key': options.key } : {}) },
    ...(options.body === undefined ? {} : { body: JSON.stringify(options.body) }),
  });
  const data = await response.json().catch(() => { throw new EngineError('Gateway response unavailable.', response.status); });
  if (!response.ok) throw new EngineError(data.error || 'Engine request failed.', response.status);
  return data as T;
}
