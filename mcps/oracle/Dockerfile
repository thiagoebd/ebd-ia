# syntax=docker/dockerfile:1.7
# ============================================================
# mcp-oracle — Servidor MCP read-only para Winthor (Oracle)
# Versão sem dependências apt para evitar bloqueio de firewall
# ============================================================

FROM python:3.12-slim AS runtime

# Metadados
LABEL org.opencontainers.image.title="EBD.ia MCP Oracle"
LABEL org.opencontainers.image.description="MCP server for read-only Winthor (Oracle) access"
LABEL org.opencontainers.image.vendor="EBD Grupo"
LABEL org.opencontainers.image.licenses="Proprietary"

# Variáveis de ambiente Python — práticas recomendadas
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONPATH=/app

# Timezone via env var (sem precisar de tzdata instalado)
ENV TZ=America/Sao_Paulo

# Diretório de trabalho
WORKDIR /app

# Copiar manifesto e instalar dependências (cache layer)
# Usamos pip do PyPI diretamente (já liberado no firewall)
COPY pyproject.toml ./
RUN pip install --no-cache-dir \
        "oracledb>=4.0.0,<5.0.0" \
        "python-dotenv>=1.0.0,<2.0.0"

# Copiar código da aplicação
COPY app/ ./app/

# Criar usuário não-root e ajustar permissões
RUN useradd --create-home --uid 1001 --shell /bin/bash mcpuser \
    && chown -R mcpuser:mcpuser /app

USER mcpuser

# Healthcheck — roda health_check.py periodicamente
HEALTHCHECK --interval=60s --timeout=30s --start-period=20s --retries=3 \
    CMD python -m app.scripts.health_check || exit 1

# Comando default: health check (vai mudar quando o servidor MCP estiver implementado)
CMD ["sleep", "infinity"]
