import { useEffect, useRef, useState } from "react";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import type { ArtifactRef } from "./ArtifactCard";

const API_BASE = import.meta.env.VITE_API_BASE_URL;

// Cores por status (mapa de positivação). Sem status → navy neutro.
const STATUS: Record<string, { cor: string; label: string }> = {
  vendeu:             { cor: "#1e9e4a", label: "Vendeu na rota" },
  visitou_nao_vendeu: { cor: "#c8102e", label: "Visitou, não vendeu" },
  nao_visitou:        { cor: "#e8b400", label: "Não visitou ainda" },
  fora_rota:          { cor: "#2563eb", label: "Fora da rota (vendeu)" },
  _default:           { cor: "#1c2c5e", label: "Sem status" },
};
const NAVY = "#1c2c5e";

type Point = {
  seq: number | null; codcli: number; cliente: string;
  lat: number; lng: number; municipio: string | null; status: string | null;
};
type RouteMapSpec = {
  title: string; rca: string; dia: string | null; footer: string;
  points: Point[];
  stats: { recebidos: number; plotados: number; descartados: number; coords_unicas: number };
};

function dodgeOverlaps(points: Point[]): (Point & { dlat: number; dlng: number })[] {
  const groups = new Map<string, Point[]>();
  for (const p of points) {
    const k = `${p.lat.toFixed(6)},${p.lng.toFixed(6)}`;
    (groups.get(k) ?? groups.set(k, []).get(k)!).push(p);
  }
  const out: (Point & { dlat: number; dlng: number })[] = [];
  for (const grp of groups.values()) {
    if (grp.length === 1) { out.push({ ...grp[0], dlat: grp[0].lat, dlng: grp[0].lng }); continue; }
    const R = 0.00025;
    grp.forEach((p, i) => {
      const ang = (2 * Math.PI * i) / grp.length;
      out.push({ ...p, dlat: p.lat + R * Math.cos(ang), dlng: p.lng + R * Math.sin(ang) });
    });
  }
  return out;
}

function pinIcon(label: string | number, cor: string) {
  return L.divIcon({
    className: "",
    html: `<div style="background:${cor};color:#fff;width:26px;height:26px;
      border-radius:50% 50% 50% 0;transform:rotate(-45deg);display:flex;align-items:center;
      justify-content:center;box-shadow:0 1px 4px rgba(0,0,0,.4);border:2px solid #fff;">
      <span style="transform:rotate(45deg);font:600 11px system-ui;">${label}</span></div>`,
    iconSize: [26, 26], iconAnchor: [13, 26], popupAnchor: [0, -24],
  });
}

export function MapCard(
  { artifact, getToken }: { artifact: ArtifactRef; getToken: () => Promise<string> }
) {
  const [spec, setSpec] = useState<RouteMapSpec | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const divRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<L.Map | null>(null);

  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const tok = await getToken();
        const r = await fetch(`${API_BASE}/api/artifacts/${artifact.id}/download`, {
          headers: { Authorization: `Bearer ${tok}` },
        });
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        const s = (await r.json()) as RouteMapSpec;
        if (alive) setSpec(s);
      } catch (e) {
        if (alive) setErr(e instanceof Error ? e.message : String(e));
      }
    })();
    return () => { alive = false; };
  }, [artifact.id]);

  useEffect(() => {
    if (!spec || !divRef.current || mapRef.current) return;
    const pts = spec.points.filter((p) => Number.isFinite(p.lat) && Number.isFinite(p.lng));
    if (!pts.length) return;

    const map = L.map(divRef.current, { scrollWheelZoom: false });
    mapRef.current = map;
    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      attribution: "© OpenStreetMap", maxZoom: 19,
    }).addTo(map);

    // polyline só pelos pontos DA ROTA (com seq), na ordem de sequência
    const rota = pts.filter((p) => p.seq != null).sort((a, b) => (a.seq! - b.seq!));
    if (rota.length > 1) {
      L.polyline(rota.map((p) => [p.lat, p.lng] as [number, number]),
        { color: NAVY, weight: 2, opacity: 0.4, dashArray: "5,6" }).addTo(map);
    }

    dodgeOverlaps(pts).forEach((p) => {
      const st = STATUS[p.status || "_default"] || STATUS._default;
      L.marker([p.dlat, p.dlng], { icon: pinIcon(p.seq ?? "•", st.cor) })
        .addTo(map)
        .bindPopup(
          `<b>${p.cliente}</b><br>cód ${p.codcli}${p.seq != null ? ` · seq ${p.seq}` : ""}` +
          `<br><span style="color:${st.cor};font-weight:600">${st.label}</span>` +
          `${p.municipio ? `<br>${p.municipio}` : ""}`
        );
    });

    map.fitBounds(L.latLngBounds(pts.map((p) => [p.lat, p.lng] as [number, number])).pad(0.12));
    setTimeout(() => map.invalidateSize(), 120);
  }, [spec]);

  useEffect(() => () => { mapRef.current?.remove(); mapRef.current = null; }, []);

  if (err) return <div className="artifact-card mapcard">⚠ Não consegui carregar o mapa ({err})</div>;
  if (!spec) return <div className="artifact-card mapcard">Carregando mapa…</div>;

  // legenda a partir dos pontos reais
  const counts: Record<string, number> = {};
  for (const p of spec.points) counts[p.status || "_default"] = (counts[p.status || "_default"] || 0) + 1;
  const hasStatus = spec.points.some((p) => p.status);
  const ordem = ["vendeu", "visitou_nao_vendeu", "nao_visitou", "fora_rota"];

  return (
    <div className="artifact-card mapcard" style={{ padding: 0, overflow: "hidden", display: "block" }}>
      <div style={{ padding: "10px 14px", borderBottom: "1px solid #e5e5e0" }}>
        <div style={{ fontWeight: 600, color: NAVY, fontSize: 15 }}>{spec.title}</div>
        <div style={{ fontSize: 12, color: "#666", marginTop: 2 }}>
          {spec.rca}{spec.dia ? ` · ${spec.dia}` : ""} · {spec.stats.plotados} clientes
        </div>
      </div>
      <div ref={divRef} style={{ height: 460, width: "100%" }} />
      {hasStatus && (
        <div style={{ display: "flex", flexWrap: "wrap", gap: "6px 16px", padding: "10px 14px", borderTop: "1px solid #e5e5e0", fontSize: 12 }}>
          {ordem.filter((k) => counts[k]).map((k) => (
            <span key={k} style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
              <span style={{ width: 11, height: 11, borderRadius: "50%", background: STATUS[k].cor, display: "inline-block" }} />
              {STATUS[k].label} <b>{counts[k]}</b>
            </span>
          ))}
        </div>
      )}
      <div style={{ padding: "8px 14px", fontSize: 11, color: "#888", borderTop: "1px solid #e5e5e0", lineHeight: 1.5 }}>
        {spec.footer}
      </div>
    </div>
  );
}
