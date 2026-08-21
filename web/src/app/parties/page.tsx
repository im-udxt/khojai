'use client';

import Link from 'next/link';
import { usePoll, num, ago } from '@/lib/api';
import { useTabs } from '@/components/Tabs';
import { ChainCard, type Chain } from '@/components/Chains';

type Party = {
  uid: string;
  name: string;
  links: number;
  outlets: number;
  around: string[];
  relations: string[];
};

type Money = {
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

type Payload = {
  summary: string;
  parties: Party[];
  money: Money[];
  connections: Chain[];
};

const TABS = ['Parties', 'Money and decisions', 'Chains'] as const;

const words = (relation: string) => relation.toLowerCase().replace(/_/g, ' ');

export default function PartiesPage() {
  const { tab, bar } = useTabs(TABS);
  const { data, error } = usePoll<Payload>('/api/parties?limit=15', 60000);

  if (error)
    return (
      <div className="card border-bad">
        <p className="text-sm text-bad">The API is not answering.</p>
      </div>
    );
  if (!data) return <p className="text-sm text-dim">Reading the graph.</p>;

  return (
    <div className="space-y-4">
      <section className="card">
        <h1 className="mb-1 text-lg font-semibold">Political parties</h1>
        <p className="text-sm text-dim">{data.summary}</p>
        <p className="mt-2 rounded border border-edge bg-bg p-2 text-[11px] text-dim">
          Parties get their own page because money and decisions around them are the links
          most worth reading, not because anything here is pointed at one of them. The same
          rules, the same sourcing and the same warnings apply as everywhere else on this
          site. A name is treated as a party when it matches a known party or carries a party
          word, which will sometimes be wrong.
        </p>
      </section>

      <section className="card">
        {bar}

        {tab === 'Parties' && (
          <div className="space-y-2">
            {data.parties.map((p) => (
              <article key={p.uid} className="rounded border border-edge bg-bg p-3">
                <div className="flex flex-wrap items-center gap-2">
                  <Link href={`/case/${p.uid}`} className="text-sm font-medium">
                    {p.name}
                  </Link>
                  <span className="text-[11px] text-dim">
                    {num(p.links)} link{p.links === 1 ? '' : 's'}
                  </span>
                  <span
                    className={`ml-auto text-[11px] ${
                      p.outlets > 2 ? 'text-good' : p.outlets === 2 ? 'text-warn' : 'text-bad'
                    }`}
                  >
                    {p.outlets} outlet{p.outlets === 1 ? '' : 's'}
                  </span>
                </div>
                {!!p.relations?.length && (
                  <p className="mt-1 text-[11px] text-dim">
                    {p.relations.map(words).join(', ')}
                  </p>
                )}
                {!!p.around?.length && (
                  <div className="mt-2 flex flex-wrap gap-1.5">
                    {p.around.map((n) => (
                      <span key={n} className="tag">
                        {n}
                      </span>
                    ))}
                  </div>
                )}
              </article>
            ))}
            {!data.parties.length && (
              <p className="text-sm text-dim">
                No party has been recorded yet. They appear as articles naming them are read.
              </p>
            )}
          </div>
        )}

        {tab === 'Money and decisions' && (
          <div className="space-y-2">
            <p className="text-xs text-dim">
              Only the links that involve money, a contract, ownership, an appointment or a
              decision. Everything else about a party is on its own page.
            </p>
            {data.money.map((m, i) => (
              <article key={i} className="rounded border border-edge bg-bg p-3">
                <p className="text-sm">
                  <Link href={`/entity/${m.subject_uid}`}>{m.subject}</Link>
                  <span className="text-dim"> {words(m.relation)} </span>
                  <Link href={`/entity/${m.object_uid}`}>{m.object}</Link>
                </p>
                {m.quote && (
                  <p className="mt-1 border-l-2 border-edge pl-2 text-xs text-dim">{m.quote}</p>
                )}
                <p className="mt-1 text-[11px] text-dim">
                  <a href={m.url} target="_blank" rel="noopener noreferrer">
                    {m.outlet || 'source'}
                  </a>
                  {m.created ? ` · ${ago(m.created)}` : ''}
                </p>
              </article>
            ))}
            {!data.money.length && (
              <p className="text-sm text-dim">
                Nothing yet. This fills in when an article states that a party gave, received,
                appointed or decided something.
              </p>
            )}
          </div>
        )}

        {tab === 'Chains' && (
          <div className="space-y-3">
            {data.connections.map((chain, i) => (
              <ChainCard key={i} chain={chain} />
            ))}
            {!data.connections.length && (
              <p className="text-sm text-dim">
                No chains through a party yet. One appears when two separately recorded facts
                meet at a party or at a name beside it.
              </p>
            )}
          </div>
        )}
      </section>
    </div>
  );
}
