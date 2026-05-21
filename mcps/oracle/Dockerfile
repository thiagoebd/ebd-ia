# syntax=docker/dockerfile:1.7
# ============================================================
# mcp-oracle — Servidor MCP read-only para Winthor (Oracle)
# ============================================================

FROM python:3.12-slim AS runtime

LABEL org.opencontainers.image.title="EBD.ia MCP Oracle"
LABEL org.opencontainers.image.description="MCP server for read-only Winthor (Oracle) access"
LABEL org.opencontainers.image.vendor="EBD Grupo"
LABEL org.opencontainers.image.licenses="Proprietary"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONPATH=/app

ENV TZ=America/Sao_Paulo

WORKDIR /app

# Copia pyproject e instala TODAS as deps (nao so 2)
COPY pyproject.toml ./
RUN pip install --no-cache-dir \
        "oracledb>=4.0.0,<5.0.0" \
        "python-dotenv>=1.0.0,<2.0.0" \
        "mcp>=1.2.0,<2.0.0" \
        "uvicorn[standard]>=0.30.0,<1.0.0" \
        "httpx>=0.27.0,<1.0.0" \
        "structlog>=24.4.0,<25.0.0" \
        "pydantic>=2.0.0,<3.0.0"

COPY app/ ./app/

RUN useradd --create-home --uid 1001 --shell /bin/bash mcpuser \
    && chown -R mcpuser:mcpuser /app

USER mcpuser

HEALTHCHECK --interval=60s --timeout=30s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8989/health',timeout=5).status==200 else 1)" || exit 1

EXPOSE 8989

CMD ["python", "-m", "app.server"]
