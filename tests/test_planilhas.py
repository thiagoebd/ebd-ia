"""Planilha: leitura, normalizacao e cruzamento com o Winthor.

O Excel destroi codigo de tres formas e todas aparecem na pratica:
zero a esquerda comido, notacao cientifica, float que era inteiro.
E nome nunca casa exato: 'thiago parreira' e 'THIAGO MARTINS PARREIRA'.
"""
import asyncio
import io
import sys

import pytest

from conftest import RAIZ

sys.path.insert(0, str(RAIZ / "core"))
from app.planilhas import (  # noqa: E402
    MAX_LINHAS, PlanilhaInvalida, blocos, chaves_unicas, junta, le_planilha,
    lista_sql, normaliza_codigo, normaliza_texto, tokens,
)
from app.planilha_match import (  # noqa: E402
    ENTIDADES, classifica, sql_por_nome, texto_para_o_usuario,
)


def xlsx(dados: dict, aba="Plan1") -> bytes:
    import pandas as pd
    buf = io.BytesIO()
    pd.DataFrame(dados).to_excel(buf, index=False, sheet_name=aba)
    return buf.getvalue()


# ─── normalizacao: o que o Excel faz com codigo ───

@pytest.mark.parametrize("bruto,esperado", [
    ("00123", "123"),                      # zero a esquerda comido
    ("7.897123883077E+12", "7897123883077"),  # EAN em notacao cientifica
    ("123.0", "123"),                      # float que era inteiro
    ("12.345.678/0001-90", "12345678000190"),  # CNPJ pontuado
    (" 456 ", "456"),
    ("", ""),
])
def test_normaliza_codigo(bruto, esperado):
    assert normaliza_codigo(bruto) == esperado


def test_normaliza_texto_tira_acento_e_espaco():
    assert normaliza_texto("  Água   Prata ") == "AGUA PRATA"


def test_tokens_ignora_palavra_curta():
    assert tokens("J. da Silva & Cia") == ["SILVA", "CIA"]


# ─── leitura ───

def test_le_xlsx_com_cabecalho_sujo():
    p = le_planilha(xlsx({"Código Produto": ["1"], "Descrição ": ["x"]}), "a.xlsx")
    assert [c.nome for c in p.colunas] == ["CODIGO_PRODUTO", "DESCRICAO"]
    assert p.total == 1


def test_le_csv_com_ponto_e_virgula():
    csv = "COD;NOME\n1;Agua\n2;Gel\n".encode()
    p = le_planilha(csv, "a.csv")
    assert p.total == 2 and len(p.colunas) == 2


def test_colunas_duplicadas_ganham_sufixo():
    import pandas as pd
    buf = io.BytesIO()
    df = pd.DataFrame([[1, 2]], columns=["COD", "COD"])
    df.to_excel(buf, index=False)
    p = le_planilha(buf.getvalue(), "a.xlsx")
    assert len({c.nome for c in p.colunas}) == 2


def test_avisa_coluna_vazia():
    p = le_planilha(xlsx({"A": ["1"], "VAZIA": [""]}), "a.xlsx")
    assert any("VAZIA" in a for a in p.avisos)


def test_arquivo_vazio_e_recusado():
    with pytest.raises(PlanilhaInvalida):
        le_planilha(b"", "a.xlsx")


def test_arquivo_ilegivel_da_mensagem_util():
    with pytest.raises(PlanilhaInvalida) as e:
        le_planilha(b"nao sou planilha", "a.xlsx")
    assert "xlsx" in str(e.value).lower()


def test_resumo_nao_traz_as_linhas():
    """O agente ve resumo, nunca os dados — custo constante."""
    p = le_planilha(xlsx({"A": [str(i) for i in range(500)]}), "a.xlsx")
    r = p.resumo_para_agente()
    assert r["linhas"] == 500
    assert "linhas_dados" not in r
    assert len(str(r)) < 2000


