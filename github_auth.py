"""
github_auth.py — hubungkan akun GitHub ke bot Telegram lewat OAuth Device Flow.

Kenapa Device Flow?
- Cocok untuk bot/CLI: user cukup buka link GitHub & masukkan kode, TANPA
  paste token ke chat, dan TANPA perlu web server / callback URL.
- Hanya butuh CLIENT_ID (public), tidak butuh client secret.

Setup (sekali saja):
  1. Buat OAuth App di https://github.com/settings/developers
     -> "New OAuth App". Homepage URL bebas (mis. https://github.com/username).
     Authorization callback URL boleh diisi sembarang (device flow tidak memakainya).
  2. Di halaman app, aktifkan "Enable Device Flow".
  3. Salin Client ID, taruh di .env: GITHUB_CLIENT_ID=...

Token per Telegram user disimpan di gh_tokens.json (JANGAN di-commit; sudah di .gitignore).
"""

from __future__ import annotations

import os
import json
import time
import asyncio

import httpx

DEVICE_CODE_URL = "https://github.com/login/device/code"
TOKEN_URL = "https://github.com/login/oauth/access_token"
API = "https://api.github.com"

TOKENS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "gh_tokens.json")
DEFAULT_SCOPE = "repo read:user"


# ---------------------------------------------------------------------------
# Penyimpanan token (lokal, per Telegram user_id)
# ---------------------------------------------------------------------------
def _load() -> dict:
    if os.path.exists(TOKENS_FILE):
        try:
            with open(TOKENS_FILE, encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def _save(data: dict) -> None:
    with open(TOKENS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f)
    try:
        os.chmod(TOKENS_FILE, 0o600)  # hanya owner yang bisa baca
    except OSError:
        pass


def get_token(user_id: int | str) -> str | None:
    return _load().get(str(user_id))


def set_token(user_id: int | str, token: str) -> None:
    data = _load()
    data[str(user_id)] = token
    _save(data)


def remove_token(user_id: int | str) -> bool:
    data = _load()
    existed = data.pop(str(user_id), None) is not None
    _save(data)
    return existed


# ---------------------------------------------------------------------------
# OAuth Device Flow
# ---------------------------------------------------------------------------
async def start_device_flow(client_id: str, scope: str = DEFAULT_SCOPE) -> dict:
    """Minta device_code + user_code ke GitHub."""
    async with httpx.AsyncClient(timeout=20, headers={"Accept": "application/json"}) as c:
        r = await c.post(DEVICE_CODE_URL, data={"client_id": client_id, "scope": scope})
        r.raise_for_status()
        return r.json()


async def poll_for_token(client_id: str, device_code: str, interval: int, expires_in: int) -> dict:
    """Poll GitHub sampai user mengizinkan (atau timeout)."""
    deadline = time.time() + expires_in
    wait = max(interval, 5)
    async with httpx.AsyncClient(timeout=20, headers={"Accept": "application/json"}) as c:
        while time.time() < deadline:
            await asyncio.sleep(wait)
            r = await c.post(
                TOKEN_URL,
                data={
                    "client_id": client_id,
                    "device_code": device_code,
                    "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                },
            )
            j = r.json()
            if j.get("access_token"):
                return {"ok": True, "token": j["access_token"]}
            err = j.get("error")
            if err == "authorization_pending":
                continue
            if err == "slow_down":
                wait += int(j.get("interval", 5))
                continue
            if err in ("expired_token", "access_denied", "unsupported_grant_type"):
                return {"ok": False, "error": err}
            # error lain
            return {"ok": False, "error": err or "unknown"}
    return {"ok": False, "error": "timeout"}


async def get_github_user(token: str) -> dict:
    async with httpx.AsyncClient(
        timeout=20,
        headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
    ) as c:
        r = await c.get(f"{API}/user")
        r.raise_for_status()
        return r.json()
