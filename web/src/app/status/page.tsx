'use client';

import { usePoll, ago } from '@/lib/api';

type Status = {
  checked: string;
  services: Record<string, { state: string; note: string }>;
  queue_depth: number;
  healthy: boolean;
  down: string[];
};

const NAMES: Record<string, string> = {
  model: 'Language model',
  graph: 'Database',
  queue: 'Job queue',
  crawler: 'News crawler',
  agents: 'Background worker',
  api: 'Website API',
};

export default function StatusPage() {
  const { data, error } = usePoll<Status>('/api/status', 15000);

  if (error)
    return (
      <div className="card border-bad">
        <h1 className="text-lg font-semibold text-bad">The site cannot reach its API</h1>
        <p className="mt-1 text-sm text-dim">
          The backend is not answering. Nothing is being processed right now.
        </p>
      </div>
    );
  if (!data) return <p className="text-sm text-dim">Checking services.</p>;

  return (
    <div className="space-y-4">
      <section className={`card ${data.healthy ? '' : 'border-bad'}`}>
        <h1 className="text-lg font-semibold">
          {data.healthy ? 'Everything is running' : 'Some services are down'}
        </h1>
        <p className="mt-1 text-sm text-dim">
          {data.healthy
            ? 'The crawler is reading sources and the model is storing links.'
            : `Not working right now: ${data.down.map((d) => NAMES[d] || d).join(', ')}. Work stops for those parts until they come back. Nothing is lost, items stay in the queue.`}
        </p>
        <p className="mt-2 text-xs text-dim">Checked {ago(data.checked)}</p>
      </section>

      <section className="card">
        <h2 className="label">Services</h2>
        <div className="space-y-2">
          {Object.entries(data.services).map(([key, info]) => (
            <div
              key={key}
              className="flex flex-wrap items-center gap-2 rounded border border-edge bg-bg p-3"
            >
              <span
                className={`inline-block h-2.5 w-2.5 rounded-full ${
                  info.state === 'up' ? 'bg-good' : 'bg-bad'
                }`}
              />
              <span className="text-sm">{NAMES[key] || key}</span>
              <span className="text-xs text-dim">{info.note}</span>
              <span
                className={`ml-auto text-xs ${info.state === 'up' ? 'text-good' : 'text-bad'}`}
              >
                {info.state === 'up' ? 'working' : 'down'}
              </span>
            </div>
          ))}
        </div>
      </section>

      <section className="card">
        <h2 className="label">Queue</h2>
        <p className="text-sm">
          {data.queue_depth} article{data.queue_depth === 1 ? '' : 's'} waiting to be read.
        </p>
      </section>
    </div>
  );
}
