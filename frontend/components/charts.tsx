'use client';
import { useId, useState } from 'react';
import { money, series } from '@/lib/demo';
export function Sparkline({ alternate = false }: { alternate?: boolean }) {
  const points = series.filter((_, i) => i % 2 === 0).map((n, i) => `${i * 4},${36 - (alternate ? n * .23 + Math.sin(i) * 6 : n * .3)}`).join(' ');
  return <svg className="sparkline" viewBox="0 0 94 40" aria-hidden="true"><polyline points={points} fill="none" stroke="currentColor" strokeWidth="1.5"/></svg>;
}
export function PerformanceChart({ value, period, mode }: { value: number; period: string; mode: 'pnl' | 'turnover' }) {
  const id = useId().replaceAll(':', '');
  const [hover, setHover] = useState<number | null>(null);
  const points = series.map((n, i) => [i * 700 / (series.length - 1), 212 - (n - 18) * 2.1]);
  const line = points.map(([x, y], i) => `${i ? 'L' : 'M'}${x.toFixed(1)} ${y.toFixed(1)}`).join(' ');
  return <div className="performance-chart">
    <div className="chart-ylabels">{[1, .75, .5, .25].map(n => <span key={n}>{money(value * n).replace(',000', 'K')}</span>)}</div>
    <div className="plot-wrap" onMouseLeave={() => setHover(null)}>
      <svg viewBox="0 0 700 230" preserveAspectRatio="none" role="img" aria-label={`${period} illustrative ${mode === 'pnl' ? 'net trading PnL' : 'stage turnover'}: ${money(value)}. Demo fixture, not actual results.`} onMouseMove={e => { const r = e.currentTarget.getBoundingClientRect(); setHover(Math.min(47, Math.max(0, Math.round((e.clientX - r.left) / r.width * 47)))); }}>
        <defs><linearGradient id={id} x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#ff303b" stopOpacity=".2"/><stop offset="100%" stopColor="#ff303b" stopOpacity="0"/></linearGradient></defs>
        {[25, 80, 135, 190].map(y => <line key={y} x1="0" x2="700" y1={y} y2={y} stroke="#262529" strokeDasharray="3 5"/>)}
        <path d={`${line} L700 230 L0 230 Z`} fill={`url(#${id})`}/>
        <path d={line} stroke="#ff3540" strokeWidth="2.4" fill="none" vectorEffect="non-scaling-stroke"/>
        {hover !== null ? <><line x1={points[hover][0]} x2={points[hover][0]} y1="0" y2="230" stroke="#777" strokeDasharray="3 4"/><circle cx={points[hover][0]} cy={points[hover][1]} r="4" fill="#ff3540" stroke="#f9ced0" strokeWidth="2"/></> : <circle cx="700" cy={points[47][1]} r="4" fill="#ff3540"/>}
      </svg>
      {hover !== null ? <div className="chart-tooltip" style={{ left: `${Math.min(78, hover / 47 * 90)}%` }}>Sample {hover + 1} <b>{money(value * (series[hover] - 18) / 76)}</b><small>Illustrative curve · {period}</small></div> : null}
      <div className="chart-xlabels">{(period === '24H' ? ['09:00', '13:00', '17:00', '21:00', '01:00', '05:00', '08:42'] : ['Start', '20%', '40%', '60%', '80%', 'Latest']).map(label => <span key={label}>{label}</span>)}</div>
    </div>
  </div>;
}
export function MultiplierMix() {
  const values = [44, 26, 16, 8, 4, 2];
  const multipliers = [2, 5, 10, 25, 50, 100];
  return <div className="funnel-chart" role="img" aria-label="Illustrative share of accepted stages by payout multiplier. These are entry proportions, not win probabilities.">
    <div className="funnel-bars">{values.map((v, i) => <div className="funnel-col" key={i}><span>{v}%</span><div className="funnel-bar" style={{ height: `${24 + Math.sqrt(v) * 16}px`, opacity: 1 - i * .1 }}/><small>{multipliers[i]}×</small></div>)}</div>
    <div className="chart-footnote"><span>Share of accepted stages · demo mix</span><span>2× → 100×</span></div>
  </div>;
}
export function Heatmap() {
  return <div className="heatmap"><div className="heatmap-cols"><span/><span>30s</span><span>1m</span><span>2m</span><span>5m</span><span>10m</span></div>{[2, 10, 50, 100].map((s) => <div className="heatmap-row" key={s}><span>{s}×</span>{[0, 1, 2, 3, 4].map(i => <div key={i} tabIndex={0} aria-label={`Demo ${s}× payout, bucket ${i + 1}: ${(s * 7 + i * 11) % 19 + 2} positions`} title={`Demo: ${(s * 7 + i * 11) % 19 + 2} positions`} style={{ background: `rgba(255, 40, 53, ${.08 + ((s * 3 + i * 7) % 8) * .095})` }}/>)}</div>)}<div className="heatmap-legend"><span>Lower exposure</span><i/><i/><i/><i/><span>Higher</span></div></div>;
}
export function OracleChart({ compact = false }: { compact?: boolean }) {
  const prices = [48, 48, 51, 51, 45, 45, 41, 41, 46, 46, 53, 53, 48, 48, 55, 55, 60, 60, 57, 57, 63, 63, 59, 59, 54, 54, 58, 58, 63, 63, 60, 60, 66, 66, 62, 62];
  let line = '';
  prices.forEach((n, i) => { const x = 28 + i * 18; const y = 242 - n * 2; line += `${i ? 'H' : 'M'}${x} ${i ? `V${y}` : y} `; });
  return <div className={`oracle-chart ${compact ? 'compact' : ''}`}><svg viewBox="0 0 760 300" role="img" aria-label="Static demonstration of discrete admitted oracle observations, with illustrative upper and lower barriers">
    {[40, 95, 150, 205, 260].map(y => <line key={y} x1="15" x2="670" y1={y} y2={y} stroke="#252328" strokeDasharray="3 5"/>)}
    <rect x="300" y="55" width="345" height="180" fill="#ff2935" opacity=".035"/>
    <line x1="15" x2="670" y1="55" y2="55" stroke="#ff4650" strokeDasharray="5 5"/><text x="680" y="59" fill="#ff6870" fontSize="12">$68,584.20</text>
    <line x1="15" x2="670" y1="235" y2="235" stroke="#ff4650" strokeDasharray="5 5"/><text x="680" y="239" fill="#ff6870" fontSize="12">$68,400.80</text>
    <line x1="300" x2="300" y1="30" y2="262" stroke="#5a565b" strokeDasharray="3 4"/>
    <path d={line} fill="none" stroke="#f5f1f1" strokeWidth="2"/>
    {prices.filter((_, i) => i % 2 === 0).map((n, i) => <circle key={i} cx={28 + i * 36} cy={242 - n * 2} r="2.5" fill="#bcb6bd"/>)}
    <circle cx="658" cy="118" r="5" fill="#ff3441"/><rect x="675" y="107" width="84" height="24" rx="4" fill="#ff3441"/><text x="681" y="123" fill="white" fontSize="11">68,492.50</text>
    <text x="20" y="290" fill="#837c86" fontSize="11">08:41:00</text><text x="300" y="290" fill="#837c86" fontSize="11">08:41:30</text><text x="590" y="290" fill="#837c86" fontSize="11">08:42:00</text>
  </svg></div>;
}
