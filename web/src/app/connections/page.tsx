'use client';

import { usePoll } from '@/lib/api';
import { ChainCard, type Chain } from '@/components/Chains';

type Payload = {
  summary: string;
  shapes: Record<string, number>;
  connections: Chain[];
};

export default function ConnectionsPage() {
  const { data, error } = usePoll<Payload>('/api/connections?limit=24', 60000);

  if (error) return <p className="text-sm text-bad">Connections are not available right now.</p>;
  if (!data) return <p className="text-sm text-dim">Walking the graph.</p>;

  return (
    <div className="space-y-4">
      <section className="card">
        <h1 className="mb-1 text-lg font-semibold">What the links add up to</h1>
        <p className="text-sm text-dim">{data.summary}</p>
        <div className="mt-3 flex flex-wrap gap-2">
          {Object.entries(data.shapes).map(([shape, count]) => (
            <span key={shape} className="tag">
              {shape}: {count}
            </span>
          ))}
        </div>
      </section>

      <div className="space-y-3">
        {data.connections.map((chain, i) => (
          <ChainCard key={i} chain={chain} />
        ))}
        {!data.connections.length && (
          <p className="text-sm text-dim">
            No chains yet. One appears as soon as two separately recorded facts share a name in
            the middle.
          </p>
        )}
      </div>
    </div>
  );
}
