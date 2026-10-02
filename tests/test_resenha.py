"""Resenha no grupo: manchetes vem da fonte, nunca da memoria do modelo."""
import asyncio
import json
from datetime import datetime, timezone
import sys

from conftest import RAIZ

sys.path.insert(0, str(RAIZ / "core"))
sys.path.insert(0, str(RAIZ))

RSS = """<rss><channel>
<item><title>Flamengo vence o Palmeiras no Maracanã - ge</title>
<pubDate>Thu, 01 Oct 2026 23:00:00 GMT</pubDate><source url="x">ge</source></item>
<item><title>Flamengo vence o Palmeiras no Maracanã - ge</title>
<pubDate>Thu, 01 Oct 2026 23:00:00 GMT</pubDate><source url="x">ge</source></item>
<item><title>Filipe Luís fala em &quot;foco total&quot; - Lance!</title>
<pubDate>Tue, 29 Sep 2026 12:00:00 GMT</pubDate><source url="y">Lance!</source></item>
<item><title>sem data</title></item>
</channel></rss>"""


def test_parse_rss_ordena_deduplica_e_limpa():
    from app.tools import resenha_tools as r
    agora = datetime(2026, 10, 2, 11, 0, tzinfo=timezone.utc)
    m = r.parse_rss(RSS, agora)
    assert [x["titulo"] for x in m] == ["Flamengo vence o Palmeiras no Maracanã",
                                        'Filipe Luís fala em "foco total"']
    assert m[0]["quando"] == "há 12h" and m[0]["veiculo"] == "ge"
    assert m[1]["quando"] == "29/09"


def test_sem_rede_devolve_vazio_com_aviso(monkeypatch):
    from app.tools import resenha_tools as r

    def quebra(url):
        raise OSError("sem rede")
    monkeypatch.setattr(r, "_baixa", quebra)
    d = json.loads(asyncio.run(r.executa("manchetes_atuais", {"assunto": "Flamengo"})))
    assert d["manchetes"] == [] and "sem citar fato" in d["aviso"]


def test_ferramenta_registrada_no_agente():
    from app.tools.resenha_tools import MANCHETES_TOOL
    from app import agent
    assert MANCHETES_TOOL in agent._tools
