'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { useRouter } from 'next/navigation';
import { getJSON } from '@/lib/api';

type Node = { id: string; label: string; type: string };
type Edge = { source: string; target: string; relation: string };
type Net = { nodes: Node[]; edges: Edge[] };
type Body = Node & { x: number; y: number; vx: number; vy: number; deg: number };

const COLOR: Record<string, string> = {
  Person: '#7dd3fc',
  Company: '#4ade80',
  Government: '#fbbf24',
  Court: '#f87171',
  Place: '#c084fc',
  Party: '#f472b6',
  Topic: '#9195a1',
  Event: '#fb923c',
};

export default function LinkMap({ query }: { query?: string }) {
  const [net, setNet] = useState<Net | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [picked, setPicked] = useState<Node | null>(null);
  const [ready, setReady] = useState(false);

  const canvas = useRef<HTMLCanvasElement | null>(null);
  const bodies = useRef<Body[]>([]);
  const links = useRef<[number, number][]>([]);
  const view = useRef({ k: 1, x: 0, y: 0 });
  const drag = useRef<{ x: number; y: number; ox: number; oy: number } | null>(null);
  const hover = useRef<number>(-1);
  const pickedIdx = useRef<number>(-1);
  const frame = useRef<number>(0);
  const alpha = useRef(1);
  const router = useRouter();

  useEffect(() => {
    setNet(null);
    setPicked(null);
    setReady(false);
    getJSON<Net>(`/api/graph${query ? `?${query}` : ''}`)
      .then(setNet)
      .catch((e) => setError(String(e)));
  }, [query]);

  useEffect(() => {
    if (!net?.nodes.length) return;
    const index = new Map(net.nodes.map((n, i) => [n.id, i]));
    const deg = new Map<string, number>();
    net.edges.forEach((e) => {
      deg.set(e.source, (deg.get(e.source) || 0) + 1);
      deg.set(e.target, (deg.get(e.target) || 0) + 1);
    });
    const count = net.nodes.length;
    const spread = Math.min(320, 60 + count * 3);
    bodies.current = net.nodes.map((n, i) => ({
      ...n,
      x: Math.cos((i / count) * Math.PI * 2) * spread + (Math.random() - 0.5) * 30,
      y: Math.sin((i / count) * Math.PI * 2) * spread + (Math.random() - 0.5) * 30,
      vx: 0,
      vy: 0,
      deg: deg.get(n.id) || 0,
    }));
    links.current = net.edges
      .map((e) => [index.get(e.source), index.get(e.target)])
      .filter((p): p is [number, number] => p[0] !== undefined && p[1] !== undefined);
    alpha.current = 1;
    view.current = { k: 1, x: 0, y: 0 };
    pickedIdx.current = -1;
    setReady(true);
  }, [net]);

  const radiusOf = (b: Body) => 4 + Math.min(Math.sqrt(b.deg) * 2.6, 14);

  // A spatial grid keeps repulsion to nearby pairs. The previous version
  // compared every pair on every step, which is what made large graphs crawl.
  const step = useCallback(() => {
    const list = bodies.current;
    const n = list.length;
    if (!n) return;
    const a = alpha.current;
    if (a <= 0.005) return;

    const cell = 90;
    const grid = new Map<string, number[]>();
    for (let i = 0; i < n; i++) {
      const key = `${Math.round(list[i].x / cell)},${Math.round(list[i].y / cell)}`;
      const bucket = grid.get(key);
      if (bucket) bucket.push(i);
      else grid.set(key, [i]);
    }
    for (let i = 0; i < n; i++) {
      const bi = list[i];
      const cx = Math.round(bi.x / cell);
      const cy = Math.round(bi.y / cell);
      for (let gx = cx - 1; gx <= cx + 1; gx++) {
        for (let gy = cy - 1; gy <= cy + 1; gy++) {
          const bucket = grid.get(`${gx},${gy}`);
          if (!bucket) continue;
          for (const j of bucket) {
            if (j <= i) continue;
            const bj = list[j];
            const dx = bi.x - bj.x;
            const dy = bi.y - bj.y;
            let d2 = dx * dx + dy * dy;
            if (d2 > 8100 || d2 === 0) continue;
            if (d2 < 1) d2 = 1;
            const d = Math.sqrt(d2);
            const f = (2600 / d2) * a;
            const ux = (dx / d) * f;
            const uy = (dy / d) * f;
            bi.vx += ux;
            bi.vy += uy;
            bj.vx -= ux;
            bj.vy -= uy;
          }
        }
      }
    }
    for (const [x, y] of links.current) {
      const bx = list[x];
      const by = list[y];
      const dx = by.x - bx.x;
      const dy = by.y - bx.y;
      const d = Math.hypot(dx, dy) || 0.01;
      const f = (d - 110) * 0.035 * a;
      const ux = (dx / d) * f;
      const uy = (dy / d) * f;
      bx.vx += ux;
      bx.vy += uy;
      by.vx -= ux;
      by.vy -= uy;
    }
    for (let i = 0; i < n; i++) {
      const b = list[i];
      b.vx -= b.x * 0.0016 * a;
      b.vy -= b.y * 0.0016 * a;
      b.x += Math.max(-18, Math.min(18, b.vx));
      b.y += Math.max(-18, Math.min(18, b.vy));
      b.vx *= 0.86;
      b.vy *= 0.86;
    }
    alpha.current = a * 0.985;
  }, []);

  const draw = useCallback(() => {
    const cv = canvas.current;
    if (!cv) return;
    const ctx = cv.getContext('2d');
    if (!ctx) return;
    const dpr = window.devicePixelRatio || 1;
    const w = cv.clientWidth;
    const h = cv.clientHeight;
    if (cv.width !== Math.round(w * dpr) || cv.height !== Math.round(h * dpr)) {
      cv.width = Math.round(w * dpr);
      cv.height = Math.round(h * dpr);
    }
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);

    const { k, x, y } = view.current;
    ctx.save();
    ctx.translate(w / 2 + x, h / 2 + y);
    ctx.scale(k, k);

    const list = bodies.current;
    const focus = hover.current >= 0 ? hover.current : pickedIdx.current;
    const lit = new Set<number>();
    if (focus >= 0) {
      lit.add(focus);
      for (const [a, b] of links.current) {
        if (a === focus) lit.add(b);
        if (b === focus) lit.add(a);
      }
    }

    ctx.lineWidth = 1 / k;
    for (const [a, b] of links.current) {
      const on = focus >= 0 && (a === focus || b === focus);
      ctx.strokeStyle = on ? '#7dd3fc' : '#2a2d35';
      ctx.globalAlpha = focus >= 0 ? (on ? 0.9 : 0.06) : 0.5;
      ctx.beginPath();
      ctx.moveTo(list[a].x, list[a].y);
      ctx.lineTo(list[b].x, list[b].y);
      ctx.stroke();
    }
    ctx.globalAlpha = 1;

    for (let i = 0; i < list.length; i++) {
      const b = list[i];
      const r = radiusOf(b);
      const dim = focus >= 0 && !lit.has(i);
      ctx.globalAlpha = dim ? 0.15 : 1;
      ctx.beginPath();
      ctx.arc(b.x, b.y, r, 0, Math.PI * 2);
      ctx.fillStyle = COLOR[b.type] || COLOR.Topic;
      ctx.fill();
      if (i === pickedIdx.current) {
        ctx.strokeStyle = '#ffffff';
        ctx.lineWidth = 2 / k;
        ctx.stroke();
      }
      if (!dim && (k > 0.75 || r > 8 || i === focus)) {
        ctx.globalAlpha = 0.92;
        ctx.fillStyle = '#c8cad1';
        ctx.font = `${Math.max(9, 11 / k)}px ui-sans-serif, system-ui, sans-serif`;
        const label = b.label.length > 26 ? `${b.label.slice(0, 26)}...` : b.label;
        ctx.fillText(label, b.x + r + 3 / k, b.y + 3 / k);
      }
    }
    ctx.restore();
  }, []);

  useEffect(() => {
    if (!ready) return;
    let running = true;
    const tick = () => {
      if (!running) return;
      step();
      draw();
      frame.current = requestAnimationFrame(tick);
    };
    frame.current = requestAnimationFrame(tick);
    return () => {
      running = false;
      cancelAnimationFrame(frame.current);
    };
  }, [ready, step, draw]);

  const hit = (clientX: number, clientY: number) => {
    const cv = canvas.current;
    if (!cv) return -1;
    const rect = cv.getBoundingClientRect();
    const { k, x, y } = view.current;
    const wx = (clientX - rect.left - rect.width / 2 - x) / k;
    const wy = (clientY - rect.top - rect.height / 2 - y) / k;
    const list = bodies.current;
    for (let i = list.length - 1; i >= 0; i--) {
      const b = list[i];
      const r = radiusOf(b) + 4;
      if ((b.x - wx) ** 2 + (b.y - wy) ** 2 <= r * r) return i;
    }
    return -1;
  };

  const onWheel = (e: React.WheelEvent) => {
    const cv = canvas.current;
    if (!cv) return;
    const rect = cv.getBoundingClientRect();
    const px = e.clientX - rect.left - rect.width / 2;
    const py = e.clientY - rect.top - rect.height / 2;
    const v = view.current;
    const next = Math.max(0.2, Math.min(6, v.k * (e.deltaY < 0 ? 1.12 : 1 / 1.12)));
    // Hold the point under the pointer still while the scale changes.
    v.x = px - ((px - v.x) / v.k) * next;
    v.y = py - ((py - v.y) / v.k) * next;
    v.k = next;
  };

  const zoomBy = (factor: number) => {
    const v = view.current;
    v.k = Math.max(0.2, Math.min(6, v.k * factor));
  };

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
          <button onClick={() => zoomBy(1.25)} className="rounded border border-edge px-2">
            +
          </button>
          <button onClick={() => zoomBy(0.8)} className="rounded border border-edge px-2">
            -
          </button>
          <button
            onClick={() => {
              view.current = { k: 1, x: 0, y: 0 };
              alpha.current = 0.6;
            }}
            className="rounded border border-edge px-2"
          >
            reset
          </button>
        </span>
      </div>

      {error && <p className="text-sm text-bad">The map could not load.</p>}
      {!error && !net && <p className="text-sm text-dim">Building the map.</p>}
      {!error && net && net.nodes.length === 0 && (
        <p className="text-sm text-dim">
          Nothing to show for this filter yet. Links appear here as articles are read.
        </p>
      )}

      {!error && net && net.nodes.length > 0 && (
        <div className="relative">
          <canvas
            ref={canvas}
            className="h-[560px] w-full cursor-grab touch-none rounded border border-edge bg-bg active:cursor-grabbing"
            onWheel={onWheel}
            onMouseDown={(e) => {
              drag.current = {
                x: e.clientX,
                y: e.clientY,
                ox: view.current.x,
                oy: view.current.y,
              };
            }}
            onMouseMove={(e) => {
              if (drag.current) {
                view.current.x = drag.current.ox + (e.clientX - drag.current.x);
                view.current.y = drag.current.oy + (e.clientY - drag.current.y);
                return;
              }
              hover.current = hit(e.clientX, e.clientY);
            }}
            onMouseUp={(e) => {
              const moved =
                drag.current !== null &&
                (Math.abs(e.clientX - drag.current.x) > 4 ||
                  Math.abs(e.clientY - drag.current.y) > 4);
              drag.current = null;
              if (moved) return;
              const i = hit(e.clientX, e.clientY);
              pickedIdx.current = i;
              setPicked(i >= 0 ? bodies.current[i] : null);
            }}
            onMouseLeave={() => {
              drag.current = null;
              hover.current = -1;
            }}
          />

          {picked && (
            <div className="absolute right-2 top-2 w-56 rounded border border-edge bg-panel/95 p-3 text-xs">
              <div className="mb-1 flex items-center gap-2">
                <span
                  className="inline-block h-2.5 w-2.5 rounded-full"
                  style={{ background: COLOR[picked.type] || COLOR.Topic }}
                />
                <span className="font-medium">{picked.label}</span>
                <button
                  onClick={() => {
                    setPicked(null);
                    pickedIdx.current = -1;
                  }}
                  className="ml-auto text-dim"
                >
                  x
                </button>
              </div>
              <p className="text-dim">{picked.type}</p>
              <button
                onClick={() => router.push(`/entity/${picked.id}`)}
                className="mt-2 rounded border border-edge px-2 py-1"
              >
                Open this name
              </button>
            </div>
          )}
        </div>
      )}

      {net && net.nodes.length > 0 && (
        <p className="mt-2 text-[11px] text-dim">
          {net.nodes.length} names and {net.edges.length} links. Scroll to zoom at the pointer, drag
          to move, click a dot to open it.
        </p>
      )}
    </div>
  );
}
