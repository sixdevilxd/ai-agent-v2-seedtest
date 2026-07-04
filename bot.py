#!/usr/bin/env python3
"""
ai-agent-v2 — Telegram AI Agent bertenaga Google Gemini (via REST, ramah Termux).

Semua kemampuan (crypto realtime, analisa meme coin, rug/anti-whale, scanner new
pairs, riset web & sosmed) dijalankan lewat FUNCTION CALLING — jadi cukup ngobrol
natural, tanpa perlu command. Coding & reasoning adalah skill di system prompt.

Command yang tersisa hanya untuk UX dasar & akun: /start /help /reset /login /logout /github.
"""

import os
import asyncio
import logging
from collections import defaultdict, deque

from dotenv import load_dotenv
from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

import crypto
import gemini
import research
import github_auth as ghauth

# ----------------------------------------------------------------------------
# Konfigurasi
# ----------------------------------------------------------------------------
load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-1.5-flash")
GITHUB_CLIENT_ID = os.getenv("GITHUB_CLIENT_ID")
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


def _load_system_prompt() -> str:
    """Prioritas: env SYSTEM_PROMPT > file system_prompt.md (Fable 5) > default."""
    env_prompt = os.getenv("SYSTEM_PROMPT")
    if env_prompt:
        return env_prompt
    prompt_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "system_prompt.md")
    if os.path.exists(prompt_file):
        with open(prompt_file, encoding="utf-8") as f:
            return f.read()
    return "Kamu adalah ai-agent-v2, asisten AI yang ramah dan cerdas."


SYSTEM_PROMPT = _load_system_prompt()

# Riwayat percakapan (teks bersih) per chat_id.
history = defaultdict(lambda: deque(maxlen=MAX_HISTORY_TURNS * 2))

# Task scanner new-pairs yang sedang berjalan, per chat_id.
scan_tasks: dict[int, asyncio.Task] = {}


# ----------------------------------------------------------------------------
# Definisi TOOLS untuk Gemini function calling
# ----------------------------------------------------------------------------
TOOLS = [
    {
        "function_declarations": [
            {
                "name": "get_price",
                "description": "Harga realtime sebuah coin (CoinGecko): harga USD, market cap, volume 24 jam, perubahan 24 jam.",
                "parameters": {
                    "type": "object",
                    "properties": {"query": {"type": "string", "description": "nama atau simbol coin, mis. 'solana' atau 'BTC'"}},
                    "required": ["query"],
                },
            },
            {
                "name": "analyze_token",
                "description": "Ambil data on-chain lengkap sebuah token (DexScreener + RugCheck): harga, likuiditas, volume, umur, transaksi, sebaran holder (anti-whale), dan risiko rug. Pakai untuk analisa/Deep Research meme coin dari sebuah token address.",
                "parameters": {
                    "type": "object",
                    "properties": {"address": {"type": "string", "description": "token/contract address"}},
                    "required": ["address"],
                },
            },
            {
                "name": "rugcheck",
                "description": "Cek risiko rug & sebaran holder untuk token Solana (mint address): risk score, mint/freeze authority, LP locked, top holders.",
                "parameters": {
                    "type": "object",
                    "properties": {"mint": {"type": "string", "description": "mint address token Solana"}},
                    "required": ["mint"],
                },
            },
            {
                "name": "new_pairs",
                "description": "Daftar token/pair yang BARU launch di sebuah chain (default Solana), lengkap dengan umur, likuiditas, FDV, volume.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "network": {"type": "string", "description": "chain, default 'solana'"},
                        "limit": {"type": "integer", "description": "jumlah hasil, default 10"},
                    },
                },
            },
            {
                "name": "web_search",
                "description": "Cari informasi terkini di web (DuckDuckGo). Pakai untuk berita, harga, tren, fakta yang bisa berubah, atau entitas yang tidak dikenal.",
                "parameters": {
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                },
            },
            {
                "name": "fetch_url",
                "description": "Ambil isi teks sebuah halaman web dari URL tertentu.",
                "parameters": {
                    "type": "object",
                    "properties": {"url": {"type": "string"}},
                    "required": ["url"],
                },
            },
            {
                "name": "social_search",
                "description": "Riset media sosial (X/Twitter, Reddit, LinkedIn, Facebook) untuk sentimen/narasi/diskusi. platform: 'x', 'reddit', 'linkedin', 'facebook', atau 'all'.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "platform": {"type": "string"},
                        "query": {"type": "string"},
                    },
                    "required": ["platform", "query"],
                },
            },
            {
                "name": "start_scanner",
                "description": "Mulai memantau token new pairs dan mengirim otomatis ke chat ini setiap 5 detik. Pakai saat user minta pantau/scan new pairs terus-menerus.",
                "parameters": {
                    "type": "object",
                    "properties": {"network": {"type": "string", "description": "chain, default 'solana'"}},
                },
            },
            {
                "name": "stop_scanner",
                "description": "Hentikan pemantauan new pairs di chat ini.",
                "parameters": {"type": "object", "properties": {}},
            },
            {
                "name": "github_list_repos",
                "description": "Daftar repositori GitHub milik user (butuh user sudah /login).",
                "parameters": {"type": "object", "properties": {}},
            },
            {
                "name": "github_read_file",
                "description": "Baca isi sebuah file di repo GitHub user (butuh /login).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "owner": {"type": "string"},
                        "repo": {"type": "string"},
                        "path": {"type": "string", "description": "path file dalam repo"},
                        "branch": {"type": "string", "description": "opsional"},
                    },
                    "required": ["owner", "repo", "path"],
                },
            },
            {
                "name": "github_commit_file",
                "description": "Buat/ubah file di repo GitHub user lalu commit & push dalam satu langkah (butuh /login). Pakai untuk menulis kode ke repo.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "owner": {"type": "string"},
                        "repo": {"type": "string"},
                        "path": {"type": "string"},
                        "content": {"type": "string", "description": "isi lengkap file"},
                        "message": {"type": "string", "description": "pesan commit"},
                        "branch": {"type": "string", "description": "opsional, default branch repo"},
                    },
                    "required": ["owner", "repo", "path", "content", "message"],
                },
            },
            {
                "name": "github_create_repo",
                "description": "Buat repositori GitHub baru milik user (butuh /login).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "description": {"type": "string"},
                        "private": {"type": "boolean"},
                    },
                    "required": ["name"],
                },
            },
        ]
    }
]


