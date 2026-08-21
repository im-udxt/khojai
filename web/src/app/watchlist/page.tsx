'use client';

import { usePoll, num } from '@/lib/api';

type Watch = { name: string; key: string; hits: number; added: number; last?: number };
type Hit = {
  ts: number;
  watched: string;
  subject: string;
  relation: string;
  object: string;
  quote: string;
  url: string;
  outlet: string;
};

type Payload = { watching: Watch[]; hits: Hit[]; note: string };

const words = (relation: string) => relation.toLowerCase().replace(/_/g, ' ');

function when(seconds?: number) {
  if (!seconds) return '';
  const secs = Math.floor(Date.now() / 1000 - seconds);
  if (secs < 60) return 'just now';
  if (secs < 3600) return `${Math.floor(secs / 60)}m ago`;
  if (secs < 86400) return `${Math.floor(secs / 3600)}h ago`;
  return `${Math.floor(secs / 86400)}d ago`;
}

export default function WatchlistPage() {
  const { data, error } = usePoll<Payload>('/api/watchlist?limit=40', 30000);

  if (error)
    return (
      <div className="card border-bad">
        <p className="text-sm text-bad">The API is not answering.</p>
      </div>
    );
  if (!data) return <p className="text-sm text-dim">Reading the watchlist.</p>;

  return (
    <div className="space-y-4">
      <section className="card">
        <h1 className="mb-1 text-lg font-semibold">Watchlist</h1>
        <p className="text-sm text-dim">
          A watched name sends a message the moment a new link touches it, so you do not have
          to come back and look. Names are added from Telegram with /watch, because this site
          never writes to the database.
        </p>
      </section>

      <div className="grid gap-4 lg:grid-cols-[260px_1fr]">
        <section className="card self-start">
          <h2 className="label">Following</h2>
          <div className="space-y-1.5">
            {data.watching.map((w) => (
              <div key={w.key} className="flex items-baseline gap-2 text-xs">
                <span className="truncate">{w.name}</span>
                <span className="ml-auto shrink-0 text-dim">{num(w.hits)}</span>
              </div>
            ))}
            {!data.watching.length && (
              <p className="text-xs text-dim">
                Nothing yet. Send /watch followed by a name to the bot.
              </p>
            )}
          </div>
        </section>

        <section className="card">
          <h2 className="label">What came in</h2>
          <div className="space-y-2">
            {data.hits.map((h, i) => (
              <article key={i} className="rounded border border-edge bg-bg p-3">
                <div className="flex flex-wrap items-baseline gap-2">
                  <span className="tag">{h.watched}</span>
                  <span className="ml-auto text-[10px] text-dim">{when(h.ts)}</span>
                </div>
                <p className="mt-1.5 text-sm">
                  {h.subject}
                  <span className="text-dim"> {words(h.relation)} </span>
                  {h.object}
                </p>
                {h.quote && (
                  <p className="mt-1 border-l-2 border-edge pl-2 text-xs text-dim">{h.quote}</p>
                )}
                {h.url && (
                  <p className="mt-1 text-[11px]">
                    <a href={h.url} target="_blank" rel="noopener noreferrer">
                      {h.outlet || 'source'}
                    </a>
                  </p>
                )}
              </article>
            ))}
            {!data.hits.length && (
              <p className="text-sm text-dim">
                Nothing has come in yet. A watched name only fires when a new link is written
                about it, not for every article that mentions it.
              </p>
            )}
          </div>
        </section>
      </div>
    </div>
  );
}
