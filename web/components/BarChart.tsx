export interface BarSeries {
  key: string;
  label: string;
  color: string;
}

export interface BarRow {
  /** Short x-axis label, e.g. "14". */
  label: string;
  /** Long label used in tooltips, e.g. "14/10". */
  title: string;
  values: Record<string, number>;
}

function niceStep(raw: number, integer: boolean): number {
  if (raw <= 0) return 1;
  const pow = Math.pow(10, Math.floor(Math.log10(raw)));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * pow).find((s) => s >= raw) ?? 10 * pow;
  return integer ? Math.max(1, Math.ceil(step)) : step;
}

/** Stacked (or single-series) bar chart drawn as plain SVG. */
export function BarChart({
  rows,
  series,
  ariaLabel,
  format = (v) => String(v),
  integer = true,
}: {
  rows: BarRow[];
  series: BarSeries[];
  ariaLabel: string;
  format?: (v: number) => string;
  integer?: boolean;
}) {
  const W = 640;
  const H = 230;
  const L = 44;
  const R = 8;
  const T = 18;
  const B = 26;
  const n = rows.length;
  const totals = rows.map((r) => series.reduce((s, x) => s + (r.values[x.key] || 0), 0));
  const maxTotal = Math.max(0, ...totals);
  const step = niceStep(maxTotal / 4, integer);
  const max = Math.max(step, Math.ceil(maxTotal / step) * step);
  const ticks: number[] = [];
  for (let t = 0; t <= max + step / 1000; t += step) ticks.push(Number(t.toFixed(6)));
  const iw = W - L - R;
  const ih = H - T - B;
  const slot = iw / Math.max(1, n);
  const bw = slot * 0.62;
  const y = (v: number) => T + ih - (v / max) * ih;
  const every = Math.max(1, Math.ceil(n / 8));
  const tickFmt = (t: number) => (integer ? String(t) : format(t));

  return (
    <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={ariaLabel}>
      {ticks.map((t) => (
        <g key={t}>
          <line x1={L} x2={W - R} y1={y(t)} y2={y(t)} stroke="var(--line)" strokeWidth="1" />
          <text x={L - 8} y={y(t) + 4} textAnchor="end" fontSize="11" fill="var(--muted)">
            {tickFmt(t)}
          </text>
        </g>
      ))}
      {rows.map((r, i) => {
        const x = L + i * slot + (slot - bw) / 2;
        let base = 0;
        const last = i === n - 1;
        return (
          <g key={r.title + i}>
            {series.map((s) => {
              const v = r.values[s.key] || 0;
              const y0 = y(base);
              base += v;
              if (v <= 0) return null;
              return (
                <rect key={s.key} x={x.toFixed(1)} y={y(base).toFixed(1)} width={bw.toFixed(1)} height={(y0 - y(base)).toFixed(1)} fill={s.color} opacity={last ? 1 : 0.85}>
                  <title>{`${r.title} · ${s.label}: ${format(v)}`}</title>
                </rect>
              );
            })}
            {((n - 1 - i) % every === 0 || last) && (
              <text x={(x + bw / 2).toFixed(1)} y={H - 8} textAnchor="middle" fontSize="11" fill="var(--muted)">
                {r.label}
              </text>
            )}
          </g>
        );
      })}
      {n > 0 && (
        <text x={(L + (n - 1) * slot + slot / 2).toFixed(1)} y={(y(totals[n - 1]) - 6).toFixed(1)} textAnchor="middle" fontSize="11" fontWeight="600" fill="var(--fg)">
          {format(totals[n - 1])}
        </text>
      )}
    </svg>
  );
}

export function Legend({ series }: { series: BarSeries[] }) {
  return (
    <div className="legend">
      {series.map((s) => (
        <span key={s.key}>
          <i style={{ background: s.color }} />
          {s.label}
        </span>
      ))}
    </div>
  );
}
