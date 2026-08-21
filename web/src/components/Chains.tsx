'use client';

import { useState } from 'react';
import Link from 'next/link';

export type Step = {
  from: string;
  relation: string;
  phrase: string;
  to: string;
  quote: string | null;
  url: string | null;
  outlet: string | null;
  outlets_backing: number;
  confidence: { level: string; outlets: number; note: string };
  when: string | null;
};

export type Chain = {
  label: string;
  why: string;
  sentence: string;
  caution: string;
  sources: string;
  names: string[];
  uids: string[];
  types: string[];
  steps: Step[];
  confidence: { level: string; outlets: number; note: string };
  weakest_backing: number;
  timeline: { ordered: boolean; note: string; events: { when: string; what: string }[] };
  outlet_count: number;
  hops: number;
};

const TONE: Record<string, string> = {
  'party and money': 'border-warn/60',
  'party and a decision': 'border-warn/50',
  'money then decision': 'border-warn/40',
  'money and a case': 'border-warn/30',
};

const CONF_COLOR: Record<string, string> = {
  'well sourced': 'text-good',
  corroborated: 'text-warn',
  'single source': 'text-bad',
};

const TABS = ['Reading', 'Proof', 'Confidence', 'Time'] as const;
type Tab = (typeof TABS)[number];

export function ChainCard({ chain }: { chain: Chain }) {
  const [tab, setTab] = useState<Tab>('Reading');

  return (
    <article className={`card ${TONE[chain.label] || 'border-edge'}`}>
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <span className="tag">{chain.label}</span>
        <span className="text-[11px] text-dim">
          {chain.hops} step{chain.hops === 1 ? '' : 's'}
        </span>
        <span className={`text-[11px] ${CONF_COLOR[chain.confidence.level] || 'text-dim'}`}>
          {chain.confidence.level}
        </span>
        <span className="ml-auto text-[11px] text-dim">
          {chain.outlet_count} outlet{chain.outlet_count === 1 ? '' : 's'}
        </span>
      </div>

      <p className="text-sm leading-relaxed">{chain.sentence}</p>

      <div className="mt-3 flex gap-1 border-b border-edge">
        {TABS.map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`px-2 py-1 text-xs ${
              tab === t ? 'border-b-2 border-ink text-ink' : 'text-dim hover:text-ink'
            }`}
          >
            {t}
          </button>
        ))}
      </div>

      <div className="pt-3">
        {tab === 'Reading' && (
          <div className="space-y-2">
            <p className="text-xs text-dim">{chain.why}</p>
            <p className="rounded border border-edge bg-bg p-2 text-[11px] text-dim">
              {chain.caution} {chain.sources}
            </p>
            <div className="flex flex-wrap gap-2 text-[11px]">
              {chain.names.map((n, i) => (
                <Link
                  key={`${n}-${i}`}
                  href={chain.uids[i] ? `/case/${chain.uids[i]}` : '#'}
                  className="tag"
                >
                  {n}
                  {chain.types[i] ? ` · ${chain.types[i]}` : ''}
                </Link>
              ))}
            </div>
          </div>
        )}

        {tab === 'Proof' && (
          <ol className="space-y-2">
            {chain.steps.map((s, i) => (
              <li key={i} className="rounded border border-edge bg-bg p-2.5">
                <p className="text-xs">
                  <span className="text-ink">{s.from}</span>
                  <span className="text-dim"> {s.phrase} </span>
                  <span className="text-ink">{s.to}</span>
                </p>
                {s.quote ? (
                  <p className="mt-1 border-l-2 border-edge pl-2 text-[11px] text-dim">
                    {s.quote}
                  </p>
                ) : (
                  <p className="mt-1 text-[11px] text-bad">No quote stored for this step.</p>
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
            <li className="text-[11px] text-dim">
              These quotes are copied from the articles. Nothing above is written by the model.
            </li>
          </ol>
        )}

        {tab === 'Confidence' && (
          <div className="space-y-2">
            <p className={`text-xs ${CONF_COLOR[chain.confidence.level] || 'text-dim'}`}>
              Overall: {chain.confidence.level}. {chain.confidence.note}
            </p>
            <p className="text-[11px] text-dim">
              A chain is only as strong as its weakest step, so the overall figure is the
              lowest one below.
            </p>
            <div className="space-y-1.5">
              {chain.steps.map((s, i) => (
                <div key={i} className="flex items-center gap-2 text-[11px]">
                  <span className="flex-1 truncate">
                    {s.from} {s.phrase} {s.to}
                  </span>
                  <span className={CONF_COLOR[s.confidence.level] || 'text-dim'}>
                    {s.confidence.level}
                  </span>
                  <span className="w-16 text-right text-dim">
                    {s.outlets_backing} outlet{s.outlets_backing === 1 ? '' : 's'}
                  </span>
                </div>
              ))}
            </div>
            <p className="rounded border border-edge bg-bg p-2 text-[11px] text-dim">
              Relations are chosen by a small model reading the quote. They are checked
              against rules about what can hold between two kinds of name, but they are not
              hand verified. Treat the quote as the fact and the relation as a label.
            </p>
          </div>
        )}

        {tab === 'Time' && (
          <div className="space-y-2">
            <p className="text-[11px] text-dim">{chain.timeline.note}</p>
            {chain.timeline.ordered ? (
              <ol className="space-y-1.5">
                {chain.timeline.events.map((e, i) => (
                  <li key={i} className="flex gap-2 text-[11px]">
                    <span className="w-24 shrink-0 text-dim">{e.when.slice(0, 10)}</span>
                    <span>{e.what}</span>
                  </li>
                ))}
              </ol>
            ) : (
              <p className="text-[11px] text-dim">
                Dates come from when the article was recorded, not when the event happened.
              </p>
            )}
          </div>
        )}
      </div>
    </article>
  );
}
