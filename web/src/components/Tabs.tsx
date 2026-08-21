'use client';

import { useState } from 'react';

export function useTabs<T extends string>(names: readonly T[]) {
  const [tab, setTab] = useState<T>(names[0]);
  const bar = (
    <div className="mb-3 flex flex-wrap gap-1 border-b border-edge">
      {names.map((name) => (
        <button
          key={name}
          onClick={() => setTab(name)}
          className={`px-3 py-1.5 text-xs ${
            tab === name ? 'border-b-2 border-ink text-ink' : 'text-dim hover:text-ink'
          }`}
        >
          {name}
        </button>
      ))}
    </div>
  );
  return { tab, bar };
}

export function Meter({ pct, warn = 75, bad = 90 }: { pct: number; warn?: number; bad?: number }) {
  const value = Math.max(0, Math.min(100, pct || 0));
  const tone = value >= bad ? 'bg-bad' : value >= warn ? 'bg-warn' : 'bg-good';
  return (
    <div className="h-1.5 w-full overflow-hidden rounded bg-bg">
      <div className={`h-full ${tone}`} style={{ width: `${value}%` }} />
    </div>
  );
}

export function Stat({ label, value, note }: { label: string; value: string; note?: string }) {
  return (
    <div className="rounded border border-edge bg-bg p-3">
      <div className="text-lg font-semibold">{value}</div>
      <div className="mt-0.5 text-[11px] text-dim">{label}</div>
      {note && <div className="mt-1 text-[10px] text-dim">{note}</div>}
    </div>
  );
}
