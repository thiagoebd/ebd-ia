import { useEffect, useState } from "react";
import {
  ResponsiveContainer, LineChart, Line, BarChart, Bar,
  XAxis, YAxis, CartesianGrid, Tooltip, Legend,
} from "recharts";
import type { ArtifactRef } from "./ArtifactCard";

const API_BASE = import.meta.env.VITE_API_BASE_URL;

// Paleta EBD (tokens 16/06): navy = acento principal, vermelho EBD = 2a serie
const SERIES_COLORS = ["#1c2c5e", "#C8102E"];

type ChartSpec = {
  chart_type: "line" | "bar";
  title: string;
  x_key: string;
  series: { key: string; label: string }[];
  data: Record<string, string | number>[];
  y_format?: "money" | "int" | "percent";
  footer: string;
};

const fmtFull = {
  money: (v: number) => v.toLocaleString("pt-BR", { style: "currency", currency: "BRL" }),
  int: (v: number) => v.toLocaleString("pt-BR"),
  percent: (v: number) => `${v.toLocaleString("pt-BR", { maximumFractionDigits: 1 })}%`,
};
const fmtAxis = {
  money: (v: number) => v.toLocaleString("pt-BR", { notation: "compact", maximumFractionDigits: 1 }),
  int: (v: number) => v.toLocaleString("pt-BR", { notation: "compact" }),
  percent: (v: number) => `${v}%`,
};

export function ChartCard(
  { artifact, getToken }: { artifact: ArtifactRef; getToken: () => Promise<string> }
) {
  const [spec, setSpec] = useState<ChartSpec | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const tok = await getToken();
        const r = await fetch(`${API_BASE}/api/artifacts/${artifact.id}/download`, {
          headers: { Authorization: `Bearer ${tok}` },
        });
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        const s = (await r.json()) as ChartSpec;
        if (alive) setSpec(s);
      } catch (e) {
        if (alive) setErr(e instanceof Error ? e.message : String(e));
      }
    })();
    return () => { alive = false; };
  }, [artifact.id]);

  if (err) return <div className="artifact-card">⚠ Não consegui carregar o gráfico ({err})</div>;
  if (!spec) return <div className="artifact-card">Carregando gráfico…</div>;

  const yf = spec.y_format ?? "int";
  const axisFmt = fmtAxis[yf];
  const fullFmt = fmtFull[yf];
  const common = { data: spec.data, margin: { top: 8, right: 16, bottom: 4, left: 8 } };

  return (
    <div style={{ background: "#fff", border: "1px solid #E0E0E0", borderRadius: 10, padding: "14px 16px", margin: "8px 0" }}>
      <div style={{ fontWeight: 600, color: "#1A1A1A", marginBottom: 8 }}>{spec.title}</div>
      <ResponsiveContainer width="100%" height={300}>
        {spec.chart_type === "line" ? (
          <LineChart {...common}>
            <CartesianGrid strokeDasharray="3 3" stroke="#E0E0E0" />
            <XAxis dataKey={spec.x_key} tick={{ fontSize: 12 }} />
            <YAxis tickFormatter={axisFmt} tick={{ fontSize: 12 }} width={70} />
            <Tooltip formatter={(v) => fullFmt(Number(v))} />
            {spec.series.length > 1 && <Legend />}
            {spec.series.map((s, i) => (
              <Line key={s.key} type="monotone" dataKey={s.key} name={s.label}
                    stroke={SERIES_COLORS[i]} strokeWidth={2} dot={spec.data.length <= 20} />
            ))}
          </LineChart>
        ) : (
          <BarChart {...common}>
            <CartesianGrid strokeDasharray="3 3" stroke="#E0E0E0" vertical={false} />
            <XAxis dataKey={spec.x_key} tick={{ fontSize: 12 }} />
            <YAxis tickFormatter={axisFmt} tick={{ fontSize: 12 }} width={70} />
            <Tooltip formatter={(v) => fullFmt(Number(v))} />
            {spec.series.length > 1 && <Legend />}
            {spec.series.map((s, i) => (
              <Bar key={s.key} dataKey={s.key} name={s.label} fill={SERIES_COLORS[i]} radius={[3, 3, 0, 0]} />
            ))}
          </BarChart>
        )}
      </ResponsiveContainer>
      <div style={{ fontSize: 12, color: "#666", fontStyle: "italic", marginTop: 6 }}>{spec.footer}</div>
    </div>
  );
}