# ─── cruzamento ───

def test_chaves_unicas_normaliza_e_deduplica():
    linhas = [{"C": "00123"}, {"C": "123"}, {"C": "456"}, {"C": ""}]
    assert chaves_unicas(linhas, "C") == ["123", "456"]


def test_blocos_respeitam_limite_do_oracle():
    ch = [str(i) for i in range(2500)]
    b = list(blocos(ch))
    assert len(b) == 3 and all(len(x) <= 1000 for x in b)


def test_lista_sql_escapa_aspas():
    assert "''" in lista_sql(["O'BRIEN"], numerico=False)


def test_junta_marca_o_que_nao_casou():
    linhas = [{"C": "00123"}, {"C": "999"}]
    novas, falta = junta(linhas, "C", {"123": {"EST": 10}})
    assert novas[0]["EST"] == 10
    assert "EST" not in novas[1]
    assert falta == ["999"]


# ─── matching por nome ───

def test_thiago_parreira_casa_com_nome_completo():
    """O caso que motivou o recurso."""
    assert set(tokens("thiago parreira")) <= set(tokens("THIAGO MARTINS PARREIRA"))


def test_fornecedor_resolve_pela_raiz():
    """Cicatriz #74: sempre NVL(CODFORNECPRINC, CODFORNEC)."""
    assert "CODFORNECPRINC" in sql_por_nome("fornecedor", ["nissin"])


def test_vendedor_traz_so_rca_de_campo():
    """Cicatriz #90: sem desligado, sem supervisor."""
    s = sql_por_nome("vendedor", ["joao silva"])
    assert "DTTERMINO" in s and "COD_CADRCA" in s


def test_produto_ignora_excluido():
    assert "DTEXCLUSAO IS NULL" in sql_por_nome("produto", ["gel energetico"])


def test_um_candidato_resolve():
    r = classifica(["thiago parreira"],
                   [{"BUSCADO": "thiago parreira", "CODUSUR": 3639,
                     "NOME": "THIAGO MARTINS PARREIRA"}])
    assert r.resolvido and not r.ambiguo


def test_varios_candidatos_vao_para_o_usuario():
    """NAO escolher sozinho — o mesmo principio do anti-fabulacao."""
    r = classifica(["silva"], [
        {"BUSCADO": "silva", "CODCLI": 7, "NOME": "JOAO SILVA"},
        {"BUSCADO": "silva", "CODCLI": 8, "NOME": "MARIA SILVA"},
    ])
    assert not r.resolvido
    assert len(r.ambiguo["silva"]) == 2


def test_nome_exato_vence_o_parcial():
    r = classifica(["aguas prata"], [
        {"BUSCADO": "aguas prata", "CODCLI": 100, "NOME": "AGUAS PRATA"},
        {"BUSCADO": "aguas prata", "CODCLI": 200,
         "NOME": "AGUAS PRATA DISTRIBUIDORA"},
    ])
    assert r.resolvido["aguas prata"]["CODCLI"] == 100


def test_sem_candidato_vira_nao_achado():
    r = classifica(["xyz"], [])
    assert r.nao_achado == ["xyz"]


def test_texto_mostra_os_tres_grupos():
    r = classifica(["a", "b"], [{"BUSCADO": "a", "CODCLI": 1, "NOME": "A"}])
    t = texto_para_o_usuario("cliente", r)
    assert "1 de 2" in t and "sem nenhum candidato" in t


def test_as_cinco_entidades_existem():
    """95% dos casos: cliente, fornecedor, produto, filial, vendedor."""
    assert set(ENTIDADES) == {"cliente", "fornecedor", "produto",
                              "filial", "vendedor"}


# ─── ferramentas ───

def test_ferramentas_mandam_perguntar_no_ambiguo():
    from app.tools.planilha_tools import PLANILHA_RESOLVER_TOOL
    d = PLANILHA_RESOLVER_TOOL["description"].lower()
    assert "pergunte" in d and "não escolha sozinho" in d


