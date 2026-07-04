#!/usr/bin/env python3
"""
ai-agent-v2 — Telegram AI Agent bertenaga Google Gemini (via REST, ramah Termux).

Cara pakai:
    1. Salin .env.example menjadi .env, lalu isi tokennya.
    2. pip install -r requirements.txt
    3. python bot.py
"""

import os
import json
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
    return (
        "Kamu adalah ai-agent-v2, asisten AI yang ramah, cerdas, dan menjawab "
        "dengan bahasa yang sama seperti yang dipakai pengguna. Jawab ringkas dan jelas."
    )


SYSTEM_PROMPT = _load_system_prompt()

# Riwayat percakapan per chat_id (format REST Gemini).
history = defaultdict(lambda: deque(maxlen=MAX_HISTORY_TURNS * 2))

# Task scanner new-pairs yang sedang berjalan, per chat_id.
scan_tasks: dict[int, asyncio.Task] = {}


# ----------------------------------------------------------------------------
# Util
# ----------------------------------------------------------------------------
async def _reply_long(update: Update, text: str) -> None:
    if not text:
        text = "(kosong)"
    for i in range(0, len(text), 4000):
        await update.message.reply_text(text[i : i + 4000], disable_web_page_preview=True)


async def _ask_gemini(contents: list[dict]) -> str:
    return await gemini.generate(GEMINI_API_KEY, GEMINI_MODEL, contents, SYSTEM_PROMPT)


# ----------------------------------------------------------------------------
# Perintah dasar
# ----------------------------------------------------------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Halo! Aku *ai-agent-v2* 🤖\n"
        "Kirim pesan apa saja untuk ngobrol, atau pakai perintah crypto:\n\n"
        "💵 /price <coin> - harga realtime (CoinGecko)\n"
        "🆕 /new - meme coin baru terdeteksi\n"
        "🛡️ /rug <mint> - cek rug + sebaran holder (Solana)\n"
        "🔬 /analyze <address> - *Deep Research Pro* (narasi, hype, rug, anti-whale)\n"
        "📡 /scan - scan new pairs tiap 5 detik | /stopscan\n\n"
        "🧠 /reason <soal> - analisis mendalam\n"
        "💻 /code <tugas> - coding semua bahasa\n"
        "🌐 /research <topik> - riset web\n"
        "📱 /social [x|reddit|linkedin|facebook] <topik> - riset sosmed\n\n"
        "🔐 /login - hubungkan akun GitHub\n"
        "🐙 /github - lihat akun GitHub terhubung\n"
        "🚪 /logout - putuskan GitHub\n\n"
        "/reset - hapus ingatan percakapan\n"
        "/help - bantuan",
        parse_mode="Markdown",
    )


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Ketik apa saja untuk ngobrol. Perintah crypto:\n"
        "/price <coin> — harga realtime\n"
        "/new — meme coin baru\n"
        "/rug <mint> — rug check (Solana)\n"
        "/analyze <address> — Deep Research Pro\n"
        "/scan — new pairs tiap 5 detik | /stopscan\n"
        "/reason <soal> — analisis mendalam\n"
        "/code <tugas> — coding semua bahasa\n"
        "/research <topik> — riset web\n"
        "/social <topik> — riset sosmed (x/reddit/linkedin/facebook)\n"
        "/login — hubungkan GitHub\n"
        "/github — akun GitHub terhubung\n"
        "/logout — putuskan GitHub\n"
        "/reset — mulai percakapan baru"
    )


async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    history.pop(update.effective_chat.id, None)
    await update.message.reply_text("Ingatan percakapan sudah dihapus. Mulai dari awal ya! 🧹")


async def chat(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    user_text = update.message.text

    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)

    convo = history[chat_id]
    convo.append(gemini.user_msg(user_text))

    try:
        reply = await _ask_gemini(list(convo))
    except Exception as e:  # noqa: BLE001
        logger.exception("Gemini error")
        convo.pop()  # jangan simpan giliran yang gagal
        await update.message.reply_text(f"⚠️ Terjadi error: {e}")
        return

    convo.append(gemini.model_msg(reply))
    await _reply_long(update, reply)


