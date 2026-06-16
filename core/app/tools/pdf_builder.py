"""Gerador de PDF com identidade visual EBD.

Saída: arquivo .pdf em /var/ebd-ia/artifacts/<uuid>.pdf
Recursos:
  - A4 retrato, margens 2cm
  - Logo EBD no canto superior DIREITO
  - Título grande à esquerda + subtítulo
  - Conteúdo via Markdown → HTML (tabelas, headers, listas, negrito)
  - Rodapé em todas páginas: "Gerado pelo EBD.ia em DD/MM/AAAA HH:MM ·
    A IA pode cometer erros, confira os dados"

Uso (standalone test):
  cd core && python3 -m app.tools.pdf_builder
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import markdown as md
from weasyprint import HTML, CSS

from app.artifacts import (
    ARTIFACTS_DIR,
    LOGO_PATH,
    EBD_NAVY,
    safe_filename,
    new_artifact_path,
    now_br_str,
)

# CSS embutido. WeasyPrint suporta @page com cabeçalho/rodapé fixos.
_BASE_CSS_TEMPLATE = """
@page {
    size: A4;
    margin: 1.5cm;
    @bottom-center {
        content: "Gerado pelo EBD.ia em FOOTER_STAMP · A IA pode cometer erros, confira os dados";
        font-family: 'DejaVu Sans', sans-serif;
        font-size: 7.5pt;
        color: #888;
        padding-top: 4mm;
        border-top: 0.3pt solid #ddd;
    }
    @bottom-right {
        content: "Página " counter(page) " de " counter(pages);
        font-family: 'DejaVu Sans', sans-serif;
        font-size: 7.5pt;
        color: #888;
        padding-top: 4mm;
    }
}

* { box-sizing: border-box; }

html, body {
    font-family: 'DejaVu Sans', 'Calibri', sans-serif;
    font-size: 9.5pt;
    line-height: 1.4;
    color: #2a2a2a;
    margin: 0; padding: 0;
}

.header {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    margin-bottom: 6mm;
    border-bottom: 0.4pt solid #ddd;
    padding-bottom: 3mm;
}

.header-text { flex: 1; padding-right: 8mm; }
.header h1 {
    margin: 0 0 1.5mm 0;
    font-size: 16pt;
    font-weight: 600;
    color: NAVY_COLOR;
    line-height: 1.15;
}
.header .subtitle {
    font-size: 9.5pt;
    color: #666;
    font-style: italic;
    margin: 0;
}
.header .meta {
    font-size: 8pt;
    color: #888;
    margin-top: 1.5mm;
}

.header .logo {
    width: 24mm;
    height: auto;
    flex-shrink: 0;
}

.content { padding-top: 1mm; }

.content h1, .content h2, .content h3 {
    color: NAVY_COLOR;
    margin-top: 4mm;
    margin-bottom: 1.5mm;
    font-weight: 600;
}
.content h1 { font-size: 12pt; }
.content h2 { font-size: 11pt; }
.content h3 { font-size: 10pt; }

