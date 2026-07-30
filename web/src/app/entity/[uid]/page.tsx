'use client';

import { use } from 'react';
import Link from 'next/link';
import { usePoll, ago } from '@/lib/api';

type Claim = {
  subject: string;
  relation: string;
  object: string;
  object_uid: string;
  quote: string;
  url: string;
  outlet: string;
  created: string;
};
type Entity = {
  uid: string;
  name: string;
  type: string;
  mentions: number;
  first_seen: string;
  last_seen: string;
  claims: Claim[];
};

const words = (relation: string) => relation.toLowerCase().replace(/_/g, ' ');

export default function EntityPage({ params }: { params: Promise<{ uid: string }> }) {
  const { uid } = use(params);
  const { data, error } = usePoll<Entity>(`/api/entity/${uid}`, 60000);

  if (error) return <p className="text-sm text-bad">That name is not stored.</p>;
  if (!data) return <p className="text-sm text-dim">Loading.</p>;

  const outlets = new Set(data.claims.map((c) => c.outlet).filter(Boolean));

  return (
    <div className="space-y-4">
      <header className="card">
        <div className="flex flex-wrap items-center gap-2">
          <h1 className="text-xl font-semibold">{data.name}</h1>
          <span className="tag">{data.type}</span>
        </div>
        <p className="mt-2 text-sm text-dim">
          Seen in {data.mentions} article{data.mentions === 1 ? '' : 's'}.{' '}
          {data.claims.length} link{data.claims.length === 1 ? '' : 's'} from{' '}
          {outlets.size} outlet{outlets.size === 1 ? '' : 's'}.
        </p>
        <Link href={`/graph?entity=${encodeURIComponent(data.name)}`} className="mt-2 inline-block text-sm">
          See this on the map
        </Link>
      </header>

      <section className="card">
        <h2 className="label">Links</h2>
        <div className="space-y-3">
          {data.claims.map((c, i) => (
            <article key={i} className="rounded border border-edge bg-bg p-3">
              <p className="text-sm">
                <span>{c.subject}</span>
                <span className="text-dim"> {words(c.relation)} </span>
                <Link href={`/entity/${c.object_uid}`}>{c.object}</Link>
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
          {!data.claims.length && <p className="text-sm text-dim">No links stored yet.</p>}
        </div>
      </section>
    </div>
  );
}
