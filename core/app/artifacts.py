"""Helpers de artefatos — usados pelas tools create_excel, create_pdf, create_pptx.

Padroniza:
  - Pasta de armazenamento (/var/ebd-ia/artifacts/)
  - Nome de arquivo seguro
  - Identidade visual EBD (logo, cores, fontes)
"""
import re
import uuid
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ARTIFACTS_DIR = Path("/var/ebd-ia/artifacts")
ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)

LOGO_PATH = Path(__file__).resolve().parents[2] / "frontend" / "public" / "logo-ebd.png"

# Identidade visual EBD
EBD_NAVY = "#1c2c5e"      # cor primária
EBD_RED = "#c1272d"       # cor do logo (vermelho EBD)
EBD_GRAY_BG = "#f5f5f0"   # fundo creme do mockup
EBD_GRAY_LINE = "#e5e5e0"
EBD_FONT_SANS = "Calibri" # corporate sans pra Excel/PPT
EBD_FONT_SERIF = "Georgia"  # backup; padrao sans


def safe_filename(title: str, ext: str) -> str:
    """Converte 'Top 10 Filiais MTD' em 'top-10-filiais-mtd.xlsx'."""
    base = re.sub(r"[^\w\s-]", "", title.lower()).strip()
    base = re.sub(r"[-\s]+", "-", base)[:60] or "artefato"
    return f"{base}.{ext.lstrip('.')}"


def new_artifact_path(ext: str) -> tuple[str, Path]:
    """Gera (id_uuid, path) único para um novo artefato."""
    art_id = str(uuid.uuid4())
    path = ARTIFACTS_DIR / f"{art_id}.{ext.lstrip('.')}"
    return art_id, path


def now_br() -> datetime:
    return datetime.now(ZoneInfo("America/Sao_Paulo"))


def now_br_str() -> str:
    return now_br().strftime("%d/%m/%Y %H:%M")
