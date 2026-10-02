"""JID privado real via Evolution (/chat/whatsappNumbers) — nono digito."""
import pytest

class _RespFalsa:
    def __init__(self, status, corpo):
        self.status_code, self._c = status, corpo

    def json(self):
        return self._c


def _roda(coro):
    import asyncio
    return asyncio.run(coro)


def test_resolve_jid_usa_o_jid_real_sem_o_nono_digito(monkeypatch):
    """Regressao 02/10 (Caiky, DDD 91): cadastro +5591984678832, conta registrada
    sem o 9 — a Evolution recusava 5591984678832@s.whatsapp.net."""
    from gateway.app import entrega
    import app.adapters.whatsapp as wa
    pedido = {}

    async def post_falso(caminho, corpo, timeout=120):
        pedido.update(caminho=caminho, corpo=corpo)
        return _RespFalsa(200, [
            {"jid": "559184678832@s.whatsapp.net", "exists": True, "number": "5591984678832"},
            {"jid": "559184678832@s.whatsapp.net", "exists": True, "number": "559184678832"}])
    monkeypatch.setattr(wa, "_post", post_falso)
    jid = _roda(entrega.resolve_jid(entrega.jid_privado("+5591984678832")))
    assert jid == "559184678832@s.whatsapp.net"
    assert pedido["caminho"] == "chat/whatsappNumbers"
    assert pedido["corpo"]["numbers"] == ["5591984678832", "559184678832"]


def test_resolve_jid_numero_sem_whatsapp_falha_claro(monkeypatch):
    from gateway.app import entrega
    import app.adapters.whatsapp as wa

    async def post_falso(caminho, corpo, timeout=120):
        return _RespFalsa(200, [{"jid": "x", "exists": False, "number": n} for n in corpo["numbers"]])
    monkeypatch.setattr(wa, "_post", post_falso)
    with pytest.raises(entrega.EntregaFalhou) as e:
        _roda(entrega.resolve_jid("5511999998888@s.whatsapp.net"))
    assert e.value.codigo == "NUMERO_SEM_WHATSAPP"


def test_resolve_jid_grupo_passa_direto_e_falha_de_rede_nao_bloqueia(monkeypatch):
    from gateway.app import entrega
    import app.adapters.whatsapp as wa

    async def post_quebrado(caminho, corpo, timeout=120):
        raise OSError("rede")
    monkeypatch.setattr(wa, "_post", post_quebrado)
    assert _roda(entrega.resolve_jid("120363000000000001@g.us")) == "120363000000000001@g.us"
    assert _roda(entrega.resolve_jid("5511999998888@s.whatsapp.net")) == "5511999998888@s.whatsapp.net"
