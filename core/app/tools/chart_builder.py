"""
chart_builder.py — Artefato de gráfico (kind='chart').

A spec JSON validada É o artefato: gravada em ARTIFACTS_DIR, renderizada
pelo ChartCard (Recharts) no frontend via rota de download existente.

Regras de validação (codificadas, não delegadas ao prompt):
- chart_type: só 'line' (série temporal) e 'bar' (comparação de magnitude).
  Pizza excluída por evidência perceptual (Cleveland & McGill 1984, JASA:
  posição em escala comum > ângulo/área em acurácia de estimativa).
- máx. 2 séries (legibilidade / mesma literatura).
- máx. 60 pontos.
- footer OBRIGATÓRIO: rodapé de fonte em linguagem de negócio (regra nível A).
"""

from __future__ import annotations

import json
import os
import re
import unicodedata
import uuid
from pathlib import Path

ARTIFACTS_DIR = Path(os.getenv("EBD_ARTIFACTS_DIR", "/var/ebd-ia/artifacts"))

VALID_TYPES = {"line", "bar"}
VALID_Y_FORMATS = {"money", "int", "percent"}
MAX_SERIES = 2
MAX_POINTS = 60


def _slug(text: str, max_len: int = 40) -> str:
    t = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    t = re.sub(r"[^A-Za-z0-9]+", "_", t).strip("_").lower()
    return t[:max_len] or "grafico"


def validate_chart_spec(spec: dict) -> str | None:
    """Retorna None se válida; string de erro (pt-BR, acionável) se não."""
    if not isinstance(spec, dict):
        return "spec deve ser um objeto"
    ct = spec.get("chart_type")
    if ct not in VALID_TYPES:
        return f"chart_type invalido: {ct!r}. Use 'line' (serie temporal) ou 'bar' (comparacao). Pizza nao e suportado."
    if not (spec.get("title") or "").strip():
        return "title obrigatorio"
    if not (spec.get("footer") or "").strip():
        return "footer obrigatorio: rodape de fonte em linguagem de negocio (ex: 'Faturamento liquido - visao BR - ultimos 7 dias')"
    x_key = spec.get("x_key")
    if not x_key:
        return "x_key obrigatorio"
    series = spec.get("series")
    if not isinstance(series, list) or not (1 <= len(series) <= MAX_SERIES):
        return f"series deve ter 1 a {MAX_SERIES} itens (limite de legibilidade)"
    for s in series:
        if not isinstance(s, dict) or not s.get("key") or not s.get("label"):
            return "cada serie precisa de key e label"
    data = spec.get("data")
    if not isinstance(data, list) or not (1 <= len(data) <= MAX_POINTS):
        return f"data deve ter 1 a {MAX_POINTS} pontos"
    skeys = [s["key"] for s in series]
    for i, row in enumerate(data):
        if not isinstance(row, dict) or x_key not in row:
            return f"data[{i}] sem a chave x_key ({x_key!r})"
        for k in skeys:
            v = row.get(k)
            if not isinstance(v, (int, float)):
                return f"data[{i}].{k} deve ser numerico (recebi {type(v).__name__})"
    yf = spec.get("y_format", "int")
    if yf not in VALID_Y_FORMATS:
        return f"y_format invalido: {yf!r}. Use money, int ou percent."
    return None


def build_chart(spec: dict) -> tuple[str, Path, str, int]:
    """Valida e grava a spec. Retorna (artifact_id, file_path, filename, size_bytes)
    — mesmo contrato do build_excel. Levanta ValueError em spec invalida."""
    err = validate_chart_spec(spec)
    if err:
        raise ValueError(err)
    artifact_id = str(uuid.uuid4())
    filename = f"{_slug(spec['title'])}_{artifact_id[:8]}.json"
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    file_path = ARTIFACTS_DIR / filename
    payload = json.dumps(spec, ensure_ascii=False, indent=2)
    file_path.write_text(payload, encoding="utf-8")
    return artifact_id, file_path, filename, len(payload.encode("utf-8"))
