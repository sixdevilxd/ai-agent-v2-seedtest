# ai-agent-v2 🤖

AI agent Telegram bertenaga **Google Gemini**, dirancang untuk berjalan di **Termux** (Android) atau server mana pun.

## Fitur
- Balas pesan Telegram pakai Gemini
- Ingat konteks percakapan per chat
- Perintah `/start`, `/help`, `/reset`
- Konfigurasi lewat file `.env` (aman, tidak ikut ter-commit)
- **Skill "Fable 5" (lite)**: kepribadian & disiplin kerja agent diatur lewat `system_prompt.md`
  (jawab langsung, ringkas, ambil inisiatif, ikut bahasa pengguna). Bisa ditimpa lewat env `SYSTEM_PROMPT`.

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

## Isi file `.env`
```ini
TELEGRAM_BOT_TOKEN=123456:ABC-token-dari-botfather
GEMINI_API_KEY=AIza...key-dari-ai-studio
GEMINI_MODEL=gemini-1.5-flash        # opsional
SYSTEM_PROMPT=Kamu adalah ai-agent-v2 # opsional
MAX_HISTORY_TURNS=12                   # opsional
```

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
