"""Bot Telegram — polling de updates e despacho pro adapter.

Roda como processo standalone (ou systemd service).
Lê TELEGRAM_BOT_TOKEN do .env do core.
"""
import asyncio
import os
import sys
import logging
from pathlib import Path

# Adiciona o core ao path pra poder importar app.*
CORE_DIR = Path(__file__).resolve().parents[2] / "core"
sys.path.insert(0, str(CORE_DIR))
os.chdir(CORE_DIR)  # importante pro .env e knowledge files

from dotenv import load_dotenv
load_dotenv(CORE_DIR / ".env")

from telegram import Update
from telegram.ext import Application, MessageHandler, CommandHandler, filters, ContextTypes
from telegram.constants import ChatAction

from app.adapters.telegram import handle_message

# Logging básico (structlog cospe no journald via systemd)
logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)
# Silencia o httpx (muito verboso)
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger("ebd-ia-telegram")


async def on_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler único pra qualquer mensagem (texto ou comando)."""
    msg = update.effective_message
    chat = update.effective_chat
    user = update.effective_user

    if not msg or not msg.text or not chat or not user:
        return

    chat_id = chat.id
    user_name = user.first_name or "Usuário"
    text = msg.text

    logger.info(f"📩 [{chat_id}] {user_name}: {text[:80]}")

    # "Digitando..." enquanto processa
    try:
        await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
    except Exception:
        pass

    try:
        responses = await handle_message(chat_id, user_name, text)
    except Exception as e:
        logger.exception(f"Erro processando msg de {chat_id}: {e}")
        await msg.reply_text(f"❌ Erro interno: {str(e)[:200]}")
        return

    for chunk in responses:
        try:
            # Tenta Markdown primeiro, cai pro texto puro se quebrar
            await msg.reply_text(chunk, parse_mode="Markdown", disable_web_page_preview=True)
        except Exception as e:
            logger.warning(f"Markdown falhou ({e}), enviando texto puro")
            try:
                await msg.reply_text(chunk[:4096], disable_web_page_preview=True)
            except Exception as e2:
                logger.error(f"Falha total ao responder: {e2}")


def main():
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    if not token:
        logger.error("TELEGRAM_BOT_TOKEN não configurado no .env")
        sys.exit(1)

    admin_ids = os.environ.get("ADMIN_CHAT_IDS", "")
    logger.info(f"🤖 EBD.ia Telegram bot iniciando... admins={admin_ids}")

    app = Application.builder().token(token).build()
    # Handler único pra todas as mensagens de texto (inclui comandos)
    app.add_handler(MessageHandler(filters.TEXT, on_message))

    logger.info("✅ Polling iniciado. Aguardando mensagens...")
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)


if __name__ == "__main__":
    main()