def test_ferramenta_cruzar_explica_o_marcador():
    from app.tools.planilha_tools import PLANILHA_CRUZAR_TOOL
    assert ":chaves" in PLANILHA_CRUZAR_TOOL["description"]


def test_planilha_cascateia_com_a_conversa():
    """Rotacao de 5 conversas tem que levar a planilha junto."""
    s = (RAIZ / "gateway" / "app" / "db.py").read_text(encoding="utf-8")
    i = s.index("CREATE TABLE IF NOT EXISTS planilhas")
    assert "REFERENCES conversations(id) ON DELETE CASCADE" in s[i:i + 700]




def _run(coro):
    """O projeto nao usa pytest-asyncio — evita mais uma dependencia."""
    return asyncio.run(coro)


async def _sem_oracle_c(sql):
    return []

# ─── executores ───

def _run(coro):
    """O projeto nao usa pytest-asyncio — evita mais uma dependencia."""
    import asyncio
    return asyncio.run(coro)


class _Pool:
    """Postgres de mentira: guarda as planilhas num dict."""

    def __init__(self):
        self.dados, self.seq = {}, 0

    def acquire(self):
        pool = self

        class _Ctx:
            async def __aenter__(self):
                return _Con(pool)

            async def __aexit__(self, *a):
                return False

        return _Ctx()


class _Con:
    def __init__(self, pool):
        self.p = pool

    async def fetchrow(self, sql, *args):
        if "INSERT" in sql:
            self.p.seq += 1
            pid = f"id-{self.p.seq}"
            self.p.dados[pid] = {
                "id": pid, "conversation_id": args[0], "user_oid": args[1],
                "nome_arquivo": args[2], "aba": args[3],
                "total_linhas": args[4], "colunas": args[5],
                "linhas": args[6], "created_at": self.p.seq}
            return {"id": pid}
        if args and str(args[0]).startswith("id-"):
            return self.p.dados.get(args[0])
        vivos = sorted(self.p.dados.values(), key=lambda d: -d["created_at"])
        return vivos[0] if vivos else None

    async def execute(self, sql, *args):
        if "DELETE" in sql:
            vivos = sorted(self.p.dados.values(), key=lambda d: -d["created_at"])
            for d in vivos[args[1]:]:
                self.p.dados.pop(d["id"], None)
        return "DELETE 0"


async def _sem_oracle(sql):
    return []


def _com_planilha(pool, dados, conv="conv-1"):
    from app.tools.planilha_exec import grava
    p = le_planilha(xlsx(dados), "x.xlsx")
    return _run(grava(pool, conv, "user-1", "x.xlsx", p))


def test_grava_e_resume():
    from app.tools.planilha_exec import executa_resumo
    pool = _Pool()
    pid = _com_planilha(pool, {"COD": ["1", "2"], "NOME": ["a", "b"]})
    r = _run(executa_resumo(pool, "conv-1", pid))
    assert r["linhas"] == 2
    assert {c["nome"] for c in r["colunas"]} == {"COD", "NOME"}


def test_poda_mantem_so_tres_versoes():
    """Cruzamento gera planilha nova — sem poda o Postgres cresce sem fim."""
    from app.tools.planilha_exec import MAX_VERSOES
    pool = _Pool()
    for _ in range(6):
        _com_planilha(pool, {"COD": ["1"]})
    assert len(pool.dados) == MAX_VERSOES


def test_cruzar_exige_o_marcador_chaves():
    from app.tools.planilha_exec import executa_cruzar
    pool = _Pool()
    _com_planilha(pool, {"COD": ["1"]})
    r = _run(executa_cruzar(pool, "conv-1", "user-1", "COD",
                            "SELECT 1 FROM DUAL", "CODPROD", _sem_oracle))
    assert ":chaves" in r["erro"]


