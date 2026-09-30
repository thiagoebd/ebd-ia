"""Regenera o catalogo de templates a partir do query_templates.md.

POR QUE

O `templates.json` foi gerado em 20/07/2026 e tem 56 de 108 templates. Os 52
que faltam sao exatamente os que criamos depois — toda a familia T-LOG, T-GM,
T-CMP e T-PRC. O script que gerou o json original nao esta no repositorio.

Sem o catalogo completo nao da para tirar os SQL do prompt: o agente pediria
um template e receberia "nao encontrado".

COMO USAR

    python3 gera_catalogo.py --simular    # mostra o que mudaria
    python3 gera_catalogo.py              # reescreve (faz backup)

O json fica em core/app/data/templates.json, que e o que o get_template le.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
from datetime import datetime, timezone

RAIZ = os.environ.get("EBDIA_REPO", os.path.expanduser("~/projects/ebd-ia"))
MD = os.path.join(RAIZ, "docs", "query_templates.md")
JSON = os.path.join(RAIZ, "core", "app", "data", "templates.json")

# familia a partir do codigo e do titulo — o get_template filtra por ela
FAMILIAS = {
    "T-LOG": "logistica", "T-GM": "metas", "T-CMP": "compras",
    "T-PRC": "precificacao", "T-RES": "resumo", "T-PAINEL": "painel",
    "T-POTENCIAL": "potencial", "T-LOJA": "loja_ebd",
}
POR_PALAVRA = [
    ("faturamento", "faturamento"), ("fatura", "faturamento"),
    ("cliente", "clientes"), ("positiva", "clientes"),
    ("fornecedor", "fornecedores"), ("industria", "fornecedores"),
    ("estoque", "estoque"), ("ruptura", "estoque"), ("mix", "estoque"),
    ("pedido", "pedidos"), ("carteira", "pedidos"),
    ("meta", "metas"), ("comiss", "metas"), ("premio", "metas"),
    ("rca", "equipe_campo"), ("vendedor", "equipe_campo"),
    ("visita", "equipe_campo"), ("rota", "equipe_campo"),
    ("regional", "regionais"), ("filial", "regionais"),
    ("inadimpl", "inadimplencia"), ("titulo", "inadimplencia"),
    ("carga", "logistica"), ("separac", "logistica"), ("wms", "logistica"),
    ("preco", "precificacao"), ("custo", "precificacao"),
]


def familia(code: str, titulo: str) -> str:
    for pref, fam in FAMILIAS.items():
        if code.startswith(pref):
            return fam
    t = titulo.lower()
    for palavra, fam in POR_PALAVRA:
        if palavra in t:
            return fam
    return "outros"


def extrai(md: str) -> list[dict]:
    """Cada bloco '## TXXX — titulo' vira uma entrada."""
    partes = re.split(r"^(#{1,3})\s+(T-?[A-Z]*\d+[\w-]*)\s*[—\-–]?\s*(.*)$",
                      md, flags=re.M)
    saida, vistos = [], set()
    for i in range(1, len(partes) - 3, 4):
        code, titulo, corpo = partes[i + 1].strip(), partes[i + 2].strip(), partes[i + 3]
        if code in vistos:          # T182 aparece como ## e ###
            continue
        vistos.add(code)

        sqls = re.findall(r"```sql\n(.*?)```", corpo, re.S)
        if not sqls:
            continue                # sem SQL nao serve ao get_template
        sql = max(sqls, key=len).strip()

        # alguns blocos nao sao query executavel:
        #   "-- Identica ao T101 com X"     -> remissao
        #   "-- ... (ver bloco acima) ..."  -> placeholder
        # devolver isso ao agente e pior que nao devolver nada: ele acha
        # que tem o SQL e nao tem
        sem_select = not re.search(r"\b(SELECT|WITH)\b", sql, re.I)
        so_comentario = all(l.strip().startswith("--") or not l.strip()
                            for l in sql.splitlines())
        placeholder = "ver bloco acima" in sql or "(...)" in sql
        remissao = None
        m_rem = re.search(r"[Ii]d[êe]ntic[ao]\s+a[o]?\s+(T-?[A-Z]*\d+\w*)", sql)
        if m_rem:
            remissao = m_rem.group(1)
        incompleto = sem_select or so_comentario or placeholder

        # binds :algumaCoisa
        binds = sorted({b for b in re.findall(r":([a-zA-Z_][a-zA-Z0-9_]*)", sql)
                        if b.lower() not in ("chaves",)})

        validado = bool(re.search(r"✅|validad|confer[ei]|bate no centavo",
                                  corpo[:600], re.I))
        nota = ""
        m = re.search(r"(?:✅|VALIDADO[: ]|Validado[: ])(.{10,180})", corpo)
        if m:
            nota = re.sub(r"\s+", " ", m.group(1)).strip(" .—-")

        lat = ""
        m2 = re.search(r"(\d+[.,]?\d*)\s*(s|seg|ms)\b[^\n]{0,40}", corpo[:900])
        if m2:
            lat = m2.group(0).strip()[:60]

        titulo_limpo = re.sub(r"[✅⚠️★]", "", titulo).strip()
        saida.append({
            "incompleto": incompleto,
            "remissao": remissao,
            "code": code,
            "version": None,
            "title": titulo_limpo or code,
            "familia": familia(code, titulo_limpo),
            "validated": validado,
            "validation_note": nota,
            "latency_note": lat,
            "binds": binds,
            "sql": sql,
        })
    return saida


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--simular", action="store_true")
    a = ap.parse_args()

    md = open(MD, encoding="utf-8").read()
    novos = extrai(md)

    antigos = []
    if os.path.exists(JSON):
        try:
            antigos = json.load(open(JSON, encoding="utf-8"))["templates"]
        except Exception:
            pass
    antes = {t["code"] for t in antigos}
    depois = {t["code"] for t in novos}

    print(f"  no catalogo antigo : {len(antes)}")
    print(f"  extraidos do md    : {len(depois)}")
    print(f"  ENTRAM             : {len(depois - antes)}")
    if depois - antes:
        print(f"    {', '.join(sorted(depois - antes)[:14])}"
              + (" ..." if len(depois - antes) > 14 else ""))
    if antes - depois:
        print(f"  SAEM (sem SQL no md): {', '.join(sorted(antes - depois)[:10])}")

    por_fam: dict[str, int] = {}
    for t in novos:
        por_fam[t["familia"]] = por_fam.get(t["familia"], 0) + 1
    print("\n  por familia:")
    for f, n in sorted(por_fam.items(), key=lambda x: -x[1]):
        print(f"    {f:<16} {n:>3}")

    incompletos = [t for t in novos if t.get("incompleto")]
    if incompletos:
        print(f"\n  ⚠️  {len(incompletos)} sem SQL executavel "
              f"(remissao ou placeholder no markdown):")
        for t in incompletos:
            alvo = f" -> ver {t['remissao']}" if t.get("remissao") else ""
            print(f"    {t['code']:<10} {t['title'][:44]}{alvo}")
        print("    O get_template avisa o agente em vez de devolver lixo.")

    validados = sum(1 for t in novos if t["validated"])
    com_bind = sum(1 for t in novos if t["binds"])
    print(f"\n  validados: {validados}  ·  com binds: {com_bind}")
    print(f"  bytes de SQL no catalogo: {sum(len(t['sql']) for t in novos):,}"
          .replace(",", "."))

    if a.simular:
        print("\n  (simulacao — nada foi escrito)")
        return 0

    doc = {
        "count": len(novos),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": "docs/query_templates.md",
        "source_sha256": hashlib.sha256(md.encode()).hexdigest(),
        "templates": sorted(novos, key=lambda t: t["code"]),
    }
    os.makedirs(os.path.dirname(JSON), exist_ok=True)
    if os.path.exists(JSON):
        shutil.copy2(JSON, f"{JSON}.bak-{datetime.now():%Y%m%d-%H%M%S}")
    with open(JSON, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)
    print(f"\n  gravado: {JSON} ({os.path.getsize(JSON):,} bytes)"
          .replace(",", "."))
    print("  DEPOIS: reiniciar o gateway para recarregar o catalogo.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