# ----------------------------------------------------------------------------
# Perintah crypto
# ----------------------------------------------------------------------------
async def price(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text("Format: /price <nama/simbol coin>\nContoh: /price solana")
        return
    query = " ".join(context.args)
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
    try:
        d = await crypto.get_price(query)
    except Exception as e:  # noqa: BLE001
        await update.message.reply_text(f"⚠️ Gagal ambil harga: {e}")
        return
    if not d or d.get("price") is None:
        await update.message.reply_text(f"Coin '{query}' tidak ditemukan di CoinGecko.")
        return
    ch = d.get("change24") or 0
    arrow = "🟢" if ch >= 0 else "🔴"
    rank = f" (rank #{d['rank']})" if d.get("rank") else ""
    await update.message.reply_text(
        f"*{d['name']}* ({d['symbol']}){rank}\n"
        f"💵 Harga: {crypto.fmt_usd(d['price'])}\n"
        f"{arrow} 24j: {ch:+.2f}%\n"
        f"📊 Market cap: {crypto.fmt_big(d['market_cap'])}\n"
        f"🔁 Vol 24j: {crypto.fmt_big(d['vol24'])}",
        parse_mode="Markdown",
    )


async def new_meme(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
    try:
        tokens = await crypto.new_meme_tokens(8)
    except Exception as e:  # noqa: BLE001
        await update.message.reply_text(f"⚠️ Gagal ambil token baru: {e}")
        return
    if not tokens:
        await update.message.reply_text("Belum ada token baru terdeteksi.")
        return
    lines = ["🆕 *Token baru terdeteksi (DexScreener):*\n"]
    for t in tokens:
        desc = (t["description"] or "").replace("\n", " ")[:60]
        lines.append(f"• `{t['address']}` ({t['chain']})\n  {desc}")
    lines.append("\nAnalisa mendalam: /analyze <address>")
    await _reply_long(update, "\n".join(lines))


async def rug(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text("Format: /rug <mint address Solana>")
        return
    mint = context.args[0]
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
    try:
        report = await crypto.rugcheck(mint)
    except Exception as e:  # noqa: BLE001
        await update.message.reply_text(f"⚠️ Gagal rugcheck: {e}")
        return
    if not report:
        await update.message.reply_text("Token tidak ditemukan di RugCheck (khusus Solana).")
        return
    s = crypto.summarize_rug(report)
    risks = "\n".join(f"• {r['name']} ({r['level']})" for r in s.get("risks", [])[:6]) or "• tidak ada flag"
    await _reply_long(
        update,
        f"🛡️ *RugCheck*\n"
        f"Risk score: {s.get('score')} (makin tinggi makin berisiko)\n"
        f"Total holder: {s.get('total_holders')}\n"
        f"Top 1 holder: {s.get('top1_pct')}%\n"
        f"Top 10 holder: {s.get('top10_pct')}%\n"
        f"LP locked: {s.get('lp_locked_pct')}%\n"
        f"Mint authority: {'AKTIF ⚠️' if s.get('mint_authority') else 'revoked ✅'}\n"
        f"Freeze authority: {'AKTIF ⚠️' if s.get('freeze_authority') else 'revoked ✅'}\n\n"
        f"*Flags:*\n{risks}",
    )


# ----------------------------------------------------------------------------
# Deep Research Pro
# ----------------------------------------------------------------------------
DEEP_RESEARCH_INSTRUCTION = (
    "Kamu analis crypto meme coin. Berdasarkan DATA on-chain di bawah (fakta nyata, "
    "jangan mengarang angka), buat analisa ringkas dalam Bahasa Indonesia dengan format:\n"
    "📊 Ringkasan (nama, chain, harga, umur, likuiditas, mcap)\n"
    "🎯 Narasi & Angle — usulkan narasi/marketing yang bagus & catchy untuk coin ini\n"
    "🔥 Potensi Hype — nilai momentum (volume, txns, perubahan harga) skala 1-10 + alasan\n"
    "🛡️ Rug Check — nilai risiko rug dari mint/freeze authority, LP locked, risk score\n"
    "🐋 Anti-Whale — evaluasi konsentrasi holder (top1 & top10); tandai bahaya jika >20% di 1 wallet atau >50% di top10\n"
    "⚖️ Verdict — kesimpulan singkat + level risiko (RENDAH/SEDANG/TINGGI)\n\n"
    "Akhiri dengan '⚠️ Bukan nasihat keuangan (NFA). DYOR.' "
    "Jawab padat, pakai bullet seperlunya, jangan bertele-tele."
)


async def analyze(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text(
            "Format: /analyze <token address>\n"
            "Contoh (Solana): /analyze DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263"
        )
        return
    address = context.args[0]
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
    await update.message.reply_text("🔍 Deep Research Pro sedang menganalisa... (5-15 detik)")
    try:
        facts = await crypto.deep_research_facts(address)
    except Exception as e:  # noqa: BLE001
        await update.message.reply_text(f"⚠️ Gagal ambil data: {e}")
        return
    if not facts.get("dex") and not facts.get("rug"):
        await update.message.reply_text(
            "Token tidak ditemukan di DexScreener/RugCheck. Pastikan address-nya benar."
        )
        return
    prompt = (
        DEEP_RESEARCH_INSTRUCTION
        + "\n\nDATA:\n"
        + json.dumps(facts, indent=2, ensure_ascii=False, default=str)
    )
    try:
        text = await _ask_gemini([gemini.user_msg(prompt)])
    except Exception as e:  # noqa: BLE001
        logger.exception("Deep research error")
        await update.message.reply_text(f"⚠️ Error saat analisa: {e}")
        return
    dex_url = (facts.get("dex") or {}).get("url")
    if dex_url:
        text += f"\n\n🔗 Chart: {dex_url}"
    await _reply_long(update, text)


# ----------------------------------------------------------------------------
# Coding & Reasoning
# ----------------------------------------------------------------------------
async def code_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text("Format: /code <deskripsi program>\nContoh: /code REST API todo list pakai FastAPI")
        return
    task = " ".join(context.args)
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
    prompt = (
        "Tugas coding. Tulis kode LENGKAP dan siap jalan untuk permintaan berikut. "
        "Pilih bahasa/framework paling sesuai (sebutkan pilihanmu), sertakan penanganan error "
        "dan cara pakai singkat. Beri kode dalam code block.\n\n"
        f"Permintaan: {task}"
    )
    try:
        text = await _ask_gemini([gemini.user_msg(prompt)])
    except Exception as e:  # noqa: BLE001
        await update.message.reply_text(f"⚠️ Error: {e}")
        return
    await _reply_long(update, text)


async def reason_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text("Format: /reason <masalah/pertanyaan sulit>")
        return
    problem = " ".join(context.args)
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
    prompt = (
        "Selesaikan dengan reasoning mendalam: pikirkan langkah demi langkah, pertimbangkan beberapa "
        "kemungkinan/hipotesis, uji asumsi, waspadai jebakan logika, lalu beri KESIMPULAN yang jelas "
        "dan bisa ditindaklanjuti di akhir.\n\n"
        f"Masalah: {problem}"
    )
    try:
        text = await _ask_gemini([gemini.user_msg(prompt)])
    except Exception as e:  # noqa: BLE001
        await update.message.reply_text(f"⚠️ Error: {e}")
        return
    await _reply_long(update, text)


# ----------------------------------------------------------------------------
# Web & social research
# ----------------------------------------------------------------------------
async def research_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text("Format: /research <topik/pertanyaan>")
        return
    query = " ".join(context.args)
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
    await update.message.reply_text("🔎 Meneliti web...")
    try:
        results = await research.web_search(query, 6)
    except Exception as e:  # noqa: BLE001
        await update.message.reply_text(f"⚠️ Gagal cari: {e}")
        return
    if not results:
        await update.message.reply_text("Tidak ada hasil pencarian.")
        return
    src = "\n\n".join(
        f"[{i+1}] {r['title']} — {r['url']}\n{r['snippet']}" for i, r in enumerate(results)
    )
    prompt = (
        "Berdasarkan hasil pencarian web berikut, jawab pertanyaan user secara akurat dan ringkas. "
        "Rujuk sumber dengan nomor [n]. Jika info tidak cukup, katakan terus terang.\n\n"
        f"Pertanyaan: {query}\n\nHASIL:\n{src}"
    )
    try:
        text = await _ask_gemini([gemini.user_msg(prompt)])
    except Exception as e:  # noqa: BLE001
        await update.message.reply_text(f"⚠️ Error: {e}")
        return
    text += "\n\n*Sumber:*\n" + "\n".join(f"[{i+1}] {r['url']}" for i, r in enumerate(results))
    await _reply_long(update, text)


async def social_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text(
            "Format: /social [x|reddit|linkedin|facebook|all] <topik>\n"
            "Contoh: /social x sentimen bonk"
        )
        return
    args = list(context.args)
    known = {"x", "twitter", "reddit", "linkedin", "facebook", "all"}
    if args[0].lower() in known:
        plat = args[0].lower()
        query = " ".join(args[1:])
    else:
        plat = "all"
        query = " ".join(args)
    if not query:
        await update.message.reply_text("Tambahkan topik yang mau diriset.")
        return

    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
    await update.message.reply_text(f"🔎 Riset sosmed ({plat})...")

    targets = ["x", "reddit", "linkedin", "facebook"] if plat == "all" else [
        "x" if plat == "twitter" else plat
    ]
    gathered: dict[str, list] = {}
    for t in targets:
        try:
            if t == "reddit":
                rd = await research.reddit_search(query, 5)
                if rd is None:  # IP diblokir -> pakai search biasa
                    rd = await research.social_search("reddit", query, 5)
                    gathered["reddit"] = [
                        {"title": x["title"], "url": x["url"], "snippet": x["snippet"]} for x in rd
                    ]
                else:
                    gathered["reddit"] = [
                        {
                            "title": x["title"],
                            "url": x["url"],
                            "snippet": f"r:{x['sub']} ↑{x['ups']} 💬{x['comments']} {x['text']}",
                        }
                        for x in rd
                    ]
            else:
                gathered[t] = await research.social_search(t, query, 5)
        except Exception:  # noqa: BLE001
            gathered[t] = []

    blocks = []
    for plt, items in gathered.items():
        if not items:
            continue
        blocks.append(f"### {plt.upper()}")
        for it in items:
            blocks.append(f"- {it['title']} — {it['url']}\n  {it.get('snippet', '')}")
    if not blocks:
        await update.message.reply_text("Tidak ada hasil dari sumber sosial.")
        return
    ctx = "\n".join(blocks)
    prompt = (
        "Kamu analis media sosial. Berdasarkan hasil dari berbagai platform berikut, rangkum: "
        "(1) sentimen umum, (2) narasi/poin yang sering muncul, (3) sinyal penting. "
        "Sebutkan platform & sumber [url]. Jangan mengarang; kalau data tipis, katakan.\n\n"
        f"Topik: {query}\n\n{ctx}"
    )
    try:
        text = await _ask_gemini([gemini.user_msg(prompt)])
    except Exception as e:  # noqa: BLE001
        await update.message.reply_text(f"⚠️ Error: {e}")
        return
    await _reply_long(update, text)


# ----------------------------------------------------------------------------
# New pairs scanner (refresh tiap 5 detik) — GeckoTerminal
# ----------------------------------------------------------------------------
def _fmt_pair(p: dict) -> str:
    line = (
        f"🚨 *NEW PAIR* — {p.get('name')}\n"
        f"`{p.get('address')}`\n"
        f"💧 Liq: {crypto.fmt_big(p.get('liq'))} | FDV: {crypto.fmt_big(p.get('fdv'))} | "
        f"Vol5m: {crypto.fmt_big(p.get('vol_m5'))}\n"
    )
    if p.get("address"):
        line += f"🔎 /analyze {p['address']}"
    return line


async def _scan_loop(context: ContextTypes.DEFAULT_TYPE, chat_id: int) -> None:
    seen: set[str] = set()
    first = True
    try:
        while True:
            try:
                pairs = await crypto.new_pairs(limit=15)
            except Exception:  # noqa: BLE001
                await asyncio.sleep(5)
                continue
            new = [p for p in pairs if p.get("id") and p["id"] not in seen]
            for p in pairs:
                if p.get("id"):
                    seen.add(p["id"])
            if first:
                first = False
                await context.bot.send_message(
                    chat_id, "🟢 Scanner new pairs aktif (refresh 5 detik). Contoh terbaru:"
                )
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


async def scan(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    if chat_id in scan_tasks and not scan_tasks[chat_id].done():
        await update.message.reply_text("Scanner sudah jalan. /stopscan untuk berhenti.")
        return
    scan_tasks[chat_id] = context.application.create_task(_scan_loop(context, chat_id))
    await update.message.reply_text(
        "🔍 Memulai scanner new pairs Solana (refresh 5 detik).\n"
        "Catatan: GMGN memblokir bot, jadi dipakai GeckoTerminal (data new pairs sama).\n"
        "Berhenti dengan /stopscan."
    )


async def stopscan(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    t = scan_tasks.pop(chat_id, None)
    if t and not t.done():
        t.cancel()
        await update.message.reply_text("🛑 Scanner dihentikan.")
    else:
        await update.message.reply_text("Tidak ada scanner yang berjalan.")


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
        reasons = {
            "timeout": "waktu habis",
            "expired_token": "kode kadaluarsa",
            "access_denied": "akses ditolak",
        }
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
    context.application.create_task(
        _finish_login(context, update.effective_chat.id, user_id, device)
    )


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
        await update.message.reply_text(
            f"⚠️ Token tidak valid lagi ({e}). Coba /logout lalu /login ulang."
        )
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
    app.add_handler(CommandHandler("price", price))
    app.add_handler(CommandHandler("new", new_meme))
    app.add_handler(CommandHandler("rug", rug))
    app.add_handler(CommandHandler("analyze", analyze))
    app.add_handler(CommandHandler("scan", scan))
    app.add_handler(CommandHandler("stopscan", stopscan))
    app.add_handler(CommandHandler("code", code_cmd))
    app.add_handler(CommandHandler("reason", reason_cmd))
    app.add_handler(CommandHandler("research", research_cmd))
    app.add_handler(CommandHandler("social", social_cmd))
    app.add_handler(CommandHandler("login", login))
    app.add_handler(CommandHandler("logout", logout))
    app.add_handler(CommandHandler("github", github_cmd))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, chat))

    logger.info("ai-agent-v2 berjalan. Tekan Ctrl+C untuk berhenti.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
