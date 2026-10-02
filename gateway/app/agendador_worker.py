"""Worker do agendador — processo proprio (systemd: ebdia-agendador).

Separado do gateway de proposito: reiniciar o gateway (vigia de modelo,
deploy) nao derruba um job no meio, e um job pesado nao disputa o processo
que atende o chat.

  cd ~/projects/ebd-ia && python3 -m gateway.app.agendador_worker

Acorda a cada AGENDA_INTERVALO_S (30 s), reivindica os jobs vencidos e roda
ate AGENDA_PARALELO (2) ao mesmo tempo. Reivindicacao com SKIP LOCKED +
unique de janela: dois workers ao mesmo tempo nao duplicam nada.
"""
import asyncio
import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

GATEWAY_DIR = Path(__file__).resolve().parent.parent
ROOT = GATEWAY_DIR.parent
load_dotenv(GATEWAY_DIR / ".env")
load_dotenv(ROOT / "core" / ".env")
sys.path.insert(0, str(ROOT / "core"))
os.environ.setdefault("TZ", "America/Sao_Paulo")

from gateway.app import agendamentos, db  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("uvicorn.error")


async def main() -> None:
    await db.init_db()
    pool = db._pool_or_raise()
    intervalo = int(os.getenv("AGENDA_INTERVALO_S", "30"))
    trava = asyncio.Semaphore(int(os.getenv("AGENDA_PARALELO", "2")))
    rodando: set[asyncio.Task] = set()
    log.info("agendador: no ar (intervalo %ss)", intervalo)

    async def roda(job):
        async with trava:
            try:
                st = await agendamentos.executar(pool, job)
                log.info("agendador: #%s %s -> %s", job["id"], job["titulo"], st)
            except Exception:
                log.exception("agendador: #%s falhou fora do previsto", job["id"])

    while True:
        try:
            for job in await agendamentos.reivindicar(pool):
                t = asyncio.create_task(roda(job))
                rodando.add(t)
                t.add_done_callback(rodando.discard)
        except Exception:
            log.exception("agendador: falha ao ler a fila (tenta de novo no proximo ciclo)")
        await asyncio.sleep(intervalo)


if __name__ == "__main__":
    asyncio.run(main())