def test_cruzar_avisa_coluna_inexistente():
    from app.tools.planilha_exec import executa_cruzar
    pool = _Pool()
    _com_planilha(pool, {"COD": ["1"]})
    r = _run(executa_cruzar(pool, "conv-1", "user-1", "NAO_EXISTE",
                            "SELECT x FROM t WHERE c IN (:chaves)",
                            "CODPROD", _sem_oracle))
    assert "COD" in r["erro"]


def test_cruzar_conta_o_que_nao_casou():
    """O agente precisa saber o que ficou de fora — nunca apresentar
    resultado parcial como se fosse completo."""
    from app.tools.planilha_exec import executa_cruzar
    pool = _Pool()
    _com_planilha(pool, {"COD": ["00123", "999"]})

    async def oracle(sql):
        return [{"CODPROD": "123", "QTESTGER": 1080, "FORNEC": "SUPLEY"}]

    r = _run(executa_cruzar(pool, "conv-1", "user-1", "COD",
                            "SELECT CODPROD, QTESTGER, FORNEC FROM t "
                            "WHERE CODPROD IN (:chaves)", "CODPROD", oracle))
    assert r["casaram"] == 1
    assert r["nao_casaram"] == 1
    assert "999" in r["chaves_sem_correspondencia"]
    assert "QTESTGER" in r["colunas_acrescentadas"]


def test_cruzar_gera_planilha_nova():
    """Encadeamento: produto -> estoque -> giro, sem refazer o de tras."""
    from app.tools.planilha_exec import executa_cruzar
    pool = _Pool()
    pid = _com_planilha(pool, {"COD": ["1"]})

    async def oracle(sql):
        return [{"CODPROD": "1", "EST": 10}]

    r = _run(executa_cruzar(pool, "conv-1", "user-1", "COD",
                            "SELECT CODPROD, EST FROM t WHERE c IN (:chaves)",
                            "CODPROD", oracle))
    assert r["planilha_id"] != pid


def test_resolver_devolve_os_tres_grupos():
    from app.tools.planilha_exec import executa_resolver
    pool = _Pool()
    _com_planilha(pool, {"CLIENTE": ["thiago parreira", "silva", "xyz"]})

    async def oracle(sql):
        return [
            {"BUSCADO": "thiago parreira", "CODCLI": 1,
             "NOME": "THIAGO MARTINS PARREIRA"},
            {"BUSCADO": "silva", "CODCLI": 2, "NOME": "JOAO SILVA"},
            {"BUSCADO": "silva", "CODCLI": 3, "NOME": "MARIA SILVA"},
        ]

    r = _run(executa_resolver(pool, "conv-1", "CLIENTE", "cliente", oracle))
    assert r["resolvidos"] == 1
    assert r["ambiguos"] == 1
    assert r["nao_achados"] == 1
    assert r["para_decidir"]


def test_cruzar_quebra_em_blocos_de_mil():
    """O Oracle recusa IN (...) com mais de 1000 itens."""
    from app.tools.planilha_exec import executa_cruzar
    pool = _Pool()
    _com_planilha(pool, {"COD": [str(i) for i in range(1, 2501)]})
    chamadas = []

    async def oracle(sql):
        chamadas.append(sql)
        return []

    r = _run(executa_cruzar(pool, "conv-1", "user-1", "COD",
                            "SELECT CODPROD FROM t WHERE CODPROD IN (:chaves)",
                            "CODPROD", oracle))
    assert len(chamadas) == 3
    assert r["blocos_consultados"] == 3


# ─── integracao: front, rota e agente ───

def _fonte(rel: str) -> str:
    return (RAIZ / rel).read_text(encoding="utf-8")


def test_agente_registra_as_tres_ferramentas():
    s = _fonte("core/app/agent.py")
    assert "PLANILHA_TOOLS" in s
    assert "_run_planilha" in s


