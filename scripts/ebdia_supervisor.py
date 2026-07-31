#!/usr/bin/env python3
"""Supervisor do stack EBD.ia.

Verifica cada componente e conserta o que estiver fora. Feito para rodar por
timer do systemd a cada 2 minutos, e tambem na mao quando algo cai.

  python3 scripts/ebdia_supervisor.py            # verifica e conserta
  python3 scripts/ebdia_supervisor.py --dry-run  # so diz o que faria
  python3 scripts/ebdia_supervisor.py --check    # so verifica, sai 1 se algo fora

Por que existe: em 30/07/2026 o servidor reiniciou, o gateway subiu ANTES do
Docker terminar, travou no startup esperando conexao, e o systemd o marcou como
'active' porque o processo estava vivo. Ninguem percebeu porque o Python
bufferiza o log. Depois ficou 'inactive (dead)' e Restart=on-failure nao religa
saida limpa.

NAO lida com senha, passphrase nem credencial. Se algo exigir segredo, o
supervisor apenas REPORTA e para.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field

REPO = os.environ.get("EBDIA_REPO", "/home/thiago/projects/ebd-ia")
CONTAINERS = ("ebdia_postgres", "ebdia_redis", "ebdia_mcp_oracle")
UNIDADE_GATEWAY = "ebdia-gateway"
UNIDADE_TELEGRAM = "ebdia-telegram"
URL_GATEWAY = "http://127.0.0.1:8000/health"
ESPERA_APOS_ACAO = 8


# ------------------------------------------------------------------
# utilidades
# ------------------------------------------------------------------
def sh(cmd: list[str], timeout: int = 60) -> tuple[int, str]:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return p.returncode, (p.stdout + p.stderr).strip()
    except subprocess.TimeoutExpired:
        return 124, f"timeout apos {timeout}s"
    except FileNotFoundError:
        return 127, f"comando nao encontrado: {cmd[0]}"


def http_ok(url: str, timeout: int = 10) -> tuple[bool, str]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return 200 <= r.status < 300, f"HTTP {r.status}"
    except urllib.error.HTTPError as e:
        return False, f"HTTP {e.code}"
    except Exception as e:
        return False, type(e).__name__


def porta_ouvindo(porta: int) -> bool:
    rc, out = sh(["ss", "-ltn"], timeout=10)
    return rc == 0 and f":{porta} " in out


# ------------------------------------------------------------------
# resultado de cada checagem
# ------------------------------------------------------------------
@dataclass
class Resultado:
    nome: str
    ok: bool
    detalhe: str = ""
    consertado: bool = False
    acoes: list[str] = field(default_factory=list)


# ------------------------------------------------------------------
# checagens
# ------------------------------------------------------------------
def checa_docker(consertar: bool) -> Resultado:
    rc, estado = sh(["systemctl", "is-active", "docker"], timeout=15)
    if estado == "active":
        return Resultado("docker", True, "active")
    if not consertar:
        return Resultado("docker", False, estado)
    sh(["sudo", "-n", "systemctl", "start", "docker"], timeout=60)
    time.sleep(ESPERA_APOS_ACAO)
    _, estado2 = sh(["systemctl", "is-active", "docker"], timeout=15)
    ok = estado2 == "active"
    return Resultado("docker", ok, estado2, consertado=ok,
                     acoes=["systemctl start docker"])


def _estado_container(nome: str) -> tuple[bool, str]:
    rc, out = sh(["docker", "inspect", "-f",
                  "{{.State.Status}}|{{if .State.Health}}{{.State.Health.Status}}"
                  "{{else}}sem-health{{end}}", nome], timeout=20)
    if rc != 0:
        return False, "nao existe"
    status, saude = (out.split("|") + ["?"])[:2]
    ok = status == "running" and saude in ("healthy", "sem-health")
    return ok, f"{status}/{saude}"


def checa_containers(consertar: bool) -> list[Resultado]:
    fora = []
    res = []
    for nome in CONTAINERS:
        ok, det = _estado_container(nome)
        if ok:
            res.append(Resultado(nome, True, det))
        else:
            fora.append(nome)
            res.append(Resultado(nome, False, det))
    if fora and consertar:
        sh(["docker", "compose", "up", "-d"], timeout=300)
        time.sleep(25)
        res = []
        for nome in CONTAINERS:
            ok, det = _estado_container(nome)
            res.append(Resultado(nome, ok, det, consertado=ok,
                                 acoes=["docker compose up -d"] if ok else []))
    return res


def checa_gateway(consertar: bool) -> Resultado:
    _, estado = sh(["systemctl", "is-active", UNIDADE_GATEWAY], timeout=15)
    ouvindo = porta_ouvindo(8000)
    respondendo, det_http = http_ok(URL_GATEWAY)

    if estado == "active" and ouvindo and respondendo:
        return Resultado("gateway", True, f"{estado}, porta 8000, {det_http}")

    detalhe = (f"systemd={estado} porta8000={'sim' if ouvindo else 'nao'} "
               f"http={det_http}")
    if not consertar:
        return Resultado("gateway", False, detalhe)

    # 'active' mas sem responder = travado no startup: restart, nao start
    acao = "restart" if estado == "active" else "start"
    sh(["sudo", "-n", "systemctl", acao, UNIDADE_GATEWAY], timeout=90)
    time.sleep(ESPERA_APOS_ACAO)

    _, estado2 = sh(["systemctl", "is-active", UNIDADE_GATEWAY], timeout=15)
    ok2, det2 = http_ok(URL_GATEWAY)
    ok = estado2 == "active" and ok2
    return Resultado("gateway", ok, f"{estado2}, {det2}", consertado=ok,
                     acoes=[f"systemctl {acao} {UNIDADE_GATEWAY}"])


def checa_telegram(consertar: bool) -> Resultado:
    """O bot faz polling: nao tem porta. Vale unidade ativa + processo vivo."""
    rc_u, estado = sh(["systemctl", "is-active", UNIDADE_TELEGRAM], timeout=15)
    if "could not be found" in estado or estado == "inactive" and rc_u == 4:
        return Resultado("telegram", True, "unidade nao instalada (ignorado)")
    rc_p, _ = sh(["pgrep", "-f", "telegram_bot/main.py"], timeout=10)
    vivo = rc_p == 0
    if estado == "active" and vivo:
        return Resultado("telegram", True, "active, processo vivo")
    detalhe = f"systemd={estado} processo={'vivo' if vivo else 'morto'}"
    if not consertar:
        return Resultado("telegram", False, detalhe)
    acao = "restart" if estado == "active" else "start"
    sh(["sudo", "-n", "systemctl", acao, UNIDADE_TELEGRAM], timeout=90)
    time.sleep(ESPERA_APOS_ACAO)
    _, estado2 = sh(["systemctl", "is-active", UNIDADE_TELEGRAM], timeout=15)
    rc_p2, _ = sh(["pgrep", "-f", "telegram_bot/main.py"], timeout=10)
    ok = estado2 == "active" and rc_p2 == 0
    return Resultado("telegram", ok, f"{estado2}, processo "
                     f"{'vivo' if rc_p2 == 0 else 'morto'}", consertado=ok,
                     acoes=[f"systemctl {acao} {UNIDADE_TELEGRAM}"])


def checa_nginx(consertar: bool) -> Resultado:
    if not shutil.which("nginx"):
        return Resultado("nginx", True, "nao instalado (ignorado)")
    _, estado = sh(["systemctl", "is-active", "nginx"], timeout=15)
    if estado == "active":
        return Resultado("nginx", True, "active")
    if not consertar:
        return Resultado("nginx", False, estado)
    sh(["sudo", "-n", "systemctl", "start", "nginx"], timeout=60)
    time.sleep(3)
    _, estado2 = sh(["systemctl", "is-active", "nginx"], timeout=15)
    ok = estado2 == "active"
    return Resultado("nginx", ok, estado2, consertado=ok,
                     acoes=["systemctl start nginx"])


def checa_disco_memoria() -> list[Resultado]:
    res = []
    rc, out = sh(["df", "-P", "/"], timeout=10)
    if rc == 0 and len(out.splitlines()) > 1:
        pct = out.splitlines()[1].split()[4].rstrip("%")
        try:
            uso = int(pct)
            res.append(Resultado("disco /", uso < 90, f"{uso}% usado"))
        except ValueError:
            pass
    try:
        with open("/proc/meminfo") as f:
            info = {l.split(":")[0]: int(l.split()[1]) for l in f if ":" in l}
        livre_pct = 100 * info.get("MemAvailable", 0) / max(info.get("MemTotal", 1), 1)
        res.append(Resultado("memoria", livre_pct > 10,
                             f"{livre_pct:.0f}% disponivel"))
    except Exception:
        pass
    return res


# ------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser(description="Supervisor do stack EBD.ia")
    ap.add_argument("--dry-run", action="store_true", help="so diz o que faria")
    ap.add_argument("--check", action="store_true", help="so verifica, nao conserta")
    ap.add_argument("--json", action="store_true", help="saida em JSON")
    args = ap.parse_args()
    consertar = not (args.dry_run or args.check)

    os.chdir(REPO)
    res: list[Resultado] = []

    r_docker = checa_docker(consertar)
    res.append(r_docker)
    if r_docker.ok:
        res.extend(checa_containers(consertar))
    res.append(checa_gateway(consertar))
    res.append(checa_telegram(consertar))
    res.append(checa_nginx(consertar))
    res.extend(checa_disco_memoria())

    fora = [r for r in res if not r.ok]
    consertados = [r for r in res if r.consertado]

    if args.json:
        print(json.dumps([r.__dict__ for r in res], ensure_ascii=False))
    else:
        agora = time.strftime("%d/%m/%Y %H:%M:%S")
        modo = "DRY-RUN" if args.dry_run else ("CHECK" if args.check else "ATIVO")
        print(f"[{agora}] supervisor EBD.ia — modo {modo}")
        for r in res:
            marca = "OK  " if r.ok else "FORA"
            extra = "  (consertado)" if r.consertado else ""
            print(f"  {marca}  {r.nome:<18} {r.detalhe}{extra}")
        if consertados:
            print(f"\n  consertados: {', '.join(r.nome for r in consertados)}")
        if fora:
            print(f"  AINDA FORA: {', '.join(r.nome for r in fora)}")

    return 1 if fora else 0


if __name__ == "__main__":
    sys.exit(main())
