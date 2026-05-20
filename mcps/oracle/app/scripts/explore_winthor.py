"""
explore_winthor.py v2 — Descoberta progressiva COMPLETA do schema Winthor.

v2 (2026-05-19):
- Extrai TODAS as views (limite 250, cobre as 197 relevantes)
- Corrige bug PCCLIENT.RAMOATV → CODATV1 com JOIN em PCATIVI
- Pula PCNFSAIDI (sem acesso confirmado)
- Adiciona Bloco E: tabelas referenciadas pelas views dimensionais
- Performance: batch de 50 views por loop, retry em LOB errors

Uso (host):
    cd ~/projects/ebd-ia
    python3 -m mcps.oracle.app.scripts.explore_winthor
"""

import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path

# ============================================================
# Setup
# ============================================================

def _setup_environment() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        env_file = parent / ".env"
        if env_file.exists():
            try:
                from dotenv import load_dotenv
                load_dotenv(env_file)
                print(f"[setup] .env carregado de: {env_file}")
                return parent
            except ImportError:
                print("[setup] python-dotenv não disponível")
                return parent
    print("[setup] Sem .env encontrado, usando env vars do ambiente")
    return here.parent.parent.parent.parent

PROJECT_ROOT = _setup_environment()

try:
    from app.pool import get_pool, close_pool, get_config
except ImportError:
    sys.path.insert(0, str(PROJECT_ROOT))
    from mcps.oracle.app.pool import get_pool, close_pool, get_config


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("explore")


# ============================================================
# Configuração
# ============================================================

SAMPLE_FILIAL = "01"  # EBD MATRIZ

# Tabelas transacionais (PCNFSAIDI já sabemos que está inacessível)
TRANSACTIONAL_TABLES = [
    "PCNFSAID",
    "PCPEDC", "PCPEDI",
    "PCEST",
    "PCPRODUT",
    "PCCLIENT",
    "PCMOV",
]

# Tabelas dimensão pequenas (Bloco A)
SMALL_TABLES = [
    "PCFILIAL",
    "PCFORNEC",
    "PCEMPR",
    "PCUSUARI",
]

# Tabelas referenciadas pelas views (Bloco E novo)
SUPPORTING_TABLES = [
    "PCATIVI",       # ramo de atividade
    "PCSUPERV",      # supervisor
    "PCGERENTE",     # gerente
    "PCREDECLIENTE", # rede de clientes
    "PCPRACA",       # praça
    "PCROTA",        # rota
    "PCREGIAO",      # região (geográfica)
    "PCCIDADE",      # cidades
    "PCCATEGORIA",   # categoria produto
    "PCSUBCATEGORIA",# subcategoria
    "PCSECAO",       # seção
    "PCDEPTO",       # departamento
    "PCMARCA",       # marca
    "PCLINHAPROD",   # linha de produto (LAMEN, NUTELLA etc)
    "PCDISTRIB",     # distribuição
    "PCCONSUM",      # parâmetros do sistema (NUMDIASCLIINATIV!)
]

# Filtros de nome de view relevantes (Bloco C)
VIEW_KEYWORDS = [
    "FAT", "META", "VEND", "INADIM", "EST", "PED",
    "COB", "CRED", "NF", "MOV", "RCA", "CLIENTE", "PROD",
    "DRE", "DIM", "FATO", "ORC",  # adicionados pra capturar mais
]

MAX_VIEWS_WITH_SQL = 250  # cobre as 197 relevantes
OUTPUT_FILE = PROJECT_ROOT / "docs" / "winthor_discovery.md"


# ============================================================
# Helpers
# ============================================================

class MarkdownWriter:
    def __init__(self):
        self.sections = []

    def add(self, text: str):
        self.sections.append(text)

    def write_to_file(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(self.sections), encoding="utf-8")
        size = sum(len(s) for s in self.sections)
        logger.info("Markdown salvo em: %s (%d caracteres, %d seções)",
                    path, size, len(self.sections))


def run_query(conn, sql: str, description: str = ""):
    """Executa query, retorna (columns, rows, elapsed_ms, error)."""
    start = time.perf_counter()
    try:
        with conn.cursor() as cur:
            cur.execute(sql)
            cols = [d[0] for d in cur.description] if cur.description else []
            rows = cur.fetchall()
        elapsed_ms = (time.perf_counter() - start) * 1000
        if description:
            logger.info("✓ %s — %d linhas em %.0fms", description, len(rows), elapsed_ms)
        return cols, rows, elapsed_ms, None
    except Exception as e:
        elapsed_ms = (time.perf_counter() - start) * 1000
        logger.error("✗ %s falhou após %.0fms: %s", description, elapsed_ms, e)
        return [], [], elapsed_ms, str(e)


