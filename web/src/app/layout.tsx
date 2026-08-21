import type { Metadata } from 'next';
import Link from 'next/link';
import './globals.css';
import Search from '@/components/Search';
import Markets from '@/components/Markets';

const site = process.env.NEXT_PUBLIC_SITE_NAME || 'KhojAI';

export const metadata: Metadata = {
  title: `${site}: public record research`,
  description:
    'Reads Indian public sources, records who is linked to whom, and shows the article each link came from.',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <Markets />
        <header className="border-b border-edge bg-panel">
          <div className="mx-auto flex max-w-6xl flex-wrap items-center gap-4 px-4 py-3">
            <Link href="/" className="text-lg font-semibold text-ink">
              {site}
            </Link>
            <nav className="flex gap-4 text-sm text-dim">
              <Link href="/">Home</Link>
              <Link href="/cases">Cases</Link>
              <Link href="/connections">Connections</Link>
              <Link href="/graph">Map</Link>
              <Link href="/insights">Insights</Link>
              <Link href="/status">Status</Link>
            </nav>
            <div className="ml-auto w-full max-w-xs">
              <Search />
            </div>
          </div>
        </header>
        <main className="mx-auto max-w-6xl px-4 py-5">{children}</main>
        <footer className="border-t border-edge px-4 py-6 text-center text-xs text-dim">
          Built from public sources. Each claim links to the article it came from.
        </footer>
      </body>
    </html>
  );
}