# ----------------------------------------------------------------------------
# Util
# ----------------------------------------------------------------------------
async def _reply_long(update: Update, text: str) -> None:
    if not text:
        text = "(kosong)"
    for i in range(0, len(text), 4000):
        await update.message.reply_text(text[i : i + 4000], disable_web_page_preview=True)


# ----------------------------------------------------------------------------
# Scanner new pairs (tiap 5 detik)
# ----------------------------------------------------------------------------
def _fmt_pair(p: dict) -> str:
    line = (
        f"🚨 *NEW PAIR* — {p.get('name')}\n"
        f"`{p.get('address')}`\n"
        f"💧 Liq: {crypto.fmt_big(p.get('liq'))} | FDV: {crypto.fmt_big(p.get('fdv'))} | "
        f"Vol5m: {crypto.fmt_big(p.get('vol_m5'))}\n"
    )
    if p.get("address"):
        line += f"🔎 Ketik: analisa {p['address']}"
    return line


async def _scan_loop(context: ContextTypes.DEFAULT_TYPE, chat_id: int, network: str) -> None:
    seen: set[str] = set()
    first = True
    try:
        while True:
            try:
                pairs = await crypto.new_pairs(network=network, limit=15)
            except Exception:  # noqa: BLE001
                await asyncio.sleep(5)
                continue
            new = [p for p in pairs if p.get("id") and p["id"] not in seen]
            for p in pairs:
                if p.get("id"):
                    seen.add(p["id"])
            if first:
                first = False
                for p in pairs[:3]:
                    await context.bot.send_message(
                        chat_id, _fmt_pair(p), parse_mode="Markdown", disable_web_page_preview=True
                    )
            else:
                for p in new[:5]:
                    await context.bot.send_message(
                        chat_id, _fmt_pair(p), parse_mode="Markdown", disable_web_page_preview=True
                    )
            await asyncio.sleep(5)
    except asyncio.CancelledError:
        pass


def _start_scanner(context: ContextTypes.DEFAULT_TYPE, chat_id: int, network: str) -> str:
    if chat_id in scan_tasks and not scan_tasks[chat_id].done():
        return "Scanner sudah berjalan."
    scan_tasks[chat_id] = context.application.create_task(_scan_loop(context, chat_id, network))
    return f"Scanner new pairs ({network}) dimulai, refresh tiap 5 detik."


def _stop_scanner(chat_id: int) -> str:
    t = scan_tasks.pop(chat_id, None)
    if t and not t.done():
        t.cancel()
        return "Scanner dihentikan."
    return "Tidak ada scanner yang berjalan."


