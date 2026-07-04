#!/usr/bin/env python3
"""
ai-agent-v2 — Telegram AI Agent bertenaga Google Gemini.
Dibuat untuk berjalan di Termux (Android) atau server mana pun.

Cara pakai:
    1. Salin .env.example menjadi .env, lalu isi tokennya.
    2. pip install -r requirements.txt
    3. python bot.py
"""

import os
import logging
from collections import defaultdict, deque

from dotenv import load_dotenv
import google.generativeai as genai
from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# ----------------------------------------------------------------------------
# Konfigurasi
# ----------------------------------------------------------------------------
load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-1.5-flash")
SYSTEM_PROMPT = os.getenv(
    "SYSTEM_PROMPT",
    "Kamu adalah ai-agent-v2, asisten AI yang ramah, cerdas, dan menjawab "
    "dengan bahasa yang sama seperti yang dipakai pengguna. Jawab ringkas dan jelas.",
)
# Berapa banyak pasang pesan (user+bot) yang diingat per chat.
MAX_HISTORY_TURNS = int(os.getenv("MAX_HISTORY_TURNS", "12"))

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("ai-agent-v2")

if not TELEGRAM_BOT_TOKEN:
    raise SystemExit("ERROR: TELEGRAM_BOT_TOKEN belum diisi di .env")
if not GEMINI_API_KEY:
    raise SystemExit("ERROR: GEMINI_API_KEY belum diisi di .env")

genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel(
    model_name=GEMINI_MODEL,
    system_instruction=SYSTEM_PROMPT,
)

# Riwayat percakapan per chat_id (disimpan di memori).
# Format Gemini: [{"role": "user"/"model", "parts": [teks]}, ...]
history = defaultdict(lambda: deque(maxlen=MAX_HISTORY_TURNS * 2))


# ----------------------------------------------------------------------------
# Handlers
# ----------------------------------------------------------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Halo! Aku *ai-agent-v2* 🤖\n"
        "Kirim pesan apa saja dan aku akan menjawab.\n\n"
        "Perintah:\n"
        "/reset - hapus ingatan percakapan\n"
        "/help - bantuan",
        parse_mode="Markdown",
    )


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Cukup ketik pertanyaan atau perintahmu, aku akan balas.\n"
        "/reset untuk mulai percakapan baru."
    )


async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    history.pop(update.effective_chat.id, None)
    await update.message.reply_text("Ingatan percakapan sudah dihapus. Mulai dari awal ya! 🧹")


async def chat(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    user_text = update.message.text

    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)

    convo = history[chat_id]
    convo.append({"role": "user", "parts": [user_text]})

    try:
        response = model.generate_content(list(convo))
        reply = (response.text or "").strip() or "Maaf, aku tidak punya jawaban untuk itu."
    except Exception as e:  # noqa: BLE001
        logger.exception("Gemini error")
        reply = f"⚠️ Terjadi error saat memproses: {e}"
        # Jangan simpan giliran yang gagal.
        convo.pop()
        await update.message.reply_text(reply)
        return

    convo.append({"role": "model", "parts": [reply]})

    # Telegram batasi 4096 karakter per pesan.
    for i in range(0, len(reply), 4000):
        await update.message.reply_text(reply[i : i + 4000])


def main() -> None:
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("reset", reset))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, chat))

    logger.info("ai-agent-v2 berjalan. Tekan Ctrl+C untuk berhenti.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
