"""Planilhas do usuário — carregar, normalizar e cruzar com o Winthor.

DESENHO

A planilha NUNCA entra no prompt. Ela vira linhas numa tabela do Postgres
e o agente recebe apenas o resumo (colunas, tipos, contagem, 3 exemplos) —
custa ~200 tokens, seja a planilha de 50 ou de 50.000 linhas.

O cruzamento acontece aqui, não no modelo: o agente diz QUAL coluna é a
chave e QUAL consulta buscar no Winthor; este módulo resolve o resto —
normaliza, quebra em blocos de 1.000 (limite do IN do Oracle), executa e
junta. O agente recebe de volta um resumo do que casou e do que não casou.

MATCHING

Duas naturezas diferentes, tratadas de formas diferentes:

  chave EXATA (codigo, CNPJ, EAN) -> problema de FORMATO. O Excel come zero
  a esquerda, transforma EAN em notacao cientifica e o CNPJ vem com ou sem
  pontuacao. Resolve-se com codigo, sem consultar o modelo.

  chave por NOME (cliente, fornecedor, produto) -> nao tem resposta
  deterministica. "thiago parreira" e "THIAGO MARTINS PARREIRA" sao a mesma
  pessoa; "PARREIRA COMERCIO" pode nao ser. Aqui o banco traz CANDIDATOS e
  quem decide e o usuario quando ha duvida — nunca se casa em silencio.
"""
from __future__ import annotations

import io
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any

MAX_LINHAS = 50_000
MAX_BYTES = 20 * 1024 * 1024
CHUNK_ORACLE = 1000          # limite do IN (...) do Oracle
AMOSTRA = 3


class PlanilhaInvalida(Exception):
    """Recusa com mensagem que vai direto ao usuário."""


# ─── normalização ──────────────────────────────────────────────────────

def sem_acento(t: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", t)
                   if not unicodedata.combining(c))


def normaliza_texto(v: Any) -> str:
    """Para comparar nome: maiúsculas, sem acento, espaço único."""
    if v is None:
        return ""
    return re.sub(r"\s+", " ", sem_acento(str(v)).upper()).strip()


def normaliza_codigo(v: Any) -> str:
    """Para comparar código numérico vindo de planilha.

    O Excel destrói códigos de três formas, e todas aparecem na prática:
      '00123'   -> vira 123 (zero à esquerda comido)
      7897123883077 -> vira 7.897123883077E+12 (notação científica)
      123       -> vira 123.0 (float)
    """
    if v is None:
        return ""
    s = str(v).strip()
    if not s:
        return ""
    # notação científica
    if re.fullmatch(r"-?\d+(\.\d+)?[eE][+-]?\d+", s):
        try:
            s = f"{int(float(s))}"
        except (ValueError, OverflowError):
            pass
    # float que era inteiro
    if re.fullmatch(r"-?\d+\.0+", s):
        s = s.split(".")[0]
    # só os dígitos (tira pontuação de CNPJ/CPF/EAN)
    so_digitos = re.sub(r"\D", "", s)
    if so_digitos:
        return so_digitos.lstrip("0") or "0"
    return normaliza_texto(s)


def tokens(t: str) -> list[str]:
    """Palavras com 3+ letras, para busca por nome.

    'thiago parreira' -> ['THIAGO', 'PARREIRA'] casa com
    'THIAGO MARTINS PARREIRA' porque todos os tokens estão presentes.
    """
    return [p for p in re.split(r"[^A-Z0-9]+", normaliza_texto(t)) if len(p) >= 3]


# ─── leitura do arquivo ────────────────────────────────────────────────

@dataclass
class Coluna:
    nome: str
    nome_original: str
    tipo: str                      # texto | numero | data
    preenchidas: int
    exemplos: list[str] = field(default_factory=list)


@dataclass
class Planilha:
    colunas: list[Coluna]
    linhas: list[dict]
    aba: str
    total: int
    avisos: list[str] = field(default_factory=list)
    # arquivo de diretoria costuma vir com varias abas; o agente precisa
    # SABER que existem para nao analisar uma de 2 linhas achando que e
    # o arquivo todo
    abas: list[dict] = field(default_factory=list)

    def resumo_para_agente(self) -> dict:
        """O que o modelo vê. Some ~200 tokens, independente do tamanho."""
        d = {
            "aba": self.aba,
            "linhas": self.total,
            "colunas": [
                {"nome": c.nome, "tipo": c.tipo,
                 "preenchidas": c.preenchidas,
                 "exemplos": c.exemplos[:AMOSTRA]}
                for c in self.colunas
            ],
            "avisos": self.avisos,
        }
        if len(self.abas) > 1:
            d["outras_abas"] = [a for a in self.abas if a["nome"] != self.aba]
        return d


