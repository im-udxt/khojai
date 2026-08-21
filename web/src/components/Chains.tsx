'use client';

import Link from 'next/link';

export type Step = {
  from: string;
  relation: string;
  phrase: string;
  to: string;
  quote: string | null;
  url: string | null;
  outlet: string | null;
};

export type Chain = {
  label: string;
  why: string;
  sentence: string;
  caution: string;
  sources: string;
  names: string[];
  uids: string[];
  steps: Step[];
  outlet_count: number;
  hops: number;
};

const TONE: Record<string, string> = {
  'money then decision': 'border-warn/50',
  'money and a case': 'border-warn/40',
  'decision and a case': 'border-warn/30',
  'shared people': 'border-edge',
};

export function ChainCard({ chain }: { chain: Chain }) {
  return (
    <article className={`card ${TONE[chain.label] || 'border-edge'}`}>
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <span className="tag">{chain.label}</span>
        <span className="text-[11px] text-dim">
          {chain.hops} step{chain.hops === 1 ? '' : 's'}
        </span>
        <span className="ml-auto text-[11px] text-dim">
          {chain.outlet_count} outlet{chain.outlet_count === 1 ? '' : 's'}
        </span>
      </div>

      <p className="text-sm leading-relaxed">{chain.sentence}</p>
      <p className="mt-1 text-xs text-dim">{chain.why}</p>

      <ol className="mt-3 space-y-2">
        {chain.steps.map((s, i) => (
          <li key={i} className="rounded border border-edge bg-bg p-2.5">
            <p className="text-xs">
              <span className="text-ink">{s.from}</span>
              <span className="text-dim"> {s.phrase} </span>
              <span className="text-ink">{s.to}</span>
            </p>
            {s.quote && (
              <p className="mt-1 border-l-2 border-edge pl-2 text-[11px] text-dim">{s.quote}</p>
            )}
            {s.url && (
              <a
                href={s.url}
                target="_blank"
                rel="noopener noreferrer"
                className="mt-1 inline-block text-[11px]"
              >
                {s.outlet || 'source'}
              </a>
            )}
          </li>
        ))}
      </ol>

      <p className="mt-3 rounded border border-edge bg-bg p-2 text-[11px] text-dim">
        {chain.caution} {chain.sources}
      </p>

      <div className="mt-2 flex flex-wrap gap-2 text-[11px]">
        {chain.names.map((n, i) =>
          chain.uids[i] ? (
            <Link key={`${n}-${i}`} href={`/case/${chain.uids[i]}`} className="tag">
              {n}
            </Link>
          ) : (
            <span key={`${n}-${i}`} className="tag">
              {n}
            </span>
          ),
        )}
      </div>
    </article>
  );
}
