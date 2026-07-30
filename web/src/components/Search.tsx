'use client';

import { useEffect, useRef, useState } from 'react';
import { useRouter } from 'next/navigation';
import { getJSON } from '@/lib/api';

type Hit = { uid: string; name: string; type: string; mentions: number };

export default function Search() {
  const [text, setText] = useState('');
  const [hits, setHits] = useState<Hit[]>([]);
  const [state, setState] = useState<'idle' | 'busy' | 'done' | 'error'>('idle');
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  const router = useRouter();

  useEffect(() => {
    if (text.trim().length < 2) {
      setHits([]);
      setState('idle');
      setOpen(false);
      return;
    }
    setState('busy');
    const timer = setTimeout(() => {
      getJSON<{ results: Hit[] }>(`/api/search?q=${encodeURIComponent(text.trim())}`)
        .then((d) => {
          setHits(d.results || []);
          setState('done');
          setOpen(true);
        })
        .catch(() => {
          setHits([]);
          setState('error');
          setOpen(true);
        });
    }, 250);
    return () => clearTimeout(timer);
  }, [text]);

  useEffect(() => {
    const close = (e: MouseEvent) => {
      if (box.current && !box.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener('mousedown', close);
    return () => document.removeEventListener('mousedown', close);
  }, []);

  return (
    <div ref={box} className="relative">
      <input
        value={text}
        onChange={(e) => setText(e.target.value)}
        onFocus={() => hits.length && setOpen(true)}
        placeholder="Search a name"
        className="w-full rounded border border-edge bg-bg px-3 py-1.5 text-sm outline-none placeholder:text-dim focus:border-dim"
      />
      {open && (
        <div className="absolute z-50 mt-1 w-full overflow-hidden rounded border border-edge bg-panel shadow-lg">
          {hits.length === 0 && (
            <p className="px-3 py-2 text-xs text-dim">
              {state === 'busy' && 'Searching'}
              {state === 'done' && `No name matching "${text.trim()}" is stored yet.`}
              {state === 'error' && 'Search is not available right now.'}
            </p>
          )}
          {hits.map((h) => (
            <button
              key={h.uid}
              onClick={() => {
                setOpen(false);
                setText('');
                router.push(`/entity/${h.uid}`);
              }}
              className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm hover:bg-edge"
            >
              <span>{h.name}</span>
              <span className="tag">{h.type}</span>
              <span className="ml-auto text-[11px] text-dim">{h.mentions}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
