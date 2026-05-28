"""Endpoint /api/me — retorna identidade do usuário logado.

Primeira parada do frontend após login bem-sucedido. Devolve:
- claims do token Entra (oid, nome, email)
- (futuro) escopo da ACL pra essa pessoa

Por enquanto, ACL não está integrada — só retorna os claims crus.
Próximo passo (Semana 3): consultar FILIAL_ACL_CHATBOT por oid.
"""
from fastapi import APIRouter, Depends
from gateway.app.auth.entra import verify_token

router = APIRouter()


@router.get("/me")
async def get_me(claims: dict = Depends(verify_token)):
    return {
        "oid": claims.get("oid"),
        "name": claims.get("name"),
        "email": claims.get("preferred_username") or claims.get("email"),
        "tenant_id": claims.get("tid"),
        # TODO Semana 3: integrar ACL
        "acl": {
            "ativo": False,
            "escopo": None,
            "filiais": [],
            "msg": "ACL ainda não configurada — Semana 3 do roadmap",
        },
        # raw debug (remover em produção depois)
        "_claims_raw": claims,
    }
