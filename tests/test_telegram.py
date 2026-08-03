"""Telegram: modelo padrao e rodape de custo.

Em 31/07/2026 o diretor comercial via "R$ 0,28 - total: R$ 13,12" em cada
resposta. A condicao era `role == "admin"` — e todos os 16 usuarios sao admin.
"""
import re
import sys
from pathlib import Path

from conftest import RAIZ

AD = RAIZ / "core" / "app" / "adapters" / "telegram.py"


def _fonte() -> str:
    return AD.read_text(encoding="utf-8")


def test_modelo_padrao_e_deepseek_pro():
    m = re.search(r"getenv\('TELEGRAM_MODEL',\s*'([^']+)'\)", _fonte())
    assert m, "nao achei o default de TELEGRAM_MODEL"
    assert m.group(1) == "deepseek-v4-pro"


def test_rodape_nao_depende_mais_de_role_admin():
    """A condicao antiga liberava para todos, ja que todos sao admin."""
    fonte = _fonte()
    i = fonte.index('response = result["text"]')
    trecho = fonte[i:i + 900]
    assert 'if role == "admin":' not in trecho
    assert "TELEGRAM_MOSTRAR_CUSTO" in trecho


def test_rodape_desligado_por_padrao():
    m = re.search(r"getenv\('TELEGRAM_MOSTRAR_CUSTO',\s*'([^']+)'\)", _fonte())
    assert m and m.group(1) == "0"


def test_custo_continua_no_log_do_servidor():
    """Sumir da tela nao pode significar parar de contabilizar."""
    fonte = _fonte()
    assert "llm_events.jsonl" in fonte
    assert "stats[\"cost_usd\"] += cost" in fonte
    assert "💰" in fonte


def test_saldo_continua_disponivel():
    """O comando /saldo segue existindo para quem quiser consultar."""
    assert "/saldo" in _fonte()
