"use client";

import { useState } from "react";
import type { RetrievalRun } from "@/lib/api";

const SERIES = "#3987e5";
const GRID = "#27272a";
const AXIS_TEXT = "#71717a";

type Tip = { left: number; top: number; value: string; lines: string[] } | null;

function niceMax(value: number): number {
  if (value <= 4) return 4;
  const power = 10 ** Math.floor(Math.log10(value));
  for (const step of [1, 2, 2.5, 5, 10]) {
    if (step * power >= value) return step * power;
  }
  return 10 * power;
}

function columnPath(x: number, y: number, w: number, h: number, r: number): string {
  if (h <= 0) return "";
  const rr = Math.min(r, w / 2, h);
  return `M${x},${y + h} V${y + rr} Q${x},${y} ${x + rr},${y} H${x + w - rr} Q${x + w},${y} ${x + w},${y + rr} V${y + h} Z`;
}

function barPath(x: number, y: number, w: number, h: number, r: number): string {
  if (w <= 0) return "";
  const rr = Math.min(r, h / 2, w);
  return `M${x},${y} H${x + w - rr} Q${x + w},${y} ${x + w},${y + rr} V${y + h - rr} Q${x + w},${y + h} ${x + w - rr},${y + h} H${x} Z`;
}

function Tooltip({ tip }: { tip: Tip }) {
  if (!tip) return null;
  return (
    <div
      role="status"
      className="pointer-events-none absolute z-10 -translate-x-1/2 -translate-y-full rounded-lg border border-zinc-700 bg-zinc-950 px-3 py-2 text-xs shadow-none"
      style={{ left: `${tip.left}%`, top: `${tip.top}%` }}
    >
      <div className="text-sm font-semibold text-zinc-100">{tip.value}</div>
      {tip.lines.map((line) => (
        <div key={line} className="text-zinc-400">
          {line}
        </div>
      ))}
    </div>
  );
}

function lastDays(days: { day: string; queries: number }[], count: number) {
  const byDay = new Map(days.map((d) => [d.day, d.queries]));
  const out: { day: string; queries: number }[] = [];
  const today = new Date();
  for (let i = count - 1; i >= 0; i--) {
    const d = new Date(Date.UTC(today.getUTCFullYear(), today.getUTCMonth(), today.getUTCDate() - i));
    const key = d.toISOString().slice(0, 10);
    out.push({ day: key, queries: byDay.get(key) ?? 0 });
  }
  return out;
}

const shortDay = (iso: string) =>
  new Date(`${iso}T00:00:00Z`).toLocaleDateString(undefined, { month: "short", day: "numeric", timeZone: "UTC" });

