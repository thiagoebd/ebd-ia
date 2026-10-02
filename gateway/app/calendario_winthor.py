"""Regra de dia do agendador — pelo calendario do Winthor, nunca pelo relogio.

PCDIASUTEIS tem o calendario de VENDAS por filial (DIAVENDAS = 'S'), com
feriado regional. Sabado nao e dia de venda na EBD (T-CAL01, 30/09/2026).

Brasil ('BR') = dia util se a MAIORIA das 21 filiais comerciais vende naquele
dia — o mesmo criterio do T-CAL01 e do painel consolidado.

Se o Oracle falhar, levanta CalendarioIndisponivel: o worker registra ERRO e
avisa. Job que nao roda e nao avisa e pior que job que nao existe.
"""
from __future__ import annotations

import time
from datetime import date

FILIAIS_BR = ("01", "02", "03", "04", "05", "06", "07", "08", "09", "10", "11",
              "12", "13", "14", "15", "16", "18", "21", "22", "52", "53")
_cache: dict[tuple[str, str], tuple[float, list[date]]] = {}
_TTL = 3 * 3600


class CalendarioIndisponivel(RuntimeError):
    pass


def _sql(filial: str) -> str:
    if filial == "BR":
        filtro = "CODFILIAL IN (" + ",".join(f"'{f}'" for f in FILIAIS_BR) + ")"
    else:
        if not (filial.isalnum() and len(filial) <= 3):
            raise ValueError(f"filial invalida: {filial!r}")
        filtro = f"CODFILIAL = '{filial}'"
    return (
        "SELECT TO_CHAR(DATA, 'YYYY-MM-DD') AS DIA, "
        "SUM(CASE WHEN DIAVENDAS = 'S' THEN 1 ELSE 0 END) AS VENDE, COUNT(*) AS TOTAL "
        "FROM EBD.PCDIASUTEIS "
        "WHERE DATA >= TRUNC(SYSDATE, 'MM') AND DATA < ADD_MONTHS(TRUNC(SYSDATE, 'MM'), 1) "
        f"AND {filtro} GROUP BY DATA ORDER BY DATA")


async def dias_uteis_do_mes(filial: str = "BR", consulta=None) -> list[date]:
    """Dias de venda do mes corrente. `consulta` permite injetar o Oracle nos testes."""
    chave = (filial, date.today().strftime("%Y-%m"))
    hit = _cache.get(chave)
    if hit and time.time() - hit[0] < _TTL:
        return hit[1]
    if consulta is None:
        from app.tools.oracle_bridge import execute_oracle_query as consulta
    r = await consulta(_sql(filial), max_rows=40)
    if r.get("error"):
        raise CalendarioIndisponivel(str(r["error"])[:200])
    linhas = (r.get("result") or {}).get("rows") or []
    if not linhas:
        raise CalendarioIndisponivel(f"PCDIASUTEIS sem o mes corrente para {filial}")
    uteis = [date.fromisoformat(x["DIA"]) for x in linhas
             if int(x["VENDE"] or 0) * 2 > int(x["TOTAL"] or 0)]
    _cache[chave] = (time.time(), uteis)
    return uteis


async def passa_regra(regra: str, hoje: date, filial: str = "BR", consulta=None) -> bool:
    """O job deve rodar hoje, pela regra do dia?"""
    if regra in ("TODO_DIA", "DIA_FIXO"):
        return True                      # DIA_FIXO: o proprio cron fixa o dia
    uteis = await dias_uteis_do_mes(filial, consulta)
    if regra == "DIA_UTIL":
        return hoje in uteis
    if regra == "ULTIMO_DIA_UTIL":
        return bool(uteis) and hoje == max(uteis)
    raise ValueError(f"regra de dia desconhecida: {regra}")
