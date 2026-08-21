'use client';

const PALETTE = ['#7dd3fc', '#4ade80', '#fbbf24', '#f87171', '#c084fc', '#fb923c', '#9195a1'];

export function Bars({
  rows,
  unit = '',
}: {
  rows: { name: string; value: number }[];
  unit?: string;
}) {
  const max = Math.max(...rows.map((r) => r.value), 1);
  if (!rows.length) return <p className="text-sm text-dim">No data yet.</p>;
  return (
    <div className="space-y-1.5">
      {rows.map((r, i) => (
        <div key={r.name} className="flex items-center gap-2 text-xs">
          <span className="w-36 shrink-0 truncate text-dim" title={r.name}>
            {r.name}
          </span>
          <span className="h-4 flex-1 overflow-hidden rounded bg-bg">
            <span
              className="block h-full rounded"
              style={{
                width: `${Math.max((r.value / max) * 100, 2)}%`,
                background: PALETTE[i % PALETTE.length],
              }}
            />
          </span>
          <span className="w-14 shrink-0 text-right tabular-nums">
            {r.value}
            {unit}
          </span>
        </div>
      ))}
    </div>
  );
}

export function Donut({ rows }: { rows: { name: string; value: number }[] }) {
  const total = rows.reduce((sum, r) => sum + r.value, 0);
  if (!total) return <p className="text-sm text-dim">No data yet.</p>;
  const R = 60;
  const C = 2 * Math.PI * R;
  let offset = 0;
  return (
    <div className="flex flex-wrap items-center gap-5">
      <svg viewBox="0 0 160 160" className="h-40 w-40 shrink-0">
        <g transform="translate(80,80) rotate(-90)">
          {rows.map((r, i) => {
            const share = r.value / total;
            const dash = share * C;
            const seg = (
              <circle
                key={r.name}
                r={R}
                fill="none"
                stroke={PALETTE[i % PALETTE.length]}
                strokeWidth={22}
                strokeDasharray={`${dash} ${C - dash}`}
                strokeDashoffset={-offset}
              />
            );
            offset += dash;
            return seg;
          })}
        </g>
        <text x="80" y="78" textAnchor="middle" className="fill-ink" fontSize="20">
          {total}
        </text>
        <text x="80" y="94" textAnchor="middle" className="fill-dim" fontSize="9">
          total
        </text>
      </svg>
      <ul className="space-y-1 text-xs">
        {rows.map((r, i) => (
          <li key={r.name} className="flex items-center gap-2">
            <span
              className="inline-block h-2.5 w-2.5 rounded-sm"
              style={{ background: PALETTE[i % PALETTE.length] }}
            />
            <span>{r.name}</span>
            <span className="text-dim">
              {r.value} ({Math.round((r.value / total) * 100)}%)
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

export function Trend({
  rows,
}: {
  rows: { day: string; processed: number; claims: number }[];
}) {
  if (!rows.length) return <p className="text-sm text-dim">No data yet.</p>;
  const max = Math.max(...rows.flatMap((r) => [r.processed, r.claims]), 1);
  const W = 520;
  const H = 140;
  const pad = 24;
  const stepX = (W - pad * 2) / Math.max(rows.length - 1, 1);
  const line = (key: 'processed' | 'claims') =>
    rows
      .map((r, i) => {
        const x = pad + i * stepX;
        const y = H - pad - (r[key] / max) * (H - pad * 2);
        return `${i === 0 ? 'M' : 'L'} ${x.toFixed(1)} ${y.toFixed(1)}`;
      })
      .join(' ');

  return (
    <div>
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full">
        <line x1={pad} y1={H - pad} x2={W - pad} y2={H - pad} stroke="#23252b" />
        <path d={line('processed')} fill="none" stroke="#7dd3fc" strokeWidth={2} />
        <path d={line('claims')} fill="none" stroke="#4ade80" strokeWidth={2} />
        {rows.map((r, i) => (
          <text
            key={r.day}
            x={pad + i * stepX}
            y={H - 8}
            textAnchor="middle"
            fontSize="9"
            fill="#9195a1"
          >
            {r.day}
          </text>
        ))}
      </svg>
      <div className="flex gap-4 text-xs text-dim">
        <span className="flex items-center gap-1">
          <span className="inline-block h-2 w-2 rounded-sm" style={{ background: '#7dd3fc' }} />
          articles read
        </span>
        <span className="flex items-center gap-1">
          <span className="inline-block h-2 w-2 rounded-sm" style={{ background: '#4ade80' }} />
          links found
        </span>
      </div>
    </div>
  );
}
