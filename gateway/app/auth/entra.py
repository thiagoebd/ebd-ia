"""Validação de token JWT do Microsoft Entra ID.

Estratégia:
- PyJWKClient cacheia as public keys do tenant por 1h (interno)
- jwt.decode valida: signature (RS256), audience, issuer, exp
- Retorna o payload (com oid, name, preferred_username, etc)

Cilada conhecida (documentada na página B.2 do roadmap):
  Se o frontend pedir scopes misturados (Graph + custom API), o Entra
  defaulta pro Graph e o aud volta como Graph. Solução: frontend pede
  SÓ o scope do nosso app — api://<client-id>/access_as_user.
"""
import os
from functools import lru_cache
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import jwt
from jwt import PyJWKClient

TENANT_ID = os.getenv("AZURE_TENANT_ID", "")
CLIENT_ID = os.getenv("AZURE_CLIENT_ID", "")

if not TENANT_ID or not CLIENT_ID:
    raise RuntimeError(
        "Variáveis AZURE_TENANT_ID e AZURE_CLIENT_ID devem estar no .env do gateway"
    )

# Endpoints derivados
# O Entra pode emitir token v1 (sts.windows.net) ou v2 (login.microsoftonline.com/v2.0)
# dependendo de accessTokenAcceptedVersion no manifest. Aceitamos AMBOS — a segurança
# vem da validação de assinatura + audience + expiração, não da string do issuer.
ISSUER_V2 = f"https://login.microsoftonline.com/{TENANT_ID}/v2.0"
ISSUER_V1 = f"https://sts.windows.net/{TENANT_ID}/"
VALID_ISSUERS = {ISSUER_V1, ISSUER_V2}
JWKS_URL = f"https://login.microsoftonline.com/{TENANT_ID}/discovery/v2.0/keys"

# AUDIENCE = Application ID URI definido em "Expose an API" no Entra portal
# (criado em 28/05/2026 como api://<client-id>)
AUDIENCE = f"api://{CLIENT_ID}"

security = HTTPBearer(description="JWT do Entra ID (Bearer)")


@lru_cache(maxsize=1)
def get_jwk_client() -> PyJWKClient:
    # PyJWKClient internamente cacheia as keys baixadas por 1h
    return PyJWKClient(JWKS_URL)


async def verify_token(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> dict:
    """Valida o JWT e retorna o payload (claims).
    
    Levanta HTTP 401 se inválido (assinatura, audience, issuer, expiração).
    """
    token = credentials.credentials
    try:
        signing_key = get_jwk_client().get_signing_key_from_jwt(token).key
        payload = jwt.decode(
            token,
            signing_key,
            algorithms=["RS256"],
            audience=AUDIENCE,
        )
        # Valida issuer manualmente contra v1 OU v2 do mesmo tenant
        if payload.get("iss") not in VALID_ISSUERS:
            raise jwt.InvalidIssuerError(payload.get("iss"))
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            detail="Token expirado",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except jwt.InvalidAudienceError:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            detail=f"Audience inválido (esperado {AUDIENCE})",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except jwt.InvalidIssuerError:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            detail=f"Issuer inválido (aceitos: v1 sts.windows.net ou v2 login.microsoftonline.com do tenant)",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except jwt.InvalidTokenError as e:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            detail=f"Token inválido: {e}",
            headers={"WWW-Authenticate": "Bearer"},
        )
