"""Fixar conversa: fica fora da rotacao e so sai por desafixar ou apagar.

Demanda do time (29/09/2026): manter 8 conversas em vez de 5 e permitir
fixar uma conversa especifica para ela nunca ser sobrescrita.
"""
from conftest import RAIZ


def _fonte(rel: str) -> str:
    return (RAIZ / rel).read_text(encoding="utf-8")


DB = _fonte("gateway/app/db.py")
ROTA = _fonte("gateway/app/routes/conversations.py")
FRONT = _fonte("frontend/src/App.tsx")


# ─── schema e limites ───

def test_coluna_pinned_criada_de_forma_idempotente():
    """O SCHEMA_SQL roda a cada boot — ADD COLUMN precisa de IF NOT EXISTS."""
    assert "ADD COLUMN IF NOT EXISTS pinned" in DB
    assert "ADD COLUMN IF NOT EXISTS pinned_at" in DB


def test_limite_padrao_e_8():
    assert 'os.getenv("MAX_CONVERSATIONS_PER_USER", "8")' in DB


def test_tem_teto_de_fixadas():
    """Sem teto, conversa e planilha anexada acumulam para sempre."""
    assert "MAX_PINNED_PER_USER" in DB
    assert "class LimiteFixadas" in DB


# ─── a rotacao ───

def test_rotacao_nao_apaga_fixada():
    i = DB.index("async def _enforce_conversation_cap")
    bloco = DB[i:i + 1400]
    assert bloco.count("pinned = false") == 2, \
        "o DELETE e a subconsulta dos mantidos precisam ignorar as fixadas"


def test_fixar_nao_reordena():
    """Fixar nao pode mexer em updated_at — senao a conversa pula para o topo."""
    i = DB.index("async def set_pinned")
    bloco = DB[i:i + 1800]
    assert "updated_at = now()" not in bloco


def test_fixar_confere_o_dono():
    i = DB.index("async def set_pinned")
    assert "user_oid = $2" in DB[i:i + 1800]


def test_listagem_poe_fixadas_primeiro():
    assert "ORDER BY pinned DESC, updated_at DESC" in DB


# ─── rota ───

def test_rota_patch_existe():
    assert '@router.patch("/conversations/{conv_id}")' in ROTA


def test_rota_devolve_409_no_limite():
    assert "status_code=409" in ROTA


def test_rota_valida_uuid():
    """UUID invalido virava erro 500 do asyncpg."""
    i = ROTA.index("async def pin_conv")
    assert "uuid.UUID(conv_id)" in ROTA[i:i + 600]


def test_listagem_devolve_pinned():
    assert '"pinned": bool(c.get("pinned"))' in ROTA


# ─── frontend ───

def test_front_tem_botao_de_fixar():
    assert "thread-pin" in FRONT and "togglePin" in FRONT


def test_front_desfaz_se_o_servidor_recusar():
    i = FRONT.index("async function togglePin")
    bloco = FRONT[i:i + 1500]
    assert "pinned: !novo" in bloco, "otimista sem rollback deixa a tela mentindo"


def test_front_separa_fixadas_e_recentes():
    assert "Fixadas" in FRONT and "Recentes" in FRONT


def test_front_nao_fixa_conversa_ainda_nao_criada():
    """Conversa tmp- ainda nao existe no banco — PATCH daria 404."""
    i = FRONT.index("async function togglePin")
    assert 'id.startsWith("tmp-")' in FRONT[i:i + 400]
