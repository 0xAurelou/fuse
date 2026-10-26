import type { NextConfig } from 'next';
const engineUrl = process.env.FUSE_ENGINE_URL?.replace(/\/$/, '');
const config: NextConfig = {
  devIndicators: false,
  env: { NEXT_PUBLIC_ENGINE_ENABLED: engineUrl ? 'true' : 'false', NEXT_PUBLIC_PAPER_DESK: engineUrl && process.env.FUSE_PAPER_DESK === 'true' ? 'true' : 'false' },
  async rewrites() {
    return engineUrl ? [{ source: '/engine/v1/:path*', destination: `${engineUrl}/v1/:path*` }] : [];
  },
};
export default config;