def rows_to_md_table(columns: list[str], rows: list[tuple], max_rows: int = 50) -> str:
    if not rows:
        return "_(sem resultados)_"
    header = "| " + " | ".join(columns) + " |"
    sep = "|" + "|".join("---" for _ in columns) + "|"
    truncated = rows[:max_rows]
    body_lines = []
    for row in truncated:
        cells = []
        for c in row:
            if c is None:
                cells.append("_NULL_")
            else:
                s = str(c).replace("|", "\\|").replace("\n", " ")
                if len(s) > 80:
                    s = s[:77] + "..."
                cells.append(s)
        body_lines.append("| " + " | ".join(cells) + " |")
    table = "\n".join([header, sep] + body_lines)
    if len(rows) > max_rows:
        table += f"\n\n_({len(rows)} linhas no total, exibindo {max_rows})_"
    return table


def describe_table(conn, md: MarkdownWriter, table_name: str,
                   include_sample: bool = True,
                   sample_filter: str = None,
                   sample_size: int = 3):
    """Descreve uma tabela: schema + sample opcional."""
    cols, rows, _, err = run_query(
        conn,
        f"""
        SELECT COLUMN_NAME, DATA_TYPE, DATA_LENGTH, NULLABLE
        FROM ALL_TAB_COLUMNS
        WHERE OWNER = 'EBD' AND TABLE_NAME = '{table_name}'
        ORDER BY COLUMN_ID
        """,
        f"{table_name} — colunas"
    )
    if err:
        md.add(f"**Erro:** `{err}`\n")
        return
    if not rows:
        md.add(f"_Tabela {table_name} não existe ou EBD_LEITURA não tem acesso._\n")
        return
    md.add(f"**Colunas ({len(rows)}):**\n\n{rows_to_md_table(cols, rows, max_rows=300)}\n")

    if include_sample:
        where_clause = f"WHERE {sample_filter}" if sample_filter else ""
        cols, rows, elapsed, err = run_query(
            conn,
            f"SELECT * FROM EBD.{table_name} {where_clause} FETCH FIRST {sample_size} ROWS ONLY",
            f"{table_name} — sample"
        )
        if not err and rows:
            md.add(f"\n**Sample {len(rows)} linhas ({elapsed:.0f}ms):**\n\n{rows_to_md_table(cols, rows, max_rows=sample_size)}\n")


# ============================================================
# Bloco A — Dimensões pequenas
# ============================================================

def block_a_dimensions(conn, md: MarkdownWriter):
    logger.info("=" * 60)
    logger.info("BLOCO A — Dimensões pequenas (PCFILIAL, PCFORNEC, PCEMPR, PCUSUARI)")
    logger.info("=" * 60)
    md.add("\n## Bloco A — Dimensões mestre\n")

    # A.1 — PCFILIAL completo (TODAS as linhas)
    md.add("### A.1 — PCFILIAL (filiais — lista completa)\n")
    describe_table(conn, md, "PCFILIAL", include_sample=False)
    cols, rows, elapsed, err = run_query(
        conn,
        "SELECT CODIGO, RAZAOSOCIAL, CIDADE, UF, NUMREGIAO FROM EBD.PCFILIAL ORDER BY CODIGO",
        "PCFILIAL — todas as filiais (campos chave)"
    )
    if not err:
        md.add(f"\n**Filiais ativas (CODIGO + RAZAOSOCIAL + CIDADE + UF + NUMREGIAO):**\n\n{rows_to_md_table(cols, rows, max_rows=30)}\n")

    # A.2 — PCFORNEC
    md.add("\n### A.2 — PCFORNEC (fornecedores)\n")
    describe_table(conn, md, "PCFORNEC", include_sample=True, sample_size=10)
    _, count_rows, _, _ = run_query(conn, "SELECT COUNT(*) FROM EBD.PCFORNEC", "PCFORNEC — total")
    if count_rows:
        md.add(f"\n**Total:** {count_rows[0][0]} fornecedores cadastrados.\n")

    # A.3 — PCEMPR
    md.add("\n### A.3 — PCEMPR (funcionários)\n")
    describe_table(conn, md, "PCEMPR", include_sample=True, sample_size=5)
    _, count_rows, _, _ = run_query(conn, "SELECT COUNT(*) FROM EBD.PCEMPR", "PCEMPR — total")
    if count_rows:
        md.add(f"\n**Total:** {count_rows[0][0]} funcionários.\n")

    # A.4 — PCUSUARI (RCAs/vendedores)
    md.add("\n### A.4 — PCUSUARI (RCAs / Vendedores)\n")
    describe_table(conn, md, "PCUSUARI", include_sample=True, sample_size=5)
    _, count_rows, _, _ = run_query(conn, "SELECT COUNT(*) FROM EBD.PCUSUARI", "PCUSUARI — total")
    if count_rows:
        md.add(f"\n**Total:** {count_rows[0][0]} usuários.\n")
    _, ativ_rows, _, _ = run_query(
        conn,
        "SELECT COUNT(*) FROM EBD.PCUSUARI WHERE DTTERMINO IS NULL",
        "PCUSUARI — ativos"
    )
    if ativ_rows:
        md.add(f"**Ativos (DTTERMINO IS NULL):** {ativ_rows[0][0]}\n")