.content p { margin: 0 0 2mm 0; }
.content strong { color: #1a1a1a; }

.content ul, .content ol {
    margin: 0 0 2mm 0;
    padding-left: 6mm;
}
.content li { margin-bottom: 0.8mm; }

table {
    width: 100%;
    border-collapse: collapse;
    margin: 2mm 0 3mm 0;
    font-size: 8.8pt;
}
thead th {
    background: #f5f5f0;
    color: NAVY_COLOR;
    font-weight: 600;
    text-align: left;
    padding: 1.8mm 2.5mm;
    border-bottom: 0.6pt solid #ccc;
}
tbody td {
    padding: 1.4mm 2.5mm;
    border-bottom: 0.25pt solid #eee;
}
tbody tr:nth-child(even) { background: #fafaf7; }

td.num { text-align: right; font-variant-numeric: tabular-nums; }

blockquote {
    border-left: 2.5px solid NAVY_COLOR;
    background: #f8f8f4;
    padding: 1.5mm 3mm;
    margin: 2mm 0;
    color: #444;
    font-style: italic;
}
""".replace("NAVY_COLOR", EBD_NAVY)


def _build_html(title: str, subtitle: str | None, markdown_body: str,
                metadata: dict | None, logo_uri: str) -> str:
    """Renderiza markdown → HTML completo pronto pra WeasyPrint."""
    metadata = metadata or {}
    body_html = md.markdown(
        markdown_body,
        extensions=["tables", "fenced_code", "sane_lists"],
    )

    meta_line_parts = []
    if metadata.get("source_label"):
        meta_line_parts.append(metadata["source_label"])
    if metadata.get("period"):
        meta_line_parts.append(metadata["period"])
    if metadata.get("scope"):
        meta_line_parts.append(metadata["scope"])
    meta_line = " · ".join(meta_line_parts)

    stamp = now_br_str()

    return f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
    <meta charset="UTF-8">
    <title>{title}</title>
</head>
<body>
    <div class="header">
        <div class="header-text">
            <h1>{title}</h1>
            {f'<p class="subtitle">{subtitle}</p>' if subtitle else ''}
            {f'<p class="meta">{meta_line}</p>' if meta_line else ''}
        </div>
        <img class="logo" src="{logo_uri}" alt="EBD" />
    </div>
    <div class="content">
        {body_html}
    </div>
</body>
</html>
"""


def build_pdf(
    title: str,
    markdown_body: str,
    subtitle: str | None = None,
    metadata: dict | None = None,
) -> tuple[str, Path, str, int]:
    """Gera PDF e salva em /var/ebd-ia/artifacts/<uuid>.pdf.

    Returns: (artifact_id_str, file_path, filename_humano, size_bytes)
    Note: artifact_id retornado é o UUID do disco. O caller deve usar
    o id do row retornado por create_artifact() ao registrar no DB.
    """
    artifact_id, file_path = new_artifact_path("pdf")
    filename = safe_filename(title, ext="pdf")
    logo_uri = Path(LOGO_PATH).resolve().as_uri()

    html_str = _build_html(title, subtitle, markdown_body, metadata, logo_uri)

    HTML(string=html_str, base_url=str(Path(LOGO_PATH).parent)).write_pdf(
        target=str(file_path),
        stylesheets=[CSS(string=_BASE_CSS_TEMPLATE.replace("FOOTER_STAMP", now_br_str()))],
    )

    size_bytes = file_path.stat().st_size
    return str(artifact_id), file_path, filename, size_bytes


# ─── teste standalone ────────────────────────────────────────────────────
if __name__ == "__main__":
    sample_md = """
## Resumo executivo

A ruptura de hoje no Brasil totaliza **R$ 139.918,71**, distribuída em **8 filiais**.

**EBD DUQUE concentra 78% do valor total** (R$ 109K) com apenas 8 SKUs em falta —
sugere produto(s) específico(s) de alto valor. Vale investigar quais SKUs estão lá.

**Boa Vista** chama atenção pelo volume de SKUs em ruptura (24) vs valor relativamente
baixo (R$ 6.641,87) — portfólio pulverizado.

## Detalhamento por filial

| Filial            | Valor Ruptura  | SKUs | Clientes | Pedidos |
|-------------------|---------------:|-----:|---------:|--------:|
| EBD DUQUE (05)    | R$ 109.243,20  |    8 |        6 |       6 |
| EBD TAQUARA (13)  | R$ 12.573,97   |    8 |        6 |       6 |
| EBD BOA VISTA (08)| R$ 6.641,87    |   24 |        4 |       4 |
| EBD SÃO GONÇALO (10)| R$ 5.392,80  |    1 |        1 |       1 |
| EBD MANAUS (06)   | R$ 3.598,93    |   12 |        3 |       3 |
| EBD SANTAREM (11) | R$ 2.129,87    |   10 |        2 |       2 |
| EBD MACAPA (07)   | R$ 266,85      |    3 |        3 |       3 |
| EBD SBC (18)      | R$ 71,28       |    2 |        1 |       1 |

## Próximos passos sugeridos

- Detalhar SKUs em ruptura no DUQUE (concentração crítica)
- Investigar portfólio pulverizado de Boa Vista
- Monitorar evolução ao longo do dia (ruptura é métrica diária em andamento)
"""

    artifact_id, fp, fn, sz = build_pdf(
        title="Ruptura por Filial — 16/06/2026",
        markdown_body=sample_md,
        subtitle="Visão BR · hoje 16/06/2026",
        metadata={
            "source_label": "Ruptura de Pedidos · visão BR",
            "period": "hoje 16/06/2026",
            "scope": "8 filiais com ocorrência",
        },
    )
    print(f"OK PDF gerado")
    print(f"   id:       {artifact_id}")
    print(f"   path:     {fp}")
    print(f"   filename: {fn}")
    print(f"   size:     {sz} bytes")
