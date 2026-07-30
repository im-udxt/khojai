'use client';

import { useEffect, useMemo, useRef, useState } from 'react';
import Link from 'next/link';
import { getJSON } from '@/lib/api';

type Node = { id: string; label: string; type: string };
type Edge = { source: string; target: string; relation: string };
type Net = { nodes: Node[]; edges: Edge[] };
type Placed = Node & { x: number; y: number; vx: number; vy: number };

const COLOR: Record<string, string> = {
  Person: '#7dd3fc',
  Company: '#4ade80',
  Government: '#fbbf24',
  Court: '#f87171',
  Place: '#c084fc',
  Topic: '#9195a1',
  Event: '#fb923c',
};

const W = 900;
const H = 560;

export default function LinkMap({ query }: { query?: string }) {
  const [net, setNet] = useState<Net | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [hover, setHover] = useState<string | null>(null);
  const [picked, setPicked] = useState<string | null>(null);
  const [view, setView] = useState({ k: 1, x: 0, y: 0 });
  const drag = useRef<{ x: number; y: number; ox: number; oy: number } | null>(null);

  useEffect(() => {
    setNet(null);
    setPicked(null);
    getJSON<Net>(`/api/graph${query ? `?${query}` : ''}`)
      .then(setNet)
      .catch((e) => setError(String(e)));
  }, [query]);

  const placed = useMemo<Placed[]>(() => {
    if (!net?.nodes.length) return [];
    const n = net.nodes.length;
    const nodes: Placed[] = net.nodes.map((node, i) => ({
      ...node,
      x: W / 2 + Math.cos((i / n) * 6.283) * 200,
      y: H / 2 + Math.sin((i / n) * 6.283) * 200,
      vx: 0,
      vy: 0,
    }));
    const index = new Map(nodes.map((node, i) => [node.id, i]));
    const links = net.edges
      .map((e) => [index.get(e.source), index.get(e.target)])
      .filter((p): p is [number, number] => p[0] !== undefined && p[1] !== undefined);

    for (let step = 0; step < 300; step++) {
      for (let i = 0; i < nodes.length; i++) {
        for (let j = i + 1; j < nodes.length; j++) {
          const dx = nodes[i].x - nodes[j].x;
          const dy = nodes[i].y - nodes[j].y;
          const d2 = dx * dx + dy * dy || 0.01;
          const force = 2400 / d2;
          const d = Math.sqrt(d2);
          nodes[i].vx += (dx / d) * force;
          nodes[i].vy += (dy / d) * force;
          nodes[j].vx -= (dx / d) * force;
          nodes[j].vy -= (dy / d) * force;
        }
      }
      for (const [a, b] of links) {
        const dx = nodes[b].x - nodes[a].x;
        const dy = nodes[b].y - nodes[a].y;
        const d = Math.sqrt(dx * dx + dy * dy) || 0.01;
        const force = (d - 100) * 0.02;
        nodes[a].vx += (dx / d) * force;
        nodes[a].vy += (dy / d) * force;
        nodes[b].vx -= (dx / d) * force;
        nodes[b].vy -= (dy / d) * force;
      }
      for (const node of nodes) {
        node.vx += (W / 2 - node.x) * 0.002;
        node.vy += (H / 2 - node.y) * 0.002;
        node.x = Math.max(20, Math.min(W - 20, node.x + Math.max(-12, Math.min(12, node.vx))));
        node.y = Math.max(20, Math.min(H - 20, node.y + Math.max(-12, Math.min(12, node.vy))));
        node.vx *= 0.8;
        node.vy *= 0.8;
      }
    }
    return nodes;
  }, [net]);

  const spot = useMemo(() => new Map(placed.map((p) => [p.id, p])), [placed]);
  const degree = useMemo(() => {
    const d = new Map<string, number>();
    net?.edges.forEach((e) => {
      d.set(e.source, (d.get(e.source) || 0) + 1);
      d.set(e.target, (d.get(e.target) || 0) + 1);
    });
    return d;
  }, [net]);
  const near = useMemo(() => {
    const m = new Map<string, Set<string>>();
    net?.edges.forEach((e) => {
      if (!m.has(e.source)) m.set(e.source, new Set());
      if (!m.has(e.target)) m.set(e.target, new Set());
      m.get(e.source)!.add(e.target);
      m.get(e.target)!.add(e.source);
    });
    return m;
  }, [net]);

  const focus = hover || picked;
  const chosen = picked ? net?.nodes.find((n) => n.id === picked) : null;

  if (error) return <p className="text-sm text-bad">The map could not load.</p>;
  if (!net) return <p className="text-sm text-dim">Building the map.</p>;
  if (!net.nodes.length)
    return (
      <p className="text-sm text-dim">
        Nothing to show for this filter yet. Links appear here as articles are read.
      </p>
    );

  return (
    <div>
      <div className="mb-2 flex flex-wrap items-center gap-3 text-[11px] text-dim">
        {Object.entries(COLOR).map(([t, c]) => (
          <span key={t} className="flex items-center gap-1">
            <span className="inline-block h-2 w-2 rounded-full" style={{ background: c }} />
            {t}
          </span>
        ))}
        <span className="ml-auto flex gap-1">
          <button
            onClick={() => setView((v) => ({ ...v, k: Math.min(3, v.k + 0.2) }))}
            className="rounded border border-edge px-2"
          >
            +
          </button>
          <button
            onClick={() => setView((v) => ({ ...v, k: Math.max(0.4, v.k - 0.2) }))}
            className="rounded border border-edge px-2"
          >
            -
          </button>
          <button
            onClick={() => setView({ k: 1, x: 0, y: 0 })}
            className="rounded border border-edge px-2"
          >
            reset
          </button>
        </span>
      </div>

      <div className="relative">
        <svg
          viewBox={`0 0 ${W} ${H}`}
          className="w-full cursor-grab rounded border border-edge bg-bg active:cursor-grabbing"
          onWheel={(e) => setView((v) => ({ ...v, k: Math.max(0.4, Math.min(3, v.k - e.deltaY * 0.001)) }))}
          onMouseDown={(e) => (drag.current = { x: e.clientX, y: e.clientY, ox: view.x, oy: view.y })}
          onMouseMove={(e) => {
            if (!drag.current) return;
            setView((v) => ({
              ...v,
              x: drag.current!.ox + (e.clientX - drag.current!.x),
              y: drag.current!.oy + (e.clientY - drag.current!.y),
            }));
          }}
          onMouseUp={() => (drag.current = null)}
          onMouseLeave={() => (drag.current = null)}
        >
          <g transform={`translate(${view.x},${view.y}) scale(${view.k})`}>
            {net.edges.map((e, i) => {
              const a = spot.get(e.source);
              const b = spot.get(e.target);
              if (!a || !b) return null;
              const lit = focus === e.source || focus === e.target;
              return (
                <line
                  key={i}
                  x1={a.x}
                  y1={a.y}
                  x2={b.x}
                  y2={b.y}
                  stroke={lit ? '#7dd3fc' : '#2a2d35'}
                  strokeWidth={lit ? 1.5 : 0.7}
                  opacity={focus && !lit ? 0.12 : 0.75}
                >
                  <title>{e.relation.toLowerCase().replace(/_/g, ' ')}</title>
                </line>
              );
            })}
            {placed.map((node) => {
              const r = 5 + Math.min((degree.get(node.id) || 0) * 1.2, 12);
              const faded = focus && focus !== node.id && !near.get(focus)?.has(node.id);
              return (
                <g
                  key={node.id}
                  transform={`translate(${node.x},${node.y})`}
                  onMouseEnter={() => setHover(node.id)}
                  onMouseLeave={() => setHover(null)}
                  onClick={() => setPicked(node.id)}
                  style={{ cursor: 'pointer', opacity: faded ? 0.2 : 1 }}
                >
                  <circle
                    r={r}
                    fill={COLOR[node.type] || COLOR.Topic}
                    stroke={picked === node.id ? '#fff' : '#0c0d10'}
                    strokeWidth={picked === node.id ? 2 : 1}
                  />
                  {(focus === node.id || r > 9) && (
                    <text x={r + 3} y={4} fontSize={10} fill="#c8cad1">
                      {node.label.length > 26 ? node.label.slice(0, 26) + '...' : node.label}
                    </text>
                  )}
                </g>
              );
            })}
          </g>
        </svg>

        {chosen && (
          <div className="absolute right-2 top-2 w-56 rounded border border-edge bg-panel/95 p-3 text-xs">
            <div className="mb-1 flex items-center gap-2">
              <span
                className="inline-block h-2.5 w-2.5 rounded-full"
                style={{ background: COLOR[chosen.type] || COLOR.Topic }}
              />
              <span className="font-medium">{chosen.label}</span>
              <button onClick={() => setPicked(null)} className="ml-auto text-dim">
                x
              </button>
            </div>
            <p className="text-dim">
              {chosen.type} with {degree.get(chosen.id) || 0} links
            </p>
            <Link href={`/entity/${chosen.id}`} className="mt-2 inline-block">
              Open this name
            </Link>
          </div>
        )}
      </div>

      <p className="mt-2 text-[11px] text-dim">
        {net.nodes.length} names and {net.edges.length} links. Scroll to zoom, drag to move,
        click a dot to open it.
      </p>
    </div>
  );
}
