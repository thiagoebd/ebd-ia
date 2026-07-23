"""
models.py — Modelos Pydantic compartilhados pelo servidor MCP.

Define o contrato padronizado de:
- UserContext: identificação + escopo do usuário fazendo a chamada
- ToolResponse: envelope padronizado de resposta de toda tool
- ToolError: erros estruturados

Versão: v0.1 (19/05/2026) — Fase 1 do MCP Oracle.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator


# ============================================================
# Contexto do usuário
# ============================================================

UserRole = Literal["vendedor", "gerente", "supervisor", "diretor", "admin"]


class UserContext(BaseModel):
    """
    Contexto do usuário que está fazendo a chamada.

    Origem:
    - Em homologação: hardcoded em app/acl.py
    - Em produção: lookup em EBD.FILIAL_ACL_CHATBOT
    """

    user_id: int | str = Field(..., description="ID único do usuário (PK da ACL)")
    nome: str = Field(..., description="Nome legível para logs/respostas")
    role: UserRole = Field(..., description="Perfil de acesso")
    codusur: int | None = Field(None, description="Código RCA no Winthor (None se não for vendedor)")

    # Lista expandida de CODFILIAL que o usuário pode acessar.
    # Já resolvida (regional → filiais) no momento da autenticação.
    allowed_filiais: list[str] = Field(
        ...,
        description="Lista de códigos de filial permitidos (ex: ['05'] ou ['10','13'])",
        min_length=1,
    )

    # Metadados de origem (canal, dispositivo)
    canal: Literal["whatsapp", "telegram", "web", "test"] | None = Field(
        None, description="Canal de origem da mensagem"
    )

    # Marcado na ORIGEM (onde o escopo e resolvido). True = visao Brasil.
    # O enforcement de filial le so este booleano e sai fora: custo zero
    # para quem enxerga tudo, que e a maioria.
    escopo_total: bool = Field(
        False, description="True quando o usuario enxerga todas as filiais"
    )

    @field_validator("allowed_filiais")
    @classmethod
    def validar_filiais(cls, v: list[str]) -> list[str]:
        """Valida que CODFILIAL é string de 2 dígitos."""
        for f in v:
            if not (isinstance(f, str) and len(f) == 2 and f.isdigit()):
                raise ValueError(
                    f"CODFILIAL inválido: '{f}'. Esperado string de 2 dígitos (ex: '05')."
                )
        return v

    def can_access_filial(self, codfilial: str) -> bool:
        """Retorna True se o usuário pode acessar a filial."""
        return codfilial in self.allowed_filiais

    def can_access_filiais(self, codfiliais: list[str]) -> bool:
        """Retorna True se o usuário pode acessar TODAS as filiais da lista."""
        return all(self.can_access_filial(f) for f in codfiliais)


# ============================================================
# Resposta padronizada de tool
# ============================================================

ToolStatus = Literal["ok", "error"]


class ToolError(BaseModel):
    """Detalhes estruturados de erro."""

    code: str = Field(..., description="Código de erro (ex: 'ORA-00904', 'ACCESS_DENIED', 'SQL_GUARD_VIOLATION')")
    message: str = Field(..., description="Mensagem legível para humano")
    details: dict[str, Any] | None = Field(None, description="Contexto adicional")


class ToolMetadata(BaseModel):
    """Metadados de auditoria de cada chamada."""

    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="ISO 8601 UTC do momento da resposta",
    )
    oracle_user: str = Field(default="EBD_LEITURA", description="Usuário Oracle utilizado")
    user_context: dict[str, Any] | None = Field(None, description="Snapshot do user_context (auditoria)")


class ToolResponse(BaseModel):
    """
    Envelope padronizado retornado por toda tool do MCP.

    Sempre tem os mesmos campos, garantindo contrato estável mesmo
    quando adicionarmos novas tools.
    """

    request_id: str = Field(
        default_factory=lambda: str(uuid4()),
        description="UUID v4 para correlacionar request com logs (tracing)",
    )
    tool: str = Field(..., description="Nome da tool executada (ex: 'oracle_query')")
    status: ToolStatus = Field(..., description="'ok' ou 'error'")
    elapsed_ms: float = Field(..., description="Latência em milissegundos")

    # Payload específico da tool (varia conforme a operação)
    result: dict[str, Any] | None = Field(None, description="Resultado bem-sucedido")
    error: ToolError | None = Field(None, description="Detalhes de erro se status=='error'")

    # Métricas opcionais (preenchidas conforme aplicável)
    rows_returned: int | None = Field(None, description="Quantas linhas retornadas (para query)")
    truncated: bool = Field(False, description="Resultado foi truncado por cap de linhas?")

    metadata: ToolMetadata = Field(default_factory=ToolMetadata)

    @classmethod
    def success(
        cls,
        tool: str,
        result: dict[str, Any],
        elapsed_ms: float,
        user_context: UserContext | None = None,
        rows_returned: int | None = None,
        truncated: bool = False,
    ) -> ToolResponse:
        """Constrói resposta de sucesso."""
        meta = ToolMetadata(
            user_context=user_context.model_dump() if user_context else None,
        )
        return cls(
            tool=tool,
            status="ok",
            elapsed_ms=elapsed_ms,
            result=result,
            rows_returned=rows_returned,
            truncated=truncated,
            metadata=meta,
        )

    @classmethod
    def failure(
        cls,
        tool: str,
        code: str,
        message: str,
        elapsed_ms: float,
        details: dict[str, Any] | None = None,
        user_context: UserContext | None = None,
    ) -> ToolResponse:
        """Constrói resposta de erro."""
        meta = ToolMetadata(
            user_context=user_context.model_dump() if user_context else None,
        )
        return cls(
            tool=tool,
            status="error",
            elapsed_ms=elapsed_ms,
            error=ToolError(code=code, message=message, details=details),
            metadata=meta,
        )