def test_agente_recebe_o_contexto_do_gateway():
    """O agente vive no core e o Postgres no gateway — o contexto desce
    por parametro."""
    s = _fonte("core/app/agent.py")
    assert s.count("planilha_ctx") >= 4


def test_rota_aceita_planilha_no_mesmo_corpo():
    s = _fonte("gateway/app/routes/chat.py")
    assert "planilha_b64" in s and "planilha_nome" in s


def test_rota_grava_antes_de_chamar_o_agente():
    s = _fonte("gateway/app/routes/chat.py")
    assert s.index("_grava_pl") < s.index("planilha_ctx=_pl_ctx")


def test_front_envia_planilha():
    s = _fonte("frontend/src/App.tsx")
    assert "planilha_b64: pl ? pl.b64 : undefined" in s


def test_front_aceita_xlsx_e_csv():
    s = _fonte("frontend/src/App.tsx")
    assert ".xlsx" in s and ".csv" in s


def test_front_permite_enviar_so_planilha():
    s = _fonte("frontend/src/App.tsx")
    assert "&& !planilha" in s


def test_agente_e_avisado_da_planilha():
    """Sem aviso o agente nao sabe que ha planilha e nunca chama a
    ferramenta — fica sem saber o que responder."""
    s = _fonte("core/app/agent.py")
    assert s.count("aviso_planilha") >= 4


def test_aviso_entra_antes_da_pergunta():
    s = _fonte("core/app/agent.py")
    assert 'f"{aviso_planilha}' in s


def test_titulo_vem_do_conteudo_nao_do_nome_do_arquivo():
    """'filiais-ebd-cnpjs.xlsx' vira 'Filiais, Cnpj (21 linhas)'."""
    s = _fonte("gateway/app/routes/chat.py")
    assert "_titulo_da_planilha" in s
    i = s.index("def _titulo_da_planilha")
    assert "c.nome" in s[i:i + 600]


def test_coluna_sem_cabecalho_nao_vira_unnamed():
    """O pandas chama 'Unnamed: 0' — poluia o titulo da conversa."""
    import pandas as pd
    buf = io.BytesIO()
    df = pd.DataFrame({"": ["x"], "VENDEDOR": ["a"]})
    df.to_excel(buf, index=False)
    p = le_planilha(buf.getvalue(), "x.xlsx")
    assert not any("UNNAMED" in c.nome for c in p.colunas)


def test_titulo_ignora_coluna_generica():
    s = _fonte("gateway/app/routes/chat.py")
    i = s.index("def _titulo_da_planilha")
    assert 'startswith("COLUNA_")' in s[i:i + 700]


def test_bolha_mostra_o_anexo():
    s = _fonte("frontend/src/App.tsx")
    assert "msg-anexo" in s
    assert 'anexo?: { nome: string; tipo: string }' in s


def test_anexo_fica_no_historico():
    s = _fonte("gateway/app/routes/chat.py")
    assert '_cont_user["anexo"]' in s
    c = _fonte("gateway/app/routes/conversations.py")
    assert '"anexo"' in c


def test_push_da_mensagem_leva_anexo_nao_base64():
    """O replace foi no objeto errado: o base64 (que e enorme) ia para a
    bolha da UI e o campo `anexo` nunca era criado."""
    s = _fonte("frontend/src/App.tsx")
    i = s.index('{ role: "user", text: question')
    msg = s[i:i + 200]
    assert "anexo: pl ?" in msg
    assert "planilha_b64" not in msg, "o base64 nao pode ir para a bolha"


def test_corpo_da_requisicao_leva_o_base64():
    s = _fonte("frontend/src/App.tsx")
    # o corpo DA MENSAGEM — outras chamadas (fixar conversa) tambem usam
    # JSON.stringify e vem antes no arquivo
    i = s.index("body: JSON.stringify({ message")
    assert "planilha_b64: pl ? pl.b64" in s[i:i + 300]


