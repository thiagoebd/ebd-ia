"""Cron de 5 campos (minuto hora dia-do-mes mes dia-da-semana), sem dependencia.

Aceita *, listas (1,15), faixas (1-5) e passos (*/15, 8-18/2). Dia da semana:
0 ou 7 = domingo. Quando dia-do-mes E dia-da-semana sao restritos, vale o
"OU" do cron classico.

O calculo e feito no fuso do agendamento (America/Sao_Paulo por padrao) —
a spec registra que cron em UTC ja fez job rodar as 21h do dia anterior.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

_LIMITES = [(0, 59), (0, 23), (1, 31), (1, 12), (0, 7)]
_NOMES = ["minuto", "hora", "dia do mes", "mes", "dia da semana"]


class CronInvalido(ValueError):
    pass


def _campo(txt: str, lo: int, hi: int, nome: str) -> set[int]:
    vals: set[int] = set()
    for parte in txt.split(","):
        passo = 1
        if "/" in parte:
            parte, p = parte.split("/", 1)
            if not p.isdigit() or int(p) < 1:
                raise CronInvalido(f"passo invalido no {nome}: {p!r}")
            passo = int(p)
        if parte == "*":
            a, b = lo, hi
        elif "-" in parte:
            x, y = parte.split("-", 1)
            if not (x.isdigit() and y.isdigit()):
                raise CronInvalido(f"faixa invalida no {nome}: {parte!r}")
            a, b = int(x), int(y)
        elif parte.isdigit():
            a = b = int(parte)
        else:
            raise CronInvalido(f"valor invalido no {nome}: {parte!r}")
        if a < lo or b > hi or a > b:
            raise CronInvalido(f"{nome} fora de {lo}-{hi}: {parte!r}")
        vals.update(range(a, b + 1, passo))
    return vals


def parse(expr: str) -> tuple[set[int], ...]:
    campos = (expr or "").split()
    if len(campos) != 5:
        raise CronInvalido("cron precisa de 5 campos: minuto hora dia mes dia-da-semana")
    minutos, horas, dias, meses, semana = (
        _campo(c, lo, hi, n) for c, (lo, hi), n in zip(campos, _LIMITES, _NOMES))
    if 7 in semana:
        semana = (semana - {7}) | {0}
    return minutos, horas, dias, meses, semana, (campos[2] != "*"), (campos[4] != "*")


def proxima(expr: str, depois_de: datetime, tz: str = "America/Sao_Paulo") -> datetime:
    """Primeiro instante do cron estritamente depois de `depois_de` (com fuso)."""
    minutos, horas, dias, meses, semana, dia_restrito, sem_restrita = parse(expr)
    z = ZoneInfo(tz)
    t = depois_de.astimezone(z).replace(second=0, microsecond=0) + timedelta(minutes=1)
    for _ in range(366 * 24 * 60):          # no maximo um ano de minutos
        dow = (t.weekday() + 1) % 7          # python: seg=0 -> cron: dom=0
        casa_dia = t.day in dias
        casa_sem = dow in semana
        if dia_restrito and sem_restrita:
            ok_dia = casa_dia or casa_sem
        else:
            ok_dia = casa_dia and casa_sem
        if t.month not in meses:
            t = (t.replace(day=1, hour=0, minute=0) + timedelta(days=32)).replace(day=1)
            continue
        if not ok_dia:
            t = (t + timedelta(days=1)).replace(hour=0, minute=0)
            continue
        if t.hour not in horas:
            t = (t + timedelta(hours=1)).replace(minute=0)
            continue
        if t.minute in minutos:
            return t
        t += timedelta(minutes=1)
    raise CronInvalido("cron nunca dispara no proximo ano")


def descreve(expr: str) -> str:
    """Leitura humana curta para a previa de confirmacao."""
    m, h, d, mes, sem = expr.split()
    hora = f"{int(h):02d}:{int(m):02d}" if h.isdigit() and m.isdigit() else f"min {m} / hora {h}"
    partes = [f"as {hora}"]
    if d != "*":
        partes.append(f"dia {d}")
    if mes != "*":
        partes.append(f"mes {mes}")
    if sem != "*":
        nomes = {"0": "dom", "7": "dom", "1": "seg", "2": "ter", "3": "qua",
                 "4": "qui", "5": "sex", "6": "sab", "1-5": "seg a sex", "1-6": "seg a sab"}
        partes.append(nomes.get(sem, f"dias da semana {sem}"))
    return " · ".join(partes)
