'use client';

import Link from 'next/link';
import { usePoll } from '@/lib/api';
import { Bars, Donut, Trend } from '@/components/Charts';

type Row = { name: string; value: number };
type Busy = { uid: string; name: string; type: string; value: number };
type Insights = {
  summary: string;
  by_type: Row[];
  by_relation: Row[];
  by_outlet: Row[];
  busiest: Busy[];
  daily: { day: string; processed: number; claims: number }[];
};

const pretty = (name: string) => name.toLowerCase().replace(/_/g, ' ');

export default function InsightsPage() {
  const { data, error } = usePoll<Insights>('/api/insights', 60000);

  if (error) return <p className="text-sm text-bad">Insights are not available right now.</p>;
  if (!data) return <p className="text-sm text-dim">Reading the graph.</p>;

  return (
    <div className="space-y-4">
      <section className="card">
        <h1 className="mb-1 text-lg font-semibold">What the data says</h1>
        <p className="text-sm text-dim">{data.summary}</p>
      </section>

      <section className="card">
        <h2 className="label">Last seven days</h2>
        <Trend rows={data.daily} />
        <p className="mt-2 text-xs text-dim">
          Articles read is how many the model got through. Links found is how many survived the
          check that the quote really appears in the article.
        </p>
      </section>

      <div className="grid gap-4 lg:grid-cols-2">
        <section className="card">
          <h2 className="label">Kinds of names stored</h2>
          <Donut rows={data.by_type} />
        </section>

        <section className="card">
          <h2 className="label">Kinds of links found</h2>
          <Bars rows={data.by_relation.map((r) => ({ ...r, name: pretty(r.name) }))} />
          <p className="mt-2 text-xs text-dim">
            Mentioned with means the article put two names together without saying how.
          </p>
        </section>

        <section className="card">
          <h2 className="label">Where the links came from</h2>
          <Bars rows={data.by_outlet} />
        </section>

        <section className="card">
          <h2 className="label">Names in the most links</h2>
          <div className="space-y-1.5">
            {data.busiest.map((b) => (
              <div key={b.uid} className="flex items-center gap-2 text-sm">
                <Link href={`/case/${b.uid}`} className="truncate">
                  {b.name}
                </Link>
                <span className="tag">{b.type}</span>
                <span className="ml-auto text-xs text-dim">{b.value} links</span>
              </div>
            ))}
            {!data.busiest.length && <p className="text-sm text-dim">No data yet.</p>}
          </div>
        </section>
      </div>
    </div>
  );
}
