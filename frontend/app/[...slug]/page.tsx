import { Dashboard } from '@/components/dashboard';
export const dynamicParams = false;
export function generateStaticParams() {
  return ['trade', 'runs', 'portfolio', 'lp', 'fuse', 'status', 'docs', 'data', 'data/lp', 'data/survival', 'data/activity', 'data/oracle', 'data/economy', 'data/methodology'].map(path => ({ slug: path.split('/') }));
}
export default async function Page({ params }: { params: Promise<{ slug: string[] }> }) {
  const { slug } = await params;
  return <Dashboard route={slug.join('/')} />;
}
