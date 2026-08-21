'use client';

import Link from 'next/link';
import { usePoll, ago } from '@/lib/api';

type Case = {
  uid: string;
  name: string;
  type: string;
  links: number;
  outlets: number;
  others: string[];
  latest: string;
  headline: string;
};

export default function CasesPage() {
  const { data, error } = usePoll<{ cases: Case[] }>('/api/cases?limit=24', 60000);

  if (error) return <p className="text-sm text-bad">Cases are not available right now.</p>;
  if (!data) return <p className="text-sm text-dim">Gathering cases.</p>;

  return (
    <div className="space-y-4">
      <section className="card">
        <h1 className="mb-1 text-lg font-semibold">Cases</h1>
        <p className="text-sm text-dim">
          A case is a name that turned up in several recorded links. It is a starting point for
          reading, not a finding. Open one to see every link and the article each came from.
        </p>
      </section>

      <div className="grid gap-3 sm:grid-cols-2">
        {data.cases.map((c) => (
          <Link key={c.uid} href={`/case/${c.uid}`} className="card block hover:border-dim">
            <div className="mb-1 flex items-center gap-2">
              <span className="tag">{c.type}</span>
              <span className="ml-auto text-[11px] text-dim">
                {c.outlets} outlet{c.outlets === 1 ? '' : 's'}
              </span>
            </div>
            <h2 className="text-sm font-semibold">{c.name}</h2>
            <p className="mt-1 text-xs text-dim">{c.headline}</p>
            <div className="mt-2 flex flex-wrap gap-1">
              {c.others.filter(Boolean).slice(0, 4).map((o) => (
                <span key={o} className="tag">
                  {o}
                </span>
              ))}
            </div>
            {c.latest && <p className="mt-2 text-[11px] text-dim">updated {ago(c.latest)}</p>}
          </Link>
        ))}
        {!data.cases.length && (
          <p className="text-sm text-dim">
            No cases yet. They appear once a name shows up in more than one recorded link.
          </p>
        )}
      </div>
    </div>
  );
}