# ----------------------------------------------------------------------------
# Dispatcher tool
# ----------------------------------------------------------------------------
async def _dispatch(name: str, args: dict, context: ContextTypes.DEFAULT_TYPE, chat_id: int, user_id: int):
    try:
        if name == "get_price":
            return await crypto.get_price(args.get("query", "")) or {"error": "tidak ditemukan"}
        if name == "analyze_token":
            return await crypto.deep_research_facts(args.get("address", ""))
        if name == "rugcheck":
            rep = await crypto.rugcheck(args.get("mint", ""))
            return crypto.summarize_rug(rep) if rep else {"error": "token tidak ditemukan di RugCheck"}
        if name == "new_pairs":
            return await crypto.new_pairs(args.get("network", "solana") or "solana", int(args.get("limit", 10) or 10))
        if name == "web_search":
            return await research.web_search(args.get("query", ""), 6)
        if name == "fetch_url":
            return {"text": await research.fetch_url(args.get("url", ""))}
        if name == "social_search":
            plat = (args.get("platform") or "all").lower()
            q = args.get("query", "")
            if plat == "reddit":
                rd = await research.reddit_search(q, 6)
                if rd is not None:
                    return rd
            return await research.social_search(plat, q, 6)
        if name == "start_scanner":
            return _start_scanner(context, chat_id, args.get("network", "solana") or "solana")
        if name == "stop_scanner":
            return _stop_scanner(chat_id)

        # ---- GitHub (butuh token dari /login) ----
        if name.startswith("github_"):
            token = ghauth.get_token(user_id)
            if not token:
                return {"error": "Belum terhubung ke GitHub. Minta user ketik /login dulu."}
            if name == "github_list_repos":
                return await ghauth.list_repos(token)
            if name == "github_read_file":
                return await ghauth.read_file(token, args["owner"], args["repo"], args["path"], args.get("branch"))
            if name == "github_commit_file":
                return await ghauth.commit_file(
                    token, args["owner"], args["repo"], args["path"],
                    args["content"], args.get("message", "update via ai-agent-v2"), args.get("branch"),
                )
            if name == "github_create_repo":
                return await ghauth.create_repo(
                    token, args["name"], args.get("description", ""), bool(args.get("private", False))
                )

        return {"error": f"tool tidak dikenal: {name}"}
    except Exception as e:  # noqa: BLE001
        logger.exception("Tool %s error", name)
        return {"error": str(e)}


# ----------------------------------------------------------------------------
# Command dasar
# ----------------------------------------------------------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Halo! Aku *ai-agent-v2* 🤖\n\n"
        "Ngobrol natural aja, aku otomatis paham maksudmu. Contoh:\n"
        "• \"harga solana berapa?\"\n"
        "• \"analisa coin ini <address>\"\n"
        "• \"pantau new pairs tiap 5 detik\" (stop: \"stop scan\")\n"
        "• \"cari sentimen X soal bonk\"\n"
        "• \"buatin script Python download youtube\"\n"
        "• \"jelasin pros/cons layer 2 dengan reasoning\"\n\n"
        "Akun GitHub: /login • /github • /logout\n"
        "/reset - hapus ingatan • /help - bantuan",
        parse_mode="Markdown",
    )


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Aku ngerti bahasa natural — nggak perlu command untuk skill.\n\n"
        "Yang bisa kubantu: harga crypto realtime, analisa meme coin (narasi, "
        "potensi hype, rug check, anti-whale), scan new pairs tiap 5 detik, riset "
        "web & sosmed (X/Reddit/LinkedIn/Facebook), coding semua bahasa, dan reasoning mendalam.\n\n"
        "Command akun: /login /github /logout\n"
        "/reset — mulai percakapan baru"
    )


async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    history.pop(update.effective_chat.id, None)
    await update.message.reply_text("Ingatan percakapan sudah dihapus. Mulai dari awal ya! 🧹")


async def chat(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    user_text = update.message.text

    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)

    convo = history[chat_id]
    convo.append(gemini.user_msg(user_text))

    working = list(convo)  # salinan kerja (termasuk giliran tool)
    final_text = ""
    try:
        for _ in range(6):  # maksimal 6 putaran tool
            content = await gemini.call(GEMINI_API_KEY, GEMINI_MODEL, working, SYSTEM_PROMPT, tools=TOOLS)
            working.append(content)
            calls = gemini.extract_calls(content)
            if not calls:
                final_text = gemini.extract_text(content)
                break
            await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
            resp_parts = []
            for call in calls:
                result = await _dispatch(call.get("name", ""), call.get("args") or {}, context, chat_id, user_id)
                resp_parts.append(gemini.function_response(call.get("name", ""), result))
            working.append({"role": "user", "parts": resp_parts})
        else:
            final_text = final_text or "Maaf, terlalu banyak langkah. Coba perjelas permintaanmu."
    except Exception as e:  # noqa: BLE001
        logger.exception("chat error (tools)")
        # Jaring pengaman: jawab tanpa tools kalau function-calling bermasalah.
        try:
            final_text = await gemini.generate(GEMINI_API_KEY, GEMINI_MODEL, list(convo), SYSTEM_PROMPT)
            convo.append(gemini.model_msg(final_text))
            await _reply_long(update, final_text)
        except Exception as e2:  # noqa: BLE001
            logger.exception("chat error (fallback)")
            convo.pop()
            await update.message.reply_text(f"⚠️ Terjadi error: {e2}")
        return

    if not final_text:
        final_text = "(kosong)"
    convo.append(gemini.model_msg(final_text))
    await _reply_long(update, final_text)


