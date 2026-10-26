import type { Metadata } from 'next';
import './globals.css';
import './terminal.css';
import './after-hours.css';
import './character-stage.css';
export const metadata: Metadata = {
  title: 'FUSE 100 — Single-stage Trading',
  description: 'BTC, HYPE and ETH. Choose 2×–100× payouts for independent 30-second stages. Live oracle prices with virtual USDC in the local paper desk.',
};
export default function Layout({ children }: { children: React.ReactNode }) {
  return <html lang="en"><body>{children}</body></html>;
}