def _limpa_cabecalho(nome: Any, i: int) -> str:
    t = normaliza_texto(nome).replace(" ", "_")
    t = re.sub(r"[^A-Z0-9_]", "", t)
    # o pandas chama coluna sem cabecalho de 'Unnamed: 0' — nao e nome de
    # verdade e polui o titulo da conversa
    if not t or t.startswith("UNNAMED"):
        return f"COLUNA_{i + 1}"
    return t


def _tipo_da_coluna(valores: list) -> str:
    uteis = [v for v in valores if v not in (None, "")][:200]
    if not uteis:
        return "texto"
    n_num = sum(1 for v in uteis
                if re.fullmatch(r"-?[\d.,]+([eE][+-]?\d+)?", str(v).strip()))
    if n_num / len(uteis) > 0.8:
        return "numero"
    n_data = sum(1 for v in uteis
                 if re.search(r"\d{2}[/-]\d{2}[/-]\d{2,4}", str(v)))
    if n_data / len(uteis) > 0.8:
        return "data"
    return "texto"


def le_planilha(dados: bytes, nome_arquivo: str = "",
                aba_escolhida: str | None = None) -> Planilha:
    """xlsx/xls/csv -> Planilha. Levanta PlanilhaInvalida com msg ao usuário."""
    if not dados:
        raise PlanilhaInvalida("O arquivo chegou vazio.")
    if len(dados) > MAX_BYTES:
        raise PlanilhaInvalida(
            f"O arquivo tem {len(dados) / 1024 / 1024:.1f} MB e o limite é 20 MB.")

    try:
        import pandas as pd
    except ImportError as e:
        raise PlanilhaInvalida(
            "O servidor está sem a biblioteca de planilhas (pandas).") from e

    nome = (nome_arquivo or "").lower()
    avisos: list[str] = []
    try:
        if nome.endswith((".csv", ".txt")):
            # separador e encoding variam muito em export de ERP
            texto = None
            for enc in ("utf-8-sig", "latin-1"):
                try:
                    texto = dados.decode(enc)
                    break
                except UnicodeDecodeError:
                    continue
            if texto is None:
                raise PlanilhaInvalida("Não consegui ler o texto do arquivo.")
            sep = ";" if texto[:2000].count(";") > texto[:2000].count(",") else ","
            df = pd.read_csv(io.StringIO(texto), sep=sep, dtype=str,
                             keep_default_na=False)
            aba = "csv"
            abas_mapa = []
        else:
            # alguns geradores escrevem atributos que o openpyxl recusa
            # (ex.: defaultColWidthPt) — tenta os outros motores antes
            # de desistir do arquivo
            xl = None
            ultimo = None
            # calamine PRIMEIRO: e o mais tolerante a dialeto. O openpyxl
            # recusa arquivos com atributos que nao conhece (medido com um
            # export real que tinha defaultColWidthPt)
            for motor in ("calamine", None, "xlrd", "odf"):
                try:
                    xl = (pd.ExcelFile(io.BytesIO(dados)) if motor is None
                          else pd.ExcelFile(io.BytesIO(dados), engine=motor))
                    break
                except ImportError:
                    continue
                except Exception as e:
                    ultimo = e
                    continue
            if xl is None:
                raise PlanilhaInvalida(
                    "Nao consegui abrir esse arquivo — ele foi gerado por uma "
                    "ferramenta que usa um formato que eu nao leio. "
                    "Reabra no Excel e salve como 'Pasta de Trabalho do Excel "
                    "(.xlsx)' ou exporte em CSV."
                ) from ultimo
            # mapeia TODAS as abas e escolhe a de MAIS dados como principal.
            # Um arquivo de diretoria pode ter a primeira aba com 2 linhas de
            # resumo e a terceira com o detalhe que interessa.
            mapa, maior, maior_n = [], None, -1
            for nome_aba in xl.sheet_names:
                try:
                    d = xl.parse(nome_aba, dtype=str, keep_default_na=False)
                except Exception:
                    continue
                preenchidas = int((d.astype(str) != "").sum().sum()) if len(d) else 0
                mapa.append({"nome": nome_aba, "linhas": len(d),
                             "colunas": [str(c) for c in d.columns][:12]})
                if preenchidas > maior_n:
                    maior, maior_n, df = nome_aba, preenchidas, d
            if maior is None:
                raise PlanilhaInvalida("Nao consegui ler nenhuma aba do arquivo.")
            aba = maior
            if aba_escolhida:
                for a in mapa:
                    if normaliza_texto(a["nome"]) == normaliza_texto(aba_escolhida):
                        aba = a["nome"]
                        df = xl.parse(aba, dtype=str, keep_default_na=False)
                        break
            abas_mapa = mapa
            if len(xl.sheet_names) > 1:
                outras = [a["nome"] for a in mapa if a["nome"] != aba]
                avisos.append(
                    f"O arquivo tem {len(xl.sheet_names)} abas. Analisei "
                    f"'{aba}' (a com mais dados). As outras: "
                    f"{', '.join(outras[:6])}"
                    + (f" e mais {len(outras) - 6}" if len(outras) > 6 else "")
                    + ". Peca a aba pelo nome se quiser outra.")
    except PlanilhaInvalida:
        raise
    except Exception as e:
        raise PlanilhaInvalida(
            f"Não consegui abrir o arquivo ({type(e).__name__}). "
            f"Ele está em xlsx, xls ou csv?") from e

    if df.empty or not len(df.columns):
        raise PlanilhaInvalida("A planilha está sem dados.")

    if len(df) > MAX_LINHAS:
        avisos.append(
            f"A planilha tem {len(df):,} linhas e o limite é {MAX_LINHAS:,} — "
            f"li as primeiras {MAX_LINHAS:,}.".replace(",", "."))
        df = df.head(MAX_LINHAS)

    nomes, vistos = [], set()
    for i, orig in enumerate(df.columns):
        n = _limpa_cabecalho(orig, i)
        base, k = n, 2
        while n in vistos:
            n = f"{base}_{k}"
            k += 1
        vistos.add(n)
        nomes.append((n, str(orig)))

    linhas = []
    for _, r in df.iterrows():
        linhas.append({n: ("" if v is None else str(v).strip())
                       for (n, _o), v in zip(nomes, r.tolist())})

    colunas = []
    for n, orig in nomes:
        vals = [l[n] for l in linhas]
        preenchidas = sum(1 for v in vals if v)
        exemplos = [v for v in vals if v][:AMOSTRA]
        colunas.append(Coluna(n, orig, _tipo_da_coluna(vals),
                              preenchidas, exemplos))

    vazias = [c.nome for c in colunas if c.preenchidas == 0]
    if vazias:
        avisos.append(f"Colunas sem nenhum dado: {', '.join(vazias[:5])}.")

    return Planilha(colunas=colunas, linhas=linhas, aba=aba,
                    total=len(linhas), avisos=avisos,
                    abas=locals().get("abas_mapa") or [])


