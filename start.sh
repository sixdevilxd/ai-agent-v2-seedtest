#!/data/data/com.termux/files/usr/bin/bash
# Skrip cepat untuk menjalankan ai-agent-v2 di Termux.
set -e

cd "$(dirname "$0")"

# Buat & aktifkan virtualenv jika belum ada
if [ ! -d ".venv" ]; then
  echo "Membuat virtualenv..."
  python -m venv .venv
fi
source .venv/bin/activate

echo "Menginstall dependensi..."
pip install -q --upgrade pip
pip install -q -r requirements.txt

if [ ! -f ".env" ]; then
  echo "PERINGATAN: file .env belum ada. Salin .env.example -> .env dan isi tokennya."
  exit 1
fi

echo "Menjalankan ai-agent-v2..."
python bot.py
