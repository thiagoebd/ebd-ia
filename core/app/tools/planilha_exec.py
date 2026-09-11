"""Executores das ferramentas de planilha — o que roda quando o agente chama.

CADEIA DE PLANILHAS

Cada cruzamento gera uma planilha NOVA, filha da anterior. Isso permite
encadear: busca o produto, depois o estoque, depois o giro — cada passo
partindo do resultado do anterior, sem refazer o de trás.

Para o Postgres não crescer sem controle, guardamos no máximo MAX_VERSOES
por conversa. A mais antiga sai (a original é preservada enquanto couber,
porque refazer o upload é o que mais incomoda o usuário).

O QUE O AGENTE RECEBE

Nunca as linhas. Sempre um resumo: quantas casaram, quantas não, e alguns
exemplos do que ficou de fora. Um cruzamento de 50.000 linhas devolve o
mesmo tamanho de resposta que um de 50.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from app.planilhas import (
    blocos, chaves_unicas, junta, lista_sql, normaliza_codigo, normaliza_texto,
)
from app.planilha_match import classifica, sql_por_nome, texto_para_o_usuario

logger = logging.getLogger("uvicorn.error")

MAX_VERSOES = 3           # por conversa
MAX_EXEMPLOS = 8


class PlanilhaNaoEncontrada(Exception):
    pass


# ─── acesso ao Postgres ────────────────────────────────────────────────

async def grava(pool, conversation_id: str, user_oid: str, nome_arquivo: str,
                planilha, origem_id: str | None = None) -> str:
    """Guarda a planilha e devolve o id. Poda as versões antigas."""
    async with pool.acquire() as con:
        row = await con.fetchrow(
            """INSERT INTO planilhas
                   (conversation_id, user_oid, nome_arquivo, aba,
                    total_linhas, colunas, linhas)
               VALUES ($1::uuid, $2, $3, $4, $5, $6::jsonb, $7::jsonb)
               RETURNING id""",
            conversation_id, user_oid, nome_arquivo, planilha.aba,
            planilha.total,
            json.dumps([{"nome": c.nome, "nome_original": c.nome_original,
                         "tipo": c.tipo, "preenchidas": c.preenchidas,
                         "exemplos": c.exemplos} for c in planilha.colunas],
                       ensure_ascii=False),
            json.dumps(planilha.linhas, ensure_ascii=False),
        )
        # poda: mantém as MAX_VERSOES mais recentes desta conversa
        await con.execute(
            """DELETE FROM planilhas
               WHERE conversation_id = $1::uuid
                 AND id NOT IN (SELECT id FROM planilhas
                                WHERE conversation_id = $1::uuid
                                ORDER BY created_at DESC LIMIT $2)""",
            conversation_id, MAX_VERSOES)
    return str(row["id"])


async def _carrega(pool, conversation_id: str, planilha_id: str | None) -> dict:
    """Busca a planilha; sem id, pega a mais recente da conversa."""
    async with pool.acquire() as con:
        if planilha_id:
            row = await con.fetchrow(
                "SELECT * FROM planilhas WHERE id = $1::uuid "
                "AND conversation_id = $2::uuid", planilha_id, conversation_id)
        else:
            row = await con.fetchrow(
                "SELECT * FROM planilhas WHERE conversation_id = $1::uuid "
                "ORDER BY created_at DESC LIMIT 1", conversation_id)
    if not row:
        raise PlanilhaNaoEncontrada(
            "Não achei planilha nesta conversa. O usuário anexou alguma?")
    d = dict(row)
    for campo in ("colunas", "linhas"):
        if isinstance(d[campo], str):
            d[campo] = json.loads(d[campo])
    return d


# ─── planilha_resumo ───────────────────────────────────────────────────

async def executa_resumo(pool, conversation_id: str,
                         planilha_id: str | None = None) -> dict:
    p = await _carrega(pool, conversation_id, planilha_id)
    return {
        "planilha_id": str(p["id"]),
        "arquivo": p["nome_arquivo"],
        "aba": p["aba"],
        "linhas": p["total_linhas"],
        "colunas": [
            {"nome": c["nome"], "tipo": c["tipo"],
             "preenchidas": c["preenchidas"], "exemplos": c["exemplos"][:3]}
            for c in p["colunas"]
        ],
    }


# ─── planilha_resolver ─────────────────────────────────────────────────

async def executa_resolver(pool, conversation_id: str, coluna: str,
                           entidade: str, roda_oracle,
                           planilha_id: str | None = None) -> dict:
    """Nomes -> códigos. `roda_oracle` é async e recebe o SQL."""
    p = await _carrega(pool, conversation_id, planilha_id)
    nomes_col = {c["nome"] for c in p["colunas"]}
    if coluna not in nomes_col:
        return {"erro": f"A planilha não tem a coluna '{coluna}'. "
                        f"Colunas: {', '.join(sorted(nomes_col))}"}

    nomes, vistos = [], set()
    for l in p["linhas"]:
        v = str(l.get(coluna, "")).strip()
        if v and v.upper() not in vistos:
            vistos.add(v.upper())
            nomes.append(v)
    if not nomes:
        return {"erro": f"A coluna '{coluna}' está vazia."}

    resolucao_total = None
    for lote in blocos(nomes, 200):       # o SQL por nome tem limite prático
        sql = sql_por_nome(entidade, lote)
        if not sql:
            continue
        linhas = await roda_oracle(sql)
        r = classifica(lote, linhas or [])
        if resolucao_total is None:
            resolucao_total = r
        else:
            resolucao_total.resolvido.update(r.resolvido)
            resolucao_total.ambiguo.update(r.ambiguo)
            resolucao_total.nao_achado.extend(r.nao_achado)

    if resolucao_total is None:
        return {"erro": "Nenhum nome válido para buscar."}

    saida = resolucao_total.resumo()
    saida["coluna"] = coluna
    saida["entidade"] = entidade
    saida["total_nomes"] = len(nomes)
    # o texto pronto para o agente repassar, com os três grupos
    saida["mensagem"] = texto_para_o_usuario(entidade, resolucao_total)
    return saida


# ─── planilha_cruzar ───────────────────────────────────────────────────

async def executa_cruzar(pool, conversation_id: str, user_oid: str,
                         coluna_planilha: str, sql: str, coluna_winthor: str,
                         roda_oracle, tipo_chave: str = "codigo",
                         planilha_id: str | None = None) -> dict:
    """Junta a planilha com o Winthor. Gera uma planilha NOVA."""
    p = await _carrega(pool, conversation_id, planilha_id)
    nomes_col = {c["nome"] for c in p["colunas"]}
    if coluna_planilha not in nomes_col:
        return {"erro": f"A planilha não tem a coluna '{coluna_planilha}'. "
                        f"Colunas: {', '.join(sorted(nomes_col))}"}
    if ":chaves" not in sql:
        return {"erro": "O SQL precisa do marcador :chaves dentro do IN (...). "
                        "Ex.: WHERE CODPROD IN (:chaves)"}

    chaves = chaves_unicas(p["linhas"], coluna_planilha, tipo_chave)
    if not chaves:
        return {"erro": f"A coluna '{coluna_planilha}' não tem valores úteis."}

    numerico = tipo_chave == "codigo" and all(c.isdigit() for c in chaves)
    achados: dict[str, dict] = {}
    colunas_novas: list[str] = []
    erros: list[str] = []

    for i, lote in enumerate(blocos(chaves)):
        sql_lote = sql.replace(":chaves", lista_sql(lote, numerico))
        try:
            linhas = await roda_oracle(sql_lote)
        except Exception as e:
            erros.append(f"bloco {i + 1}: {type(e).__name__}: {str(e)[:120]}")
            continue
        for l in (linhas or []):
            if coluna_winthor not in l:
                return {"erro": f"O resultado do Winthor não tem a coluna "
                                f"'{coluna_winthor}'. Voltou: "
                                f"{', '.join(list(l.keys())[:8])}"}
            norm = normaliza_codigo if tipo_chave == "codigo" else normaliza_texto
            chave = norm(l[coluna_winthor])
            if chave:
                achados[chave] = {k: v for k, v in l.items()
                                  if k != coluna_winthor}
                for k in achados[chave]:
                    if k not in colunas_novas:
                        colunas_novas.append(k)

    if erros and not achados:
        return {"erro": "Nenhum bloco do Winthor retornou. " + " | ".join(erros[:2])}

    novas_linhas, faltantes = junta(p["linhas"], coluna_planilha,
                                    achados, tipo_chave)

    # planilha NOVA, filha desta
    from app.planilhas import Coluna, Planilha
    cols = [Coluna(c["nome"], c.get("nome_original", c["nome"]), c["tipo"],
                   c["preenchidas"], c.get("exemplos", []))
            for c in p["colunas"]]
    for nome in colunas_novas:
        vals = [l.get(nome, "") for l in novas_linhas]
        cols.append(Coluna(nome, nome, "texto",
                           sum(1 for v in vals if v not in (None, "")),
                           [str(v) for v in vals if v not in (None, "")][:3]))
    nova = Planilha(colunas=cols, linhas=novas_linhas, aba=p["aba"],
                    total=len(novas_linhas))
    novo_id = await grava(pool, conversation_id, user_oid,
                          f"{p['nome_arquivo']} + Winthor", nova,
                          origem_id=str(p["id"]))

    casaram = len(p["linhas"]) - sum(
        1 for l in novas_linhas if not any(k in l for k in colunas_novas))
    resultado = {
        "planilha_id": novo_id,
        "linhas": len(novas_linhas),
        "casaram": casaram,
        "nao_casaram": len(novas_linhas) - casaram,
        "colunas_acrescentadas": colunas_novas,
        "chaves_sem_correspondencia": faltantes[:MAX_EXEMPLOS],
        "total_chaves_sem_correspondencia": len(faltantes),
        "blocos_consultados": len(list(blocos(chaves))),
    }
    if erros:
        resultado["avisos"] = erros[:3]
    # a frase que o agente deve repassar — sem esconder o que falhou
    resultado["mensagem"] = (
        f"{casaram} de {len(novas_linhas)} linhas casaram com o Winthor."
        + (f" {len(faltantes)} chaves não foram encontradas"
           f" (ex.: {', '.join(faltantes[:5])})." if faltantes else "")
    )
    return resultado