# ============================================================
# Bloco B — Tabelas transacionais (sem PCNFSAIDI)
# ============================================================

def block_b_transactional(conn, md: MarkdownWriter):
    logger.info("=" * 60)
    logger.info("BLOCO B — Tabelas transacionais (filial amostra: %s)", SAMPLE_FILIAL)
    logger.info("=" * 60)
    md.add(f"\n## Bloco B — Tabelas transacionais (filial amostra: {SAMPLE_FILIAL})\n")
    md.add("\n> **Nota:** `PCNFSAIDI` foi removida pois EBD_LEITURA não tem acesso.\n")

    for tabela in TRANSACTIONAL_TABLES:
        md.add(f"\n### B — {tabela}\n")
        # Tabelas com CODFILIAL
        has_filial_filter = tabela in ["PCNFSAID", "PCPEDC", "PCPEDI", "PCEST", "PCMOV"]
        if has_filial_filter:
            describe_table(conn, md, tabela, include_sample=True,
                          sample_filter=f"CODFILIAL = '{SAMPLE_FILIAL}'",
                          sample_size=3)
        else:
            describe_table(conn, md, tabela, include_sample=True, sample_size=3)


# ============================================================
# Bloco C — Views Oracle (TODAS as relevantes)
# ============================================================

def block_c_views(conn, md: MarkdownWriter):
    logger.info("=" * 60)
    logger.info("BLOCO C — Views Oracle (extração completa)")
    logger.info("=" * 60)
    md.add("\n## Bloco C — Views Oracle (regras de negócio embutidas)\n")

    # C.1 — Lista de TODAS as views EBD
    cols, all_views, _, err = run_query(
        conn,
        "SELECT VIEW_NAME FROM ALL_VIEWS WHERE OWNER = 'EBD' ORDER BY VIEW_NAME",
        "ALL_VIEWS WHERE OWNER='EBD'"
    )
    if err:
        md.add(f"**Erro:** `{err}`\n")
        return

    view_names = [r[0] for r in all_views]
    md.add(f"\n### C.1 — Inventário total\n")
    md.add(f"**Total de views visíveis ao EBD_LEITURA:** {len(view_names)}\n")

    # C.2 — Filtrar relevantes
    relevant = []
    for name in view_names:
        upper = name.upper()
        if upper.startswith("V"):
            relevant.append(name)
            continue
        if any(kw in upper for kw in VIEW_KEYWORDS):
            relevant.append(name)

    md.add(f"\n### C.2 — Views relevantes\n")
    md.add(f"**Filtros:** começa com V, OU contém qualquer de: {VIEW_KEYWORDS}\n")
    md.add(f"**Total relevantes:** {len(relevant)}\n")

    md.add(f"\n**Lista completa de views EBD (todas):**\n\n")
    md.add("```\n" + "\n".join(view_names) + "\n```\n")

    # C.3 — Extrair SQL de TODAS as relevantes (até MAX_VIEWS_WITH_SQL)
    target_count = min(len(relevant), MAX_VIEWS_WITH_SQL)
    md.add(f"\n### C.3 — SQL das views relevantes ({target_count} de {len(relevant)})\n")
    logger.info("Extraindo SQL de %d views (limite: %d)", target_count, MAX_VIEWS_WITH_SQL)

    extracted = 0
    errors = 0
    start_total = time.perf_counter()

    for i, view_name in enumerate(relevant[:MAX_VIEWS_WITH_SQL], 1):
        try:
            with conn.cursor() as cur:
                cur.execute(f"""
                    SELECT TEXT FROM ALL_VIEWS
                    WHERE OWNER = 'EBD' AND VIEW_NAME = '{view_name}'
                """)
                row = cur.fetchone()
            if row and row[0]:
                sql_text = str(row[0]).strip()
                md.add(f"\n#### {view_name}\n\n```sql\n{sql_text}\n```\n")
                extracted += 1
                if i % 25 == 0:
                    elapsed = time.perf_counter() - start_total
                    logger.info("  Progresso: %d/%d views (%.1fs)", i, target_count, elapsed)
            else:
                md.add(f"\n#### {view_name}\n_(SQL vazio ou inacessível)_\n")
        except Exception as e:
            md.add(f"\n#### {view_name}\n_(Erro: {e})_\n")
            errors += 1
            logger.warning("  ✗ Falha em %s: %s", view_name, e)

    total_elapsed = time.perf_counter() - start_total
    md.add(f"\n_Resumo: {extracted} views extraídas, {errors} erros, em {total_elapsed:.1f}s._\n")
    logger.info("Views: %d extraídas, %d erros, em %.1fs", extracted, errors, total_elapsed)


