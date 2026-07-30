'use client';

import { useEffect, useState } from 'react';

export async function getJSON<T>(path: string): Promise<T> {
  const res = await fetch(path, { cache: 'no-store' });
  if (!res.ok) throw new Error(`request failed: ${res.status}`);
  return res.json() as Promise<T>;
}

export function usePoll<T>(path: string, ms: number) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let live = true;
    const load = () =>
      getJSON<T>(path)
        .then((d) => live && (setData(d), setError(null)))
        .catch((e) => live && setError(String(e)));
    load();
    const id = setInterval(load, ms);
    return () => {
      live = false;
      clearInterval(id);
    };
  }, [path, ms]);
  return { data, error };
}

export function num(value: number | null | undefined, digits = 0) {
  if (value === null || value === undefined) return '-';
  return value.toLocaleString('en-IN', { maximumFractionDigits: digits });
}

export function ago(iso: string) {
  if (!iso) return '';
  const secs = Math.floor((Date.now() - new Date(iso).getTime()) / 1000);
  if (secs < 60) return `${secs}s ago`;
  if (secs < 3600) return `${Math.floor(secs / 60)}m ago`;
  if (secs < 86400) return `${Math.floor(secs / 3600)}h ago`;
  return `${Math.floor(secs / 86400)}d ago`;
}
