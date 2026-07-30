#!/usr/bin/env python3
"""Instala a resiliencia do stack EBD.ia.

  sudo python3 instala_resiliencia.py            # instala e ativa
  sudo python3 instala_resiliencia.py --dry-run  # so mostra o que faria

O que faz:
  1. Corrige a unidade ebdia-gateway (log sem buffer, Restart=always,
     espera o Docker, e um ExecStartPre que aguarda o MCP responder)
  2. Instala ebdia-supervisor.service + .timer (verifica e conserta a cada 2 min)
  3. Garante docker e ebdia-gateway habilitados no boot
  4. Faz backup de qualquer unidade que substituir

NAO mexe em chave SSH, senha nem passphrase.
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

REPO = os.environ.get("EBDIA_REPO", "/home/thiago/projects/ebd-ia")
USUARIO = os.environ.get("EBDIA_USER", "thiago")
SYSTEMD = Path("/etc/systemd/system")
STAMP = time.strftime("%Y%m%d-%H%M%S")

GATEWAY = f"""[Unit]
Description=EBD.ia Gateway (FastAPI)
# o Docker precisa estar de pe ANTES: em 30/07/2026 o gateway subiu primeiro,
# travou esperando o Postgres/MCP e ficou 'active' sem responder
After=network-online.target docker.service
Wants=network-online.target docker.service
Requires=docker.service

[Service]
Type=simple
User={USUARIO}
WorkingDirectory={REPO}
# sem isto o log fica preso no buffer do Python e o arquivo aparece VAZIO
Environment=PYTHONUNBUFFERED=1
# espera o MCP ficar saudavel por ate 60s; nunca falha, so atrasa o start
ExecStartPre={REPO}/scripts/espera_mcp.sh 30 2
ExecStart=/usr/bin/python3 -m uvicorn gateway.app.main:app --host 0.0.0.0 --port 8000
# 'always' e nao 'on-failure': saida limpa tambem precisa religar
Restart=always
RestartSec=5
StandardOutput=append:{REPO}/logs/gateway/gateway.log
StandardError=append:{REPO}/logs/gateway/gateway.log

[Install]
WantedBy=multi-user.target
"""

SUPERVISOR = f"""[Unit]
Description=EBD.ia — supervisor do stack (verifica e conserta)
After=network-online.target docker.service
Wants=docker.service

[Service]
Type=oneshot
Environment=PYTHONUNBUFFERED=1
Environment=EBDIA_REPO={REPO}
WorkingDirectory={REPO}
ExecStart=/usr/bin/python3 {REPO}/scripts/ebdia_supervisor.py
StandardOutput=append:{REPO}/logs/gateway/supervisor.log
StandardError=append:{REPO}/logs/gateway/supervisor.log
"""

TIMER = """[Unit]
Description=EBD.ia — roda o supervisor a cada 2 minutos

[Timer]
# 90s depois do boot: da tempo do Docker terminar
OnBootSec=90s
OnUnitActiveSec=2min
AccuracySec=15s
Unit=ebdia-supervisor.service

[Install]
WantedBy=timers.target
"""


def sh(cmd, dry=False):
    if dry:
        print(f"    [dry-run] {' '.join(cmd)}")
        return 0, ""
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    return p.returncode, (p.stdout + p.stderr).strip()


def escreve(caminho: Path, conteudo: str, dry: bool) -> bool:
    atual = caminho.read_text(encoding="utf-8") if caminho.exists() else None
    if atual == conteudo:
        print(f"  JA OK   {caminho.name}")
        return False
    if dry:
        print(f"  [dry]   {caminho.name} seria "
              f"{'substituido' if atual else 'criado'}")
        return True
    if atual is not None:
        bak = caminho.with_suffix(caminho.suffix + f".bak-{STAMP}")
        shutil.copy2(caminho, bak)
        print(f"  BACKUP  {bak.name}")
    caminho.write_text(conteudo, encoding="utf-8")
    print(f"  ESCREVE {caminho.name}")
    return True


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    dry = args.dry_run

    if not dry and os.geteuid() != 0:
        print("Precisa de root: sudo python3 instala_resiliencia.py")
        return 1

    repo = Path(REPO)
    if not (repo / "gateway").is_dir():
        print(f"Repo nao encontrado em {REPO} — ajuste EBDIA_REPO.")
        return 1

    print(f">> repo={REPO}  usuario={USUARIO}\n")

    print(">> 1. diretorios de log e scripts")
    for d in (repo / "logs" / "gateway", repo / "scripts"):
        if not d.exists():
            if dry:
                print(f"  [dry]   criaria {d}")
            else:
                d.mkdir(parents=True, exist_ok=True)
                shutil.chown(d, USUARIO, USUARIO)
                print(f"  CRIA    {d}")
        else:
            print(f"  JA OK   {d}")

    faltando = [n for n in ("ebdia_supervisor.py", "espera_mcp.sh")
                if not (repo / "scripts" / n).exists()]
    if faltando:
        print(f"\nFALTA em {repo}/scripts/: {', '.join(faltando)}")
        return 1
    if not dry:
        for n in ("ebdia_supervisor.py", "espera_mcp.sh"):
            os.chmod(repo / "scripts" / n, 0o755)

    print("\n>> 2. unidades systemd")
    mudou = escreve(SYSTEMD / "ebdia-gateway.service", GATEWAY, dry)
    mudou |= escreve(SYSTEMD / "ebdia-supervisor.service", SUPERVISOR, dry)
    mudou |= escreve(SYSTEMD / "ebdia-supervisor.timer", TIMER, dry)

    print("\n>> 3. recarregar e habilitar")
    if mudou:
        sh(["systemctl", "daemon-reload"], dry)
    for unidade in ("docker", "ebdia-gateway", "ebdia-supervisor.timer"):
        rc, estado = sh(["systemctl", "is-enabled", unidade], dry)
        if dry:
            print(f"    [dry-run] habilitaria {unidade}")
            continue
        if estado != "enabled":
            sh(["systemctl", "enable", unidade])
            print(f"  HABILITA {unidade}")
        else:
            print(f"  JA OK    {unidade} enabled")

    print("\n>> 4. subir agora")
    if dry:
        print("    [dry-run] restart ebdia-gateway + start do timer")
    else:
        sh(["systemctl", "restart", "ebdia-gateway"])
        sh(["systemctl", "start", "ebdia-supervisor.timer"])
        time.sleep(10)
        for unidade in ("ebdia-gateway", "ebdia-supervisor.timer"):
            _, est = sh(["systemctl", "is-active", unidade])
            print(f"  {unidade}: {est}")
        rc, out = sh(["ss", "-ltn"])
        print(f"  porta 8000: {'ouvindo' if ':8000 ' in out else 'NAO OUVINDO'}")

    print("\n" + "=" * 62)
    print("pronto. para conferir:")
    print("  systemctl list-timers ebdia-supervisor.timer")
    print(f"  tail -20 {REPO}/logs/gateway/supervisor.log")
    print(f"  python3 {REPO}/scripts/ebdia_supervisor.py --check")
    print("=" * 62)
    return 0


if __name__ == "__main__":
    sys.exit(main())
