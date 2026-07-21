import { useEffect, useRef, useState } from "react";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import type { ArtifactRef } from "./ArtifactCard";

const API_BASE = import.meta.env.VITE_API_BASE_URL;
const NAVY = "#1c2c5e";
const RED = "#C8102E";

type Point = {
  seq: number | null; codcli: number; cliente: string;
  lat: number; lng: number; municipio: string | null;
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

function numberedIcon(n: number, stacked: boolean) {
  return L.divIcon({
    className: "",
    html: `<div style="background:${stacked ? RED : NAVY};color:#fff;width:26px;height:26px;
      border-radius:50% 50% 50% 0;transform:rotate(-45deg);display:flex;align-items:center;
      justify-content:center;box-shadow:0 1px 4px rgba(0,0,0,.4);border:2px solid #fff;">
      <span style="transform:rotate(45deg);font:600 11px system-ui;">${n}</span></div>`,
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

    const dodged = dodgeOverlaps(pts);
    const line = pts.map((p) => [p.lat, p.lng] as [number, number]);
    L.polyline(line, { color: NAVY, weight: 2, opacity: 0.5, dashArray: "5,6" }).addTo(map);

    dodged.forEach((p) => {
      const k = `${p.lat.toFixed(6)},${p.lng.toFixed(6)}`;
      const stacked = spec.points.filter((q) => `${q.lat.toFixed(6)},${q.lng.toFixed(6)}` === k).length > 1;
      L.marker([p.dlat, p.dlng], { icon: numberedIcon(p.seq ?? p.codcli, stacked) })
        .addTo(map)
        .bindPopup(
          `<b>${p.cliente}</b><br>cód ${p.codcli}${p.seq != null ? ` · seq ${p.seq}` : ""}` +
          `${p.municipio ? `<br>${p.municipio}` : ""}${stacked ? `<br><i>coord. aproximada</i>` : ""}`
        );
    });

    map.fitBounds(L.latLngBounds(line).pad(0.12));
    setTimeout(() => map.invalidateSize(), 120);
  }, [spec]);

  useEffect(() => () => { mapRef.current?.remove(); mapRef.current = null; }, []);

  if (err) return <div className="artifact-card mapcard">⚠ Não consegui carregar o mapa ({err})</div>;
  if (!spec) return <div className="artifact-card mapcard">Carregando mapa…</div>;

  const aprox = spec.stats.plotados - spec.stats.coords_unicas;
  return (
    <div className="artifact-card mapcard" style={{ padding: 0, overflow: "hidden", display: "block" }}>
      {/* header enxuto, largura cheia */}
      <div style={{ padding: "10px 14px", borderBottom: "1px solid #e5e5e0" }}>
        <div style={{ fontWeight: 600, color: NAVY, fontSize: 15 }}>{spec.title}</div>
        <div style={{ fontSize: 12, color: "#666", marginTop: 2 }}>
          {spec.rca}{spec.dia ? ` · ${spec.dia}` : ""} · {spec.stats.plotados} clientes
        </div>
      </div>
      {/* mapa dominando, largura cheia */}
      <div ref={divRef} style={{ height: 460, width: "100%" }} />
      {/* rodape fininho de fonte, largura cheia */}
      <div style={{ padding: "8px 14px", fontSize: 11, color: "#888", borderTop: "1px solid #e5e5e0", lineHeight: 1.5 }}>
        {aprox > 0 ? `${aprox} cliente(s) em coordenada aproximada · ` : ""}
        {spec.stats.descartados ? `${spec.stats.descartados} sem coord · ` : ""}
        {spec.footer}
      </div>
    </div>
  );
}
