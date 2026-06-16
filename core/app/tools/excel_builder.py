"""Gerador de XLSX com identidade visual EBD.

Saída: arquivo .xlsx em /var/ebd-ia/artifacts/<uuid>.xlsx
Recursos:
  - Cabeçalho com logo EBD (azul-marinho #1c2c5e, texto branco)
  - Subtítulo em cinza
  - Tabela nativa Excel (autofilter, sort, header colorido, zebra)
  - Tipos: text, money (R$ 1.234,56), int, percent (33,0%), date
  - Formatação condicional por regra (highlights)
  - Aba "Metadados" com data, usuário, origem (sem expor SQL/view)

Uso (standalone test):
  python3 -m app.tools.excel_builder
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import xlsxwriter

from app.artifacts import (
    ARTIFACTS_DIR,
    LOGO_PATH,
    EBD_NAVY,
    EBD_RED,
    EBD_GRAY_LINE,
    EBD_FONT_SANS,
    safe_filename,
    new_artifact_path,
    now_br_str,
)

# Cores da formatação condicional (claras pra não ofuscar texto)
HL_RED_BG = "#FCE4E4"
HL_RED_FG = "#9B1C1C"
HL_GREEN_BG = "#E6F4EA"
HL_GREEN_FG = "#1E6B3A"
HL_AMBER_BG = "#FFF4DC"
HL_AMBER_FG = "#8A5A00"

ROW_HEADER_H = 36
ROW_DATA_H = 22
COL_W_TEXT = 28
COL_W_MONEY = 18
COL_W_INT = 12
COL_W_PCT = 11


def _format_for(wb: xlsxwriter.Workbook, col_type: str, base: dict | None = None) -> Any:
    base = base or {}
    if col_type == "money":
        return wb.add_format({"num_format": 'R$ #,##0.00;[Red]-R$ #,##0.00', **base})
    if col_type == "int":
        return wb.add_format({"num_format": "#,##0", **base})
    if col_type == "percent":
        return wb.add_format({"num_format": '0.0"%"', **base})
    if col_type == "date":
        return wb.add_format({"num_format": "dd/mm/yyyy", **base})
    return wb.add_format(base)


def _apply_highlights(ws, wb, columns, rows, highlights, data_start_row):
    palette = {
        "red":   wb.add_format({"bg_color": HL_RED_BG, "font_color": HL_RED_FG, "bold": True}),
        "green": wb.add_format({"bg_color": HL_GREEN_BG, "font_color": HL_GREEN_FG, "bold": True}),
        "amber": wb.add_format({"bg_color": HL_AMBER_BG, "font_color": HL_AMBER_FG, "bold": True}),
    }
    col_idx = {c["key"]: i for i, c in enumerate(columns)}
    for hl in highlights:
        key = hl.get("column")
        if key not in col_idx:
            continue
        rule = hl.get("rule")
        value = hl.get("value", 0)
        color = hl.get("color", "amber")
        fmt = palette.get(color, palette["amber"])
        c = col_idx[key]
        first_row = data_start_row
        last_row = data_start_row + len(rows) - 1
        if rule == "below":
            ws.conditional_format(first_row, c, last_row, c, {
                "type": "cell", "criteria": "<", "value": value, "format": fmt,
            })
        elif rule == "above":
            ws.conditional_format(first_row, c, last_row, c, {
                "type": "cell", "criteria": ">", "value": value, "format": fmt,
            })


def build_excel(
    title: str,
    sheets: list[dict],
    subtitle: str | None = None,
    metadata: dict | None = None,
) -> tuple[str, Path, str, int]:
    """Gera XLSX com identidade EBD.

    Retorna (artifact_id, file_path, filename_seguro, size_bytes).
    """
    artifact_id, file_path = new_artifact_path("xlsx")
    filename = safe_filename(title, "xlsx")

    wb = xlsxwriter.Workbook(str(file_path), {"in_memory": True})

    fmt_header_banner = wb.add_format({
        "bg_color": EBD_NAVY, "font_color": "white", "bold": True,
        "font_size": 16, "font_name": EBD_FONT_SANS,
        "align": "left", "valign": "vcenter",
    })
    fmt_subtitle = wb.add_format({
        "font_color": "#555555", "italic": True,
        "font_size": 11, "font_name": EBD_FONT_SANS,
        "align": "left", "valign": "vcenter",
    })
    fmt_date_right = wb.add_format({
        "font_color": "white", "bold": True,
        "font_size": 11, "font_name": EBD_FONT_SANS,
        "bg_color": EBD_NAVY,
        "align": "right", "valign": "vcenter",
    })

    for sheet_idx, sheet in enumerate(sheets):
        ws = wb.add_worksheet(sheet.get("name", f"Aba {sheet_idx+1}")[:31])
        columns = sheet["columns"]
        rows = sheet.get("rows", [])
        highlights = sheet.get("highlights", [])
        n_cols = len(columns)

        ws.set_row(0, ROW_HEADER_H)
        if LOGO_PATH.exists():
            ws.insert_image(0, 0, str(LOGO_PATH), {
                "x_scale": 0.06, "y_scale": 0.06,
                "x_offset": 4, "y_offset": 5,
                "object_position": 1,
            })
        ws.merge_range(0, 1, 0, max(1, n_cols - 2), title, fmt_header_banner)
        ws.write(0, n_cols - 1, now_br_str(), fmt_date_right)

        if subtitle:
            ws.set_row(1, 18)
            ws.merge_range(1, 0, 1, n_cols - 1, subtitle, fmt_subtitle)

        ws.set_row(2, 6)

        data_start_row = 4
        table_first_row = 3
        table_last_row = data_start_row + len(rows) - 1

        for i, c in enumerate(columns):
            t = c.get("type", "text")
            w = {"text": COL_W_TEXT, "money": COL_W_MONEY,
                 "int": COL_W_INT, "percent": COL_W_PCT, "date": COL_W_INT}.get(t, COL_W_TEXT)
            ws.set_column(i, i, w, _format_for(wb, t))

        table_data = []
        for row in rows:
            table_data.append([row.get(c["key"], "") for c in columns])

        if rows:
            ws.add_table(table_first_row, 0, table_last_row, n_cols - 1, {
                "name": f"Tab_{sheet_idx+1}",
                "style": "Table Style Medium 2",
                "columns": [{"header": c["label"]} for c in columns],
                "data": table_data,
            })
            _apply_highlights(ws, wb, columns, rows, highlights, data_start_row)
        else:
            ws.write_row(table_first_row, 0, [c["label"] for c in columns],
                         wb.add_format({"bold": True, "bg_color": EBD_NAVY, "font_color": "white"}))

        ws.freeze_panes(data_start_row, 0)
        ws.hide_gridlines(2)

    meta_ws = wb.add_worksheet("Metadados")
    meta_ws.set_column(0, 0, 22)
    meta_ws.set_column(1, 1, 60)
    fmt_meta_k = wb.add_format({"bold": True, "font_color": EBD_NAVY, "font_name": EBD_FONT_SANS})
    fmt_meta_v = wb.add_format({"font_name": EBD_FONT_SANS})
    meta = metadata or {}
    rows_meta = [
        ("Documento", title),
        ("Subtítulo", subtitle or ""),
        ("Gerado em", now_br_str()),
        ("Origem", meta.get("source_label", "EBD.ia · dados do Winthor")),
        ("Período", meta.get("period", "")),
        ("Escopo", meta.get("scope", "")),
        ("Usuário", meta.get("user_name", "")),
        ("Conversa", meta.get("conversation_id", "")),
    ]
    for i, (k, v) in enumerate(rows_meta):
        meta_ws.write(i, 0, k, fmt_meta_k)
        meta_ws.write(i, 1, str(v) if v else "—", fmt_meta_v)
    meta_ws.hide_gridlines(2)

    wb.close()
    size_bytes = file_path.stat().st_size
    return artifact_id, file_path, filename, size_bytes


if __name__ == "__main__":
    sample = {
        "title": "Top 10 Filiais — Faturamento Líquido MTD",
        "subtitle": "Visão BR · MTD jun/2026",
        "sheets": [{
            "name": "Top 10 Filiais",
            "columns": [
                {"key": "rank", "label": "#", "type": "int"},
                {"key": "filial", "label": "Filial", "type": "text"},
                {"key": "liquido", "label": "Real Líquido", "type": "money"},
                {"key": "meta", "label": "Meta", "type": "money"},
                {"key": "pct_meta", "label": "% Meta", "type": "percent"},
            ],
            "rows": [
                {"rank": 1, "filial": "EBD DUQUE (05)",      "liquido": 15401916, "meta": 46685128, "pct_meta": 33.0},
                {"rank": 2, "filial": "EBD TAQUARA (13)",    "liquido": 12488862, "meta": 36471136, "pct_meta": 34.2},
                {"rank": 3, "filial": "EBD SAO GONCALO (10)","liquido": 9683742,  "meta": 26739524, "pct_meta": 36.2},
                {"rank": 4, "filial": "EBDN CARUARU (53)",   "liquido": 6672579,  "meta": 23667340, "pct_meta": 28.2},
                {"rank": 5, "filial": "EBD MANAUS (06)",     "liquido": 6608419,  "meta": 18500000, "pct_meta": 35.7},
                {"rank": 6, "filial": "EBD PIRAI (14)",      "liquido": 5941204,  "meta": 20846980, "pct_meta": 28.5},
                {"rank": 7, "filial": "EBD SP (02)",         "liquido": 5475890,  "meta": 11583343, "pct_meta": 47.3},
                {"rank": 8, "filial": "EBD SAO LUIS (04)",   "liquido": 5333465,  "meta": 15039465, "pct_meta": 35.5},
                {"rank": 9, "filial": "EBD SBC (18)",        "liquido": 4168509,  "meta": 16020045, "pct_meta": 26.0},
                {"rank": 10,"filial": "EBD MATRIZ (01)",     "liquido": 4158712,  "meta": 31167784, "pct_meta": 13.3},
            ],
            "highlights": [
                {"column": "pct_meta", "rule": "below", "value": 30, "color": "red"},
                {"column": "pct_meta", "rule": "above", "value": 45, "color": "green"},
            ],
        }],
    }
    meta = {
        "source_label": "Faturamento Liquido EBD - visao BR",
        "period": "MTD jun/2026",
        "scope": "21 filiais consolidadas",
        "user_name": "Thiago Parreira",
        "conversation_id": "demo-standalone",
    }
    art_id, path, fname, size = build_excel(
        title=sample["title"],
        subtitle=sample["subtitle"],
        sheets=sample["sheets"],
        metadata=meta,
    )
    print(f"OK XLSX gerado")
    print(f"   id:       {art_id}")
    print(f"   path:     {path}")
    print(f"   filename: {fname}")
    print(f"   size:     {size} bytes")
