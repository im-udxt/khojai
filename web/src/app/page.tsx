'use client';

import Link from 'next/link';
import { usePoll, num, ago } from '@/lib/api';

type Stats = {
  today: { seen: number; queued: number; processed: number; claims: number; duplicates: number };
  total: { entities: number; claims: number };
};
type Claim = {
  subject: string;
  subject_uid: string;
  relation: string;
  object: string;
  object_uid: string;
  quote: string;
  url: string;
  outlet: string;
  created: string;
};
type Activity = { ts: string; actor: string; message: string };

const words = (relation: string) => relation.toLowerCase().replace(/_/g, ' ');

export default function Home() {
  const { data: stats } = usePoll<Stats>('/api/stats', 30000);
  const { data: claims } = usePoll<{ claims: Claim[] }>('/api/claims?limit=25', 30000);
  const { data: feed } = usePoll<{ activity: Activity[] }>('/api/activity?limit=25', 15000);

  const cells: [string, number | undefined][] = [
    ['Articles seen today', stats?.today.seen],
    ['Read by the model', stats?.today.processed],
    ['Links found today', stats?.today.claims],
    ['Names stored', stats?.total.entities],
    ['Links stored', stats?.total.claims],
  ];

  return (
    <div className="space-y-4">
      <section className="card">
        <h1 className="mb-1 text-lg font-semibold">What this is</h1>
        <p className="text-sm text-dim">
          This site reads Indian news and official feeds all day. When an article says two
          names are connected, that link is stored with the sentence that said it and a
          link to the article. Nothing here is a conclusion. Check the source yourself.
        </p>
      </section>

      <section className="card">
        <h2 className="label">Numbers</h2>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-5">
          {cells.map(([label, value]) => (
            <div key={label} className="rounded border border-edge bg-bg p-3 text-center">
              <div className="text-xl font-semibold">{num(value)}</div>
              <div className="mt-1 text-[11px] text-dim">{label}</div>
            </div>
          ))}
        </div>
      </section>

      <div className="grid gap-4 lg:grid-cols-[1fr_300px]">
        <section className="card">
          <h2 className="label">Latest links found</h2>
          <div className="space-y-3">
            {(claims?.claims || []).map((c, i) => (
              <article key={i} className="rounded border border-edge bg-bg p-3">
                <p className="text-sm">
                  <Link href={`/entity/${c.subject_uid}`}>{c.subject}</Link>
                  <span className="text-dim"> {words(c.relation)} </span>
                  <Link href={`/entity/${c.object_uid}`}>{c.object}</Link>
                </p>
                <p className="mt-1 border-l-2 border-edge pl-2 text-xs text-dim">
                  {c.quote}
                </p>
                <p className="mt-1 text-[11px] text-dim">
                  <a href={c.url} target="_blank" rel="noopener noreferrer">
                    {c.outlet || 'source'}
                  </a>
                  {c.created ? ` · ${ago(c.created)}` : ''}
                </p>
              </article>
            ))}
            {!claims?.claims?.length && (
              <p className="text-sm text-dim">
                Nothing stored yet. The crawler runs every few minutes and links show up
                here as they are found.
              </p>
            )}
          </div>
        </section>

        <aside className="card">
          <h2 className="label">What it is doing</h2>
          <div className="space-y-1.5 text-xs">
            {(feed?.activity || []).map((a, i) => (
              <div key={i} className="flex gap-2">
                <span className="w-16 shrink-0 text-dim">{a.actor}</span>
                <span>{a.message}</span>
              </div>
            ))}
            {!feed?.activity?.length && <p className="text-dim">Starting up.</p>}
          </div>
        </aside>
      </div>
    </div>
  );
}