export function QueriesPerDayChart({ days }: { days: { day: string; queries: number }[] }) {
  const [tip, setTip] = useState<Tip>(null);
  const data = lastDays(days, 14);
  const W = 640;
  const H = 210;
  const m = { top: 14, right: 8, bottom: 26, left: 34 };
  const plotW = W - m.left - m.right;
  const plotH = H - m.top - m.bottom;
  const max = niceMax(Math.max(...data.map((d) => d.queries), 1));
  const band = plotW / data.length;
  const colW = Math.min(24, band - 8);
  const ticks = [0, max / 2, max];
  const y = (v: number) => m.top + plotH - (v / max) * plotH;

  return (
    <figure className="grid gap-2">
      <div className="relative">
        <svg viewBox={`0 0 ${W} ${H}`} className="h-auto w-full" role="img" aria-label="Questions answered per day, last 14 days">
          {ticks.map((t) => (
            <g key={t}>
              <line x1={m.left} x2={W - m.right} y1={y(t)} y2={y(t)} stroke={GRID} strokeWidth={1} />
              <text x={m.left - 8} y={y(t) + 4} textAnchor="end" fontSize={11} fill={AXIS_TEXT}>
                {Number.isInteger(t) ? t : t.toFixed(1)}
              </text>
            </g>
          ))}
          {data.map((d, i) => {
            const x = m.left + i * band + (band - colW) / 2;
            const h = (d.queries / max) * plotH;
            const isLast = i === data.length - 1;
            return (
              <g key={d.day}>
                <path d={columnPath(x, m.top + plotH - h, colW, h, 4)} fill={SERIES} opacity={tip && tip.lines[0] !== shortDay(d.day) ? 0.55 : 1} />
                {isLast && d.queries > 0 && (
                  <text x={x + colW / 2} y={m.top + plotH - h - 6} textAnchor="middle" fontSize={11} fill="#e4e4e7">
                    {d.queries}
                  </text>
                )}
                {(i % 2 === 1 || isLast) && (
                  <text x={x + colW / 2} y={H - 8} textAnchor="middle" fontSize={11} fill={AXIS_TEXT}>
                    {shortDay(d.day)}
                  </text>
                )}
                <rect
                  x={m.left + i * band}
                  y={m.top}
                  width={band}
                  height={plotH}
                  fill="transparent"
                  tabIndex={0}
                  aria-label={`${shortDay(d.day)}: ${d.queries} questions`}
                  onMouseEnter={() => setTip({ left: ((x + colW / 2) / W) * 100, top: ((m.top + plotH - h) / H) * 100, value: `${d.queries} questions`, lines: [shortDay(d.day)] })}
                  onFocus={() => setTip({ left: ((x + colW / 2) / W) * 100, top: ((m.top + plotH - h) / H) * 100, value: `${d.queries} questions`, lines: [shortDay(d.day)] })}
                  onMouseLeave={() => setTip(null)}
                  onBlur={() => setTip(null)}
                />
              </g>
            );
          })}
          <line x1={m.left} x2={W - m.right} y1={m.top + plotH} y2={m.top + plotH} stroke="#3f3f46" strokeWidth={1} />
        </svg>
        <Tooltip tip={tip} />
      </div>
      <details className="text-xs text-zinc-400">
        <summary className="cursor-pointer hover:text-zinc-200">Show as table</summary>
        <table className="mt-2 w-full tabular-nums">
          <tbody>
            {data.map((d) => (
              <tr key={d.day} className="border-t border-zinc-800">
                <td className="py-1">{d.day}</td>
                <td className="py-1 text-right text-zinc-200">{d.queries}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </details>
    </figure>
  );
}

const pct = (v: number) => `${(v * 100).toFixed(1).replace(/\.0$/, "")}%`;

export function RetrievalRunsChart({ runs }: { runs: RetrievalRun[] }) {
  const [tip, setTip] = useState<Tip>(null);
  const rows = runs.slice(0, 8);
  const W = 640;
  const row = 30;
  const labelW = 200;
  const m = { top: 6, right: 52, bottom: 24 };
  const plotW = W - labelW - m.right;
  const H = m.top + rows.length * row + m.bottom;
  const barH = 14;
  const x = (v: number) => labelW + v * plotW;

  if (rows.length === 0) {
    return <p className="text-sm text-zinc-400">No evaluation runs yet. Run <code>python -m eval.run_eval</code>.</p>;
  }

  return (
    <figure className="grid gap-2">
      <div className="relative">
        <svg viewBox={`0 0 ${W} ${H}`} className="h-auto w-full" role="img" aria-label="Retrieval hit at 5 for the most recent evaluation runs">
          {[0, 0.25, 0.5, 0.75, 1].map((t) => (
            <g key={t}>
              <line x1={x(t)} x2={x(t)} y1={m.top} y2={H - m.bottom} stroke={GRID} strokeWidth={1} />
              <text x={x(t)} y={H - 7} textAnchor="middle" fontSize={11} fill={AXIS_TEXT}>
                {t * 100}%
              </text>
            </g>
          ))}
          {rows.map((r, i) => {
            const top = m.top + i * row + (row - barH) / 2;
            const label = r.label.length > 28 ? `${r.label.slice(0, 27)}…` : r.label;
            const show = () =>
              setTip({
                left: (x(r.hit_at_5) / W) * 100,
                top: (top / H) * 100,
                value: `${pct(r.hit_at_5)} hit@5`,
                lines: [r.label, `hit@1 ${pct(r.hit_at_1)} · hit@10 ${pct(r.hit_at_10)} · MRR ${r.mrr.toFixed(3)}`, `${r.mode ?? "?"} · ${r.collection ?? "?"}`],
              });
            return (
              <g key={`${r.label}-${r.created_at}`}>
                <text x={labelW - 10} y={top + barH - 3} textAnchor="end" fontSize={11.5} fill="#a1a1aa">
                  {label}
                </text>
                <path d={barPath(labelW, top, r.hit_at_5 * plotW, barH, 4)} fill={SERIES} />
                <text x={x(r.hit_at_5) + 6} y={top + barH - 3} fontSize={11.5} fill="#e4e4e7">
                  {pct(r.hit_at_5)}
                </text>
                <rect
                  x={0}
                  y={m.top + i * row}
                  width={W}
                  height={row}
                  fill="transparent"
                  tabIndex={0}
                  aria-label={`${r.label}: hit at 5 ${pct(r.hit_at_5)}`}
                  onMouseEnter={show}
                  onFocus={show}
                  onMouseLeave={() => setTip(null)}
                  onBlur={() => setTip(null)}
                />
              </g>
            );
          })}
        </svg>
        <Tooltip tip={tip} />
      </div>
      <p className="text-xs text-zinc-500">Newest run at the top. hit@5 is the share of the 40 questions whose answer file is in the top 5 results.</p>
    </figure>
  );
}
