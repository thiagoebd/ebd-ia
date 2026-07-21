"""
routemap_builder.py — Artefato de mapa de roteiro (kind='route_map').

A spec JSON validada É o artefato: gravada em ARTIFACTS_DIR, renderizada
pelo MapCard (Leaflet) no frontend via a mesma rota de download.
Mesmo contrato de build_chart: retorna (artifact_id, file_path, filename, size_bytes).

Regras (codificadas, nao delegadas ao prompt):
- dedup por codcli (a PCROTACLI tem fan-out de linhas por cliente/dia);
- lat/lng chegam como string do Oracle (VARCHAR2) -> float; descarta invalidos
  e fora do Brasil (lat -34..6, lng -74..-34);
- agrupa pontos na MESMA coord (geocodacao grosseira por CEP/bairro) em stacks,
  pro frontend desempilhar; mantem a ordem de SEQUENCIA;
- footer obrigatorio.
"""
from __future__ import annotations

import json
import os
import re
import unicodedata
import uuid
from pathlib import Path

ARTIFACTS_DIR = Path(os.getenv("EBD_ARTIFACTS_DIR", "/var/ebd-ia/artifacts"))

MAX_POINTS = 200
# bounding box do Brasil (com folga) — descarta coord obviamente errada
BR_LAT = (-34.0, 6.0)
BR_LNG = (-74.5, -33.5)


def _slug(text: str, max_len: int = 40) -> str:
    t = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    t = re.sub(r"[^A-Za-z0-9]+", "_", t).strip("_").lower()
    return t[:max_len] or "roteiro"


def _to_float(v) -> float | None:
    if v is None:
        return None
    try:
        f = float(str(v).strip().replace(",", "."))
    except (ValueError, AttributeError):
        return None
    return f


def validate_routemap_spec(spec: dict) -> str | None:
    if not isinstance(spec, dict):
        return "spec deve ser um objeto"
    if not (spec.get("title") or "").strip():
        return "title obrigatorio"
    if not (spec.get("rca") or "").strip():
        return "rca obrigatorio"
    if not (spec.get("footer") or "").strip():
        return "footer obrigatorio: fonte + escopo (ex: 'Roteiro RCA 3366 de 21/07 - coord PCCLIENT')"
    pts = spec.get("points")
    if not isinstance(pts, list) or not pts:
        return "points deve ter ao menos 1 ponto"
    if len(pts) > MAX_POINTS:
        return f"points acima do limite ({MAX_POINTS})"
    return None


def _clean_points(raw: list[dict]) -> tuple[list[dict], dict]:
    """Dedup por codcli (mantem menor seq), parseia coord, descarta invalidos.
    Retorna (points_limpos, stats)."""
    seen: dict = {}
    descartados = 0
    for p in raw:
        cod = p.get("codcli")
        lat = _to_float(p.get("lat"))
        lng = _to_float(p.get("lng"))
        if cod is None or lat is None or lng is None:
            descartados += 1
            continue
        if not (BR_LAT[0] <= lat <= BR_LAT[1] and BR_LNG[0] <= lng <= BR_LNG[1]):
            descartados += 1
            continue
        seq = p.get("seq")
        prev = seen.get(cod)
        # mantem a ocorrencia de menor SEQUENCIA
        if prev is None or (seq is not None and (prev.get("seq") is None or seq < prev["seq"])):
            seen[cod] = {
                "seq": seq,
                "codcli": cod,
                "cliente": (p.get("cliente") or "").strip(),
                "lat": round(lat, 7),
                "lng": round(lng, 7),
                "municipio": (p.get("municipio") or "").strip() or None,
            }
    pts = sorted(seen.values(), key=lambda x: (x["seq"] is None, x["seq"] if x["seq"] is not None else 0))
    coords_unicas = len({(x["lat"], x["lng"]) for x in pts})
    stats = {
        "recebidos": len(raw),
        "plotados": len(pts),
        "descartados": descartados,
        "coords_unicas": coords_unicas,  # < plotados = geocodacao grosseira (pins empilhados)
    }
    return pts, stats


def build_route_map(spec: dict) -> tuple[str, Path, str, int]:
    """Valida, limpa e grava a spec do mapa. Retorna (artifact_id, file_path,
    filename, size_bytes) — mesmo contrato de build_chart/build_excel."""
    err = validate_routemap_spec(spec)
    if err:
        raise ValueError(err)

    points, stats = _clean_points(spec["points"])
    if not points:
        raise ValueError("nenhum ponto com coordenada valida apos limpeza")

    out = {
        "kind": "route_map",
        "title": spec["title"].strip(),
        "rca": spec["rca"].strip(),
        "dia": (spec.get("dia") or "").strip() or None,
        "footer": spec["footer"].strip(),
        "points": points,
        "stats": stats,
    }

    artifact_id = str(uuid.uuid4())
    filename = f"{_slug(spec['title'])}_{artifact_id[:8]}.json"
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    file_path = ARTIFACTS_DIR / filename
    payload = json.dumps(out, ensure_ascii=False, indent=2)
    file_path.write_text(payload, encoding="utf-8")
    return artifact_id, file_path, filename, len(payload.encode("utf-8"))


# --- autoteste contra pontos reais de Boa Vista (roda: python3 app/tools/routemap_builder.py) ---
if __name__ == "__main__":
    fixture = {
        "title": "Roteiro RCA 3366 - 21/07",
        "rca": "3366 - Antonio Fernando (fil 08)",
        "dia": "2026-07-21",
        "footer": "Roteiro do RCA 3366 de 21/07 - coord de cadastro PCCLIENT",
        "points": [
            {"seq": 1, "codcli": 49922, "cliente": "COMERCIAL LEAO LTDA-ME", "lat": "2.8491217", "lng": "-60.7464633", "municipio": "BOA VISTA"},
            {"seq": 2, "codcli": 49922, "cliente": "COMERCIAL LEAO LTDA-ME", "lat": "2.8491217", "lng": "-60.7464633", "municipio": "BOA VISTA"},  # dup
            {"seq": 3, "codcli": 171630, "cliente": "BISPO E LOBO LTDA", "lat": "2.8491217", "lng": "-60.7464633", "municipio": "BOA VISTA"},  # mesma coord
            {"seq": 7, "codcli": 45371, "cliente": "ELDA CAMILO MACUXI - ME", "lat": "2.7833978", "lng": "-60.7200118", "municipio": "BOA VISTA"},
            {"seq": 19, "codcli": 204432, "cliente": "DEIVIS JOSE ALCALA", "lat": "2.8260817", "lng": "-60.6728417", "municipio": "BOA VISTA"},
            {"seq": 99, "codcli": 90001, "cliente": "COORD INVALIDA", "lat": "0", "lng": "0", "municipio": "X"},  # fora do BR -> descarta
            {"seq": 98, "codcli": 90002, "cliente": "LAT VAZIA", "lat": None, "lng": "-60.7", "municipio": "X"},   # nula -> descarta
        ],
    }
    aid, path, fn, size = build_route_map(fixture)
    data = json.loads(path.read_text(encoding="utf-8"))
    print("OK build_route_map")
    print("  id:", aid, "| filename:", fn, "| bytes:", size)
    print("  stats:", data["stats"])
    print("  points plotados:", [(p["seq"], p["codcli"], p["cliente"]) for p in data["points"]])
    path.unlink()  # limpa o teste