# ============================================================
# Bloco D — Constantes (CORRIGIDO: CODATV1 + JOIN PCATIVI)
# ============================================================

def block_d_constants(conn, md: MarkdownWriter):
    logger.info("=" * 60)
    logger.info("BLOCO D — Constantes/enums do negócio")
    logger.info("=" * 60)
    md.add("\n## Bloco D — Constantes e enums\n")

    queries = [
        ("PCNFSAID.CONDVENDA (últimos 30 dias filial 01)", f"""
            SELECT DISTINCT CONDVENDA, COUNT(*) AS QTD
            FROM EBD.PCNFSAID
            WHERE CODFILIAL = '{SAMPLE_FILIAL}'
              AND DTSAIDA >= TRUNC(SYSDATE) - 30
            GROUP BY CONDVENDA
            ORDER BY QTD DESC
        """),
        ("PCNFSAID.TIPOVENDA (últimos 30 dias filial 01)", f"""
            SELECT DISTINCT TIPOVENDA, COUNT(*) AS QTD
            FROM EBD.PCNFSAID
            WHERE CODFILIAL = '{SAMPLE_FILIAL}'
              AND DTSAIDA >= TRUNC(SYSDATE) - 30
            GROUP BY TIPOVENDA
            ORDER BY QTD DESC
        """),
        ("PCPEDC.POSICAO (últimos 30 dias filial 01)", f"""
            SELECT DISTINCT POSICAO, COUNT(*) AS QTD
            FROM EBD.PCPEDC
            WHERE CODFILIAL = '{SAMPLE_FILIAL}'
              AND DATA >= TRUNC(SYSDATE) - 30
            GROUP BY POSICAO
            ORDER BY QTD DESC
        """),
        # CORRIGIDO: agora vai em CODATV1 com JOIN em PCATIVI
        ("PCCLIENT.CODATV1 + PCATIVI.RAMO (top 20)", """
            SELECT ATI.CODATIV, ATI.RAMO, COUNT(*) AS QTD_CLIENTES
            FROM EBD.PCCLIENT C
            LEFT JOIN EBD.PCATIVI ATI ON ATI.CODATIV = C.CODATV1
            WHERE C.DTEXCLUSAO IS NULL
            GROUP BY ATI.CODATIV, ATI.RAMO
            ORDER BY QTD_CLIENTES DESC
            FETCH FIRST 20 ROWS ONLY
        """),
        ("PCCLIENT — total cadastrado + ativo", """
            SELECT
                COUNT(*) AS TOTAL_CADASTRADO,
                COUNT(CASE WHEN DTEXCLUSAO IS NULL THEN 1 END) AS NAO_EXCLUIDO,
                COUNT(CASE WHEN DTULTCOMP >= SYSDATE - 90 THEN 1 END) AS COMPROU_90D
            FROM EBD.PCCLIENT
        """),
        ("PCCONSUM — parâmetros do sistema (NUMDIASCLIINATIV)", """
            SELECT NUMDIASCLIINATIV
            FROM EBD.PCCONSUM
        """),
        ("PCUSUARI.TIPOVEND (tipos de vendedor)", """
            SELECT TIPOVEND, COUNT(*) AS QTD
            FROM EBD.PCUSUARI
            WHERE DTTERMINO IS NULL
            GROUP BY TIPOVEND
            ORDER BY QTD DESC
        """),
        ("PCCLIENT.CLASSEVENDA (curva)", """
            SELECT CLASSEVENDA, COUNT(*) AS QTD
            FROM EBD.PCCLIENT
            WHERE DTEXCLUSAO IS NULL
            GROUP BY CLASSEVENDA
            ORDER BY QTD DESC
        """),
        ("PCCLIENT.VIP", """
            SELECT VIP, COUNT(*) AS QTD
            FROM EBD.PCCLIENT
            WHERE DTEXCLUSAO IS NULL
            GROUP BY VIP
            ORDER BY QTD DESC
        """),
    ]

    for label, sql in queries:
        md.add(f"\n### D — {label}\n")
        cols, rows, elapsed, err = run_query(conn, sql, label)
        if err:
            md.add(f"**Erro:** `{err}`\n")
        elif not rows:
            md.add("_(sem dados)_\n")
        else:
            md.add(f"**{len(rows)} valores ({elapsed:.0f}ms):**\n\n{rows_to_md_table(cols, rows, max_rows=30)}\n")