# ----------------------------------------------------------------------------
# GitHub — /login, /logout, /github (OAuth Device Flow)
# ----------------------------------------------------------------------------
async def _finish_login(context: ContextTypes.DEFAULT_TYPE, chat_id: int, user_id: int, device: dict) -> None:
    res = await ghauth.poll_for_token(
        GITHUB_CLIENT_ID,
        device["device_code"],
        int(device.get("interval", 5)),
        int(device.get("expires_in", 900)),
    )
    if res.get("ok"):
        ghauth.set_token(user_id, res["token"])
        try:
            u = await ghauth.get_github_user(res["token"])
            name = u.get("login", "?")
            await context.bot.send_message(
                chat_id,
                f"✅ GitHub terhubung sebagai *{name}*!\nCek dengan /github, putuskan dengan /logout.",
                parse_mode="Markdown",
            )
        except Exception:  # noqa: BLE001
            await context.bot.send_message(chat_id, "✅ GitHub terhubung!")
    else:
        reasons = {"timeout": "waktu habis", "expired_token": "kode kadaluarsa", "access_denied": "akses ditolak"}
        await context.bot.send_message(
            chat_id, f"❌ Login gagal ({reasons.get(res.get('error'), res.get('error'))}). Coba /login lagi."
        )


async def login(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    if not GITHUB_CLIENT_ID:
        await update.message.reply_text(
            "⚠️ GITHUB_CLIENT_ID belum di-set di .env.\n"
            "Buat OAuth App di https://github.com/settings/developers, "
            "aktifkan *Enable Device Flow*, lalu isi GITHUB_CLIENT_ID di .env.",
            parse_mode="Markdown",
        )
        return
    if ghauth.get_token(user_id):
        await update.message.reply_text("Kamu sudah terhubung. /github untuk lihat, /logout untuk putuskan.")
        return
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
    try:
        device = await ghauth.start_device_flow(GITHUB_CLIENT_ID)
    except Exception as e:  # noqa: BLE001
        await update.message.reply_text(f"⚠️ Gagal memulai login: {e}")
        return
    await update.message.reply_text(
        "🔐 *Hubungkan GitHub:*\n\n"
        f"1. Buka: {device['verification_uri']}\n"
        f"2. Masukkan kode: `{device['user_code']}`\n\n"
        "Aku tunggu sampai kamu selesai mengizinkan (jangan tutup chat).",
        parse_mode="Markdown",
    )
    context.application.create_task(_finish_login(context, update.effective_chat.id, user_id, device))


async def logout(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    removed = ghauth.remove_token(update.effective_user.id)
    if removed:
        await update.message.reply_text("👋 GitHub sudah diputuskan dari bot.")
    else:
        await update.message.reply_text("Kamu belum terhubung ke GitHub. Pakai /login.")


async def github_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    token = ghauth.get_token(update.effective_user.id)
    if not token:
        await update.message.reply_text("Belum terhubung. Pakai /login untuk menghubungkan GitHub.")
        return
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
    try:
        u = await ghauth.get_github_user(token)
    except Exception as e:  # noqa: BLE001
        await update.message.reply_text(f"⚠️ Token tidak valid lagi ({e}). Coba /logout lalu /login ulang.")
        return
    await update.message.reply_text(
        f"🐙 *GitHub terhubung*\n"
        f"User: {u.get('login')}\n"
        f"Nama: {u.get('name') or '-'}\n"
        f"Public repos: {u.get('public_repos')}\n"
        f"Followers: {u.get('followers')}\n"
        f"Profil: {u.get('html_url')}",
        parse_mode="Markdown",
    )


# ----------------------------------------------------------------------------
def main() -> None:
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("reset", reset))
    app.add_handler(CommandHandler("login", login))
    app.add_handler(CommandHandler("logout", logout))
    app.add_handler(CommandHandler("github", github_cmd))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, chat))

    logger.info("ai-agent-v2 berjalan. Tekan Ctrl+C untuk berhenti.")
    # Python 3.14 (Termux) tidak lagi membuat event loop otomatis.
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
