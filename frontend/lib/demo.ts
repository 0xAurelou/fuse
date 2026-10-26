// Design fixtures only. Never pass these values off as live protocol accounting.
export const SNAPSHOT = { id: 'demo-20261026-0842', asOf: '2026-10-26T08:42:00Z', policy: 'single-stage-preview-v2', grade: 'DEMO DATA' } as const;
export type Period = '24H' | '7D' | '30D' | '90D';
export const periods: Period[] = ['24H', '7D', '30D', '90D'];
export const datasets: Record<Period, { turnover: number; initialRisk: number; pnl: number; equity: number; reserve: number; survival: number; stages: number; wallets: number; required: number }> = {
  '24H': { turnover: 1248530, initialRisk: 1248530, pnl: 18432, equity: 286420, reserve: 64312, survival: 47.82, stages: 28416, wallets: 1842, required: 107408 },
  '7D': { turnover: 8624500, initialRisk: 8624500, pnl: 74920, equity: 286420, reserve: 64312, survival: 48.13, stages: 193426, wallets: 6920, required: 107408 },
  '30D': { turnover: 34812560, initialRisk: 34812560, pnl: 192340, equity: 286420, reserve: 64312, survival: 48.06, stages: 784820, wallets: 18432, required: 107408 },
  '90D': { turnover: 78540200, initialRisk: 78540200, pnl: 384250, equity: 286420, reserve: 64312, survival: 47.94, stages: 1748200, wallets: 34682, required: 107408 },
};
export const money = (value: number, decimals = 0) => new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: decimals, minimumFractionDigits: decimals }).format(value);
export const count = (value: number) => new Intl.NumberFormat('en-US').format(value);
export const compact = (value: number) => new Intl.NumberFormat('en-US', { notation: 'compact', maximumFractionDigits: 2 }).format(value);
export const series = [22, 25, 24, 29, 26, 31, 34, 30, 35, 38, 34, 37, 33, 39, 43, 38, 44, 42, 49, 46, 50, 45, 52, 49, 54, 58, 52, 59, 55, 62, 59, 65, 61, 67, 63, 71, 68, 73, 70, 78, 75, 82, 78, 85, 81, 90, 86, 94];
export const events = [
  { id: 'EP-00842', time: '08:42:00', name: 'Settlement checkpoint', detail: 'Epoch 842 · 1,284 stage receipts', amount: '+$2,184.62', state: 'Journal fixture', icon: 'layers' },
  { id: 'RF-00841', time: '08:38:24', name: 'FUSE reserve funding', detail: 'LP vault → segregated reserve', amount: '+$764.62', state: 'Transfer fixture', icon: 'arrow' },
  { id: 'RN-14829', time: '08:36:12', name: '100× stage survived', detail: 'One 30-second stage · $10 stake · 100× payout', amount: '$1,000.00', state: 'Outcome fixture', icon: 'bolt' },
  { id: 'EP-00841', time: '08:30:00', name: 'Settlement checkpoint', detail: 'Epoch 841 · 1,106 stage receipts', amount: '+$1,842.18', state: 'Journal fixture', icon: 'layers' },
] as const;
export function exportRows(period: Period) {
  const d = datasets[period];
  return Object.entries(d).map(([metric, value]) => ({ snapshot: SNAPSHOT.id, asOf: SNAPSHOT.asOf, period, grade: SNAPSHOT.grade, metric, value }));
}
export function snapshotCsv(period: Period) {
  return ['snapshot,asOf,period,grade,metric,value', ...exportRows(period).map(row => Object.values(row).join(','))].join('\n');
}
export function parseUsdc(value: string): bigint | null {
  if (!/^\d+(\.\d{0,6})?$/.test(value)) return null;
  const [whole, fraction = ''] = value.split('.');
  const result = BigInt(whole) * 1_000_000n + BigInt(fraction.padEnd(6, '0'));
  return result > 0n ? result : null;
}