# ============================================================
# Bloco E — Tabelas de suporte (referenciadas pelas views)
# ============================================================

def block_e_supporting(conn, md: MarkdownWriter):
    logger.info("=" * 60)
    logger.info("BLOCO E — Tabelas de suporte (joins das views dimensionais)")
    logger.info("=" * 60)
    md.add("\n## Bloco E — Tabelas de suporte (referenciadas pelas views dimensionais)\n")
    md.add("\n> Descobertas analisando os JOINs das views `GD_DIM_*`. Cada uma agrega\n> dimensão extra ao modelo dimensional.\n")

    for tabela in SUPPORTING_TABLES:
        md.add(f"\n### E — {tabela}\n")
        describe_table(conn, md, tabela, include_sample=True, sample_size=5)
        # Total
        _, count_rows, _, _ = run_query(
            conn,
            f"SELECT COUNT(*) FROM EBD.{tabela}",
            f"{tabela} — total"
        )
        if count_rows:
            md.add(f"\n**Total:** {count_rows[0][0]} linhas.\n")


# ============================================================
# Main
# ============================================================

def main() -> int:
    print("=" * 70)
    print("Winthor Schema Discovery v2 — EBD.ia")
    print(f"Timestamp: {datetime.now().isoformat()}")
    print(f"Filial amostra: {SAMPLE_FILIAL}")
    print(f"Output: {OUTPUT_FILE}")
    print(f"MAX_VIEWS_WITH_SQL: {MAX_VIEWS_WITH_SQL}")
    print("=" * 70)

    md = MarkdownWriter()
    md.add(f"# Winthor Discovery v2 — Schema Completo do Oracle Winthor (EBD)\n")
    md.add(f"> **Gerado por:** `mcps/oracle/app/scripts/explore_winthor.py` v2")
    md.add(f">")
    md.add(f"> **Data:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    md.add(f">")
    md.add(f"> **Filial amostra:** `{SAMPLE_FILIAL}` (EBD MATRIZ)")
    md.add(f">")
    md.add(f"> **Usuário Oracle:** `EBD_LEITURA` (teste)")
    md.add(f">")
    md.add(f"> **Mudanças vs v1:**")
    md.add(f"> - Extrai até {MAX_VIEWS_WITH_SQL} views (era 50)")
    md.add(f"> - Corrige consulta de ramo de atividade (PCATIVI JOIN)")
    md.add(f"> - Pula PCNFSAIDI (sem acesso)")
    md.add(f"> - Adiciona Bloco E: tabelas de suporte das views\n")
    md.add("---")

    try:
        pool = get_pool()
        cfg = get_config()
        logger.info("Pool inicializado: %s", cfg.safe_repr())
    except Exception as e:
        logger.error("Falha ao inicializar pool: %s", e)
        return 1

    start_global = time.perf_counter()
    try:
        with pool.acquire() as conn:
            block_a_dimensions(conn, md)
            block_b_transactional(conn, md)
            block_c_views(conn, md)
            block_d_constants(conn, md)
            block_e_supporting(conn, md)
    finally:
        close_pool()

    md.write_to_file(OUTPUT_FILE)
    total_elapsed = time.perf_counter() - start_global
    print(f"\n✅ Concluído em {total_elapsed:.1f}s. Resultado: {OUTPUT_FILE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
