'use client';

import { use } from 'react';
import Link from 'next/link';
import { usePoll, ago } from '@/lib/api';
import { Bars } from '@/components/Charts';

type Claim = {
  subject: string;
  relation: string;
  object: string;
  quote: string;
  url: string;
  outlet: string;
  created: string;
};
type CaseDetail = {
  uid: string;
  name: string;
  type: string;
  mentions: number;
  first_seen: string;
  last_seen: string;
  reading: string;
  outlets: string[];
  relations: string[];
  claims: Claim[];
};

const pretty = (r: string) => r.toLowerCase().replace(/_/g, ' ');

export default function CasePage({ params }: { params: Promise<{ uid: string }> }) {
  const { uid } = use(params);
  const { data, error } = usePoll<CaseDetail>(`/api/case/${uid}`, 60000);

  if (error) return <p className="text-sm text-bad">That case was not found.</p>;
  if (!data) return <p className="text-sm text-dim">Opening the case.</p>;

  const byOutlet = Object.entries(
    data.claims.reduce<Record<string, number>>((acc, c) => {
      const key = c.outlet || 'unknown';
      acc[key] = (acc[key] || 0) + 1;
      return acc;
    }, {}),
  )
    .map(([name, value]) => ({ name, value }))
    .sort((a, b) => b.value - a.value);

  const byRelation = Object.entries(
    data.claims.reduce<Record<string, number>>((acc, c) => {
      const key = pretty(c.relation);
      acc[key] = (acc[key] || 0) + 1;
      return acc;
    }, {}),
  )
    .map(([name, value]) => ({ name, value }))
    .sort((a, b) => b.value - a.value);

  return (
    <div className="space-y-4">
      <header className="card">
        <div className="flex flex-wrap items-center gap-2">
          <h1 className="text-xl font-semibold">{data.name}</h1>
          <span className="tag">{data.type}</span>
          <Link href={`/graph?entity=${encodeURIComponent(data.name)}`} className="ml-auto text-sm">
            See on the map
          </Link>
        </div>
        <p className="mt-2 text-sm text-dim">{data.reading}</p>
      </header>

      <div className="grid gap-4 lg:grid-cols-2">
        <section className="card">
          <h2 className="label">Which outlets reported it</h2>
          <Bars rows={byOutlet} />
        </section>
        <section className="card">
          <h2 className="label">What kind of links</h2>
          <Bars rows={byRelation} />
        </section>
      </div>

      <section className="card">
        <h2 className="label">Every recorded link</h2>
        <div className="space-y-3">
          {data.claims.map((c, i) => (
            <article key={i} className="rounded border border-edge bg-bg p-3">
              <p className="text-sm">
                <span>{c.subject}</span>
                <span className="text-dim"> {pretty(c.relation)} </span>
                <span>{c.object}</span>
              </p>
              <p className="mt-1 border-l-2 border-edge pl-2 text-xs text-dim">{c.quote}</p>
              <p className="mt-1 text-[11px] text-dim">
                <a href={c.url} target="_blank" rel="noopener noreferrer">
                  {c.outlet || 'source'}
                </a>
                {c.created ? ` · ${ago(c.created)}` : ''}
              </p>
            </article>
          ))}
          {!data.claims.length && <p className="text-sm text-dim">Nothing recorded yet.</p>}
        </div>
      </section>
    </div>
  );
}
