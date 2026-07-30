'use client';

import { Suspense, useState } from 'react';
import { useSearchParams } from 'next/navigation';
import LinkMap from '@/components/Map';

const TYPES = ['Person', 'Company', 'Government', 'Court', 'Place', 'Topic'];

function Inner() {
  const params = useSearchParams();
  const [text, setText] = useState(params.get('entity') || '');
  const [entity, setEntity] = useState(params.get('entity') || '');
  const [type, setType] = useState('');

  const qs = new URLSearchParams();
  if (entity) qs.set('entity', entity);
  if (type) qs.set('type', type);

  return (
    <section className="card">
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <h1 className="text-lg font-semibold">Map of links</h1>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            setEntity(text.trim());
          }}
          className="ml-auto flex gap-2"
        >
          <input
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder="Focus on a name"
            className="w-56 rounded border border-edge bg-bg px-3 py-1.5 text-sm outline-none placeholder:text-dim focus:border-dim"
          />
          <button className="rounded border border-edge px-3 py-1.5 text-sm">Show</button>
        </form>
      </div>

      <div className="mb-3 flex flex-wrap items-center gap-1.5 text-xs">
        <span className="text-dim">Type:</span>
        {TYPES.map((t) => (
          <button
            key={t}
            onClick={() => setType(type === t ? '' : t)}
            className={`rounded border px-1.5 py-0.5 ${
              type === t ? 'border-ink text-ink' : 'border-edge text-dim'
            }`}
          >
            {t}
          </button>
        ))}
      </div>

      <LinkMap query={qs.toString()} />
    </section>
  );
}

export default function GraphPage() {
  return (
    <Suspense fallback={<p className="text-sm text-dim">Loading.</p>}>
      <Inner />
    </Suspense>
  );
}