def test_le_xlsx_de_dialeto_estranho():
    """Um export real tinha 'defaultColWidthPt', que o openpyxl recusa com
    TypeError. O calamine le — por isso ele vem primeiro."""
    s = (RAIZ / "core" / "app" / "planilhas.py").read_text(encoding="utf-8")
    i = s.index("for motor in")
    assert '"calamine", None' in s[i:i + 120], "calamine tem que vir primeiro"


def test_arquivo_ilegivel_orienta_o_usuario():
    """Mensagem que diz O QUE FAZER, nao so que falhou."""
    s = (RAIZ / "core" / "app" / "planilhas.py").read_text(encoding="utf-8")
    assert "salve como" in s.lower() or "exporte em CSV" in s


def test_pl_pendente_existe_mesmo_se_a_leitura_falhar():
    """Bug de 11/09: a variavel so era criada no else, entao quando a
    leitura lancava excecao o erro real sumia atras de um NameError."""
    s = (RAIZ / "gateway" / "app" / "routes" / "chat.py").read_text(encoding="utf-8")
    i = s.index("_erro_pl = None")
    j = s.index("if body.planilha_b64:")
    assert "_pl_pendente = None" in s[i:j], \
        "_pl_pendente tem que ser inicializada ANTES do try"


def test_escolhe_a_aba_com_mais_dados():
    """Um arquivo real de diretoria tinha 8 abas: a primeira com 2 linhas
    de resumo e a ultima com 2.562 de detalhe. Ler a primeira dava uma
    analise sobre nada."""
    import pandas as pd
    buf = io.BytesIO()
    with pd.ExcelWriter(buf) as w:
        pd.DataFrame({"A": ["1"]}).to_excel(w, sheet_name="resumo", index=False)
        pd.DataFrame({"B": [str(i) for i in range(200)]}).to_excel(
            w, sheet_name="detalhe", index=False)
    p = le_planilha(buf.getvalue(), "x.xlsx")
    assert p.aba == "detalhe"
    assert p.total == 200


def test_mapeia_todas_as_abas():
    import pandas as pd
    buf = io.BytesIO()
    with pd.ExcelWriter(buf) as w:
        for n in ("um", "dois", "tres"):
            pd.DataFrame({"A": ["1"]}).to_excel(w, sheet_name=n, index=False)
    p = le_planilha(buf.getvalue(), "x.xlsx")
    assert len(p.abas) == 3
    assert {a["nome"] for a in p.abas} == {"um", "dois", "tres"}


def test_resumo_mostra_as_outras_abas():
    """O agente precisa SABER que existem, senao analisa uma e cala."""
    import pandas as pd
    buf = io.BytesIO()
    with pd.ExcelWriter(buf) as w:
        pd.DataFrame({"A": ["1"]}).to_excel(w, sheet_name="a", index=False)
        pd.DataFrame({"B": ["1", "2"]}).to_excel(w, sheet_name="b", index=False)
    r = le_planilha(buf.getvalue(), "x.xlsx").resumo_para_agente()
    assert "outras_abas" in r and len(r["outras_abas"]) == 1


def test_permite_escolher_a_aba():
    import pandas as pd
    buf = io.BytesIO()
    with pd.ExcelWriter(buf) as w:
        pd.DataFrame({"A": ["1"]}).to_excel(w, sheet_name="pequena", index=False)
        pd.DataFrame({"B": [str(i) for i in range(50)]}).to_excel(
            w, sheet_name="grande", index=False)
    p = le_planilha(buf.getvalue(), "x.xlsx", aba_escolhida="pequena")
    assert p.aba == "pequena"


def test_aviso_ao_agente_lista_as_abas():
    s = _fonte("gateway/app/routes/chat.py")
    assert "O ARQUIVO TEM" in s and "DIGA ao usuario quais sao as outras abas" in s
