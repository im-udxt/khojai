'use client';

import Link from 'next/link';
import { usePoll, num, ago } from '@/lib/api';
import { useTabs, Meter, Stat } from '@/components/Tabs';

type Status = {
  checked: string;
  services: Record<string, { state: string; note: string }>;
  queue_depth: number;
  processed_today: number;
  healthy: boolean;
  down: string[];
};

type Box = {
  kind?: string;
  system?: string;
  arch?: string;
  host_uptime_seconds?: number;
  cpu?: { cores: number; busy_pct: number; load_1m: number | null };
  memory?: { total_gb: number; used_gb: number; used_pct: number };
  swap?: { total_gb: number; used_pct: number };
  agents?: { memory_mb: number; threads: number; cpu_pct: number };
  disks?: { path: string; total_gb: number; used_gb: number; used_pct: number }[];
  note?: string;
};

type Machine = {
  available: boolean;
  fresh?: boolean;
  age_seconds?: number;
  note?: string;
  summary?: string;
  machine?: Box;
  archive?: { documents: number; size_mb: number };
};

type Stats = {
  today: Record<string, number>;
  total: { entities: number; claims: number };
  ever: {
    seen: number;
    processed: number;
    claims: number;
    duplicates: number;
    merged: number;
    since: string;
  };
};

type Sources = {
  summary: string;
  sources: { source: string; items: number; detail: string; age_seconds: number }[];
  by_outlet: { outlet: string; value: number }[];
  claims_by_outlet: { outlet: string; value: number }[];
};

type Merges = {
  summary: string;
  merged: {
    ts: number;
    kept: string;
    kept_uid: string;
    removed: string;
    reason: string;
    automatic: boolean;
  }[];
  waiting: {
    pair: string;
    reason: string;
    a: { uid: string; name: string; type: string };
    b: { uid: string; name: string; type: string };
  }[];
};

const NAMES: Record<string, string> = {
  model: 'Language model',
  graph: 'Database',
  queue: 'Job queue',
  crawler: 'News crawler',
  worker: 'Article reader',
  agents: 'Background service',
  api: 'Website API',
};

const TABS = ['Services', 'Machine', 'Totals', 'Sources', 'Names'] as const;

function hours(seconds?: number) {
  if (!seconds) return '-';
  const h = Math.floor(seconds / 3600);
  if (h < 48) return `${h}h`;
  return `${Math.floor(h / 24)}d`;
}

