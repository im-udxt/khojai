'use client';

import { usePoll, num } from '@/lib/api';

type Quote = {
  symbol: string;
  label: string;
  kind: string;
  price: number | null;
  change_pct: number | null;
};

export default function Markets() {
  const { data } = usePoll<{ quotes: Quote[] }>('/api/markets', 5 * 60 * 1000);
  const quotes = (data?.quotes || []).filter((q) => q.price !== null);
  if (!quotes.length) return null;

  return (
    <div className="border-b border-edge bg-panel">
      <div className="mx-auto flex max-w-6xl flex-wrap gap-x-6 gap-y-1 px-4 py-1.5 text-xs">
        {quotes.map((q) => {
          const up = (q.change_pct ?? 0) >= 0;
          return (
            <span key={q.symbol} className="flex items-center gap-1.5">
              <span className="text-dim">{q.label}</span>
              <span>{num(q.price, 2)}</span>
              <span className={up ? 'text-good' : 'text-bad'}>
                {up ? '+' : ''}
                {num(q.change_pct, 2)}%
              </span>
            </span>
          );
        })}
      </div>
    </div>
  );
}
