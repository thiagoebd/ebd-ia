"""Carrega e valida configuracao do core EBD.ia."""
from pathlib import Path
from dotenv import load_dotenv
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Carrega .env do mesmo dir deste arquivo (core/.env)
_ENV_PATH = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(_ENV_PATH)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=str(_ENV_PATH), extra="ignore")

    # Anthropic
    anthropic_api_key: str = Field(..., alias="ANTHROPIC_API_KEY")
    claude_model: str = Field("claude-opus-4-7", alias="CLAUDE_MODEL")

    # MCP Oracle
    mcp_oracle_url: str = Field(..., alias="MCP_ORACLE_URL")
    mcp_oracle_token: str = Field(..., alias="MCP_ORACLE_TOKEN")

    # Knowledge base
    kb_path: Path = Field(..., alias="EBD_IA_KB_PATH")
    repo_path: Path = Field(..., alias="EBD_IA_REPO_PATH")

    # Limites
    max_tokens: int = 4096
    max_iterations: int = 10  # cap de tool-use loop


settings = Settings()