export default function StatusPage() {
  const { tab, bar } = useTabs(TABS);
  const { data, error } = usePoll<Status>('/api/status', 15000);
  const { data: snap } = usePoll<Machine>('/api/machine', 30000);
  const box = snap?.machine;
  const { data: stats } = usePoll<Stats>('/api/stats', 30000);
  const { data: sources } = usePoll<Sources>('/api/sources', 60000);
  const { data: merges } = usePoll<Merges>('/api/merges', 60000);

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
            : `Not working right now: ${data.down
                .map((d) => NAMES[d] || d)
                .join(', ')}. Work stops for those parts until they come back. Nothing is lost, items stay in the queue.`}
        </p>
        <p className="mt-2 text-xs text-dim">Checked {ago(data.checked)}</p>
      </section>

      <section className="card">
        {bar}

        {tab === 'Services' && (
          <div className="space-y-2">
            {Object.entries(data.services).map(([key, info]) => (
              <div
                key={key}
                className="flex flex-wrap items-center gap-2 rounded border border-edge bg-bg p-3"
              >
                <span
                  className={`inline-block h-2.5 w-2.5 rounded-full ${
                    info.state === 'up'
                      ? 'bg-good'
                      : info.state === 'unknown'
                        ? 'bg-warn'
                        : 'bg-bad'
                  }`}
                />
                <span className="text-sm">{NAMES[key] || key}</span>
                <span className="text-xs text-dim">{info.note}</span>
                <span
                  className={`ml-auto text-xs ${
                    info.state === 'up'
                      ? 'text-good'
                      : info.state === 'unknown'
                        ? 'text-warn'
                        : 'text-bad'
                  }`}
                >
                  {info.state === 'up' ? 'working' : info.state === 'unknown' ? 'unknown' : 'down'}
                </span>
              </div>
            ))}
            <p className="pt-1 text-sm">
              {num(data.queue_depth)} article{data.queue_depth === 1 ? '' : 's'} waiting to be
              read. {num(data.processed_today)} read today.
            </p>
            {data.queue_depth > 500 && data.processed_today === 0 && (
              <p className="text-xs text-bad">
                The queue is growing and nothing has been read today. The reader is not keeping
                up.
              </p>
            )}
          </div>
        )}

        {tab === 'Machine' && (
          <div className="space-y-3">
            {!snap?.available ? (
              <p className="text-sm text-dim">
                {snap?.note || 'No reading from the machine yet.'}
              </p>
            ) : (
              <>
                <p className="text-[11px] text-dim">
                  This is {box?.kind || 'the machine the containers run in'}, not the Mac
                  itself. The containers run inside a small Linux machine, and that is the
                  memory and processor the pipeline actually gets. Taken{' '}
                  {snap.age_seconds ?? 0} seconds ago.
                  {!snap.fresh && ' This reading is stale, so the numbers may be wrong.'}
                </p>

                <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                  <Stat
                    label="processor in use"
                    value={box?.cpu ? `${box.cpu.busy_pct}%` : '-'}
                    note={box?.cpu ? `${box.cpu.cores} cores` : ''}
                  />
                  <Stat
                    label="memory in use"
                    value={box?.memory ? `${box.memory.used_pct}%` : '-'}
                    note={box?.memory ? `${box.memory.used_gb} of ${box.memory.total_gb} GB` : ''}
                  />
                  <Stat
                    label="this service"
                    value={box?.agents ? `${box.agents.memory_mb} MB` : '-'}
                    note={box?.agents ? `${box.agents.threads} threads` : ''}
                  />
                  <Stat label="machine up" value={hours(box?.host_uptime_seconds)} />
                </div>

                {box?.memory && (
                  <div>
                    <p className="mb-1 text-[11px] text-dim">memory</p>
                    <Meter pct={box.memory.used_pct} />
                  </div>
                )}
                {box?.cpu && (
                  <div>
                    <p className="mb-1 text-[11px] text-dim">
                      processor{box.cpu.load_1m !== null ? ` · load ${box.cpu.load_1m}` : ''}
                    </p>
                    <Meter pct={box.cpu.busy_pct} />
                  </div>
                )}

                <div className="space-y-2 pt-1">
                  {(box?.disks || []).map((d) => (
                    <div key={d.path}>
                      <p className="mb-1 flex text-[11px] text-dim">
                        <span>{d.path}</span>
                        <span className="ml-auto">
                          {d.used_gb} of {d.total_gb} GB used
                        </span>
                      </p>
                      <Meter pct={d.used_pct} />
                    </div>
                  ))}
                </div>

                {snap.archive && (
                  <p className="text-xs text-dim">
                    Archive holds {num(snap.archive.documents)} compressed documents,{' '}
                    {num(snap.archive.size_mb)} MB. A copy of every article is kept before
                    anything is derived from it.
                  </p>
                )}
                {box?.note && <p className="text-[11px] text-warn">{box.note}</p>}
                <p className="text-[11px] text-dim">
                  {box?.system} on {box?.arch}
                </p>
              </>
            )}
          </div>
        )}

        {tab === 'Totals' && (
          <div className="space-y-3">
            <p className="text-sm">{snap?.summary || 'Nothing counted yet.'}</p>
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-5">
              <Stat label="listings looked at" value={num(stats?.ever.seen)} />
              <Stat label="articles read in full" value={num(stats?.ever.processed)} />
              <Stat label="links found" value={num(stats?.ever.claims)} />
              <Stat label="near copies dropped" value={num(stats?.ever.duplicates)} />
              <Stat label="duplicate names folded" value={num(stats?.ever.merged)} />
            </div>
            <p className="text-[11px] text-dim">
              Running totals since {(stats?.ever.since || '').slice(0, 10) || 'they were added'}.
              Counting started when these were added, not when the project did, so this is not
              the whole history.
            </p>
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              <Stat label="names stored now" value={num(stats?.total.entities)} />
              <Stat label="links stored now" value={num(stats?.total.claims)} />
              <Stat label="read today" value={num(stats?.today.processed)} />
              <Stat label="found today" value={num(stats?.today.claims)} />
            </div>
          </div>
        )}

        {tab === 'Sources' && (
          <div className="space-y-3">
            <p className="text-sm text-dim">{sources?.summary}</p>
            <div className="max-h-[60vh] space-y-1 overflow-y-auto pr-1">
              {(sources?.sources || []).map((s) => (
                <div key={s.source} className="flex items-center gap-2 text-xs">
                  <span
                    className={`inline-block h-2 w-2 shrink-0 rounded-full ${
                      s.items > 0 ? 'bg-good' : 'bg-bad'
                    }`}
                  />
                  <span className="w-40 shrink-0 truncate">{s.source}</span>
                  <span className="w-16 shrink-0 text-dim">{s.items} items</span>
                  <span className="flex-1 truncate text-dim">{s.detail}</span>
                </div>
              ))}
              {!sources?.sources?.length && (
                <p className="text-sm text-dim">No source has reported yet.</p>
              )}
            </div>
            {!!sources?.claims_by_outlet?.length && (
              <div>
                <h3 className="label">Links found per outlet</h3>
                <div className="space-y-1">
                  {sources.claims_by_outlet.slice(0, 12).map((o) => (
                    <div key={o.outlet} className="flex gap-2 text-xs">
                      <span className="w-44 truncate">{o.outlet}</span>
                      <span className="text-dim">{num(o.value)}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}

        {tab === 'Names' && (
          <div className="space-y-3">
            <p className="text-sm text-dim">{merges?.summary}</p>

            {!!merges?.waiting?.length && (
              <div>
                <h3 className="label">Too close to call</h3>
                <div className="space-y-2">
                  {merges.waiting.slice(0, 20).map((w) => (
                    <div key={w.pair} className="rounded border border-edge bg-bg p-2.5 text-xs">
                      <p>
                        <Link href={`/case/${w.a.uid}`}>{w.a.name}</Link>
                        <span className="text-dim"> and </span>
                        <Link href={`/case/${w.b.uid}`}>{w.b.name}</Link>
                      </p>
                      <p className="mt-0.5 text-[11px] text-dim">{w.reason}</p>
                    </div>
                  ))}
                </div>
                <p className="mt-2 text-[11px] text-dim">
                  These are decided from Telegram with /merges, not from this page. The site
                  never writes to the database.
                </p>
              </div>
            )}

            <div>
              <h3 className="label">Folded together</h3>
              <div className="max-h-[50vh] space-y-1 overflow-y-auto pr-1">
                {(merges?.merged || []).map((m, i) => (
                  <div key={i} className="text-xs">
                    <span className="text-dim">{m.removed}</span>
                    <span className="text-dim"> into </span>
                    <Link href={`/case/${m.kept_uid}`}>{m.kept}</Link>
                    <span className="text-[10px] text-dim">
                      {' '}
                      · {m.reason}
                      {m.automatic ? '' : ' · approved by hand'}
                    </span>
                  </div>
                ))}
                {!merges?.merged?.length && (
                  <p className="text-sm text-dim">Nothing has been folded together yet.</p>
                )}
              </div>
            </div>
          </div>
        )}
      </section>
    </div>
  );
}