# ─── cruzamento ────────────────────────────────────────────────────────

def chaves_unicas(linhas: list[dict], coluna: str, como: str = "codigo") -> list[str]:
    """Valores distintos e normalizados de uma coluna, prontos para o IN."""
    norm = normaliza_codigo if como == "codigo" else normaliza_texto
    vistos, saida = set(), []
    for l in linhas:
        v = norm(l.get(coluna, ""))
        if v and v not in vistos:
            vistos.add(v)
            saida.append(v)
    return saida


def blocos(chaves: list[str], tamanho: int = CHUNK_ORACLE):
    """O Oracle recusa IN (...) com mais de 1000 itens."""
    for i in range(0, len(chaves), tamanho):
        yield chaves[i:i + tamanho]


def lista_sql(chaves: list[str], numerico: bool = True) -> str:
    """Formata para dentro do IN (...). Escapa aspas em texto."""
    if numerico and all(c.isdigit() for c in chaves):
        return ",".join(chaves)
    return ",".join("'" + c.replace("'", "''") + "'" for c in chaves)


def junta(linhas: list[dict], coluna: str, achados: dict[str, dict],
          como: str = "codigo") -> tuple[list[dict], list[str]]:
    """Acrescenta as colunas do Winthor em cada linha da planilha.

    Devolve (linhas_enriquecidas, chaves_que_nao_casaram).
    """
    norm = normaliza_codigo if como == "codigo" else normaliza_texto
    novas, faltantes = [], []
    for l in linhas:
        chave = norm(l.get(coluna, ""))
        extra = achados.get(chave)
        nova = dict(l)
        if extra:
            nova.update(extra)
        else:
            if chave and chave not in faltantes:
                faltantes.append(chave)
        novas.append(nova)
    return novas, faltantes
