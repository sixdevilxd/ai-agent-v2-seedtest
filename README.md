# ai-agent-v2 🤖

AI agent Telegram bertenaga **Google Gemini**, dirancang untuk berjalan di **Termux** (Android) atau server mana pun.

## Fitur
- Balas pesan Telegram pakai Gemini, ingat konteks percakapan per chat
- Konfigurasi lewat file `.env` (aman, tidak ikut ter-commit)
- **Semua skill dijalankan lewat bahasa natural (function calling)** — nggak perlu command.
  AI otomatis memanggil tool yang tepat berdasarkan permintaanmu:
  - **Crypto realtime** — "harga solana berapa?"
  - **Deep Research meme coin** (narasi, potensi hype, rug check, anti-whale) — "analisa coin ini `<address>`"
  - **Rug check + sebaran holder** (Solana) — "rugcheck `<mint>`"
  - **New pairs** — "ada token baru launch apa?"
  - **Scanner new pairs tiap 5 detik** — "pantau new pairs tiap 5 detik" / "stop scan"
    (pakai GeckoTerminal; GMGN diblokir Cloudflare untuk bot)
  - **Riset web** — "cari berita terbaru soal ..."
  - **Riset sosmed** (X/Reddit/LinkedIn/Facebook) — "cari sentimen X soal bonk"
  - **Coding semua bahasa** — "buatin script Python untuk ..."
  - **Reasoning mendalam** — "jelasin dengan reasoning ..."
- **Skill "Fable 5" (lite) + skills di atas** diatur lewat `system_prompt.md`
  (jawab langsung, ringkas, ambil inisiatif, pakai tool untuk data faktual, ikut bahasa pengguna).
  Bisa ditimpa lewat env `SYSTEM_PROMPT`.
- **Command dasar**: `/start`, `/help`, `/reset`
- **Login GitHub** (OAuth Device Flow, tanpa paste token):
  - `/login` — hubungkan akun GitHub ke bot (buka link + masukkan kode)
  - `/github` — lihat akun GitHub yang terhubung
  - `/logout` — putuskan koneksi GitHub

## Yang dibutuhkan
1. **Token bot Telegram** — buat lewat [@BotFather](https://t.me/BotFather) (`/newbot`).
2. **API key Gemini** — ambil di [Google AI Studio](https://aistudio.google.com/app/apikey) (ada tier gratis).

## Cara install di Termux

```bash
# 1. Install paket dasar
pkg update -y && pkg upgrade -y
pkg install -y python git

# 2. Clone repo ini
git clone https://github.com/sixdevilxd/ai-agent-v2.git
cd ai-agent-v2

# 3. Buat file .env dan isi tokennya
cp .env.example .env
nano .env      # isi TELEGRAM_BOT_TOKEN dan GEMINI_API_KEY

# 4. Jalankan (otomatis buat virtualenv + install dependensi)
bash start.sh
```



### Menjalankan manual (tanpa start.sh)
```bash
pip install -r requirements.txt
python bot.py
```

> Semua dependensi **pure-Python** (python-telegram-bot, python-dotenv, httpx). Gemini dipanggil via REST API, jadi **tidak butuh Rust/kompilasi** — aman untuk Termux/Android.

## Isi file `.env`
```ini
TELEGRAM_BOT_TOKEN=123456:ABC-token-dari-botfather
GEMINI_API_KEY=AIza...key-dari-ai-studio
GEMINI_MODEL=gemini-1.5-flash        # opsional
SYSTEM_PROMPT=Kamu adalah ai-agent-v2 # opsional
MAX_HISTORY_TURNS=12                   # opsional
```

## Setup fitur `/login` GitHub (opsional)
1. Buka https://github.com/settings/developers → **New OAuth App**.
   - Homepage URL: bebas (mis. `https://github.com/username`)
   - Callback URL: boleh diisi sembarang (device flow tidak memakainya)
2. Buka app-nya, centang **Enable Device Flow**.
3. Salin **Client ID**, taruh di `.env`:
   ```ini
   GITHUB_CLIENT_ID=Iv1.xxxxxxxx
   ```
4. Di Telegram: `/login` → buka link yang muncul → masukkan kode. Selesai.

Token per user disimpan lokal di `gh_tokens.json` (sudah masuk `.gitignore`, tidak ikut ter-commit). Putuskan kapan saja dengan `/logout`.

## Biar tetap jalan di background (Termux)
```bash
pkg install -y tmux
tmux new -s aiagent
bash start.sh
# tekan Ctrl+B lalu D untuk keluar tanpa mematikan bot
# tmux attach -t aiagent  # untuk masuk lagi
```

## Keamanan
- File `.env` **tidak** ikut ter-push (sudah ada di `.gitignore`).
- Jangan pernah membagikan token/API key-mu ke publik.

---
Dibuat otomatis. Selamat ngobrol dengan agent-mu! 🚀
